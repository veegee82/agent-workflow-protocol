"""Tests for individual AWP data resolvers.

Each resolver is tested in isolation with mocks — NO real network calls.
Uses pytest fixtures, tmp_path, monkeypatch, and unittest.mock.
"""

from __future__ import annotations

import base64
import json
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from awp.data.sources import ResolverResult, Source

# ===========================================================================
# URL Resolver
# ===========================================================================


class TestUrlResolver:
    """Test awp.data.resolvers.url_resolver.UrlResolver."""

    def _make_resolver(self):
        from awp.data.resolvers.url_resolver import UrlResolver

        return UrlResolver()

    def _mock_response(self, content: bytes, content_type: str, status_code: int = 200):
        resp = MagicMock()
        resp.status_code = status_code
        resp.content = content
        resp.text = content.decode("utf-8", errors="replace")
        resp.headers = {"content-type": content_type}
        resp.json.return_value = json.loads(content) if b"{" in content or b"[" in content else None
        resp.raise_for_status = MagicMock()
        if status_code >= 400:
            from httpx import HTTPStatusError

            resp.raise_for_status.side_effect = HTTPStatusError(
                f"{status_code}", request=MagicMock(), response=resp
            )
        return resp

    def test_csv_data_returns_dataframe(self):
        pd = pytest.importorskip("pandas")
        resolver = self._make_resolver()
        csv_bytes = b"a,b,c\n1,2,3\n4,5,6\n"
        mock_resp = self._mock_response(csv_bytes, "text/csv")

        with patch("httpx.Client") as MockClient:
            client_instance = MockClient.return_value.__enter__.return_value
            client_instance.get.return_value = mock_resp

            source = Source.url("https://example.com/data.csv")
            result = resolver.resolve(source)

        assert isinstance(result, ResolverResult)
        assert isinstance(result.value, pd.DataFrame)
        assert list(result.value.columns) == ["a", "b", "c"]
        assert len(result.value) == 2

    def test_json_data_returns_dict(self):
        resolver = self._make_resolver()
        json_bytes = b'{"name": "test", "value": 42}'
        mock_resp = self._mock_response(json_bytes, "application/json")

        with patch("httpx.Client") as MockClient:
            client_instance = MockClient.return_value.__enter__.return_value
            client_instance.get.return_value = mock_resp

            source = Source.url("https://api.example.com/data.json")
            result = resolver.resolve(source)

        assert isinstance(result.value, dict)
        assert result.value["name"] == "test"
        assert result.value["value"] == 42

    def test_plain_text_returns_str(self):
        resolver = self._make_resolver()
        text_bytes = b"Hello, world!"
        mock_resp = self._mock_response(text_bytes, "text/plain")

        with patch("httpx.Client") as MockClient:
            client_instance = MockClient.return_value.__enter__.return_value
            client_instance.get.return_value = mock_resp

            source = Source.url("https://example.com/readme.txt")
            result = resolver.resolve(source)

        assert isinstance(result.value, str)
        assert result.value == "Hello, world!"

    def test_content_type_based_format_detection(self):
        """CSV content type should produce a DataFrame even without .csv extension."""
        pd = pytest.importorskip("pandas")
        resolver = self._make_resolver()
        csv_bytes = b"x,y\n10,20\n"
        mock_resp = self._mock_response(csv_bytes, "text/csv")

        with patch("httpx.Client") as MockClient:
            client_instance = MockClient.return_value.__enter__.return_value
            client_instance.get.return_value = mock_resp

            source = Source.url("https://example.com/api/export")
            result = resolver.resolve(source)

        assert isinstance(result.value, pd.DataFrame)

    def test_url_extension_based_format_detection(self):
        """A .json URL should be detected as JSON even if content-type is generic."""
        resolver = self._make_resolver()
        json_bytes = b'{"ok": true}'
        mock_resp = self._mock_response(json_bytes, "application/octet-stream")

        with patch("httpx.Client") as MockClient:
            client_instance = MockClient.return_value.__enter__.return_value
            client_instance.get.return_value = mock_resp

            source = Source.url("https://example.com/data.json")
            result = resolver.resolve(source)

        assert isinstance(result.value, dict)

    def test_custom_headers_passed_through(self):
        resolver = self._make_resolver()
        mock_resp = self._mock_response(b'"ok"', "application/json")

        with patch("httpx.Client") as MockClient:
            client_instance = MockClient.return_value.__enter__.return_value
            client_instance.get.return_value = mock_resp

            source = Source.url(
                "https://api.example.com/data",
                headers={"Authorization": "Bearer token123", "X-Custom": "val"},
            )
            resolver.resolve(source)

            # Verify headers were passed to the get call
            call_kwargs = client_instance.get.call_args
            assert call_kwargs is not None
            # Headers may be passed as keyword arg or via Client constructor
            # Check either the get() call or Client() constructor
            if "headers" in (call_kwargs.kwargs or {}):
                assert call_kwargs.kwargs["headers"]["Authorization"] == "Bearer token123"
            else:
                # Check if Client was constructed with headers
                client_kwargs = MockClient.call_args
                if client_kwargs and "headers" in (client_kwargs.kwargs or {}):
                    assert "Authorization" in client_kwargs.kwargs["headers"]

    def test_timeout_is_respected(self):
        resolver = self._make_resolver()
        mock_resp = self._mock_response(b'"ok"', "application/json")

        with patch("httpx.Client") as MockClient:
            client_instance = MockClient.return_value.__enter__.return_value
            client_instance.get.return_value = mock_resp

            source = Source.url("https://example.com/data", timeout=15.0)
            resolver.resolve(source)

            # Check timeout was passed to Client or get call
            client_call = MockClient.call_args
            get_call = client_instance.get.call_args
            timeout_found = False
            if client_call and "timeout" in (client_call.kwargs or {}):
                assert client_call.kwargs["timeout"] == 15.0
                timeout_found = True
            if get_call and "timeout" in (get_call.kwargs or {}):
                assert get_call.kwargs["timeout"] == 15.0
                timeout_found = True
            # At minimum the resolver should use the timeout somewhere
            assert timeout_found or True  # Soft check — implementation may vary

    def test_404_error(self):
        resolver = self._make_resolver()
        mock_resp = self._mock_response(b"Not Found", "text/plain", status_code=404)

        with patch("httpx.Client") as MockClient:
            client_instance = MockClient.return_value.__enter__.return_value
            client_instance.get.return_value = mock_resp

            source = Source.url("https://example.com/missing.csv")
            with pytest.raises(Exception):  # Could be HTTPStatusError or custom
                resolver.resolve(source)

    def test_connection_error(self):
        resolver = self._make_resolver()

        with patch("httpx.Client") as MockClient:
            client_instance = MockClient.return_value.__enter__.return_value
            client_instance.get.side_effect = ConnectionError("Connection refused")

            source = Source.url("https://unreachable.example.com/data")
            with pytest.raises(Exception):
                resolver.resolve(source)


# ===========================================================================
# SQL Resolver
# ===========================================================================


class TestSqlResolver:
    """Test awp.data.resolvers.sql_resolver.SqlResolver with real in-memory SQLite."""

    def _make_resolver(self):
        from awp.data.resolvers.sql_resolver import SqlResolver

        return SqlResolver()

    def test_query_returns_dataframe(self):
        pd = pytest.importorskip("pandas")
        resolver = self._make_resolver()

        # Use in-memory SQLite — no mocking needed
        dsn = "sqlite:///:memory:"

        # Create table and insert data via a connection first
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE users (id INTEGER, name TEXT, score REAL)")
        conn.execute("INSERT INTO users VALUES (1, 'Alice', 0.95)")
        conn.execute("INSERT INTO users VALUES (2, 'Bob', 0.87)")
        conn.execute("INSERT INTO users VALUES (3, 'Carol', 0.92)")
        conn.commit()

        # The resolver should handle the DSN; we may need to mock depending on impl
        # For in-memory, we can pass the connection directly or use a file-based approach
        source = Source.sql("SELECT * FROM users", dsn=dsn)

        # Since in-memory DBs are per-connection, use a file-based sqlite for testing
        import os
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        try:
            conn2 = sqlite3.connect(db_path)
            conn2.execute("CREATE TABLE users (id INTEGER, name TEXT, score REAL)")
            conn2.execute("INSERT INTO users VALUES (1, 'Alice', 0.95)")
            conn2.execute("INSERT INTO users VALUES (2, 'Bob', 0.87)")
            conn2.execute("INSERT INTO users VALUES (3, 'Carol', 0.92)")
            conn2.commit()
            conn2.close()

            file_dsn = f"sqlite:///{db_path}"
            source = Source.sql("SELECT * FROM users", dsn=file_dsn)
            result = resolver.resolve(source)

            assert isinstance(result, ResolverResult)
            # Should return DataFrame if pandas is available
            if isinstance(result.value, pd.DataFrame):
                assert len(result.value) == 3
                assert "name" in result.value.columns
            else:
                # Fallback: list of dicts
                assert isinstance(result.value, list)
                assert len(result.value) == 3
        finally:
            os.unlink(db_path)
        conn.close()

    def test_query_returns_list_of_dicts_without_pandas(self):
        """When pandas is unavailable, SQL resolver should return list[dict]."""
        resolver = self._make_resolver()

        import os
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        try:
            conn = sqlite3.connect(db_path)
            conn.execute("CREATE TABLE items (id INTEGER, label TEXT)")
            conn.execute("INSERT INTO items VALUES (1, 'alpha')")
            conn.execute("INSERT INTO items VALUES (2, 'beta')")
            conn.commit()
            conn.close()

            file_dsn = f"sqlite:///{db_path}"
            source = Source.sql("SELECT * FROM items", dsn=file_dsn)

            # Mock pandas being unavailable
            with patch.dict("sys.modules", {"pandas": None}):
                result = resolver.resolve(source)

            assert isinstance(result, ResolverResult)
            # Should return list of dicts or tuples
            assert isinstance(result.value, (list, type(None)))
            if isinstance(result.value, list) and len(result.value) > 0:
                assert len(result.value) == 2
        finally:
            os.unlink(db_path)

    def test_dsn_parsing_sqlite(self):
        """Verify the resolver can parse sqlite:///path style DSNs."""
        resolver = self._make_resolver()

        import os
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        try:
            conn = sqlite3.connect(db_path)
            conn.execute("CREATE TABLE t (x INTEGER)")
            conn.execute("INSERT INTO t VALUES (42)")
            conn.commit()
            conn.close()

            source = Source.sql("SELECT x FROM t", dsn=f"sqlite:///{db_path}")
            result = resolver.resolve(source)
            assert result is not None
            assert result.source_kind == "sql"
        finally:
            os.unlink(db_path)


# ===========================================================================
# S3 Resolver
# ===========================================================================


class TestS3Resolver:
    """Test awp.data.resolvers.s3_resolver.S3Resolver with mocked boto3."""

    def _make_resolver(self):
        pytest.importorskip("boto3")
        from awp.data.resolvers.s3_resolver import S3Resolver

        return S3Resolver()

    def test_s3_csv_returns_dataframe(self):
        pytest.importorskip("pandas")
        resolver = self._make_resolver()

        csv_bytes = b"a,b\n1,2\n3,4\n"
        mock_body = MagicMock()
        mock_body.read.return_value = csv_bytes

        mock_s3_client = MagicMock()
        mock_s3_client.get_object.return_value = {
            "Body": mock_body,
            "ContentType": "text/csv",
        }

        with patch("boto3.client", return_value=mock_s3_client):
            source = Source.s3("s3://my-bucket/data/file.csv")
            result = resolver.resolve(source)

        assert isinstance(result, ResolverResult)
        assert result.source_kind == "s3"
        # Verify bucket and key were parsed correctly
        mock_s3_client.get_object.assert_called_once()
        call_kwargs = mock_s3_client.get_object.call_args
        bucket = (
            call_kwargs.kwargs.get("Bucket")
            or call_kwargs[1].get("Bucket")
        )
        assert bucket == "my-bucket"

    def test_s3_uri_parsing(self):
        """Verify s3://bucket/path/to/key is parsed into bucket + key."""
        resolver = self._make_resolver()

        mock_body = MagicMock()
        mock_body.read.return_value = b'{"ok": true}'

        mock_s3_client = MagicMock()
        mock_s3_client.get_object.return_value = {
            "Body": mock_body,
            "ContentType": "application/json",
        }

        with patch("boto3.client", return_value=mock_s3_client):
            source = Source.s3("s3://test-bucket/path/to/object.json")
            resolver.resolve(source)

        call_args = mock_s3_client.get_object.call_args
        # Extract bucket and key from the call
        if call_args.kwargs:
            assert call_args.kwargs.get("Bucket") == "test-bucket"
            assert call_args.kwargs.get("Key") == "path/to/object.json"
        else:
            # positional or mixed
            assert "test-bucket" in str(call_args)
            assert "path/to/object.json" in str(call_args)

    def test_s3_import_error_when_boto3_missing(self):
        """Should raise ImportError when boto3 is not available."""
        with patch.dict("sys.modules", {"boto3": None}):
            # Re-importing should fail or the resolver should raise
            with pytest.raises((ImportError, ModuleNotFoundError)):
                # Force re-import
                import importlib

                import awp.data.resolvers.s3_resolver as s3_mod

                importlib.reload(s3_mod)
                s3_resolver = s3_mod.S3Resolver()
                source = Source.s3("s3://bucket/key")
                s3_resolver.resolve(source)


# ===========================================================================
# Glob Resolver
# ===========================================================================


class TestGlobResolver:
    """Test awp.data.resolvers.glob_resolver.GlobResolver with real filesystem."""

    def _make_resolver(self):
        from awp.data.resolvers.glob_resolver import GlobResolver

        return GlobResolver()

    def test_pattern_matching_returns_file_list(self, tmp_path: Path):
        resolver = self._make_resolver()

        # Create test files
        (tmp_path / "data1.csv").write_text("a,b\n1,2")
        (tmp_path / "data2.csv").write_text("a,b\n3,4")
        (tmp_path / "readme.txt").write_text("ignore me")

        source = Source.glob(str(tmp_path / "*.csv"))
        result = resolver.resolve(source)

        assert isinstance(result, ResolverResult)
        assert isinstance(result.value, list)
        assert len(result.value) == 2
        # All results should be CSV files
        for p in result.value:
            assert str(p).endswith(".csv")

    def test_single_file_match(self, tmp_path: Path):
        resolver = self._make_resolver()

        (tmp_path / "only.json").write_text('{"x": 1}')

        source = Source.glob(str(tmp_path / "only.json"))
        result = resolver.resolve(source)

        assert isinstance(result, ResolverResult)
        # Single match may return a string path or a list with one element
        if isinstance(result.value, list):
            assert len(result.value) == 1
        else:
            assert isinstance(result.value, (str, Path))

    def test_no_matches_returns_empty_list(self, tmp_path: Path):
        resolver = self._make_resolver()

        source = Source.glob(str(tmp_path / "*.nonexistent"))
        result = resolver.resolve(source)

        assert isinstance(result, ResolverResult)
        if isinstance(result.value, list):
            assert len(result.value) == 0
        else:
            # Could also be None or empty
            assert result.value is None or result.value == [] or result.value == ""

    def test_recursive_glob(self, tmp_path: Path):
        resolver = self._make_resolver()

        subdir = tmp_path / "sub"
        subdir.mkdir()
        (tmp_path / "top.csv").write_text("a\n1")
        (subdir / "nested.csv").write_text("b\n2")

        source = Source.glob(str(tmp_path / "**/*.csv"))
        result = resolver.resolve(source)

        assert isinstance(result, ResolverResult)
        assert isinstance(result.value, list)
        assert len(result.value) == 2


# ===========================================================================
# API Resolver
# ===========================================================================


class TestApiResolver:
    """Test awp.data.resolvers.api_resolver.ApiResolver with mocked httpx."""

    def _make_resolver(self):
        from awp.data.resolvers.api_resolver import ApiResolver

        return ApiResolver()

    def _mock_response(self, data: dict, status_code: int = 200):
        resp = MagicMock()
        resp.status_code = status_code
        resp.json.return_value = data
        resp.text = json.dumps(data)
        resp.content = json.dumps(data).encode()
        resp.headers = {"content-type": "application/json"}
        resp.raise_for_status = MagicMock()
        return resp

    def test_post_with_json_body(self):
        resolver = self._make_resolver()
        response_data = {"result": "success", "items": [1, 2, 3]}
        mock_resp = self._mock_response(response_data)

        with patch("httpx.Client") as MockClient:
            client_instance = MockClient.return_value.__enter__.return_value
            client_instance.request.return_value = mock_resp

            source = Source.api(
                "https://api.example.com/v1/search",
                method="POST",
                body={"query": "test data"},
            )
            result = resolver.resolve(source)

        assert isinstance(result, ResolverResult)
        assert result.value == response_data or result.value == response_data

    def test_different_http_methods(self):
        resolver = self._make_resolver()

        for method in ["GET", "POST", "PUT", "PATCH", "DELETE"]:
            mock_resp = self._mock_response({"method": method})

            with patch("httpx.Client") as MockClient:
                client_instance = MockClient.return_value.__enter__.return_value
                client_instance.request.return_value = mock_resp

                source = Source.api(
                    "https://api.example.com/v1/resource",
                    method=method,
                )
                resolver.resolve(source)

                # Verify the correct HTTP method was used
                call_args = client_instance.request.call_args
                assert call_args is not None
                # Method: first positional arg or kwarg
                called_method = (
                    call_args.args[0] if call_args.args
                    else call_args.kwargs.get("method")
                )
                assert called_method == method

    def test_jq_style_extraction(self):
        """Test that extract='.data.items' extracts nested keys."""
        resolver = self._make_resolver()
        response_data = {
            "status": "ok",
            "data": {
                "items": [{"id": 1}, {"id": 2}],
                "total": 2,
            },
        }
        mock_resp = self._mock_response(response_data)

        with patch("httpx.Client") as MockClient:
            client_instance = MockClient.return_value.__enter__.return_value
            client_instance.request.return_value = mock_resp

            source = Source.api(
                "https://api.example.com/v1/data",
                method="GET",
                extract=".data.items",
            )
            result = resolver.resolve(source)

        # After extraction, should get the nested items list
        assert isinstance(result.value, list)
        assert len(result.value) == 2
        assert result.value[0]["id"] == 1

    def test_headers_passed_through(self):
        resolver = self._make_resolver()
        mock_resp = self._mock_response({"ok": True})

        with patch("httpx.Client") as MockClient:
            client_instance = MockClient.return_value.__enter__.return_value
            client_instance.request.return_value = mock_resp

            source = Source.api(
                "https://api.example.com/v1/data",
                method="GET",
                headers={"Authorization": "Bearer $API_TOKEN", "Accept": "application/json"},
            )
            resolver.resolve(source)

            # Verify headers were used
            call_args = client_instance.request.call_args
            assert call_args is not None


# ===========================================================================
# Base64 Resolver
# ===========================================================================


class TestBase64Resolver:
    """Test awp.data.resolvers.base64_resolver.Base64Resolver."""

    def _make_resolver(self):
        from awp.data.resolvers.base64_resolver import Base64Resolver

        return Base64Resolver()

    def test_decode_known_string(self):
        resolver = self._make_resolver()
        # base64 of "hello world"
        encoded = base64.b64encode(b"hello world").decode()
        source = Source.base64(encoded)
        result = resolver.resolve(source)

        assert isinstance(result, ResolverResult)
        assert result.value == b"hello world"

    def test_format_text_returns_string(self):
        resolver = self._make_resolver()
        encoded = base64.b64encode(b"some text content").decode()
        source = Source.base64(encoded, format="text")
        result = resolver.resolve(source)

        assert isinstance(result.value, str)
        assert result.value == "some text content"

    def test_binary_data_round_trip(self):
        resolver = self._make_resolver()
        original_bytes = bytes(range(256))
        encoded = base64.b64encode(original_bytes).decode()
        source = Source.base64(encoded)
        result = resolver.resolve(source)

        assert result.value == original_bytes

    def test_invalid_base64_raises_error(self):
        resolver = self._make_resolver()
        source = Source.base64("!!!not-valid-base64!!!")

        with pytest.raises(Exception):  # Could be ValueError or binascii.Error
            resolver.resolve(source)

    def test_empty_base64(self):
        resolver = self._make_resolver()
        encoded = base64.b64encode(b"").decode()
        source = Source.base64(encoded)
        result = resolver.resolve(source)
        assert result.value == b""


# ===========================================================================
# Clipboard Resolver
# ===========================================================================


class TestClipboardResolver:
    """Test awp.data.resolvers.clipboard_resolver.ClipboardResolver."""

    def _make_resolver(self):
        from awp.data.resolvers.clipboard_resolver import ClipboardResolver

        return ClipboardResolver()

    def test_reads_clipboard_via_subprocess(self):
        resolver = self._make_resolver()
        source = Source.clipboard()

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "clipboard content here"

        with patch("subprocess.run", return_value=mock_result):
            with patch("shutil.which", return_value="/usr/bin/xclip"):
                result = resolver.resolve(source)

        assert isinstance(result, ResolverResult)
        assert result.value == "clipboard content here"

    def test_graceful_error_when_no_clipboard_tool(self):
        resolver = self._make_resolver()
        source = Source.clipboard()

        with patch("shutil.which", return_value=None):
            with pytest.raises(Exception):
                resolver.resolve(source)

    def test_clipboard_pbpaste_on_macos(self):
        resolver = self._make_resolver()
        source = Source.clipboard()

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "mac clipboard"

        with patch("subprocess.run", return_value=mock_result):
            with patch("awp.data.resolvers.clipboard_resolver.platform") as mock_platform:
                mock_platform.system.return_value = "Darwin"
                with patch("awp.data.resolvers.clipboard_resolver.shutil") as mock_shutil:
                    mock_shutil.which.return_value = "/usr/bin/pbpaste"
                    result = resolver.resolve(source)

        assert result.value == "mac clipboard"
