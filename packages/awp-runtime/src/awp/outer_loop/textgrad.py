"""Text-gradient optimizer for the outer loop (Phase A3).

The :class:`TextGradOptimizer` treats the six prompt artifacts registered
under :mod:`awp.outer_loop.defaults` as the *parameters* of the outer
loop. Given the outcome of one epoch (per-task losses, defect patterns,
gate rejections) it asks an LLM to propose ONE textual update to exactly
ONE artifact, then returns the highest-expected-value proposal as a
:class:`ArtifactUpdate`.

Design invariants
-----------------

* **Deterministic fallback.** Every LLM call is wrapped in
  ``try/except``. A network error, a malformed JSON reply, or a proposal
  that violates one of the hard constraints (wrong artifact name,
  unchanged content, content > 20 000 chars) is silently skipped; the
  candidate simply does not enter the ranking.
* **One artifact per epoch.** The optimiser returns either exactly one
  :class:`ArtifactUpdate` or ``None``. The caller (``SuiteRunner.optimize``)
  is responsible for persisting the new version — the optimiser never
  writes to the registry.
* **Learning rate is informational.** The LRvalue is passed verbatim to
  the LLM prompt as a textual instruction ("at lr=1 you may rewrite the
  entire artifact; at lr=0.2 change only a narrow section"). There is no
  numeric interpolation on the optimiser side — we trust the LLM to
  scale the edit.
* **No real LLM in tests.** The LLM client is injected via constructor
  so tests feed a mock.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from .artifacts import ArtifactRegistry
from .runner import EpochResult

logger = logging.getLogger(__name__)


# Hard constraints that apply to every proposal returned by the LLM.
_MAX_CONTENT_CHARS = 20_000


# The optimiser's own system prompt. This is intentionally NOT a
# learnable artifact — if we ever let the optimiser edit the optimiser's
# own prompt we would need a second-order stabiliser. Keep it in code.
_OPTIMIZER_SYSTEM_PROMPT = """\
You are an AWP outer-loop optimizer. Your job is to propose ONE concrete
textual update to exactly ONE named artifact in the AWP prompt library,
based on observed task losses and defect patterns from a suite of runs.

You will receive:
- The current content of the artifact being considered.
- Aggregated defects and low-score patterns across all tasks in the epoch.
- A learning rate (0..1). At lr=1 you may rewrite the entire artifact;
  at lr=0.2 change only a narrow section. At lr=0.5 rewrite at most one
  logical section (header, list, paragraph).
- The expected output: strict JSON with fields:
  {
    "artifact_name": "<the artifact you chose>",
    "proposed_content": "<full new content of that artifact>",
    "rationale": "<1-2 sentence reasoning>",
    "expected_loss_reduction": 0.0..1.0,
    "confidence": 0.0..1.0
  }

HARD CONSTRAINTS
- Output MUST be valid JSON, with no markdown fence.
- Do not invent new artifact names. Choose from the candidate list.
- Keep the artifact's scope the same (e.g. pitfalls stay pitfalls).
- Prefer additive or refined changes over deletions.
- If no reasonable improvement is available, return JSON with
  `artifact_name: null` and `confidence: 0.0`.
"""


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class ArtifactUpdate:
    """A proposed update to one artifact, with the LLM's self-reported score.

    The outer-loop orchestrator ranks candidates by
    ``expected_loss_reduction * confidence`` and applies only the winner.
    """

    artifact_name: str
    proposed_content: str
    rationale: str
    expected_loss_reduction: float  # 0..1
    confidence: float  # 0..1

    @property
    def score(self) -> float:
        """Ranking key: pure product of the two LLM self-reports."""
        return max(0.0, float(self.expected_loss_reduction)) * max(0.0, float(self.confidence))


# ---------------------------------------------------------------------------
# Defect aggregation
# ---------------------------------------------------------------------------


def _summarise_defects(epoch: EpochResult) -> str:
    """Build a compact, model-friendly summary of the epoch's failure modes.

    The summary is deliberately short (< 2 KB in practice) so every
    candidate call stays cheap. We lean on the raw_signals already
    persisted into each :class:`~awp.outer_loop.loss.LossBreakdown` — no
    extra disk I/O.
    """
    lines: list[str] = []
    lines.append(f"Suite: {epoch.suite_name} — epoch {epoch.epoch_num}")
    lines.append(
        f"Mean loss: {epoch.mean_loss:.4f}" if epoch.mean_loss is not None else "Mean loss: n/a"
    )
    lines.append("")
    lines.append("Per-task outcomes:")
    sorted_results = sorted(epoch.task_results, key=lambda r: -(r.loss or 0.0))
    for r in sorted_results:
        raw = r.breakdown.raw_signals if r.breakdown else {}
        eval_score = raw.get("eval_score")
        critique_score = raw.get("critique_score")
        rejections = raw.get("gate_rejection_count", 0)
        status = r.status or "unknown"
        parts = [
            f"- {r.task_name}",
            f"status={status}",
            f"loss={r.loss:.4f}" if r.loss is not None else "loss=n/a",
        ]
        if isinstance(eval_score, (int, float)):
            parts.append(f"eval={float(eval_score):.3f}")
        if isinstance(critique_score, (int, float)):
            parts.append(f"critique={float(critique_score):.3f}")
        if rejections:
            parts.append(f"gate_rejections={int(rejections)}")
        if r.error:
            # Keep error short — the full trace is not needed for proposals.
            parts.append(f"error={r.error[:160]!r}")
        lines.append(" ".join(parts))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# JSON parsing (lenient)
# ---------------------------------------------------------------------------


def _strip_markdown_fence(text: str) -> str:
    """Remove ```json ... ``` or ``` ... ``` fences if present."""
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    # Drop leading fence line (``` or ```json) and trailing closing fence.
    lines = stripped.splitlines()
    # First line is the opening fence; strip it.
    lines = lines[1:]
    # If the last line is a bare fence, drop it too.
    while lines and lines[-1].strip().startswith("```"):
        lines.pop()
    return "\n".join(lines).strip()


def _parse_proposal_json(raw: str) -> dict[str, Any] | None:
    """Parse a strict-ish JSON object from the LLM's reply.

    Accepts a bare JSON object, or a JSON object wrapped in a markdown
    fence. Returns ``None`` on any parse failure — the caller treats
    that as "candidate skipped".
    """
    if not raw or not raw.strip():
        return None
    cleaned = _strip_markdown_fence(raw)
    try:
        data = json.loads(cleaned)
    except (json.JSONDecodeError, ValueError):
        # Brace-match fallback for replies with leading prose.
        start = cleaned.find("{")
        if start == -1:
            return None
        depth = 0
        for i in range(start, len(cleaned)):
            if cleaned[i] == "{":
                depth += 1
            elif cleaned[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        data = json.loads(cleaned[start : i + 1])
                        break
                    except (json.JSONDecodeError, ValueError):
                        return None
        else:
            return None
    if not isinstance(data, dict):
        return None
    return data


# ---------------------------------------------------------------------------
# Optimizer
# ---------------------------------------------------------------------------


class TextGradOptimizer:
    """LLM-driven text-gradient optimiser.

    Parameters
    ----------
    llm_client
        Any object exposing ``chat_text(messages, **kwargs) -> str``
        (the signature of :class:`awp.runtime.llm.LLMClient`). Tests
        inject a stub. The optimiser is agnostic to which model/provider
        is used; the caller is responsible for picking the manager model.
    registry
        :class:`ArtifactRegistry` used to fetch current artifact content
        for each candidate.
    """

    def __init__(self, llm_client: Any, registry: ArtifactRegistry) -> None:
        self._llm = llm_client
        self._registry = registry

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def propose_update(
        self,
        epoch_result: EpochResult,
        candidate_artifacts: list[str],
        *,
        learning_rate: float = 0.5,
    ) -> ArtifactUpdate | None:
        """Ask the LLM for one update per candidate, return the best one.

        The optimiser returns ``None`` iff no candidate survives the
        hard constraints — e.g. every task scored perfectly, the LLM
        declined on every candidate, or the LLM client errored out.
        """
        if not candidate_artifacts:
            return None

        defects = _summarise_defects(epoch_result)
        proposals: list[ArtifactUpdate] = []

        for name in candidate_artifacts:
            try:
                current = self._registry.get_active(name)
            except KeyError:
                logger.warning("outer_loop.textgrad.unknown_artifact name=%s", name)
                continue
            update = self._propose_for_artifact(
                name=name,
                current_content=current.content,
                defect_summary=defects,
                learning_rate=learning_rate,
                candidate_names=candidate_artifacts,
            )
            if update is not None:
                proposals.append(update)

        if not proposals:
            return None

        # Highest (expected_loss_reduction * confidence) wins. Ties broken
        # by higher confidence, then artifact name for determinism.
        proposals.sort(
            key=lambda u: (u.score, u.confidence, u.artifact_name),
            reverse=True,
        )
        winner = proposals[0]
        if winner.score <= 0.0:
            # Every candidate returned zero signal → treat as no-op.
            return None
        logger.info(
            "outer_loop.textgrad.winner name=%s score=%.4f confidence=%.2f",
            winner.artifact_name,
            winner.score,
            winner.confidence,
        )
        return winner

    # ------------------------------------------------------------------
    # Single-candidate prompt
    # ------------------------------------------------------------------

    def _propose_for_artifact(
        self,
        *,
        name: str,
        current_content: str,
        defect_summary: str,
        learning_rate: float,
        candidate_names: list[str],
    ) -> ArtifactUpdate | None:
        """Run one LLM call for one candidate artifact.

        Returns ``None`` on LLM error, malformed reply, declined proposal,
        or any hard-constraint violation. The outer-loop orchestrator
        treats ``None`` as "skip this candidate".
        """
        user_prompt = self._build_user_prompt(
            name=name,
            current_content=current_content,
            defect_summary=defect_summary,
            learning_rate=learning_rate,
            candidate_names=candidate_names,
        )
        messages = [
            {"role": "system", "content": _OPTIMIZER_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

        try:
            raw = self._llm.chat_text(messages)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "outer_loop.textgrad.llm_failed name=%s error=%s",
                name,
                str(exc)[:200],
            )
            return None

        data = _parse_proposal_json(raw)
        if data is None:
            logger.warning("outer_loop.textgrad.parse_failed name=%s", name)
            return None

        # ``artifact_name: null`` is the explicit "no improvement" signal.
        chosen_name = data.get("artifact_name")
        if chosen_name is None:
            return None
        if not isinstance(chosen_name, str):
            logger.warning("outer_loop.textgrad.invalid_name name=%s got=%r", name, chosen_name)
            return None
        if chosen_name not in candidate_names:
            logger.warning(
                "outer_loop.textgrad.unknown_name got=%s candidates=%s",
                chosen_name,
                candidate_names,
            )
            return None

        proposed_content = data.get("proposed_content")
        if not isinstance(proposed_content, str) or not proposed_content.strip():
            return None
        if len(proposed_content) > _MAX_CONTENT_CHARS:
            logger.warning(
                "outer_loop.textgrad.content_too_long name=%s chars=%d cap=%d",
                chosen_name,
                len(proposed_content),
                _MAX_CONTENT_CHARS,
            )
            return None

        # If the LLM picked a DIFFERENT artifact than the one we sent, we
        # must re-fetch *that* artifact's current content to check for
        # no-op updates correctly.
        try:
            active_for_chosen = self._registry.get_active(chosen_name).content
        except KeyError:
            return None
        if proposed_content == active_for_chosen:
            # No-op update — treat as declined.
            return None

        try:
            expected = float(data.get("expected_loss_reduction", 0.0))
            confidence = float(data.get("confidence", 0.0))
        except (TypeError, ValueError):
            return None
        # Clamp to the documented [0, 1] envelope so a hallucinated 1.5
        # cannot dominate the ranking.
        expected = max(0.0, min(1.0, expected))
        confidence = max(0.0, min(1.0, confidence))

        rationale = data.get("rationale", "")
        if not isinstance(rationale, str):
            rationale = str(rationale)

        return ArtifactUpdate(
            artifact_name=chosen_name,
            proposed_content=proposed_content,
            rationale=rationale,
            expected_loss_reduction=expected,
            confidence=confidence,
        )

    @staticmethod
    def _build_user_prompt(
        *,
        name: str,
        current_content: str,
        defect_summary: str,
        learning_rate: float,
        candidate_names: list[str],
    ) -> str:
        """Format the per-candidate user message."""
        # Cap the artifact content reproduced inside the user message so a
        # huge v0 string cannot blow past the context window. 20 000 is
        # the same cap we enforce on the *output* — symmetric is enough.
        rendered_content = current_content
        if len(rendered_content) > _MAX_CONTENT_CHARS:
            rendered_content = rendered_content[:_MAX_CONTENT_CHARS] + "\n...[truncated]"
        candidate_list = ", ".join(sorted(candidate_names))
        return (
            f"Candidate artifact: {name}\n"
            f"Learning rate: {learning_rate:.2f}\n"
            f"Allowed artifact names: {candidate_list}\n"
            "\n"
            f"---- CURRENT CONTENT OF {name} ----\n"
            f"{rendered_content}\n"
            f"---- END CURRENT CONTENT ----\n"
            "\n"
            "---- EPOCH DEFECT SUMMARY ----\n"
            f"{defect_summary}\n"
            "---- END EPOCH DEFECT SUMMARY ----\n"
            "\n"
            "Respond with the JSON schema described in the system message. "
            "If this artifact is not the best lever for the observed defects, "
            'return {"artifact_name": null, "confidence": 0.0}.'
        )


__all__ = [
    "ArtifactUpdate",
    "TextGradOptimizer",
]
