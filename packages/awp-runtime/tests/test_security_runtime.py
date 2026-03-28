"""Tests for the security module (CircuitBreaker, RateLimiter, AccessController)."""

import time

from awp.runtime.security import (
    CircuitBreaker,
    RateLimiter,
    AccessController,
    SecurityContext,
)


class TestCircuitBreaker:
    def test_initial_state_is_closed(self):
        cb = CircuitBreaker(failure_threshold=3)
        assert cb.state == "closed"
        assert cb.check() is True

    def test_opens_after_threshold(self):
        cb = CircuitBreaker(failure_threshold=3)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == "closed"
        cb.record_failure()
        assert cb.state == "open"
        assert cb.check() is False

    def test_half_open_after_timeout(self):
        cb = CircuitBreaker(failure_threshold=2, reset_timeout=0.05)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == "open"

        time.sleep(0.06)
        assert cb.state == "half_open"
        assert cb.check() is True

    def test_half_open_to_closed_on_success(self):
        cb = CircuitBreaker(failure_threshold=2, reset_timeout=0.05)
        cb.record_failure()
        cb.record_failure()
        time.sleep(0.06)

        assert cb.state == "half_open"
        cb.check()  # Allow one call
        cb.record_success()
        assert cb.state == "closed"

    def test_half_open_to_open_on_failure(self):
        cb = CircuitBreaker(failure_threshold=2, reset_timeout=0.05)
        cb.record_failure()
        cb.record_failure()
        time.sleep(0.06)

        assert cb.state == "half_open"
        cb.check()
        cb.record_failure()
        assert cb.state == "open"

    def test_success_resets_count(self):
        cb = CircuitBreaker(failure_threshold=3)
        cb.record_failure()
        cb.record_failure()
        cb.record_success()
        cb.record_failure()
        cb.record_failure()
        # Still closed because success reset the count
        assert cb.state == "closed"

    def test_half_open_max_calls(self):
        cb = CircuitBreaker(
            failure_threshold=1, reset_timeout=0.01, half_open_max_calls=1
        )
        cb.record_failure()
        time.sleep(0.02)

        assert cb.check() is True  # First call allowed
        assert cb.check() is False  # Second blocked


class TestRateLimiter:
    def test_allows_within_limit(self):
        rl = RateLimiter(max_calls_per_minute=5, per_agent=True)
        for _ in range(5):
            assert rl.check("agent1") is True
            rl.record("agent1")

    def test_blocks_over_limit(self):
        rl = RateLimiter(max_calls_per_minute=3, per_agent=True)
        for _ in range(3):
            rl.record("agent1")
        assert rl.check("agent1") is False

    def test_per_agent_isolation(self):
        rl = RateLimiter(max_calls_per_minute=2, per_agent=True)
        rl.record("agent1")
        rl.record("agent1")
        assert rl.check("agent1") is False
        assert rl.check("agent2") is True  # Different agent

    def test_global_mode(self):
        rl = RateLimiter(max_calls_per_minute=2, per_agent=False)
        rl.record("agent1")
        rl.record("agent2")
        assert rl.check("agent3") is False  # Global limit reached


class TestAccessController:
    def test_default_allow(self):
        ac = AccessController(default_policy="allow")
        assert ac.is_allowed("any_agent", "any_tool") is True

    def test_deny_specific_tool(self):
        ac = AccessController(
            default_policy="allow",
            rules=[{"agent": "report_writer", "deny_tools": ["shell.execute"]}],
        )
        assert ac.is_allowed("report_writer", "shell.execute") is False
        assert ac.is_allowed("report_writer", "file.write") is True
        assert ac.is_allowed("other_agent", "shell.execute") is True

    def test_multiple_denied_tools(self):
        ac = AccessController(
            default_policy="allow",
            rules=[
                {"agent": "restricted", "deny_tools": ["shell.execute", "web.search"]}
            ],
        )
        assert ac.is_allowed("restricted", "shell.execute") is False
        assert ac.is_allowed("restricted", "web.search") is False
        assert ac.is_allowed("restricted", "file.read") is True

    def test_no_rules(self):
        ac = AccessController(default_policy="allow", rules=[])
        assert ac.is_allowed("any", "any") is True


class TestSecurityContext:
    def test_from_config_none(self):
        class MockManifest:
            security = None

        ctx = SecurityContext.from_config(MockManifest())
        assert ctx.circuit_breaker is None
        assert ctx.rate_limiter is None
        assert ctx.access_controller is None
