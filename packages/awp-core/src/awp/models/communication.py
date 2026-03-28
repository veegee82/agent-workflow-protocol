"""AWP Communication models (Layer 3) — Message Bus, Channels, Patterns."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class BusConfig(BaseModel):
    """Message bus configuration."""

    type: str = "internal"  # internal | redis | nats | kafka | rabbitmq
    persistence: str = "run"  # run | session | permanent
    delivery: str = "at_least_once"  # at_most_once | at_least_once | exactly_once
    ordering: str = "fifo"  # fifo | priority | timestamp
    max_message_size_kb: int = 256
    max_message_size: int = 65536  # Alternative: bytes
    config: dict[str, Any] = Field(default_factory=dict)


class ChannelACL(BaseModel):
    """Access control for a channel."""

    publishers: list[str] = Field(default_factory=list)  # Agent IDs or "*"
    subscribers: list[str] = Field(default_factory=list)


class Channel(BaseModel):
    """Communication channel definition."""

    name: str
    type: str = "direct"  # direct | broadcast | topic | request_response
    description: str = ""
    acl: Optional[ChannelACL] = None
    config: dict[str, Any] = Field(default_factory=dict)


class PatternConfig(BaseModel):
    """Communication pattern configuration."""

    type: str  # request_response | pub_sub | pipeline | scatter_gather
    timeout: int = 30
    max_rounds: int = 5
    config: dict[str, Any] = Field(default_factory=dict)


class CommunicationConfig(BaseModel):
    """Complete communication configuration (Layer 3)."""

    bus: BusConfig = Field(default_factory=BusConfig)
    channels: list[Channel] = Field(default_factory=list)
    patterns: list[PatternConfig] = Field(default_factory=list)
    default_channel: str = "direct"


class MessageMetadata(BaseModel):
    """Message metadata."""

    priority: str = "normal"  # normal | high | critical
    ttl: Optional[int] = None  # Time-to-live in seconds
    requires_ack: bool = False
    trace_id: Optional[str] = None
    tags: list[str] = Field(default_factory=list)


class MessageEnvelope(BaseModel):
    """Standardized AWP message envelope.

    Every message on the bus uses this envelope format.
    """

    id: str  # UUID v7
    timestamp: str  # ISO 8601
    version: str = "1.0.0"
    from_agent: str = Field(..., alias="from")
    to: str  # Agent ID or "*" for broadcast
    channel: str = "direct"
    reply_to: Optional[str] = None
    type: str = "event"  # request | response | event | error | ack
    correlation_id: Optional[str] = None
    content_type: str = "application/json"
    content: Any = None
    metadata: Optional[MessageMetadata] = None

    model_config = {"populate_by_name": True}
