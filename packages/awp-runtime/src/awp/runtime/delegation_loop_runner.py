"""AWP Delegation Loop Runner — Dynamic manager-worker orchestration engine.

Implements the ``delegation_loop`` orchestration engine where a manager agent
dynamically generates instructions, skills, and tools for ephemeral worker
agents.  Workers execute in parallel, report back, and the loop continues
until the manager declares completion, a budget limit is hit, or stall
detection triggers.

Key features:
- Manager generates DelegationEnvelopes (instructions + skills + tool config)
- Workers are ephemeral — configured at runtime, no static agent.awp.yaml
- Fan-out: multiple workers per iteration, executed in parallel
- Recursive sub-delegation: workers can become managers within their budget
- Budget system: tokens, workers, wall-time, tool-calls propagate through tree
- Two-tier validation: deterministic checks + LLM semantic validation
- Stall detection: confidence plateau → warn → stop
- Dual logging: JSON (machine) + Markdown (human) on disk
- Rolling summary: recent results in full, older ones summarized

Usage::

    from awp.runtime.delegation_loop_runner import DelegationLoopRunner

    runner = DelegationLoopRunner(
        workflow_dir=Path("my-workflow"),
        config=delegation_loop_config,
        manager_model="openrouter/anthropic/claude-opus-4",
        worker_model="openrouter/anthropic/claude-sonnet-4",
    )
    result = runner.run("Analyze the API performance")
"""

from __future__ import annotations

import importlib.util
import json
import logging
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from awp.models.orchestration import DelegationLoopConfig, DelegationBudget
from .agent import StandaloneAgent
from .context_sharing import (
    ContextBudgetConfig,
    build_input_registry,
    prepare_context,
)
from .critique import CritiqueEngine
from .evaluation import EvaluationEngine
from .llm import LLMClient
from .tools import ToolRegistry

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _find_truncation_points(text: str) -> list[int]:
    """Return candidate truncation offsets for repairing truncated JSON.

    Yields positions just after structural tokens (closing brace/bracket,
    comma after a complete value) — from longest to shortest — so the caller
    can try each until one produces valid JSON.
    """
    points: list[int] = []
    in_str = False
    esc = False
    for i, ch in enumerate(text):
        if esc:
            esc = False
            continue
        if ch == "\\":
            esc = True
            continue
        if ch == '"':
            in_str = not in_str
            if not in_str:
                # End of a string — candidate point right after it
                points.append(i + 1)
            continue
        if in_str:
            continue
        if ch in ("}", "]", ","):
            points.append(i + 1)
    # Reverse so we try longest (most complete) first
    points.reverse()
    return points


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


class BudgetSnapshot:
    """Tracks consumed resources across the entire delegation tree.

    For A4 recursive delegation, a child snapshot can be allocated via
    :meth:`allocate_child`. The child has hard-cap caps that cannot be
    exceeded; on :meth:`reclaim_child` the child's actual usage is folded
    back into the parent so that ungeused budget is freed.
    """

    def __init__(
        self,
        budget: DelegationBudget,
        reservation_config: Any | None = None,
        parent: "BudgetSnapshot | None" = None,
    ) -> None:
        self.max_loops = budget.max_loops
        self.max_total_workers = budget.max_total_workers
        self.max_total_tokens = budget.max_total_tokens
        self.max_wall_time = budget.max_wall_time
        self.max_tool_calls = budget.max_tool_calls
        self.max_depth = budget.max_depth
        # Submanager caps (P2)
        self.max_concurrent_submanagers: int = getattr(
            budget, "max_concurrent_submanagers", 3
        )
        self.max_total_submanagers_per_run: int = getattr(
            budget, "max_total_submanagers_per_run", 6
        )
        # Consumed
        self.loops_used = 0
        self.workers_spawned = 0
        self.tokens_consumed = 0
        self.tool_calls_used = 0
        self.spawned_submanagers_total: int = 0
        self.active_submanagers: int = 0
        self.start_time = time.monotonic()
        # Budget reservation (Manager Intelligence)
        self._reservation = reservation_config
        self._current_phase: str = "core_work"
        self._phase_transitions: list[tuple[int, str]] = [(0, "core_work")]
        # A4 recursive delegation
        self._parent: "BudgetSnapshot | None" = parent
        self._reclaimed: bool = False

    # -- A4: Child allocation -------------------------------------------------

    def allocate_child(
        self,
        fraction: float = 0.3,
        max_depth: int | None = None,
    ) -> "BudgetSnapshot":
        """Allocate a child budget that is a hard-capped subset of this one.

        The child receives a fraction of *currently remaining* parent
        capacity for loops, workers, tokens, tool_calls. The allocated
        amount is **immediately reserved** against the parent (counted as
        consumed) — this prevents three parallel ``allocate_child(0.3)``
        calls from each grabbing 30% of the same base and over-committing
        90% of the budget.

        On :meth:`reclaim_child` the reservation is released and replaced
        with the child's *actual* usage. Unused capacity flows back to the
        parent automatically.

        Wall-time is shared (the child sees the parent's remaining
        wall-time as its hard cap, so the global timeout always wins — no
        child can hang the whole tree).
        """
        fraction = max(0.05, min(0.95, float(fraction)))
        # Compute remaining capacity per dimension
        rem_loops = max(1, self.max_loops - self.loops_used)
        rem_workers = max(1, self.max_total_workers - self.workers_spawned)
        rem_tokens = (
            max(1, self.max_total_tokens - self.tokens_consumed)
            if self.max_total_tokens else 0
        )
        rem_tool_calls = (
            max(1, self.max_tool_calls - self.tool_calls_used)
            if self.max_tool_calls else 0
        )

        # Build a synthetic DelegationBudget for the child
        class _ChildBudget:
            pass
        cb = _ChildBudget()
        cb.max_loops = max(1, int(rem_loops * fraction))
        cb.max_total_workers = max(1, int(rem_workers * fraction))
        cb.max_total_tokens = int(rem_tokens * fraction) if rem_tokens else 0
        # Wall-time: child shares parent's remaining wall-time as hard cap.
        # The global timeout always wins — child cannot outlive the parent.
        cb.max_wall_time = max(1, int(self.wall_time_remaining))
        cb.max_tool_calls = int(rem_tool_calls * fraction) if rem_tool_calls else 0
        cb.max_depth = (
            max_depth if max_depth is not None else max(0, self.max_depth - 1)
        )

        child = BudgetSnapshot(cb, reservation_config=None, parent=self)  # type: ignore[arg-type]
        # Pre-charge the reservation against the parent so concurrent
        # siblings see a smaller "remaining" pool. Stored on the child so
        # reclaim_child knows how much to refund.
        child._reserved_loops = cb.max_loops
        child._reserved_workers = cb.max_total_workers
        child._reserved_tokens = cb.max_total_tokens
        child._reserved_tool_calls = cb.max_tool_calls
        self.loops_used += cb.max_loops
        self.workers_spawned += cb.max_total_workers
        self.tokens_consumed += cb.max_total_tokens
        self.tool_calls_used += cb.max_tool_calls
        # P2: Submanager tracking
        self.spawned_submanagers_total += 1
        self.active_submanagers += 1
        return child

    def reclaim_child(self, child: "BudgetSnapshot") -> None:
        """Release the child's reservation and book its actual usage.

        Net change to the parent equals ``child.actual - child.reserved``,
        which is always ≤ 0 because the child cannot exceed its caps.
        Calling reclaim twice is a no-op so that nested error paths cannot
        double-charge or double-refund.
        """
        if child._reclaimed or child._parent is not self:
            return
        # Release the reservation that was pre-charged at allocate time
        self.loops_used -= getattr(child, "_reserved_loops", 0)
        self.workers_spawned -= getattr(child, "_reserved_workers", 0)
        self.tokens_consumed -= getattr(child, "_reserved_tokens", 0)
        self.tool_calls_used -= getattr(child, "_reserved_tool_calls", 0)
        # Book the child's actual consumption
        self.loops_used += child.loops_used
        self.workers_spawned += child.workers_spawned
        self.tokens_consumed += child.tokens_consumed
        self.tool_calls_used += child.tool_calls_used
        # Clamp to non-negative just in case of edge-case rounding
        self.loops_used = max(0, self.loops_used)
        self.workers_spawned = max(0, self.workers_spawned)
        self.tokens_consumed = max(0, self.tokens_consumed)
        self.tool_calls_used = max(0, self.tool_calls_used)
        # P2: release submanager active slot (total stays for run-wide cap)
        self.active_submanagers = max(0, self.active_submanagers - 1)
        child._reclaimed = True

    @property
    def wall_time_elapsed(self) -> float:
        return time.monotonic() - self.start_time

    @property
    def wall_time_remaining(self) -> float:
        return max(0, self.max_wall_time - self.wall_time_elapsed)

    @property
    def workers_remaining(self) -> int:
        return max(0, self.max_total_workers - self.workers_spawned)

    @property
    def loops_remaining(self) -> int:
        return max(0, self.max_loops - self.loops_used)

    @property
    def budget_fraction_remaining(self) -> float:
        """Fraction of budget remaining (0.0 to 1.0), based on most-consumed resource."""
        fractions = [
            1 - (self.loops_used / max(self.max_loops, 1)),
            1 - (self.workers_spawned / max(self.max_total_workers, 1)),
            1 - (self.wall_time_elapsed / max(self.max_wall_time, 1)),
        ]
        if self.max_total_tokens:
            fractions.append(1 - (self.tokens_consumed / self.max_total_tokens))
        if self.max_tool_calls:
            fractions.append(1 - (self.tool_calls_used / self.max_tool_calls))
        return max(0.0, min(fractions))

    @property
    def current_phase(self) -> str:
        """Name of the active budget phase."""
        return self._current_phase

    def _get_phase_fraction(self, phase_name: str) -> float:
        """Return the budget fraction allocated to *phase_name*."""
        if not self._reservation or not self._reservation.enabled:
            return 1.0
        for p in self._reservation.phases:
            if p.name == phase_name:
                return p.fraction
        return 1.0

    def _cumulative_fraction_through(self, phase_name: str) -> float:
        """Cumulative budget fraction from phase 0 through *phase_name* (inclusive)."""
        if not self._reservation or not self._reservation.enabled:
            return 1.0
        total = 0.0
        for p in self._reservation.phases:
            total += p.fraction
            if p.name == phase_name:
                return total
        return 1.0

    def phase_budget_remaining(self) -> float:
        """Fraction of the current phase's budget that is still available (0.0-1.0)."""
        if not self._reservation or not self._reservation.enabled:
            return self.budget_fraction_remaining
        consumed = 1.0 - self.budget_fraction_remaining
        ceiling = self._cumulative_fraction_through(self._current_phase)
        phase_frac = self._get_phase_fraction(self._current_phase)
        if phase_frac <= 0:
            return 0.0
        floor = ceiling - phase_frac
        phase_consumed = max(0.0, consumed - floor)
        return max(0.0, 1.0 - (phase_consumed / phase_frac))

    def transition_phase(self, phase_name: str, iteration: int) -> None:
        """Move to a new budget phase."""
        self._current_phase = phase_name
        self._phase_transitions.append((iteration, phase_name))

    def phase_warning(self) -> str | None:
        """Return a warning string if < 10% of the current phase budget remains."""
        if not self._reservation or not self._reservation.enabled:
            return None
        remaining = self.phase_budget_remaining()
        if remaining < 0.10:
            return (
                f"Phase '{self._current_phase}' is at {remaining * 100:.0f}% — "
                f"consider transitioning to the next phase"
            )
        return None

    def can_continue(self) -> tuple[bool, str]:
        """Check if the loop can continue within budget."""
        if self.loops_used >= self.max_loops:
            return False, "max_loops reached"
        if self.workers_spawned >= self.max_total_workers:
            return False, "max_total_workers reached"
        if self.wall_time_elapsed >= self.max_wall_time:
            return False, "max_wall_time exceeded"
        if self.max_total_tokens and self.tokens_consumed >= self.max_total_tokens:
            return False, "max_total_tokens reached"
        if self.max_tool_calls and self.tool_calls_used >= self.max_tool_calls:
            return False, "max_tool_calls reached"
        return True, "ok"

    def to_dict(self) -> dict[str, Any]:
        d = {
            "loops": {"used": self.loops_used, "max": self.max_loops},
            "workers": {"spawned": self.workers_spawned, "max": self.max_total_workers},
            "tokens": {"consumed": self.tokens_consumed, "max": self.max_total_tokens},
            "tool_calls": {"used": self.tool_calls_used, "max": self.max_tool_calls},
            "wall_time": {
                "elapsed_s": round(self.wall_time_elapsed, 1),
                "max_s": self.max_wall_time,
            },
            "budget_remaining_pct": round(self.budget_fraction_remaining * 100, 1),
        }
        if self._reservation and self._reservation.enabled:
            d["phase"] = {
                "current": self._current_phase,
                "phase_remaining_pct": round(self.phase_budget_remaining() * 100, 1),
            }
            warning = self.phase_warning()
            if warning:
                d["phase"]["warning"] = warning
        return d


class StallDetector:
    """Detects when the delegation loop makes no meaningful progress.

    Uses two independent signals:
    1. Confidence delta — are confidence scores improving?
    2. Output similarity — are worker results actually changing?

    Both channels must agree before stopping; a single channel triggers a
    warning first.
    """

    def __init__(
        self,
        window: int = 3,
        min_delta: float = 0.05,
        strategy_config: Any | None = None,
    ) -> None:
        self.window = window
        self.min_delta = min_delta
        self._history: list[float] = []
        self._output_history: list[str] = []
        self._warnings = 0
        # Strategy switching (Manager Intelligence)
        self._strategy_config = strategy_config
        self._strategy_pool: list[str] = (
            list(strategy_config.strategies)
            if strategy_config and strategy_config.enabled
            else []
        )
        self._current_strategy_idx: int = 0
        self._active_strategy: str | None = None

    @staticmethod
    def _output_similarity(a: str, b: str) -> float:
        """Compute a cheap similarity ratio between two output strings."""
        if not a and not b:
            return 1.0
        if not a or not b:
            return 0.0
        from difflib import SequenceMatcher

        return SequenceMatcher(None, a[:2000], b[:2000]).ratio()

    def record(self, confidence: float, output_snapshot: str = "") -> str:
        """Record a confidence value and output snapshot.

        Returns 'ok', 'warn', or 'stop'.
        """
        self._history.append(confidence)
        self._output_history.append(output_snapshot)

        if len(self._history) < self.window:
            return "ok"

        # Channel 1: confidence delta
        recent = self._history[-self.window :]
        delta = recent[-1] - recent[0]
        confidence_stalled = abs(delta) < self.min_delta

        # Channel 2: output similarity (compare latest to window-start)
        output_stalled = False
        if len(self._output_history) >= self.window:
            old_out = self._output_history[-self.window]
            new_out = self._output_history[-1]
            if old_out or new_out:
                output_stalled = self._output_similarity(old_out, new_out) > 0.85

        both_stalled = confidence_stalled and output_stalled
        either_stalled = confidence_stalled or output_stalled

        if either_stalled:
            self._warnings += 1
            # Strategy switching: rotate through strategies before stopping
            if self._strategy_pool:
                if self._current_strategy_idx < len(self._strategy_pool):
                    self._active_strategy = self._strategy_pool[self._current_strategy_idx]
                    self._current_strategy_idx += 1
                    self._warnings = 0  # reset warnings for new strategy
                    return "switch_strategy"
                # All strategies exhausted
                return "stop"
            # Both channels agree → stop immediately (was: require 2 warnings)
            if both_stalled:
                return "stop"
            # Only one channel → warn first, stop on second warning
            if self._warnings >= 2:
                return "stop"
            return "warn"

        # Progress detected — reset warnings
        self._warnings = 0
        return "ok"

    @property
    def suggested_strategy(self) -> str | None:
        """The currently active meta-strategy, if any."""
        return self._active_strategy

    @property
    def strategies_exhausted(self) -> bool:
        """True if all strategies have been tried."""
        return bool(self._strategy_pool) and self._current_strategy_idx >= len(
            self._strategy_pool
        )


# ---------------------------------------------------------------------------
# Performance Profiler
# ---------------------------------------------------------------------------


class PerformanceProfiler:
    """Collects timing data for each phase of the delegation loop.

    When ``enabled=True``, records wall-clock durations for manager calls,
    worker execution, critique, logging, and code execution.  Writes a
    ``timing_report.json`` at the end of the run.
    """

    def __init__(self, enabled: bool = False) -> None:
        self.enabled = enabled
        self._events: list[dict[str, Any]] = []
        self._open: dict[str, float] = {}

    def start(self, label: str, **meta: Any) -> None:
        if not self.enabled:
            return
        self._open[label] = time.monotonic()

    def stop(self, label: str, **meta: Any) -> float:
        if not self.enabled or label not in self._open:
            return 0.0
        elapsed = time.monotonic() - self._open.pop(label)
        event: dict[str, Any] = {
            "label": label,
            "duration_s": round(elapsed, 4),
        }
        event.update(meta)
        self._events.append(event)
        return elapsed

    def get_report(self) -> dict[str, Any]:
        """Return structured timing report with per-phase aggregates."""
        if not self._events:
            return {}
        # Aggregate by label prefix (e.g. "manager", "worker", "critique")
        aggregates: dict[str, list[float]] = {}
        for ev in self._events:
            prefix = ev["label"].split(".")[0]
            aggregates.setdefault(prefix, []).append(ev["duration_s"])
        summary = {}
        total = 0.0
        for prefix, durations in sorted(aggregates.items()):
            s = sum(durations)
            total += s
            summary[prefix] = {
                "total_s": round(s, 2),
                "count": len(durations),
                "avg_s": round(s / len(durations), 2),
                "max_s": round(max(durations), 2),
            }
        return {
            "total_profiled_s": round(total, 2),
            "phases": summary,
            "events": self._events,
        }

    def write_report(self, run_dir: Path) -> None:
        """Write timing_report.json to disk."""
        if not self.enabled or not self._events:
            return
        report = self.get_report()
        path = run_dir / "timing_report.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(report, indent=2, default=str, ensure_ascii=False),
            encoding="utf-8",
        )
        # Print summary to log
        logger.info("=== TIMING REPORT ===")
        for phase, data in report.get("phases", {}).items():
            logger.info(
                "  %-20s %6.1fs total  (%d calls, avg %.1fs, max %.1fs)",
                phase,
                data["total_s"],
                data["count"],
                data["avg_s"],
                data["max_s"],
            )
        logger.info("  %-20s %6.1fs", "TOTAL PROFILED", report["total_profiled_s"])


# ---------------------------------------------------------------------------
# Manager Intelligence data structures
# ---------------------------------------------------------------------------


class DecisionJournal:
    """Reflective workspace memory — tracks manager decisions and outcomes.

    Enables the manager to learn from its own decision history within a
    single run by recording what was decided, why, and what happened.
    """

    def __init__(self, max_entries: int = 20) -> None:
        self._entries: list[dict[str, Any]] = []
        self._max = max_entries

    def record(
        self,
        iteration: int,
        decision_type: str,
        rationale: str,
        worker_ids: list[str] | None = None,
    ) -> None:
        """Record a manager decision."""
        entry = {
            "iteration": iteration,
            "decision": decision_type,
            "rationale": rationale,
            "worker_ids": worker_ids or [],
            "outcome": None,
            "lesson": None,
        }
        self._entries.append(entry)
        if len(self._entries) > self._max:
            self._entries.pop(0)

    def record_outcome(self, iteration: int, outcomes: dict[str, float]) -> None:
        """Attach outcomes to the most recent entry matching *iteration*."""
        for entry in reversed(self._entries):
            if entry["iteration"] == iteration:
                entry["outcome"] = outcomes
                # Auto-derive a lesson from confidence trends
                if outcomes:
                    avg_conf = sum(outcomes.values()) / len(outcomes)
                    if avg_conf < 0.3:
                        entry["lesson"] = "Low confidence — consider changing approach"
                    elif avg_conf > 0.8:
                        entry["lesson"] = "High confidence — approach is effective"
                break

    def to_prompt_section(self) -> str:
        """Format journal for injection into the manager prompt."""
        if not self._entries:
            return ""
        lines = ["## Decision Journal (recent decisions and outcomes)\n"]
        for e in self._entries[-10:]:
            outcome_str = ""
            if e["outcome"]:
                confs = [f"{k}={v:.2f}" for k, v in e["outcome"].items()]
                outcome_str = f" → outcomes: {', '.join(confs)}"
            lesson_str = f" | Lesson: {e['lesson']}" if e["lesson"] else ""
            lines.append(
                f"- **Iter {e['iteration']}** [{e['decision']}]: "
                f"{e['rationale']}{outcome_str}{lesson_str}"
            )
        lines.append(
            "\n**Reflection**: Given the pattern of decisions and outcomes above, "
            "what adjustment would improve the next iteration?\n"
        )
        return "\n".join(lines)


class TaskPlan:
    """Explicit task graph created by the manager during the planning phase.

    Tracks subtasks with dependencies, priorities, status, and success
    criteria so the manager can monitor progress across iterations.
    """

    # Maximum iterations on a single subtask before force-completing it
    MAX_SUBTASK_ITERATIONS = 5

    def __init__(self, max_subtasks: int = 10) -> None:
        self._subtasks: list[dict[str, Any]] = []
        self._max = max_subtasks
        # worker_id → subtask_id explicit mapping from delegation envelopes
        self._worker_subtask_map: dict[str, str] = {}
        # subtask_id → number of iterations spent on it
        self._subtask_iterations: dict[str, int] = {}

    def set_subtasks(self, subtasks: list[dict[str, Any]]) -> None:
        """Set the plan from the manager's PLAN decision output."""
        self._subtasks = subtasks[: self._max]
        for st in self._subtasks:
            st.setdefault("status", "pending")
            st.setdefault("result_summary", "")

    def register_worker_mapping(self, worker_id: str, subtask_id: str) -> None:
        """Register an explicit worker_id → subtask_id mapping from a delegation envelope."""
        self._worker_subtask_map[worker_id] = subtask_id

    def _resolve_subtask(self, worker_id: str) -> dict[str, Any] | None:
        """Resolve a worker_id to a subtask, using explicit mapping first, then fuzzy match."""
        # 1. Exact match on subtask id
        for st in self._subtasks:
            if st.get("id") == worker_id:
                return st
        # 2. Explicit mapping from delegation envelope's subtask_id field
        mapped_id = self._worker_subtask_map.get(worker_id)
        if mapped_id:
            for st in self._subtasks:
                if st.get("id") == mapped_id:
                    return st
        # 3. Fuzzy match: find subtask whose id shares significant tokens with worker_id.
        # Strip trailing digits/version suffixes (v2, _3, iter20) for better matching.
        import re
        def _normalize(s: str) -> set[str]:
            s = s.lower().replace("-", "_")
            tokens = set()
            for tok in s.split("_"):
                tok = re.sub(r"\d+$", "", tok)  # strip trailing digits (v2 → v, iter20 → iter)
                tok = re.sub(r"^v$", "", tok)  # drop bare 'v' (version marker)
                if len(tok) >= 3:  # ignore short tokens
                    tokens.add(tok)
            return tokens

        worker_tokens = _normalize(worker_id)
        # Generic tokens that shouldn't count as meaningful overlap
        STOP = {"subtask", "task", "worker", "agent", "step", "phase", "the", "and", "for"}
        worker_tokens -= STOP
        if not worker_tokens:
            return None
        best_match: dict[str, Any] | None = None
        best_score = 0
        for st in self._subtasks:
            if st.get("status") == "completed":
                continue  # don't match against already-completed subtasks
            st_id = st.get("id", "")
            st_tokens = _normalize(st_id) - STOP
            desc_words = re.findall(r"[a-z]+", st.get("description", "").lower())[:30]
            desc_tokens = {w for w in desc_words if len(w) >= 3} - STOP
            overlap = len(worker_tokens & (st_tokens | desc_tokens))
            if overlap > best_score and overlap >= 1:
                best_score = overlap
                best_match = st
        return best_match

    def update_status(
        self, worker_id: str, status: str, result_summary: str = ""
    ) -> None:
        """Update a subtask's status after a worker completes.

        Uses explicit subtask_id mapping, then fuzzy matching if no exact match.
        """
        st = self._resolve_subtask(worker_id)
        if not st:
            return
        st["status"] = status
        if result_summary:
            st["result_summary"] = result_summary

    def record_iteration(self, worker_id: str) -> None:
        """Record that an iteration was spent on the subtask associated with this worker."""
        st = self._resolve_subtask(worker_id)
        if not st:
            return
        st_id = st.get("id", "")
        self._subtask_iterations[st_id] = self._subtask_iterations.get(st_id, 0) + 1

    def get_stuck_subtasks(self) -> list[dict[str, Any]]:
        """Return subtasks that have exceeded MAX_SUBTASK_ITERATIONS without completing."""
        stuck = []
        for st in self._subtasks:
            st_id = st.get("id", "")
            iters = self._subtask_iterations.get(st_id, 0)
            if iters >= self.MAX_SUBTASK_ITERATIONS and st["status"] != "completed":
                stuck.append(st)
        return stuck

    def force_advance_stuck(
        self,
        promote_to_submanager: bool = False,
    ) -> list[str]:
        """Handle stuck subtasks. Two modes:

        - ``promote_to_submanager=False`` (default): force-complete the
          subtask so the loop moves on. Used when recursive delegation is
          not available (depth limit reached, A2/A3 workflow).
        - ``promote_to_submanager=True``: mark the subtask with
          ``delegation_strategy="submanager"`` and reset its iteration
          counter. The next DELEGATE for that subtask will spawn a child
          DelegationLoopRunner with a dedicated budget. Status stays
          ``in_progress`` so the manager keeps working on it.

        Either way the parent loop is guaranteed to make progress: a
        force-completed subtask unblocks dependents; a promoted one gets
        a fresh iteration window with a stronger execution mode.
        """
        advanced = []
        for st in self.get_stuck_subtasks():
            st_id = st.get("id", "")
            if promote_to_submanager and st.get("delegation_strategy") != "submanager":
                st["delegation_strategy"] = "submanager"
                st["status"] = "in_progress"
                st["result_summary"] = (
                    f"[AUTO-PROMOTED to submanager after "
                    f"{self._subtask_iterations.get(st_id, 0)} stuck iterations]"
                )
                # Reset iteration counter so the submanager gets its own window
                self._subtask_iterations[st_id] = 0
                advanced.append(st_id)
            else:
                st["status"] = "completed"
                st["result_summary"] = (
                    f"[AUTO-ADVANCED after {self._subtask_iterations.get(st_id, 0)} "
                    f"iterations — use best available results]"
                )
                advanced.append(st_id)
        return advanced

    def get_next_actionable(self) -> list[dict[str, Any]]:
        """Return subtasks whose dependencies are all completed."""
        completed_ids = {st["id"] for st in self._subtasks if st["status"] == "completed"}
        actionable = []
        for st in self._subtasks:
            if st["status"] != "pending":
                continue
            deps = st.get("dependencies", [])
            if all(d in completed_ids for d in deps):
                actionable.append(st)
        return actionable

    def progress_summary(self) -> str:
        """One-line progress summary."""
        total = len(self._subtasks)
        done = sum(1 for st in self._subtasks if st["status"] == "completed")
        in_prog = sum(1 for st in self._subtasks if st["status"] == "in_progress")
        return f"{done}/{total} completed, {in_prog} in progress"

    def to_prompt_section(self) -> str:
        """Format plan for injection into the manager prompt."""
        if not self._subtasks:
            return ""
        lines = [
            f"## Task Plan Progress ({self.progress_summary()})\n",
            "| ID | Description | Priority | Dependencies | Status | Iterations | Result |",
            "|-----|-------------|----------|--------------|--------|------------|--------|",
        ]
        for st in self._subtasks:
            deps = ", ".join(st.get("dependencies", [])) or "none"
            iters = self._subtask_iterations.get(st.get("id", ""), 0)
            iter_warn = f" ⚠" if iters >= self.MAX_SUBTASK_ITERATIONS - 1 else ""
            lines.append(
                f"| {st.get('id', '?')} | {st.get('description', '')[:60]} "
                f"| {st.get('priority', 'normal')} | {deps} "
                f"| **{st['status']}** | {iters}{iter_warn} "
                f"| {st.get('result_summary', '')[:40]} |"
            )
        actionable = self.get_next_actionable()
        if actionable:
            ids = ", ".join(a["id"] for a in actionable)
            lines.append(f"\n**Next actionable subtasks**: {ids}\n")
        stuck = self.get_stuck_subtasks()
        if stuck:
            ids = ", ".join(s["id"] for s in stuck)
            lines.append(
                f"\n**⚠ STUCK SUBTASKS (>{self.MAX_SUBTASK_ITERATIONS} iterations)**: {ids}\n"
                f"These subtasks will be auto-advanced. Use best available results "
                f"and move to the next subtask.\n"
            )
        return "\n".join(lines)


class RunLogger:
    """Dual-layer logging: structured JSON + human-readable Markdown.

    File writes are dispatched to a background thread so they don't
    block the hot path (manager → worker → critique chain).

    Also maintains a comprehensive debug logging facility under
    ``<experiment>/logs/<run_id>/`` with multiple views (chronological
    debug trace, JSONL event stream, errors-only, manager decisions,
    gate triggers, tool calls). These files are append-mode and
    thread-safe so external tools can tail them while the run is live.
    """

    def __init__(self, run_dir: Path, fmt: str = "dual") -> None:
        self.run_dir = run_dir
        self.fmt = fmt  # "dual" | "json" | "md"
        self.run_dir.mkdir(parents=True, exist_ok=True)
        (self.run_dir / "iterations").mkdir(exist_ok=True)
        (self.run_dir / "history").mkdir(exist_ok=True)
        (self.run_dir / "artifacts" / "skills").mkdir(parents=True, exist_ok=True)
        (self.run_dir / "artifacts" / "tools").mkdir(parents=True, exist_ok=True)
        # Async write queue (daemon thread processes writes in background)
        import queue
        import threading
        self._queue: queue.Queue[tuple | None] = queue.Queue()
        self._writer = threading.Thread(target=self._bg_writer, daemon=True)
        self._writer.start()

        # ----- Debug logging facility ------------------------------------
        # Resolve the experiment directory: standard layout is
        #   <experiment>/workspace/runs/<run_id>/
        # parents[0] = "runs", parents[1] = "workspace", parents[2] = experiment.
        self._debug_dir: Optional[Path] = None
        try:
            resolved = run_dir.resolve()
            parts = list(resolved.parts)
            # Walk up to find ".../<experiment>/workspace/runs/<top_run>/...".
            # Sub-runs are nested arbitrarily deep under
            #   <top_run>/iterations/NNN/delegations/<worker>/runs/<sub_id>/...
            # We extract the experiment dir + the *top-level* run id and route
            # ALL sub-run logs into <experiment>/logs/<top_run>/sub_<rel>/ so
            # that everything for one run is collocated under one tree.
            experiment_dir: Optional[Path] = None
            top_run: Optional[str] = None
            for i in range(len(parts) - 2):
                if parts[i] == "workspace" and parts[i + 1] == "runs":
                    experiment_dir = Path(*parts[:i])
                    top_run = parts[i + 2] if i + 2 < len(parts) else None
                    break
            if experiment_dir and top_run:
                # Is this the top-level run, or a deeper sub-run?
                if resolved.name == top_run and resolved.parent.name == "runs":
                    # Top-level run: <exp>/logs/<top_run>/
                    self._debug_dir = experiment_dir / "logs" / top_run
                else:
                    # Sub-run: build a slug from the path between top_run and
                    # the sub run id so deeply-nested sub-sub-managers stay
                    # uniquely identified.
                    after_top_idx = parts.index(top_run) + 1
                    rel_parts = parts[after_top_idx:]
                    # Compress: keep only delegation worker + sub run id
                    # segments; drop "iterations/NNN/delegations/" noise.
                    compressed: list[str] = []
                    skip_next = 0
                    for j, p in enumerate(rel_parts):
                        if skip_next > 0:
                            skip_next -= 1
                            continue
                        if p in ("iterations", "delegations", "runs"):
                            continue
                        # numeric iter labels
                        if p.isdigit() and len(p) == 3:
                            continue
                        compressed.append(p)
                    slug = "__".join(compressed) or "sub"
                    # Final layout: <exp>/logs/<top_run>/sub_<slug>/
                    self._debug_dir = (
                        experiment_dir / "logs" / top_run / f"sub_{slug}"
                    )
            else:
                # Fallback: put logs alongside the run dir itself
                self._debug_dir = run_dir / "logs"
            self._debug_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            self._debug_dir = None

        self._debug_lock = threading.Lock()
        self._debug_handles: dict[str, Any] = {}
        if self._debug_dir is not None:
            # Open all log files in append mode so the run can resume after
            # a process restart and external tools can tail them live.
            for fname in (
                "debug.log",
                "events.jsonl",
                "errors.log",
                "decisions.log",
                "gates.log",
                "tool_calls.jsonl",
            ):
                try:
                    self._debug_handles[fname] = open(
                        self._debug_dir / fname,
                        "a",
                        encoding="utf-8",
                        buffering=1,  # line-buffered for live tailing
                    )
                except Exception:
                    pass
            # Initial banner so the file isn't empty on first read
            self._debug_write(
                "debug.log",
                f"==== RunLogger initialized for {run_dir.name} at "
                f"{datetime.now(timezone.utc).isoformat()} ====\n",
            )

    # -- Debug log helpers -----------------------------------------------

    def _debug_write(self, fname: str, line: str) -> None:
        """Thread-safe append to a debug log file."""
        h = self._debug_handles.get(fname)
        if h is None:
            return
        try:
            with self._debug_lock:
                h.write(line)
        except Exception:
            pass

    def trace(
        self,
        category: str,
        message: str,
        level: str = "INFO",
        **fields: Any,
    ) -> None:
        """Record a debug trace event.

        Writes to:
          - debug.log    (chronological human-readable line)
          - events.jsonl (structured one-event-per-line JSON)
          - errors.log   (also, if level is WARNING/ERROR/CRITICAL)

        Categories used by the runtime:
          run, iteration, manager, worker, tool, critique, gate, budget,
          delegation, repair, eval, completion
        """
        if self._debug_dir is None:
            return
        ts = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        # Sanitize fields for the human line: keep scalars, truncate long strings
        flat_parts: list[str] = []
        for k, v in fields.items():
            if v is None:
                continue
            if isinstance(v, (str,)):
                vv = v.replace("\n", " ⏎ ")
                if len(vv) > 200:
                    vv = vv[:197] + "..."
                flat_parts.append(f"{k}={vv!r}")
            elif isinstance(v, (int, float, bool)):
                flat_parts.append(f"{k}={v}")
            else:
                # Compact JSON for nested values
                try:
                    j = json.dumps(v, default=str, ensure_ascii=False)
                    if len(j) > 200:
                        j = j[:197] + "..."
                    flat_parts.append(f"{k}={j}")
                except Exception:
                    flat_parts.append(f"{k}=<unrepr>")
        flat = " ".join(flat_parts)
        human = f"{ts} [{level:<8}] [{category:<11}] {message}"
        if flat:
            human += f"  {flat}"
        human += "\n"
        self._debug_write("debug.log", human)

        if level in ("WARNING", "ERROR", "CRITICAL"):
            self._debug_write("errors.log", human)

        try:
            event = {
                "ts": ts,
                "level": level,
                "category": category,
                "msg": message,
                "fields": fields,
            }
            self._debug_write(
                "events.jsonl",
                json.dumps(event, default=str, ensure_ascii=False) + "\n",
            )
        except Exception:
            pass

    def trace_decision(
        self,
        iteration: int,
        decision: str,
        reasoning: str = "",
        confidence: Optional[float] = None,
        delegations: Optional[list] = None,
        depth: int = 0,
    ) -> None:
        """Record a manager decision (also written to decisions.log)."""
        n_deleg = len(delegations) if delegations else 0
        self.trace(
            "manager",
            f"iter {iteration}: {decision.upper()}",
            iteration=iteration,
            depth=depth,
            decision=decision,
            confidence=confidence,
            delegations=n_deleg,
            reasoning=reasoning,
        )
        ts = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        line = (
            f"{ts} iter={iteration:03d} depth={depth} decision={decision} "
            f"conf={confidence} n_deleg={n_deleg}\n"
        )
        if reasoning:
            line += f"  reasoning: {reasoning[:500]}\n"
        if delegations:
            for d in delegations[:10]:
                if isinstance(d, dict):
                    line += f"  → {d.get('worker', d.get('worker_id', '?'))}: {str(d.get('task', ''))[:120]}\n"
        self._debug_write("decisions.log", line)

    def trace_gate(
        self,
        gate_name: str,
        triggered: bool,
        reason: str,
        **fields: Any,
    ) -> None:
        """Record a completion gate firing (critique / placeholder / file / eval)."""
        level = "WARNING" if triggered else "INFO"
        verb = "REJECTED completion" if triggered else "PASSED"
        self.trace(
            "gate",
            f"{gate_name} {verb}: {reason}",
            level=level,
            gate=gate_name,
            triggered=triggered,
            reason=reason,
            **fields,
        )
        ts = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        line = f"{ts} gate={gate_name} triggered={triggered} reason={reason}"
        if fields:
            line += "  " + " ".join(f"{k}={v}" for k, v in fields.items())
        line += "\n"
        self._debug_write("gates.log", line)

    def trace_tool_call(
        self,
        worker_id: str,
        iteration: str,
        tool: str,
        ok: bool,
        duration_ms: Optional[float] = None,
        error: Optional[str] = None,
        arguments: Optional[dict] = None,
    ) -> None:
        """Record a single tool call (tool_calls.jsonl + debug.log)."""
        self.trace(
            "tool",
            f"{tool} {'OK' if ok else 'FAIL'}",
            level="INFO" if ok else "WARNING",
            worker=worker_id,
            iteration=iteration,
            tool=tool,
            ok=ok,
            duration_ms=duration_ms,
            error=(error[:200] if error else None),
        )
        try:
            ts = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
            entry = {
                "ts": ts,
                "worker_id": worker_id,
                "iteration": iteration,
                "tool": tool,
                "ok": ok,
                "duration_ms": duration_ms,
                "error": (error[:500] if error else None),
                "arguments": arguments,
            }
            self._debug_write(
                "tool_calls.jsonl",
                json.dumps(entry, default=str, ensure_ascii=False) + "\n",
            )
        except Exception:
            pass

    def _bg_writer(self) -> None:
        """Background thread that drains the write queue."""
        while True:
            item = self._queue.get()
            if item is None:
                self._queue.task_done()
                break
            path, content = item
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")
            except Exception:
                pass
            finally:
                self._queue.task_done()

    def flush(self) -> None:
        """Wait until all queued writes are flushed to disk."""
        self._queue.join()

    def shutdown(self) -> None:
        """Flush remaining writes and stop the background thread."""
        self._queue.put(None)
        self._writer.join(timeout=5)

    def _enqueue(self, path: Path, content: str) -> None:
        self._queue.put((path, content))

    def write_json(self, path: Path, data: Any) -> None:
        if self.fmt in ("dual", "json"):
            content = json.dumps(data, indent=2, default=str, ensure_ascii=False)
            self._enqueue(path, content)

    def write_md(self, path: Path, content: str) -> None:
        if self.fmt in ("dual", "md"):
            self._enqueue(path, content)

    def _write_file(self, path: Path, content: str) -> None:
        """Write any file (always, regardless of format setting)."""
        self._enqueue(path, content)

    def log_run_start(
        self,
        task: str,
        run_id: str,
        config: DelegationLoopConfig,
        manager_model: str,
        worker_model: str,
    ) -> None:
        manifest = {
            "run_id": run_id,
            "task": task,
            "started": datetime.now(timezone.utc).isoformat(),
            "models": {"manager": manager_model, "worker": worker_model},
            "budget": config.budget.model_dump() if config.budget else {},
        }
        self.write_json(self.run_dir / "run_manifest.json", manifest)
        self.trace(
            "run",
            f"started run {run_id}",
            run_id=run_id,
            manager_model=manager_model,
            worker_model=worker_model,
            task_preview=task[:200],
        )
        md = (
            f"# Run: {run_id}\n"
            f"**Task:** {task}\n"
            f"**Started:** {manifest['started']}\n"
            f"**Models:** Manager={manager_model} | Worker={worker_model}\n\n"
            f"## Budget\n"
            f"| Resource | Max |\n|---|---|\n"
        )
        if config.budget:
            b = config.budget
            md += (
                f"| Loops | {b.max_loops} |\n"
                f"| Workers | {b.max_total_workers} |\n"
                f"| Wall Time | {b.max_wall_time}s |\n"
            )
        self.write_md(self.run_dir / "RUN_SUMMARY.md", md)

    # -- Progressive logging (real-time file writes for watchers) --------

    def log_manager_decision(self, iteration: int, manager_decision: dict) -> None:
        """Write manager_decision.json immediately after manager returns."""
        iter_dir = self.run_dir / "iterations" / f"{iteration:03d}"
        iter_dir.mkdir(parents=True, exist_ok=True)
        self.write_json(iter_dir / "manager_decision.json", manager_decision)
        self.trace_decision(
            iteration=iteration,
            decision=str(manager_decision.get("decision", "?")),
            reasoning=str(manager_decision.get("reasoning", ""))[:1000],
            confidence=manager_decision.get("confidence"),
            delegations=manager_decision.get("delegations") or manager_decision.get("delegate") or [],
            depth=int(manager_decision.get("depth", 0) or 0),
        )

    def log_worker_envelope(
        self, iteration: int, worker_id: str, envelope: dict
    ) -> None:
        """Write envelope.json before worker starts executing."""
        worker_dir = (
            self.run_dir
            / "iterations"
            / f"{iteration:03d}"
            / "delegations"
            / worker_id
        )
        worker_dir.mkdir(parents=True, exist_ok=True)
        self.write_json(worker_dir / "envelope.json", envelope)
        self.trace(
            "worker",
            f"spawn {worker_id}",
            iteration=iteration,
            worker=worker_id,
            tools_allowed=envelope.get("tools_allowed") if isinstance(envelope, dict) else None,
            instructions_preview=str(envelope.get("instructions", "") if isinstance(envelope, dict) else "")[:200],
        )

    def log_worker_result(
        self, iteration: int, worker_id: str, result: dict
    ) -> None:
        """Write result.json after worker completes."""
        worker_dir = (
            self.run_dir
            / "iterations"
            / f"{iteration:03d}"
            / "delegations"
            / worker_id
        )
        worker_dir.mkdir(parents=True, exist_ok=True)
        self.write_json(worker_dir / "result.json", result)
        has_error = bool(result.get("error") or result.get("has_error")) if isinstance(result, dict) else False
        conf = result.get("confidence") if isinstance(result, dict) else None
        crit_score = result.get("_critique_score") if isinstance(result, dict) else None
        self.trace(
            "worker",
            f"{'FAIL' if has_error else 'done '} {worker_id}",
            level="ERROR" if has_error else "INFO",
            iteration=iteration,
            worker=worker_id,
            confidence=conf,
            critique_score=crit_score,
            error=(str(result.get("error", ""))[:200] if has_error and isinstance(result, dict) else None),
        )

    def log_critique(
        self, iteration: int, critiques: list[dict], summary: dict
    ) -> None:
        """Write critique results and repair history for an iteration."""
        iter_dir = self.run_dir / "iterations" / f"{iteration:03d}"
        iter_dir.mkdir(parents=True, exist_ok=True)
        self.write_json(iter_dir / "critique.json", {
            "critiques": critiques,
            "summary": summary,
        })
        # Trace summary line per worker
        for c in critiques:
            wid = c.get("worker_id", "?")
            score = c.get("score")
            defects = len(c.get("defects", []) or [])
            critical = c.get("critical_count", 0)
            level = "WARNING" if (critical or (isinstance(score, (int, float)) and score < 0.5)) else "INFO"
            self.trace(
                "critique",
                f"worker={wid} score={score} defects={defects} critical={critical}",
                level=level,
                iteration=iteration,
                worker=wid,
                score=score,
                defects=defects,
                critical=critical,
            )
        # Write per-worker critique files
        for c in critiques:
            wid = c.get("worker_id", "unknown")
            worker_dir = iter_dir / "delegations" / wid
            worker_dir.mkdir(parents=True, exist_ok=True)
            self.write_json(worker_dir / "critique.json", c)
        # Human-readable critique summary
        md_lines = [f"# Critique — Iteration {iteration}\n"]
        for c in critiques:
            wid = c.get("worker_id", "?")
            score = c.get("score", "?")
            status = "PASS" if c.get("critical_count", 0) == 0 else "NEEDS REPAIR"
            md_lines.append(f"## {wid}: {status} (score={score})\n")
            for d in c.get("defects", []):
                sev = d.get("severity", "?")
                cat = d.get("category", "?")
                desc = d.get("description", "?")
                md_lines.append(f"- [{sev.upper()}] **{cat}**: {desc}")
            prescriptions = c.get("prescriptions", [])
            if prescriptions:
                md_lines.append("\n**Prescriptions:**")
                for p in prescriptions:
                    md_lines.append(f"  - {p}")
            md_lines.append("")
        # Repair history
        repairs = summary.get("repair_history", [])
        if repairs:
            md_lines.append("## Repair History\n")
            for r in repairs:
                md_lines.append(
                    f"- **{r.get('worker_id')}** attempt {r.get('attempt')}: "
                    f"{r.get('original_score', '?')} -> {r.get('repaired_score', '?')} "
                    f"({r.get('defects_fixed', 0)} fixed)"
                )
        # Patterns
        patterns = summary.get("patterns", {})
        if patterns:
            md_lines.append("\n## Accumulated Patterns\n")
            for name, p in patterns.items():
                md_lines.append(
                    f"- **{name}** (x{p.get('frequency', 1)}): {p.get('prevention_rule', '')}"
                )
        self.write_md(iter_dir / "CRITIQUE.md", "\n".join(md_lines))

    def log_iteration_budget(self, iteration: int, budget: "BudgetSnapshot") -> None:
        """Write budget_snapshot.json after iteration finishes."""
        iter_dir = self.run_dir / "iterations" / f"{iteration:03d}"
        iter_dir.mkdir(parents=True, exist_ok=True)
        self.write_json(iter_dir / "budget_snapshot.json", budget.to_dict())
        try:
            d = budget.to_dict()
            self.trace(
                "budget",
                f"iter {iteration}",
                iteration=iteration,
                loops_used=d.get("loops_used") or (d.get("loops") or {}).get("used"),
                tokens_used=d.get("tokens_used") or (d.get("tokens") or {}).get("consumed"),
                workers_spawned=d.get("workers_spawned") or (d.get("workers") or {}).get("spawned"),
                wall_time_s=d.get("wall_time_elapsed") or (d.get("wall_time") or {}).get("elapsed_s"),
            )
        except Exception:
            pass

    # -- Full iteration log (called after iteration for full artifact dump) --

    def log_iteration(
        self,
        iteration: int,
        manager_decision: dict,
        delegations: list[dict],
        budget: BudgetSnapshot,
        validation_results: list[dict],
    ) -> None:
        iter_dir = self.run_dir / "iterations" / f"{iteration:03d}"
        iter_dir.mkdir(parents=True, exist_ok=True)

        # Manager decision (may already exist from progressive write)
        self.write_json(iter_dir / "manager_decision.json", manager_decision)

        # Delegations
        for i, deleg in enumerate(delegations):
            worker_dir = (
                iter_dir / "delegations" / (deleg.get("worker_id", f"worker_{i}"))
            )
            worker_dir.mkdir(parents=True, exist_ok=True)
            self.write_json(worker_dir / "envelope.json", deleg.get("envelope", {}))
            self.write_json(worker_dir / "result.json", deleg.get("result", {}))

            wid = deleg.get("worker_id", f"worker_{i}")

            # Save worker instructions as artifact
            envelope = deleg.get("envelope", {})
            instructions = envelope.get("instructions", "")
            if isinstance(instructions, str) and instructions.strip():
                instr_file = worker_dir / "instructions.md"
                self.write_md(instr_file, f"# Worker: {wid}\n\n{instructions}")
                artifact_instr = (
                    self.run_dir / "artifacts" / "skills" / f"{wid}_instructions.md"
                )
                self.write_md(artifact_instr, f"# Worker: {wid}\n\n{instructions}")

            # Save envelope skills as artifacts (input skills from manager)
            for j, skill in enumerate(envelope.get("skills", [])):
                if isinstance(skill, str) and skill.strip():
                    # Per-worker copy
                    skill_file = worker_dir / "generated_skills" / f"skill_{j}.md"
                    self.write_md(skill_file, skill)
                    # Central artifacts copy
                    artifact_file = (
                        self.run_dir / "artifacts" / "skills" / f"{wid}_skill_{j}.md"
                    )
                    self.write_md(artifact_file, skill)

            # Save worker-generated skills from result (output skills)
            worker_result = deleg.get("result", {})
            result_skills = worker_result.get(
                "skills_created", worker_result.get("skills", [])
            )
            if isinstance(result_skills, list):
                for j, skill in enumerate(result_skills):
                    if isinstance(skill, str) and skill.strip():
                        skill_file = (
                            worker_dir / "generated_skills" / f"result_skill_{j}.md"
                        )
                        self.write_md(skill_file, skill)
                        artifact_file = (
                            self.run_dir
                            / "artifacts"
                            / "skills"
                            / f"{wid}_result_skill_{j}.md"
                        )
                        self.write_md(artifact_file, skill)
                    elif isinstance(skill, dict):
                        sname = skill.get("name", f"skill_{j}")
                        scontent = skill.get(
                            "content", skill.get("text", json.dumps(skill, indent=2))
                        )
                        skill_file = worker_dir / "generated_skills" / f"{sname}.md"
                        self.write_md(skill_file, scontent)
                        artifact_file = (
                            self.run_dir / "artifacts" / "skills" / f"{wid}_{sname}.md"
                        )
                        self.write_md(artifact_file, scontent)

            # Save generated tools — always store FULL specs (code, parameters,
            # description, registration status) for code_mode debugging.
            worker_result = deleg.get("result", {})
            wid = deleg.get("worker_id", f"worker_{i}")

            # Collect tools from all possible sources in the result
            all_tool_specs: list[dict] = []

            # 1. tools_created: raw LLM output (original tool specs with code)
            tools_created = worker_result.get("tools_created", [])
            if isinstance(tools_created, list):
                for tool_info in tools_created:
                    if isinstance(tool_info, dict):
                        all_tool_specs.append(tool_info)

            # 2. tools_registered: enriched by _process_tool_creation (includes
            #    code + registration status + validation results)
            tools_registered = worker_result.get("tools_registered", [])
            if isinstance(tools_registered, list):
                for tool_info in tools_registered:
                    if isinstance(tool_info, dict):
                        # Only add if not already present (by name)
                        existing_names = {t.get("name") for t in all_tool_specs}
                        if tool_info.get("name") not in existing_names:
                            all_tool_specs.append(tool_info)

            # Save each tool fully (JSON + .py source)
            if all_tool_specs:
                for t, tool_info in enumerate(all_tool_specs):
                    tool_name = tool_info.get("name", f"tool_{t}")
                    safe_name = tool_name.replace(".", "_")

                    # Per-worker copy (full spec with code)
                    tool_file = worker_dir / "generated_tools" / f"{safe_name}.json"
                    self.write_json(tool_file, tool_info)

                    # Central artifacts copy (full spec with code)
                    artifact_file = (
                        self.run_dir / "artifacts" / "tools" / f"{safe_name}.json"
                    )
                    self.write_json(artifact_file, tool_info)

                    # Save tool code as .py file for easy inspection
                    tool_code = tool_info.get("code", "")
                    if tool_code:
                        header = (
                            f"# Auto-generated tool: {tool_name}\n"
                            f"# Created by worker: {tool_info.get('worker_id', wid)}\n"
                            f"# Description: {tool_info.get('description', '')}\n"
                            f"# Required secrets: {tool_info.get('required_secrets', [])}\n"
                            f"# Parameters: {json.dumps(tool_info.get('parameters', {}), default=str)}\n"
                            f"# Registered: {tool_info.get('registered', 'unknown')}\n\n"
                        )
                        py_file = worker_dir / "generated_tools" / f"{safe_name}.py"
                        self._write_file(py_file, header + tool_code)
                        artifact_py = (
                            self.run_dir / "artifacts" / "tools" / f"{safe_name}.py"
                        )
                        self._write_file(artifact_py, header + tool_code)

                # Save a combined manifest with all tools for this worker
                tool_manifest = {
                    "worker_id": wid,
                    "iteration": iteration,
                    "tool_count": len(all_tool_specs),
                    "tools": all_tool_specs,
                }
                manifest_file = (
                    self.run_dir / "artifacts" / "tools" / f"{wid}_manifest.json"
                )
                self.write_json(manifest_file, tool_manifest)

            # Also check for tool_names (alternative format — name-only list)
            tool_names = worker_result.get("tool_names", [])
            if isinstance(tool_names, list) and tool_names:
                tool_names_manifest = {"worker_id": wid, "tools": tool_names}
                artifact_file = (
                    self.run_dir / "artifacts" / "tools" / f"{wid}_tools.json"
                )
                self.write_json(artifact_file, tool_names_manifest)

            # Save tool call traces as artifacts (especially code.execute calls)
            tool_calls = worker_result.get("_tool_calls", [])
            if isinstance(tool_calls, list) and tool_calls:
                # Save full tool call log as JSON
                calls_file = worker_dir / "tool_calls.json"
                self.write_json(calls_file, tool_calls)
                artifact_calls = (
                    self.run_dir / "artifacts" / "tools" / f"{wid}_tool_calls.json"
                )
                self.write_json(artifact_calls, tool_calls)

                # Extract and save code.execute calls as .py files
                code_idx = 0
                for tc in tool_calls:
                    if not isinstance(tc, dict):
                        continue
                    tool_name = tc.get("tool", "")
                    if tool_name in ("code.execute", "code_execute"):
                        args = tc.get("arguments", {})
                        code_text = args.get("code", "")
                        if code_text:
                            result_data = tc.get("result", {})
                            stdout = ""
                            stderr = ""
                            if isinstance(result_data, dict):
                                data_inner = result_data.get("data", {})
                                if isinstance(data_inner, dict):
                                    stdout = data_inner.get("stdout", "")
                                    stderr = data_inner.get("stderr", "")

                            header = (
                                f"# code.execute call #{code_idx} by worker: {wid}\n"
                                f"# Tool: {tool_name}\n"
                                f"# Status: {'OK' if result_data.get('ok') else 'ERROR'}\n"
                            )
                            footer = ""
                            if stdout:
                                footer += f"\n# --- STDOUT ---\n# {stdout[:2000]}\n"
                            if stderr:
                                footer += f"\n# --- STDERR ---\n# {stderr[:2000]}\n"

                            py_file = (
                                worker_dir
                                / "generated_tools"
                                / f"code_execute_{code_idx}.py"
                            )
                            self._write_file(py_file, header + code_text + footer)
                            artifact_py = (
                                self.run_dir
                                / "artifacts"
                                / "tools"
                                / f"{wid}_code_execute_{code_idx}.py"
                            )
                            self._write_file(artifact_py, header + code_text + footer)
                            code_idx += 1

            # Worker result as MD
            result = deleg.get("result", {})
            confidence = result.get("confidence", "N/A")
            md = (
                f"# Worker: {wid}\n\n"
                f"**Confidence:** {confidence}\n\n"
                f"## Result\n```json\n{json.dumps(result, indent=2, default=str)}\n```\n"
            )
            self.write_md(worker_dir / "RESULT.md", md)

        # Budget snapshot
        self.write_json(iter_dir / "budget_snapshot.json", budget.to_dict())

        # Validation
        self.write_json(iter_dir / "validation.json", validation_results)

        # Iteration summary MD
        decision_type = manager_decision.get("decision", "unknown")
        md_lines = [
            f"# Iteration {iteration} — {decision_type.upper()}\n",
            f"## Manager Decision: {decision_type.upper()}\n",
        ]
        reasoning = manager_decision.get("reasoning", "")
        if reasoning:
            md_lines.append(f"**Reasoning:** {reasoning}\n")

        md_lines.append(f"\n## Delegations ({len(delegations)})\n")
        for deleg in delegations:
            wid = deleg.get("worker_id", "?")
            conf = deleg.get("result", {}).get("confidence", "?")
            md_lines.append(f"- **{wid}**: confidence={conf}")

        md_lines.append(
            f"\n## Budget\n- Remaining: {budget.budget_fraction_remaining * 100:.0f}%\n"
        )
        self.write_md(iter_dir / "ITERATION_SUMMARY.md", "\n".join(md_lines))

    def log_completion(
        self,
        run_id: str,
        final_result: dict,
        budget: BudgetSnapshot,
        total_iterations: int,
        status: str,
    ) -> None:
        summary = {
            "run_id": run_id,
            "status": status,
            "total_iterations": total_iterations,
            "final_budget": budget.to_dict(),
            "completed": datetime.now(timezone.utc).isoformat(),
        }
        self.write_json(self.run_dir / "run_completion.json", summary)
        self.trace(
            "completion",
            f"run {run_id} {status} after {total_iterations} iterations",
            level="ERROR" if status in ("error", "failed", "eval_fail") else "INFO",
            run_id=run_id,
            status=status,
            total_iterations=total_iterations,
            tokens=getattr(budget, "tokens_consumed", None),
            workers=getattr(budget, "workers_spawned", None),
            wall_time_s=getattr(budget, "wall_time_elapsed", None),
        )
        # Append completion section to the per-run RUN_SUMMARY.md
        md = (
            f"\n\n---\n## Completion\n"
            f"**Status:** {status}\n"
            f"**Iterations:** {total_iterations}\n"
            f"**Wall Time:** {getattr(budget, 'wall_time_elapsed', 0):.1f}s\n"
            f"**Workers Spawned:** {getattr(budget, 'workers_spawned', 0)}\n"
        )
        # Flush pending writes so RUN_SUMMARY.md is on disk before we read it
        self.flush()
        run_summary = self.run_dir / "RUN_SUMMARY.md"
        existing = ""
        if run_summary.exists():
            try:
                existing = run_summary.read_text(encoding="utf-8")
            except Exception:
                pass
        self.write_md(run_summary, existing + md)

        # Write a human-readable summary into the experiment logs dir
        self._write_debug_summary(run_id, status, total_iterations, budget)
        # Close debug log handles
        self._close_debug_handles()

    def _write_debug_summary(
        self,
        run_id: str,
        status: str,
        total_iterations: int,
        budget: "BudgetSnapshot",
    ) -> None:
        """Generate a final summary.md inside the experiment logs dir."""
        if self._debug_dir is None:
            return
        try:
            lines: list[str] = []
            lines.append(f"# Run Debug Summary — {run_id}\n")
            lines.append(f"- **Status**: `{status}`")
            lines.append(f"- **Iterations**: {total_iterations}")
            lines.append(f"- **Workers spawned**: {getattr(budget, 'workers_spawned', '?')}")
            lines.append(f"- **Tokens consumed**: {getattr(budget, 'tokens_consumed', '?')}")
            lines.append(f"- **Wall time**: {getattr(budget, 'wall_time_elapsed', 0):.1f}s")
            lines.append(f"- **Completed**: {datetime.now(timezone.utc).isoformat()}\n")

            # Tail of debug.log
            debug_path = self._debug_dir / "debug.log"
            if debug_path.exists():
                try:
                    txt = debug_path.read_text(encoding="utf-8", errors="replace")
                    tail = txt.splitlines()[-50:]
                    lines.append("## Last 50 trace events\n")
                    lines.append("```")
                    lines.extend(tail)
                    lines.append("```\n")
                except Exception:
                    pass

            # Errors
            err_path = self._debug_dir / "errors.log"
            if err_path.exists():
                try:
                    txt = err_path.read_text(encoding="utf-8", errors="replace")
                    err_lines = txt.splitlines()
                    if err_lines:
                        lines.append(f"## Errors ({len(err_lines)} total)\n")
                        lines.append("```")
                        lines.extend(err_lines[-30:])
                        lines.append("```\n")
                except Exception:
                    pass

            # Gates
            gate_path = self._debug_dir / "gates.log"
            if gate_path.exists():
                try:
                    txt = gate_path.read_text(encoding="utf-8", errors="replace")
                    gates = [l for l in txt.splitlines() if "triggered=True" in l]
                    if gates:
                        lines.append(f"## Completion gates triggered ({len(gates)})\n")
                        lines.append("```")
                        lines.extend(gates[-20:])
                        lines.append("```\n")
                except Exception:
                    pass

            (self._debug_dir / "summary.md").write_text(
                "\n".join(lines), encoding="utf-8"
            )
        except Exception:
            pass

    def _close_debug_handles(self) -> None:
        for h in list(self._debug_handles.values()):
            try:
                h.close()
            except Exception:
                pass
        self._debug_handles.clear()

    def update_rolling_summary(
        self,
        iteration: int,
        confidence: float,
        key_findings: str,
        full_history: list[dict],
        window: int = 3,
    ) -> None:
        """Write ROLLING_SUMMARY.md with recent details and older summaries."""
        lines = [
            "# Rolling Summary\n",
            "## Progress\n",
            f"- Iteration: {iteration}\n",
            f"- Current Confidence: {confidence}\n\n",
        ]

        # Confidence trend
        if full_history:
            trend = " → ".join(
                f"Iter {h['iteration']}: {h.get('confidence', '?')}"
                for h in full_history[-6:]
            )
            lines.append(f"## Confidence Trend\n{trend}\n\n")

        # Last N iterations in detail
        recent = full_history[-window:] if full_history else []
        if recent:
            lines.append(f"## Last {len(recent)} Iterations (Detail)\n")
            for h in reversed(recent):
                lines.append(f"### Iteration {h['iteration']}\n")
                lines.append(f"- Confidence: {h.get('confidence', '?')}\n")
                findings = h.get("key_findings", "")
                if findings:
                    lines.append(f"- Findings: {findings}\n")
                lines.append("")

        # Older iterations summarized
        older = full_history[:-window] if len(full_history) > window else []
        if older:
            lines.append("## Older Iterations (Summary)\n")
            for h in older:
                lines.append(
                    f"- Iter {h['iteration']}: confidence={h.get('confidence', '?')}\n"
                )

        self.write_md(self.run_dir / "history" / "ROLLING_SUMMARY.md", "".join(lines))
        self.write_json(
            self.run_dir / "history" / "rolling_summary.json",
            {
                "iteration": iteration,
                "confidence": confidence,
                "history": full_history,
            },
        )


# ---------------------------------------------------------------------------
# Delegation Loop Runner
# ---------------------------------------------------------------------------


class DelegationLoopRunner:
    """Executes the delegation_loop orchestration engine.

    The manager agent receives the task + rolling summary and decides:
    - DELEGATE: generate envelopes for worker agents
    - COMPLETE: return final result
    - FAIL: abort with partial result

    Workers are ephemeral, configured by the manager's delegation envelopes.
    """

    def __init__(
        self,
        workflow_dir: Path,
        config: DelegationLoopConfig,
        tool_registry: Optional[ToolRegistry] = None,
        manager_model: Optional[str] = None,
        worker_model: Optional[str] = None,
        run_id: Optional[str] = None,
        depth: int = 0,
        parent_budget: Optional[BudgetSnapshot] = None,
        eval_config: Any = None,
        llm_client: Optional[LLMClient] = None,
        profile: bool = False,
        run_dir_override: Optional[Path] = None,
        inherited_state: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._dir = workflow_dir
        self._config = config
        self._profiler = PerformanceProfiler(enabled=profile)
        self._tools = tool_registry
        self._manager_model = manager_model or config.models.manager or ""
        self._worker_model = worker_model or config.models.worker or self._manager_model
        self._run_id = (
            run_id
            or datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M-%S")
            + "_"
            + uuid.uuid4().hex[:8]
        )
        self._depth = depth

        # Budget: use parent's remaining budget or create fresh
        reservation_cfg = getattr(config, "budget_reservation", None)
        if parent_budget:
            self._budget = parent_budget
        else:
            self._budget = BudgetSnapshot(config.budget, reservation_config=reservation_cfg)

        # Persistent LLM client for manager (reused across iterations)
        self._manager_llm: LLMClient | None = None
        if self._manager_model:
            try:
                self._manager_llm = LLMClient(model=self._manager_model)
            except Exception:
                logger.debug("Could not pre-create manager LLM client")

        # Stall detection (with optional strategy switching)
        stall_cfg = config.termination
        strategy_cfg = (
            getattr(stall_cfg, "strategy_switching", None) if stall_cfg else None
        )
        self._stall = (
            StallDetector(
                window=stall_cfg.window if stall_cfg else 3,
                min_delta=stall_cfg.min_confidence_delta if stall_cfg else 0.05,
                strategy_config=strategy_cfg,
            )
            if (stall_cfg and stall_cfg.enabled)
            else None
        )

        # Manager Intelligence: Decision Journal
        journal_cfg = getattr(config, "decision_journal", None)
        self._journal: DecisionJournal | None = None
        if journal_cfg and journal_cfg.enabled:
            self._journal = DecisionJournal(max_entries=journal_cfg.max_entries)
            logger.info("Decision journal active (max_entries=%d)", journal_cfg.max_entries)

        # Manager Intelligence: Task Decomposition
        planning_cfg = getattr(config, "planning", None)
        self._planning_enabled = bool(planning_cfg and planning_cfg.enabled)
        self._task_plan: TaskPlan | None = None
        if self._planning_enabled:
            self._task_plan_max = planning_cfg.max_subtasks  # type: ignore[union-attr]
            logger.info("Task planning active (max_subtasks=%d)", self._task_plan_max)

        # Manager Intelligence: Hypothesis-Driven Debugging
        diagnosis_cfg = getattr(config, "diagnosis", None)
        self._diagnosis_enabled = bool(diagnosis_cfg and diagnosis_cfg.enabled)
        self._diagnosis_threshold = (
            diagnosis_cfg.confidence_threshold if diagnosis_cfg else 0.3
        )
        self._diagnosis_max_hypotheses = (
            diagnosis_cfg.max_hypotheses if diagnosis_cfg else 3
        )

        # Logger — submanagers write under their parent worker directory so
        # the visualizer can render nested sub-runs (graph_builder.py walks
        # `<worker_dir>/runs/<sub_run_id>/`).
        if run_dir_override is not None:
            run_dir = run_dir_override
        else:
            run_dir = self._dir / "workspace" / "runs" / self._run_id
        self._run_dir = run_dir
        self._inherited_state = inherited_state or {}
        self._logger = RunLogger(run_dir, fmt=config.logging.format)

        # Blackboard (sibling coordination) — one per manager run.
        # Submanagers automatically get their own because every
        # DelegationLoopRunner construction picks a distinct run_id
        # and a fresh Blackboard instance (see blackboard.py).
        from .blackboard import Blackboard as _Blackboard
        self._blackboard: Optional[_Blackboard] = None
        self._last_blackboard_seen_id: Optional[str] = None
        if getattr(config, "blackboard_enabled", True):
            try:
                self._blackboard = _Blackboard(
                    workspace=self._dir / "workspace",
                    manager_run_id=self._run_id,
                )
                logger.info(
                    "Blackboard active for run %s at %s",
                    self._run_id,
                    self._blackboard.path,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Could not init blackboard: %s", exc)
                self._blackboard = None

        # Hierarchical Context Digest (HCD) — one DigestStore per manager
        # run, writing into `<workspace>/digest/<sha>.json`. The store is
        # bound into a ContextVar during `run()` so the `digest.fetch`
        # builtin tool serves THIS run and only this run.
        from .digest import DigestStore as _DigestStore
        self._digest_store: Optional[_DigestStore] = None
        self._current_digest: Optional[Any] = None
        self._current_digest_sha: Optional[str] = None
        self._pending_child_digest_hashes: list[str] = []
        # Parent digest sha — set by a parent runner when it spawns a
        # submanager, so the child can link back to its parent's
        # latest digest in its own records.
        self._parent_digest_sha: Optional[str] = None
        if (inherited_state or {}).get("__parent_digest_sha"):
            parent_sha = (inherited_state or {}).get("__parent_digest_sha")
            if isinstance(parent_sha, str):
                self._parent_digest_sha = parent_sha
        if getattr(config, "digest_enabled", True):
            try:
                self._digest_store = _DigestStore(
                    workspace=self._dir / "workspace" / "runs" / self._run_id,
                )
                logger.info(
                    "DigestStore active for run %s at %s",
                    self._run_id,
                    self._digest_store.path,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Could not init digest store: %s", exc)
                self._digest_store = None

        # Iteration label counter — separate from budget.loops_used so that
        # child-budget reservations (which pre-charge loops to the parent)
        # don't make the manager iteration counter jump (e.g. 3 → 10 → 16).
        # This is purely a display/log-path counter; budget.loops_used still
        # tracks real budget consumption.
        self._iter_counter = 0

        # History
        self._history: list[dict[str, Any]] = []
        # P4: track signatures of past delegation dispatches to detect when
        # the manager re-issues the same logical subtasks instead of repairing.
        self._past_delegation_signatures: list[tuple[str, ...]] = []
        # Baustein 4 (auto-curation): track failing delegation signatures
        # (redundant re-dispatch, worker error, worker confidence < 0.3)
        # so the Curator can write them as antipatterns at run end.
        self._failed_signatures: list[dict] = []
        # Wall-clock run start — used by the curator to bucket facts
        # into ``memory/facts/YYYY-MM-DD.md``.
        from datetime import datetime as _dt, timezone as _tz
        self._run_started_at = _dt.now(_tz.utc)

        # Critique engine (Reflective Critique Loop)
        self._critique_engine: Optional[CritiqueEngine] = None
        critique_cfg = getattr(config, "critique", None)
        if critique_cfg and critique_cfg.enabled:
            self._critique_engine = CritiqueEngine(
                config=critique_cfg,
                workflow_dir=workflow_dir,
                run_id=self._run_id,
                worker_model=self._worker_model,
                llm_client=llm_client,
            )
            logger.info("Critique engine active (max_repair=%d)", critique_cfg.max_repair_attempts)

        # Evaluation engine (no-op if not configured)
        self._eval_engine: Optional[EvaluationEngine] = None
        if eval_config and getattr(eval_config, "enabled", False):
            self._eval_engine = EvaluationEngine(
                config=eval_config,
                workflow_dir=workflow_dir,
                run_id=self._run_id,
                llm_client=llm_client,
            )
            logger.info(
                "Evaluation engine active with %d metrics",
                len(eval_config.metrics),
            )

    def _load_agent(
        self, agent_dir: Path, llm: Optional[LLMClient] = None
    ) -> StandaloneAgent:
        """Load the Agent class from ``agent.py``, falling back to
        :class:`StandaloneAgent`.  See :meth:`WorkflowRunner._load_agent`."""
        agent_py = agent_dir / "agent.py"
        if agent_py.exists():
            try:
                spec = importlib.util.spec_from_file_location(
                    f"awp_agent_{agent_dir.name}",
                    str(agent_py),
                )
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)  # type: ignore[union-attr]
                agent_cls = getattr(module, "Agent", None)
                if agent_cls is not None:
                    return agent_cls(
                        agent_dir=agent_dir,
                        workflow_dir=self._dir,
                        llm=llm,
                        tool_registry=self._tools,
                    )
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "Could not load Agent from %s, using StandaloneAgent: %s",
                    agent_py,
                    exc,
                )
        return StandaloneAgent(
            agent_dir,
            self._dir,
            llm=llm,
            tool_registry=self._tools,
        )

    def run(self, task: str, state: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Execute the delegation loop."""
        state = dict(state or {})
        state["task"] = task

        # Isolate output under this run ID
        if self._tools and hasattr(self._tools, "set_run_id"):
            self._tools.set_run_id(self._run_id)

        logger.info(
            "DelegationLoop [%s] depth=%d starting: %s",
            self._run_id,
            self._depth,
            task[:80],
        )

        self._logger.log_run_start(
            task,
            self._run_id,
            self._config,
            self._manager_model,
            self._worker_model,
        )

        final_result: Dict[str, Any] = {}
        status = "unknown"

        # Bind this run's blackboard to the contextvar so the
        # `board.post` / `board.read` builtin tools serve THIS run
        # (and only this run). Submanagers re-bind inside their own
        # `run()` call; the token stack restores the parent on return.
        from .blackboard import current_blackboard as _current_bb
        from .digest import current_digest_store as _current_ds
        _bb_token = _current_bb.set(self._blackboard)
        _ds_token = _current_ds.set(self._digest_store)
        try:
            final_result, status = self._loop(task, state)
        except Exception as exc:
            logger.error("DelegationLoop error: %s", exc)
            final_result = {"error": str(exc), "confidence": 0.0}
            status = "error"
        finally:
            try:
                _current_bb.reset(_bb_token)
            except Exception:
                pass
            try:
                _current_ds.reset(_ds_token)
            except Exception:
                pass
        # Surface the final digest sha on the run result so parent
        # runners can fold it into their own digests.
        if self._current_digest_sha and isinstance(final_result, dict):
            final_result.setdefault("_digest_sha", self._current_digest_sha)

        self._logger.log_completion(
            self._run_id,
            final_result,
            self._budget,
            self._iter_counter,
            status,
        )
        # Flush all async writes to disk before returning
        self._logger.flush()

        # Write performance timing report if profiling is enabled
        run_dir = self._dir / "workspace" / "runs" / self._run_id
        self._profiler.write_report(run_dir)

        wrapped = {"delegation_loop": final_result}
        if self._current_digest_sha:
            wrapped["_digest_sha"] = self._current_digest_sha

        # Baustein 4: Auto-curation — deterministically distill this run
        # into long-term memory files under ``<workflow_dir>/memory/``.
        # Only the root manager curates (submanagers share the parent's
        # workflow_dir but the curator is idempotent so a double-run is
        # safe — restricting to root keeps the run-id attribution clean).
        if (
            getattr(self._config, "auto_curation_enabled", True)
            and self._parent_digest_sha is None
        ):
            try:
                from .curator import Curator as _Curator
                report = _Curator(
                    workflow_dir=self._dir,
                    run_id=self._run_id,
                    digest_store=self._digest_store,
                    final_result=final_result,
                    dynamic_tools_registry=self._tools,
                    root_digest_sha=self._current_digest_sha,
                    failed_signatures=self._failed_signatures,
                    run_started_at=self._run_started_at,
                ).curate()
                wrapped["delegation_loop"]["curation_report"] = report.to_dict()
            except Exception as exc:  # noqa: BLE001
                logger.warning("Auto-curation failed (non-fatal): %s", exc)
        return wrapped

    def _loop(self, task: str, state: dict) -> tuple[dict, str]:
        """Core loop: ask manager → delegate → validate → repeat."""

        while True:
            # Budget check
            can_go, reason = self._budget.can_continue()
            if not can_go:
                logger.warning("Budget exhausted: %s", reason)
                return self._build_partial_result(reason), "budget_exhausted"

            self._budget.loops_used += 1
            self._iter_counter += 1
            iteration = self._iter_counter

            logger.info("=== Iteration %d ===", iteration)

            # 1. Ask manager for decision
            self._profiler.start(f"manager.iter_{iteration}")
            manager_decision = self._run_manager(task, state, iteration)
            self._profiler.stop(f"manager.iter_{iteration}", iteration=iteration)
            decision_type = manager_decision.get("decision", "fail")

            # Write manager decision to disk immediately (for file watchers)
            self._profiler.start(f"logging.manager_decision_{iteration}")
            self._logger.log_manager_decision(iteration, manager_decision)
            self._profiler.stop(f"logging.manager_decision_{iteration}")

            # Record decision in journal (Manager Intelligence)
            if self._journal:
                rationale = manager_decision.get("reasoning", "")
                if not rationale and decision_type == "delegate":
                    rationale = f"Delegating to {len(manager_decision.get('delegations', []))} workers"
                self._journal.record(
                    iteration,
                    decision_type,
                    rationale,
                    worker_ids=[
                        d.get("worker_id", "")
                        for d in manager_decision.get("delegations", [])
                    ],
                )

            # Handle PLAN decision (Manager Intelligence: Task Decomposition).
            #
            # The plan is normally accepted once and then locked, but two
            # important exceptions exist:
            #
            #   1. **Refinement before any work starts** — weak manager
            #      models often issue a first rough plan and then a second,
            #      better plan a turn later (e.g. with `delegation_strategy:
            #      submanager` annotations). If no subtask has been worked on
            #      yet, the second plan is allowed to fully REPLACE the first
            #      one. Without this, A4 submanager activation is silently
            #      lost whenever the manager improves its plan in iteration 2.
            #
            #   2. **Annotation merge after work started** — if work has
            #      already begun, we still merge any *new*
            #      `delegation_strategy` annotations from the new plan into
            #      pending subtasks of the existing plan. This lets the
            #      manager promote subtasks to submanagers mid-flight without
            #      losing progress on completed ones.
            if decision_type == "plan":
                # R31 Plan-Tool-Closure (HARD): every subtask must declare a
                # tool_manifest. Reject and force a re-plan if violated.
                try:
                    from awp.validator.rules_planning import (
                        format_violations,
                        validate_runtime_plan,
                    )

                    # P5: inject default `assumptions: []` so managers that
                    # forget the field don't trip R31 unnecessarily.
                    for _st in manager_decision.get("subtasks", []) or []:
                        if isinstance(_st, dict) and "assumptions" not in _st:
                            _st["assumptions"] = []
                    _r31_violations = validate_runtime_plan(manager_decision)
                except Exception as _r31_exc:  # pragma: no cover
                    logger.warning("R31 validator unavailable: %s", _r31_exc)
                    _r31_violations = []
                if _r31_violations:
                    state["_r31_feedback"] = format_violations(_r31_violations)
                    self._logger.trace_gate(
                        "r31_plan_tool_closure",
                        triggered=True,
                        reason=f"{len(_r31_violations)} violation(s)",
                        violations=len(_r31_violations),
                        first=str(_r31_violations[0]) if _r31_violations else "",
                    )
                    logger.warning(
                        "R31 rejected PLAN with %d violation(s); requesting re-plan",
                        len(_r31_violations),
                    )
                    continue
                new_subtasks = manager_decision.get("subtasks", [])
                # Track consecutive PLAN iterations without any worker progress
                # so we can force the manager out of an endless planning loop.
                # Without this cap a weaker model can sit in PLAN forever,
                # refining the same subtasks across many iterations and
                # never actually executing anything.
                pre_progress_plans = int(state.get("_pre_progress_plans", 0))
                MAX_PRE_PROGRESS_PLANS = 2
                if self._task_plan is not None:
                    has_progress = any(
                        st.get("status") in ("in_progress", "completed", "failed")
                        for st in self._task_plan._subtasks
                    )
                    if not has_progress:
                        pre_progress_plans += 1
                        state["_pre_progress_plans"] = pre_progress_plans
                        if pre_progress_plans > MAX_PRE_PROGRESS_PLANS:
                            logger.warning(
                                "Manager issued PLAN %d times without any "
                                "worker progress — locking plan and forcing "
                                "DELEGATE next iteration.",
                                pre_progress_plans,
                            )
                            state["_plan_locked"] = (
                                f"You have issued PLAN {pre_progress_plans} "
                                f"times in a row without spawning any workers. "
                                f"The plan is now LOCKED. You MUST issue a "
                                f"DELEGATE decision next, picking the first "
                                f"pending subtask from the existing plan and "
                                f"assigning it to a worker. Do NOT issue PLAN "
                                f"or DIAGNOSE again until at least one worker "
                                f"has produced a result."
                            )
                            self._logger.trace_gate(
                                "plan_loop",
                                triggered=True,
                                reason=f"{pre_progress_plans} consecutive PLANs with no progress",
                                pre_progress_plans=pre_progress_plans,
                            )
                            continue
                    if (
                        not has_progress
                        and new_subtasks
                        and self._planning_enabled
                    ):
                        # Case 1: refinement — fully replace the plan.
                        logger.info(
                            "Replacing initial plan with refined plan "
                            "(no work started yet, %d → %d subtasks)",
                            len(self._task_plan._subtasks),
                            len(new_subtasks),
                        )
                        self._task_plan = TaskPlan(max_subtasks=self._task_plan_max)
                        if self._depth < self._budget.max_depth:
                            promoted = self._auto_promote_complex_subtasks(
                                new_subtasks
                            )
                            if promoted:
                                logger.info(
                                    "Auto-promoted %d subtask(s) on refined "
                                    "plan: %s",
                                    len(promoted), promoted,
                                )
                        self._task_plan.set_subtasks(new_subtasks)
                        logger.info(
                            "Refined task plan installed with %d subtasks",
                            len(new_subtasks),
                        )
                        continue

                    # Case 2: merge delegation_strategy annotations from
                    # the new plan into pending subtasks of the existing
                    # plan. We never touch in_progress / completed entries.
                    merged = 0
                    if new_subtasks:
                        existing_by_id = {
                            st.get("id"): st for st in self._task_plan._subtasks
                        }
                        for nst in new_subtasks:
                            nid = nst.get("id")
                            nstrat = nst.get("delegation_strategy")
                            if not (nid and nstrat):
                                continue
                            est = existing_by_id.get(nid)
                            if not est:
                                continue
                            if est.get("status") not in (None, "pending"):
                                continue
                            if est.get("delegation_strategy") != nstrat:
                                est["delegation_strategy"] = nstrat
                                merged += 1
                        if merged:
                            logger.info(
                                "Merged %d delegation_strategy annotation(s) "
                                "from re-PLAN into existing plan",
                                merged,
                            )

                    logger.warning(
                        "Manager issued PLAN again but plan already in "
                        "progress (%s). Locking plan — manager should DELEGATE.",
                        self._task_plan.progress_summary(),
                    )
                    state["_plan_locked"] = (
                        "A task plan already exists and work has started. "
                        "You MUST use DELEGATE to assign workers to pending "
                        "subtasks, or COMPLETE if the task is done. "
                        "Do NOT issue PLAN again."
                    )
                    if self._stall:
                        stall_status = self._stall.record(0.0, "repeated_plan")
                        if stall_status == "switch_strategy":
                            state["_strategy_override"] = self._stall.suggested_strategy
                            logger.warning(
                                "PLAN loop stall — switching strategy: %s",
                                self._stall.suggested_strategy,
                            )
                        elif stall_status == "stop":
                            return self._build_partial_result(
                                "stall_detected_plan_loop"
                            ), "stall_detected"
                    continue
                subtasks = new_subtasks
                # First-ever plan also counts toward the pre-progress cap
                state["_pre_progress_plans"] = pre_progress_plans + 1
                if subtasks and self._planning_enabled:
                    self._task_plan = TaskPlan(
                        max_subtasks=self._task_plan_max
                    )
                    # Defense-in-depth for A4: smart auto-tagging.
                    #
                    # The manager *should* set delegation_strategy on each
                    # subtask itself (the system prompt asks for it). But
                    # weaker models forget the field. We score each subtask
                    # for "complexity" and only promote ones that look like
                    # they actually need their own iteration loop.
                    #
                    # Scoring is intentionally cheap and deterministic so
                    # the user never has to think about it.
                    if self._depth < self._budget.max_depth:
                        promoted = self._auto_promote_complex_subtasks(subtasks)
                        if promoted:
                            logger.info(
                                "Auto-promoted %d subtask(s) to submanager "
                                "based on complexity scoring: %s",
                                len(promoted), promoted,
                            )
                    self._task_plan.set_subtasks(subtasks)
                    logger.info(
                        "Task plan created with %d subtasks", len(subtasks)
                    )
                else:
                    logger.warning("PLAN decision but no subtasks or planning disabled")
                continue  # manager will see the plan on the next iteration

            # Handle DIAGNOSE decision (Manager Intelligence: Hypothesis Debugging)
            # Max 2 consecutive DIAGNOSE decisions — after that, force DELEGATE.
            # Also enforce a total diagnose budget (max 30% of loop budget) and
            # a cooldown period (must delegate at least 2 times before diagnosing again).
            if decision_type == "diagnose":
                prev_diagnose_count = state.get("_consecutive_diagnoses", 0)
                total_diagnoses = state.get("_total_diagnoses", 0)
                diagnose_cooldown = state.get("_diagnose_cooldown", 0)
                max_total_diagnoses = max(3, self._budget.max_loops // 4)
                blocked = False

                if total_diagnoses >= max_total_diagnoses:
                    logger.warning(
                        "Total DIAGNOSE budget exhausted (%d/%d) — "
                        "forcing delegation.",
                        total_diagnoses, max_total_diagnoses,
                    )
                    state["_diagnose_locked"] = (
                        f"You have used all {max_total_diagnoses} DIAGNOSE decisions. "
                        f"You MUST now DELEGATE workers or COMPLETE the task. "
                        f"No more diagnosis is allowed."
                    )
                    blocked = True
                elif diagnose_cooldown > 0:
                    logger.warning(
                        "DIAGNOSE cooldown active (%d delegations remaining) — "
                        "forcing delegation.",
                        diagnose_cooldown,
                    )
                    state["_diagnose_locked"] = (
                        "DIAGNOSE is on cooldown. You must DELEGATE at least "
                        f"{diagnose_cooldown} more time(s) before diagnosing again. "
                        "Use the existing hypotheses to guide your delegation."
                    )
                    blocked = True
                elif prev_diagnose_count >= 2:
                    logger.warning(
                        "Manager issued DIAGNOSE %d times in a row — "
                        "forcing delegation. Hypotheses are already available.",
                        prev_diagnose_count + 1,
                    )
                    state["_diagnose_locked"] = (
                        "You have already diagnosed the problem. Hypotheses "
                        "are listed above. You MUST now DELEGATE a worker to "
                        "test or fix the issue, or COMPLETE if the task is done. "
                        "Do NOT issue DIAGNOSE again."
                    )
                    blocked = True

                if blocked:
                    # Feed stall detector
                    if self._stall:
                        stall_status = self._stall.record(0.0, "repeated_diagnose")
                        if stall_status == "switch_strategy":
                            state["_strategy_override"] = self._stall.suggested_strategy
                            logger.warning(
                                "DIAGNOSE loop stall — switching strategy: %s",
                                self._stall.suggested_strategy,
                            )
                        elif stall_status == "stop":
                            return self._build_partial_result(
                                "stall_detected_diagnose_loop"
                            ), "stall_detected"
                    continue

                hypotheses = manager_decision.get("hypotheses", [])
                if hypotheses and self._diagnosis_enabled:
                    state["_active_hypotheses"] = hypotheses
                    state["_consecutive_diagnoses"] = prev_diagnose_count + 1
                    state["_total_diagnoses"] = total_diagnoses + 1
                    logger.info(
                        "Diagnosis: %d hypotheses generated for worker '%s' "
                        "(total diagnoses: %d/%d)",
                        len(hypotheses),
                        manager_decision.get("failed_worker", "?"),
                        total_diagnoses + 1,
                        max_total_diagnoses,
                    )
                else:
                    logger.warning("DIAGNOSE decision but no hypotheses or diagnosis disabled")
                continue  # manager will use hypotheses to inform next delegation

            # 2. Handle decision
            if decision_type == "complete":
                result = manager_decision.get("final_result", {})
                # Support flat complete format (report_md, chart_paths, json_data at top level)
                if not result:
                    result = {}
                    for key in (
                        "report_md",
                        "chart_paths",
                        "json_data",
                        "plan",
                        "reasoning",
                    ):
                        if key in manager_decision:
                            result[key] = manager_decision[key]
                if "confidence" not in result:
                    result["confidence"] = manager_decision.get("confidence", 0.8)

                # --- Critique gate: reject completion if the latest
                # iteration's mean critique score is below the configured
                # threshold. The manager often calls "complete" with low
                # critique scores because it doesn't weight critique
                # feedback heavily enough on its own; this gate enforces it.
                if (
                    self._critique_engine
                    and self._critique_engine.enabled
                    and self._history
                    and self._budget.can_continue()[0]
                ):
                    last = self._history[-1] if self._history else {}
                    critique_entries = last.get("critique") or []
                    scores: list[float] = []
                    defect_count = 0
                    for ce in critique_entries:
                        s = ce.get("score") if isinstance(ce, dict) else None
                        if isinstance(s, (int, float)):
                            scores.append(float(s))
                        defs = ce.get("defects") if isinstance(ce, dict) else None
                        if isinstance(defs, list):
                            defect_count += len(defs)
                    threshold = float(
                        getattr(
                            self._config.critique,
                            "min_score_to_complete",
                            0.5,
                        )
                    )
                    # Ground-truth bypass: if the task implies a file
                    # deliverable AND that deliverable already exists on
                    # disk with non-trivial size, the LLM critic's
                    # narrative pessimism is overruled. Critique is
                    # advisory; the filesystem is authoritative.
                    deliverable_missing = self._check_missing_deliverable(task)
                    if scores and threshold > 0 and not deliverable_missing:
                        # Check if task hints at any file deliverable at all
                        task_text = (task or "").lower()
                        any_hint = any(
                            kw in task_text
                            for kws, _ in self._DELIVERABLE_HINTS
                            for kw in kws
                        )
                        if any_hint:
                            logger.info(
                                "Critique gate bypassed: task implies a "
                                "file deliverable and it exists on disk; "
                                "ignoring critic mean_score=%.2f",
                                sum(scores) / len(scores),
                            )
                            scores = []  # disable the critique gate below

                    if scores and threshold > 0:
                        mean_score = sum(scores) / len(scores)
                        if mean_score < threshold:
                            logger.warning(
                                "Manager tried to COMPLETE but mean critique "
                                "score %.2f is below threshold %.2f "
                                "(%d critiques, %d defects). Forcing repair.",
                                mean_score,
                                threshold,
                                len(scores),
                                defect_count,
                            )
                            self._logger.trace_gate(
                                "critique",
                                triggered=True,
                                reason=f"mean_score={mean_score:.2f} < {threshold:.2f}",
                                iteration=iteration,
                                mean_score=round(mean_score, 4),
                                threshold=threshold,
                                n_critiques=len(scores),
                                defects=defect_count,
                            )
                            state["_critique_repair_required"] = {
                                "mean_score": round(mean_score, 4),
                                "threshold": threshold,
                                "defects": defect_count,
                                "n_critiques": len(scores),
                            }
                            state["_last_manager_feedback"] = (
                                f"COMPLETION REJECTED by critique gate: "
                                f"mean critique score {mean_score:.2f} is "
                                f"below the required {threshold:.2f}. "
                                f"There are {defect_count} unresolved defect(s) "
                                f"across {len(scores)} worker critique(s). "
                                f"You MUST address the defects (re-delegate "
                                f"or repair) before the task can complete."
                            )
                            continue  # force another loop iteration

                # --- Deliverable placeholder gate: reject completion if any
                # required output value or output file still contains obvious
                # placeholders. Catches cases where the manager terminates
                # with `XX%`, `TODO`, `???`, or empty values in the
                # deliverables.
                placeholder_findings = self._scan_placeholders(result)
                if placeholder_findings and self._budget.can_continue()[0]:
                    logger.warning(
                        "Manager tried to COMPLETE but %d placeholder(s) "
                        "remain in deliverables: %s",
                        len(placeholder_findings),
                        placeholder_findings[:5],
                    )
                    self._logger.trace_gate(
                        "placeholder",
                        triggered=True,
                        reason=f"{len(placeholder_findings)} placeholder(s) found",
                        iteration=iteration,
                        sample=placeholder_findings[:3],
                    )
                    state["_placeholder_repair_required"] = placeholder_findings[:20]
                    state["_last_manager_feedback"] = (
                        f"COMPLETION REJECTED: {len(placeholder_findings)} "
                        f"placeholder value(s) found in deliverables that "
                        f"must be replaced with real content. Examples: "
                        + "; ".join(placeholder_findings[:8])
                    )
                    continue  # force another loop iteration

                # --- Final output gate: reject completion if critical
                # placeholder files exist (1x1 PNGs, empty PDFs, etc.)
                file_warnings = self._validate_output_files()
                if file_warnings:
                    from .file_validator import classify_warning_severity
                    critical = [
                        w for w in file_warnings
                        if self._classify_output_warning(w) == "critical"
                    ]
                    if critical and self._budget.can_continue()[0]:
                        logger.warning(
                            "Manager tried to COMPLETE but %d critical "
                            "output files are broken: %s",
                            len(critical),
                            critical[:5],
                        )
                        self._logger.trace_gate(
                            "file",
                            triggered=True,
                            reason=f"{len(critical)} critical broken file(s)",
                            iteration=iteration,
                            files=critical[:5],
                        )
                        # Inject the broken-file feedback into state so
                        # the manager sees it on the next iteration and
                        # delegates a repair worker.
                        state["_file_repair_required"] = critical
                        state["_last_manager_feedback"] = (
                            f"COMPLETION REJECTED: {len(critical)} output "
                            f"file(s) are placeholder/broken and MUST be "
                            f"regenerated before the task can complete. "
                            f"Broken files: "
                            + "; ".join(critical[:10])
                        )
                        continue  # force another loop iteration

                # --- Deliverable presence gate: if the original task implies
                # a file deliverable (image, document, dataset, ...) but the
                # output dir is empty, reject completion. This catches the
                # "manager declares done after only investigating" pathology.
                missing_deliverable = self._check_missing_deliverable(task)
                if missing_deliverable and self._budget.can_continue()[0]:
                    logger.warning(
                        "Manager tried to COMPLETE but task requires a "
                        "file deliverable and _output_dir is empty: %s",
                        missing_deliverable,
                    )
                    self._logger.trace_gate(
                        "deliverable",
                        triggered=True,
                        reason=missing_deliverable,
                        iteration=iteration,
                    )
                    state["_deliverable_required"] = missing_deliverable
                    state["_last_manager_feedback"] = (
                        f"COMPLETION REJECTED: {missing_deliverable} "
                        f"You must delegate a worker that actually produces "
                        f"the file in `_output_dir` before completing."
                    )
                    continue

                # --- Evaluation gate: score final result before accepting
                if self._eval_engine and self._eval_engine.enabled:
                    final_eval = self._eval_engine.evaluate_final(
                        result=result, state=state, budget=self._budget,
                    )
                    if final_eval:
                        action = self._eval_engine.decide_retry(final_eval)
                        logger.info(
                            "Evaluation gate: score=%.2f action=%s",
                            final_eval.score,
                            action,
                        )
                        if action == "retry_with_repair" and self._budget.can_continue()[0]:
                            self._eval_engine.record_retry()
                            self._logger.trace_gate(
                                "eval",
                                triggered=True,
                                reason=f"score={final_eval.score:.2f} action={action}",
                                iteration=iteration,
                                score=round(final_eval.score, 4),
                            )
                            state["_eval_repair_required"] = {
                                "score": round(final_eval.score, 4),
                                "action": action,
                                "metrics": [
                                    {"name": ms.name, "score": round(ms.score, 4)}
                                    for ms in final_eval.metric_scores
                                ],
                            }
                            state["_last_manager_feedback"] = (
                                f"COMPLETION REJECTED by evaluation: "
                                f"score={final_eval.score:.2f} (threshold="
                                f"{self._eval_engine._config.thresholds.retry:.2f}). "
                                f"Please improve the result quality."
                            )
                            continue  # force another loop iteration
                        elif action == "fail_workflow":
                            result["_evaluation"] = self._eval_engine.get_summary()
                            self._eval_engine.flush()
                            return result, "eval_fail"
                        else:
                            result["_evaluation"] = self._eval_engine.get_summary()
                    self._eval_engine.flush()

                self._logger.log_iteration(
                    iteration,
                    manager_decision,
                    [],
                    self._budget,
                    [],
                )
                # Append-only protection: if any earlier snapshot held
                # better (=larger) versions of the deliverables, restore them.
                try:
                    self._restore_best_deliverables()
                except Exception as exc:
                    logger.debug("deliverable restore failed: %s", exc)
                return result, "complete"

            if decision_type == "fail":
                reason = manager_decision.get("reason", "Manager decided to fail")
                is_parse_failure = "missing 'decision' field" in reason
                # If this is a parse failure (not an explicit manager fail)
                # and we have accumulated work, return partial result instead
                # of discarding everything.
                if is_parse_failure and self._history:
                    logger.warning(
                        "Manager parse failure after %d iterations — "
                        "returning partial result instead of hard fail",
                        len(self._history),
                    )
                    partial = self._build_partial_result(f"manager_parse_failure: {reason}")
                    partial["partial_result"] = manager_decision.get("partial_result", {})
                    return partial, "partial_complete"
                return {
                    "error": reason,
                    "partial_result": manager_decision.get("partial_result", {}),
                    "confidence": 0.0,
                }, "fail"

            if decision_type == "retry":
                # Retry signal from _parse_manager_output (e.g. all
                # delegations were truncated).  Just continue the loop so
                # the manager gets another chance.
                logger.warning("Manager requested retry — continuing loop")
                continue

            if decision_type not in ("delegate",):
                logger.warning("Unknown decision: %s, treating as fail", decision_type)
                if self._history:
                    return self._build_partial_result(
                        f"unknown_decision: {decision_type}"
                    ), "partial_complete"
                return {
                    "error": f"Unknown decision: {decision_type}",
                    "confidence": 0.0,
                }, "fail"

            # 3. Execute delegations (fan-out)
            # Reset consecutive-diagnose counter on actual delegation.
            # Apply cooldown: after a diagnose lock, require 2 delegations
            # before allowing diagnose again to prevent diagnose→delegate→diagnose loops.
            if state.get("_consecutive_diagnoses", 0) >= 2:
                state["_diagnose_cooldown"] = 2  # must delegate 2x before diagnosing again
            state.pop("_consecutive_diagnoses", None)
            state.pop("_diagnose_locked", None)
            # Decrement cooldown counter
            cooldown = state.get("_diagnose_cooldown", 0)
            if cooldown > 0:
                state["_diagnose_cooldown"] = cooldown - 1

            envelopes = manager_decision.get("delegations", [])
            if not envelopes:
                logger.warning("Manager returned DELEGATE with no delegations")
                continue

            # P3: Convergence detector — if confidence has stalled, force a
            # partial complete instead of dispatching yet another round.
            if self._check_convergence(iteration):
                partial = self._build_partial_result("forced_convergence")
                partial["partial"] = True
                partial["reason"] = "forced_convergence"
                return partial, "complete"

            # P4: Compute the delegation signature and detect redundancy.
            current_sig = self._delegation_signature(envelopes)
            is_redundant = current_sig in self._past_delegation_signatures

            # P1: Critique gate also for DELEGATE — if the last iteration's
            # mean critique score is below threshold AND the manager wants
            # to re-issue the same logical subtasks, force a repair path
            # by overriding the decision to DIAGNOSE.
            if (
                is_redundant
                and self._critique_engine
                and self._critique_engine.enabled
                and self._history
            ):
                last = self._history[-1] if self._history else {}
                critique_entries = last.get("critique") or []
                scores: list[float] = []
                for ce in critique_entries:
                    s = ce.get("score") if isinstance(ce, dict) else None
                    if isinstance(s, (int, float)):
                        scores.append(float(s))
                threshold = float(
                    getattr(self._config.critique, "min_score_to_complete", 0.6)
                )
                if scores:
                    mean_score = sum(scores) / len(scores)
                    if mean_score < threshold:
                        logger.warning(
                            "P1/P4: blocking re-delegation of identical "
                            "subtasks (sig=%s) — mean critique %.2f < %.2f. "
                            "Overriding DELEGATE → DIAGNOSE.",
                            current_sig[:1], mean_score, threshold,
                        )
                        state["_critique_blocking_redelegate"] = (
                            f"FORBIDDEN: re-delegate same subtasks. You MUST "
                            f"choose diagnose, repair, or complete. Mean "
                            f"critique score {mean_score:.2f} is below "
                            f"required {threshold:.2f}."
                        )
                        # Hard override: skip dispatch this iteration so the
                        # manager is forced into a different decision next.
                        continue

            # Baustein 4: a redundant dispatch (same signature already
            # seen) is an antipattern — record it for the curator.
            if is_redundant:
                first_instr = ""
                try:
                    if envelopes and isinstance(envelopes[0], dict):
                        first_instr = str(envelopes[0].get("instructions", ""))
                except Exception:
                    first_instr = ""
                self._failed_signatures.append(
                    {
                        "signature": "|".join(current_sig),
                        "reason": "redundant",
                        "iteration": iteration,
                        "instructions": first_instr,
                    }
                )

            # Record signature now that we are committed to dispatching.
            self._past_delegation_signatures.append(current_sig)

            # Track delegation history to detect repeated same-worker patterns
            if "_delegation_history" not in state:
                state["_delegation_history"] = {}
            repeated_warnings = []
            for env in envelopes:
                wid = env.get("worker_id", env.get("id", ""))
                if wid:
                    hist = state["_delegation_history"]
                    hist[wid] = hist.get(wid, 0) + 1
                    if hist[wid] >= 3:
                        logger.warning(
                            "Worker '%s' delegated %d times — likely stuck",
                            wid, hist[wid],
                        )
                        repeated_warnings.append(
                            f"Worker '{wid}' has been delegated {hist[wid]} times "
                            f"with no satisfactory result. You MUST change the "
                            f"approach: use a DIFFERENT worker_id, change the "
                            f"instructions substantially, or fix the root cause "
                            f"identified in earlier failures."
                        )
            if repeated_warnings:
                state["_repeated_delegation_warning"] = "\n".join(repeated_warnings)
                # Feed stall detector with zero confidence for repeated patterns
                if self._stall:
                    stall_status = self._stall.record(0.0, "repeated_worker_delegation")
                    if stall_status == "stop":
                        return self._build_partial_result(
                            "stall_detected_repeated_delegations"
                        ), "stall_detected"
            else:
                state.pop("_repeated_delegation_warning", None)

            self._profiler.start(f"workers.iter_{iteration}")
            self._current_iteration = iteration  # for tool-call debug logging
            delegation_results = self._execute_delegations(
                envelopes, task, state, iteration=iteration
            )
            self._profiler.stop(
                f"workers.iter_{iteration}",
                iteration=iteration,
                worker_count=len(envelopes),
            )

            # Baustein 4: record per-worker failures as antipatterns so
            # the curator can surface them on the next run.
            try:
                for dr in delegation_results or []:
                    if not isinstance(dr, dict):
                        continue
                    res = dr.get("result") if isinstance(dr.get("result"), dict) else {}
                    status = dr.get("status", "")
                    conf = res.get("confidence") if isinstance(res, dict) else None
                    conf_f = float(conf) if isinstance(conf, (int, float)) else None
                    reason: Optional[str] = None
                    if status == "error" or (isinstance(res, dict) and "error" in res):
                        reason = "error"
                    elif conf_f is not None and conf_f < 0.3:
                        reason = "low_confidence"
                    if reason is None:
                        continue
                    env = dr.get("envelope") or {}
                    single_sig = self._delegation_signature([env])
                    self._failed_signatures.append(
                        {
                            "signature": "|".join(single_sig),
                            "reason": reason,
                            "iteration": iteration,
                            "instructions": str(env.get("instructions", ""))[:500],
                        }
                    )
            except Exception as _exc:  # noqa: BLE001
                logger.debug("failed-signature tracking skipped: %s", _exc)

            # 4. Critique phase (Reflective Critique Loop)
            critique_envelopes = []
            if self._critique_engine and self._critique_engine.enabled:
                self._profiler.start(f"critique.iter_{iteration}")
                critique_envelopes = self._critique_and_repair(
                    delegation_results, task, state, iteration
                )
                self._profiler.stop(
                    f"critique.iter_{iteration}",
                    iteration=iteration,
                    worker_count=len(delegation_results),
                )

            # 5. Validate results (2-tier)
            validation_results = self._validate_results(delegation_results, task)

            # (Step evaluation is now done inside _execute_delegations before file write)

            # 6. Write budget snapshot immediately (for file watchers)
            self._profiler.start(f"logging.iter_{iteration}")
            self._logger.log_iteration_budget(iteration, self._budget)

            # 6b. Log full iteration (artifacts, tools, critique, etc.)
            self._logger.log_iteration(
                iteration,
                manager_decision,
                delegation_results,
                self._budget,
                validation_results,
            )
            self._profiler.stop(f"logging.iter_{iteration}")

            # 6c. Log critique data if present
            if critique_envelopes:
                self._logger.log_critique(
                    iteration,
                    [c.to_dict() for c in critique_envelopes],
                    self._critique_engine.get_summary() if self._critique_engine else {},
                )

            # 7. Aggregate into history
            agg_confidence = self._aggregate_confidence(delegation_results)
            key_findings = self._extract_key_findings(delegation_results)

            history_entry: dict[str, Any] = {
                "iteration": iteration,
                "confidence": agg_confidence,
                "key_findings": key_findings,
                "worker_count": len(delegation_results),
                "validation": validation_results,
            }
            if critique_envelopes:
                history_entry["critique"] = [c.to_dict() for c in critique_envelopes]
                history_entry["critique_summary"] = (
                    self._critique_engine.get_manager_critique_summary(critique_envelopes)
                    if self._critique_engine
                    else ""
                )
            self._history.append(history_entry)

            # 7b. Build + persist the Hierarchical Context Digest for
            # this iteration. Deterministic (no LLM): goal carries from
            # prior digest or falls back to the original task; key facts
            # come from high-confidence worker outputs; open questions
            # from low-confidence or explicit `open_questions` fields.
            if self._digest_store is not None:
                mode = getattr(self._config, "digest_mode", "deterministic")
                if mode == "llm":
                    raise NotImplementedError(
                        "digest_mode='llm' is reserved for a future version"
                    )
                if mode != "deterministic":
                    logger.warning(
                        "Unknown digest_mode=%r, falling back to deterministic",
                        mode,
                    )
                try:
                    from .digest import build_digest_from_iteration as _build_digest
                    new_digest = _build_digest(
                        history_entry=history_entry,
                        prior_digest=self._current_digest,
                        run_id=self._run_id,
                        iteration=iteration,
                        delegation_results=delegation_results,
                        original_task=task,
                    )
                    # Fold in any child digest hashes collected from
                    # submanagers that returned in this iteration.
                    if self._pending_child_digest_hashes:
                        prior_children = (
                            list(self._current_digest.child_digest_hashes)
                            if self._current_digest is not None
                            else []
                        )
                        new_digest.child_digest_hashes = (
                            prior_children + list(self._pending_child_digest_hashes)
                        )
                        self._pending_child_digest_hashes = []
                    elif self._current_digest is not None:
                        new_digest.child_digest_hashes = list(
                            self._current_digest.child_digest_hashes
                        )
                    sha = self._digest_store.put(new_digest)
                    self._current_digest = new_digest
                    self._current_digest_sha = sha
                    logger.debug(
                        "Digest iter=%d sha=%s facts=%d questions=%d",
                        iteration, sha[:12], len(new_digest.key_facts),
                        len(new_digest.open_questions),
                    )
                except NotImplementedError:
                    raise
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Digest build failed: %s", exc)

            # 6d. Snapshot deliverables so a later worker that overwrites
            # `workspace/outputs/` cannot regress earlier good results.
            try:
                self._snapshot_deliverables(iteration)
            except Exception as exc:
                logger.debug("deliverable snapshot failed: %s", exc)

            # 7. Update rolling summary
            window = self._config.history.full_results_window
            self._logger.update_rolling_summary(
                iteration,
                agg_confidence,
                key_findings,
                self._history,
                window,
            )

            # 8. Update state with results (strip internal fields to avoid
            #    polluting manager context with tooling traces)
            _INTERNAL_PREFIXES = ("_tool_calls", "_critique", "_eval", "_repair", "tools_created")
            for dr in delegation_results:
                wid = dr.get("worker_id", "")
                if wid:
                    raw = dr.get("result", {})
                    if isinstance(raw, dict):
                        state[wid] = {
                            k: v for k, v in raw.items()
                            if not any(k.startswith(p) for p in _INTERNAL_PREFIXES)
                        }
                    else:
                        state[wid] = raw

            # 8b. Record outcomes in decision journal (Manager Intelligence)
            if self._journal:
                outcomes = {}
                for dr in delegation_results:
                    wid = dr.get("worker_id", "")
                    conf = dr.get("result", {}).get("confidence", 0.0)
                    if wid:
                        outcomes[wid] = conf if isinstance(conf, (int, float)) else 0.0
                self._journal.record_outcome(iteration, outcomes)

            # 8c. Update task plan status (Manager Intelligence)
            if self._task_plan:
                # Register explicit subtask_id mappings from delegation envelopes
                for env in envelopes:
                    env_wid = env.get("worker_id", env.get("id", ""))
                    env_stid = env.get("subtask_id", "")
                    if env_wid and env_stid:
                        self._task_plan.register_worker_mapping(env_wid, env_stid)
                for dr in delegation_results:
                    wid = dr.get("worker_id", "")
                    result = dr.get("result", {})
                    conf = result.get("confidence", 0.0)
                    status = "completed" if isinstance(conf, (int, float)) and conf > 0.3 else "failed"
                    summary = str(result.get("key_finding", result.get("summary", "")))[:60]
                    self._task_plan.update_status(wid, status, summary)
                    self._task_plan.record_iteration(wid)
                # Force-advance subtasks stuck for too many iterations.
                # If recursive delegation is allowed (max_depth > current
                # depth), PROMOTE the stuck subtask to a submanager instead
                # of force-completing — this gives it a fresh budget window
                # under a dedicated child runner. The parent loop still
                # makes progress because the iteration counter is reset
                # AND any new stall in the child propagates upward as a
                # failed delegation, which we will then force-complete.
                can_promote = self._depth < self._budget.max_depth
                advanced = self._task_plan.force_advance_stuck(
                    promote_to_submanager=can_promote
                )
                if advanced:
                    if can_promote:
                        logger.warning(
                            "Auto-promoted stuck subtasks to submanagers: %s",
                            ", ".join(advanced),
                        )
                        state["_subtask_advanced"] = (
                            f"Subtasks {', '.join(advanced)} were AUTO-PROMOTED "
                            f"to submanagers after {TaskPlan.MAX_SUBTASK_ITERATIONS} "
                            f"stuck iterations. Your NEXT DELEGATE for any of "
                            f"these subtasks MUST set `as_submanager: true` so "
                            f"the runtime spawns a dedicated child loop with a "
                            f"reserved budget."
                        )
                    else:
                        logger.warning(
                            "Auto-advanced stuck subtasks (max_depth reached): %s",
                            ", ".join(advanced),
                        )
                        state["_subtask_advanced"] = (
                            f"Subtasks {', '.join(advanced)} were AUTO-ADVANCED "
                            f"after {TaskPlan.MAX_SUBTASK_ITERATIONS} iterations. "
                            f"Recursion depth limit reached — use best available "
                            f"results and proceed to the NEXT subtask. Do NOT "
                            f"re-delegate work for these subtasks."
                        )

            # 8d. Update hypothesis status (Manager Intelligence)
            if state.get("_active_hypotheses") and self._diagnosis_enabled:
                for dr in delegation_results:
                    wid = dr.get("worker_id", "")
                    result = dr.get("result", {})
                    # Check if worker was a diagnostic worker
                    for h in state["_active_hypotheses"]:
                        if h.get("test_worker") == wid:
                            conf = result.get("confidence", 0.0)
                            h["status"] = "confirmed" if isinstance(conf, (int, float)) and conf > 0.5 else "refuted"

            # 8e. Detect low-confidence workers for diagnosis hint (Manager Intelligence)
            if self._diagnosis_enabled:
                low_conf_workers = [
                    dr.get("worker_id", "?")
                    for dr in delegation_results
                    if isinstance(dr.get("result", {}).get("confidence"), (int, float))
                    and dr["result"]["confidence"] < self._diagnosis_threshold
                ]
                if low_conf_workers:
                    state["_diagnosis_suggested"] = low_conf_workers

            # 8f. Budget phase auto-transition (Manager Intelligence)
            budget_remaining = self._budget.budget_fraction_remaining
            if self._budget._reservation and self._budget._reservation.enabled:
                # Auto-transition based on budget consumption
                phase = self._budget.current_phase
                if phase == "core_work" and budget_remaining < 0.40:
                    self._budget.transition_phase("validation_repair", iteration)
                    logger.info("Budget phase transition: core_work → validation_repair")
                elif phase == "validation_repair" and budget_remaining < 0.20:
                    self._budget.transition_phase("synthesis", iteration)
                    logger.info("Budget phase transition: validation_repair → synthesis")
                elif phase == "synthesis" and budget_remaining < 0.05:
                    self._budget.transition_phase("reserve", iteration)
                    logger.info("Budget phase transition: synthesis → reserve")

            # 9. Stall detection (with strategy switching)
            if self._stall:
                stall_status = self._stall.record(agg_confidence, key_findings)
                if stall_status == "switch_strategy":
                    strategy = self._stall.suggested_strategy
                    state["_strategy_override"] = strategy
                    logger.warning(
                        "Stall detected — switching to strategy: %s", strategy
                    )
                elif stall_status == "stop":
                    logger.warning("Stall detected — stopping loop (all strategies exhausted)")
                    return self._build_partial_result(
                        "stall_detected"
                    ), "stall_detected"
                elif stall_status == "warn":
                    logger.warning("Stall warning — confidence not improving")

    # -- Manager execution ------------------------------------------------

    def _run_manager(self, task: str, state: dict, iteration: int) -> dict:
        """Execute the manager agent to get a delegation decision."""
        manager_dir = self._dir / self._config.manager
        if not manager_dir.exists():
            # Inline manager — create system prompt dynamically
            return self._run_inline_manager(task, state, iteration)

        # Use agent.py (or StandaloneAgent fallback) for the manager
        try:
            llm = self._manager_llm or LLMClient(model=self._manager_model)
            tokens_before = llm.total_tokens_used
            agent = self._load_agent(manager_dir, llm=llm)

            # Build enhanced task with context
            enhanced_task = self._build_manager_task(task, state, iteration)
            result = agent.run(enhanced_task, state)
            self._budget.tokens_consumed += llm.total_tokens_used - tokens_before

            # Extract the manager's output
            manager_output = result.get(agent.name, {})

            # If the agent returned a wrapped non-JSON result, try to extract
            # the actual JSON from the "result" field (LLM may have returned
            # JSON wrapped in markdown or extra text)
            if (
                isinstance(manager_output, dict)
                and "result" in manager_output
                and "decision" not in manager_output
            ):
                raw_text = manager_output.get("result", "")
                if isinstance(raw_text, str) and "{" in raw_text:
                    extracted = self._parse_json_response(raw_text)
                    if "decision" in extracted or "delegations" in extracted:
                        manager_output = extracted

            parsed = self._parse_manager_output(manager_output)

            # If parsing failed or needs retry, fall back to inline manager
            _needs_retry = (
                (parsed.get("decision") == "fail"
                 and "missing 'decision' field" in parsed.get("reason", ""))
                or parsed.get("decision") == "retry"
            )
            if _needs_retry:
                logger.warning(
                    "Agent manager returned unparseable output, "
                    "falling back to inline manager"
                )
                return self._run_inline_manager(task, state, iteration)

            return parsed

        except Exception as exc:
            logger.error("Manager execution failed: %s", exc)
            return {"decision": "fail", "reason": str(exc)}

    def _run_inline_manager(self, task: str, state: dict, iteration: int) -> dict:
        """Run manager with inline prompting (no agent.awp.yaml required).

        Retries once with a shorter prompt if the first attempt fails to
        produce a parseable decision (truncated JSON is the #1 cause).
        """
        llm = self._manager_llm or LLMClient(model=self._manager_model)
        tokens_before = llm.total_tokens_used

        system_prompt = self._build_manager_system_prompt()
        user_message = self._build_manager_task(task, state, iteration)

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ]

        for attempt in range(2):
            try:
                # Use streaming on first attempt for faster TTFT
                if attempt == 0:
                    try:
                        result = llm.chat_stream_json(
                            messages, temperature=0.2, max_tokens=16384
                        )
                    except Exception:
                        # Streaming not supported — fall back to non-streaming
                        result = llm.chat_json(
                            messages, temperature=0.2, max_tokens=16384
                        )
                else:
                    result = llm.chat_json(
                        messages, temperature=0.2, max_tokens=16384
                    )
                self._budget.tokens_consumed += llm.total_tokens_used - tokens_before
                tokens_before = llm.total_tokens_used
                parsed = self._parse_manager_output(result)

                _is_parse_fail = (
                    parsed.get("decision") == "fail"
                    and "missing 'decision' field" in parsed.get("reason", "")
                ) or parsed.get("decision") == "retry"

                if _is_parse_fail and attempt == 0:
                    logger.warning(
                        "Inline manager attempt %d returned unparseable "
                        "output, retrying with clarification",
                        attempt + 1,
                    )
                    # Add a clarification message to guide the LLM
                    messages.append({"role": "assistant", "content": json.dumps(result, default=str)[:2000]})
                    messages.append({
                        "role": "user",
                        "content": (
                            "Your previous response could not be parsed as a "
                            "valid decision. Please respond with a SHORT JSON "
                            "object containing exactly one of:\n"
                            '- {"decision": "delegate", "delegations": [...]}\n'
                            '- {"decision": "complete", "final_result": {...}}\n'
                            '- {"decision": "fail", "reason": "..."}\n'
                            "Keep delegations concise to avoid truncation."
                        ),
                    })
                    continue

                return parsed

            except Exception as exc:
                self._budget.tokens_consumed += llm.total_tokens_used - tokens_before
                tokens_before = llm.total_tokens_used
                if attempt == 0:
                    logger.warning("Inline manager attempt 1 failed: %s, retrying", exc)
                    continue
                logger.error("Inline manager failed after retry: %s", exc)
                return {"decision": "fail", "reason": str(exc)}

        # Should not reach here, but safety fallback
        return {"decision": "fail", "reason": "Inline manager exhausted retries"}

    # -- Manager Intelligence prompt helpers ---------------------------------

    def _build_intelligence_decision_options(self) -> str:
        """Build optional PLAN and DIAGNOSE decision options for the system prompt."""
        parts: list[str] = []

        if self._planning_enabled:
            parts.append("""
### PLAN — Create a task decomposition (first iteration recommended)
```json
{
  "decision": "plan",
  "reasoning": "Breaking the task into subtasks for systematic execution",
  "subtasks": [
    {
      "id": "subtask_1",
      "description": "What this subtask accomplishes",
      "dependencies": [],
      "priority": "high",
      "success_criteria": "How to know this subtask is done",
      "delegation_strategy": "worker",
      "submanager_agent": null
    }
  ]
}
```
Use PLAN **once** on the first iteration to decompose the problem before delegating.
You can only PLAN once — after that, use DELEGATE to execute the plan.
After planning, you will see a Task Plan Progress section tracking subtask status.
**CRITICAL: In every DELEGATE decision, include `"subtask_id": "subtask_X"` in each delegation envelope to link the worker to a plan subtask.** This enables automatic progress tracking. Without `subtask_id`, the plan cannot track which subtasks are done.
**A4 — Submanager autonomous decision (REQUIRED on every subtask):**
For EACH subtask you plan, set `"delegation_strategy"` to either
`"worker"` (single ephemeral worker is enough) or `"submanager"` (the
subtask needs its own iteration loop with sub-workers). Use this
deterministic decision tree:

  Use `"submanager"` when ALL of these hold:
  - The subtask is independent of others (no `dependencies`) so it can
    run in parallel with siblings.
  - The subtask description names ≥ 3 distinct deliverables OR contains
    keywords like "research", "investigate", "validate", "iteratively",
    "comprehensive", "end-to-end", "multi-step", "build and test".
  - A single worker round would not plausibly complete the work — the
    subtask needs intermediate decisions, retries, or self-evaluation.

  Use `"worker"` when ANY of these hold:
  - The subtask is a single computation, data load, or transformation.
  - The subtask depends on the output of another subtask (linear DAG).
  - The work fits in a single `code.execute` call.

If you set `"delegation_strategy": "submanager"`, you MAY also set
`"submanager_agent": "agents/specialist"` to use a different manager
agent for the sub-loop (defaults to the parent's manager). The runtime
spawns a child DelegationLoopRunner with a hard-capped budget fraction
of the parent. If `max_depth` would be exceeded, the field is silently
ignored and a normal worker runs instead — the loop never hangs.

**Defense in depth**: If you forget to set `delegation_strategy`, the
runtime will score each independent subtask for complexity (description
length, keyword presence, deliverable count, priority) and auto-promote
the ones above the threshold. You don't have to worry about getting
this perfectly right — but explicit choices are honoured over the
heuristic.
**IMPORTANT: Do NOT issue PLAN again after the first iteration. Use DELEGATE instead.**
**IMPORTANT: If a subtask is marked as STUCK or AUTO-ADVANCED, do NOT retry it. Move to the next subtask immediately.**
""")

        if self._diagnosis_enabled:
            parts.append(f"""
### DIAGNOSE — Generate failure hypotheses before retrying
```json
{{
  "decision": "diagnose",
  "reasoning": "Worker failed — generating hypotheses before retrying",
  "failed_worker": "worker_id_that_failed",
  "hypotheses": [
    {{
      "id": "h1",
      "cause": "Description of suspected root cause",
      "test": "How to test this hypothesis",
      "likelihood": 0.7
    }}
  ]
}}
```
Use DIAGNOSE when a worker produces confidence < {self._diagnosis_threshold} or fails entirely.
Generate up to {self._diagnosis_max_hypotheses} hypotheses. On the next iteration, delegate
targeted workers to test the most likely hypotheses before doing a full retry.
""")

        return "\n".join(parts)

    def _build_intelligence_task_sections(self, state: dict, iteration: int) -> str:
        """Build all Manager Intelligence sections for the user message."""
        parts: list[str] = []

        # Plan-locked warning (prevents PLAN loops). Consume-once: if the
        # next iteration also stalls in PLAN the gate will set this fresh.
        plan_lock = state.pop("_plan_locked", None)
        if plan_lock:
            parts.append(
                f"## PLAN LOCKED\n"
                f"**{plan_lock}**\n"
            )

        # R31 Plan-Tool-Closure feedback (consume-once). Surfaced when the
        # previous PLAN was rejected for missing/invalid tool_manifest.
        r31_feedback = state.pop("_r31_feedback", None)
        if r31_feedback:
            parts.append(
                f"## ⚠ PLAN REJECTED — R31 Plan-Tool-Closure\n"
                f"{r31_feedback}\n"
            )

        # Diagnose-locked warning (prevents DIAGNOSE loops)
        diag_lock = state.get("_diagnose_locked")
        if diag_lock:
            parts.append(
                f"## DIAGNOSE LOCKED\n"
                f"**{diag_lock}**\n"
            )

        # Subtask auto-advanced warning
        subtask_advanced = state.get("_subtask_advanced")
        if subtask_advanced:
            parts.append(
                f"## ⚠ SUBTASKS AUTO-ADVANCED\n"
                f"**{subtask_advanced}**\n"
            )

        # Task Plan Progress
        if self._task_plan:
            section = self._task_plan.to_prompt_section()
            if section:
                parts.append(section)

        # Budget Phase
        if self._budget._reservation and self._budget._reservation.enabled:
            phase = self._budget.current_phase
            phase_remaining = self._budget.phase_budget_remaining()
            warning = self._budget.phase_warning()
            phase_section = (
                f"## Budget Phase\n"
                f"- **Current phase**: {phase}\n"
                f"- **Phase budget remaining**: {phase_remaining * 100:.0f}%\n"
            )
            if warning:
                phase_section += f"- **Warning**: {warning}\n"
            parts.append(phase_section)

        # Active Hypotheses (Diagnosis)
        hypotheses = state.get("_active_hypotheses")
        if hypotheses and self._diagnosis_enabled:
            lines = ["## Active Hypotheses\n"]
            lines.append("| ID | Cause | Likelihood | Status |")
            lines.append("|----|-------|------------|--------|")
            for h in hypotheses:
                status = h.get("status", "untested")
                lines.append(
                    f"| {h.get('id', '?')} | {h.get('cause', '')[:60]} "
                    f"| {h.get('likelihood', '?')} | **{status}** |"
                )
            confirmed = [h for h in hypotheses if h.get("status") == "confirmed"]
            if confirmed:
                lines.append(
                    f"\n**Confirmed cause(s)**: "
                    + ", ".join(h.get("cause", "?") for h in confirmed)
                    + ". Use this to inform your next delegation.\n"
                )
            parts.append("\n".join(lines))

        # Diagnosis suggestion
        suggested = state.get("_diagnosis_suggested")
        if suggested and self._diagnosis_enabled:
            parts.append(
                f"## Diagnosis Suggested\n"
                f"Worker(s) {', '.join(suggested)} produced low confidence "
                f"(< {self._diagnosis_threshold}). Consider using DIAGNOSE to "
                f"generate hypotheses before retrying.\n"
            )

        # Strategy Directive
        strategy = state.get("_strategy_override")
        if strategy:
            strategy_descriptions = {
                "decompose_finer": (
                    "Break current work into smaller, more specific subtasks. "
                    "Each worker should handle one narrow piece."
                ),
                "simplify": (
                    "Reduce scope — solve a simpler version of the problem first, "
                    "then extend the solution incrementally."
                ),
                "reframe": (
                    "Reformulate the problem from a different angle. "
                    "Try a fundamentally different approach."
                ),
                "escalate": (
                    "Use more powerful tools, higher temperature, or a "
                    "completely different methodology."
                ),
            }
            desc = strategy_descriptions.get(
                strategy, "Change your approach to break through the stall."
            )
            parts.append(
                f"## Strategy Directive (Stall Recovery)\n"
                f"**Active strategy: `{strategy}`**\n\n{desc}\n\n"
                f"Your previous approach was not making progress. "
                f"You MUST change your delegation strategy according to "
                f"the directive above.\n"
            )

        # Decision Journal
        if self._journal:
            section = self._journal.to_prompt_section()
            if section:
                parts.append(section)

        return "\n".join(parts)

    def _build_namespace_capabilities_section(self) -> str:
        """Build a section describing per-namespace capabilities for the manager prompt."""
        factory = getattr(self._tools, "_dynamic_tool_factory", None) if self._tools else None
        if not factory or not getattr(factory, "_namespace_configs", None):
            return ""

        lines = ["\n## Namespace Capabilities"]
        for ns_name, ns_cfg in factory._namespace_configs.items():
            caps = ns_cfg.get("capabilities", ["compute"])
            allowlist = ns_cfg.get("network_allowlist", [])
            line = f"- **{ns_name}**: {', '.join(caps)}"
            if allowlist:
                line += f" (network restricted to: {', '.join(allowlist)})"
            lines.append(line)
        lines.append("")
        return "\n".join(lines)

    def _build_dynamic_tools_section(self) -> str:
        """Build a section listing all registered dynamic tools for the manager prompt."""
        if not self._tools:
            return ""
        dynamic = getattr(self._tools, "_dynamic_tools", {})
        if not dynamic:
            return ""

        lines = ["\n## Available Dynamic Tools (from previous runs)\n"]
        lines.append(
            "These tools are already registered and can be added to any worker's "
            "`tools_allowed` list. Use `\"dynamic.*\"` to give a worker ALL dynamic tools, "
            "or list specific ones like `\"dynamic.my_tool\"`.\n"
        )
        for fqn in sorted(dynamic.keys()):
            defn = self._tools._definitions.get(fqn)
            desc = ""
            if defn and "function" in defn:
                desc = defn["function"].get("description", "")[:120]
            creator = dynamic[fqn].get("creator", "")
            lines.append(f"- **`{fqn}`**: {desc}")
            if creator:
                lines.append(f"  _(created by: {creator})_")
        lines.append("")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Skill Registry — persist, catalog, lazy-load
    # ------------------------------------------------------------------

    @property
    def _skills_dir(self) -> Path:
        return self._dir / "workspace" / "skills"

    @staticmethod
    def _skill_name_from_content(content: str) -> str:
        """Extract a slug name from the first heading of a skill markdown."""
        for line in content.splitlines():
            line = line.strip()
            if line.startswith("# "):
                title = line.lstrip("# ").strip()
                # Remove "Skill:" prefix if present
                if title.lower().startswith("skill:"):
                    title = title[6:].strip()
                # Slugify
                import re as _re
                slug = _re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_")
                return slug[:60] if slug else "unnamed_skill"
        return "unnamed_skill"

    @staticmethod
    def _skill_description_from_content(content: str) -> str:
        """Extract a one-line description from the Purpose section."""
        in_purpose = False
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.lower().startswith("## purpose"):
                in_purpose = True
                continue
            if in_purpose:
                if stripped.startswith("##"):
                    break
                if stripped:
                    return stripped[:150]
        # Fallback: first non-heading non-empty line
        for line in content.splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                return stripped[:150]
        return ""

    def _persist_skill(self, name: str, content: str) -> None:
        """Save a skill to workspace/skills/{name}.md (latest wins)."""
        self._skills_dir.mkdir(parents=True, exist_ok=True)
        path = self._skills_dir / f"{name}.md"
        path.write_text(content, encoding="utf-8")
        logger.info("Persisted skill: %s (%d chars)", name, len(content))

    def _load_skill_catalog(self) -> dict[str, str]:
        """Return {name: one-line description} for all persisted skills."""
        catalog: dict[str, str] = {}
        if not self._skills_dir.is_dir():
            return catalog
        for path in sorted(self._skills_dir.glob("*.md")):
            name = path.stem
            try:
                content = path.read_text(encoding="utf-8")
                desc = self._skill_description_from_content(content)
                catalog[name] = desc
            except OSError:
                catalog[name] = ""
        return catalog

    def _resolve_skills(self, skills: list) -> list[str]:
        """Resolve skill entries: short names → load from disk, full markdown → pass through.

        Also persists any new/updated inline skills.
        """
        resolved: list[str] = []
        for entry in skills:
            if not isinstance(entry, str) or not entry.strip():
                continue
            stripped = entry.strip()
            # Full markdown skill (has heading or >80 chars) → use as-is + persist
            if stripped.startswith("#") or len(stripped) > 80:
                name = self._skill_name_from_content(stripped)
                self._persist_skill(name, stripped)
                resolved.append(stripped)
            else:
                # Short name reference → load from disk
                slug = stripped.replace(" ", "_").lower()
                path = self._skills_dir / f"{slug}.md"
                if path.is_file():
                    content = path.read_text(encoding="utf-8")
                    resolved.append(content)
                    logger.info("Loaded skill by name: %s", slug)
                else:
                    # Not found — treat as inline skill fragment
                    logger.warning("Skill '%s' not found in registry, passing as-is", slug)
                    resolved.append(stripped)
        return resolved

    def _persist_worker_result_skills(self, worker_result: dict, worker_id: str) -> None:
        """Persist skills from a worker's result to the skill registry."""
        result_skills = worker_result.get(
            "skills_created", worker_result.get("skills", [])
        )
        if not isinstance(result_skills, list):
            return
        for skill in result_skills:
            content = ""
            if isinstance(skill, str) and skill.strip():
                content = skill.strip()
            elif isinstance(skill, dict):
                content = skill.get("content", skill.get("text", ""))
            if content and len(content.split()) >= 30:
                name = self._skill_name_from_content(content)
                self._persist_skill(name, content)

    def _build_skill_catalog_section(self) -> str:
        """Build a section listing all persisted skills for the manager prompt."""
        catalog = self._load_skill_catalog()
        if not catalog:
            return ""
        lines = ["\n## Available Skills (reusable from previous runs)\n"]
        lines.append(
            "Reference these by name in a worker's `skills` array instead of writing "
            "them inline. The runtime will load the full content automatically.\n"
            "To **update** a skill, provide the full markdown with the same `# Skill: Name` "
            "heading — it will overwrite the previous version.\n"
        )
        for name, desc in catalog.items():
            lines.append(f"- **`{name}`**: {desc}" if desc else f"- **`{name}`**")
        lines.append("")
        return "\n".join(lines)

    def _build_namespace_import_rules(self, namespace: str) -> str:
        """Build import rules for a namespace, reflecting its capabilities."""
        factory = getattr(self._tools, "_dynamic_tool_factory", None) if self._tools else None
        if factory and namespace in getattr(factory, "_namespace_configs", {}):
            caps = factory.get_namespace_capabilities(namespace)
            allowlist = factory.get_network_allowlist(namespace)
            lines = ["- NEVER import os, subprocess, sys, ctypes, importlib, signal, or multiprocessing\n"]
            if "network" in caps:
                if allowlist:
                    lines.append(f"- Network access ALLOWED (restricted to: {', '.join(allowlist)}). You may import requests, httpx, urllib, http.\n")
                else:
                    lines.append("- Network access ALLOWED. You may import requests, httpx, urllib, http.\n")
            else:
                lines.append("- No imports of socket, http, urllib, requests, or httpx (no network access)\n")
            if "filesystem" in caps:
                lines.append("- Filesystem access ALLOWED. You may import pathlib, glob, shutil, tempfile.\n")
            else:
                lines.append("- Use `open()` (builtin) to write files — do NOT import `os` or `pathlib`\n")
            return "".join(lines)
        # Default: no special capabilities
        return (
            "- No imports of os, subprocess, sys, socket, or network modules\n"
            "- Use `open()` (builtin) to write files — do NOT import `os` or `pathlib`\n"
        )

    def _build_manager_system_prompt(self) -> str:
        """System prompt for the manager agent."""
        enforced = self._config.worker_policy.enforced
        return f"""You are a Manager Agent in an AWP Delegation Loop.

Your role is to analyze a task, break it into subtasks, and delegate them to worker agents.
You generate instructions, skills (domain knowledge), and tool configurations for each worker.

## Your Decision Options

You MUST respond with a JSON object containing ONE of these decisions:

### DELEGATE — Assign work to workers

**MANDATORY FIELDS in every delegation envelope:**
- `worker_id` — unique snake_case
- `subtask_id` — MUST be the id of a plan subtask. The runtime cannot
  track progress without this field. Omitting it forces the runtime
  into fuzzy-matching, which is unreliable. ALWAYS set it.
- `instructions` — what the worker must do

**MANDATORY for any subtask whose plan entry has `delegation_strategy: "submanager"`:**
- `as_submanager: true` — REQUIRED. The plan said this is a submanager
  subtask; the envelope MUST honour that. If you forget, the runtime
  will spawn a normal worker, and the subtask will likely loop until
  auto-promotion kicks in — wasting an iteration.
- `submanager_budget_fraction` — float in [0.05, 0.95], default 0.3

```json
{{
  "decision": "delegate",
  "reasoning": "Why you're delegating this way",
  "delegations": [
    {{
      "worker_id": "unique_snake_case_name",
      "subtask_id": "subtask_1",
      "as_submanager": false,
      "submanager_agent": "agents/specialist",
      "submanager_budget_fraction": 0.3,
      "inherited_state_keys": ["data_summary"],
      "instructions": "Detailed instructions for the worker",
      "skills": ["# Skill Name\\n\\n## Purpose\\n...\\n\\n## Concepts\\n...\\n\\n## Rules\\n1. ..."],
      "tools_allowed": ["web.search", "file.read"],
      "output_contract": {{
        "required_fields": ["findings", "confidence"],
        "description": "What the worker should return"
      }},
      "codemode": {{
        "enabled": false,
        "tool_creation": false
      }},
      "temperature": 0.2
    }}
  ],
  "confidence": 0.0
}}
```

**Skill structure:** Each skill in the `skills` array MUST be a Markdown string with these sections:
- `# Name` — skill title
- `## Purpose` — one sentence describing what the skill supports
- `## Concepts` — 3-7 key terms as a definition list
- `## Rules` — numbered, testable constraints
- `## Procedure` (optional) — step-by-step sequence for multi-step tasks
- `## Examples` (optional) — input/output pairs when correct application is non-obvious

**Submanager fields (A4 — recursive delegation, optional):**
- `as_submanager: true` — spawns a child DelegationLoopRunner instead of an
  ephemeral worker. Use this when the subtask itself decomposes into many
  sub-steps that need their own iteration loop (e.g. "perform a multi-source
  research", "build and validate an end-to-end pipeline").
- `submanager_agent` — relative path to a manager agent dir (e.g.
  `agents/specialist`). Defaults to the parent's manager when omitted.
- `submanager_budget_fraction` — float in (0.05, 0.95), default 0.3. The
  child receives this fraction of the parent's REMAINING capacity as a
  HARD CAP. Unused budget flows back to the parent automatically.
- `inherited_state_keys` — list of state keys the child should see. Only
  these keys are passed; everything else is hidden to keep tokens low.
- The plan-level alternative: declare `delegation_strategy: "submanager"`
  + optional `submanager_agent` directly on the subtask in your PLAN.
- The recursion depth is bounded by `max_depth` in the budget. When the
  current depth reaches the limit, `as_submanager` is silently downgraded
  to a normal worker so the loop never hangs.

### COMPLETE — Task is done
```json
{{
  "decision": "complete",
  "reasoning": "Why the task is complete",
  "final_result": {{
    "your": "final output here",
    "confidence": 0.9
  }},
  "confidence": 0.9
}}
```

### FAIL — Cannot complete the task
```json
{{
  "decision": "fail",
  "reason": "Why the task cannot be completed",
  "partial_result": {{}}
}}
```
{self._build_intelligence_decision_options()}
## Worker Policy (Enforced Limits)
- Sandbox: {enforced.sandbox.type}, max {enforced.sandbox.max_memory_mb}MB RAM, {enforced.sandbox.max_cpu_seconds}s CPU
- Max tools per worker: {enforced.codemode.max_tools_per_worker}
- Forbidden tools: {", ".join(enforced.forbidden_tools)}
{self._build_namespace_capabilities_section()}{self._build_dynamic_tools_section()}{self._build_skill_catalog_section()}
## Rules
- **Reuse existing skills** — reference them by name in `skills` array instead of rewriting
- **Update skills** — to improve a skill, provide updated full markdown with the same heading
- **Reuse existing dynamic tools** — add them to workers' `tools_allowed` instead of recreating
- Give each worker a unique, descriptive worker_id (snake_case)
- Workers can only use tools from their tools_allowed list
- Include relevant domain knowledge in the skills array as Markdown strings
- Be specific in instructions — the worker only sees what you provide
- Set `temperature` per worker to control creativity (0.0 = deterministic, 1.0 = creative). Choose based on the task: use low temperature for analysis/validation, higher for brainstorming/writing. If omitted, defaults to 0.2.
- Respond ONLY with the JSON object, no other text

## Output File Validation
All output files (PNGs, CSVs, JSON, etc.) are automatically validated after each worker run.
- PNG files must be real charts (>500 bytes, >=10×10 pixels). 1×1 placeholder PNGs are REJECTED.
- CSV files must have at least one data row beyond the header.
- 0-byte files are always REJECTED.
If validation finds broken files, you will see a "FILE REPAIR REQUIRED" section in the next iteration.
You MUST delegate a repair worker to fix those files before marking the task as complete.
Do NOT accept "complete" if there are unresolved critical file errors.
"""

    def _build_manager_task(self, task: str, state: dict, iteration: int) -> str:
        """Build the user message for the manager with context."""
        parts = [f"## Original Task\n{task}\n"]

        # Baustein 4: Prior-run memory priming. ONLY on the first
        # iteration of the ROOT manager (submanagers inherit priors via
        # the parent digest). Gated by auto_curation_enabled.
        if (
            getattr(self._config, "auto_curation_enabled", True)
            and getattr(self, "_parent_digest_sha", None) is None
            and iteration <= 1
        ):
            try:
                from .curator import read_prior_memory as _read_prior
                prior_md = _read_prior(self._dir)
            except Exception as _exc:  # noqa: BLE001
                logger.debug("read_prior_memory failed: %s", _exc)
                prior_md = ""
            if prior_md:
                parts.append(prior_md + "\n")

        # Sibling coordination: inject any NEW blackboard entries since
        # the last time the manager was invoked. Silent when empty so
        # the prompt stays lean. Scoped to this manager run only.
        if self._blackboard is not None:
            try:
                new_entries = self._blackboard.read(
                    since=self._last_blackboard_seen_id
                )
            except Exception as exc:  # noqa: BLE001
                logger.debug("Blackboard read failed: %s", exc)
                new_entries = []
            if new_entries:
                bb_lines = [
                    "## SIBLING SIGNALS",
                    (
                        "Signals posted by workers in THIS manager run "
                        "since the last iteration. Use them to avoid "
                        "duplicate work and to react to partial findings."
                    ),
                ]
                for e in new_entries[-20:]:  # cap to keep prompt bounded
                    bb_lines.append(
                        f"- [{e.get('topic', '?')}] "
                        f"by {e.get('worker_id', '?')}: "
                        f"{json.dumps(e.get('payload', {}), default=str, ensure_ascii=False)[:400]}"
                    )
                parts.append("\n".join(bb_lines) + "\n")
                last_id = new_entries[-1].get("id")
                if isinstance(last_id, str):
                    self._last_blackboard_seen_id = last_id

        # Hierarchical Context Digest — inject this level's compact
        # digest so deep graphs don't lose context between iterations.
        # Followed by 1 level of inlined child digests (by default),
        # with deeper layers reachable via the `digest.fetch` tool.
        digest_active = (
            getattr(self._config, "digest_enabled", True)
            and self._current_digest is not None
        )
        if digest_active:
            md = self._current_digest.to_markdown()
            parts.append(
                "## MY DIGEST\n"
                "Compact, deterministic digest of THIS manager run "
                f"(sha={self._current_digest_sha[:12] if self._current_digest_sha else '?'}).\n"
                f"{md}\n"
            )
            max_depth = int(getattr(self._config, "digest_max_depth", 1) or 0)
            child_shas = list(self._current_digest.child_digest_hashes or [])
            if child_shas and max_depth >= 1 and self._digest_store is not None:
                child_lines = [
                    "## CHILDREN DIGESTS",
                    (
                        "Digests merged from submanagers in prior "
                        "iterations. Use `digest.fetch` for deeper "
                        "layers beyond digest_max_depth."
                    ),
                ]
                for sha in child_shas[-10:]:
                    child = self._digest_store.get(sha)
                    if child is None:
                        child_lines.append(f"- {sha[:12]}: (not retrievable)")
                        continue
                    goal_preview = (child.goal or "")[:120]
                    child_lines.append(
                        f"- {sha[:12]} iter={child.iteration} "
                        f"facts={len(child.key_facts)} "
                        f"questions={len(child.open_questions)}: "
                        f"{goal_preview}"
                    )
                parts.append("\n".join(child_lines) + "\n")

        # Budget status
        parts.append(
            f"## Budget Status\n```json\n{json.dumps(self._budget.to_dict(), indent=2)}\n```\n"
        )

        # Iteration info
        parts.append(f"## Current Iteration: {iteration}\n")

        # Rolling summary from history
        if self._history:
            parts.append("## Previous Results Summary\n")
            window = self._config.history.full_results_window
            # When the digest is active, cap the rolling detail tail
            # to the last 3 iterations so the prompt tokens go into
            # the structured digest instead of duplicated detail.
            if digest_active:
                window = min(window, 3)
            recent = self._history[-window:]
            for h in recent:
                parts.append(
                    f"### Iteration {h['iteration']} (confidence: {h.get('confidence', '?')})\n"
                    f"{h.get('key_findings', 'No findings recorded')}\n"
                )
            older = self._history[:-window] if len(self._history) > window else []
            if older:
                parts.append("### Earlier Iterations (Summary)\n")
                for h in older:
                    parts.append(
                        f"- Iter {h['iteration']}: confidence={h.get('confidence', '?')}\n"
                    )

        # Validation feedback from last iteration
        if self._history and self._history[-1].get("validation"):
            parts.append("## Validation Feedback\n")
            has_file_issues = False
            for v in self._history[-1]["validation"]:
                parts.append(
                    f"- Worker {v.get('worker_id', '?')}: {v.get('feedback', 'ok')}\n"
                )
                # Check for file validation failures in deterministic results
                det = v.get("deterministic", {})
                file_warnings = det.get("file_warnings", [])
                if file_warnings:
                    has_file_issues = True

            # Inject explicit file repair instructions if there were file issues
            if has_file_issues:
                from .file_validator import validate_directory, build_repair_instructions
                all_warnings = []
                workspace = self._dir / "workspace"
                run_output = self._dir / "output" / self._run_id
                if workspace.exists():
                    ws_outputs = workspace / "outputs"
                    if ws_outputs.exists():
                        for p in sorted(ws_outputs.rglob("*")):
                            if p.is_file() and not p.name.startswith("."):
                                from .file_validator import validate_file
                                w = validate_file(p)
                                if w:
                                    all_warnings.append((p, w))
                if run_output.exists():
                    for p in sorted(run_output.rglob("*")):
                        if p.is_file() and not p.name.startswith("."):
                            from .file_validator import validate_file
                            w = validate_file(p)
                            if w:
                                all_warnings.append((p, w))
                if all_warnings:
                    repair = build_repair_instructions(all_warnings)
                    parts.append(f"\n## ⚠ FILE REPAIR REQUIRED\n{repair}\n")
                    parts.append(
                        "**You MUST delegate a worker to fix these broken files "
                        "before marking the task as complete.** "
                        "Instruct the worker to re-generate the files with real data. "
                        "Do NOT accept placeholder images or empty files as valid output.\n"
                    )

        # Inject completion-rejection feedback from any of the completion
        # gates (file validator, critique threshold, placeholder scanner,
        # evaluation engine). The specific reason is in the message; we
        # only need to make the requirement clear.
        # Consume-once: pop the flag so the model sees it exactly in the
        # iteration that follows the rejection. If the same gate fires
        # again, the new feedback will be set fresh.
        repair_feedback = state.pop("_last_manager_feedback", None)
        # Also clear the per-gate sentinels so they don't accumulate.
        state.pop("_critique_repair_required", None)
        state.pop("_placeholder_repair_required", None)
        if repair_feedback:
            parts.append(
                f"## 🛑 COMPLETION REJECTED — REPAIR REQUIRED\n"
                f"{repair_feedback}\n\n"
                f"You MUST delegate a worker (or repair the existing "
                f"results) to address the issue above before attempting "
                f"to complete again. Do NOT mark the task as complete "
                f"until the underlying problem is actually fixed — not "
                f"just renamed or papered over.\n"
            )

        # Repeated delegation warning
        repeated_warn = state.get("_repeated_delegation_warning")
        if repeated_warn:
            parts.append(
                f"## ⚠ REPEATED DELEGATION DETECTED\n{repeated_warn}\n\n"
                f"Re-delegating the same worker with the same approach is "
                f"not making progress. Change strategy, merge subtasks, or "
                f"use a different decomposition.\n"
            )

        # Diagnose findings enforcement
        active_hypotheses = state.get("_active_hypotheses")
        if active_hypotheses:
            parts.append("## 🔬 ACTIVE DIAGNOSIS — YOU MUST ADDRESS THESE\n")
            parts.append(
                "You previously diagnosed problems and generated hypotheses. "
                "Your next delegation MUST test or fix at least one of these:\n"
            )
            for i, hyp in enumerate(active_hypotheses, 1):
                if isinstance(hyp, dict):
                    parts.append(
                        f"{i}. **{hyp.get('hypothesis', hyp.get('description', str(hyp)))}**\n"
                    )
                else:
                    parts.append(f"{i}. **{hyp}**\n")
            parts.append(
                "\nDo NOT ignore these and repeat the same delegation that failed. "
                "Address the root cause.\n"
            )

        # Critique feedback from last iteration
        if self._history and self._history[-1].get("critique_summary"):
            parts.append(self._history[-1]["critique_summary"])
            parts.append("")

        # Pattern pitfalls from critique engine
        if self._critique_engine and self._critique_engine.enabled:
            pitfalls = self._critique_engine.build_pattern_pitfalls_section()
            if pitfalls:
                parts.append(pitfalls)
                parts.append("")

        # State from previous workers
        worker_states = {
            k: v for k, v in state.items() if k != "task" and not k.startswith("_")
        }
        if worker_states:
            parts.append("## Worker Results Available in State\n")
            for k, v in worker_states.items():
                if isinstance(v, dict):
                    summary = json.dumps(v, indent=2, default=str)
                    if len(summary) > 500:
                        summary = summary[:500] + "...(truncated)"
                    parts.append(f"### {k}\n```json\n{summary}\n```\n")

        # Output directory listing — gives the manager hard evidence of
        # what deliverables already exist on disk.  Without this section
        # the manager often re-spawns workers (or unnecessary "validate"
        # workers) for files that are already produced.
        output_listing = self._build_output_dir_listing()
        if output_listing:
            parts.append(output_listing)
            parts.append("")

        # Manager Intelligence sections
        intelligence = self._build_intelligence_task_sections(state, iteration)
        if intelligence:
            parts.append(intelligence)

        return "\n".join(parts)

    def _build_output_dir_listing(self, max_entries: int = 30) -> str:
        """Return a markdown listing of the run's output directory.

        Empty string if the directory does not exist or has no files.
        """
        try:
            run_output_dir = self._dir / "output" / self._run_id
        except Exception:
            return ""
        if not run_output_dir.exists() or not run_output_dir.is_dir():
            return ""
        files: list[tuple[str, int]] = []
        for p in sorted(run_output_dir.rglob("*")):
            if p.is_file():
                try:
                    rel = p.relative_to(run_output_dir).as_posix()
                    size = p.stat().st_size
                except Exception:
                    continue
                files.append((rel, size))
                if len(files) >= max_entries:
                    break
        if not files:
            return ""
        lines = [
            "## Files Currently in Output Directory",
            "",
            "These deliverables already exist in `_output_dir` from previous "
            "iterations of THIS run. Before delegating more work, check whether "
            "the task is already satisfied by these files — if so, issue "
            "**COMPLETE**, do NOT spawn validation workers.",
            "",
        ]
        for rel, size in files:
            lines.append(f"- `{rel}` ({size} bytes)")
        return "\n".join(lines)

    def _parse_manager_output(self, output: Any) -> dict:
        """Parse and normalize manager output."""
        if isinstance(output, str):
            output = self._parse_json_response(output)
        if not isinstance(output, dict):
            return {
                "decision": "fail",
                "reason": f"Invalid manager output type: {type(output)}",
            }

        # Try to extract decision from a nested "result" string (LLMs
        # sometimes double-wrap their JSON response)
        if (
            "decision" not in output
            and "delegations" not in output
            and "result" in output
            and isinstance(output["result"], str)
            and "{" in output["result"]
        ):
            extracted = self._parse_json_response(output["result"])
            if "decision" in extracted or "delegations" in extracted or "final_result" in extracted:
                # Preserve any metadata from outer dict, then overlay extracted
                meta = {k: v for k, v in output.items() if k.startswith("_")}
                output = extracted
                output.update(meta)

        # Normalize "workers" key to "delegations" (both formats accepted)
        if "workers" in output and "delegations" not in output:
            workers = output.pop("workers")
            # Normalize worker_id: accept "id" or "worker_id"
            if isinstance(workers, list):
                for w in workers:
                    if isinstance(w, dict) and "id" in w and "worker_id" not in w:
                        w["worker_id"] = w.pop("id")
            output["delegations"] = workers

        # Also accept "tasks" as an alias for "delegations"
        if "tasks" in output and "delegations" not in output:
            tasks = output.pop("tasks")
            if isinstance(tasks, list):
                for t in tasks:
                    if isinstance(t, dict):
                        if "id" in t and "worker_id" not in t:
                            t["worker_id"] = t.pop("id")
                        if "task" in t and "instructions" not in t:
                            t["instructions"] = t.pop("task")
            output["delegations"] = tasks

        # Normalize decision field
        if "decision" not in output:
            if "subtasks" in output:
                output["decision"] = "plan"
            elif "hypotheses" in output:
                output["decision"] = "diagnose"
            elif "delegations" in output:
                output["decision"] = "delegate"
            elif any(
                k in output
                for k in (
                    "final_result", "report_md", "summary", "conclusion",
                    "output", "deliverables",
                )
            ):
                # LLMs often omit "decision" when they consider the task done
                output["decision"] = "complete"
                # Move the completion content into final_result if not already
                if "final_result" not in output:
                    for k in ("summary", "conclusion", "output", "deliverables"):
                        if k in output:
                            output["final_result"] = output[k]
                            break
            else:
                # Last resort: check if output has substantive content that
                # looks like it could be a completion (many keys, no error)
                _meta_keys = {"confidence", "reasoning", "reason", "_truncated",
                              "_confidence_source", "_parse_failure", "result"}
                content_keys = {k for k in output if k not in _meta_keys}
                if len(content_keys) >= 2 and "error" not in output:
                    logger.warning(
                        "Manager output missing 'decision' field but has "
                        "substantive content keys %s — treating as complete",
                        content_keys,
                    )
                    output["decision"] = "complete"
                    output["final_result"] = {
                        k: v for k, v in output.items() if k not in _meta_keys
                    }
                else:
                    output["decision"] = "fail"
                    output["reason"] = "Manager output missing 'decision' field"
        else:
            # Normalize decision value — LLMs sometimes return verbose strings
            raw = str(output["decision"]).strip().lower()
            _DELEGATE_WORDS = {"delegate", "delegat", "assign", "dispatch", "spawn"}
            _COMPLETE_WORDS = {
                "complete",
                "done",
                "finalize",
                "finish",
                "final",
                "synthesize",
                "conclude",
                "submit",
            }
            _FAIL_WORDS = {"fail", "abort", "error", "cancel", "impossible"}
            _PLAN_WORDS = {"plan", "decompose", "breakdown"}
            _DIAGNOSE_WORDS = {"diagnose", "diagnosis", "hypothes"}

            if any(w in raw for w in _DELEGATE_WORDS):
                output["decision"] = "delegate"
            elif any(w in raw for w in _COMPLETE_WORDS):
                output["decision"] = "complete"
            elif any(w in raw for w in _PLAN_WORDS):
                output["decision"] = "plan"
            elif any(w in raw for w in _DIAGNOSE_WORDS):
                output["decision"] = "diagnose"
            elif any(w in raw for w in _FAIL_WORDS):
                output["decision"] = "fail"
            # else: keep as-is, will be caught downstream

        # Filter out incomplete delegations (e.g. from truncated JSON repair)
        if output.get("decision") == "delegate" and "delegations" in output:
            valid = []
            for d in output["delegations"]:
                if isinstance(d, dict) and d.get("worker_id") and d.get("instructions"):
                    valid.append(d)
                else:
                    logger.warning("Dropping incomplete delegation entry: %s", d)
            output["delegations"] = valid
            # If all delegations were dropped, fall back to retry (not fail)
            if not valid:
                logger.warning(
                    "All delegations dropped after filtering — "
                    "will retry manager call"
                )
                output["decision"] = "retry"
                output["reason"] = "All delegations were incomplete/truncated"

            # Enforce skill quality — replace shallow tags with empty list
            # so the worker doesn't receive useless noise.  Log warnings
            # so the manager output can be diagnosed.
            if valid:
                for d in valid:
                    self._enforce_skill_quality(d)
                    self._enforce_tool_whitelist(d)

        return output

    # -- Tool whitelist enforcement ----------------------------------------

    _TOOL_WHITELIST_FALLBACK: tuple[str, ...] = (
        "code.execute",
        "file.read",
        "file.write",
        "file.list",
    )

    def _enforce_tool_whitelist(self, delegation: dict) -> None:
        """Drop hallucinated tool names from a delegation's tools_allowed.

        LLMs frequently invent tools like ``file.stat``, ``system.run``,
        ``shell.execute``, ``http.get``.  These do not exist and silently
        leave the worker without the tool the manager intended.  We:

        1. Build the closed set of valid tool names = built-in fallback
           tools + any externally registered tool names known to the runtime.
        2. Filter the delegation's ``tools_allowed`` against that set.
        3. Log a warning for each dropped tool so the cause is visible.
        4. If the filter empties the list, restore the safe defaults so
           the worker can still run instead of being silently de-tooled.
        """
        raw = delegation.get("tools_allowed")
        if not isinstance(raw, list) or not raw:
            return

        # Pull external tool names from the registry if available.
        external: set[str] = set()
        registry = getattr(self, "_external_tool_registry", None) or getattr(
            self, "_tool_registry", None
        )
        if registry is not None:
            try:
                names = registry.list_external_tool_names()  # type: ignore[attr-defined]
                external = {str(n) for n in names}
            except Exception:
                external = set()

        allowed = set(self._TOOL_WHITELIST_FALLBACK) | external
        wid = delegation.get("worker_id", "unknown")

        kept: list[str] = []
        dropped: list[str] = []
        for name in raw:
            if not isinstance(name, str):
                dropped.append(repr(name))
                continue
            if name in allowed:
                kept.append(name)
            else:
                dropped.append(name)

        if dropped:
            logger.warning(
                "Worker %s: dropping %d hallucinated tool name(s): %s "
                "(allowed=%s)",
                wid,
                len(dropped),
                dropped,
                sorted(allowed),
            )

        if not kept:
            logger.warning(
                "Worker %s: tools_allowed was emptied by whitelist filter "
                "— restoring safe defaults %s",
                wid,
                list(self._TOOL_WHITELIST_FALLBACK),
            )
            kept = list(self._TOOL_WHITELIST_FALLBACK)

        delegation["tools_allowed"] = kept

    # -- Skill quality enforcement -----------------------------------------

    _MIN_SKILL_WORDS = 30  # minimum word count for a valid skill

    def _enforce_skill_quality(self, delegation: dict) -> None:
        """Validate and filter skills in a delegation envelope.

        Skills that are too short (tags/labels like "CSV parsing") are dropped
        and a warning is logged.  The delegation dict is mutated in-place.
        """
        wid = delegation.get("worker_id", "unknown")
        raw_skills = delegation.get("skills", [])
        if not isinstance(raw_skills, list):
            return

        quality_skills: list[str] = []
        for i, skill in enumerate(raw_skills):
            if not isinstance(skill, str):
                continue
            stripped = skill.strip()
            if not stripped:
                continue
            word_count = len(stripped.split())
            if word_count < self._MIN_SKILL_WORDS:
                logger.warning(
                    "Worker %s: dropping shallow skill[%d] (%d words): %r — "
                    "skills must be detailed Markdown documents, not tags",
                    wid,
                    i,
                    word_count,
                    stripped[:80],
                )
            else:
                quality_skills.append(stripped)

        if len(quality_skills) < len(raw_skills):
            dropped = len(raw_skills) - len(quality_skills)
            logger.info(
                "Worker %s: kept %d/%d skills (%d dropped for low quality)",
                wid,
                len(quality_skills),
                len(raw_skills),
                dropped,
            )

        delegation["skills"] = quality_skills

    # -- Critique and repair -----------------------------------------------

    def _critique_and_repair(
        self,
        delegation_results: list[dict],
        task: str,
        state: dict,
        iteration: int,
    ) -> list:
        """Run critique phase on all worker results; attempt targeted repairs.

        Returns list of CritiqueEnvelope objects. May mutate delegation_results
        in-place if repairs improve results.
        """
        from .critique import CritiqueEnvelope

        if not self._critique_engine:
            return []

        # 1. Critique all results
        critiques = self._critique_engine.critique_results(
            delegation_results, task, iteration
        )

        # 2. Attempt targeted repair for results with critical defects
        repair_budget_limit = (
            self._config.critique.repair_budget_fraction * self._budget.max_total_tokens
        )

        for i, (dr, critique) in enumerate(zip(delegation_results, critiques)):
            if not critique.has_critical_defects:
                # Annotate result with critique metadata
                dr["result"]["_critique_score"] = round(critique.score, 4)
                dr["result"]["_critique_summary"] = critique.summary
                continue

            # Check repair budget
            if self._critique_engine._total_repair_tokens >= repair_budget_limit:
                logger.warning(
                    "Repair budget exhausted (%.0f tokens used of %.0f limit)",
                    self._critique_engine._total_repair_tokens,
                    repair_budget_limit,
                )
                dr["result"]["_critique_score"] = round(critique.score, 4)
                dr["result"]["_critique_summary"] = critique.summary
                dr["result"]["_critique_defects"] = [
                    {"category": d.category, "severity": d.severity, "description": d.description}
                    for d in critique.defects
                ]
                continue

            worker_id = dr.get("worker_id", "unknown")
            envelope = dr.get("envelope", {})

            def run_repair_worker(repair_envelope: dict, repair_task: str) -> dict:
                return self._run_ephemeral_worker(
                    f"{worker_id}_repair", repair_envelope, repair_task, state
                )

            repaired_result, attempts = self._critique_engine.attempt_repair(
                worker_id=worker_id,
                worker_result=dr["result"],
                critique=critique,
                task=task,
                envelope=envelope,
                run_worker_fn=run_repair_worker,
                budget_checker=self._budget.can_continue,
                iteration=iteration,
            )

            # Update delegation result with repaired version
            if attempts:
                last_attempt = attempts[-1]
                dr["result"] = repaired_result
                dr["result"]["_critique_score"] = round(last_attempt.repaired_score, 4)
                dr["result"]["_critique_summary"] = f"Repaired after {len(attempts)} attempt(s)"
                dr["result"]["_critique_repairs"] = [a.to_dict() for a in attempts]
                # Log repair result to disk
                self._logger.log_worker_result(iteration, worker_id, repaired_result)
                # Track workers spawned for repair
                self._budget.workers_spawned += len(attempts)
            else:
                dr["result"]["_critique_score"] = round(critique.score, 4)
                dr["result"]["_critique_summary"] = critique.summary
                dr["result"]["_critique_defects"] = [
                    {"category": d.category, "severity": d.severity, "description": d.description}
                    for d in critique.defects
                ]

        return critiques

    # -- Worker execution -------------------------------------------------

    def _execute_delegations(
        self, envelopes: list[dict], task: str, state: dict,
        iteration: int = 0,
    ) -> list[dict]:
        """Execute all delegations in parallel (fan-out)."""
        results: list[dict] = []
        # P6: rough count of submanager candidates so the budget fraction can
        # be divided across this dispatch. We deliberately use a cheap flag
        # check (no cap-check side effects) — the real submanager decision is
        # still made by `_is_submanager_envelope` per worker below.
        def _looks_like_submanager(env: dict) -> bool:
            if bool(env.get("as_submanager")):
                return True
            if self._task_plan is not None:
                stid = env.get("subtask_id", "")
                if stid:
                    for st in self._task_plan._subtasks:
                        if st.get("id") == stid:
                            return st.get("delegation_strategy") == "submanager"
            return False

        sub_candidate_count = sum(
            1 for env in envelopes if _looks_like_submanager(env)
        ) or 1

        def run_worker(envelope: dict) -> dict:
            worker_id = envelope.get("worker_id", f"worker_{uuid.uuid4().hex[:6]}")
            self._budget.workers_spawned += 1

            logger.info("  Spawning worker: %s", worker_id)

            # Write envelope to disk BEFORE worker starts (for file watchers)
            self._logger.log_worker_envelope(iteration, worker_id, envelope)

            # A4: recursive sub-manager spawning. If the envelope is marked
            # as_submanager (or the matching plan subtask declares
            # delegation_strategy="submanager"), we spawn a child
            # DelegationLoopRunner instead of running an ephemeral worker.
            if self._is_submanager_envelope(envelope):
                try:
                    return self._spawn_submanager(
                        worker_id, envelope, task, state, iteration,
                        num_submanagers_in_dispatch=sub_candidate_count,
                    )
                except Exception as exc:
                    logger.error(
                        "  Submanager %s failed: %s", worker_id, exc
                    )
                    err = {
                        "error": str(exc),
                        "confidence": 0.0,
                        "submanager_failed": True,
                    }
                    self._logger.log_worker_result(iteration, worker_id, err)
                    return {
                        "worker_id": worker_id,
                        "envelope": envelope,
                        "result": err,
                        "status": "error",
                    }

            try:
                result = self._run_ephemeral_worker(worker_id, envelope, task, state)
                # Persist any skills the worker created to the skill registry
                self._persist_worker_result_skills(result, worker_id)
                # Run step evaluation BEFORE writing result (so file watcher gets scores)
                if self._eval_engine and self._eval_engine.enabled and isinstance(result, dict):
                    step_eval = self._eval_engine.evaluate_step(
                        hook="worker_result",
                        result=result,
                        state=state,
                        budget=self._budget,
                        agent_id=worker_id,
                    )
                    if step_eval:
                        result["_eval_score"] = round(step_eval.score, 4)
                        result["_eval_action"] = step_eval.action
                        result["_eval_metrics"] = [
                            {"name": ms.name, "score": round(ms.score, 4), "weight": ms.weight}
                            for ms in step_eval.metric_scores
                        ]
                # Write result to disk immediately (for file watchers)
                self._logger.log_worker_result(iteration, worker_id, result)
                return {
                    "worker_id": worker_id,
                    "envelope": envelope,
                    "result": result,
                    "status": "ok",
                }
            except Exception as exc:
                logger.error("  Worker %s failed: %s", worker_id, exc)
                error_result = {"error": str(exc), "confidence": 0.0}
                self._logger.log_worker_result(iteration, worker_id, error_result)
                return {
                    "worker_id": worker_id,
                    "envelope": envelope,
                    "result": error_result,
                    "status": "error",
                }

        # Fan-out with ThreadPoolExecutor (8 threads to avoid blocking
        # when manager delegates 5+ workers — typical in production runs)
        max_workers = min(len(envelopes), 8)
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {pool.submit(run_worker, env): env for env in envelopes}
            for future in as_completed(futures):
                results.append(future.result())

        return results

    # ------------------------------------------------------------------
    # A4 — Recursive submanager spawning
    # ------------------------------------------------------------------

    def _is_submanager_envelope(self, envelope: dict) -> bool:
        """Decide whether a delegation should spawn a child DelegationLoopRunner.

        A worker becomes a submanager when:
        - The envelope has ``as_submanager: true``, OR
        - The matching plan subtask has ``delegation_strategy: "submanager"``
          (matched by explicit ``subtask_id`` OR by fuzzy worker_id match).

        Hard-blocked when ``self._depth >= self._budget.max_depth`` so the
        recursion can never escape its allowed depth.

        This is intentionally lenient: weaker manager models often forget
        to set ``as_submanager`` even when the plan said they should. We
        defend in depth here so the plan's intent is honoured even when
        the manager envelope is sloppy.
        """
        if self._depth >= self._budget.max_depth:
            return False
        # P2: hard caps on submanager fan-out
        if (
            self._budget.spawned_submanagers_total
            >= self._budget.max_total_submanagers_per_run
        ):
            logger.warning(
                "Submanager spawn blocked: total cap reached (%d/%d). "
                "Falling back to ephemeral worker.",
                self._budget.spawned_submanagers_total,
                self._budget.max_total_submanagers_per_run,
            )
            return False
        if (
            self._budget.active_submanagers
            >= self._budget.max_concurrent_submanagers
        ):
            logger.warning(
                "Submanager spawn blocked: concurrent cap reached (%d/%d). "
                "Falling back to ephemeral worker.",
                self._budget.active_submanagers,
                self._budget.max_concurrent_submanagers,
            )
            return False
        if bool(envelope.get("as_submanager")):
            return True
        if self._task_plan is not None:
            stid = envelope.get("subtask_id", "")
            # 1. Explicit subtask_id link
            if stid:
                for st in self._task_plan._subtasks:
                    if st.get("id") == stid:
                        return st.get("delegation_strategy") == "submanager"
            # 2. Fall back to fuzzy worker_id matching — the same heuristic
            # the TaskPlan uses for status tracking. Manager forgot subtask_id
            # but the worker name still maps clearly to a submanager subtask.
            wid = envelope.get("worker_id", "")
            if wid:
                resolved = self._task_plan._resolve_subtask(wid)
                if resolved and resolved.get("delegation_strategy") == "submanager":
                    return True
        return False

    # ------------------------------------------------------------------
    # A4 — Smart auto-promotion of complex subtasks
    # ------------------------------------------------------------------

    # Keywords that signal a subtask is structurally multi-step / iterative.
    # English + German because workflow tasks come in both.
    _COMPLEXITY_KEYWORDS = (
        # English
        "iterativ", "iteratively", "research", "investigate", "explore",
        "analyse", "analyze", "validate", "comprehensive", "multi-step",
        "multi-source", "end-to-end", "pipeline", "deep dive", "decompose",
        "synthesise", "synthesize", "build and test", "evaluate",
        "benchmark", "characterise", "characterize", "survey", "audit",
        # German
        "mehrstufig", "rekursiv", "umfangreich", "vollständig", "recherche",
        "untersuche", "validiere", "bewerte", "analysiere", "tiefgehend",
    )

    def _score_subtask_complexity(self, subtask: dict) -> tuple[int, list[str]]:
        """Return (score, reasons) for whether a subtask deserves a submanager.

        Score thresholds:
            >= 3 → submanager candidate
            < 3  → normal worker

        Reasons are returned for logging so users can see WHY the runtime
        chose to promote a subtask.
        """
        score = 0
        reasons: list[str] = []

        description = str(subtask.get("description", "")).lower()
        success = str(subtask.get("success_criteria", "")).lower()
        combined = f"{description}\n{success}"

        # 1. Manager already explicitly opted in — strong signal
        if subtask.get("delegation_strategy") == "submanager":
            score += 10
            reasons.append("manager-explicit")
            return score, reasons

        # 2. Manager already explicitly opted out — respect that
        if subtask.get("delegation_strategy") == "worker":
            return 0, ["manager-explicit-worker"]

        # 3. Description length — long descriptions usually mean multi-step work
        word_count = len(description.split())
        if word_count >= 80:
            score += 2
            reasons.append(f"long-description({word_count}w)")
        elif word_count >= 40:
            score += 1
            reasons.append(f"medium-description({word_count}w)")

        # 4. Complexity keywords
        kw_hits = [kw for kw in self._COMPLEXITY_KEYWORDS if kw in combined]
        if len(kw_hits) >= 3:
            score += 2
            reasons.append(f"keywords:{kw_hits[:3]}")
        elif len(kw_hits) >= 1:
            score += 1
            reasons.append(f"keyword:{kw_hits[0]}")

        # 5. Subtask lists multiple deliverables (numbered list, bullets,
        #    "and X" enumerations). A subtask that produces 3+ artefacts
        #    almost certainly needs more than a single worker round.
        deliverable_signals = (
            description.count("\n-")
            + description.count("\n*")
            + len([m for m in description.split("\n") if m.strip()[:2].rstrip(".") in ("1", "2", "3", "4", "5")])
        )
        if deliverable_signals >= 3:
            score += 2
            reasons.append(f"deliverables({deliverable_signals})")
        elif deliverable_signals >= 2:
            score += 1
            reasons.append(f"deliverables({deliverable_signals})")

        # 6. High priority + non-trivial description → likely a real workpackage
        if subtask.get("priority") == "high" and word_count >= 25:
            score += 1
            reasons.append("high-priority+nontrivial")

        return score, reasons

    def _auto_promote_complex_subtasks(
        self, subtasks: list[dict]
    ) -> list[str]:
        """Score each subtask and promote complex ones to submanager strategy.

        Returns the list of promoted subtask ids (for logging).

        Promotion rules (deterministic, no LLM call):
        - A subtask becomes a submanager if its complexity score is >= 3
          AND it is independent (no incoming dependencies) so it can be
          dispatched in parallel with siblings.
        - A subtask the manager explicitly tagged is honoured either way.
        - We never promote MORE than half of the subtasks at once — if the
          plan is uniformly "complex" the runtime falls back to normal
          workers for the lower-scored half so the parent budget isn't
          blown by parallel sub-loops.
        """
        if not subtasks:
            return []

        # Score every subtask. Independent subtasks (no incoming deps)
        # are the natural fan-out roots and get a +1 bonus, but dependent
        # subtasks are no longer hard-excluded — realistic plans almost
        # always have a pipeline shape (subtask_2 depends on subtask_1)
        # and the previous "independent only" rule meant auto-promotion
        # was inactive for them. A complex pipeline-stage workpackage is
        # still a perfectly good submanager candidate.
        scored: list[tuple[dict, int, list[str]]] = []
        for st in subtasks:
            score, reasons = self._score_subtask_complexity(st)
            if not st.get("dependencies"):
                score += 1
                reasons.append("independent-root")
            scored.append((st, score, reasons))

        if not scored:
            return []

        # COLLECTIVE UPLIFT: when ≥2 subtasks all share at least one
        # complexity indicator (score ≥ 1), they form a natural fan-out
        # pattern that benefits from submanagers even if each individual
        # subtask is small. Threshold lowered from 3 → 2 because realistic
        # plans rarely have 3+ truly independent roots.
        nontrivial = [(st, s, r) for (st, s, r) in scored if s >= 1]
        if len(nontrivial) >= 2:
            for st, s, r in nontrivial:
                idx = scored.index((st, s, r))
                scored[idx] = (st, s + 2, r + ["collective-fanout"])

        # Sort by score descending, take only those above threshold
        scored.sort(key=lambda x: -x[1])
        candidates = [(st, s, r) for (st, s, r) in scored if s >= 3]
        # Cap at half of all subtasks to avoid budget over-commit
        max_promotions = max(1, len(subtasks) // 2 + 1)
        candidates = candidates[:max_promotions]

        promoted: list[str] = []
        for st, score, reasons in candidates:
            # Don't override an explicit manager choice
            if st.get("delegation_strategy") == "worker":
                continue
            st["delegation_strategy"] = "submanager"
            sid = st.get("id", "?")
            logger.info(
                "  → %s: score=%d reasons=%s", sid, score, reasons
            )
            promoted.append(sid)
        return promoted

    # ------------------------------------------------------------------
    # P3 / P4 — Convergence + redundancy detection
    # ------------------------------------------------------------------

    def _check_convergence(self, iteration: int) -> bool:
        """Return True if the loop has converged and should be force-completed.

        Two heuristics:
          (a) After at least 3 iterations, if confidence has improved by
              less than 0.05 across the last two iterations, we're stuck.
          (b) If the last 3 history entries were all DELEGATE iterations
              that produced no new key findings, we're spinning.
        """
        if iteration < 3 or len(self._history) < 2:
            return False
        try:
            last = float(self._history[-1].get("confidence", 0.0) or 0.0)
            prev = float(self._history[-2].get("confidence", 0.0) or 0.0)
        except (TypeError, ValueError):
            return False
        if abs(last - prev) < 0.05 and last < 0.95:
            logger.warning(
                "Convergence detector: confidence delta %.3f < 0.05 "
                "(last=%.2f, prev=%.2f) — forcing partial complete.",
                abs(last - prev), last, prev,
            )
            return True
        if len(self._history) >= 3:
            recent = self._history[-3:]
            findings = [tuple(h.get("key_findings") or ()) for h in recent]
            if len(set(findings)) == 1:
                logger.warning(
                    "Convergence detector: 3 consecutive iterations with "
                    "identical key_findings — forcing partial complete."
                )
                return True
        return False

    @staticmethod
    def _normalize_instructions(text: str) -> str:
        """Lowercase + collapse whitespace + truncate. Used for signature hashing."""
        if not isinstance(text, str):
            return ""
        return " ".join(text.lower().split())[:500]

    @staticmethod
    def _canonical_context(env: dict) -> str:
        """Build a stable canonical JSON representation of the context the
        envelope references. Used to make delegation signatures content-aware
        so two workers with identical instructions but different input context
        are no longer flagged as redundant.

        Sources considered, in order of precedence:
          1. explicit ``context`` dict on the envelope (preferred by newer
             manager prompts),
          2. ``input_context`` dict (legacy alias),
          3. ``inherited_state_keys`` list — if present we emit a sorted
             marker list (the keys themselves are part of the context
             because the *set of referenced keys* differentiates two
             otherwise identical delegations).

        Returns an empty string when the envelope references no context, so
        behavior is fully backward compatible with the legacy instructions-
        only signature.
        """
        if not isinstance(env, dict):
            return ""
        ctx = env.get("context")
        if not isinstance(ctx, dict) or not ctx:
            ctx = env.get("input_context")
        if isinstance(ctx, dict) and ctx:
            try:
                return json.dumps(ctx, sort_keys=True, default=str)
            except (TypeError, ValueError):
                return repr(sorted(ctx.items()))
        keys = env.get("inherited_state_keys")
        if isinstance(keys, (list, tuple)) and keys:
            return json.dumps(
                {"_inherited_keys": sorted(str(k) for k in keys)},
                sort_keys=True,
            )
        return ""

    @staticmethod
    def _delegation_signature(envelopes: list[dict]) -> tuple[str, ...]:
        """Stable signature for a delegation dispatch (P4 redundancy detection).

        Content-aware: hashes both the normalized instructions *and* a stable
        canonical representation of any context payload referenced by the
        envelope. Envelopes that reference no context hash identically to
        the legacy instructions-only signature (backward compatible).
        """
        import hashlib

        sigs: list[str] = []
        for env in envelopes or []:
            instr = DelegationLoopRunner._normalize_instructions(
                env.get("instructions", "") if isinstance(env, dict) else ""
            )
            ctx_repr = DelegationLoopRunner._canonical_context(
                env if isinstance(env, dict) else {}
            )
            if ctx_repr:
                payload = instr + "\x1f" + ctx_repr
            else:
                # Legacy path — pure instructions hash for backward compat.
                payload = instr
            sigs.append(hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16])
        return tuple(sorted(sigs))

    def _merge_submanager_outputs(
        self, sub_output_dir: Path, submanager_name: str
    ) -> list[str]:
        """Copy files from a submanager's _output_dir into the parent _output_dir.

        Files that collide with existing parent files are renamed using a
        ``<submanager_name>__<filename>`` prefix so nothing is silently lost.
        Returns the list of merged destination filenames (relative paths).
        """
        import shutil

        merged: list[str] = []
        if not sub_output_dir.exists() or not sub_output_dir.is_dir():
            return merged
        parent_output = self._dir / "output" / (self._run_id or "")
        try:
            parent_output.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            logger.warning(
                "Could not create parent output dir %s: %s", parent_output, exc
            )
            return merged
        for src in sub_output_dir.rglob("*"):
            if not src.is_file():
                continue
            try:
                rel = src.relative_to(sub_output_dir)
            except ValueError:
                continue
            dst = parent_output / rel
            if dst.exists():
                dst = parent_output / f"{submanager_name}__{rel.name}"
            try:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
                merged.append(str(dst.relative_to(parent_output)))
            except OSError as exc:
                logger.warning("Failed to merge submanager file %s: %s", src, exc)
        if merged:
            logger.info(
                "Merged %d submanager file(s) from %s into parent output: %s",
                len(merged),
                submanager_name,
                merged[:10],
            )
        return merged

    def _spawn_submanager(
        self,
        worker_id: str,
        envelope: dict,
        task: str,
        state: dict,
        iteration: int,
        num_submanagers_in_dispatch: int = 1,
    ) -> dict:
        """Spawn a child :class:`DelegationLoopRunner` for this delegation.

        Termination guarantees (so the parent can never hang):

        - Budget is allocated as a hard-cap fraction of the parent's
          *remaining* capacity (:meth:`BudgetSnapshot.allocate_child`).
        - Wall-time is shared with the parent — the global timeout always
          wins, regardless of recursion depth.
        - The submanager has its own ``StallDetector`` and force-advance
          logic (inherited from the same DelegationLoopRunner code).
        - On exception or timeout we still ``reclaim_child`` so the parent
          accounting stays accurate.
        - The result envelope always contains a ``confidence`` field so
          downstream aggregation never blocks.
        """
        # 1. Resolve which agent to load (subtask config beats envelope)
        sub_agent_path = envelope.get("submanager_agent")
        if not sub_agent_path and self._task_plan is not None:
            stid = envelope.get("subtask_id", "")
            for st in self._task_plan._subtasks:
                if st.get("id") == stid:
                    sub_agent_path = st.get("submanager_agent")
                    break
        if not sub_agent_path:
            sub_agent_path = self._config.manager  # fall back to parent's manager

        # 2. Build inherited state subset.
        #
        # Precedence (highest to lowest):
        #   (a) Explicit whitelist — envelope ``inherited_state_keys`` set
        #       and non-empty. Only the listed keys are copied (legacy
        #       behavior, fully backward compatible for workflows that
        #       already set it).
        #   (b) Blacklist + default inherit-all — pass every parent state
        #       key except those listed in ``forbidden_inheritance_keys``
        #       (read from the envelope first, then from the delegation
        #       loop config as a workflow-wide default).
        #   (c) Default — inherit everything the parent currently holds.
        inherited: dict
        whitelist = envelope.get("inherited_state_keys")
        if isinstance(whitelist, (list, tuple)) and len(whitelist) > 0:
            inherited = {k: state.get(k) for k in whitelist if k in state}
        else:
            forbidden_env = envelope.get("forbidden_inheritance_keys") or []
            forbidden_cfg = list(
                getattr(self._config, "forbidden_inheritance_keys", []) or []
            )
            forbidden = set()
            for item in list(forbidden_env) + forbidden_cfg:
                if isinstance(item, str):
                    forbidden.add(item)
            inherited = {
                k: v for k, v in (state or {}).items() if k not in forbidden
            }

        # Pass the parent's current digest sha into the child's
        # inherited state under a reserved key so the child runner
        # can record its lineage (read in __init__).
        if self._current_digest_sha:
            inherited = dict(inherited)
            inherited["__parent_digest_sha"] = self._current_digest_sha

        # 3. Allocate child budget (hard-cap fraction).
        # P6: dynamic fraction — when several submanagers spawn in the same
        # dispatch, split 0.8 of the parent budget across them so the total
        # never exceeds 80% and a single one cannot grab 30% three times.
        n = max(1, int(num_submanagers_in_dispatch))
        default_fraction = min(0.3, 0.8 / n)
        fraction = float(envelope.get("submanager_budget_fraction", default_fraction))
        child_budget = self._budget.allocate_child(fraction=fraction)

        # 4. Build sub-run dir under the parent worker dir so the
        # visualizer can render the nested run cluster
        parent_worker_dir = (
            self._run_dir
            / "iterations"
            / f"{iteration:03d}"
            / "delegations"
            / worker_id
        )
        sub_run_id = (
            datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M-%S")
            + "_"
            + uuid.uuid4().hex[:8]
        )
        sub_run_dir = parent_worker_dir / "runs" / sub_run_id

        # 5. Construct the sub-task description for the child manager
        sub_task = envelope.get("instructions", "") or task
        sub_task_header = (
            f"## Submanager task\n"
            f"You have been spawned as a sub-manager for `{worker_id}` "
            f"(depth {self._depth + 1} of max {self._budget.max_depth}).\n"
            f"Budget allocated: {child_budget.max_loops} loops, "
            f"{child_budget.max_total_workers} workers, "
            f"{child_budget.max_total_tokens} tokens, "
            f"{int(child_budget.max_wall_time)}s wall-time.\n\n"
            f"Inherited state keys: {list(inherited.keys()) or 'none'}\n\n"
        )
        full_sub_task = sub_task_header + sub_task

        # 6. Construct child runner — same workflow_dir, same config (so
        # forbidden tools, sandbox, validation rules all transfer), shared
        # tool registry, but its own run_dir + budget + inherited state.
        logger.info(
            "  Spawning SUBMANAGER %s at depth=%d (budget fraction=%.2f, "
            "loops=%d, tokens=%d, wall=%ds)",
            worker_id, self._depth + 1, fraction,
            child_budget.max_loops, child_budget.max_total_tokens,
            int(child_budget.max_wall_time),
        )
        child = DelegationLoopRunner(
            workflow_dir=self._dir,
            config=self._config,
            tool_registry=self._tools,
            manager_model=self._manager_model,
            worker_model=self._worker_model,
            run_id=sub_run_id,
            depth=self._depth + 1,
            parent_budget=child_budget,
            eval_config=getattr(self, "_eval_engine_config", None),
            llm_client=self._manager_llm,
            profile=False,
            run_dir_override=sub_run_dir,
            inherited_state=inherited,
        )
        # The child agent class is loaded from sub_agent_path on the next
        # _run_manager call. We override the manager path for the child by
        # patching its config copy (lightweight: only the manager attribute).
        try:
            child._config = type(self._config).model_validate(
                self._config.model_dump()
            )
            child._config.manager = sub_agent_path
        except Exception:
            pass  # config is shared — fall back to parent's manager

        # 7. Run the child loop. This call is bounded by:
        #    - child_budget.max_loops / max_total_workers / max_total_tokens
        #    - child_budget.max_wall_time (= parent's remaining wall-time)
        #    - child's own StallDetector (inherited code path)
        #    - child's own depth-limit (max_depth - 1)
        try:
            sub_result = child.run(full_sub_task, dict(inherited))
        except Exception as exc:
            import traceback as _tb
            tb_str = _tb.format_exc()
            logger.error(
                "Submanager %s raised: %s\n%s", worker_id, exc, tb_str,
            )
            try:
                self._logger.trace(
                    "submanager",
                    f"crashed: {worker_id}",
                    level="ERROR",
                    worker=worker_id,
                    error=str(exc),
                    traceback=tb_str[-1000:],
                )
            except Exception:
                pass
            sub_result = {
                "error": str(exc),
                "traceback": tb_str,
                "confidence": 0.0,
                "submanager_failed": True,
            }
        finally:
            # 8. Always reclaim child budget so unused capacity flows back
            self._budget.reclaim_child(child_budget)
            # P0: merge submanager output dir into parent output dir.
            # The child runner used `<workflow_dir>/output/<sub_run_id>/` as
            # its `_output_dir` (its workers wrote there because each runner
            # builds output paths from its own _run_id). We copy those files
            # back into the parent's output dir so deliverables surface in
            # the experiment without "outside the workflow directory" hits.
            try:
                sub_output_dir = self._dir / "output" / sub_run_id
                merged_files = self._merge_submanager_outputs(
                    sub_output_dir, worker_id
                )
                if merged_files:
                    if isinstance(sub_result, dict):
                        sub_result.setdefault("_merged_files", merged_files)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Submanager output merge failed for %s: %s", worker_id, exc
                )
            # Restore the parent's run_id on the shared tool registry — the
            # child set it to its own sub_run_id during run() and we need
            # parent workers to write under the parent run again.
            if self._tools and hasattr(self._tools, "set_run_id"):
                try:
                    self._tools.set_run_id(self._run_id)
                except Exception:
                    pass

        # 9. Normalise result so downstream aggregation never blocks
        if not isinstance(sub_result, dict):
            sub_result = {"value": sub_result, "confidence": 0.5}
        sub_result.setdefault("confidence", 0.5)
        sub_result["_submanager"] = True
        sub_result["_submanager_depth"] = self._depth + 1
        sub_result["_submanager_run_id"] = sub_run_id

        # Capture the submanager's final digest sha (if any) so the
        # parent can merge it into its own next-iteration digest.
        try:
            child_digest_sha = sub_result.get("_digest_sha")
            if isinstance(child_digest_sha, str) and child_digest_sha:
                self._pending_child_digest_hashes.append(child_digest_sha)
        except Exception:
            pass

        self._logger.log_worker_result(iteration, worker_id, sub_result)
        return {
            "worker_id": worker_id,
            "envelope": envelope,
            "result": sub_result,
            "status": "ok",
        }

    def _run_ephemeral_worker(
        self, worker_id: str, envelope: dict, task: str, state: dict
    ) -> dict:
        """Run an ephemeral worker configured entirely by the delegation envelope."""
        instructions = envelope.get("instructions", "")
        raw_skills = envelope.get("skills", [])
        # Resolve skill names to full content (lazy loading from skill registry)
        skills = self._resolve_skills(raw_skills) if raw_skills else []
        # Inject critique pattern pitfalls as an additional skill
        if self._critique_engine and self._critique_engine.enabled:
            pitfalls = self._critique_engine.build_pattern_pitfalls_section()
            if pitfalls:
                skills.append(f"# Quality Guard\n\n{pitfalls}")
        envelope["skills"] = skills  # Update envelope for logging
        tools_allowed = envelope.get("tools_allowed", [])
        output_contract = envelope.get("output_contract", {})
        codemode = envelope.get("codemode", {})

        # Sanitize tools_allowed: the manager LLM occasionally hallucinates
        # tool names like "python", "pandas", "timeout", "yaml" — none of
        # which are real registered tools. Drop unknowns (preserving glob
        # patterns like "dynamic.*") and, if the worker is supposed to run
        # code but the resulting list contains nothing useful, fall back to
        # a sane default so the worker isn't silently rendered tool-less.
        if tools_allowed and self._tools is not None:
            known = set(self._tools.tool_names)
            sanitized: list[str] = []
            dropped: list[str] = []
            for t in tools_allowed:
                if not isinstance(t, str):
                    continue
                if "*" in t or t in known:
                    sanitized.append(t)
                else:
                    dropped.append(t)
            if dropped:
                logger.warning(
                    "  Worker %s: dropping unknown/hallucinated tools %s "
                    "(not registered in ToolRegistry)",
                    worker_id,
                    sorted(set(dropped)),
                )
            tools_allowed = sanitized
        # If the worker is supposed to run code but ended up with no usable
        # tools, restore a minimal default toolset.
        if (
            (not tools_allowed)
            and isinstance(codemode, dict)
            and codemode.get("enabled", False)
        ):
            tools_allowed = ["code.execute", "file.read", "file.write", "file.list"]
            logger.warning(
                "  Worker %s: tools_allowed was empty/invalid — restored default "
                "code-mode toolset",
                worker_id,
            )

        # Dynamic temperature: envelope value (set by manager) takes priority
        worker_temperature = envelope.get("temperature", 0.2)
        if not isinstance(worker_temperature, (int, float)):
            worker_temperature = 0.2
        worker_temperature = max(0.0, min(float(worker_temperature), 2.0))
        logger.info(
            "Worker %s: temperature=%.2f (from %s)",
            worker_id,
            worker_temperature,
            "envelope" if "temperature" in envelope else "default",
        )

        # Enforce codemode from worker policy manager_controlled.
        # The manager LLM frequently ignores prompt instructions and sends
        # codemode.enabled=false.  When the policy lists these fields in
        # manager_controlled, force them to true so workers always get the
        # configured capabilities.
        if not isinstance(codemode, dict):
            codemode = {}
        wp = getattr(self._config, "worker_policy", None)
        if wp and "codemode.enabled" in (wp.manager_controlled or []):
            if not codemode.get("enabled", False):
                logger.info(
                    "Worker %s: enforcing codemode.enabled=true (policy override)",
                    worker_id,
                )
            codemode["enabled"] = True
        if wp and "codemode.tool_creation" in (wp.manager_controlled or []):
            if not codemode.get("tool_creation", False):
                logger.info(
                    "Worker %s: enforcing codemode.tool_creation=true (policy override)",
                    worker_id,
                )
            codemode["tool_creation"] = True

        # Ensure code.execute is in tools_allowed when codemode is enabled
        if codemode.get("enabled", False) and "code.execute" not in tools_allowed:
            tools_allowed = list(tools_allowed) + ["code.execute"]
            logger.info(
                "Worker %s: auto-added code.execute (codemode.enabled=true)", worker_id
            )

        # Expose the sibling-coordination blackboard tools when the
        # feature is enabled. They are run-scoped (bound via ContextVar
        # in `run()`), so every worker in this manager run sees the
        # same board, while workers in other runs cannot touch it.
        if self._blackboard is not None:
            for bb_tool in ("board.post", "board.read"):
                if bb_tool not in tools_allowed:
                    tools_allowed = list(tools_allowed) + [bb_tool]

        # Hierarchical Context Digest — expose `digest.fetch` to
        # workers so they can pull deeper layers than what's inlined
        # in the manager prompt. Run-scoped via ContextVar.
        if self._digest_store is not None:
            if "digest.fetch" not in tools_allowed:
                tools_allowed = list(tools_allowed) + ["digest.fetch"]

        envelope["codemode"] = codemode
        envelope["tools_allowed"] = tools_allowed

        # Debug: log full envelope
        logger.debug(
            "Worker %s envelope:\n%s",
            worker_id,
            json.dumps(envelope, indent=2, default=str, ensure_ascii=False),
        )

        # Check if this worker should create tools
        tool_creation = (
            isinstance(codemode, dict)
            and codemode.get("enabled", False)
            and codemode.get("tool_creation", False)
        )

        # Build system prompt from envelope.
        # WORKER_PITFALLS is injected unconditionally so workers see the
        # hard-won bug list (stateless code.execute, .iloc, MultiIndex,
        # hallucinated APIs, …) regardless of what the manager wrote into
        # `instructions`. Earlier runs proved that pitfalls placed only in
        # the manager prompt never reach workers.
        from awp.data.prompts import WORKER_PITFALLS
        system_parts = [
            f"You are a Worker Agent (ID: {worker_id}) executing a delegated task.\n",
            WORKER_PITFALLS,
            f"## Instructions\n{instructions}\n",
        ]

        if skills:
            system_parts.append("## Domain Knowledge\n")
            for i, skill in enumerate(skills):
                if isinstance(skill, str):
                    # If the skill already has a top-level heading, use it as-is;
                    # otherwise wrap it with a numbered heading for clarity.
                    stripped = skill.lstrip()
                    if stripped.startswith("# "):
                        system_parts.append(f"{skill}\n")
                    else:
                        system_parts.append(f"### Skill {i + 1}\n{skill}\n")

        # If codemode is enabled, tell the worker about file I/O capabilities
        if isinstance(codemode, dict) and codemode.get("enabled", False):
            workspace_path = str(self._dir / "workspace")
            # Always use run_id-isolated output directory
            run_output_dir = self._dir / "output" / self._run_id
            run_output_dir.mkdir(parents=True, exist_ok=True)
            output_path = str(run_output_dir)

            # Build input registry with schema previews for data files
            workspace_path_obj = self._dir / "workspace"
            input_registry_block = build_input_registry(workspace_path_obj)

            # When no input files exist, tell worker it can generate data
            no_inputs_hint = ""
            if not input_registry_block.strip():
                no_inputs_hint = (
                    "## Data Availability\n\n"
                    "No pre-loaded input files are available in the workspace. "
                    "If the task requires data, **generate it programmatically** "
                    "using `code.execute`. For example:\n"
                    "- Generate synthetic data with numpy/pandas\n"
                    "- Fetch data via HTTP or domain-specific libraries\n"
                    "- Save generated data to `_workspace_dir + \"/inputs/\"` for reuse\n\n"
                )

            # Build live directory tree showing only this run's output
            dir_tree = self._build_directory_tree(workspace_path_obj, run_output_dir)

            system_parts.append(f"""{input_registry_block}
{no_inputs_hint}{dir_tree}## IMPORTANT: Use `code.execute` for All Computation

You MUST use the `code.execute` tool to run Python code for:
- Data processing, analysis, and computation
- Creating charts/plots (matplotlib, etc.)
- Saving files (PNGs, CSVs, JSON, etc.)
- Any task that requires importing libraries

Do NOT try to compute results in your JSON response — use `code.execute` to run actual Python code.
Do NOT use `file.write` for binary files (PNGs, images) — generate them via `code.execute` with matplotlib/PIL.

## CRITICAL: Never Write Placeholder Files

**NEVER write 1×1 pixel placeholder PNGs, empty files, or base64-encoded dummy images as a fallback.**
If plotting fails (e.g. matplotlib not installed, empty data), you MUST:
1. First install the missing package: `pip.install(packages=["matplotlib"])`
2. Then re-run the plotting code with real data
3. After saving, verify the file: `_verify_png(path)` (returns True if valid)

All output files are automatically validated. Files that are empty, too small, or contain
placeholder content will be flagged as CRITICAL errors, and your confidence score will be
heavily penalized. The manager will require you to fix them before the task can complete.

## File I/O

In `code.execute` calls, these paths are available as pre-defined variables:
- `_workspace_dir` = `"{workspace_path}"` (workspace directory with input files)
- `_output_dir` = `"{output_path}"` (save final deliverables here)

**IMPORTANT:** Always use `_workspace_dir + "/inputs/FILENAME"` to read input files.
Do NOT use relative paths like `open("data.csv")` — they will fail.

Use string concatenation for paths: `_output_dir + "/chart.png"`

**Prefer flat output files:** Save files directly into `_output_dir` without subdirectories:
`_output_dir + "/chart.png"`, `_output_dir + "/results.csv"`.
Parent directories are created automatically when you call `open()` in write mode,
so subdirectories like `_output_dir + "/plots/chart.png"` will also work.

**Discovering files at runtime:** Call `_list_files()` to get all files in the workspace,
or `_list_files(_output_dir)` for output files. This is useful when reading results from
previous workers:
```python
# See what files are available
print(_list_files())           # workspace files
print(_list_files(_output_dir))  # output files from other workers
```

**IMPORTANT: Always check before reading.** Before reading a file, verify it exists:
```python
path = _workspace_dir + "/inputs/data.csv"
if _os.path.exists(path):
    df = pd.read_csv(path)
else:
    print(f"File not found: {{path}}")
    print("Available files:", _list_files())
```

Example (reading CSV and saving a chart):
```python
import pandas as pd
df = pd.read_csv(_workspace_dir + "/inputs/data.csv")

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
plt.figure(figsize=(10, 6))
df.plot()
plt.savefig(_output_dir + "/chart.png", dpi=150, bbox_inches="tight")
plt.close()
print("Chart saved")
```
""")

        # If tool creation is requested, add instructions for generating tools
        if tool_creation:
            namespace = codemode.get("tool_creation_namespace", "dynamic")
            system_parts.append(self._build_tool_creation_prompt(namespace))

        # Output contract instructions
        if output_contract:
            system_parts.append("## Output Requirements\n")
            system_parts.append("Respond with a valid JSON object containing:\n")

            # Support both formats:
            #  1. Schema-style: {"field_name": {"type": "...", "description": "..."}, ...}
            #  2. Legacy list-style: {"required_fields": [...], "description": "..."}
            required_list = output_contract.get("required_fields", None)
            if required_list is not None:
                # Legacy format
                desc = output_contract.get("description", "")
                if desc:
                    system_parts.append(f"{desc}\n")
                for field in required_list:
                    system_parts.append(f"- `{field}`\n")
            else:
                # Schema-style: keys are field names, values are type descriptors
                for field_name, field_def in output_contract.items():
                    if isinstance(field_def, dict):
                        ftype = field_def.get("type", "any")
                        fdesc = field_def.get("description", "")
                        system_parts.append(f"- `{field_name}` ({ftype}): {fdesc}\n")
                    else:
                        # Bare field name or scalar
                        system_parts.append(f"- `{field_name}`\n")

            # Always ensure confidence is mentioned with clear guidance
            if "confidence" not in output_contract:
                system_parts.append(
                    "- `confidence` (float 0.0-1.0, **REQUIRED**): "
                    "Your honest assessment of result quality. "
                    "0.9-1.0 = fully verified, all checks pass. "
                    "0.7-0.8 = high quality, minor uncertainties. "
                    "0.5-0.6 = partial result, some issues. "
                    "0.1-0.4 = low quality, significant gaps. "
                    "Do NOT default to a generic value — assess your actual output.\n"
                )
            if tool_creation:
                system_parts.append(
                    "- `tools_created` (array): List of tool objects you created\n"
                )
            system_parts.append("\nRespond ONLY with the JSON object.\n")

        system_prompt = "\n".join(system_parts)

        # Build user message with context (smart spillover for large results)
        user_parts = [f"## Task\n{task}\n"]

        cb_cfg = self._config.context_budget
        ctx_budget = ContextBudgetConfig(
            total_chars=cb_cfg.total_chars,
            min_per_entry=cb_cfg.min_per_entry,
            preview_chars=cb_cfg.preview_chars,
        )
        workspace_dir = self._dir / "workspace"
        context_block = prepare_context(state, workspace_dir, ctx_budget)
        if context_block:
            user_parts.append(context_block)

        # Inject a live workspace + output file tree so the worker cannot
        # invent paths like "iterations/002/delegations/.../instructions.md".
        # The same snapshot logic is used by tools._snapshot_workspace_tree.
        try:
            output_dir = self._dir / "output" / (self._run_id or "")
            tree_lines: list[str] = []
            for base, label in ((workspace_dir, "_workspace_dir"), (output_dir, "_output_dir")):
                if base.exists():
                    tree_lines.append(f"{label}/  ({base})")
                    count = 0
                    for p in sorted(base.rglob("*")):
                        if count >= 60:
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
                user_parts.append(
                    "## Available files (real, live snapshot)\n"
                    "These are the ONLY files that exist. Do NOT invent paths.\n"
                    "Use `_list_files()` inside `code.execute` to refresh.\n```\n"
                    + "\n".join(tree_lines)
                    + "\n```\n"
                )
        except Exception:
            pass

        user_message = "\n".join(user_parts)

        # Execute via LLM
        llm = LLMClient(model=self._worker_model)
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ]

        # Enforce forbidden_tools from worker_policy
        enforced = (
            getattr(self._config.worker_policy, "enforced", None)
            if self._config.worker_policy
            else None
        )
        forbidden = (
            set(getattr(enforced, "forbidden_tools", []) or []) if enforced else set()
        )
        if forbidden and tools_allowed:
            original = list(tools_allowed)
            tools_allowed = [t for t in tools_allowed if t not in forbidden]
            removed = set(original) - set(tools_allowed)
            if removed:
                logger.warning(
                    "  Worker %s: removed forbidden tools: %s",
                    worker_id,
                    ", ".join(sorted(removed)),
                )

        # Determine if tools are needed
        if tools_allowed and self._tools:
            tool_defs = self._tools.get_definitions(
                tools_allowed if tools_allowed else None
            )
            if tool_defs:
                # Wrap tool_executor to capture code.execute calls for artifacts
                _tool_call_log: list[dict] = []
                _original_call = self._tools.call

                def _tracking_call(name: str, arguments: dict) -> dict:
                    import time as _t
                    _start = _t.perf_counter()
                    result = _original_call(name, arguments)
                    _dur_ms = (_t.perf_counter() - _start) * 1000.0
                    _tool_call_log.append(
                        {
                            "tool": name,
                            "arguments": arguments,
                            "result": result,
                            "duration_ms": round(_dur_ms, 2),
                        }
                    )
                    self._budget.tool_calls_used += 1
                    # Comprehensive debug log
                    try:
                        ok = bool(result.get("ok", True)) if isinstance(result, dict) else True
                        err = (result.get("error") if isinstance(result, dict) else None) or None
                        self._logger.trace_tool_call(
                            worker_id=worker_id,
                            iteration=str(getattr(self, "_current_iteration", "?")),
                            tool=name,
                            ok=ok,
                            duration_ms=round(_dur_ms, 2),
                            error=str(err) if err else None,
                            arguments=arguments if isinstance(arguments, dict) else None,
                        )
                    except Exception:
                        pass
                    return result

                # Code-mode workers need more rounds: install pkg → run
                # code → handle file warnings → retry → final answer.
                # 5 rounds was too tight and caused many premature failures.
                _max_tool_rounds = 15 if codemode.get("enabled") else 5

                final_msg = llm.chat_with_tools(
                    messages,
                    tools=tool_defs,
                    tool_executor=_tracking_call,
                    max_rounds=_max_tool_rounds,
                    temperature=worker_temperature,
                    max_tokens=16384,
                )
                content = ""
                if isinstance(final_msg, dict):
                    content = final_msg.get("content", "") or ""
                elif isinstance(final_msg, str):
                    content = final_msg
                result = self._parse_json_response(content)
                if not self._has_real_confidence(result):
                    # LLM didn't provide a usable confidence — derive from
                    # tool call outcomes instead of using a meaningless default.
                    result["confidence"] = self._derive_tool_confidence(
                        _tool_call_log
                    )
                    result["_confidence_source"] = "derived_from_tools"

                # Attach tool call log to result for artifact persistence
                if _tool_call_log:
                    result["_tool_calls"] = _tool_call_log

                logger.debug(
                    "Worker %s raw result (with tools):\n%s",
                    worker_id,
                    json.dumps(result, indent=2, default=str, ensure_ascii=False),
                )

                # Process tool creation from result
                if tool_creation:
                    tools_in_result = result.get("tools_created", [])
                    logger.info(
                        "Worker %s returned %d tools_created entries",
                        worker_id,
                        len(tools_in_result)
                        if isinstance(tools_in_result, list)
                        else 0,
                    )
                    self._process_tool_creation(result, worker_id, codemode, llm_client=llm)

                    logger.info(
                        "Worker %s after tool processing — tools_registered: %s",
                        worker_id,
                        json.dumps(
                            result.get("tools_registered", []), indent=2, default=str
                        ),
                    )
                self._budget.tokens_consumed += llm.total_tokens_used
                return result

        # Simple call (no tools)
        try:
            result = llm.chat_json(messages, temperature=worker_temperature, max_tokens=4096)
            if not isinstance(result, dict):
                result = {"result": str(result), "confidence": 0.0, "_confidence_source": "parse_failure"}
        except Exception:
            text = llm.chat_text(messages, temperature=worker_temperature, max_tokens=4096)
            result = self._parse_json_response(text)

        if not self._has_real_confidence(result):
            result["confidence"] = 0.0
            result["_confidence_source"] = "missing_from_llm"

        logger.debug(
            "Worker %s raw result (simple call):\n%s",
            worker_id,
            json.dumps(result, indent=2, default=str, ensure_ascii=False),
        )

        # Process tool creation from result
        if tool_creation:
            tools_in_result = result.get("tools_created", [])
            logger.info(
                "Worker %s returned %d tools_created entries (simple call)",
                worker_id,
                len(tools_in_result) if isinstance(tools_in_result, list) else 0,
            )
            self._process_tool_creation(result, worker_id, codemode)

            logger.info(
                "Worker %s after tool processing — tools_registered: %s",
                worker_id,
                json.dumps(result.get("tools_registered", []), indent=2, default=str),
            )

        self._budget.tokens_consumed += llm.total_tokens_used
        return result

    @staticmethod
    def _build_directory_tree(
        workspace: Path, output: Path, max_files: int = 60
    ) -> str:
        """Build a markdown directory tree of workspace + output for the worker prompt.

        This gives workers a complete picture of what files exist so they can
        read data from previous workers or avoid overwriting existing files.
        """
        lines: list[str] = []
        count = 0

        def _walk(base: Path, label: str, var_name: str, depth: int = 0) -> None:
            nonlocal count
            if count >= max_files or not base.exists():
                return
            try:
                entries = sorted(base.iterdir(), key=lambda p: (p.is_file(), p.name))
            except OSError:
                return
            for entry in entries:
                if count >= max_files:
                    lines.append(f"{'  ' * (depth + 1)}... (truncated)")
                    return
                if entry.name.startswith(".") or entry.name == "__pycache__":
                    continue
                rel = entry.relative_to(base)
                if entry.is_dir():
                    lines.append(f"{'  ' * (depth + 1)}{entry.name}/")
                    _walk(entry, label, var_name, depth + 1)
                else:
                    size = entry.stat().st_size
                    if size < 1024:
                        s = f"{size} B"
                    elif size < 1024 * 1024:
                        s = f"{size / 1024:.1f} KB"
                    else:
                        s = f"{size / (1024 * 1024):.1f} MB"
                    access = f'{var_name} + "/{rel}"'
                    lines.append(f"{'  ' * (depth + 1)}{entry.name}  ({s})  →  `{access}`")
                    count += 1

        has_files = False

        # Workspace tree
        ws_entries = []
        if workspace.exists():
            try:
                ws_entries = [
                    e for e in workspace.iterdir()
                    if not e.name.startswith(".") and e.name != "__pycache__"
                ]
            except OSError:
                pass

        if ws_entries:
            lines.append(f"_workspace_dir = `{workspace}`")
            _walk(workspace, "workspace", "_workspace_dir")
            has_files = True

        # Output tree
        out_entries = []
        if output.exists():
            try:
                out_entries = [
                    e for e in output.rglob("*")
                    if e.is_file() and not e.name.startswith(".")
                ]
            except OSError:
                pass

        if out_entries:
            lines.append(f"_output_dir = `{output}`")
            _walk(output, "output", "_output_dir")
            has_files = True

        if not has_files:
            return ""

        header = (
            "## Workspace Directory Tree\n\n"
            "These files currently exist. Use the paths shown to read/write them.\n"
            "Call `_list_files()` in `code.execute` for a live listing at runtime.\n"
            "Always use `_ensure_dir(path)` before writing to subdirectories.\n\n"
            "```\n"
        )
        return header + "\n".join(lines) + "\n```\n\n"

    def _build_tool_creation_prompt(self, namespace: str) -> str:
        """Build the prompt section that instructs the worker to create tools.

        Includes the list of available secret key names (not values!) so the
        worker can declare ``required_secrets`` for tools that need API keys.
        """
        # Collect available secret key names (never expose values)
        available_secret_keys: list[str] = []
        if self._tools and hasattr(self._tools, "_secrets") and self._tools._secrets:
            available_secret_keys = sorted(self._tools._secrets.keys())

        secrets_section = ""
        if available_secret_keys:
            keys_list = "\n".join(f"  - `{k}`" for k in available_secret_keys)
            secrets_section = f"""
## Available Secrets

The following API keys / secrets are available for your tools to use.
To access them, add a `required_secrets` array to your tool spec listing
the keys your tool needs. At runtime the matching values will be injected
into a `_secrets` dict variable that your handler code can read.

Available keys:
{keys_list}

**How to use secrets in your tool code:**
```python
def handler(*, query):
    api_key = _secrets.get("OPENAI_API_KEY", "")
    # Use api_key in your API call...
    return {{"ok": True, "status": 200, "data": {{}}, "error": None}}
```

**Important:**
- `_secrets` is a pre-defined dict variable — do NOT add it to your handler signature
- Only request keys you actually need
- Always provide a fallback with `.get("KEY", "")` in case the key is missing
"""

        return f"""
## Tool Creation Mode

You are in TOOL CREATION mode. Your job is to generate reusable Python tools.

### Top failure patterns — AVOID these (each one wastes a full iteration):

1. **Forgot `return`** — handler MUST end with `return {{"ok": True, "status": 200, "data": {{...}}, "error": None}}`. No print, no implicit None.
2. **Wrong signature** — MUST be `def handler(*, arg1, arg2):` with the `*`. Positional args are rejected.
3. **Schema/signature mismatch** — every key your handler reads (`arg1`, `arg2`) MUST appear in `parameters.properties`, and vice versa. Validator compares them and rejects mismatches.
4. **Forbidden imports** — NEVER import `os`, `sys`, `subprocess`, `ctypes`, `importlib`, `signal`, `multiprocessing`. Use the pre-defined helpers (`_output_dir`, `_workspace_dir`, `_ensure_dir`, `_safe_open`/builtin `open`) instead.
5. **Placeholder outputs** — never write base64 1x1 PNGs or 100-byte "PDF" stubs. Use real libraries (matplotlib for charts, reportlab for PDFs). If a library is missing, request it via the `pip.install` tool BEFORE creating the tool.
6. **Reading `_secrets` not declared** — if you read `_secrets["FOO"]`, you MUST list `"FOO"` in `required_secrets`.
7. **Multi-line JSON output** — only the LAST line of stdout is parsed as the result. Do not `print` after the result line.

### DO ✅
```python
def handler(*, value, weight):
    score = min(value / 100.0, 1.0) * weight
    return {{"ok": True, "status": 200, "data": {{"score": round(score, 4)}}, "error": None}}
```

### DON'T ❌
```python
import os                              # forbidden import
def handler(value, weight):            # missing '*', positional args
    score = value * weight
    print(score)                       # no return
```

### Required tool spec fields

For each tool you create, include it in the `tools_created` array in your response.
Each tool object must have:
- `name`: Fully qualified name in the "{namespace}" namespace (e.g., "{namespace}.calculate_score")
- `description`: What the tool does
- `parameters`: JSON Schema for the tool's input parameters. The `properties` keys MUST exactly match the keyword arguments your `handler` reads.
- `code`: Python code containing a `def handler(*, ...)` function that returns a dict with `{{"ok": True, "status": 200, "data": {{}}, "error": None}}`
- `required_secrets` (optional): Array of secret key names the tool needs at runtime (e.g., `["OPENAI_API_KEY"]`). The values are injected as a `_secrets` dict variable in the sandbox.

Example tool (without secrets):
```json
{{
  "name": "{namespace}.weighted_score",
  "description": "Calculate a weighted score",
  "parameters": {{
    "type": "object",
    "properties": {{
      "value": {{"type": "number", "description": "Raw value"}},
      "weight": {{"type": "number", "description": "Weight factor"}}
    }},
    "required": ["value", "weight"]
  }},
  "code": "def handler(*, value, weight):\\n    score = min(value / 100.0, 1.0) * weight\\n    return {{\\"ok\\": True, \\"status\\": 200, \\"data\\": {{\\"score\\": round(score, 4)}}, \\"error\\": None}}"
}}
```

Example tool (with secrets):
```json
{{
  "name": "{namespace}.api_search",
  "description": "Search via an external API using an API key",
  "required_secrets": ["SEARCH_API_KEY"],
  "parameters": {{
    "type": "object",
    "properties": {{
      "query": {{"type": "string", "description": "Search query"}}
    }},
    "required": ["query"]
  }},
  "code": "import urllib.request, urllib.parse, json\\ndef handler(*, query):\\n    api_key = _secrets.get(\\"SEARCH_API_KEY\\", \\"\\")\\n    url = f\\"https://api.example.com/search?q={{urllib.parse.quote(query)}}&key={{api_key}}\\"\\n    resp = urllib.request.urlopen(url, timeout=10)\\n    data = json.loads(resp.read())\\n    return {{\\"ok\\": True, \\"status\\": 200, \\"data\\": data, \\"error\\": None}}"
}}
```

## File Output

Your tool code can save files (PNG charts, CSV exports, JSON data, etc.) to disk.
Two pre-defined string variables are available in the sandbox:

- `_workspace_dir` — path to the workspace directory (for intermediate files)
- `_output_dir` — path to the output directory (for final deliverables like charts, reports)

Use Python's built-in `open()` to write files. Do NOT import `os` or `pathlib` —
use string concatenation for paths instead.

**Example: saving a PNG chart:**
```python
import matplotlib
matplotlib.use("Agg")  # non-interactive backend
import matplotlib.pyplot as plt

def handler(*, data, filename):
    plt.figure()
    plt.plot(data)
    plt.title("Chart")
    filepath = _output_dir + "/" + filename
    plt.savefig(filepath, dpi=150, bbox_inches="tight")
    plt.close()
    return {{"ok": True, "status": 200, "data": {{"file": filepath}}, "error": None}}
```

**Example: saving a CSV:**
```python
import csv

def handler(*, rows, filename):
    filepath = _output_dir + "/" + filename
    with open(filepath, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerows(rows)
    return {{"ok": True, "status": 200, "data": {{"file": filepath, "rows": len(rows)}}, "error": None}}
```

Rules:
- Tools MUST have a `def handler(*, ...)` function (keyword-only arguments)
- Tools MUST return the standard AWP format: `{{"ok": bool, "status": int, "data": {{}}, "error": str|None}}`
{self._build_namespace_import_rules(namespace)}- Use `_output_dir + "/" + filename` for file paths (string concatenation)
- Use `_ensure_dir(path)` before writing to subdirectories (creates parent dirs automatically)
- Keep tool code concise and focused
- If your tool needs an API key, declare it in `required_secrets` and access it via `_secrets.get("KEY_NAME", "")`
- The `_secrets`, `_workspace_dir`, `_output_dir` variables are pre-defined — do NOT add them as handler parameters
{secrets_section}"""

    def _process_tool_creation(
        self,
        result: dict,
        worker_id: str,
        codemode: dict,
        llm_client: Any = None,
    ) -> None:
        """Extract tools from worker result and register them via DynamicToolFactory.

        Preserves the full ``tools_created`` array (with code, parameters, etc.)
        in the result so that downstream logging and debug output can inspect
        the complete tool specifications.  Adds ``tools_registered`` with
        per-tool registration status and the full spec for each tool.
        """
        tools_created = result.get("tools_created", [])
        if not isinstance(tools_created, list) or not tools_created:
            return

        namespace = codemode.get("tool_creation_namespace", "dynamic")
        registered = []

        for tool_spec in tools_created:
            if not isinstance(tool_spec, dict):
                continue

            name = tool_spec.get("name", "")
            code = tool_spec.get("code", "")
            description = tool_spec.get("description", "")
            parameters = tool_spec.get("parameters", {})
            req_secrets = tool_spec.get("required_secrets", [])
            if not isinstance(req_secrets, list):
                req_secrets = []

            # Build full record for logging (always keep full spec)
            full_record = {
                "name": name,
                "description": description,
                "parameters": parameters,
                "code": code,
                "worker_id": worker_id,
                "namespace": namespace,
                "required_secrets": req_secrets,
            }

            if not name or not code:
                logger.warning("Skipping tool with missing name or code: %s", tool_spec)
                full_record["registered"] = False
                full_record["error"] = "missing name or code"
                registered.append(full_record)
                continue

            logger.info(
                "  Worker %s tool creation attempt: %s\n"
                "    Description: %s\n"
                "    Parameters:  %s\n"
                "    Required secrets: %s\n"
                "    Code (%d chars):\n%s",
                worker_id,
                name,
                description,
                json.dumps(parameters, indent=2, default=str),
                req_secrets,
                len(code),
                code,
            )

            # Try to register via DynamicToolFactory if available
            if self._tools and hasattr(self._tools, "_dynamic_tool_factory"):
                factory = self._tools._dynamic_tool_factory
                if factory and factory.enabled:
                    reg_result = factory.create_tool(
                        name=name,
                        description=description,
                        parameters=parameters,
                        code=code,
                        creator_agent=worker_id,
                        max_tools=codemode.get("max_tools", 10),
                        allowed_namespace=namespace,
                        required_secrets=req_secrets if req_secrets else None,
                    )
                    # B4: Inline LLM repair loop for repairable failures.
                    if (
                        not reg_result.get("ok")
                        and reg_result.get("repairable", False)
                        and llm_client is not None
                    ):
                        from .tool_repair import attempt_repair

                        max_repair = int(codemode.get("repair_attempts", 2))
                        logger.warning(
                            "  Tool %s failed (%s) — entering repair loop (max %d)",
                            name,
                            reg_result.get("category", "?"),
                            max_repair,
                        )
                        reg_result = attempt_repair(
                            llm_client=llm_client,
                            factory=factory,
                            tool_spec={
                                "name": name,
                                "description": description,
                                "parameters": parameters,
                                "code": code,
                                "required_secrets": req_secrets,
                            },
                            failed_result=reg_result,
                            creator_agent=worker_id,
                            namespace=namespace,
                            max_tools=codemode.get("max_tools", 10),
                            max_attempts=max_repair,
                        )

                    if reg_result.get("ok"):
                        logger.info(
                            "  Worker %s created tool: %s — OK%s",
                            worker_id,
                            name,
                            " (repaired)" if reg_result.get("repaired") else "",
                        )
                        full_record["registered"] = True
                        if reg_result.get("repaired"):
                            full_record["repaired"] = True
                            full_record["repair_attempts"] = reg_result.get(
                                "repair_attempts", 0
                            )
                        if reg_result.get("cache_hit"):
                            full_record["cache_hit"] = True
                    else:
                        error = reg_result.get("error", "unknown")
                        logger.warning(
                            "  Tool creation FAILED for %s: %s\n"
                            "    Status: %s\n"
                            "    Category: %s\n"
                            "    Full result: %s",
                            name,
                            error,
                            reg_result.get("status", "?"),
                            reg_result.get("category", "?"),
                            json.dumps(reg_result, indent=2, default=str),
                        )
                        full_record["registered"] = False
                        full_record["error"] = error
                        full_record["category"] = reg_result.get("category", "")
                        full_record["validation_result"] = reg_result
                    registered.append(full_record)
                    continue

            # Fallback: just log that we received the tool spec
            logger.info(
                "  Worker %s defined tool: %s (not registered — no factory)",
                worker_id,
                name,
            )
            full_record["registered"] = False
            full_record["reason"] = "no_factory"
            registered.append(full_record)

        # Keep original tools_created AND add enriched tools_registered
        # (tools_created is preserved as-is for backward compatibility)
        result["tools_registered"] = registered

    # -- Validation -------------------------------------------------------

    def _validate_results(
        self, delegation_results: list[dict], task: str
    ) -> list[dict]:
        """Two-tier validation: deterministic + LLM."""
        validation_results = []

        for dr in delegation_results:
            result = dr.get("result", {})
            worker_id = dr.get("worker_id", "?")
            v: dict[str, Any] = {"worker_id": worker_id, "deterministic": {}, "llm": {}}

            # Tier 1: Deterministic
            det = self._validate_deterministic(result)
            v["deterministic"] = det

            if not det.get("passed", False):
                v["feedback"] = (
                    f"Deterministic validation failed: {det.get('errors', [])}"
                )
                validation_results.append(v)
                continue

            # Include deterministic warnings in feedback even when passed
            det_warnings = det.get("warnings", [])
            if det_warnings:
                v["feedback_warnings"] = det_warnings

            # Tier 2: LLM (if enabled and conditions met)
            val_cfg = self._config.validation
            confidence = result.get("confidence", 0.0)
            if (
                val_cfg.llm.enabled
                and confidence < val_cfg.llm.skip_when_confidence_above
                and self._budget.budget_fraction_remaining
                > val_cfg.llm.skip_when_budget_remaining_below
            ):
                llm_result = self._validate_llm(result, task, worker_id)
                v["llm"] = llm_result
                v["feedback"] = llm_result.get("feedback", "ok")

                # Adjust confidence if LLM validator suggests it
                adjusted = llm_result.get("adjusted_confidence")
                if adjusted is not None:
                    result["confidence"] = adjusted
            else:
                v["feedback"] = "ok (LLM validation skipped)"

            validation_results.append(v)

        return validation_results

    def _validate_deterministic(self, result: dict) -> dict:
        """Tier 1: Cheap deterministic checks."""
        errors = []
        warnings = []

        # Must be a dict
        if not isinstance(result, dict):
            return {"passed": False, "errors": ["Result is not a dict"], "warnings": [], "file_warnings": []}

        # Must have confidence
        if "confidence" not in result:
            errors.append("Missing 'confidence' field — worker did not self-assess")

        # Confidence must be valid
        conf = result.get("confidence", 0)
        if not isinstance(conf, (int, float)):
            errors.append(f"Confidence is not a number: {type(conf)}")
        elif not (0.0 <= conf <= 1.0):
            errors.append(f"Confidence out of range: {conf}")

        # Flag derived/fallback confidence as a warning (informational, not a failure)
        source = result.get("_confidence_source")
        if source:
            warnings.append(
                f"Confidence was not provided by worker (source: {source})"
            )

        # Must not be only an error
        if "error" in result and len(result) <= 2:  # just error + confidence
            errors.append("Result contains only an error")

        # --- File output validation (Phase 3: safety net) ---
        file_warnings = self._validate_output_files()
        if file_warnings:
            # Classify severity of each file warning
            from .file_validator import classify_warning_severity
            critical_count = 0
            for w in file_warnings:
                errors.append(f"Invalid output file: {w}")
                # Try to extract path from warning for severity classification
                # Warnings start with "filename.ext: ..."
                fname = w.split(":")[0].strip() if ":" in w else ""
                if fname:
                    # Check candidate paths in output and workspace
                    for search_dir in [self._dir / "output" / self._run_id, self._dir / "workspace" / "outputs"]:
                        candidates = list(search_dir.rglob(fname)) if search_dir.exists() else []
                        for p in candidates:
                            severity = classify_warning_severity(p, w)
                            if severity == "critical":
                                critical_count += 1
                                break

            # Penalize confidence — critical files get heavy penalty
            if isinstance(conf, (int, float)) and conf > 0:
                if critical_count > 0:
                    # Critical files (0-byte, placeholder PNGs) → heavy penalty
                    penalty = min(0.8, 0.2 * critical_count)
                else:
                    penalty = min(0.3, 0.1 * len(file_warnings))
                result["confidence"] = max(0.0, conf - penalty)
                result["_confidence_penalty_reason"] = (
                    f"Reduced by {penalty:.1f} due to {len(file_warnings)} "
                    f"invalid output file(s) ({critical_count} critical)"
                )

        return {"passed": len(errors) == 0, "errors": errors, "warnings": warnings, "file_warnings": file_warnings}

    # Compiled regex for placeholder values that indicate the manager
    # terminated the run with stub deliverables instead of real content.
    _PLACEHOLDER_PATTERNS: tuple[str, ...] = (
        r"\bXX%?",          # XX, XX%
        r"\bTODO\b",
        r"\bTBD\b",
        r"\bN/A\b",
        r"\?\?\?+",          # ??? or longer
        r"<placeholder[^>]*>",
        r"\{\{\s*[A-Za-z_][A-Za-z0-9_ ]*\s*\}\}",  # mustache-style {{ var }}
        r"\bFIXME\b",
        r"\blorem ipsum\b",
        # --- Manager template-stub leakage (observed with weak LLMs that
        #     verbatim copy the example skeleton from their own system prompt)
        r"\bfinal output here\b",
        r"\byour final output here\b",
        r"\bwhy the task is complete\b",
        r"\b<your[^>]*>",          # <your-text>, <your value>, ...
        r"\bplaceholder\b",
        r"\bexample[_ ]value\b",
        r"\bfill[_ ]in[_ ]here\b",
    )

    # Keys that, when present at any depth in `final_result`, are
    # unambiguous evidence the manager copied the prompt template stub
    # instead of producing real content. e.g. {"your": "final output here"}.
    _PLACEHOLDER_KEYS: frozenset[str] = frozenset({
        "your", "your_field", "your_key", "your_value",
        "field_name", "key_name", "example_field",
    })

    # Keywords (case-insensitive) in the task description that imply a
    # file deliverable must end up in `_output_dir`. Mapped to a friendly
    # name used in the rejection message.
    _DELIVERABLE_HINTS: tuple[tuple[tuple[str, ...], str], ...] = (
        (("image", "picture", "photo", "illustration", "render",
          "bild", "foto", "illustration", "zeichnung", "grafik", "logo"),
         "an image file"),
        (("pdf", "document", "report", "dokument", "bericht"),
         "a document file (pdf/md)"),
        (("chart", "plot", "graph", "diagram", "figure", "diagramm"),
         "a chart/figure file"),
        (("video", "animation", "gif"),
         "a video/animation file"),
        (("audio", "sound", "mp3", "wav"),
         "an audio file"),
        (("dataset", "csv", "spreadsheet", "table", "tabelle"),
         "a data file (csv/xlsx)"),
    )

    def _check_missing_deliverable(self, task: str) -> str:
        """Return a non-empty string describing the missing deliverable
        if the task implies a file output but `_output_dir` (the run's
        output dir) is empty or contains only placeholder-sized files.
        Empty string means the gate is satisfied.
        """
        if not task:
            return ""
        text = task.lower()
        matched: list[str] = []
        for keywords, label in self._DELIVERABLE_HINTS:
            if any(k in text for k in keywords):
                matched.append(label)
        if not matched:
            return ""
        # Inspect the run output dir for any non-trivial file (>=512 B).
        run_out = self._dir / "output" / (self._run_id or "")
        if not run_out.exists():
            return (
                f"Task implies {matched[0]}, but output directory does not "
                f"exist yet ({run_out})."
            )
        substantial = [
            p for p in run_out.rglob("*")
            if p.is_file() and p.stat().st_size >= 512
        ]
        if not substantial:
            return (
                f"Task implies {matched[0]}, but `_output_dir` is empty "
                f"(no file >=512 B found in {run_out})."
            )
        return ""

    def _scan_placeholders(self, result: dict) -> list[str]:
        """Scan a final_result dict and any declared output files for
        obvious placeholder strings. Returns a list of human-readable
        findings; empty list means the deliverables look real.

        This is a hard gate: if any placeholder is found and budget allows,
        the manager's "complete" decision is rejected and another iteration
        is forced. The model often emits stub tables like ``XX%`` or
        ``Profit Factor: TODO`` and then declares success — without this
        check those would be persisted as final deliverables.
        """
        import re

        if not result:
            return []

        compiled = [re.compile(p, re.IGNORECASE) for p in self._PLACEHOLDER_PATTERNS]
        findings: list[str] = []

        def _scan_text(label: str, text: str) -> None:
            if not text or not isinstance(text, str):
                return
            # Skip very large blobs by sampling first 200k chars to avoid
            # pathological scans on huge logs.
            sample = text[:200_000]
            for pat in compiled:
                m = pat.search(sample)
                if m:
                    snippet = sample[max(0, m.start() - 20): m.end() + 20].replace("\n", " ").strip()
                    findings.append(f"{label}: '{snippet}' (matched /{pat.pattern}/)")
                    return  # one finding per scope is enough

        def _walk(label: str, value: object) -> None:
            if isinstance(value, str):
                _scan_text(label, value)
            elif isinstance(value, dict):
                for k, v in value.items():
                    if isinstance(k, str) and k.startswith("_"):
                        continue  # skip internal annotations like _critique
                    if isinstance(k, str) and k.lower() in self._PLACEHOLDER_KEYS:
                        findings.append(
                            f"{label}: contains stub key '{k}' "
                            f"(template skeleton was copied verbatim)"
                        )
                    _walk(f"{label}.{k}", v)
            elif isinstance(value, (list, tuple)):
                for i, v in enumerate(value):
                    _walk(f"{label}[{i}]", v)

        _walk("result", result)

        # Also scan declared output files (text-based) on disk so we catch
        # placeholders that the manager wrote into files but didn't reflect
        # in `final_result`.
        text_exts = {".md", ".txt", ".csv", ".json", ".yaml", ".yml", ".html", ".tex"}
        scan_dirs: list = []
        ws_out = self._dir / "workspace" / "outputs"
        run_out = self._dir / "output" / self._run_id
        if ws_out.exists():
            scan_dirs.append(ws_out)
        if run_out.exists():
            scan_dirs.append(run_out)
        for d in scan_dirs:
            for p in d.rglob("*"):
                if not p.is_file():
                    continue
                if p.suffix.lower() not in text_exts:
                    continue
                try:
                    if p.stat().st_size > 5_000_000:
                        continue  # skip huge files
                    txt = p.read_text(encoding="utf-8", errors="replace")
                except Exception:
                    continue
                _scan_text(f"file:{p.name}", txt)

        # De-duplicate while preserving order
        seen: set[str] = set()
        unique: list[str] = []
        for f in findings:
            if f not in seen:
                seen.add(f)
                unique.append(f)
        return unique

    # ----------------------------------------------------------------
    # Append-only deliverable protection
    #
    # After every iteration we snapshot workspace/outputs/ into
    #   <run_dir>/iterations/<NNN>/_outputs_snapshot/
    # On termination we walk all snapshots and, for each deliverable
    # filename, restore the LARGEST version found across history (after
    # rejecting placeholder content). This guarantees that a later worker
    # which overwrites a good summary.md / backtest.py / cbot.cs / png
    # with a shorter buggy version cannot regress the run's final output.
    # ----------------------------------------------------------------

    def _outputs_dir(self) -> Path:
        return self._dir / "workspace" / "outputs"

    def _snapshot_deliverables(self, iteration: int) -> None:
        """Copy workspace/outputs/ into the per-iteration snapshot dir."""
        src = self._outputs_dir()
        if not src.exists():
            return
        dst = (
            self._run_dir
            / "iterations"
            / f"{iteration:03d}"
            / "_outputs_snapshot"
        )
        if dst.exists():
            return  # idempotent
        try:
            import shutil
            # Copy as a tree but skip our own snapshot dirs (defensive)
            def _ignore(_d: str, names: list[str]) -> list[str]:
                return [n for n in names if n.startswith("_outputs_snapshot")]
            shutil.copytree(src, dst, ignore=_ignore, dirs_exist_ok=False)
        except Exception as exc:
            logger.debug("snapshot copy failed for iter %d: %s", iteration, exc)

    def _restore_best_deliverables(self) -> None:
        """Walk all per-iteration snapshots and, for each deliverable file
        path (relative to workspace/outputs/), pick the LARGEST surviving
        version that does not contain placeholder strings, and restore it
        if it is bigger than the current on-disk version (or if the
        current version is missing/empty/placeholder)."""
        outputs = self._outputs_dir()
        iters_dir = self._run_dir / "iterations"
        if not iters_dir.exists():
            return

        # Build map: rel_path -> (best_size, best_path, iter_number)
        best: dict[str, tuple[int, Path, int]] = {}
        placeholder_re = None
        try:
            import re
            placeholder_re = re.compile(
                r"\bXX%?|\bTODO\b|\bTBD\b|\?\?\?+|<placeholder",
                re.IGNORECASE,
            )
        except Exception:
            pass

        for iter_dir in sorted(iters_dir.iterdir()):
            snap = iter_dir / "_outputs_snapshot"
            if not snap.is_dir():
                continue
            try:
                iter_num = int(iter_dir.name)
            except ValueError:
                iter_num = 0
            for f in snap.rglob("*"):
                if not f.is_file():
                    continue
                try:
                    rel = str(f.relative_to(snap))
                except ValueError:
                    continue
                size = f.stat().st_size
                if size == 0:
                    continue
                # Reject placeholder content for text-like files
                if placeholder_re and f.suffix.lower() in {
                    ".md", ".txt", ".csv", ".json", ".yaml", ".yml", ".html",
                    ".py", ".cs", ".js", ".ts",
                }:
                    try:
                        head = f.read_text(encoding="utf-8", errors="replace")[:50_000]
                        if placeholder_re.search(head):
                            continue
                    except Exception:
                        pass
                cur = best.get(rel)
                if cur is None or size > cur[0]:
                    best[rel] = (size, f, iter_num)

        if not best:
            return

        restored = 0
        outputs.mkdir(parents=True, exist_ok=True)
        text_exts = {
            ".md", ".txt", ".csv", ".json", ".yaml", ".yml", ".html",
            ".py", ".cs", ".js", ".ts",
        }
        for rel, (best_size, best_path, iter_num) in best.items():
            target = outputs / rel
            need_restore = False
            if not target.exists():
                need_restore = True
            else:
                try:
                    cur_size = target.stat().st_size
                except OSError:
                    cur_size = 0
                # Detect placeholder content in current file even if it's
                # large — bigger ≠ better when the content is "TODO ..." padding.
                cur_has_placeholder = False
                if (
                    placeholder_re
                    and target.suffix.lower() in text_exts
                ):
                    try:
                        ch = target.read_text(encoding="utf-8", errors="replace")[:50_000]
                        if placeholder_re.search(ch):
                            cur_has_placeholder = True
                    except Exception:
                        pass
                if cur_size == 0 or cur_has_placeholder or best_size > cur_size:
                    need_restore = True
            if need_restore:
                try:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    import shutil
                    shutil.copy2(best_path, target)
                    restored += 1
                    logger.info(
                        "Restored deliverable %s from iter %03d snapshot "
                        "(%d bytes, larger than current)",
                        rel, iter_num, best_size,
                    )
                except Exception as exc:
                    logger.debug("restore failed for %s: %s", rel, exc)

        if restored:
            try:
                self._logger.trace(
                    "deliverables",
                    f"restored {restored} file(s) from snapshots",
                    level="INFO",
                    restored=restored,
                )
            except Exception:
                pass

    def _validate_output_files(self) -> list[str]:
        """Scan workspace and output dirs for invalid files."""
        from .file_validator import validate_directory

        warnings: list[str] = []
        workspace = self._dir / "workspace"
        run_output = self._dir / "output" / self._run_id
        if workspace.exists():
            # Only validate outputs subdir of workspace (not inputs, context, etc.)
            ws_outputs = workspace / "outputs"
            if ws_outputs.exists():
                warnings.extend(validate_directory(ws_outputs))
        if run_output.exists():
            warnings.extend(validate_directory(run_output))
        return warnings

    def _classify_output_warning(self, warning: str) -> str:
        """Classify a file warning string as critical/error/warning.

        Extracts the filename from the warning (format: 'name.ext: ...'),
        finds the actual file on disk, and uses classify_warning_severity.
        Falls back to heuristic if the file can't be located.
        """
        from .file_validator import classify_warning_severity

        fname = warning.split(":")[0].strip() if ":" in warning else ""
        if fname:
            for search_dir in [
                self._dir / "output" / self._run_id,
                self._dir / "workspace" / "outputs",
            ]:
                if search_dir.exists():
                    candidates = list(search_dir.rglob(fname))
                    for p in candidates:
                        return classify_warning_severity(p, warning)
        # Heuristic fallback: placeholder keywords → critical
        w_lower = warning.lower()
        if "placeholder" in w_lower or "1×1" in w_lower or "0 bytes" in w_lower:
            return "critical"
        return "warning"

    def _validate_llm(self, result: dict, task: str, worker_id: str) -> dict:
        """Tier 2: LLM-based semantic validation."""
        try:
            llm = LLMClient(model=self._worker_model)

            messages = [
                {
                    "role": "system",
                    "content": (
                        "You are a Validation Agent. Evaluate whether a worker's result "
                        "meaningfully addresses the original task. Respond with JSON:\n"
                        '{"valid": true/false, "adjusted_confidence": 0.0-1.0, '
                        '"feedback": "...", "suggestion": "..."}'
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"## Original Task\n{task}\n\n"
                        f"## Worker ID: {worker_id}\n"
                        f"## Worker Result\n```json\n"
                        f"{json.dumps(result, indent=2, default=str)}\n```\n\n"
                        f"Does this result meaningfully address the task? "
                        f"Is the confidence realistic?"
                    ),
                },
            ]

            v_result = llm.chat_json(messages, temperature=0.1, max_tokens=1024)
            self._budget.tokens_consumed += llm.total_tokens_used
            return v_result

        except Exception as exc:
            logger.warning("LLM validation failed: %s", exc)
            return {"valid": True, "feedback": f"LLM validation error: {exc}"}

    # -- Helpers ----------------------------------------------------------

    @staticmethod
    def _parse_json_response(text: str) -> dict:
        """Robustly parse an LLM response as JSON.

        Tries multiple strategies:
        1. Direct JSON parse (strict, then lenient)
        2. Strip markdown code fences and parse
        3. Extract the first {...} block from freetext via brace-matching
        4. Repair truncated JSON

        All json.loads calls use strict=False to tolerate literal control
        characters (newlines, tabs) inside JSON string values — a common
        LLM output quirk that causes strict parsing to fail.
        """
        if not text or not isinstance(text, str):
            return {
                "result": str(text) if text is not None else "",
                "confidence": 0.3,
                "_confidence_source": "parse_failure",
            }
        cleaned = text.strip()

        def _try_parse(s: str) -> dict | None:
            """Try parsing with strict=True first, then strict=False."""
            for strict in (True, False):
                try:
                    parsed = json.loads(s, strict=strict)
                    if isinstance(parsed, dict):
                        return parsed
                except (json.JSONDecodeError, ValueError):
                    pass
            return None

        # Strategy 1: direct parse
        result = _try_parse(cleaned)
        if result is not None:
            return result

        # Strategy 2: strip markdown code fences
        if "```" in cleaned:
            lines = cleaned.split("\n")
            lines = [line for line in lines if not line.strip().startswith("```")]
            fenced = "\n".join(lines).strip()
            result = _try_parse(fenced)
            if result is not None:
                return result

        # Strategy 3: find the first top-level {...} block via brace matching
        start = cleaned.find("{")
        if start != -1:
            depth = 0
            in_string = False
            escape = False
            # Track the stack of open delimiters for truncation repair
            stack: list[str] = []
            for i in range(start, len(cleaned)):
                ch = cleaned[i]
                if escape:
                    escape = False
                    continue
                if ch == "\\":
                    escape = True
                    continue
                if ch == '"' and not escape:
                    in_string = not in_string
                    continue
                if in_string:
                    continue
                if ch == "{":
                    depth += 1
                    stack.append("}")
                elif ch == "[":
                    stack.append("]")
                elif ch == "}":
                    depth -= 1
                    if stack and stack[-1] == "}":
                        stack.pop()
                    if depth == 0:
                        candidate = cleaned[start : i + 1]
                        result = _try_parse(candidate)
                        if result is not None:
                            return result
                        break
                elif ch == "]":
                    if stack and stack[-1] == "]":
                        stack.pop()

            # Strategy 4: repair truncated JSON — LLM response was cut off
            # mid-output (e.g. max_tokens reached).  Progressively trim the
            # tail and close open delimiters until we get valid JSON.
            if depth > 0:
                fragment = cleaned[start:]
                # Try progressively shorter truncation points
                for trim_to in _find_truncation_points(fragment):
                    candidate = fragment[:trim_to]
                    # Re-scan to find what delimiters are open at this point
                    _stack: list[str] = []
                    _in_str = False
                    _esc = False
                    for ch in candidate:
                        if _esc:
                            _esc = False
                            continue
                        if ch == "\\":
                            _esc = True
                            continue
                        if ch == '"':
                            _in_str = not _in_str
                            continue
                        if _in_str:
                            continue
                        if ch == "{":
                            _stack.append("}")
                        elif ch == "[":
                            _stack.append("]")
                        elif ch in ("}", "]") and _stack and _stack[-1] == ch:
                            _stack.pop()
                    # If we're inside a string at this point, skip
                    if _in_str:
                        continue
                    repaired = candidate + "".join(reversed(_stack))
                    result = _try_parse(repaired)
                    if result is not None:
                        result["_truncated"] = True
                        logger.warning(
                            "Recovered truncated JSON (trimmed to %d/%d chars, closed %d delimiters)",
                            trim_to, len(fragment), len(_stack),
                        )
                        return result

            # Strategy 5: error-site repair — LLMs sometimes forget to close
            # an inner array/object before moving to the next key, e.g.
            #   "skills": [ "long string",
            #   "tools_allowed": [...]
            # which leaves `[` unclosed mid-structure. The JSONDecodeError
            # position is typically reported AFTER the unclosed scope, so
            # we try inserting one or more close-delimiters at every
            # newline-aligned candidate position walking backward from the
            # error site, for each plausible combination of `]`/`}`.
            fragment = cleaned[start:]
            try:
                json.loads(fragment, strict=False)
            except json.JSONDecodeError as exc:
                err_pos = exc.pos
                if 0 < err_pos <= len(fragment):
                    # Candidate insertion points: walk backward from err_pos
                    # to each newline boundary (skipping leading whitespace).
                    candidates: list[int] = []
                    pos = err_pos
                    while pos > 0:
                        # Trim trailing whitespace + newlines
                        while pos > 0 and fragment[pos - 1] in " \t\r\n":
                            pos -= 1
                        if pos > 0 and pos not in candidates:
                            candidates.append(pos)
                        # Also try position right before a trailing `,` —
                        # the missing close-delimiter often belongs there
                        # (e.g. `"skills": ["str"],\n "next":` needs `]`
                        # inserted before the comma).
                        if pos > 0 and fragment[pos - 1] == ",":
                            cpos = pos - 1
                            # also strip any whitespace before the comma
                            while cpos > 0 and fragment[cpos - 1] in " \t\r\n":
                                cpos -= 1
                            if cpos > 0 and cpos not in candidates:
                                candidates.append(cpos)
                        # Step back to previous newline
                        nl = fragment.rfind("\n", 0, pos)
                        if nl == -1:
                            break
                        pos = nl
                        if len(candidates) >= 16:
                            break

                    closer_combos = ("]", "}", "]]", "}}", "]}", "}]",
                                     "]]]", "}}}", "]]}", "}]]", "]}]", "}]}")
                    for ipos in candidates:
                        for closers in closer_combos:
                            repaired = fragment[:ipos] + closers + fragment[ipos:]
                            result = _try_parse(repaired)
                            if result is not None:
                                logger.warning(
                                    "Recovered malformed JSON via error-site "
                                    "repair (inserted %r at pos %d, err_pos %d)",
                                    closers, ipos, err_pos,
                                )
                                result["_repaired"] = True
                                return result

        return {
            "result": text,
            "confidence": 0.3,
            "_confidence_source": "parse_failure",
        }

    @staticmethod
    def _has_real_confidence(result: dict) -> bool:
        """Check if a result contains a real LLM-provided confidence value.

        Returns False if confidence is missing or was set by a parse-failure fallback.
        """
        if "confidence" not in result:
            return False
        if result.get("_confidence_source") in ("parse_failure", "missing_from_llm", "derived_from_tools"):
            return False
        conf = result["confidence"]
        if not isinstance(conf, (int, float)):
            return False
        return True

    @staticmethod
    def _derive_tool_confidence(tool_call_log: list[dict]) -> float:
        """Derive a confidence score from tool execution outcomes.

        When the LLM does not return a parseable confidence value, we
        estimate one from the tool calls that actually ran:
        - No tool calls → 0.1 (almost no evidence)
        - All succeeded → 0.7 (tools worked, but LLM didn't self-assess)
        - Mixed → proportional between 0.1 and 0.7
        """
        if not tool_call_log:
            return 0.1
        total = len(tool_call_log)
        ok_count = sum(
            1
            for tc in tool_call_log
            if isinstance(tc.get("result"), dict) and tc["result"].get("ok")
        )
        # Scale: 0 ok → 0.1, all ok → 0.7
        return round(0.1 + 0.6 * (ok_count / total), 2)

    def _aggregate_confidence(self, delegation_results: list[dict]) -> float:
        """Aggregate confidence from multiple workers (weighted average)."""
        confidences = []
        for dr in delegation_results:
            conf = dr.get("result", {}).get("confidence", 0.0)
            if isinstance(conf, (int, float)):
                confidences.append(float(conf))
        if not confidences:
            return 0.0
        return sum(confidences) / len(confidences)

    def _extract_key_findings(self, delegation_results: list[dict]) -> str:
        """Extract a summary of key findings from worker results."""
        findings = []
        for dr in delegation_results:
            wid = dr.get("worker_id", "?")
            result = dr.get("result", {})
            # Try common field names
            found_finding = False
            for key in (
                "findings",
                "result",
                "summary",
                "analysis",
                "answer",
                "output",
            ):
                if key in result:
                    val = result[key]
                    if isinstance(val, str) and val.strip():
                        if len(val) > 150:
                            val = val[:150] + "..."
                        findings.append(f"{wid}: {val}")
                        found_finding = True
                    elif isinstance(val, list) and val:
                        findings.append(f"{wid}: {len(val)} items")
                        found_finding = True
                    break

            if not found_finding:
                # Surface tool errors when result is empty
                tool_calls = result.get("_tool_calls", [])
                failed_tools = [
                    tc for tc in tool_calls
                    if isinstance(tc, dict)
                    and isinstance(tc.get("result"), dict)
                    and not tc["result"].get("ok", True)
                ]
                if failed_tools:
                    err = failed_tools[0]["result"].get("error", "unknown error")
                    if isinstance(err, str) and len(err) > 150:
                        err = err[:150] + "..."
                    findings.append(f"{wid}: TOOL ERROR — {err}")
                else:
                    conf = result.get("confidence", "?")
                    findings.append(f"{wid}: confidence={conf}")
        return "; ".join(findings)

    def _build_partial_result(self, reason: str) -> dict:
        """Build a partial result when the loop terminates early.

        Always restore the best-known deliverable snapshot so a partial run
        still ends with the highest-quality outputs we ever produced (not
        whatever a late buggy worker happened to leave on disk).
        """
        try:
            self._restore_best_deliverables()
        except Exception as exc:
            logger.debug("deliverable restore failed: %s", exc)
        last_confidence = (
            self._history[-1].get("confidence", 0.0) if self._history else 0.0
        )
        return {
            "partial": True,
            "termination_reason": reason,
            "iterations_completed": self._iter_counter,
            "confidence": last_confidence,
            "history_summary": [
                {"iteration": h["iteration"], "confidence": h.get("confidence", 0)}
                for h in self._history
            ],
        }
