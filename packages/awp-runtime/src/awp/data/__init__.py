"""AWP Data — Programmatic agent workflow for arbitrary data + tasks.

Usage::

    from awp.data import AgentWorkflow

    result = AgentWorkflow(
        inputs={"data": df, "config": {"threshold": 0.8}},
        task="Analyze trends and create visualizations",
        model="openrouter/anthropic/claude-sonnet-4",
    ).run()
"""

from awp.data.workflow import AgentWorkflow

__all__ = ["AgentWorkflow"]
