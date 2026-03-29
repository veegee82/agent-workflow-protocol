"""AWP Data — Programmatic agent workflow for arbitrary data + tasks.

Usage::

    from awp.data import AgentWorkflow, ExternalTool, ExternalToolSpec, Source

    result = AgentWorkflow(
        inputs={
            "data": df,
            "config": {"threshold": 0.8},
            "remote": Source.url("https://example.com/data.csv"),
        },
        task="Analyze trends and create visualizations",
        model="openrouter/anthropic/claude-sonnet-4",
        secrets={"SERP_API_KEY": "sk-..."},
        skills=["path/to/skill.md"],
        external_tools=[my_tool_func],
    ).run()
"""

from awp.data.sources import Source
from awp.data.workflow import AgentWorkflow
from awp.runtime.external_tools import ExternalTool, ExternalToolSpec

__all__ = ["AgentWorkflow", "ExternalTool", "ExternalToolSpec", "Source"]
