"""AWP Manifest model — Root document (Layer 0) for workflow.awp.yaml."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field

from .common import SemVer, WorkflowName


class ToolDependency(BaseModel):
    """External tool package dependency."""
    package: str
    version: str  # SemVer range
    registry: str = "default"


class WorkflowDependency(BaseModel):
    """Sub-workflow dependency."""
    name: str
    ref: str  # "github:org/repo@v1" | "awp-registry:name@v1"
    alias: Optional[str] = None


class SkillDependency(BaseModel):
    """External skill dependency."""
    name: str
    ref: str


class Dependencies(BaseModel):
    """External dependencies section."""
    tools: list[ToolDependency] = Field(default_factory=list)
    workflows: list[WorkflowDependency] = Field(default_factory=list)
    skills: list[SkillDependency] = Field(default_factory=list)
    python: list[str] = Field(default_factory=list)


class EnvVar(BaseModel):
    """Required environment variable."""
    name: str
    description: str = ""
    sensitive: bool = False


class EnvConfig(BaseModel):
    """Environment variable configuration."""
    required: list[EnvVar] = Field(default_factory=list)
    defaults: dict[str, str] = Field(default_factory=dict)


class RuntimeRequirements(BaseModel):
    """Runtime requirements for the workflow."""
    min_awp_version: Optional[str] = None
    python: str = ">=3.10"
    required_providers: list[str] = Field(default_factory=list)
    required_capabilities: list[str] = Field(default_factory=list)


class LLMSettings(BaseModel):
    """Global LLM settings."""
    default_provider: str = "openrouter"
    models: dict[str, str] = Field(default_factory=dict)
    temperature: float = 0.2


class WorkflowSettings(BaseModel):
    """Global workflow settings."""
    llm: LLMSettings = Field(default_factory=LLMSettings)
    custom: dict[str, Any] = Field(default_factory=dict)


class WorkflowMetadata(BaseModel):
    """Workflow metadata section."""
    name: WorkflowName
    version: SemVer
    description: str = Field(..., max_length=500)
    author: Optional[str] = None
    license: Optional[str] = None
    tags: list[str] = Field(default_factory=list)
    homepage: Optional[str] = None
    repository: Optional[str] = None
    runtime: RuntimeRequirements = Field(default_factory=RuntimeRequirements)
    dependencies: Dependencies = Field(default_factory=Dependencies)
    env: EnvConfig = Field(default_factory=EnvConfig)
    settings: WorkflowSettings = Field(default_factory=WorkflowSettings)


class DynamicToolsConfig(BaseModel):
    """Configuration for runtime dynamic tool creation."""
    enabled: bool = False
    persist: bool = False
    max_total: int = 50
    allowed_namespaces: list[str] = Field(default_factory=lambda: ["dynamic"])
    code_review: bool = False


class AWPManifest(BaseModel):
    """Root model for workflow.awp.yaml (Layer 0).

    Contains workflow metadata, orchestration graph, state management,
    communication, memory, observability, custom tools, and security config.
    """
    awp: SemVer
    workflow: WorkflowMetadata

    # Inline sections from other layers (all optional at manifest level)
    orchestration: Optional[Any] = None  # AWPOrchestrationConfig (resolved at parse time)
    state: Optional[Any] = None  # StateModel
    memory: Optional[Any] = None  # MemoryConfig
    communication: Optional[Any] = None  # CommunicationConfig
    observability: Optional[Any] = None  # ObservabilityConfig
    custom_tools: Optional[Any] = None  # CustomToolsConfig
    dynamic_tools: Optional[DynamicToolsConfig] = None
    security: Optional[Any] = None  # SecurityConfig

    # Top-level env and settings (alternative to inside workflow)
    env: Optional[Any] = None
    settings: Optional[Any] = None

    model_config = {"extra": "allow"}
