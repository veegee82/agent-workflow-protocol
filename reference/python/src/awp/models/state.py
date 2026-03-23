"""AWP State models (Layer 4) — State management, sharing, persistence."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class PersistenceConfig(BaseModel):
    """State persistence configuration."""
    enabled: bool = True
    path: str = "data/state"
    format: str = "json"  # json | msgpack | pickle
    snapshot_on_completion: bool = True


class SharingRule(BaseModel):
    """Sharing rule for state fields between agents."""
    from_agent: str
    fields: list[str]
    to_agents: list[str] = Field(default_factory=list)  # Empty = all dependents
    transform: Optional[str] = None  # Optional transformation expression


class SharingConfig(BaseModel):
    """State sharing configuration."""
    strategy: str = "full"  # full | selective | isolated
    rules: list[SharingRule] = Field(default_factory=list)
    validation: str = "warn"  # strict | warn | none


class StateModel(BaseModel):
    """Complete state management configuration (Layer 4)."""
    model: str = "shared_dict"  # shared_dict | event_sourced | cqrs
    persistence: PersistenceConfig = Field(default_factory=PersistenceConfig)
    sharing: SharingConfig = Field(default_factory=SharingConfig)
    required_fields: list[str] = Field(default_factory=list)
    auto_inject: dict[str, Any] = Field(default_factory=dict)
    max_state_size_mb: int = 50
