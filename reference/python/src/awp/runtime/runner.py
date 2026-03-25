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

import json
import logging
import subprocess
import sys
import time
import uuid
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from ..parser import parse_manifest
from ..models.orchestration import AWPOrchestrationConfig, ConditionalDependency
from .agent import StandaloneAgent
from .code_executor import CodeExecutor
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
    ) -> None:
        self._dir = Path(workflow_dir)
        self._install_requirements()
        self._manifest = parse_manifest(self._dir / "workflow.awp.yaml")
        self._llm = llm
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

        # Code executor
        self._code_executor = CodeExecutor(
            max_timeout=60,
            working_dir=self._dir,
        )
        self._tools.set_code_executor(self._code_executor)

        # Dynamic tool factory
        dynamic_tools_cfg = getattr(self._manifest, "dynamic_tools", None)
        self._dynamic_tool_factory = DynamicToolFactory(
            registry=self._tools,
            code_executor=self._code_executor,
            config=dynamic_tools_cfg,
            workflow_dir=self._dir,
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
                "Failed to install workflow dependencies: %s", exc.stderr.decode() if exc.stderr else str(exc)
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
        if not orch or not hasattr(orch, "graph") or not orch.graph:
            logger.warning("No orchestration graph -- nothing to run")
            return state

        levels = self._topological_levels(orch)

        # Initialize observability
        obs = ObservabilityContext.from_config(self._manifest, self._dir, run_id)

        # Start workflow trace span
        root_span = None
        if obs.tracer:
            root_span = obs.tracer.start_span("workflow.run", attributes={
                "workflow.name": self.name,
                "run_id": run_id,
            })
        if obs.audit:
            obs.audit.record("workflow.start", details={"task": task, "run_id": run_id})

        logger.info(
            "Running workflow '%s' [run_id=%s] with %d agents in %d levels",
            self.name, run_id, sum(len(l) for l in levels), len(levels),
        )

        workflow_start = time.monotonic()

        for level_idx, level in enumerate(levels):
            level_str = ", ".join(level)
            parallel = " (parallel)" if len(level) > 1 else ""
            logger.info("Level %d: [%s]%s", level_idx, level_str, parallel)

            for agent_id in level:
                node = self._get_node(orch, agent_id)
                if node and not node.enabled:
                    logger.info("  Skipping disabled agent: %s", agent_id)
                    continue

                # Evaluate when condition
                if not self._evaluate_when(node, state):
                    logger.info("  Skipping agent %s: when condition not met", agent_id)
                    if obs.audit:
                        obs.audit.record("agent.skipped", agent_id, details={"reason": "when_condition"})
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
                        state[agent_id] = {"error": "Circuit breaker open", "confidence": 0.0}
                        continue

                # Set current agent for tool access control
                self._tools._current_agent_id = agent_id

                # Execute agent with retry
                agent_dir = self._dir / "agents" / agent_id
                result = self._run_agent_with_retry(
                    agent_id, agent_dir, task, state, node, obs,
                    root_span_id=root_span,
                )
                state.update(result)

                # Record rate limit usage
                if self._security.rate_limiter:
                    self._security.rate_limiter.record(agent_id)

                # State persistence checkpoint
                try:
                    self._state_persistence.save_checkpoint(agent_id, state)
                except Exception as exc:
                    logger.warning("Failed to save checkpoint for %s: %s", agent_id, exc)

        # Finalize
        workflow_duration = time.monotonic() - workflow_start
        if obs.tracer and root_span:
            obs.tracer.end_span(root_span, status="ok", attributes={
                "duration_s": round(workflow_duration, 2),
                "agents_executed": sum(len(l) for l in levels),
            })
        if obs.metrics:
            obs.metrics.histogram("workflow.duration_s", workflow_duration,
                                  labels={"workflow": self.name})
        if obs.audit:
            obs.audit.record("workflow.complete", details={
                "run_id": run_id,
                "duration_s": round(workflow_duration, 2),
            })

        # Flush observability
        obs.flush_all()

        # Clean up dynamic tools
        if self._dynamic_tool_factory.enabled:
            self._dynamic_tool_factory.cleanup()

        # Save final state
        try:
            self._state_persistence.save_final(state)
        except Exception as exc:
            logger.warning("Failed to save final state: %s", exc)

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
                    obs.tracer.end_span(agent_span, status="error",
                                        attributes={"error": "dir_not_found"})
                if node and node.on_failure == "abort":
                    raise RuntimeError(f"Agent directory not found: {agent_dir}")
                return {agent_id: {"error": "Agent directory not found", "confidence": 0.0}}

            try:
                agent = StandaloneAgent(
                    agent_dir, self._dir,
                    llm=self._llm,
                    tool_registry=self._tools,
                )
                result = agent.run(task, state)
                agent_duration = time.monotonic() - agent_start

                # Success
                if obs.tracer and agent_span:
                    obs.tracer.end_span(agent_span, status="ok", attributes={
                        "duration_s": round(agent_duration, 2),
                    })
                if obs.metrics:
                    obs.metrics.histogram("agent.duration_s", agent_duration,
                                          labels={"agent": agent_id})
                    obs.metrics.increment("agent.executions", labels={"agent": agent_id, "status": "ok"})
                if obs.audit:
                    agent_result = result.get(agent_id, {})
                    obs.audit.record("agent.complete", agent_id, details={
                        "duration_s": round(agent_duration, 2),
                        "confidence": agent_result.get("confidence", "N/A"),
                    })
                if self._security.circuit_breaker:
                    self._security.circuit_breaker.record_success()

                logger.info("  Completed: %s (%.1fs)", agent_id, agent_duration)

                # Memory auto-write
                self._auto_write_memory(agent_id, result.get(agent_id, {}))

                return result

            except Exception as exc:
                agent_duration = time.monotonic() - agent_start
                logger.error("  Failed: %s -- %s (attempt %d/%d)",
                             agent_id, exc, attempt + 1, max_retries + 1)

                if obs.tracer and agent_span:
                    obs.tracer.end_span(agent_span, status="error",
                                        attributes={"error": str(exc)})
                if obs.metrics:
                    obs.metrics.increment("agent.executions",
                                          labels={"agent": agent_id, "status": "error"})
                if obs.audit:
                    obs.audit.record("agent.error", agent_id, details={
                        "error": str(exc), "attempt": attempt,
                    })
                if self._security.circuit_breaker:
                    self._security.circuit_breaker.record_failure()

                # Retry?
                if attempt < max_retries:
                    delay = retry_delay * (2 ** attempt)
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
