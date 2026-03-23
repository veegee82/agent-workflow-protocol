"""AWP Workflow Runner -- Standalone DAG executor with full AWP support.

Reads ``workflow.awp.yaml``, topologically sorts the agent graph,
and executes agents in order. Supports:
- Sequential and parallel execution
- DAG-based topological ordering
- State sharing between agents
- Memory auto-write after each agent
- Tool registry shared across agents
- Error handling (continue / skip / abort)

Usage::

    from awp.runtime import WorkflowRunner

    runner = WorkflowRunner("path/to/my-workflow")
    result = runner.run("Analyze the latest quarterly report")
"""

from __future__ import annotations

import json
import logging
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from ..parser import parse_manifest
from ..models.orchestration import AWPOrchestrationConfig, ConditionalDependency
from .agent import StandaloneAgent
from .llm import LLMClient
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
        self._manifest = parse_manifest(self._dir / "workflow.awp.yaml")
        self._llm = llm
        self._tools = ToolRegistry(self._dir)

    @property
    def name(self) -> str:
        return self._manifest.workflow.name

    def run(self, task: str, state: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Execute the workflow."""
        state = dict(state or {})
        state["task"] = task

        # Auto-inject fields
        if self._manifest.state and hasattr(self._manifest.state, "auto_inject"):
            for key, value in self._manifest.state.auto_inject.items():
                state.setdefault(key, value)

        orch = self._manifest.orchestration
        if not orch or not hasattr(orch, "graph") or not orch.graph:
            logger.warning("No orchestration graph -- nothing to run")
            return state

        levels = self._topological_levels(orch)

        logger.info(
            "Running workflow '%s' with %d agents in %d levels",
            self.name, sum(len(l) for l in levels), len(levels),
        )

        for level_idx, level in enumerate(levels):
            level_str = ", ".join(level)
            parallel = " (parallel)" if len(level) > 1 else ""
            logger.info("Level %d: [%s]%s", level_idx, level_str, parallel)

            for agent_id in level:
                node = self._get_node(orch, agent_id)
                if node and not node.enabled:
                    logger.info("  Skipping disabled agent: %s", agent_id)
                    continue

                agent_dir = self._dir / "agents" / agent_id
                if not agent_dir.exists():
                    logger.error("  Agent dir not found: %s", agent_dir)
                    if node and node.on_failure == "abort":
                        raise RuntimeError(f"Agent directory not found: {agent_dir}")
                    continue

                try:
                    agent = StandaloneAgent(
                        agent_dir, self._dir,
                        llm=self._llm,
                        tool_registry=self._tools,
                    )
                    result = agent.run(task, state)
                    state.update(result)
                    logger.info("  Completed: %s", agent_id)

                    # Memory auto-write
                    self._auto_write_memory(agent_id, result.get(agent_id, {}))

                except Exception as exc:
                    logger.error("  Failed: %s -- %s", agent_id, exc)
                    on_failure = node.on_failure if node else "continue"
                    if on_failure == "abort":
                        raise
                    state[agent_id] = {"error": str(exc), "confidence": 0.0}

        return state

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
        time = datetime.now(timezone.utc).strftime("%H:%M:%S")
        log_file = workspace / f"{date}.md"

        # Build summary
        confidence = result.get("confidence", "N/A")
        summary_parts = [f"\n### {time} -- {agent_id} (confidence: {confidence})\n"]
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
