"""Analyst agent -- uses dynamically created scoring tools to rank items."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from awp.runtime.agent import StandaloneAgent
from awp.runtime.llm import LLMClient
from awp.runtime.tools import ToolRegistry


class Agent(StandaloneAgent):
    """Analyst agent -- uses dynamically created scoring tools to rank items."""

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
