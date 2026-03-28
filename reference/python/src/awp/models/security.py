"""AWP Security models (Layer 5 Enterprise) — Circuit Breaker, Rate Limiting."""

from __future__ import annotations

from typing import Any, Optional

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
    """Access control for tools and resources.

    Supports two formats:
    1. ``agent_policies`` dict: agent_id → AgentAccessPolicy
    2. ``rules`` list: [{agent, deny_tools, ...}] (enterprise style)
    """

    enabled: bool = False
    default_policy: str = "allow"  # allow | deny
    agent_policies: dict[str, AgentAccessPolicy] = Field(default_factory=dict)
    rules: list[dict[str, Any]] = Field(default_factory=list)

    model_config = {"extra": "allow"}


class SecretsConfig(BaseModel):
    """Secrets management configuration."""

    provider: str = "file"  # file | env | vault | aws_secrets
    path: str = "secrets.yaml"
    required: list[str] = Field(default_factory=list)

    model_config = {"extra": "allow"}


class SecurityConfig(BaseModel):
    """Complete security configuration (Layer 5 Enterprise)."""

    circuit_breaker: CircuitBreakerConfig = Field(default_factory=CircuitBreakerConfig)
    rate_limit: RateLimitConfig = Field(default_factory=RateLimitConfig)
    access_control: Optional[AccessControlConfig] = None
    secrets: Optional[SecretsConfig] = None
    secrets_backend: str = "env"  # env | vault | aws_secrets
    audit_security_events: bool = True

    model_config = {"extra": "allow"}

    def model_post_init(self, __context: Any) -> None:
        """Map YAML aliases: rate_limiting -> rate_limit."""
        if not self.rate_limit.enabled and hasattr(self, "__pydantic_extra__"):
            rl = (self.__pydantic_extra__ or {}).get("rate_limiting")
            if isinstance(rl, dict) and rl.get("enabled"):
                self.rate_limit = RateLimitConfig(
                    enabled=rl.get("enabled", False),
                    max_calls_per_minute=rl.get(
                        "max_calls_per_minute",
                        rl.get("max_per_minute", 60),
                    ),
                    max_tokens_per_minute=rl.get("max_tokens_per_minute", 100000),
                    per_agent=rl.get("per_agent", False),
                    burst_multiplier=rl.get("burst_multiplier", 1.5),
                )
