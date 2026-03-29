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
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from awp.parser import parse_manifest
from awp.models.capabilities import SandboxConfig
from awp.models.orchestration import (
    AWPOrchestrationConfig,
    ConditionalDependency,
    RunBudgetLimits,
)
from .agent import StandaloneAgent
from .executor_factory import create_executor
from .expressions import safe_eval
from .llm import LLMClient
from .message_bus import MessageBus
from .observability import ObservabilityContext
from .secrets import load_secrets
from .security import SecurityContext
from .state_persistence import StatePersistence
from .dynamic_tool_factory import DynamicToolFactory
from .tools import ToolRegistry

logger = logging.getLogger(__name__)


class RunBudgetTracker:
    """Tracks consumed resources against global run budget limits.

    Only checks limits that are listed in ``enabled_limits``.
    """

    def __init__(self, budget: RunBudgetLimits) -> None:
        self._budget = budget
        self._enabled = set(budget.enabled_limits)
        self.agent_runs = 0
        self.tool_calls = 0
        self.tokens_used = 0
        self.cost_usd = 0.0
        self._start = time.monotonic()

    @property
    def wall_time_elapsed(self) -> float:
        return time.monotonic() - self._start

    def record_agent_run(self) -> None:
        self.agent_runs += 1

    def record_tool_calls(self, count: int = 1) -> None:
        self.tool_calls += count

    def record_tokens(self, count: int) -> None:
        self.tokens_used += count

    def record_cost(self, usd: float) -> None:
        self.cost_usd += usd

    def check(self) -> tuple[bool, str]:
        """Return (can_continue, reason).  Only checks enabled limits."""
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
                    value = value.replace(
                        "{{TIMESTAMP}}", datetime.now(timezone.utc).isoformat()
                    )
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

        logger.info(
            "Running workflow '%s' [run_id=%s] with %d agents in %d levels",
            self.name,
            run_id,
            sum(len(lvl) for lvl in levels),
            len(levels),
        )

        workflow_start = time.monotonic()

        for level_idx, level in enumerate(levels):
            level_str = ", ".join(level)
            parallel = " (parallel)" if len(level) > 1 else ""
            logger.info("Level %d: [%s]%s", level_idx, level_str, parallel)

            for agent_id in level:
                # Run budget check — stop early if a limit is exceeded
                if self._run_budget:
                    can_go, reason = self._run_budget.check()
                    if not can_go:
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
                        state["_run_budget"] = self._run_budget.summary()
                        state["_run_budget"]["exceeded"] = reason
                        # Break out of both loops
                        return self._finalize_run(
                            state, obs, root_span, workflow_start, levels
                        )

                node = self._get_node(orch, agent_id)
                if node and not node.enabled:
                    logger.info("  Skipping disabled agent: %s", agent_id)
                    continue

                # Evaluate when condition
                if not self._evaluate_when(node, state):
                    logger.info("  Skipping agent %s: when condition not met", agent_id)
                    if obs.audit:
                        obs.audit.record(
                            "agent.skipped",
                            agent_id,
                            details={"reason": "when_condition"},
                        )
                    continue

                # Rate limiter check
                if self._security.rate_limiter:
                    if not self._security.rate_limiter.check(agent_id):
                        logger.warning("  Rate limited: %s", agent_id)
                        if obs.audit:
                            obs.audit.record("agent.rate_limited", agent_id)
                        state[agent_id] = {"error": "Rate limited", "confidence": 0.0}
                        continue

                # Circuit breaker check
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

                # Set current agent for tool access control
                self._tools._current_agent_id = agent_id

                # Execute agent with retry
                agent_dir = self._dir / "agents" / agent_id
                result = self._run_agent_with_retry(
                    agent_id,
                    agent_dir,
                    task,
                    state,
                    node,
                    obs,
                    root_span_id=root_span,
                )
                state.update(result)

                # Track agent run in global budget
                if self._run_budget:
                    self._run_budget.record_agent_run()

                # Record rate limit usage
                if self._security.rate_limiter:
                    self._security.rate_limiter.record(agent_id)

                # State persistence checkpoint
                try:
                    self._state_persistence.save_checkpoint(agent_id, state)
                except Exception as exc:
                    logger.warning(
                        "Failed to save checkpoint for %s: %s", agent_id, exc
                    )

        return self._finalize_run(state, obs, root_span, workflow_start, levels)

    def _finalize_run(
        self,
        state: Dict[str, Any],
        obs: "ObservabilityContext",
        root_span: Optional[str],
        workflow_start: float,
        levels: list,
    ) -> Dict[str, Any]:
        """Finalize a workflow run — observability, cleanup, persistence."""
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

        # Generate execution graph
        try:
            from .execution_graph import generate_execution_graph

            rid = getattr(self, "_current_run_id", "")
            graph_dir = self._dir / "data" / rid if rid else self._dir / "data"
            graph_dir.mkdir(parents=True, exist_ok=True)
            generate_execution_graph(
                run_dir=self._dir,
                output_path=graph_dir / "execution_graph.html",
                workflow_dir=self._dir,
            )
        except Exception as exc:
            logger.debug("Execution graph generation skipped: %s", exc)

        return state

    # -- Delegation loop dispatch ------------------------------------------

    def _run_delegation_loop(self, task: str, state: dict[str, Any]) -> dict[str, Any]:
        """Dispatch to the DelegationLoopRunner when engine=delegation_loop."""
        from .delegation_loop_runner import DelegationLoopRunner

        orch = self._manifest.orchestration
        dl_config = getattr(orch, "delegation_loop", None)
        if not dl_config:
            raise RuntimeError(
                "engine=delegation_loop but no delegation_loop config found"
            )

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

        runner = DelegationLoopRunner(
            workflow_dir=self._dir,
            config=dl_config,
            tool_registry=self._tools,
            manager_model=manager_model,
            worker_model=worker_model,
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
                return {
                    agent_id: {"error": "Agent directory not found", "confidence": 0.0}
                }

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
                    obs.tracer.end_span(
                        agent_span, status="error", attributes={"error": str(exc)}
                    )
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
            logger.warning(
                "  when expression error '%s': %s (defaulting to True)", when_expr, exc
            )
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
