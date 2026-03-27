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
from typing import Any, Dict, List, Optional

from ..models.orchestration import DelegationLoopConfig, DelegationBudget
from .agent import StandaloneAgent
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
        return max(0.0, min(fractions))

    def can_continue(self) -> tuple[bool, str]:
        """Check if the loop can continue within budget."""
        if self.loops_used >= self.max_loops:
            return False, "max_loops reached"
        if self.workers_spawned >= self.max_total_workers:
            return False, "max_total_workers reached"
        if self.wall_time_elapsed >= self.max_wall_time:
            return False, "max_wall_time exceeded"
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
    """Detects when the delegation loop makes no meaningful progress."""

    def __init__(self, window: int = 3, min_delta: float = 0.05) -> None:
        self.window = window
        self.min_delta = min_delta
        self._history: list[float] = []
        self._warnings = 0

    def record(self, confidence: float) -> str:
        """Record a confidence value. Returns 'ok', 'warn', or 'stop'."""
        self._history.append(confidence)
        if len(self._history) < self.window:
            return "ok"

        recent = self._history[-self.window:]
        delta = recent[-1] - recent[0]

        if abs(delta) < self.min_delta:
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
            path.write_text(json.dumps(data, indent=2, default=str, ensure_ascii=False),
                            encoding="utf-8")

    def write_md(self, path: Path, content: str) -> None:
        if self.fmt in ("dual", "md"):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")

    def log_run_start(self, task: str, run_id: str, config: DelegationLoopConfig,
                      manager_model: str, worker_model: str) -> None:
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

    def log_iteration(self, iteration: int, manager_decision: dict,
                      delegations: list[dict], budget: BudgetSnapshot,
                      validation_results: list[dict]) -> None:
        iter_dir = self.run_dir / "iterations" / f"{iteration:03d}"
        iter_dir.mkdir(parents=True, exist_ok=True)

        # Manager decision
        self.write_json(iter_dir / "manager_decision.json", manager_decision)

        # Delegations
        for i, deleg in enumerate(delegations):
            worker_dir = iter_dir / "delegations" / (deleg.get("worker_id", f"worker_{i}"))
            worker_dir.mkdir(parents=True, exist_ok=True)
            self.write_json(worker_dir / "envelope.json", deleg.get("envelope", {}))
            self.write_json(worker_dir / "result.json", deleg.get("result", {}))

            # Save generated skills (per-worker and central artifacts)
            for j, skill in enumerate(deleg.get("envelope", {}).get("skills", [])):
                if isinstance(skill, str) and len(skill) > 50:
                    wid = deleg.get("worker_id", f"worker_{i}")
                    # Per-worker copy
                    skill_file = worker_dir / "generated_skills" / f"skill_{j}.md"
                    self.write_md(skill_file, skill)
                    # Central artifacts copy
                    artifact_file = self.run_dir / "artifacts" / "skills" / f"{wid}_skill_{j}.md"
                    self.write_md(artifact_file, skill)

            # Save generated tools (if worker created any via codemode)
            worker_result = deleg.get("result", {})
            wid = deleg.get("worker_id", f"worker_{i}")
            tools_created = worker_result.get("tools_created", [])
            if isinstance(tools_created, list):
                for t, tool_info in enumerate(tools_created):
                    if isinstance(tool_info, dict):
                        tool_name = tool_info.get("name", f"tool_{t}")
                        safe_name = tool_name.replace(".", "_")
                        # Per-worker copy
                        tool_file = worker_dir / "generated_tools" / f"{safe_name}.json"
                        self.write_json(tool_file, tool_info)
                        # Central artifacts copy
                        artifact_file = self.run_dir / "artifacts" / "tools" / f"{safe_name}.json"
                        self.write_json(artifact_file, tool_info)
            # Also check for tool_names (alternative format)
            tool_names = worker_result.get("tool_names", [])
            if isinstance(tool_names, list) and tool_names:
                tool_manifest = {"worker_id": wid, "tools": tool_names}
                artifact_file = self.run_dir / "artifacts" / "tools" / f"{wid}_tools.json"
                self.write_json(artifact_file, tool_manifest)

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

        md_lines.append(f"\n## Budget\n- Remaining: {budget.budget_fraction_remaining*100:.0f}%\n")
        self.write_md(iter_dir / "ITERATION_SUMMARY.md", "\n".join(md_lines))

    def log_completion(self, run_id: str, final_result: dict, budget: BudgetSnapshot,
                       total_iterations: int, status: str) -> None:
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

    def update_rolling_summary(self, iteration: int, confidence: float,
                               key_findings: str, full_history: list[dict],
                               window: int = 3) -> None:
        """Write ROLLING_SUMMARY.md with recent details and older summaries."""
        lines = [
            f"# Rolling Summary\n",
            f"## Progress\n",
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
            lines.append(f"## Older Iterations (Summary)\n")
            for h in older:
                lines.append(
                    f"- Iter {h['iteration']}: confidence={h.get('confidence', '?')}\n"
                )

        self.write_md(self.run_dir / "history" / "ROLLING_SUMMARY.md", "".join(lines))
        self.write_json(self.run_dir / "history" / "rolling_summary.json", {
            "iteration": iteration,
            "confidence": confidence,
            "history": full_history,
        })


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
        self._run_id = run_id or datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M-%S") + "_" + uuid.uuid4().hex[:8]
        self._depth = depth

        # Budget: use parent's remaining budget or create fresh
        if parent_budget:
            self._budget = parent_budget
        else:
            self._budget = BudgetSnapshot(config.budget)

        # Stall detection
        stall_cfg = config.termination
        self._stall = StallDetector(
            window=stall_cfg.window if stall_cfg else 3,
            min_delta=stall_cfg.min_confidence_delta if stall_cfg else 0.05,
        ) if (stall_cfg and stall_cfg.enabled) else None

        # Logger
        run_dir = self._dir / "workspace" / "runs" / self._run_id
        self._logger = RunLogger(run_dir, fmt=config.logging.format)

        # History
        self._history: list[dict[str, Any]] = []

    def _load_agent(self, agent_dir: Path, llm: Optional[LLMClient] = None) -> StandaloneAgent:
        """Load the Agent class from ``agent.py``, falling back to
        :class:`StandaloneAgent`.  See :meth:`WorkflowRunner._load_agent`."""
        agent_py = agent_dir / "agent.py"
        if agent_py.exists():
            try:
                spec = importlib.util.spec_from_file_location(
                    f"awp_agent_{agent_dir.name}", str(agent_py),
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
                    agent_py, exc,
                )
        return StandaloneAgent(
            agent_dir, self._dir,
            llm=llm,
            tool_registry=self._tools,
        )

    def run(self, task: str, state: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Execute the delegation loop."""
        state = dict(state or {})
        state["task"] = task

        logger.info(
            "DelegationLoop [%s] depth=%d starting: %s",
            self._run_id, self._depth, task[:80],
        )

        self._logger.log_run_start(
            task, self._run_id, self._config,
            self._manager_model, self._worker_model,
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
            self._run_id, final_result, self._budget,
            self._budget.loops_used, status,
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

            # 2. Handle decision
            if decision_type == "complete":
                result = manager_decision.get("final_result", {})
                # Support flat complete format (report_md, chart_paths, json_data at top level)
                if not result:
                    result = {}
                    for key in ("report_md", "chart_paths", "json_data", "plan", "reasoning"):
                        if key in manager_decision:
                            result[key] = manager_decision[key]
                if "confidence" not in result:
                    result["confidence"] = manager_decision.get("confidence", 0.8)
                self._logger.log_iteration(
                    iteration, manager_decision, [], self._budget, [],
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
                return {"error": f"Unknown decision: {decision_type}", "confidence": 0.0}, "fail"

            # 3. Execute delegations (fan-out)
            envelopes = manager_decision.get("delegations", [])
            if not envelopes:
                logger.warning("Manager returned DELEGATE with no delegations")
                continue

            delegation_results = self._execute_delegations(envelopes, task, state)

            # 4. Validate results (2-tier)
            validation_results = self._validate_results(delegation_results, task)

            # 5. Log iteration
            self._logger.log_iteration(
                iteration, manager_decision, delegation_results,
                self._budget, validation_results,
            )

            # 6. Aggregate into history
            agg_confidence = self._aggregate_confidence(delegation_results)
            key_findings = self._extract_key_findings(delegation_results)

            self._history.append({
                "iteration": iteration,
                "confidence": agg_confidence,
                "key_findings": key_findings,
                "worker_count": len(delegation_results),
                "validation": validation_results,
            })

            # 7. Update rolling summary
            window = self._config.history.full_results_window
            self._logger.update_rolling_summary(
                iteration, agg_confidence, key_findings, self._history, window,
            )

            # 8. Update state with results
            for dr in delegation_results:
                wid = dr.get("worker_id", "")
                if wid:
                    state[wid] = dr.get("result", {})

            # 9. Stall detection
            if self._stall:
                stall_status = self._stall.record(agg_confidence)
                if stall_status == "stop":
                    logger.warning("Stall detected — stopping loop")
                    return self._build_partial_result("stall_detected"), "stall_detected"
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

            # Extract the manager's output
            manager_output = result.get(agent.name, {})

            # If the agent returned a wrapped non-JSON result, try to extract
            # the actual JSON from the "result" field (LLM may have returned
            # JSON wrapped in markdown or extra text)
            if isinstance(manager_output, dict) and "result" in manager_output and "decision" not in manager_output:
                raw_text = manager_output.get("result", "")
                if isinstance(raw_text, str) and "{" in raw_text:
                    extracted = self._parse_json_response(raw_text)
                    if "decision" in extracted or "delegations" in extracted:
                        manager_output = extracted

            parsed = self._parse_manager_output(manager_output)

            # If parsing still failed, fall back to inline manager
            if parsed.get("decision") == "fail" and "missing 'decision' field" in parsed.get("reason", ""):
                logger.warning("Agent manager returned unparseable output, falling back to inline manager")
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
            return self._parse_manager_output(result)
        except Exception as exc:
            logger.error("Inline manager failed: %s", exc)
            return {"decision": "fail", "reason": str(exc)}

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
      }}
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
- Forbidden tools: {', '.join(enforced.forbidden_tools)}

## Rules
- Give each worker a unique, descriptive worker_id (snake_case)
- Workers can only use tools from their tools_allowed list
- Include relevant domain knowledge in the skills array as Markdown strings
- Be specific in instructions — the worker only sees what you provide
- Respond ONLY with the JSON object, no other text
"""

    def _build_manager_task(self, task: str, state: dict, iteration: int) -> str:
        """Build the user message for the manager with context."""
        parts = [f"## Original Task\n{task}\n"]

        # Budget status
        parts.append(f"## Budget Status\n```json\n{json.dumps(self._budget.to_dict(), indent=2)}\n```\n")

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
                    parts.append(f"- Iter {h['iteration']}: confidence={h.get('confidence', '?')}\n")

        # Validation feedback from last iteration
        if self._history and self._history[-1].get("validation"):
            parts.append("## Validation Feedback\n")
            for v in self._history[-1]["validation"]:
                parts.append(f"- Worker {v.get('worker_id', '?')}: {v.get('feedback', 'ok')}\n")

        # State from previous workers
        worker_states = {k: v for k, v in state.items() if k != "task" and not k.startswith("_")}
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
            return {"decision": "fail", "reason": f"Invalid manager output type: {type(output)}"}

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
            _COMPLETE_WORDS = {"complete", "done", "finalize", "finish", "final", "synthesize", "conclude", "submit"}
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

    def _execute_delegations(self, envelopes: list[dict], task: str,
                             state: dict) -> list[dict]:
        """Execute all delegations in parallel (fan-out)."""
        results: list[dict] = []

        def run_worker(envelope: dict) -> dict:
            worker_id = envelope.get("worker_id", f"worker_{uuid.uuid4().hex[:6]}")
            self._budget.workers_spawned += 1

            logger.info("  Spawning worker: %s", worker_id)

            try:
                result = self._run_ephemeral_worker(worker_id, envelope, task, state)
                return {
                    "worker_id": worker_id,
                    "envelope": envelope,
                    "result": result,
                    "status": "ok",
                }
            except Exception as exc:
                logger.error("  Worker %s failed: %s", worker_id, exc)
                return {
                    "worker_id": worker_id,
                    "envelope": envelope,
                    "result": {"error": str(exc), "confidence": 0.0},
                    "status": "error",
                }

        # Fan-out with ThreadPoolExecutor
        max_workers = min(len(envelopes), 4)
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {pool.submit(run_worker, env): env for env in envelopes}
            for future in as_completed(futures):
                results.append(future.result())

        return results

    def _run_ephemeral_worker(self, worker_id: str, envelope: dict,
                              task: str, state: dict) -> dict:
        """Run an ephemeral worker configured entirely by the delegation envelope."""
        instructions = envelope.get("instructions", "")
        skills = envelope.get("skills", [])
        tools_allowed = envelope.get("tools_allowed", [])
        output_contract = envelope.get("output_contract", {})
        codemode = envelope.get("codemode", {})

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
                    system_parts.append(f"### Skill {i+1}\n{skill}\n")

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

            # Always ensure confidence is mentioned
            if "confidence" not in output_contract:
                system_parts.append("- `confidence` (float 0.0-1.0): How confident you are\n")
            if tool_creation:
                system_parts.append('- `tools_created` (array): List of tool objects you created\n')
            system_parts.append("\nRespond ONLY with the JSON object.\n")

        system_prompt = "\n".join(system_parts)

        # Build user message with context
        user_parts = [f"## Task\n{task}\n"]

        # Include relevant state
        for k, v in state.items():
            if k == "task" or k.startswith("_"):
                continue
            if isinstance(v, dict):
                summary = json.dumps(v, indent=2, default=str)
                if len(summary) > 300:
                    summary = summary[:300] + "..."
                user_parts.append(f"### Context: {k}\n```json\n{summary}\n```\n")

        user_message = "\n".join(user_parts)

        # Execute via LLM
        llm = LLMClient(model=self._worker_model)
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ]

        # Enforce forbidden_tools from worker_policy
        enforced = getattr(self._config.worker_policy, "enforced", None) if self._config.worker_policy else None
        forbidden = set(getattr(enforced, "forbidden_tools", []) or []) if enforced else set()
        if forbidden and tools_allowed:
            original = list(tools_allowed)
            tools_allowed = [t for t in tools_allowed if t not in forbidden]
            removed = set(original) - set(tools_allowed)
            if removed:
                logger.warning(
                    "  Worker %s: removed forbidden tools: %s",
                    worker_id, ", ".join(sorted(removed)),
                )

        # Determine if tools are needed
        if tools_allowed and self._tools:
            tool_defs = self._tools.get_definitions(tools_allowed if tools_allowed else None)
            if tool_defs:
                final_msg = llm.chat_with_tools(
                    messages, tools=tool_defs,
                    tool_executor=self._tools.call,
                    max_rounds=5,
                    temperature=0.2, max_tokens=4096,
                )
                content = ""
                if isinstance(final_msg, dict):
                    content = final_msg.get("content", "") or ""
                elif isinstance(final_msg, str):
                    content = final_msg
                result = self._parse_json_response(content)
                if "confidence" not in result:
                    result["confidence"] = 0.5
                # Process tool creation from result
                if tool_creation:
                    self._process_tool_creation(result, worker_id, codemode)
                return result

        # Simple call (no tools)
        try:
            result = llm.chat_json(messages, temperature=0.2, max_tokens=4096)
            if not isinstance(result, dict):
                result = {"result": str(result), "confidence": 0.3}
        except Exception:
            text = llm.chat_text(messages, temperature=0.2, max_tokens=4096)
            result = self._parse_json_response(text)

        if "confidence" not in result:
            result["confidence"] = 0.5

        # Process tool creation from result
        if tool_creation:
            self._process_tool_creation(result, worker_id, codemode)

        return result

    def _build_tool_creation_prompt(self, namespace: str) -> str:
        """Build the prompt section that instructs the worker to create tools."""
        return f"""
## Tool Creation Mode

You are in TOOL CREATION mode. Your job is to generate reusable Python tools.

For each tool you create, include it in the `tools_created` array in your response.
Each tool object must have:
- `name`: Fully qualified name in the "{namespace}" namespace (e.g., "{namespace}.calculate_score")
- `description`: What the tool does
- `parameters`: JSON Schema for the tool's input parameters
- `code`: Python code containing a `def handler(*, ...)` function that returns a dict with `{{"ok": True, "status": 200, "data": {{}}, "error": None}}`

Example tool:
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

Rules:
- Tools MUST have a `def handler(*, ...)` function (keyword-only arguments)
- Tools MUST return the standard AWP format: `{{"ok": bool, "status": int, "data": {{}}, "error": str|None}}`
- No imports of os, subprocess, sys, socket, or network modules
- Keep tool code concise and focused
"""

    def _process_tool_creation(self, result: dict, worker_id: str,
                               codemode: dict) -> None:
        """Extract tools from worker result and register them via DynamicToolFactory."""
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

            if not name or not code:
                logger.warning("Skipping tool with missing name or code: %s", tool_spec)
                continue

            # Try to register via DynamicToolFactory if available
            if self._tools and hasattr(self._tools, '_dynamic_tool_factory'):
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
                    )
                    if reg_result.get("ok"):
                        logger.info("  Worker %s created tool: %s", worker_id, name)
                        registered.append({"name": name, "registered": True})
                    else:
                        logger.warning("  Tool creation failed for %s: %s",
                                       name, reg_result.get("error"))
                        registered.append({"name": name, "registered": False,
                                           "error": reg_result.get("error")})
                    continue

            # Fallback: just log that we received the tool spec
            logger.info("  Worker %s defined tool: %s (not registered — no factory)",
                        worker_id, name)
            registered.append({"name": name, "registered": False, "reason": "no_factory"})

        # Update result with registration status
        result["tools_registered"] = registered

    # -- Validation -------------------------------------------------------

    def _validate_results(self, delegation_results: list[dict],
                          task: str) -> list[dict]:
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
                v["feedback"] = f"Deterministic validation failed: {det.get('errors', [])}"
                validation_results.append(v)
                continue

            # Tier 2: LLM (if enabled and conditions met)
            val_cfg = self._config.validation
            confidence = result.get("confidence", 0.0)
            if (val_cfg.llm.enabled
                and confidence < val_cfg.llm.skip_when_confidence_above
                and self._budget.budget_fraction_remaining > val_cfg.llm.skip_when_budget_remaining_below):
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
            errors.append("Missing 'confidence' field")

        # Confidence must be valid
        conf = result.get("confidence", 0)
        if not isinstance(conf, (int, float)):
            errors.append(f"Confidence is not a number: {type(conf)}")
        elif not (0.0 <= conf <= 1.0):
            errors.append(f"Confidence out of range: {conf}")

        # Must not be only an error
        if "error" in result and len(result) <= 2:  # just error + confidence
            errors.append("Result contains only an error")

        return {"passed": len(errors) == 0, "errors": errors}

    def _validate_llm(self, result: dict, task: str, worker_id: str) -> dict:
        """Tier 2: LLM-based semantic validation."""
        try:
            llm = LLMClient(model=self._worker_model)

            messages = [
                {"role": "system", "content": (
                    "You are a Validation Agent. Evaluate whether a worker's result "
                    "meaningfully addresses the original task. Respond with JSON:\n"
                    '{"valid": true/false, "adjusted_confidence": 0.0-1.0, '
                    '"feedback": "...", "suggestion": "..."}'
                )},
                {"role": "user", "content": (
                    f"## Original Task\n{task}\n\n"
                    f"## Worker ID: {worker_id}\n"
                    f"## Worker Result\n```json\n"
                    f"{json.dumps(result, indent=2, default=str)}\n```\n\n"
                    f"Does this result meaningfully address the task? "
                    f"Is the confidence realistic?"
                )},
            ]

            v_result = llm.chat_json(messages, temperature=0.1, max_tokens=1024)
            return v_result

        except Exception as exc:
            logger.warning("LLM validation failed: %s", exc)
            return {"valid": True, "feedback": f"LLM validation error: {exc}"}

    # -- Helpers ----------------------------------------------------------

    @staticmethod
    def _parse_json_response(text: str) -> dict:
        """Robustly parse an LLM response as JSON."""
        if not text or not isinstance(text, str):
            return {"result": str(text), "confidence": 0.3}
        cleaned = text.strip()
        # Strip markdown code fences
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            cleaned = "\n".join(lines).strip()
        try:
            parsed = json.loads(cleaned)
            if isinstance(parsed, dict):
                return parsed
            return {"result": parsed, "confidence": 0.3}
        except (json.JSONDecodeError, ValueError):
            return {"result": text, "confidence": 0.3}

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
            for key in ("findings", "result", "summary", "analysis", "answer", "output"):
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
        last_confidence = self._history[-1].get("confidence", 0.0) if self._history else 0.0
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
