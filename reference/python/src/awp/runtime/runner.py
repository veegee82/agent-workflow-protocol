"""AWP Workflow Runner -- Standalone DAG executor with full AWP support.

Reads ``workflow.awp.yaml``, topologically sorts the agent graph,
and executes agents in order. Supports:
- Sequential and parallel execution
- DAG-based topological ordering
- State sharing between agents
- Memory auto-write after each agent
- Tool registry shared across agents
- Error handling (continue / skip / abort)
- Observability (tracing, metrics, audit)
- Security (circuit breaker, rate limiting, access control)
- Message bus for inter-agent communication
- Code execution sandbox
- State persistence
- Conditional execution (when expressions)
- Retry with backoff

Usage::

    from awp.runtime import WorkflowRunner

    runner = WorkflowRunner("path/to/my-workflow")
    result = runner.run("Analyze the latest quarterly report")
"""

from __future__ import annotations

import importlib.util
import logging
import subprocess
import sys
import threading
import time
import uuid
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, as_completed, wait
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from awp.models.capabilities import SandboxConfig
from awp.models.orchestration import (
    AWPOrchestrationConfig,
    ConditionalDependency,
    RunBudgetLimits,
)
from awp.parser import parse_manifest

from .agent import StandaloneAgent
from .dynamic_tool_factory import DynamicToolFactory
from .evaluation import EvaluationEngine
from .executor_factory import create_executor
from .expressions import safe_eval
from .llm import LLMClient
from .message_bus import MessageBus
from .observability import ObservabilityContext
from .secrets import load_secrets
from .security import SecurityContext
from .state_persistence import StatePersistence
from .tools import ToolRegistry

logger = logging.getLogger(__name__)


class RunBudgetTracker:
    """Tracks consumed resources against global run budget limits.

    Only checks limits that are listed in ``enabled_limits``.
    """

    def __init__(self, budget: RunBudgetLimits) -> None:
        self._budget = budget
        self._enabled = set(budget.enabled_limits)
        self._lock = threading.Lock()
        self.agent_runs = 0
        self.tool_calls = 0
        self.tokens_used = 0
        self.cost_usd = 0.0
        self._start = time.monotonic()

    @property
    def wall_time_elapsed(self) -> float:
        return time.monotonic() - self._start

    def record_agent_run(self) -> None:
        with self._lock:
            self.agent_runs += 1

    def record_tool_calls(self, count: int = 1) -> None:
        with self._lock:
            self.tool_calls += count

    def record_tokens(self, count: int) -> None:
        with self._lock:
            self.tokens_used += count

    def record_cost(self, usd: float) -> None:
        with self._lock:
            self.cost_usd += usd

    def check(self) -> tuple[bool, str]:
        """Return (can_continue, reason).  Only checks enabled limits."""
        with self._lock:
            if "max_wall_time" in self._enabled:
                if self.wall_time_elapsed >= self._budget.max_wall_time:
                    return False, f"max_wall_time exceeded ({self._budget.max_wall_time}s)"
            if "max_total_tokens" in self._enabled:
                if self.tokens_used >= self._budget.max_total_tokens:
                    return (
                        False,
                        f"max_total_tokens reached ({self._budget.max_total_tokens})",
                    )
            if "max_tool_calls" in self._enabled:
                if self.tool_calls >= self._budget.max_tool_calls:
                    return False, f"max_tool_calls reached ({self._budget.max_tool_calls})"
            if "max_agent_runs" in self._enabled:
                if self.agent_runs >= self._budget.max_agent_runs:
                    return False, f"max_agent_runs reached ({self._budget.max_agent_runs})"
            if "max_cost_usd" in self._enabled:
                if self.cost_usd >= self._budget.max_cost_usd:
                    return False, f"max_cost_usd reached (${self._budget.max_cost_usd:.2f})"
            return True, "ok"

    def summary(self) -> dict:
        with self._lock:
            return {
                "wall_time_s": round(self.wall_time_elapsed, 1),
                "agent_runs": self.agent_runs,
                "tool_calls": self.tool_calls,
                "tokens_used": self.tokens_used,
                "cost_usd": round(self.cost_usd, 4),
                "enabled_limits": sorted(self._enabled),
            }


class WorkflowRunner:
    """Standalone AWP workflow executor.

    Supports:
    - Sequential and parallel execution modes
    - DAG-based topological ordering
    - State sharing between agents
    - Memory auto-write after each agent
    - Shared tool registry (built-in + custom MCP tools)
    - Basic error handling (continue / skip / abort)
    - Observability (tracing, metrics, audit trail)
    - Security (circuit breaker, rate limiting, access control)
    - Message bus for inter-agent communication
    - Code executor for sandboxed Python execution
    - State persistence (per-agent checkpoints + final state)
    - Conditional execution via ``when`` expressions
    - Retry with exponential backoff

    Args:
        workflow_dir: Path to workflow directory.
        llm: Optional pre-configured LLMClient.
    """

    def __init__(
        self,
        workflow_dir: str | Path,
        llm: Optional[LLMClient] = None,
        manager_model: Optional[str] = None,
        worker_model: Optional[str] = None,
    ) -> None:
        self._dir = Path(workflow_dir)
        self._install_requirements()
        self._manifest = parse_manifest(self._dir / "workflow.awp.yaml")
        self._llm = llm
        self._manager_model = manager_model
        self._worker_model = worker_model
        secrets = load_secrets(self._dir)
        self._tools = ToolRegistry(self._dir, secrets=secrets)

        # Security context
        self._security = SecurityContext.from_config(self._manifest)
        if self._security.access_controller:
            self._tools.set_security_context(self._security)

        # Message bus
        comm = getattr(self._manifest, "communication", None)
        self._bus = MessageBus(config=comm)
        self._tools.set_message_bus(self._bus)

        # Code executor (sandbox-type-aware)
        sandbox_cfg = self._resolve_sandbox_config()
        self._sandbox_type = sandbox_cfg.type
        self._code_executor = create_executor(sandbox_cfg, working_dir=self._dir)
        self._tools.set_code_executor(self._code_executor)

        # Dynamic tool factory (with sandbox-type-aware import policies)
        dynamic_tools_cfg = getattr(self._manifest, "dynamic_tools", None)
        self._dynamic_tool_factory = DynamicToolFactory(
            registry=self._tools,
            code_executor=self._code_executor,
            config=dynamic_tools_cfg,
            workflow_dir=self._dir,
            sandbox_type=self._sandbox_type,
        )
        self._tools.set_dynamic_tool_factory(self._dynamic_tool_factory)

        # State persistence
        state_cfg = getattr(self._manifest, "state", None)
        persistence_cfg = getattr(state_cfg, "persistence", None) if state_cfg else None
        if persistence_cfg and getattr(persistence_cfg, "enabled", False):
            state_path = self._dir / getattr(persistence_cfg, "path", "data/state")
        else:
            state_path = self._dir / "data" / "state"
        self._state_persistence = StatePersistence(state_path, config=persistence_cfg)

    def _resolve_sandbox_config(self) -> SandboxConfig:
        """Resolve sandbox configuration from the workflow manifest.

        Checks for a workflow-level sandbox config first, then falls back
        to scanning agent capabilities, and finally returns defaults.
        """
        # Check workflow-level sandbox config
        sandbox = getattr(self._manifest, "sandbox", None)
        if sandbox is not None:
            if isinstance(sandbox, SandboxConfig):
                return sandbox
            if isinstance(sandbox, dict):
                return SandboxConfig(**sandbox)

        # Check first agent with sandbox config in capabilities
        orch = getattr(self._manifest, "orchestration", None)
        if orch and hasattr(orch, "graph") and orch.graph:
            for node in orch.graph:
                agent_dir = self._dir / "agents" / node.id
                agent_yaml = agent_dir / "agent.awp.yaml"
                if agent_yaml.exists():
                    try:
                        import yaml

                        data = yaml.safe_load(agent_yaml.read_text(encoding="utf-8"))
                        caps = data.get("capabilities", {})
                        sb = caps.get("sandbox")
                        if sb and isinstance(sb, dict):
                            return SandboxConfig(**sb)
                    except Exception:
                        pass

        return SandboxConfig()

    def _install_requirements(self) -> None:
        """Auto-install workflow dependencies from requirements.txt if present."""
        req_file = self._dir / "requirements.txt"
        if not req_file.exists():
            return

        logger.info("Installing workflow dependencies from %s", req_file)
        try:
            subprocess.check_call(
                [sys.executable, "-m", "pip", "install", "-q", "-r", str(req_file)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
            logger.info("Workflow dependencies installed successfully")
        except subprocess.CalledProcessError as exc:
            logger.warning(
                "Failed to install workflow dependencies: %s",
                exc.stderr.decode() if exc.stderr else str(exc),
            )

    def _load_agent(self, agent_dir: Path) -> StandaloneAgent:
        """Load the Agent class from the agent's ``agent.py``, falling back to
        :class:`StandaloneAgent` when the file is missing, does not define an
        ``Agent`` class, or the import fails for any reason.

        This allows generated ``agent.py`` files that inherit from
        ``StandaloneAgent`` to be picked up automatically, including any
        user-provided overrides of ``run()``, ``_build_system_prompt()``, etc.
        """
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
                    agent = agent_cls(
                        agent_dir=agent_dir,
                        workflow_dir=self._dir,
                        llm=self._llm,
                        tool_registry=self._tools,
                    )
                    return agent
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "Could not load Agent class from %s, using StandaloneAgent: %s",
                    agent_py,
                    exc,
                )
        return StandaloneAgent(
            agent_dir,
            self._dir,
            llm=self._llm,
            tool_registry=self._tools,
        )

    @property
    def name(self) -> str:
        return self._manifest.workflow.name

    def get_missing_secrets(self) -> dict[str, list[str]]:
        """Check which tool secrets are missing without logging warnings."""
        missing: dict[str, list[str]] = {}
        for tool_name in self._tools.tool_names:
            declared = self._tools._tool_secrets.get(tool_name, [])
            for key in declared:
                if key not in self._tools._secrets:
                    missing.setdefault(tool_name, []).append(key)
        return missing

    def inject_secrets(self, new_secrets: dict[str, str]) -> None:
        """Inject additional secrets into the tool registry at runtime."""
        self._tools.inject_secrets(new_secrets)

    def run(self, task: str, state: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Execute the workflow."""
        state = dict(state or {})
        state["task"] = task

        # Generate run ID
        run_id = uuid.uuid4().hex[:12]
        self._current_run_id = run_id

        # Isolate output and state under this run ID
        self._tools.set_run_id(run_id)
        self._state_persistence.set_run_id(run_id)

        # Validate tool secrets (warns but does not block)
        self._tools.validate_secrets()

        # Auto-inject fields
        if self._manifest.state and hasattr(self._manifest.state, "auto_inject"):
            for key, value in self._manifest.state.auto_inject.items():
                if isinstance(value, str):
                    value = value.replace("{{RUN_ID}}", run_id)
                    value = value.replace("{{TIMESTAMP}}", datetime.now(timezone.utc).isoformat())
                state.setdefault(key, value)

        orch = self._manifest.orchestration

        # Initialize global run budget tracker
        run_budget_cfg = getattr(orch, "run_budget", None) if orch else None
        self._run_budget: Optional[RunBudgetTracker] = None
        if run_budget_cfg:
            self._run_budget = RunBudgetTracker(run_budget_cfg)
            enabled = run_budget_cfg.enabled_limits
            logger.info("Run budget active — enabled limits: %s", ", ".join(enabled))

        # Dispatch to delegation loop engine if configured
        if orch and getattr(orch, "engine", "dag") == "delegation_loop":
            return self._run_delegation_loop(task, state)

        if not orch or not hasattr(orch, "graph") or not orch.graph:
            # A workflow may declare only deterministic phases (R33) and no
            # graph nodes at all — phase-only workflows are a legitimate use
            # of the DAG engine. Dispatch phases and return; otherwise the
            # run is truly empty.
            if orch and getattr(orch, "phases", None):
                obs = ObservabilityContext.from_config(self._manifest, self._dir, run_id)
                self._run_deterministic_phases(orch, state, obs)
                obs.flush_all()
                return state
            logger.warning("No orchestration graph -- nothing to run")
            return state

        levels = self._topological_levels(orch)

        # Initialize observability
        obs = ObservabilityContext.from_config(self._manifest, self._dir, run_id)

        # Start workflow trace span
        root_span = None
        if obs.tracer:
            root_span = obs.tracer.start_span(
                "workflow.run",
                attributes={
                    "workflow.name": self.name,
                    "run_id": run_id,
                },
            )
        if obs.audit:
            obs.audit.record("workflow.start", details={"task": task, "run_id": run_id})

        # Initialize evaluation engine (no-op if not configured)
        eval_engine: Optional[EvaluationEngine] = None
        obs_cfg = getattr(self._manifest, "observability", None)
        eval_cfg = getattr(obs_cfg, "evaluation", None) if obs_cfg else None
        if eval_cfg and eval_cfg.enabled:
            eval_engine = EvaluationEngine(
                config=eval_cfg,
                workflow_dir=self._dir,
                run_id=run_id,
                llm_client=self._llm,
            )
            logger.info("Evaluation engine active with %d metrics", len(eval_cfg.metrics))

        logger.info(
            "Running workflow '%s' [run_id=%s] with %d agents in %d levels",
            self.name,
            run_id,
            sum(len(lvl) for lvl in levels),
            len(levels),
        )

        workflow_start = time.monotonic()

        exec_cfg = getattr(orch, "execution", None)
        scheduler_mode = getattr(exec_cfg, "scheduler", "levels") if exec_cfg else "levels"
        if scheduler_mode == "ready_queue":
            return self._execute_ready_queue(
                orch,
                task,
                state,
                levels,
                obs,
                root_span,
                eval_engine,
                workflow_start,
            )

        for level_idx, level in enumerate(levels):
            # Budget check once per level
            if self._run_budget:
                can_go, reason = self._run_budget.check()
                if not can_go:
                    logger.warning("  Run budget limit hit: %s — stopping workflow", reason)
                    if obs.audit:
                        obs.audit.record(
                            "workflow.budget_exceeded",
                            details={
                                "reason": reason,
                                "budget_summary": self._run_budget.summary(),
                            },
                        )
                    state["_run_budget"] = self._run_budget.summary()
                    state["_run_budget"]["exceeded"] = reason
                    return self._finalize_run(state, obs, root_span, workflow_start, levels)

            # Filter eligible agents (enabled, when-condition, security)
            eligible: list[str] = []
            for agent_id in level:
                node = self._get_node(orch, agent_id)
                if node and not node.enabled:
                    logger.info("  Skipping disabled agent: %s", agent_id)
                    continue
                if not self._evaluate_when(node, state):
                    logger.info("  Skipping agent %s: when condition not met", agent_id)
                    if obs.audit:
                        obs.audit.record(
                            "agent.skipped",
                            agent_id,
                            details={"reason": "when_condition"},
                        )
                    continue
                if self._security.rate_limiter:
                    if not self._security.rate_limiter.check(agent_id):
                        logger.warning("  Rate limited: %s", agent_id)
                        if obs.audit:
                            obs.audit.record("agent.rate_limited", agent_id)
                        state[agent_id] = {"error": "Rate limited", "confidence": 0.0}
                        continue
                if self._security.circuit_breaker:
                    if not self._security.circuit_breaker.check():
                        logger.warning("  Circuit breaker open, skipping: %s", agent_id)
                        if obs.audit:
                            obs.audit.record("agent.circuit_breaker", agent_id)
                        state[agent_id] = {
                            "error": "Circuit breaker open",
                            "confidence": 0.0,
                        }
                        continue
                eligible.append(agent_id)

            if not eligible:
                continue

            level_str = ", ".join(eligible)
            parallel = " (parallel)" if len(eligible) > 1 else ""
            logger.info("Level %d: [%s]%s", level_idx, level_str, parallel)

            if len(eligible) == 1:
                # Single agent — sequential fast path (no thread overhead)
                agent_id = eligible[0]
                self._tools._current_agent_id = agent_id
                agent_dir = self._dir / "agents" / agent_id
                node = self._get_node(orch, agent_id)
                result = self._execute_node(
                    agent_id,
                    agent_dir,
                    task,
                    state,
                    node,
                    obs,
                    root_span_id=root_span,
                )
                state.update(result)
                if eval_engine:
                    step_eval = eval_engine.evaluate_step(
                        hook="worker_result",
                        result=result,
                        state=state,
                        budget=self._run_budget,
                        agent_id=agent_id,
                    )
                    if step_eval:
                        logger.info(
                            "  Eval [%s]: score=%.2f action=%s",
                            agent_id,
                            step_eval.score,
                            step_eval.action,
                        )
                if self._run_budget:
                    self._run_budget.record_agent_run()
                if self._security.rate_limiter:
                    self._security.rate_limiter.record(agent_id)
                try:
                    self._state_persistence.save_checkpoint(agent_id, state)
                except Exception as exc:
                    logger.warning("Failed to save checkpoint for %s: %s", agent_id, exc)
            else:
                # Multiple agents — parallel execution via ThreadPoolExecutor
                level_start_state = dict(state)

                def _run_agent_thread(aid: str) -> tuple[str, dict]:
                    self._tools._current_agent_id = aid
                    adir = self._dir / "agents" / aid
                    anode = self._get_node(orch, aid)
                    return aid, self._execute_node(
                        aid,
                        adir,
                        task,
                        level_start_state,
                        anode,
                        obs,
                        root_span_id=root_span,
                    )

                max_workers = min(len(eligible), 16)
                collected: dict[str, dict] = {}
                with ThreadPoolExecutor(max_workers=max_workers) as pool:
                    futures = {pool.submit(_run_agent_thread, aid): aid for aid in eligible}
                    for future in as_completed(futures):
                        aid, result = future.result()
                        collected[aid] = result

                # Merge results after all agents complete
                for agent_id in eligible:
                    if agent_id in collected:
                        state.update(collected[agent_id])

                # Post-merge: eval, budget, rate-limit, checkpoints (sequential)
                for agent_id in eligible:
                    if agent_id not in collected:
                        continue
                    if eval_engine:
                        step_eval = eval_engine.evaluate_step(
                            hook="worker_result",
                            result=collected[agent_id],
                            state=state,
                            budget=self._run_budget,
                            agent_id=agent_id,
                        )
                        if step_eval:
                            logger.info(
                                "  Eval [%s]: score=%.2f action=%s",
                                agent_id,
                                step_eval.score,
                                step_eval.action,
                            )
                    if self._run_budget:
                        self._run_budget.record_agent_run()
                    if self._security.rate_limiter:
                        self._security.rate_limiter.record(agent_id)
                    try:
                        self._state_persistence.save_checkpoint(agent_id, state)
                    except Exception as exc:
                        logger.warning("Failed to save checkpoint for %s: %s", agent_id, exc)

        # Phase 2 scope (R33): deterministic phases run post-graph, in
        # topological order of their ``depends_on`` lists. The DAG runner
        # is the only engine that dispatches them in this release; the
        # delegation-loop hook lands in Phase 2.x.
        self._run_deterministic_phases(orch, state, obs)

        return self._finalize_run(state, obs, root_span, workflow_start, levels, eval_engine)

    # ------------------------------------------------------------------
    # Deterministic phases (R33, Phase 2)
    # ------------------------------------------------------------------

    def _run_deterministic_phases(
        self,
        orch: AWPOrchestrationConfig,
        state: Dict[str, Any],
        obs: "ObservabilityContext",
    ) -> None:
        """Dispatch deterministic phases declared under ``orchestration.phases``.

        Invoked once, after all graph nodes complete, before finalization.
        Phases are executed in topological order of ``depends_on`` (over
        the phase set only; graph-node dependencies are not re-checked —
        the graph has already completed). Each phase's result is
        persisted under ``output/<run_id>/phase_<id>/`` and mirrored
        into ``state["_phases"]`` for downstream consumption.
        """
        phases_raw = getattr(orch, "phases", None)
        if not phases_raw:
            return

        # Resolve each entry into a DeterministicPhase (other types are
        # skipped here; ``llm`` phases flow through the manager loop and
        # ``hybrid`` is reserved).
        from awp.models.orchestration import DeterministicPhase

        from .deterministic import (
            DeterministicPhaseRunner,
            ExecutionContext,
        )

        phase_objs: list[DeterministicPhase] = []
        for pd in phases_raw:
            if not isinstance(pd, dict):
                continue
            ptype = pd.get("type", "llm")
            if ptype == "deterministic":
                try:
                    phase_objs.append(DeterministicPhase.model_validate(pd))
                except Exception as exc:  # noqa: BLE001
                    logger.error(
                        "Invalid deterministic phase spec %r: %s", pd.get("id"), exc
                    )
                    continue
            elif ptype == "hybrid":
                raise NotImplementedError(
                    f"Phase {pd.get('id')!r}: type='hybrid' is reserved and not "
                    f"yet implemented. Split into an 'llm' phase followed by a "
                    f"'deterministic' phase."
                )
            # llm phases: the DAG engine has no manager loop to dispatch
            # to — they are a no-op here. Workflow authors targeting LLM
            # phases should use ``engine: delegation_loop``.

        if not phase_objs:
            return

        # Topological sort over phase ids — dependencies on graph nodes
        # are satisfied by construction (graph already completed).
        phase_ids = {p.id for p in phase_objs}
        indeg: dict[str, int] = {p.id: 0 for p in phase_objs}
        adj: dict[str, list[str]] = {p.id: [] for p in phase_objs}
        for p in phase_objs:
            for dep in p.depends_on:
                if dep in phase_ids:
                    indeg[p.id] += 1
                    adj[dep].append(p.id)
        ready = [pid for pid, d in indeg.items() if d == 0]
        ordered: list[str] = []
        while ready:
            pid = ready.pop(0)
            ordered.append(pid)
            for nxt in adj[pid]:
                indeg[nxt] -= 1
                if indeg[nxt] == 0:
                    ready.append(nxt)
        if len(ordered) != len(phase_objs):
            logger.error(
                "Cycle detected in orchestration.phases depends_on — "
                "falling back to declared order"
            )
            ordered = [p.id for p in phase_objs]

        by_id = {p.id: p for p in phase_objs}

        # Resolve workspace / output directories for this run.
        run_id = getattr(self, "_current_run_id", None) or ""
        output_dir = self._dir / "output" / run_id if run_id else self._dir / "output"
        workspace_dir = self._dir / "workspace"
        output_dir.mkdir(parents=True, exist_ok=True)
        workspace_dir.mkdir(parents=True, exist_ok=True)

        runner = DeterministicPhaseRunner(workflow_dir=self._dir, logger=logger)
        phase_records: list[dict[str, Any]] = []
        aggregate_status = "complete"

        for pid in ordered:
            phase = by_id[pid]
            ctx = ExecutionContext(
                workflow_dir=self._dir,
                workspace_dir=workspace_dir,
                output_dir=output_dir,
                state=state,
            )
            logger.info("Deterministic phase '%s' starting", pid)
            result = runner.run(phase, ctx)
            logger.info(
                "Deterministic phase '%s' -> %s (%.2fs) reason=%r",
                pid,
                result.status,
                result.duration_s,
                result.reason,
            )

            # Persist per-phase artifact.
            phase_dir = output_dir / f"phase_{pid}"
            try:
                phase_dir.mkdir(parents=True, exist_ok=True)
                import json as _json

                (phase_dir / "result.json").write_text(
                    _json.dumps(result.to_dict(), indent=2, default=str),
                    encoding="utf-8",
                )
                if result.stdout:
                    (phase_dir / "stdout.log").write_text(
                        result.stdout, encoding="utf-8"
                    )
                if result.stderr:
                    (phase_dir / "stderr.log").write_text(
                        result.stderr, encoding="utf-8"
                    )
            except OSError as exc:
                logger.warning(
                    "Could not persist phase '%s' artifacts: %s", pid, exc
                )

            record = result.to_dict()
            phase_records.append(record)

            if obs.audit:
                obs.audit.record(
                    "phase.complete",
                    details={
                        "phase_id": pid,
                        "status": result.status,
                        "reason": result.reason,
                        "duration_s": round(result.duration_s, 3),
                    },
                )

            # Aggregate status: failed > partial > complete.
            if result.status == "failed":
                aggregate_status = "failed"
            elif result.status == "partial" and aggregate_status != "failed":
                aggregate_status = "partial"

        state["_phases"] = phase_records
        if aggregate_status != "complete":
            state.setdefault("_phase_status", aggregate_status)

    def _finalize_run(
        self,
        state: Dict[str, Any],
        obs: "ObservabilityContext",
        root_span: Optional[str],
        workflow_start: float,
        levels: list,
        eval_engine: Optional[EvaluationEngine] = None,
    ) -> Dict[str, Any]:
        """Finalize a workflow run — observability, evaluation, cleanup, persistence."""
        workflow_duration = time.monotonic() - workflow_start

        # Attach budget summary to state
        if self._run_budget:
            state.setdefault("_run_budget", self._run_budget.summary())

        if obs.tracer and root_span:
            obs.tracer.end_span(
                root_span,
                status="ok",
                attributes={
                    "duration_s": round(workflow_duration, 2),
                    "agents_executed": sum(len(lvl) for lvl in levels),
                },
            )
        if obs.metrics:
            obs.metrics.histogram(
                "workflow.duration_s", workflow_duration, labels={"workflow": self.name}
            )
        if obs.audit:
            obs.audit.record(
                "workflow.complete",
                details={
                    "duration_s": round(workflow_duration, 2),
                },
            )

        # Final evaluation
        if eval_engine and eval_engine.enabled:
            final_eval = eval_engine.evaluate_final(
                result=state,
                state=state,
                budget=self._run_budget,
            )
            if final_eval:
                action = eval_engine.decide_retry(final_eval)
                logger.info(
                    "Final evaluation: score=%.2f action=%s",
                    final_eval.score,
                    action,
                )
                state["_evaluation"] = eval_engine.get_summary()
            eval_engine.flush()

        # Flush observability
        obs.flush_all()

        # Clean up dynamic tools
        if self._dynamic_tool_factory.enabled:
            self._dynamic_tool_factory.cleanup()

        # Clean up executor resources (venv, containers, etc.)
        if hasattr(self._code_executor, "cleanup"):
            self._code_executor.cleanup()

        # Save final state
        try:
            self._state_persistence.save_final(state)
        except Exception as exc:
            logger.warning("Failed to save final state: %s", exc)

        return state

    # -- Ready-queue scheduler ---------------------------------------------

    def _execute_ready_queue(
        self,
        orch: AWPOrchestrationConfig,
        task: str,
        state: dict[str, Any],
        levels: list[list[str]],
        obs: ObservabilityContext,
        root_span: Optional[str],
        eval_engine: Optional[EvaluationEngine],
        workflow_start: float,
    ) -> dict[str, Any]:
        """Execute the DAG as a ready-queue, dispatching nodes as soon as their
        direct dependencies complete.

        Semantics differ from the level scheduler in one observable way:
        ``when`` expressions, circuit-breaker checks, and rate-limit checks
        are evaluated at **dispatch time** (against the current state snapshot)
        rather than at level-start. Every agent is dispatched at most once.

        Concurrency: a persistent ``ThreadPoolExecutor`` is sized at
        ``min(total_nodes, 16)`` — identical to the level path's cap. Only
        ``state.update(result)`` is serialized via a lock; reads remain
        lock-free because R17 guarantees disjoint writer keys per agent.
        """
        all_node_ids: list[str] = [node.id for node in orch.graph]
        pending_deps: dict[str, set[str]] = {}
        dependents: dict[str, list[str]] = {nid: [] for nid in all_node_ids}
        for node in orch.graph:
            dep_set: set[str] = set()
            for dep in node.depends_on:
                if isinstance(dep, ConditionalDependency):
                    dep_set.add(dep.agent)
                elif isinstance(dep, dict):
                    agent_ref = dep.get("agent") or dep.get("id", "")
                    if agent_ref:
                        dep_set.add(agent_ref)
                else:
                    dep_set.add(dep)
            pending_deps[node.id] = dep_set
            for parent in dep_set:
                if parent in dependents:
                    dependents[parent].append(node.id)

        total_nodes = len(all_node_ids)
        pool_cap = min(total_nodes, 16) if total_nodes > 0 else 1

        state_lock = threading.Lock()
        in_flight: dict[Any, str] = {}
        ready: list[str] = [nid for nid, deps in pending_deps.items() if not deps]
        dispatched: set[str] = set()
        completed: set[str] = set()
        budget_exceeded_reason: Optional[str] = None

        def _run_agent_thread(aid: str, snapshot: dict[str, Any]) -> tuple[str, dict]:
            self._tools._current_agent_id = aid
            adir = self._dir / "agents" / aid
            anode = self._get_node(orch, aid)
            return aid, self._execute_node(
                aid,
                adir,
                task,
                snapshot,
                anode,
                obs,
                root_span_id=root_span,
            )

        def _skip_node(aid: str, reason: str, payload: Optional[dict] = None) -> None:
            if payload is not None:
                with state_lock:
                    state[aid] = payload
            if obs.audit:
                obs.audit.record("agent.skipped", aid, details={"reason": reason})
            completed.add(aid)
            for child in dependents.get(aid, []):
                if child in completed or child in dispatched:
                    continue
                pending_deps[child].discard(aid)
                if not pending_deps[child] and child not in ready:
                    ready.append(child)

        pool: Optional[ThreadPoolExecutor] = None
        try:
            pool = ThreadPoolExecutor(max_workers=pool_cap)
            while ready or in_flight:
                # Dispatch as many ready nodes as possible.
                i = 0
                while i < len(ready):
                    if budget_exceeded_reason:
                        break
                    if self._run_budget:
                        can_go, reason = self._run_budget.check()
                        if not can_go:
                            budget_exceeded_reason = reason
                            logger.warning(
                                "  Run budget limit hit: %s — stopping workflow", reason
                            )
                            if obs.audit:
                                obs.audit.record(
                                    "workflow.budget_exceeded",
                                    details={
                                        "reason": reason,
                                        "budget_summary": self._run_budget.summary(),
                                    },
                                )
                            break
                    agent_id = ready[i]
                    node = self._get_node(orch, agent_id)

                    if node and not node.enabled:
                        logger.info("  Skipping disabled agent: %s", agent_id)
                        ready.pop(i)
                        dispatched.add(agent_id)
                        _skip_node(agent_id, "disabled")
                        continue

                    with state_lock:
                        state_snapshot = dict(state)

                    if not self._evaluate_when(node, state_snapshot):
                        logger.info("  Skipping agent %s: when condition not met", agent_id)
                        ready.pop(i)
                        dispatched.add(agent_id)
                        _skip_node(agent_id, "when_condition")
                        continue

                    if self._security.rate_limiter and not self._security.rate_limiter.check(
                        agent_id
                    ):
                        logger.warning("  Rate limited: %s", agent_id)
                        ready.pop(i)
                        dispatched.add(agent_id)
                        _skip_node(
                            agent_id,
                            "rate_limited",
                            payload={"error": "Rate limited", "confidence": 0.0},
                        )
                        if obs.audit:
                            obs.audit.record("agent.rate_limited", agent_id)
                        continue

                    if (
                        self._security.circuit_breaker
                        and not self._security.circuit_breaker.check()
                    ):
                        logger.warning("  Circuit breaker open, skipping: %s", agent_id)
                        ready.pop(i)
                        dispatched.add(agent_id)
                        _skip_node(
                            agent_id,
                            "circuit_breaker",
                            payload={"error": "Circuit breaker open", "confidence": 0.0},
                        )
                        if obs.audit:
                            obs.audit.record("agent.circuit_breaker", agent_id)
                        continue

                    if obs.audit:
                        obs.audit.record(
                            "agent.dispatched",
                            agent_id,
                            details={
                                "scheduler": "ready_queue",
                                "state_snapshot_keys": sorted(state_snapshot.keys()),
                            },
                        )
                    logger.info("Dispatch (ready_queue): %s", agent_id)
                    future = pool.submit(_run_agent_thread, agent_id, state_snapshot)
                    in_flight[future] = agent_id
                    ready.pop(i)
                    dispatched.add(agent_id)

                if budget_exceeded_reason and in_flight:
                    # Drain currently in-flight futures but stop new dispatch.
                    pass

                if not in_flight:
                    # No new dispatches happened and nothing is running.
                    if budget_exceeded_reason:
                        break
                    # If ready is empty and in_flight is empty, loop will exit.
                    if not ready:
                        break
                    # All ready items were consumed above; check again.
                    continue

                # Wait for at least one future to finish.
                done_set, _ = wait(list(in_flight.keys()), return_when=FIRST_COMPLETED)

                for future in done_set:
                    agent_id = in_flight.pop(future)
                    try:
                        aid, result = future.result()
                    except Exception as exc:
                        logger.error("  Ready-queue agent %s raised: %s", agent_id, exc)
                        result = {agent_id: {"error": str(exc), "confidence": 0.0}}
                        aid = agent_id

                    with state_lock:
                        state.update(result)

                    if eval_engine:
                        step_eval = eval_engine.evaluate_step(
                            hook="worker_result",
                            result=result,
                            state=state,
                            budget=self._run_budget,
                            agent_id=aid,
                        )
                        if step_eval:
                            logger.info(
                                "  Eval [%s]: score=%.2f action=%s",
                                aid,
                                step_eval.score,
                                step_eval.action,
                            )

                    if self._run_budget:
                        self._run_budget.record_agent_run()
                    if self._security.rate_limiter:
                        self._security.rate_limiter.record(aid)

                    try:
                        self._state_persistence.save_checkpoint(aid, state)
                    except Exception as exc:
                        logger.warning("Failed to save checkpoint for %s: %s", aid, exc)

                    completed.add(aid)
                    for child in dependents.get(aid, []):
                        if child in completed or child in dispatched:
                            continue
                        pending_deps[child].discard(aid)
                        if not pending_deps[child] and child not in ready:
                            ready.append(child)
        finally:
            if pool is not None:
                pool.shutdown(wait=True)

        if budget_exceeded_reason and self._run_budget:
            state["_run_budget"] = self._run_budget.summary()
            state["_run_budget"]["exceeded"] = budget_exceeded_reason
        else:
            # Only dispatch deterministic phases if the graph completed
            # normally — a budget-exceeded exit skips them (same as the
            # level-scheduler path).
            self._run_deterministic_phases(orch, state, obs)

        return self._finalize_run(state, obs, root_span, workflow_start, levels, eval_engine)

    # -- Delegation loop dispatch ------------------------------------------

    def _run_delegation_loop(self, task: str, state: dict[str, Any]) -> dict[str, Any]:
        """Dispatch to the DelegationLoopRunner when engine=delegation_loop."""
        from .delegation_loop_runner import DelegationLoopRunner

        orch = self._manifest.orchestration
        dl_config = getattr(orch, "delegation_loop", None)
        if not dl_config:
            raise RuntimeError("engine=delegation_loop but no delegation_loop config found")

        import os

        manager_model = (
            self._manager_model
            or (dl_config.models.manager if dl_config.models else None)
            or os.getenv("LLM_MODEL", "")
        )
        worker_model = (
            self._worker_model
            or (dl_config.models.worker if dl_config.models else None)
            or manager_model
        )

        # Pass evaluation config if available
        obs_cfg = getattr(self._manifest, "observability", None)
        eval_cfg = getattr(obs_cfg, "evaluation", None) if obs_cfg else None

        runner = DelegationLoopRunner(
            workflow_dir=self._dir,
            config=dl_config,
            tool_registry=self._tools,
            manager_model=manager_model,
            worker_model=worker_model,
            eval_config=eval_cfg,
            llm_client=self._llm,
        )
        result = runner.run(task, state)
        state.update(result)
        return state

    # -- Agent execution with retry ----------------------------------------

    def _run_agent_with_retry(
        self,
        agent_id: str,
        agent_dir: Path,
        task: str,
        state: dict[str, Any],
        node: Any,
        obs: ObservabilityContext,
        root_span_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Execute an agent with retry logic."""
        max_retries = 0
        retry_delay = 2.0
        if node:
            max_retries = getattr(node, "retry", 0)
            # Get retry config from execution error_handling
            exec_cfg = getattr(self._manifest.orchestration, "execution", None)
            if exec_cfg and hasattr(exec_cfg, "error_handling"):
                eh = exec_cfg.error_handling
                max_retries = max_retries or getattr(eh, "max_retries", 0)
                retry_delay = getattr(eh, "retry_delay", 2.0)

        for attempt in range(max_retries + 1):
            # Start agent span
            agent_span = None
            if obs.tracer:
                agent_span = obs.tracer.start_span(
                    f"agent.{agent_id}",
                    parent_id=root_span_id,
                    attributes={"agent_id": agent_id, "attempt": attempt},
                )
            if obs.audit:
                obs.audit.record("agent.start", agent_id, details={"attempt": attempt})

            agent_start = time.monotonic()

            if not agent_dir.exists():
                logger.error("  Agent dir not found: %s", agent_dir)
                if obs.tracer and agent_span:
                    obs.tracer.end_span(
                        agent_span,
                        status="error",
                        attributes={"error": "dir_not_found"},
                    )
                if node and node.on_failure == "abort":
                    raise RuntimeError(f"Agent directory not found: {agent_dir}")
                return {agent_id: {"error": "Agent directory not found", "confidence": 0.0}}

            try:
                agent = self._load_agent(agent_dir)
                result = agent.run(task, state)
                agent_duration = time.monotonic() - agent_start

                # Success
                if obs.tracer and agent_span:
                    obs.tracer.end_span(
                        agent_span,
                        status="ok",
                        attributes={
                            "duration_s": round(agent_duration, 2),
                        },
                    )
                if obs.metrics:
                    obs.metrics.histogram(
                        "agent.duration_s", agent_duration, labels={"agent": agent_id}
                    )
                    obs.metrics.increment(
                        "agent.executions", labels={"agent": agent_id, "status": "ok"}
                    )
                if obs.audit:
                    agent_result = result.get(agent_id, {})
                    obs.audit.record(
                        "agent.complete",
                        agent_id,
                        details={
                            "duration_s": round(agent_duration, 2),
                            "confidence": agent_result.get("confidence", "N/A"),
                        },
                    )
                if self._security.circuit_breaker:
                    self._security.circuit_breaker.record_success()

                logger.info("  Completed: %s (%.1fs)", agent_id, agent_duration)

                # Memory auto-write
                self._auto_write_memory(agent_id, result.get(agent_id, {}))

                return result

            except Exception as exc:
                agent_duration = time.monotonic() - agent_start
                logger.error(
                    "  Failed: %s -- %s (attempt %d/%d)",
                    agent_id,
                    exc,
                    attempt + 1,
                    max_retries + 1,
                )

                if obs.tracer and agent_span:
                    obs.tracer.end_span(agent_span, status="error", attributes={"error": str(exc)})
                if obs.metrics:
                    obs.metrics.increment(
                        "agent.executions",
                        labels={"agent": agent_id, "status": "error"},
                    )
                if obs.audit:
                    obs.audit.record(
                        "agent.error",
                        agent_id,
                        details={
                            "error": str(exc),
                            "attempt": attempt,
                        },
                    )
                if self._security.circuit_breaker:
                    self._security.circuit_breaker.record_failure()

                # Retry?
                if attempt < max_retries:
                    delay = retry_delay * (2**attempt)
                    logger.info("  Retrying %s in %.1fs...", agent_id, delay)
                    time.sleep(delay)
                    continue

                # Final failure
                on_failure = node.on_failure if node else "continue"
                if on_failure == "abort":
                    raise
                return {agent_id: {"error": str(exc), "confidence": 0.0}}

        # Should not reach here, but just in case
        return {agent_id: {"error": "Max retries exceeded", "confidence": 0.0}}

    # -- Node execution (loop + fan_out + retry) ---------------------------

    def _execute_node(
        self,
        agent_id: str,
        agent_dir: Path,
        task: str,
        state: dict[str, Any],
        node: Any,
        obs: ObservabilityContext,
        root_span_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Run a node, honouring its loop and fan_out configuration.

        Composition order: loop(fan_out(retry(run))). Both loop and fan_out
        are pure no-ops unless ``.enabled`` is True on the node config.
        """
        loop_cfg = getattr(node, "loop", None) if node else None
        if loop_cfg is not None and getattr(loop_cfg, "enabled", False):
            return self._execute_loop(
                agent_id, agent_dir, task, state, node, obs, root_span_id, loop_cfg
            )

        fan_out_cfg = getattr(node, "fan_out", None) if node else None
        if fan_out_cfg is not None and getattr(fan_out_cfg, "enabled", False):
            return self._execute_fan_out(
                agent_id, agent_dir, task, state, node, obs, root_span_id, fan_out_cfg
            )

        return self._run_agent_with_retry(
            agent_id, agent_dir, task, state, node, obs, root_span_id=root_span_id
        )

    def _execute_loop(
        self,
        agent_id: str,
        agent_dir: Path,
        task: str,
        state: dict[str, Any],
        node: Any,
        obs: ObservabilityContext,
        root_span_id: Optional[str],
        loop_cfg: Any,
    ) -> dict[str, Any]:
        """Run a node iteratively.

        Semantics of ``until_condition``: the loop continues **while the
        expression evaluates truthy**; it exits when the expression becomes
        falsy or when ``max_iterations`` is reached. An empty condition runs
        the loop exactly ``max_iterations`` times. The expression is
        evaluated against the running state *after* each iteration, so it
        can reference the latest agent output via ``state.<agent_id>.*``.
        """
        max_iter = max(1, int(getattr(loop_cfg, "max_iterations", 5)))
        cond = (getattr(loop_cfg, "until_condition", "") or "").strip()
        mode = getattr(loop_cfg, "mode", "standard")
        if mode == "interactive":
            logger.warning(
                "  Loop [%s]: interactive mode not implemented, falling back to standard",
                agent_id,
            )

        fan_out_cfg = getattr(node, "fan_out", None) if node else None
        use_fan_out = fan_out_cfg is not None and getattr(fan_out_cfg, "enabled", False)

        iterations: list[dict[str, Any]] = []
        last_result: dict[str, Any] = {}
        for iteration in range(max_iter):
            if use_fan_out:
                step = self._execute_fan_out(
                    agent_id, agent_dir, task, state, node, obs, root_span_id, fan_out_cfg
                )
            else:
                step = self._run_agent_with_retry(
                    agent_id, agent_dir, task, state, node, obs, root_span_id=root_span_id
                )
            state.update(step)
            last_result = step
            iterations.append(step.get(agent_id, {}))

            if obs.audit:
                obs.audit.record(
                    "agent.loop_iteration",
                    agent_id,
                    details={"iteration": iteration + 1, "max": max_iter},
                )

            if not cond:
                continue

            try:
                keep_going = bool(safe_eval(cond, {"state": state}))
            except Exception as exc:
                logger.warning(
                    "  Loop [%s]: condition '%s' error: %s (exiting loop)",
                    agent_id,
                    cond,
                    exc,
                )
                break

            logger.info(
                "  Loop [%s]: iteration %d/%d until_condition=%s",
                agent_id,
                iteration + 1,
                max_iter,
                keep_going,
            )
            if not keep_going:
                break

        final = dict(last_result.get(agent_id, {}))
        final["_loop_iterations"] = len(iterations)
        final["_loop_history"] = iterations
        return {agent_id: final}

    def _execute_fan_out(
        self,
        agent_id: str,
        agent_dir: Path,
        task: str,
        state: dict[str, Any],
        node: Any,
        obs: ObservabilityContext,
        root_span_id: Optional[str],
        fan_out_cfg: Any,
    ) -> dict[str, Any]:
        """Spawn the agent in parallel across items from ``source_field``.

        - ``source_field`` resolves against the current state. Supports a
          leading ``state.`` prefix and dotted paths (``ctx.topics``).
        - Each instance receives a shallow-copied state with the item
          injected under the reserved key ``fan_out_item`` and its index
          under ``_fan_out_index``.
        - ``max_parallel`` caps the thread-pool size.
        - ``aggregation`` chooses how per-item outputs are combined: ``merge``
          returns ``{items: [...], confidence: mean}``; ``concat`` flattens
          list-valued fields across items; anything else behaves as ``merge``.
        """
        items = self._resolve_fan_out_source(
            getattr(fan_out_cfg, "source_field", "") or "", state
        )
        if not items:
            logger.warning(
                "  fan_out [%s]: source '%s' resolved to empty list",
                agent_id,
                getattr(fan_out_cfg, "source_field", ""),
            )
            return {
                agent_id: {
                    "confidence": 0.0,
                    "error": f"fan_out source '{getattr(fan_out_cfg, 'source_field', '')}' empty",
                    "_fan_out_count": 0,
                    "items": [],
                }
            }

        max_parallel = max(1, int(getattr(fan_out_cfg, "max_parallel", 4) or 4))
        aggregation = getattr(fan_out_cfg, "aggregation", "merge") or "merge"

        def _run_one(idx: int, item: Any) -> tuple[int, dict[str, Any]]:
            item_state = dict(state)
            item_state["fan_out_item"] = item
            item_state["_fan_out_index"] = idx
            return idx, self._run_agent_with_retry(
                agent_id, agent_dir, task, item_state, node, obs, root_span_id=root_span_id
            )

        collected: list[tuple[int, dict[str, Any]]] = []
        workers = min(max_parallel, len(items))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(_run_one, i, it) for i, it in enumerate(items)]
            for fut in as_completed(futures):
                collected.append(fut.result())
        collected.sort(key=lambda p: p[0])
        outputs = [res.get(agent_id, {}) for _, res in collected]

        confidences = [
            o.get("confidence", 0.0)
            for o in outputs
            if isinstance(o.get("confidence"), (int, float))
        ]
        mean_conf = sum(confidences) / len(confidences) if confidences else 0.0

        if aggregation == "concat":
            merged: dict[str, Any] = {}
            for o in outputs:
                for k, v in o.items():
                    if k in ("confidence", "_fan_out_index"):
                        continue
                    if isinstance(v, list):
                        merged.setdefault(k, []).extend(v)
                    else:
                        merged.setdefault(k, []).append(v)
            merged["confidence"] = mean_conf
            merged["_fan_out_count"] = len(outputs)
            merged["items"] = outputs
            return {agent_id: merged}

        # "merge" (default) or any unknown aggregation: preserve per-item outputs
        return {
            agent_id: {
                "items": outputs,
                "confidence": mean_conf,
                "_fan_out_count": len(outputs),
            }
        }

    @staticmethod
    def _resolve_fan_out_source(source: str, state: dict[str, Any]) -> list[Any]:
        """Resolve a dotted state path to an iterable list.

        Accepts ``state.a.b``, ``a.b``, or just ``a``. Returns ``[]`` if the
        path is empty, missing, or resolves to a non-iterable scalar.
        """
        path = source.strip()
        if not path:
            return []
        if path.startswith("state."):
            path = path[len("state."):]
        node: Any = state
        for part in path.split("."):
            if isinstance(node, dict):
                node = node.get(part)
            else:
                node = getattr(node, part, None)
            if node is None:
                return []
        if isinstance(node, (list, tuple)):
            return list(node)
        if isinstance(node, dict):
            return list(node.values())
        return []

    # -- When conditions ---------------------------------------------------

    def _evaluate_when(self, node: Any, state: dict[str, Any]) -> bool:
        """Evaluate a node's ``when`` expression. True if no condition."""
        if not node:
            return True

        # Check node-level when
        when_expr = getattr(node, "when", None)
        if not when_expr:
            # Also check depends_on for conditional when expressions
            for dep in getattr(node, "depends_on", []):
                if isinstance(dep, dict):
                    dep_when = dep.get("when")
                elif hasattr(dep, "when"):
                    dep_when = dep.when
                else:
                    dep_when = None
                if dep_when:
                    when_expr = dep_when
                    break

        if not when_expr:
            return True

        try:
            result = safe_eval(when_expr, {"state": state})
            logger.info("  when '%s' => %s", when_expr, result)
            return bool(result)
        except Exception as exc:
            logger.warning("  when expression error '%s': %s (defaulting to True)", when_expr, exc)
            return True

    # -- Memory -------------------------------------------------------

    def _auto_write_memory(self, agent_id: str, result: dict[str, Any]) -> None:
        """Write agent result summary to daily log if memory is enabled."""
        mem = self._manifest.memory
        if not mem or not hasattr(mem, "enabled") or not mem.enabled:
            return
        if not hasattr(mem, "daily_log") or not mem.daily_log.enabled:
            return
        if not hasattr(mem.daily_log, "auto_write") or not mem.daily_log.auto_write:
            return

        workspace = self._dir / "workspace" / "memory"
        workspace.mkdir(parents=True, exist_ok=True)

        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        time_str = datetime.now(timezone.utc).strftime("%H:%M:%S")
        log_file = workspace / f"{date}.md"

        # Build summary
        confidence = result.get("confidence", "N/A")
        summary_parts = [f"\n### {time_str} -- {agent_id} (confidence: {confidence})\n"]
        for key, value in result.items():
            if key in ("confidence", "error"):
                continue
            if isinstance(value, str) and len(value) > 200:
                value = value[:200] + "..."
            summary_parts.append(f"- **{key}**: {value}")

        with log_file.open("a", encoding="utf-8") as f:
            f.write("\n".join(summary_parts) + "\n")

    # -- Helpers ------------------------------------------------------

    def _topological_levels(self, orch: AWPOrchestrationConfig) -> list[list[str]]:
        deps: dict[str, set[str]] = {}
        all_ids: list[str] = []
        for node in orch.graph:
            all_ids.append(node.id)
            dep_set: set[str] = set()
            for dep in node.depends_on:
                if isinstance(dep, ConditionalDependency):
                    dep_set.add(dep.agent)
                elif isinstance(dep, dict):
                    agent_ref = dep.get("agent") or dep.get("id", "")
                    if agent_ref:
                        dep_set.add(agent_ref)
                else:
                    dep_set.add(dep)
            deps[node.id] = dep_set

        levels: list[list[str]] = []
        remaining = set(all_ids)
        while remaining:
            level = [n for n in remaining if not deps.get(n, set()) & remaining]
            if not level:
                levels.append(sorted(remaining))
                break
            levels.append(sorted(level))
            remaining -= set(level)
        return levels

    @staticmethod
    def _get_node(orch: AWPOrchestrationConfig, agent_id: str):
        for node in orch.graph:
            if node.id == agent_id:
                return node
        return None
