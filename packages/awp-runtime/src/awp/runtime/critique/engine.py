"""CritiqueEngine — orchestrates structured critique, targeted repair, and pattern learning.

The engine sits between worker execution and the manager's next decision,
providing a fast feedback loop that can fix small defects without a full
manager round-trip.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from .models import CritiqueEnvelope, Defect, PatternMemory, RepairAttempt

if TYPE_CHECKING:
    from awp.models.orchestration import CritiqueConfig

    from ..llm import LLMClient

logger = logging.getLogger(__name__)

# Default defect categories for the critic prompt
_DEFAULT_CATEGORIES = [
    "missing_data",
    "wrong_format",
    "incomplete",
    "hallucinated",
    "stale",
    "policy_violation",
]


class CritiqueEngine:
    """Orchestrates the Reflective Critique Loop.

    Lifecycle within one delegation loop iteration:
    1. ``critique_results()`` — critique all worker results (parallel-safe)
    2. ``repair_if_needed()`` — run targeted repair cycles for critical defects
    3. ``inject_patterns()`` — enrich next worker skills with learned patterns
    """

    def __init__(
        self,
        config: "CritiqueConfig",
        workflow_dir: Path,
        run_id: str,
        worker_model: str = "",
        llm_client: Optional["LLMClient"] = None,
        max_parallel_workers: int = 16,
    ) -> None:
        self._config = config
        self._workflow_dir = workflow_dir
        self._run_id = run_id
        self._worker_model = worker_model
        self._llm_client = llm_client
        self._max_parallel_workers = max_parallel_workers
        self._pattern_memory = PatternMemory()
        self._repair_history: list[RepairAttempt] = []
        self._total_repair_tokens = 0

    @property
    def enabled(self) -> bool:
        return self._config.enabled

    @property
    def pattern_memory(self) -> PatternMemory:
        return self._pattern_memory

    @property
    def repair_history(self) -> list[RepairAttempt]:
        return self._repair_history

    # -- Public API -----------------------------------------------------------

    def critique_result(
        self,
        worker_id: str,
        worker_result: dict[str, Any],
        task: str,
        envelope: dict[str, Any],
        iteration: int,
    ) -> CritiqueEnvelope:
        """Critique a single worker result. Returns structured feedback."""
        if not self._config.enabled:
            # Pass-through: no critique, perfect score
            return CritiqueEnvelope(worker_id=worker_id, score=1.0, summary="Critique disabled")

        return self._run_critique(worker_id, worker_result, task, envelope, iteration)

    def critique_results(
        self,
        delegation_results: list[dict[str, Any]],
        task: str,
        iteration: int,
    ) -> list[CritiqueEnvelope]:
        """Critique all worker results from an iteration (parallel)."""
        from concurrent.futures import ThreadPoolExecutor, as_completed

        # Build work items preserving original order
        work = []
        for i, dr in enumerate(delegation_results):
            wid = dr.get("worker_id", "unknown")
            result = dr.get("result", {})
            envelope = dr.get("envelope", {})
            work.append((i, wid, result, envelope))

        # Execute critiques in parallel (LLM calls are I/O-bound)
        results_map: dict[int, CritiqueEnvelope] = {}
        max_threads = min(len(work), self._max_parallel_workers)
        with ThreadPoolExecutor(max_workers=max_threads) as pool:
            futures = {
                pool.submit(self.critique_result, wid, result, task, envelope, iteration): idx
                for idx, wid, result, envelope in work
            }
            for future in as_completed(futures):
                idx = futures[future]
                results_map[idx] = future.result()

        # Reassemble in original order
        envelopes = [results_map[i] for i in range(len(work))]

        # Record patterns (sequential — mutates shared state).
        # We record TWO sources so pattern memory actually accumulates:
        #   1. Explicit reusable_patterns the critic returned.
        #   2. Every critical/warning defect itself (the critic almost
        #      never populates reusable_patterns, so without this the
        #      pattern memory stays empty across the entire run and the
        #      manager prompt never learns from earlier failures — the
        #      exact pathology observed when workers were renamed and the
        #      same bug recurred 4× in a row).
        if self._config.pattern_memory:
            for critique in envelopes:
                for pattern_desc in critique.reusable_patterns:
                    cat = critique.defects[0].category if critique.defects else "generic"
                    self._pattern_memory.record(
                        category=cat,
                        description=pattern_desc,
                        prevention_rule=pattern_desc,
                        iteration=iteration,
                    )
                for d in critique.defects:
                    if d.severity not in ("critical", "warning"):
                        continue
                    rule = f"[{d.category}] {d.description}".strip()
                    if not rule:
                        continue
                    self._pattern_memory.record(
                        category=d.category or "generic",
                        description=rule,
                        prevention_rule=rule,
                        iteration=iteration,
                    )
        return envelopes

    def attempt_repair(
        self,
        worker_id: str,
        worker_result: dict[str, Any],
        critique: CritiqueEnvelope,
        task: str,
        envelope: dict[str, Any],
        run_worker_fn: Any,  # callable(instructions, state, envelope) -> result
        budget_checker: Any,  # callable() -> (bool, str)
        iteration: int,
    ) -> tuple[dict[str, Any], list[RepairAttempt]]:
        """Run targeted repair cycles for a worker with critical defects.

        Returns the (possibly improved) result and list of repair attempts.
        """
        if not critique.has_critical_defects:
            return worker_result, []

        max_attempts = self._config.max_repair_attempts
        attempts: list[RepairAttempt] = []
        current_result = worker_result
        current_critique = critique

        for attempt_num in range(1, max_attempts + 1):
            # Budget check
            can_go, reason = budget_checker()
            if not can_go:
                logger.warning("Repair budget exhausted for %s: %s", worker_id, reason)
                break

            if not current_critique.has_critical_defects:
                break

            logger.info(
                "  Repair attempt %d/%d for %s (%d critical defects)",
                attempt_num,
                max_attempts,
                worker_id,
                current_critique.critical_count,
            )

            # Build repair instructions
            repair_instructions = self._build_repair_prompt(
                current_result, current_critique, envelope
            )

            # Run worker with repair instructions
            repair_envelope = dict(envelope)
            repair_envelope["instructions"] = repair_instructions
            repair_envelope["_repair_attempt"] = attempt_num
            repair_envelope["_original_critique"] = current_critique.to_dict()

            try:
                repaired_result = run_worker_fn(repair_envelope, task)
            except Exception as exc:
                logger.error("Repair worker failed: %s", exc)
                break

            # Re-critique the repaired result
            new_critique = self._run_critique(worker_id, repaired_result, task, envelope, iteration)

            attempt = RepairAttempt(
                worker_id=worker_id,
                attempt=attempt_num,
                original_score=current_critique.score,
                repaired_score=new_critique.score,
                defects_fixed=current_critique.critical_count - new_critique.critical_count,
                defects_remaining=new_critique.critical_count,
                critique_before=current_critique,
                critique_after=new_critique,
            )
            attempts.append(attempt)
            self._repair_history.append(attempt)

            # Use repaired result if it's better
            if new_critique.score >= current_critique.score:
                current_result = repaired_result
                current_critique = new_critique
            else:
                logger.warning(
                    "Repair attempt %d made %s worse (%.2f -> %.2f), keeping original",
                    attempt_num,
                    worker_id,
                    current_critique.score,
                    new_critique.score,
                )
                break

        return current_result, attempts

    def build_pattern_pitfalls_section(self) -> str:
        """Build a '## Known Pitfalls' skill section from accumulated patterns."""
        rules = self._pattern_memory.get_prevention_rules()
        if not rules:
            return ""
        lines = ["## Known Pitfalls (from this run)\n"]
        lines.append(
            "These issues were found in previous workers during this run. Avoid repeating them:\n"
        )
        for i, rule in enumerate(rules, 1):
            lines.append(f"{i}. {rule}")
        return "\n".join(lines)

    def get_manager_critique_summary(self, critiques: list[CritiqueEnvelope]) -> str:
        """Build a summary for the manager's next iteration context."""
        if not critiques:
            return ""
        lines = ["## Critique Summary\n"]
        for c in critiques:
            status = "PASS" if not c.has_critical_defects else "NEEDS REPAIR"
            lines.append(
                f"- **{c.worker_id}**: score={c.score:.2f} [{status}] "
                f"({c.critical_count} critical, {c.warning_count} warnings)"
            )
            if c.defects:
                for d in c.defects[:3]:  # show top 3 defects
                    icon = (
                        "X" if d.severity == "critical" else "!" if d.severity == "warning" else "i"
                    )
                    lines.append(f"  [{icon}] {d.category}: {d.description}")
            if c.prescriptions:
                lines.append(f"  Prescriptions: {'; '.join(c.prescriptions[:2])}")
        # Pattern summary
        patterns = self._pattern_memory.get_prevention_rules()
        if patterns:
            lines.append("\n### Recurring Patterns")
            for p in patterns[:5]:
                lines.append(f"- {p}")
        # Repair history summary
        if self._repair_history:
            lines.append(f"\n### Repair Attempts: {len(self._repair_history)} total")
            for r in self._repair_history[-3:]:
                lines.append(
                    f"- {r.worker_id} attempt {r.attempt}: "
                    f"{r.original_score:.2f} -> {r.repaired_score:.2f} "
                    f"({r.defects_fixed} fixed, {r.defects_remaining} remaining)"
                )
        return "\n".join(lines)

    def get_summary(self) -> dict[str, Any]:
        """Full summary for logging/artifacts."""
        return {
            "patterns": self._pattern_memory.to_dict(),
            "repair_history": [r.to_dict() for r in self._repair_history],
            "total_repair_tokens": self._total_repair_tokens,
        }

    # -- Internal -------------------------------------------------------------

    def _run_critique(
        self,
        worker_id: str,
        worker_result: dict[str, Any],
        task: str,
        envelope: dict[str, Any],
        iteration: int,
    ) -> CritiqueEnvelope:
        """Run the actual critique via LLM or heuristic fallback."""
        from ..llm import LLMClient

        model = self._config.model or self._worker_model
        llm = self._llm_client or LLMClient(model=model)

        system_prompt = self._build_critic_system_prompt(envelope)
        user_prompt = self._build_critic_user_prompt(worker_id, worker_result, task, envelope)

        try:
            result = llm.chat_json(
                [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.1,
                max_tokens=4096,
            )
            if hasattr(llm, "total_tokens_used"):
                self._total_repair_tokens += llm.total_tokens_used
            envelope_obj = self._parse_critique_response(worker_id, result)
            return self._filter_false_positive_missing_data(envelope_obj)
        except Exception as exc:
            logger.warning("Critique LLM call failed for %s: %s", worker_id, exc)
            return self._heuristic_critique(worker_id, worker_result, envelope)

    def _build_critic_system_prompt(self, envelope: dict[str, Any]) -> str:
        categories = self._config.defect_categories or _DEFAULT_CATEGORIES
        cat_list = ", ".join(categories)
        return f"""You are a Quality Critic in an agent workflow system.

Your job is to diagnose defects in a worker's output and prescribe targeted repairs.

## Defect Categories
{cat_list}

## Severity Levels
- **critical**: Must be fixed before the result can be accepted
- **warning**: Should be improved but not blocking
- **info**: Minor observation, no action needed

## Your Response Format
Respond with a JSON object:
```json
{{
  "score": 0.0-1.0,
  "summary": "one-line quality assessment",
  "defects": [
    {{
      "category": "one of: {cat_list}",
      "location": "where in the output",
      "description": "what is wrong",
      "severity": "critical | warning | info"
    }}
  ],
  "prescriptions": ["specific repair instruction 1", "..."],
  "reusable_patterns": ["pattern that other workers should avoid"],
  "effort_estimate": "trivial | moderate | major"
}}
```

## CRITICAL: Ground-Truth Filesystem Verification
When a "Ground-truth filesystem snapshot" section is provided in the user prompt,
you MUST cross-reference it before flagging any `missing_data` defect.
If a file appears in the snapshot with size > 0 bytes, it EXISTS — do NOT flag it as missing_data.
Flagging an existing file as missing_data is a FALSE POSITIVE and degrades system reliability.

## Rules
- Score 0.9-1.0: Excellent, no critical defects
- Score 0.6-0.89: Acceptable with warnings
- Score 0.3-0.59: Needs repair (critical defects present)
- Score 0.0-0.29: Fundamentally broken
- Be specific in prescriptions — the worker will receive them as repair instructions
- Only flag reusable_patterns if the issue is likely to affect other workers too
- Respond ONLY with JSON, no other text

## Example: Correct handling of ground-truth filesystem data

If the ground-truth snapshot shows:
```
_workspace_dir/  (/tmp/experiment/workspace)
  inputs/repo-a  (15234567 B)
  manifests/report.json  (1234 B)
_output_dir/  (/tmp/experiment/output/run-001)
  summary.json  (567 B)
```

And the worker claims: "Saved report to /tmp/experiment/workspace/manifests/report.json"

CORRECT critique: score=0.85, no missing_data defects (file verified in snapshot)
WRONG critique: score=0.35, missing_data defect for report.json (this is a FALSE POSITIVE)

The filesystem snapshot is AUTHORITATIVE. Trust it over the worker's narrative.
"""

    def _build_critic_user_prompt(
        self,
        worker_id: str,
        worker_result: dict[str, Any],
        task: str,
        envelope: dict[str, Any],
    ) -> str:
        instructions = envelope.get("instructions", "")
        output_contract = envelope.get("output_contract", {})
        result_json = json.dumps(worker_result, indent=2, default=str)
        if len(result_json) > 6000:
            result_json = result_json[:6000] + "\n...(truncated)"

        parts = [
            f"## Original Task\n{task}\n",
            f"## Worker: {worker_id}\n",
            f"## Instructions Given\n{instructions[:2000]}\n",
        ]
        if output_contract:
            parts.append(
                f"## Expected Output Contract\n"
                f"```json\n{json.dumps(output_contract, indent=2)}\n```\n"
            )
        parts.append(f"## Worker Result\n```json\n{result_json}\n```\n")

        # --- Ground-truth filesystem snapshot ---
        # The critic LLM consistently hallucinates "file not saved" defects
        # because it only sees the worker's findings JSON (which often contains
        # an intermediate path) without checking the actual filesystem. Inject
        # a real listing of workspace/ + output/<run>/ so the critic can verify
        # claims against ground truth.
        try:
            ws = self._workflow_dir / "workspace"
            out = self._workflow_dir / "output" / (self._run_id or "")
            tree_lines: list[str] = []
            for base, label in ((ws, "_workspace_dir"), (out, "_output_dir")):
                if base.exists():
                    tree_lines.append(f"{label}/  ({base})")
                    count = 0
                    for p in sorted(base.rglob("*")):
                        if count >= 80:
                            tree_lines.append("  ... (truncated)")
                            break
                        if p.is_file():
                            try:
                                size = p.stat().st_size
                            except OSError:
                                size = 0
                            rel = p.relative_to(base)
                            tree_lines.append(f"  {rel}  ({size} B)")
                            count += 1
            if tree_lines:
                parts.append(
                    "## Ground-truth filesystem snapshot (REAL files on disk)\n"
                    "Verify the worker's claims against this listing. "
                    "If a required file already exists at the expected path with "
                    "non-trivial size, do NOT flag it as `missing_data` even if "
                    "the worker's `findings.path` reports a different path.\n```\n"
                    + "\n".join(tree_lines)
                    + "\n```\n"
                )
        except Exception:
            pass

        # Include known patterns as context
        patterns = self._pattern_memory.get_prevention_rules()
        if patterns:
            parts.append("## Known Failure Patterns (from earlier workers)\n")
            for p in patterns[:5]:
                parts.append(f"- {p}")

        return "\n".join(parts)

    def _build_repair_prompt(
        self,
        worker_result: dict[str, Any],
        critique: CritiqueEnvelope,
        envelope: dict[str, Any],
    ) -> str:
        """Build repair instructions for a worker based on critique feedback."""
        original_instructions = envelope.get("instructions", "")
        # Strip the heavy _tool_calls log out of the result echo (we surface
        # the relevant failure traces separately, below) so the model isn't
        # drowned in noise.
        slim_result = {k: v for k, v in worker_result.items() if k != "_tool_calls"}
        result_json = json.dumps(slim_result, indent=2, default=str)
        if len(result_json) > 4000:
            result_json = result_json[:4000] + "\n...(truncated)"

        # Extract the LAST failing tool_call's stderr + offending code so the
        # repair worker can actually see *why* its previous attempt blew up.
        # Without this it tends to resubmit nearly identical code.
        failure_block = self._extract_failure_evidence(worker_result)

        lines = [
            "## REPAIR MODE — Fix specific defects in your previous output\n",
            "You produced the following output which has quality issues. "
            "Fix ONLY the listed defects. Keep everything else unchanged.\n",
            f"## Your Previous Output\n```json\n{result_json}\n```\n",
        ]
        if failure_block:
            lines.append(failure_block)
        lines.append("## Defects to Fix\n")
        for i, d in enumerate(critique.defects, 1):
            if d.severity in ("critical", "warning"):
                lines.append(
                    f"{i}. [{d.severity.upper()}] **{d.category}** at {d.location}: {d.description}"
                )
        lines.append("\n## Repair Instructions\n")
        for p in critique.prescriptions:
            lines.append(f"- {p}")
        lines.append(
            f"\n## Original Task Instructions (for context)\n{original_instructions[:1500]}"
        )
        return "\n".join(lines)

    # Map stderr substrings → concrete repair hints. Keeps the model from
    # blindly resubmitting the same broken code (the dominant failure mode
    # observed in real runs: pandas indexing, yfinance MultiIndex, lost state).
    _STDERR_HINTS: list[tuple[str, str]] = [
        (
            "cannot do slice indexing on DatetimeIndex",
            "You used a positional/integer slice on a DatetimeIndex via `.loc`. "
            "Use `.iloc[start:stop]` for positional access, or pass actual "
            "Timestamps to `.loc`.",
        ),
        (
            "MultiIndex",
            "yfinance / pandas returned columns as a MultiIndex. Flatten with "
            "`df.columns = df.columns.get_level_values(0)` before selecting.",
        ),
        (
            "NameError",
            "`code.execute` calls do NOT share Python state across calls. "
            "Re-import modules and re-define every helper inside the SAME call, "
            "or persist data to `_workspace_dir` and reload it.",
        ),
        (
            "FileNotFoundError",
            "The file you tried to read does not exist. List `_workspace_dir` "
            "with `os.listdir` first, and only read files that earlier workers "
            "actually wrote.",
        ),
        (
            "KeyError",
            "A column / dict key you referenced does not exist. Print the "
            "available keys (`df.columns.tolist()` / `list(d.keys())`) before "
            "accessing them and adapt to what is actually present.",
        ),
    ]

    def _extract_failure_evidence(self, worker_result: dict[str, Any]) -> str:
        """Pull stderr + offending code from the last failing tool call.

        Returns a markdown block ready to drop into the repair prompt, or "".
        """
        tool_calls = worker_result.get("_tool_calls") or []
        if not isinstance(tool_calls, list):
            return ""

        last_failure: dict[str, Any] | None = None
        for tc in tool_calls:
            if not isinstance(tc, dict):
                continue
            res = tc.get("result") or {}
            data = res.get("data") if isinstance(res, dict) else None
            stderr = ""
            if isinstance(data, dict):
                stderr = data.get("stderr") or ""
            err = res.get("error") if isinstance(res, dict) else None
            if stderr or err:
                last_failure = tc

        if not last_failure:
            return ""

        res = last_failure.get("result") or {}
        data = res.get("data") if isinstance(res, dict) else {}
        stderr = (data or {}).get("stderr", "") if isinstance(data, dict) else ""
        err = res.get("error", "") if isinstance(res, dict) else ""
        args = last_failure.get("arguments") or last_failure.get("args") or {}
        code_snippet = ""
        if isinstance(args, dict):
            code_snippet = args.get("code") or args.get("source") or ""

        # Tail of stderr is the most informative part (final traceback frame)
        stderr_tail = (stderr or err or "")[-1500:]

        hints = []
        for needle, hint in self._STDERR_HINTS:
            if needle in stderr_tail:
                hints.append(f"- {hint}")

        block = ["## Previous Execution Failure (real stderr — diagnose this!)\n"]
        if code_snippet:
            snippet = code_snippet
            if len(snippet) > 1500:
                snippet = snippet[:1500] + "\n...(truncated)"
            block.append(f"### Offending code\n```python\n{snippet}\n```\n")
        if stderr_tail:
            block.append(f"### Stderr / traceback\n```\n{stderr_tail}\n```\n")
        if hints:
            block.append("### Targeted hints\n" + "\n".join(hints) + "\n")
        block.append(
            "Do NOT resubmit the same code. Diagnose the traceback above and "
            "change the specific line(s) it points at.\n"
        )
        return "\n".join(block)

    def _parse_critique_response(self, worker_id: str, response: Any) -> CritiqueEnvelope:
        """Parse the LLM critique response into a CritiqueEnvelope."""
        if isinstance(response, str):
            try:
                response = json.loads(response)
            except json.JSONDecodeError:
                return CritiqueEnvelope(
                    worker_id=worker_id,
                    score=0.5,
                    summary="Failed to parse critique response",
                )

        if not isinstance(response, dict):
            return CritiqueEnvelope(
                worker_id=worker_id,
                score=0.5,
                summary=f"Invalid critique response type: {type(response)}",
            )

        defects = []
        for d in response.get("defects", []):
            if isinstance(d, dict):
                defects.append(
                    Defect(
                        category=d.get("category", "unknown"),
                        location=d.get("location", ""),
                        description=d.get("description", ""),
                        severity=d.get("severity", "info"),
                    )
                )

        score = float(response.get("score", 0.5))
        score = max(0.0, min(1.0, score))

        return CritiqueEnvelope(
            worker_id=worker_id,
            score=score,
            defects=defects,
            prescriptions=response.get("prescriptions", []),
            reusable_patterns=response.get("reusable_patterns", []),
            effort_estimate=response.get("effort_estimate", "trivial"),
            summary=response.get("summary", ""),
        )

    def _filter_false_positive_missing_data(self, critique: CritiqueEnvelope) -> CritiqueEnvelope:
        """Deterministically remove hallucinated missing_data defects.

        After the LLM returns its critique, scan every defect with
        ``category == "missing_data"`` and check whether the file path
        mentioned in ``description`` or ``location`` actually exists on disk
        (workspace/ or output/<run_id>/) with a non-trivial size > 0 bytes.

        If the file exists → downgrade the defect from ``critical`` to ``info``
        and prepend "[FALSE POSITIVE — file exists on disk]" to the description.

        After filtering, recalculate the score upward:
        +0.15 per removed false-positive critical defect, capped at 1.0.
        """
        ws = self._workflow_dir / "workspace"
        out = self._workflow_dir / "output" / (self._run_id or "")

        # Build a flat set of all existing non-empty files in both roots so
        # lookups are O(1) after the initial scan.
        existing: set[str] = set()
        for root in (ws, out):
            if not root.exists():
                continue
            for p in root.rglob("*"):
                if p.is_file():
                    try:
                        if p.stat().st_size > 0:
                            # Store as stem, name, and absolute string for
                            # flexible matching against arbitrary LLM text.
                            existing.add(p.name.lower())
                            existing.add(str(p).lower())
                            existing.add(p.stem.lower())
                            existing.add(str(p.relative_to(root)).lower())
                    except OSError:
                        pass

        if not existing:
            # No files on disk yet — nothing to filter.
            return critique

        removed_critical = 0
        new_defects: list[Defect] = []
        for defect in critique.defects:
            if defect.category != "missing_data" or defect.severity != "critical":
                new_defects.append(defect)
                continue

            # Check if any token from description or location matches a
            # real file on disk (case-insensitive substring / name match).
            combined = f"{defect.description} {defect.location}".lower()
            matched = False
            for entry in existing:
                if entry and entry in combined:
                    matched = True
                    break
            # Also check the reverse: any existing filename appears in the text.
            if not matched:
                for word in combined.split():
                    word_clean = word.strip("\"'/\\,;:()")
                    if word_clean and word_clean in existing:
                        matched = True
                        break

            if matched:
                logger.info(
                    "  [critique-filter] Downgrading false-positive missing_data defect "
                    "for worker '%s': '%s'",
                    critique.worker_id,
                    defect.description[:120],
                )
                new_defects.append(
                    Defect(
                        category=defect.category,
                        location=defect.location,
                        description=f"[FALSE POSITIVE — file exists on disk] {defect.description}",
                        severity="info",
                    )
                )
                removed_critical += 1
            else:
                new_defects.append(defect)

        if removed_critical == 0:
            return critique

        new_score = min(1.0, critique.score + 0.15 * removed_critical)
        logger.info(
            "  [critique-filter] Removed %d false-positive critical defect(s) for '%s'; "
            "score %.2f → %.2f",
            removed_critical,
            critique.worker_id,
            critique.score,
            new_score,
        )
        return CritiqueEnvelope(
            worker_id=critique.worker_id,
            score=new_score,
            defects=new_defects,
            prescriptions=critique.prescriptions,
            reusable_patterns=critique.reusable_patterns,
            effort_estimate=critique.effort_estimate,
            summary=critique.summary,
        )

    def _heuristic_critique(
        self,
        worker_id: str,
        worker_result: dict[str, Any],
        envelope: dict[str, Any],
    ) -> CritiqueEnvelope:
        """Fallback heuristic critique when LLM is unavailable."""
        defects: list[Defect] = []
        score = 1.0

        # Check confidence
        confidence = worker_result.get("confidence")
        if confidence is None:
            defects.append(
                Defect(
                    category="missing_data",
                    location="root.confidence",
                    description="No confidence score in result",
                    severity="critical",
                )
            )
            score -= 0.3
        elif confidence < 0.3:
            defects.append(
                Defect(
                    category="incomplete",
                    location="root.confidence",
                    description=f"Very low confidence: {confidence}",
                    severity="warning",
                )
            )
            score -= 0.2

        # Check for error
        if worker_result.get("error"):
            defects.append(
                Defect(
                    category="incomplete",
                    location="root.error",
                    description=f"Worker returned error: {worker_result['error']}",
                    severity="critical",
                )
            )
            score -= 0.4

        # Check output contract
        output_contract = envelope.get("output_contract", {})
        required_fields = output_contract.get("required_fields", [])
        for field_name in required_fields:
            if field_name not in worker_result:
                defects.append(
                    Defect(
                        category="missing_data",
                        location=f"root.{field_name}",
                        description=f"Required field '{field_name}' missing from output",
                        severity="critical",
                    )
                )
                score -= 0.2

        # Check for empty string values in top-level fields
        for key, value in worker_result.items():
            if key.startswith("_"):
                continue
            if isinstance(value, str) and not value.strip() and key != "error":
                defects.append(
                    Defect(
                        category="incomplete",
                        location=f"root.{key}",
                        description=f"Field '{key}' is empty",
                        severity="warning",
                    )
                )
                score -= 0.1

        score = max(0.0, min(1.0, score))

        prescriptions = []
        for d in defects:
            if d.severity == "critical":
                prescriptions.append(f"Fix: {d.description}")

        effort = "trivial" if len(defects) <= 1 else "moderate" if len(defects) <= 3 else "major"

        return CritiqueEnvelope(
            worker_id=worker_id,
            score=score,
            defects=defects,
            prescriptions=prescriptions,
            effort_estimate=effort,
            summary=f"Heuristic critique: {len(defects)} defects found",
        )
