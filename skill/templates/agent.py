from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from awp.runtime.agent import StandaloneAgent
from awp.runtime.llm import LLMClient
from awp.runtime.tools import ToolRegistry


class Agent(StandaloneAgent):
    """{{AGENT_DESCRIPTION}}"""

    def __init__(
        self,
        agent_dir: str | Path | None = None,
        workflow_dir: str | Path | None = None,
        llm: Optional[LLMClient] = None,
        tool_registry: Optional[ToolRegistry] = None,
    ) -> None:
        super().__init__(
            agent_dir=agent_dir or Path(__file__).parent,
            workflow_dir=workflow_dir or Path(__file__).parents[2],
            llm=llm,
            tool_registry=tool_registry,
        )

    # -- Override hooks (all optional) ------------------------------------
    #
    # def run(self, task: str, state: Dict[str, Any]) -> Dict[str, Any]:
    #     """Full custom logic — replaces the default LLM call pipeline."""
    #     return super().run(task, state)
    #
    # def _build_system_prompt(self) -> str:
    #     """Customise the system prompt sent to the LLM."""
    #     return super()._build_system_prompt()
    #
    # def _build_user_message(self, task: str, state: Dict[str, Any]) -> str:
    #     """Customise the user message sent to the LLM."""
    #     return super()._build_user_message(task, state)
