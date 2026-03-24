"""AWP Agent Identity model (Layer 1) for agent.awp.yaml."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field

from .common import AgentId, SemVer


class AgentIdentity(BaseModel):
    """Agent identity section."""
    id: AgentId
    role: str
    description: str
    version: SemVer = "1.0.0"
    tags: list[str] = Field(default_factory=list)


class AgentRuntime(BaseModel):
    """Runtime constraints for skill-build compatibility."""
    class_name: str = "Agent"  # R3: Must be "Agent"
    strategy_folder: str = "workflow"


class ModelParameters(BaseModel):
    """LLM model parameters."""
    temperature: float = 0.0
    max_tokens: Optional[int] = None
    top_p: float = 1.0


class ReasoningConfig(BaseModel):
    """Chain-of-thought configuration."""
    enabled: bool = True
    effort: str = "medium"  # low | medium | high
    force: bool = True


class ModelConfig(BaseModel):
    """LLM model configuration.

    When ``name`` is empty or not set, the runtime resolves the model from
    the ``LLM_MODEL`` environment variable (set interactively via the run
    wizard or in the shell environment).
    """
    provider: Optional[str] = None  # Inherits from manifest if None
    name: str = ""  # Empty = resolve from LLM_MODEL env var at runtime
    fallback: Optional[str] = None
    parameters: ModelParameters = Field(default_factory=ModelParameters)
    reasoning: ReasoningConfig = Field(default_factory=ReasoningConfig)


class PromptConfig(BaseModel):
    """Prompt architecture configuration."""
    system: str  # File path relative to agent dir
    user_template: Optional[str] = None
    additional: list[str] = Field(default_factory=list)
    variables: dict[str, str] = Field(default_factory=dict)
    injection_order: list[str] = Field(
        default_factory=lambda: [
            "system_prompt", "skills", "memory",
            "previous_agents", "user_prompt", "context",
        ]
    )


class OutputField(BaseModel):
    """Single field in the output contract."""
    type: str
    description: str = ""
    shareable: bool = True
    sensitive: bool = False
    required: bool = False
    items: Optional[dict[str, Any]] = None
    minimum: Optional[float] = None
    maximum: Optional[float] = None
    max_length: Optional[int] = None
    default: Optional[Any] = None
    examples: list[Any] = Field(default_factory=list)


class OutputValidation(BaseModel):
    """Output validation configuration."""
    mode: str = "strict"  # strict | lenient | none
    on_invalid: str = "retry"  # retry | skip | abort | use_partial
    max_retries: int = 2
    retry_prompt: Optional[str] = None


class OutputConfig(BaseModel):
    """Output contract configuration."""
    format: str = "json"  # json | text | markdown
    schema_path: Optional[str] = Field(None, alias="schema")
    schema_description: Optional[str] = None
    contract: dict[str, OutputField] = Field(default_factory=dict)
    validation: OutputValidation = Field(default_factory=OutputValidation)

    model_config = {"populate_by_name": True}


class VisionConfig(BaseModel):
    """Vision capabilities configuration."""
    enabled: bool = False
    model: Optional[str] = None
    supported_formats: list[str] = Field(
        default_factory=lambda: ["png", "jpg", "webp", "pdf"]
    )
    max_images: int = 10
    max_size_mb: int = 20


class PreprocessorConfig(BaseModel):
    """Preprocessor configuration."""
    enabled: bool = False
    pipeline: str = "default"
    steps: list[Any] = Field(default_factory=list)

    model_config = {"extra": "allow"}


class AWPAgent(BaseModel):
    """Root model for agent.awp.yaml (Layer 1).

    Defines agent identity, LLM configuration, prompt architecture,
    output contract, capabilities, vision, and preprocessing.
    """
    awp_agent: SemVer
    identity: AgentIdentity
    runtime: AgentRuntime = Field(default_factory=AgentRuntime)
    model: ModelConfig
    prompt: PromptConfig
    output: OutputConfig = Field(default_factory=OutputConfig)
    vision: VisionConfig = Field(default_factory=VisionConfig)
    preprocessor: PreprocessorConfig = Field(default_factory=PreprocessorConfig)

    # Capabilities (Layer 2) — inline in agent.awp.yaml
    capabilities: Optional[Any] = None  # Resolved at parse time
    # Memory override at agent level
    memory: Optional[Any] = None
