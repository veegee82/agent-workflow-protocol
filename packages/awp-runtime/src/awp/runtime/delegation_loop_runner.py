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
from .llm import LLMClient
from .tools import ToolRegistry

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


class BudgetSnapshot:
    """Tracks consumed resources across the entire delegation tree."""

    def __init__(self, budget: DelegationBudget) -> None:
        self.max_loops = budget.max_loops
        self.max_total_workers = budget.max_total_workers
        self.max_total_tokens = budget.max_total_tokens
        self.max_wall_time = budget.max_wall_time
        self.max_tool_calls = budget.max_tool_calls
        self.max_depth = budget.max_depth
        # Consumed
        self.loops_used = 0
        self.workers_spawned = 0
        self.tokens_consumed = 0
        self.tool_calls_used = 0
        self.start_time = time.monotonic()

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
        return {
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


class StallDetector:
    """Detects when the delegation loop makes no meaningful progress.

    Uses two independent signals:
    1. Confidence delta — are confidence scores improving?
    2. Output similarity — are worker results actually changing?

    Both channels must agree before stopping; a single channel triggers a
    warning first.
    """

    def __init__(self, window: int = 3, min_delta: float = 0.05) -> None:
        self.window = window
        self.min_delta = min_delta
        self._history: list[float] = []
        self._output_history: list[str] = []
        self._warnings = 0

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

        if confidence_stalled or output_stalled:
            self._warnings += 1
            if self._warnings >= 2:
                return "stop"
            return "warn"

        # Progress detected — reset warnings
        self._warnings = 0
        return "ok"


class RunLogger:
    """Dual-layer logging: structured JSON + human-readable Markdown."""

    def __init__(self, run_dir: Path, fmt: str = "dual") -> None:
        self.run_dir = run_dir
        self.fmt = fmt  # "dual" | "json" | "md"
        self.run_dir.mkdir(parents=True, exist_ok=True)
        (self.run_dir / "iterations").mkdir(exist_ok=True)
        (self.run_dir / "history").mkdir(exist_ok=True)
        (self.run_dir / "artifacts" / "skills").mkdir(parents=True, exist_ok=True)
        (self.run_dir / "artifacts" / "tools").mkdir(parents=True, exist_ok=True)

    def write_json(self, path: Path, data: Any) -> None:
        if self.fmt in ("dual", "json"):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(data, indent=2, default=str, ensure_ascii=False),
                encoding="utf-8",
            )

    def write_md(self, path: Path, content: str) -> None:
        if self.fmt in ("dual", "md"):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")

    def _write_file(self, path: Path, content: str) -> None:
        """Write any file (always, regardless of format setting)."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

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

    def log_iteration_budget(self, iteration: int, budget: "BudgetSnapshot") -> None:
        """Write budget_snapshot.json after iteration finishes."""
        iter_dir = self.run_dir / "iterations" / f"{iteration:03d}"
        iter_dir.mkdir(parents=True, exist_ok=True)
        self.write_json(iter_dir / "budget_snapshot.json", budget.to_dict())

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

        md = (
            f"\n\n---\n## Completion\n"
            f"**Status:** {status}\n"
            f"**Iterations:** {total_iterations}\n"
            f"**Wall Time:** {budget.wall_time_elapsed:.1f}s\n"
            f"**Workers Spawned:** {budget.workers_spawned}\n"
        )
        # Append to RUN_SUMMARY.md
        existing = ""
        run_summary = self.run_dir / "RUN_SUMMARY.md"
        if run_summary.exists():
            existing = run_summary.read_text(encoding="utf-8")
        self.write_md(run_summary, existing + md)

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
    ) -> None:
        self._dir = workflow_dir
        self._config = config
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
        if parent_budget:
            self._budget = parent_budget
        else:
            self._budget = BudgetSnapshot(config.budget)

        # Stall detection
        stall_cfg = config.termination
        self._stall = (
            StallDetector(
                window=stall_cfg.window if stall_cfg else 3,
                min_delta=stall_cfg.min_confidence_delta if stall_cfg else 0.05,
            )
            if (stall_cfg and stall_cfg.enabled)
            else None
        )

        # Logger
        run_dir = self._dir / "workspace" / "runs" / self._run_id
        self._logger = RunLogger(run_dir, fmt=config.logging.format)

        # History
        self._history: list[dict[str, Any]] = []

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

        try:
            final_result, status = self._loop(task, state)
        except Exception as exc:
            logger.error("DelegationLoop error: %s", exc)
            final_result = {"error": str(exc), "confidence": 0.0}
            status = "error"

        self._logger.log_completion(
            self._run_id,
            final_result,
            self._budget,
            self._budget.loops_used,
            status,
        )

        return {"delegation_loop": final_result}

    def _loop(self, task: str, state: dict) -> tuple[dict, str]:
        """Core loop: ask manager → delegate → validate → repeat."""

        while True:
            # Budget check
            can_go, reason = self._budget.can_continue()
            if not can_go:
                logger.warning("Budget exhausted: %s", reason)
                return self._build_partial_result(reason), "budget_exhausted"

            self._budget.loops_used += 1
            iteration = self._budget.loops_used

            logger.info("=== Iteration %d ===", iteration)

            # 1. Ask manager for decision
            manager_decision = self._run_manager(task, state, iteration)
            decision_type = manager_decision.get("decision", "fail")

            # Write manager decision to disk immediately (for file watchers)
            self._logger.log_manager_decision(iteration, manager_decision)

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
                self._logger.log_iteration(
                    iteration,
                    manager_decision,
                    [],
                    self._budget,
                    [],
                )
                return result, "complete"

            if decision_type == "fail":
                return {
                    "error": manager_decision.get("reason", "Manager decided to fail"),
                    "partial_result": manager_decision.get("partial_result", {}),
                    "confidence": 0.0,
                }, "fail"

            if decision_type != "delegate":
                logger.warning("Unknown decision: %s, treating as fail", decision_type)
                return {
                    "error": f"Unknown decision: {decision_type}",
                    "confidence": 0.0,
                }, "fail"

            # 3. Execute delegations (fan-out)
            envelopes = manager_decision.get("delegations", [])
            if not envelopes:
                logger.warning("Manager returned DELEGATE with no delegations")
                continue

            delegation_results = self._execute_delegations(
                envelopes, task, state, iteration=iteration
            )

            # 4. Validate results (2-tier)
            validation_results = self._validate_results(delegation_results, task)

            # 5. Write budget snapshot immediately (for file watchers)
            self._logger.log_iteration_budget(iteration, self._budget)

            # 5b. Log full iteration (artifacts, tools, etc.)
            self._logger.log_iteration(
                iteration,
                manager_decision,
                delegation_results,
                self._budget,
                validation_results,
            )

            # 6. Aggregate into history
            agg_confidence = self._aggregate_confidence(delegation_results)
            key_findings = self._extract_key_findings(delegation_results)

            self._history.append(
                {
                    "iteration": iteration,
                    "confidence": agg_confidence,
                    "key_findings": key_findings,
                    "worker_count": len(delegation_results),
                    "validation": validation_results,
                }
            )

            # 7. Update rolling summary
            window = self._config.history.full_results_window
            self._logger.update_rolling_summary(
                iteration,
                agg_confidence,
                key_findings,
                self._history,
                window,
            )

            # 8. Update state with results
            for dr in delegation_results:
                wid = dr.get("worker_id", "")
                if wid:
                    state[wid] = dr.get("result", {})

            # 9. Stall detection
            if self._stall:
                stall_status = self._stall.record(agg_confidence, key_findings)
                if stall_status == "stop":
                    logger.warning("Stall detected — stopping loop")
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
            llm = LLMClient(model=self._manager_model)
            agent = self._load_agent(manager_dir, llm=llm)

            # Build enhanced task with context
            enhanced_task = self._build_manager_task(task, state, iteration)
            result = agent.run(enhanced_task, state)
            self._budget.tokens_consumed += llm.total_tokens_used

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

            # If parsing still failed, fall back to inline manager
            if parsed.get(
                "decision"
            ) == "fail" and "missing 'decision' field" in parsed.get("reason", ""):
                logger.warning(
                    "Agent manager returned unparseable output, falling back to inline manager"
                )
                return self._run_inline_manager(task, state, iteration)

            return parsed

        except Exception as exc:
            logger.error("Manager execution failed: %s", exc)
            return {"decision": "fail", "reason": str(exc)}

    def _run_inline_manager(self, task: str, state: dict, iteration: int) -> dict:
        """Run manager with inline prompting (no agent.awp.yaml required)."""
        llm = LLMClient(model=self._manager_model)

        system_prompt = self._build_manager_system_prompt()
        user_message = self._build_manager_task(task, state, iteration)

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ]

        try:
            result = llm.chat_json(messages, temperature=0.2, max_tokens=4096)
            self._budget.tokens_consumed += llm.total_tokens_used
            return self._parse_manager_output(result)
        except Exception as exc:
            self._budget.tokens_consumed += llm.total_tokens_used
            logger.error("Inline manager failed: %s", exc)
            return {"decision": "fail", "reason": str(exc)}

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
```json
{{
  "decision": "delegate",
  "reasoning": "Why you're delegating this way",
  "delegations": [
    {{
      "worker_id": "unique_snake_case_name",
      "instructions": "Detailed instructions for the worker",
      "skills": ["Markdown domain knowledge injected into the worker's prompt"],
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

## Worker Policy (Enforced Limits)
- Sandbox: {enforced.sandbox.type}, max {enforced.sandbox.max_memory_mb}MB RAM, {enforced.sandbox.max_cpu_seconds}s CPU
- Max tools per worker: {enforced.codemode.max_tools_per_worker}
- Forbidden tools: {", ".join(enforced.forbidden_tools)}
{self._build_namespace_capabilities_section()}
## Rules
- Give each worker a unique, descriptive worker_id (snake_case)
- Workers can only use tools from their tools_allowed list
- Include relevant domain knowledge in the skills array as Markdown strings
- Be specific in instructions — the worker only sees what you provide
- Set `temperature` per worker to control creativity (0.0 = deterministic, 1.0 = creative). Choose based on the task: use low temperature for analysis/validation, higher for brainstorming/writing. If omitted, defaults to 0.2.
- Respond ONLY with the JSON object, no other text
"""

    def _build_manager_task(self, task: str, state: dict, iteration: int) -> str:
        """Build the user message for the manager with context."""
        parts = [f"## Original Task\n{task}\n"]

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
            for v in self._history[-1]["validation"]:
                parts.append(
                    f"- Worker {v.get('worker_id', '?')}: {v.get('feedback', 'ok')}\n"
                )

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

        return "\n".join(parts)

    def _parse_manager_output(self, output: Any) -> dict:
        """Parse and normalize manager output."""
        if isinstance(output, str):
            output = self._parse_json_response(output)
        if not isinstance(output, dict):
            return {
                "decision": "fail",
                "reason": f"Invalid manager output type: {type(output)}",
            }

        # Normalize "workers" key to "delegations" (both formats accepted)
        if "workers" in output and "delegations" not in output:
            workers = output.pop("workers")
            # Normalize worker_id: accept "id" or "worker_id"
            if isinstance(workers, list):
                for w in workers:
                    if isinstance(w, dict) and "id" in w and "worker_id" not in w:
                        w["worker_id"] = w.pop("id")
            output["delegations"] = workers

        # Normalize decision field
        if "decision" not in output:
            if "delegations" in output:
                output["decision"] = "delegate"
            elif "final_result" in output or "report_md" in output:
                output["decision"] = "complete"
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

            if any(w in raw for w in _DELEGATE_WORDS):
                output["decision"] = "delegate"
            elif any(w in raw for w in _COMPLETE_WORDS):
                output["decision"] = "complete"
            elif any(w in raw for w in _FAIL_WORDS):
                output["decision"] = "fail"
            # else: keep as-is, will be caught downstream

        return output

    # -- Worker execution -------------------------------------------------

    def _execute_delegations(
        self, envelopes: list[dict], task: str, state: dict,
        iteration: int = 0,
    ) -> list[dict]:
        """Execute all delegations in parallel (fan-out)."""
        results: list[dict] = []

        def run_worker(envelope: dict) -> dict:
            worker_id = envelope.get("worker_id", f"worker_{uuid.uuid4().hex[:6]}")
            self._budget.workers_spawned += 1

            logger.info("  Spawning worker: %s", worker_id)

            # Write envelope to disk BEFORE worker starts (for file watchers)
            self._logger.log_worker_envelope(iteration, worker_id, envelope)

            try:
                result = self._run_ephemeral_worker(worker_id, envelope, task, state)
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

        # Fan-out with ThreadPoolExecutor
        max_workers = min(len(envelopes), 4)
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {pool.submit(run_worker, env): env for env in envelopes}
            for future in as_completed(futures):
                results.append(future.result())

        return results

    def _run_ephemeral_worker(
        self, worker_id: str, envelope: dict, task: str, state: dict
    ) -> dict:
        """Run an ephemeral worker configured entirely by the delegation envelope."""
        instructions = envelope.get("instructions", "")
        skills = envelope.get("skills", [])
        tools_allowed = envelope.get("tools_allowed", [])
        output_contract = envelope.get("output_contract", {})
        codemode = envelope.get("codemode", {})

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

        # Build system prompt from envelope
        system_parts = [
            f"You are a Worker Agent (ID: {worker_id}) executing a delegated task.\n",
            f"## Instructions\n{instructions}\n",
        ]

        if skills:
            system_parts.append("## Domain Knowledge\n")
            for i, skill in enumerate(skills):
                if isinstance(skill, str):
                    system_parts.append(f"### Skill {i + 1}\n{skill}\n")

        # If codemode is enabled, tell the worker about file I/O capabilities
        if isinstance(codemode, dict) and codemode.get("enabled", False):
            workspace_path = str(self._dir / "workspace")
            output_path = str(self._dir / "output")

            # Build input registry with schema previews for data files
            workspace_path_obj = self._dir / "workspace"
            input_registry_block = build_input_registry(workspace_path_obj)

            system_parts.append(f"""{input_registry_block}
## File I/O

In `code.execute` calls, these paths are available as pre-defined variables:
- `_workspace_dir` = `"{workspace_path}"` (workspace directory with input files)
- `_output_dir` = `"{output_path}"` (save final deliverables here)

**IMPORTANT:** Always use `_workspace_dir + "/inputs/FILENAME"` to read input files.
Do NOT use relative paths like `open("data.csv")` — they will fail.

Use string concatenation for paths: `_output_dir + "/chart.png"`

**Subdirectories:** If you save files to a subdirectory (e.g. `_output_dir + "/plots/chart.png"`),
call `_ensure_dir(path)` first to create parent directories automatically:
```python
path = _output_dir + "/plots/chart.png"
_ensure_dir(path)  # creates _output_dir/plots/ if needed
plt.savefig(path, dpi=150, bbox_inches="tight")
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
                    result = _original_call(name, arguments)
                    _tool_call_log.append(
                        {
                            "tool": name,
                            "arguments": arguments,
                            "result": result,
                        }
                    )
                    self._budget.tool_calls_used += 1
                    return result

                final_msg = llm.chat_with_tools(
                    messages,
                    tools=tool_defs,
                    tool_executor=_tracking_call,
                    max_rounds=5,
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
                    self._process_tool_creation(result, worker_id, codemode)

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

For each tool you create, include it in the `tools_created` array in your response.
Each tool object must have:
- `name`: Fully qualified name in the "{namespace}" namespace (e.g., "{namespace}.calculate_score")
- `description`: What the tool does
- `parameters`: JSON Schema for the tool's input parameters
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
        self, result: dict, worker_id: str, codemode: dict
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
                    if reg_result.get("ok"):
                        logger.info(
                            "  Worker %s created tool: %s — OK", worker_id, name
                        )
                        full_record["registered"] = True
                    else:
                        error = reg_result.get("error", "unknown")
                        logger.warning(
                            "  Tool creation FAILED for %s: %s\n"
                            "    Status: %s\n"
                            "    Full result: %s",
                            name,
                            error,
                            reg_result.get("status", "?"),
                            json.dumps(reg_result, indent=2, default=str),
                        )
                        full_record["registered"] = False
                        full_record["error"] = error
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

        # Must be a dict
        if not isinstance(result, dict):
            return {"passed": False, "errors": ["Result is not a dict"]}

        # Must have confidence
        if "confidence" not in result:
            errors.append("Missing 'confidence' field — worker did not self-assess")

        # Confidence must be valid
        conf = result.get("confidence", 0)
        if not isinstance(conf, (int, float)):
            errors.append(f"Confidence is not a number: {type(conf)}")
        elif not (0.0 <= conf <= 1.0):
            errors.append(f"Confidence out of range: {conf}")

        # Flag derived/fallback confidence so manager knows
        source = result.get("_confidence_source")
        if source:
            errors.append(
                f"Confidence was not provided by worker (source: {source})"
            )

        # Must not be only an error
        if "error" in result and len(result) <= 2:  # just error + confidence
            errors.append("Result contains only an error")

        return {"passed": len(errors) == 0, "errors": errors}

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
        1. Direct JSON parse
        2. Strip markdown code fences and parse
        3. Extract the first {...} block from freetext via brace-matching
        """
        if not text or not isinstance(text, str):
            return {"result": str(text), "_confidence_source": "parse_failure"}
        cleaned = text.strip()

        # Strategy 1: direct parse
        try:
            parsed = json.loads(cleaned)
            if isinstance(parsed, dict):
                return parsed
        except (json.JSONDecodeError, ValueError):
            pass

        # Strategy 2: strip markdown code fences
        if "```" in cleaned:
            lines = cleaned.split("\n")
            lines = [line for line in lines if not line.strip().startswith("```")]
            fenced = "\n".join(lines).strip()
            try:
                parsed = json.loads(fenced)
                if isinstance(parsed, dict):
                    return parsed
            except (json.JSONDecodeError, ValueError):
                pass

        # Strategy 3: find the first top-level {...} block via brace matching
        start = cleaned.find("{")
        if start != -1:
            depth = 0
            in_string = False
            escape = False
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
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        candidate = cleaned[start : i + 1]
                        try:
                            parsed = json.loads(candidate)
                            if isinstance(parsed, dict):
                                return parsed
                        except (json.JSONDecodeError, ValueError):
                            pass
                        break

        return {"result": text, "_confidence_source": "parse_failure"}

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
                    if isinstance(val, str):
                        if len(val) > 150:
                            val = val[:150] + "..."
                        findings.append(f"{wid}: {val}")
                    elif isinstance(val, list):
                        findings.append(f"{wid}: {len(val)} items")
                    break
            else:
                conf = result.get("confidence", "?")
                findings.append(f"{wid}: confidence={conf}")
        return "; ".join(findings)

    def _build_partial_result(self, reason: str) -> dict:
        """Build a partial result when the loop terminates early."""
        last_confidence = (
            self._history[-1].get("confidence", 0.0) if self._history else 0.0
        )
        return {
            "partial": True,
            "termination_reason": reason,
            "iterations_completed": self._budget.loops_used,
            "confidence": last_confidence,
            "history_summary": [
                {"iteration": h["iteration"], "confidence": h.get("confidence", 0)}
                for h in self._history
            ],
        }
