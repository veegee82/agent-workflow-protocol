"""Shared types for AWP models."""

from __future__ import annotations

import re
from typing import Annotated

from pydantic import AfterValidator


def _validate_semver(v: str) -> str:
    pattern = r"^\d+\.\d+\.\d+(-[a-zA-Z0-9.]+)?(\+[a-zA-Z0-9.]+)?$"
    if not re.match(pattern, v):
        raise ValueError(f"Invalid SemVer: {v}")
    return v


def _validate_agent_id(v: str) -> str:
    pattern = r"^[a-z][a-z0-9_]{0,46}[a-z0-9]$"
    if len(v) == 1:
        if not re.match(r"^[a-z]$", v):
            raise ValueError(f"Invalid AgentId: {v}")
    elif not re.match(pattern, v):
        raise ValueError(f"Invalid AgentId: {v}")
    return v


def _validate_tool_fqn(v: str) -> str:
    pattern = r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$"
    if not re.match(pattern, v):
        raise ValueError(f"Invalid ToolFQN: {v}")
    return v


def _validate_workflow_name(v: str) -> str:
    pattern = r"^[a-z][a-z0-9_-]{0,62}[a-z0-9]$"
    if len(v) == 1:
        if not re.match(r"^[a-z]$", v):
            raise ValueError(f"Invalid workflow name: {v}")
    elif not re.match(pattern, v):
        raise ValueError(f"Invalid workflow name: {v}")
    return v


SemVer = Annotated[str, AfterValidator(_validate_semver)]
AgentId = Annotated[str, AfterValidator(_validate_agent_id)]
ToolFQN = Annotated[str, AfterValidator(_validate_tool_fqn)]
WorkflowName = Annotated[str, AfterValidator(_validate_workflow_name)]

# Reserved tool namespaces that custom tools must not use
RESERVED_TOOL_NAMESPACES = frozenset(
    {
        "web",
        "http",
        "file",
        "shell",
        "terminal",
        "agent",
        "memory",
        "arithmetic",
        "numpy",
        "matplot",
        "pandas",
        "doc",
        "sklearn",
    }
)
