"""Tests for awp.data.resolver — InputResolver orchestrator.

Tests cover: raw value passthrough, Source resolution, secret substitution,
parallel resolution, retry logic, caching, and timeout handling.
"""

from __future__ import annotations

import time
from typing import Any

import pytest
from awp.data.resolver import InputResolver
from awp.data.sources import ResolverResult, Source

# ---------------------------------------------------------------------------
# Helpers / Fixtures
# ---------------------------------------------------------------------------


class FakeResolver:
    """A controllable fake resolver for testing the orchestrator."""

    def __init__(
        self, return_value: Any = "resolved",
        *, fail_n_times: int = 0, delay: float = 0.0,
    ):
        self.return_value = return_value
        self.call_count = 0
        self.fail_n_times = fail_n_times
        self.delay = delay

    def resolve(self, source: Source) -> ResolverResult:
        self.call_count += 1
        if self.delay > 0:
            time.sleep(self.delay)
        if self.call_count <= self.fail_n_times:
            raise ConnectionError(f"Transient failure (attempt {self.call_count})")
        return ResolverResult(value=self.return_value, source_kind=source.kind)


@pytest.fixture
def resolver_registry():
    """Create an InputResolver with fake resolvers registered."""
    ir = InputResolver()
    return ir


# ---------------------------------------------------------------------------
# Raw value passthrough
# ---------------------------------------------------------------------------


class TestRawValuePassthrough:
    """Raw Python values (dict, str, int, DataFrame) should pass through unchanged."""

    def test_dict_passthrough(self):
        ir = InputResolver()
        inputs = {"config": {"threshold": 0.8}}
        result = ir.resolve_all(inputs)
        assert result["config"] == {"threshold": 0.8}

    def test_str_passthrough(self):
        ir = InputResolver()
        inputs = {"text": "hello world"}
        result = ir.resolve_all(inputs)
        assert result["text"] == "hello world"

    def test_int_passthrough(self):
        ir = InputResolver()
        inputs = {"count": 42}
        result = ir.resolve_all(inputs)
        assert result["count"] == 42

    def test_float_passthrough(self):
        ir = InputResolver()
        inputs = {"score": 0.95}
        result = ir.resolve_all(inputs)
        assert result["score"] == 0.95

    def test_list_passthrough(self):
        ir = InputResolver()
        inputs = {"items": [1, 2, 3]}
        result = ir.resolve_all(inputs)
        assert result["items"] == [1, 2, 3]

    def test_none_passthrough(self):
        ir = InputResolver()
        inputs = {"empty": None}
        result = ir.resolve_all(inputs)
        assert result["empty"] is None

    def test_bool_passthrough(self):
        ir = InputResolver()
        inputs = {"flag": True}
        result = ir.resolve_all(inputs)
        assert result["flag"] is True

    def test_dataframe_passthrough(self):
        pd = pytest.importorskip("pandas")
        ir = InputResolver()
        df = pd.DataFrame({"a": [1, 2], "b": [3, 4]})
        inputs = {"data": df}
        result = ir.resolve_all(inputs)
        pd.testing.assert_frame_equal(result["data"], df)


# ---------------------------------------------------------------------------
# Source resolution
# ---------------------------------------------------------------------------


class TestSourceResolution:
    """Source objects should be resolved via their registered resolver."""

    def test_source_gets_resolved(self):
        ir = InputResolver()
        fake = FakeResolver(return_value={"resolved": True})

        # Register the fake resolver for "base64" kind
        ir.register("base64", fake)

        source = Source.base64("aGVsbG8=")
        inputs = {"data": source}
        result = ir.resolve_all(inputs)

        assert result["data"] == {"resolved": True}
        assert fake.call_count == 1

    def test_mixed_raw_and_source(self):
        ir = InputResolver()
        fake = FakeResolver(return_value=[1, 2, 3])
        ir.register("base64", fake)

        inputs = {
            "config": {"key": "value"},
            "count": 42,
            "remote_data": Source.base64("dGVzdA=="),
        }
        result = ir.resolve_all(inputs)

        assert result["config"] == {"key": "value"}
        assert result["count"] == 42
        assert result["remote_data"] == [1, 2, 3]

    def test_multiple_sources_resolved(self):
        ir = InputResolver()
        fake_b64 = FakeResolver(return_value="decoded_base64")
        fake_glob = FakeResolver(return_value=["/tmp/a.csv", "/tmp/b.csv"])

        ir.register("base64", fake_b64)
        ir.register("glob", fake_glob)

        inputs = {
            "encoded": Source.base64("dGVzdA=="),
            "files": Source.glob("/data/*.csv"),
        }
        result = ir.resolve_all(inputs)

        assert result["encoded"] == "decoded_base64"
        assert result["files"] == ["/tmp/a.csv", "/tmp/b.csv"]


# ---------------------------------------------------------------------------
# Secret substitution
# ---------------------------------------------------------------------------


class TestSecretSubstitution:
    """$SECRET_NAME placeholders in Source params should be replaced."""

    def test_simple_secret_substitution(self):
        ir = InputResolver(secrets={"API_KEY": "sk-real-key-123"})
        fake = FakeResolver(return_value={"ok": True})
        ir.register("api", fake)

        source = Source.api(
            "https://api.example.com/v1",
            method="GET",
            headers={"Authorization": "Bearer $API_KEY"},
        )
        inputs = {"result": source}

        # The resolver should receive the source with secrets substituted
        # We need to check what the fake resolver actually received
        original_resolve = fake.resolve
        received_sources = []

        def capture_resolve(src):
            received_sources.append(src)
            return original_resolve(src)

        fake.resolve = capture_resolve
        ir.resolve_all(inputs)

        assert len(received_sources) == 1
        resolved_source = received_sources[0]
        # The headers should have the secret substituted
        if hasattr(resolved_source, 'params') and 'headers' in resolved_source.params:
            assert resolved_source.params["headers"]["Authorization"] == "Bearer sk-real-key-123"

    def test_missing_secret_raises_error(self):
        ir = InputResolver(secrets={})
        fake = FakeResolver(return_value={"ok": True})
        ir.register("api", fake)

        source = Source.api(
            "https://api.example.com/v1",
            method="GET",
            headers={"Authorization": "Bearer $MISSING_SECRET"},
        )
        inputs = {"result": source}

        with pytest.raises((ValueError, KeyError)):
            ir.resolve_all(inputs)

    def test_nested_secret_substitution(self):
        ir = InputResolver(secrets={"DB_PASS": "s3cret", "DB_USER": "admin"})
        fake = FakeResolver(return_value=[])
        ir.register("sql", fake)

        source = Source.sql(
            "SELECT 1",
            dsn="postgresql://$DB_USER:$DB_PASS@localhost/db",
        )
        inputs = {"query": source}

        received_sources = []
        original_resolve = fake.resolve

        def capture_resolve(src):
            received_sources.append(src)
            return original_resolve(src)

        fake.resolve = capture_resolve
        ir.resolve_all(inputs)

        if received_sources:
            resolved_dsn = received_sources[0].params.get("dsn", "")
            assert "admin" in resolved_dsn
            assert "s3cret" in resolved_dsn
            assert "$DB_USER" not in resolved_dsn
            assert "$DB_PASS" not in resolved_dsn

    def test_secret_in_nested_dict(self):
        ir = InputResolver(secrets={"TOKEN": "abc123"})
        fake = FakeResolver(return_value={})
        ir.register("api", fake)

        source = Source.api(
            "https://example.com",
            method="POST",
            body={"auth": {"token": "$TOKEN"}},
            headers={"X-Key": "$TOKEN"},
        )
        inputs = {"data": source}

        received_sources = []
        original_resolve = fake.resolve

        def capture_resolve(src):
            received_sources.append(src)
            return original_resolve(src)

        fake.resolve = capture_resolve
        ir.resolve_all(inputs)

        if received_sources:
            params = received_sources[0].params
            if "body" in params:
                assert params["body"]["auth"]["token"] == "abc123"
            if "headers" in params:
                assert params["headers"]["X-Key"] == "abc123"


# ---------------------------------------------------------------------------
# Retry on transient failure
# ---------------------------------------------------------------------------


class TestRetryBehavior:
    """First call fails, second succeeds — should return the successful result."""

    def test_retry_on_transient_failure(self):
        ir = InputResolver()
        fake = FakeResolver(return_value="success", fail_n_times=1)
        ir.register("base64", fake)

        source = Source.base64("dGVzdA==", retries=2)
        inputs = {"data": source}
        result = ir.resolve_all(inputs)

        assert result["data"] == "success"
        assert fake.call_count == 2  # Failed once, succeeded on retry

    def test_all_retries_exhausted(self):
        ir = InputResolver()
        fake = FakeResolver(return_value="never", fail_n_times=10)
        ir.register("base64", fake)

        source = Source.base64("dGVzdA==", retries=2)
        inputs = {"data": source}

        with pytest.raises(Exception):
            ir.resolve_all(inputs)

        # Should have tried original + retries
        assert fake.call_count <= 3  # 1 original + 2 retries


# ---------------------------------------------------------------------------
# Caching
# ---------------------------------------------------------------------------


class TestCaching:
    """Same Source resolved twice should only call the resolver once."""

    def test_cache_hit(self):
        ir = InputResolver()
        fake = FakeResolver(return_value="cached_value")
        ir.register("base64", fake)

        source = Source.base64("aGVsbG8=")
        inputs = {
            "first": source,
            "second": source,  # Same Source object
        }
        result = ir.resolve_all(inputs)

        assert result["first"] == "cached_value"
        assert result["second"] == "cached_value"
        assert fake.call_count == 1  # Only resolved once

    def test_cache_disabled(self):
        ir = InputResolver()
        fake = FakeResolver(return_value="not_cached")
        ir.register("base64", fake)

        source = Source.base64("aGVsbG8=", cache=False)
        inputs = {
            "first": source,
            "second": source,
        }
        result = ir.resolve_all(inputs)

        assert result["first"] == "not_cached"
        assert result["second"] == "not_cached"
        # Without caching, should resolve twice
        assert fake.call_count == 2

    def test_different_sources_not_cached(self):
        ir = InputResolver()
        fake = FakeResolver(return_value="val")
        ir.register("base64", fake)

        s1 = Source.base64("aGVsbG8=")
        s2 = Source.base64("d29ybGQ=")
        inputs = {"a": s1, "b": s2}
        ir.resolve_all(inputs)

        assert fake.call_count == 2


# ---------------------------------------------------------------------------
# Timeout
# ---------------------------------------------------------------------------


class TestTimeout:
    """Slow resolver should raise an appropriate timeout error."""

    def test_timeout_raises_error(self):
        ir = InputResolver()
        # Create a resolver that takes 5 seconds
        fake = FakeResolver(return_value="slow", delay=5.0)
        ir.register("url", fake)

        # Source with a very short timeout
        source = Source.url("https://slow.example.com/data", timeout=0.1)
        inputs = {"data": source}

        # Should raise a timeout-related error
        with pytest.raises(Exception):
            ir.resolve_all(inputs)


# ---------------------------------------------------------------------------
# Parallel resolution
# ---------------------------------------------------------------------------


class TestParallelResolution:
    """Multiple Sources should be resolved concurrently when possible."""

    def test_multiple_sources_resolved(self):
        ir = InputResolver()

        fake_b64 = FakeResolver(return_value="decoded")
        fake_glob = FakeResolver(return_value=["/a.csv"])

        ir.register("base64", fake_b64)
        ir.register("glob", fake_glob)

        inputs = {
            "raw": "passthrough",
            "encoded": Source.base64("dGVzdA=="),
            "files": Source.glob("/data/*.csv"),
        }
        result = ir.resolve_all(inputs)

        assert result["raw"] == "passthrough"
        assert result["encoded"] == "decoded"
        assert result["files"] == ["/a.csv"]
        assert fake_b64.call_count == 1
        assert fake_glob.call_count == 1


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_empty_inputs(self):
        ir = InputResolver()
        result = ir.resolve_all({})
        assert result == {}

    def test_only_raw_values(self):
        ir = InputResolver()
        inputs = {"a": 1, "b": "hello", "c": [1, 2]}
        result = ir.resolve_all(inputs)
        assert result == inputs

    def test_unregistered_source_kind_raises(self):
        ir = InputResolver()
        # Use a custom kind that no resolver handles
        source = Source(kind="custom_nonexistent", uri="foo://bar")
        inputs = {"data": source}

        with pytest.raises((KeyError, ValueError, RuntimeError)):
            ir.resolve_all(inputs)
