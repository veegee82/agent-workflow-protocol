"""AWP Custom Tools models — Project-local MCP tool declarations."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class ToolMeta(BaseModel):
    """Tool metadata for documentation and optimization."""

    side_effects: bool = False
    idempotent: bool = False
    deterministic: bool = False
    cost: str = "low"  # low | medium | high
    requires: list[str] = Field(default_factory=list)


class CustomToolDeclaration(BaseModel):
    """Single custom MCP tool declaration."""

    fqn: str  # "namespace.action"
    description: str
    file: str  # Python file in mcp/ or tools/
    parameters: dict[str, Any] = Field(default_factory=dict)  # JSON Schema
    returns: Optional[dict[str, Any]] = None
    meta: Optional[ToolMeta] = None


class CustomToolsConfig(BaseModel):
    """Custom MCP tools configuration in workflow.awp.yaml."""

    source_dir: str = "mcp/"
    auto_discovery: bool = True
    auto_inject: bool = True
    declarations: list[CustomToolDeclaration] = Field(default_factory=list)
    reserved_namespaces: list[str] = Field(
        default_factory=lambda: [
            "web",
            "http",
            "file",
            "shell",
            "agent",
            "memory",
            "arithmetic",
            "numpy",
            "matplot",
            "pandas",
            "doc",
            "sklearn",
        ]
    )
