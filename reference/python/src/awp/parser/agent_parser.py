"""Parser for agent.awp.yaml -> AWPAgent."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from ..models.agent import AWPAgent
from ..models.capabilities import AgentCapabilities
from ..models.memory import MemoryConfig
from .template import resolve_templates


def parse_agent(
    path: str | Path,
    manifest_context: dict[str, Any] | None = None,
) -> AWPAgent:
    """Parse an agent.awp.yaml file into an AWPAgent model.

    Args:
        path: Path to agent.awp.yaml file.
        manifest_context: Optional context from the manifest for template resolution.

    Returns:
        Validated AWPAgent instance.

    Raises:
        FileNotFoundError: If the file doesn't exist.
        yaml.YAMLError: If YAML is malformed.
        pydantic.ValidationError: If schema validation fails.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Agent config not found: {path}")

    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"Agent config must be a YAML mapping, got {type(raw).__name__}")

    # Resolve templates with manifest context if provided
    context = manifest_context or {}
    resolved = resolve_templates(raw, context)

    # Parse typed sub-sections
    agent_data = dict(resolved)

    if "capabilities" in agent_data:
        agent_data["capabilities"] = AgentCapabilities(**agent_data["capabilities"])
    if "memory" in agent_data:
        agent_data["memory"] = MemoryConfig(**agent_data["memory"])

    return AWPAgent(**agent_data)
