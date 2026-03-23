"""AWP Orchestration models (Layer 5) — DAG, execution, loops, fan-out."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field

from .common import AgentId


class ConditionalDependency(BaseModel):
    """Dependency with condition."""
    agent: AgentId
    condition: str = "success"  # success | failure | always | expression


class LoopConfig(BaseModel):
    """Loop execution configuration for an agent."""
    enabled: bool = False
    max_iterations: int = 5
    until_condition: str = ""  # Safe Python expression
    mode: str = "standard"  # standard | interactive
    poll_interval: float = 2.0


class FanOutConfig(BaseModel):
    """Fan-out configuration for parallel agent spawning."""
    enabled: bool = False
    source_field: str = ""  # State field containing items
    agent_template: str = ""  # Agent to spawn per item
    max_parallel: int = 4
    aggregation: str = "merge"  # merge | concat | custom


class GraphNode(BaseModel):
    """Single node in the orchestration DAG."""
    id: AgentId
    agent: str  # Agent directory name
    enabled: bool = True
    depends_on: list[str | ConditionalDependency] = Field(default_factory=list)
    share_input: dict[str, list[str]] = Field(default_factory=dict)
    description: str = ""
    on_failure: str = "continue"  # continue | skip | abort
    loop: Optional[LoopConfig] = None
    fan_out: Optional[FanOutConfig] = None
    timeout: Optional[int] = None  # Override per-agent timeout
    retry: int = 0


class ErrorHandling(BaseModel):
    """Error handling configuration."""
    default: str = "continue"  # continue | stop | retry
    max_retries: int = 1
    retry_delay: float = 2.0
    fallback_agent: Optional[str] = None


class TimeoutConfig(BaseModel):
    """Timeout configuration."""
    per_agent: int = 120
    total: int = 300


class AWPExecutionConfig(BaseModel):
    """Execution configuration."""
    mode: str = "parallel"  # sequential | parallel | conditional
    timeout: TimeoutConfig = Field(default_factory=TimeoutConfig)
    max_parallel_agents: int = 4
    error_handling: ErrorHandling = Field(default_factory=ErrorHandling)


class SubworkflowRef(BaseModel):
    """Reference to a sub-workflow."""
    name: str
    ref: str  # Path or registry reference
    input_mapping: dict[str, str] = Field(default_factory=dict)
    output_mapping: dict[str, str] = Field(default_factory=dict)


class AWPOrchestrationConfig(BaseModel):
    """Complete orchestration configuration (Layer 5)."""
    engine: str = "dag"
    graph: list[GraphNode] = Field(default_factory=list)
    execution: AWPExecutionConfig = Field(default_factory=AWPExecutionConfig)
    subworkflows: list[SubworkflowRef] = Field(default_factory=list)
