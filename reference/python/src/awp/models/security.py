"""AWP Security models (Layer 5 Enterprise) — Circuit Breaker, Rate Limiting."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class CircuitBreakerConfig(BaseModel):
    """Circuit breaker configuration per agent or global."""
    enabled: bool = False
    failure_threshold: int = 5  # Failures before opening
    reset_timeout: int = 60  # Seconds before half-open
    half_open_max_calls: int = 1  # Calls allowed in half-open
    monitored_exceptions: list[str] = Field(
        default_factory=lambda: ["TimeoutError", "ConnectionError"]
    )


class RateLimitConfig(BaseModel):
    """Rate limiting configuration."""
    enabled: bool = False
    max_calls_per_minute: int = 60
    max_tokens_per_minute: int = 100000
    per_agent: bool = False  # Per-agent or global
    burst_multiplier: float = 1.5


class AgentAccessPolicy(BaseModel):
    """Per-agent access policy."""
    allowed_tools: list[str] = Field(default_factory=list)
    denied_tools: list[str] = Field(default_factory=list)
    allowed_channels: list[str] = Field(default_factory=list)
    max_state_writes: Optional[int] = None
    filesystem_access: str = "read"  # none | read | write | full


class AccessControlConfig(BaseModel):
    """Access control for tools and resources."""
    default_policy: str = "allow"  # allow | deny
    agent_policies: dict[str, AgentAccessPolicy] = Field(default_factory=dict)


class SecurityConfig(BaseModel):
    """Complete security configuration (Layer 5 Enterprise)."""
    circuit_breaker: CircuitBreakerConfig = Field(
        default_factory=CircuitBreakerConfig
    )
    rate_limit: RateLimitConfig = Field(default_factory=RateLimitConfig)
    access_control: Optional[AccessControlConfig] = None
    secrets_backend: str = "env"  # env | vault | aws_secrets
    audit_security_events: bool = True
