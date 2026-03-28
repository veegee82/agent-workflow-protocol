"""AWP Capabilities models (Layer 2) — Tools, Skills, Data Sources."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class ToolsCapability(BaseModel):
    """Tool access configuration for an agent."""

    enabled: bool = False
    max_calls: int = 0
    allowed: list[str] = Field(default_factory=list)  # Empty = all tools
    denied: list[str] = Field(default_factory=list)
    namespaces: list[str] = Field(default_factory=list)
    max_parallel: int = 16
    timeout_per_call: int = 30
    tool_choice: Optional[str] = (
        None  # "auto" | "none" | "required" | specific tool name
    )
    parallel_calls: Optional[bool] = (
        None  # None = provider default, True/False = explicit
    )


class SkillsCapability(BaseModel):
    """Skills configuration for an agent."""

    agent_skills: list[str] = Field(default_factory=list)  # Agent-level skill refs
    project_skills: bool = True  # Load project-level skills


class DataSourceConfig(BaseModel):
    """Data source configuration (e.g., RAG, HTTP, file)."""

    name: str = ""
    type: str = ""  # rag | http | file | database | web | api | memory
    description: str = ""
    config: dict = Field(default_factory=dict)


class SandboxConfig(BaseModel):
    """Sandbox configuration for code execution."""

    enabled: bool = False
    type: str = "subprocess"  # subprocess | docker | venv | wasm | isolate | none
    runtime: str = "python"
    timeout: int = 30
    max_memory_mb: int = 256
    max_cpu_seconds: int = 30
    max_output_bytes: int = 1_048_576
    allowed_modules: list[str] = Field(default_factory=list)
    network_access: bool = False
    packages: list[str] = Field(default_factory=list)  # pip packages to pre-install
    image: str = "awp-sandbox-python"  # Docker image name (docker type only)
    pip_install: bool = False  # Allow runtime pip install for missing packages

    model_config = {"extra": "allow"}


class CodeModeConfig(BaseModel):
    """Code Mode configuration (Layer 2 extension)."""

    enabled: bool = False
    language: str = "python"  # python | typescript | javascript
    sdk_surface: dict = Field(default_factory=dict)
    tool_creation: bool = False
    tool_creation_namespace: str = "dynamic"
    max_tools: int = 10

    model_config = {"extra": "allow"}


class AgentCapabilities(BaseModel):
    """Complete capabilities configuration for an agent (Layer 2)."""

    tools: ToolsCapability = Field(default_factory=ToolsCapability)
    skills: SkillsCapability = Field(default_factory=SkillsCapability)
    data_sources: list[DataSourceConfig] = Field(default_factory=list)
    sandbox: Optional[SandboxConfig] = None
    codemode: Optional[CodeModeConfig] = None

    model_config = {"extra": "allow"}
