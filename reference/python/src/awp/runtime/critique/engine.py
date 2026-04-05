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
    ) -> None:
        self._config = config
        self._workflow_dir = workflow_dir
        self._run_id = run_id
        self._worker_model = worker_model
        self._llm_client = llm_client
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
        """Critique all worker results from an iteration."""
        envelopes = []
        for dr in delegation_results:
            wid = dr.get("worker_id", "unknown")
            result = dr.get("result", {})
            envelope = dr.get("envelope", {})
            critique = self.critique_result(wid, result, task, envelope, iteration)
            envelopes.append(critique)
            # Record patterns
            if self._config.pattern_memory:
                for pattern_desc in critique.reusable_patterns:
                    # Extract category from first defect or use generic
                    cat = critique.defects[0].category if critique.defects else "generic"
                    self._pattern_memory.record(
                        category=cat,
                        description=pattern_desc,
                        prevention_rule=pattern_desc,
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
            return self._parse_critique_response(worker_id, result)
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

## Rules
- Score 0.9-1.0: Excellent, no critical defects
- Score 0.6-0.89: Acceptable with warnings
- Score 0.3-0.59: Needs repair (critical defects present)
- Score 0.0-0.29: Fundamentally broken
- Be specific in prescriptions — the worker will receive them as repair instructions
- Only flag reusable_patterns if the issue is likely to affect other workers too
- Respond ONLY with JSON, no other text
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
        result_json = json.dumps(worker_result, indent=2, default=str)
        if len(result_json) > 4000:
            result_json = result_json[:4000] + "\n...(truncated)"

        lines = [
            "## REPAIR MODE — Fix specific defects in your previous output\n",
            "You produced the following output which has quality issues. "
            "Fix ONLY the listed defects. Keep everything else unchanged.\n",
            f"## Your Previous Output\n```json\n{result_json}\n```\n",
            "## Defects to Fix\n",
        ]
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
