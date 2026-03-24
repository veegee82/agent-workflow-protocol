"""AWP Memory models (Layer 4) — Multi-tier memory system."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class LongTermMemoryConfig(BaseModel):
    """Long-term memory (MEMORY.md) configuration."""
    enabled: bool = True
    inject: bool = True  # Inject into agent prompt
    max_tokens: int = 2000
    auto_curate: bool = False
    curate_interval: str = "daily"  # daily | weekly | on_demand


class DailyLogConfig(BaseModel):
    """Daily log memory tier configuration."""
    enabled: bool = True
    auto_write: bool = True
    retention_days: int = 30


class EpisodicMemoryConfig(BaseModel):
    """Episodic memory (agent outputs) configuration."""
    enabled: bool = True
    max_entries: int = 100


class SemanticMemoryConfig(BaseModel):
    """Semantic memory (vector DB) configuration."""
    enabled: bool = False
    backend: str = "chromadb"  # chromadb | pinecone | qdrant
    collection: Optional[str] = None
    embedding_model: Optional[str] = None
    config: dict = Field(default_factory=dict)


class CurationConfig(BaseModel):
    """Memory curation configuration."""
    enabled: bool = False
    schedule: str = "after_run"  # after_run | daily | weekly
    days: int = 7

    model_config = {"extra": "allow"}


class MemoryConfig(BaseModel):
    """Complete memory configuration (Layer 4)."""
    enabled: bool = True
    workspace_dir: str = "workspace"
    long_term: LongTermMemoryConfig = Field(default_factory=LongTermMemoryConfig)
    daily_log: DailyLogConfig = Field(default_factory=DailyLogConfig)
    episodic: EpisodicMemoryConfig = Field(default_factory=EpisodicMemoryConfig)
    semantic: SemanticMemoryConfig = Field(default_factory=SemanticMemoryConfig)
    curation: CurationConfig = Field(default_factory=CurationConfig)
    search_enabled: bool = True

    model_config = {"extra": "allow"}
