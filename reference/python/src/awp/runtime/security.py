"""AWP Security -- Circuit breaker, rate limiting, and access control.

All implementations are in-memory with no external dependencies.
Production deployments can swap in Redis-backed or distributed versions.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Circuit Breaker
# ---------------------------------------------------------------------------

class CircuitBreaker:
    """Simple in-memory circuit breaker.

    States: closed (normal) → open (blocking) → half_open (testing).
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        reset_timeout: float = 60.0,
        half_open_max_calls: int = 1,
    ) -> None:
        self._failure_threshold = failure_threshold
        self._reset_timeout = reset_timeout
        self._half_open_max_calls = half_open_max_calls
        self._failure_count = 0
        self._state = "closed"  # closed | open | half_open
        self._last_failure_time: float = 0.0
        self._half_open_calls = 0

    @property
    def state(self) -> str:
        self._maybe_transition()
        return self._state

    def check(self) -> bool:
        """Return True if a call is allowed."""
        self._maybe_transition()
        if self._state == "closed":
            return True
        if self._state == "half_open":
            if self._half_open_calls < self._half_open_max_calls:
                self._half_open_calls += 1
                return True
            return False
        return False  # open

    def record_success(self) -> None:
        """Record a successful call."""
        if self._state == "half_open":
            self._state = "closed"
            self._failure_count = 0
            self._half_open_calls = 0
            logger.info("Circuit breaker: half_open → closed")
        elif self._state == "closed":
            self._failure_count = 0

    def record_failure(self) -> None:
        """Record a failed call."""
        self._failure_count += 1
        self._last_failure_time = time.monotonic()
        if self._state == "half_open":
            self._state = "open"
            logger.warning("Circuit breaker: half_open → open")
        elif self._failure_count >= self._failure_threshold:
            self._state = "open"
            logger.warning(
                "Circuit breaker: closed → open (failures=%d)", self._failure_count
            )

    def _maybe_transition(self) -> None:
        """Check if open → half_open transition should happen."""
        if self._state == "open":
            elapsed = time.monotonic() - self._last_failure_time
            if elapsed >= self._reset_timeout:
                self._state = "half_open"
                self._half_open_calls = 0
                logger.info("Circuit breaker: open → half_open (timeout elapsed)")


# ---------------------------------------------------------------------------
# Rate Limiter
# ---------------------------------------------------------------------------

class RateLimiter:
    """Sliding window rate limiter per agent."""

    def __init__(
        self,
        max_calls_per_minute: int = 60,
        per_agent: bool = True,
    ) -> None:
        self._max_calls = max_calls_per_minute
        self._per_agent = per_agent
        self._windows: dict[str, deque[float]] = {}

    def check(self, agent_id: str = "global") -> bool:
        """Return True if a call is allowed within the rate limit."""
        key = agent_id if self._per_agent else "global"
        self._purge(key)
        window = self._windows.get(key, deque())
        return len(window) < self._max_calls

    def record(self, agent_id: str = "global") -> None:
        """Record a call timestamp."""
        key = agent_id if self._per_agent else "global"
        self._windows.setdefault(key, deque()).append(time.monotonic())

    def _purge(self, key: str) -> None:
        """Remove entries older than 60 seconds."""
        window = self._windows.get(key)
        if not window:
            return
        cutoff = time.monotonic() - 60.0
        while window and window[0] < cutoff:
            window.popleft()


# ---------------------------------------------------------------------------
# Access Controller
# ---------------------------------------------------------------------------

class AccessController:
    """Enforce tool access policies per agent."""

    def __init__(
        self,
        default_policy: str = "allow",
        rules: Optional[list[dict[str, Any]]] = None,
    ) -> None:
        self._default_policy = default_policy
        # Build lookup: agent_id → set of denied tools
        self._denied: dict[str, set[str]] = {}
        for rule in (rules or []):
            agent = rule.get("agent", "")
            denied = rule.get("deny_tools", [])
            if agent and denied:
                self._denied[agent] = set(denied)

    def is_allowed(self, agent_id: str, tool_name: str) -> bool:
        """Check if an agent is allowed to use a tool."""
        denied = self._denied.get(agent_id, set())
        if tool_name in denied:
            logger.warning(
                "Access denied: agent '%s' cannot use tool '%s'", agent_id, tool_name
            )
            return False
        return self._default_policy == "allow"


# ---------------------------------------------------------------------------
# SecurityContext
# ---------------------------------------------------------------------------

@dataclass
class SecurityContext:
    """Composed security subsystems."""

    circuit_breaker: Optional[CircuitBreaker] = None
    rate_limiter: Optional[RateLimiter] = None
    access_controller: Optional[AccessController] = None

    @classmethod
    def from_config(cls, manifest: Any) -> SecurityContext:
        """Create context from manifest security configuration."""
        sec_cfg = getattr(manifest, "security", None)
        if not sec_cfg:
            return cls()

        cb = None
        rl = None
        ac = None

        # Circuit breaker
        if hasattr(sec_cfg, "circuit_breaker"):
            cb_cfg = sec_cfg.circuit_breaker
            if hasattr(cb_cfg, "enabled") and cb_cfg.enabled:
                cb = CircuitBreaker(
                    failure_threshold=getattr(cb_cfg, "failure_threshold", 5),
                    reset_timeout=getattr(cb_cfg, "reset_timeout", 60.0),
                    half_open_max_calls=getattr(cb_cfg, "half_open_max_calls", 1),
                )

        # Rate limiter
        if hasattr(sec_cfg, "rate_limit"):
            rl_cfg = sec_cfg.rate_limit
            if hasattr(rl_cfg, "enabled") and rl_cfg.enabled:
                rl = RateLimiter(
                    max_calls_per_minute=getattr(rl_cfg, "max_calls_per_minute", 60),
                    per_agent=getattr(rl_cfg, "per_agent", True),
                )

        # Access control
        if hasattr(sec_cfg, "access_control"):
            ac_cfg = sec_cfg.access_control
            if hasattr(ac_cfg, "enabled") and ac_cfg.enabled:
                rules = []
                if hasattr(ac_cfg, "rules"):
                    for rule in ac_cfg.rules:
                        if isinstance(rule, dict):
                            rules.append(rule)
                        else:
                            rules.append(rule.model_dump() if hasattr(rule, "model_dump") else dict(rule))
                ac = AccessController(
                    default_policy=getattr(ac_cfg, "default_policy", "allow"),
                    rules=rules,
                )

        return cls(circuit_breaker=cb, rate_limiter=rl, access_controller=ac)
