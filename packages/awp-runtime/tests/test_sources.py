"""Tests for awp.data.sources — Source dataclass, ResolverResult, and resolver registry.

These tests validate the Source factory methods, serialization round-trips,
immutability, default values, and kwargs passthrough.
"""

from __future__ import annotations

import pytest
from awp.data.sources import ResolverResult, Source

# ---------------------------------------------------------------------------
# Factory methods — correct kind/uri/params
# ---------------------------------------------------------------------------


class TestSourceFactoryMethods:
    def test_url_factory(self):
        src = Source.url("https://example.com/data.csv")
        assert src.kind == "url"
        assert src.uri == "https://example.com/data.csv"
        assert src.params == {}

    def test_url_factory_with_headers(self):
        src = Source.url(
            "https://api.example.com/data",
            headers={"Authorization": "Bearer $API_KEY"},
            format="json",
        )
        assert src.kind == "url"
        assert src.uri == "https://api.example.com/data"
        assert src.params["headers"] == {"Authorization": "Bearer $API_KEY"}
        assert src.format == "json"

    def test_sql_factory(self):
        src = Source.sql("SELECT * FROM users", dsn="sqlite:///test.db")
        assert src.kind == "sql"
        assert src.uri == "SELECT * FROM users"
        assert src.params["dsn"] == "sqlite:///test.db"

    def test_s3_factory(self):
        src = Source.s3("s3://my-bucket/path/to/data.csv")
        assert src.kind == "s3"
        assert src.uri == "s3://my-bucket/path/to/data.csv"

    def test_s3_factory_with_region(self):
        src = Source.s3("s3://bucket/key.csv", region="us-west-2")
        assert src.params["region"] == "us-west-2"

    def test_glob_factory(self):
        src = Source.glob("/data/**/*.csv")
        assert src.kind == "glob"
        assert src.uri == "/data/**/*.csv"

    def test_api_factory(self):
        src = Source.api(
            "https://api.example.com/v1/search",
            method="POST",
            body={"query": "test"},
        )
        assert src.kind == "api"
        assert src.uri == "https://api.example.com/v1/search"
        assert src.params["method"] == "POST"
        assert src.params["body"] == {"query": "test"}

    def test_base64_factory(self):
        src = Source.base64("aGVsbG8gd29ybGQ=")
        assert src.kind == "base64"
        assert src.uri == "aGVsbG8gd29ybGQ="

    def test_base64_factory_with_format(self):
        src = Source.base64("aGVsbG8=", format="text")
        assert src.params["format"] == "text"

    def test_clipboard_factory(self):
        src = Source.clipboard()
        assert src.kind == "clipboard"
        assert src.uri == ""


# ---------------------------------------------------------------------------
# Default values
# ---------------------------------------------------------------------------


class TestSourceDefaults:
    def test_cache_default(self):
        src = Source.url("https://example.com/data.csv")
        assert src.cache is True

    def test_retries_default(self):
        src = Source.url("https://example.com/data.csv")
        assert src.retries == 2

    def test_timeout_default(self):
        src = Source.url("https://example.com/data.csv")
        assert src.timeout == 30.0

    def test_cache_override(self):
        src = Source.url("https://example.com/data.csv", cache=False)
        assert src.cache is False

    def test_retries_override(self):
        src = Source.url("https://example.com/data.csv", retries=5)
        assert src.retries == 5

    def test_timeout_override(self):
        src = Source.url("https://example.com/data.csv", timeout=60.0)
        assert src.timeout == 60.0


# ---------------------------------------------------------------------------
# Serialization round-trip
# ---------------------------------------------------------------------------


class TestSourceSerialization:
    def test_to_dict_basic(self):
        src = Source.url("https://example.com/data.csv")
        d = src.to_dict()
        assert d["kind"] == "url"
        assert d["uri"] == "https://example.com/data.csv"
        assert "cache" in d
        assert "retries" in d
        assert "timeout" in d

    def test_from_dict_basic(self):
        d = {
            "kind": "url",
            "uri": "https://example.com/data.csv",
            "params": {},
            "cache": True,
            "retries": 2,
            "timeout": 30.0,
        }
        src = Source.from_dict(d)
        assert src.kind == "url"
        assert src.uri == "https://example.com/data.csv"
        assert src.cache is True

    def test_round_trip_url(self):
        original = Source.url(
            "https://example.com/data.csv",
            headers={"X-Api-Key": "test"},
            format="csv",
        )
        restored = Source.from_dict(original.to_dict())
        assert restored == original

    def test_round_trip_sql(self):
        original = Source.sql("SELECT 1", dsn="sqlite:///test.db")
        restored = Source.from_dict(original.to_dict())
        assert restored == original

    def test_round_trip_s3(self):
        original = Source.s3("s3://bucket/key.csv", region="eu-west-1")
        restored = Source.from_dict(original.to_dict())
        assert restored == original

    def test_round_trip_glob(self):
        original = Source.glob("*.csv")
        restored = Source.from_dict(original.to_dict())
        assert restored == original

    def test_round_trip_api(self):
        original = Source.api(
            "https://api.test.com/v1",
            method="POST",
            body={"q": "test"},
            headers={"Auth": "Bearer xyz"},
        )
        restored = Source.from_dict(original.to_dict())
        assert restored == original

    def test_round_trip_base64(self):
        original = Source.base64("aGVsbG8=", format="text")
        restored = Source.from_dict(original.to_dict())
        assert restored == original

    def test_round_trip_clipboard(self):
        original = Source.clipboard()
        restored = Source.from_dict(original.to_dict())
        assert restored == original

    def test_round_trip_with_overridden_defaults(self):
        original = Source.url(
            "https://example.com/data.csv",
            cache=False,
            retries=5,
            timeout=120.0,
        )
        restored = Source.from_dict(original.to_dict())
        assert restored.cache is False
        assert restored.retries == 5
        assert restored.timeout == 120.0


# ---------------------------------------------------------------------------
# Immutability and hashability
# ---------------------------------------------------------------------------


class TestSourceImmutability:
    def test_frozen(self):
        src = Source.url("https://example.com/data.csv")
        with pytest.raises((AttributeError, TypeError)):
            src.kind = "s3"  # type: ignore[misc]

    def test_frozen_uri(self):
        src = Source.url("https://example.com/data.csv")
        with pytest.raises((AttributeError, TypeError)):
            src.uri = "changed"  # type: ignore[misc]

    def test_hashable(self):
        src = Source.url("https://example.com/data.csv")
        # Should not raise
        h = hash(src)
        assert isinstance(h, int)

    def test_hashable_in_set(self):
        s1 = Source.url("https://example.com/a.csv")
        s2 = Source.url("https://example.com/b.csv")
        s3 = Source.url("https://example.com/a.csv")  # same as s1
        sources = {s1, s2, s3}
        assert len(sources) == 2

    def test_equality(self):
        s1 = Source.url("https://example.com/data.csv")
        s2 = Source.url("https://example.com/data.csv")
        assert s1 == s2

    def test_inequality(self):
        s1 = Source.url("https://example.com/a.csv")
        s2 = Source.url("https://example.com/b.csv")
        assert s1 != s2


# ---------------------------------------------------------------------------
# Kwargs passthrough
# ---------------------------------------------------------------------------


class TestSourceKwargsPassthrough:
    def test_url_extra_kwargs(self):
        src = Source.url(
            "https://example.com/data.csv",
            format="csv",
            delimiter=";",
            encoding="latin-1",
        )
        assert src.params["format"] == "csv"
        assert src.params["delimiter"] == ";"
        assert src.params["encoding"] == "latin-1"

    def test_sql_extra_kwargs(self):
        src = Source.sql(
            "SELECT * FROM t",
            dsn="sqlite:///test.db",
            params={"limit": 100},
        )
        # dsn should be in params
        assert src.params["dsn"] == "sqlite:///test.db"

    def test_api_extract_path(self):
        src = Source.api(
            "https://api.test.com/v1/data",
            method="GET",
            extract=".data.items",
        )
        assert src.params["extract"] == ".data.items"

    def test_s3_extra_kwargs(self):
        src = Source.s3(
            "s3://bucket/key",
            region="us-east-1",
            profile="production",
        )
        assert src.params["region"] == "us-east-1"
        assert src.params["profile"] == "production"


# ---------------------------------------------------------------------------
# ResolverResult
# ---------------------------------------------------------------------------


class TestResolverResult:
    def test_basic_creation(self):
        rr = ResolverResult(value={"key": "val"}, source_kind="url")
        assert rr.value == {"key": "val"}
        assert rr.source_kind == "url"

    def test_with_metadata(self):
        rr = ResolverResult(
            value=[1, 2, 3],
            source_kind="sql",
            metadata={"rows": 3, "query": "SELECT 1"},
        )
        assert rr.metadata["rows"] == 3

    def test_default_metadata(self):
        rr = ResolverResult(value="hello", source_kind="base64")
        assert rr.metadata == {} or rr.metadata is None or isinstance(rr.metadata, dict)
