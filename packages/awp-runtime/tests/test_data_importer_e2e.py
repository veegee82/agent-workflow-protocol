"""End-to-end integration tests for the AWP universal data importer.

No LLM calls. Tests the full pipeline from AgentWorkflow input specification
through Source resolution, workspace preparation, and manifest generation.
Uses mocks for HTTP calls but exercises real filesystem operations.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from awp.data.inputs import classify_input, prepare_workspace
from awp.data.resolver import InputResolver
from awp.data.sources import Source

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def csv_files(tmp_path: Path) -> list[Path]:
    """Create sample CSV files in a temp directory."""
    files = []
    for i, name in enumerate(["sales.csv", "inventory.csv"]):
        p = tmp_path / name
        p.write_text(f"id,value\n{i},100\n{i+10},200\n")
        files.append(p)
    return files


# ---------------------------------------------------------------------------
# Source.base64 + raw dict mixed inputs
# ---------------------------------------------------------------------------


class TestBase64AndRawInputs:
    """Create AgentWorkflow with Source.base64(...) input + raw dict input."""

    def test_resolve_base64_and_raw_dict(self):
        ir = InputResolver()

        # Register a real-ish base64 resolver
        from awp.data.resolvers.base64_resolver import Base64Resolver

        ir.register("base64", Base64Resolver())

        encoded = base64.b64encode(b"hello world").decode()
        inputs = {
            "config": {"threshold": 0.8, "mode": "fast"},
            "raw_data": Source.base64(encoded, format="text"),
            "count": 42,
        }

        result = ir.resolve_all(inputs)

        assert result["config"] == {"threshold": 0.8, "mode": "fast"}
        assert result["raw_data"] == "hello world"
        assert result["count"] == 42

    def test_resolved_inputs_in_prepare_workspace(self, tmp_path: Path):
        """After resolving Sources, prepare_workspace should handle the results."""
        ir = InputResolver()
        from awp.data.resolvers.base64_resolver import Base64Resolver

        ir.register("base64", Base64Resolver())

        encoded = base64.b64encode(b'{"key": "value"}').decode()
        inputs = {
            "config": {"threshold": 0.5},
            "decoded": Source.base64(encoded, format="text"),
        }

        resolved = ir.resolve_all(inputs)

        # Now prepare_workspace should handle the resolved values
        manifest = prepare_workspace(resolved, tmp_path)

        assert manifest["config"]["type"] == "dict"
        assert (tmp_path / "inputs" / "config.json").exists()
        # decoded is a string after resolution
        assert manifest["decoded"]["type"] == "string"
        assert manifest["decoded"]["value"] == '{"key": "value"}'


# ---------------------------------------------------------------------------
# input_manifest.json correctness
# ---------------------------------------------------------------------------


class TestManifestGeneration:
    """Verify input_manifest.json is written correctly after resolution."""

    def test_manifest_written_with_resolved_sources(self, tmp_path: Path):
        ir = InputResolver()
        from awp.data.resolvers.base64_resolver import Base64Resolver

        ir.register("base64", Base64Resolver())

        encoded = base64.b64encode(b"binary data here").decode()
        inputs = {
            "text": "plain text",
            "number": 3.14,
            "binary": Source.base64(encoded),
        }

        resolved = ir.resolve_all(inputs)
        prepare_workspace(resolved, tmp_path)

        # Check manifest file was written
        manifest_path = tmp_path / "input_manifest.json"
        assert manifest_path.exists()

        loaded_manifest = json.loads(manifest_path.read_text())
        assert "text" in loaded_manifest
        assert "number" in loaded_manifest
        assert "binary" in loaded_manifest

        assert loaded_manifest["text"]["type"] == "string"
        assert loaded_manifest["number"]["type"] == "numeric"
        assert loaded_manifest["binary"]["type"] == "bytes"

    def test_manifest_has_workspace_paths_for_files(self, tmp_path: Path):
        pd = pytest.importorskip("pandas")
        ir = InputResolver()

        df = pd.DataFrame({"x": [1, 2, 3], "y": [4, 5, 6]})
        inputs = {"data": df, "config": {"k": "v"}}

        # No Sources to resolve, just raw values
        resolved = ir.resolve_all(inputs)
        manifest = prepare_workspace(resolved, tmp_path)

        assert manifest["data"]["workspace_path"] == "inputs/data.csv"
        assert manifest["config"]["workspace_path"] == "inputs/config.json"
        assert (tmp_path / "inputs" / "data.csv").exists()
        assert (tmp_path / "inputs" / "config.json").exists()


# ---------------------------------------------------------------------------
# Regression: existing raw inputs still work
# ---------------------------------------------------------------------------


class TestRawInputRegression:
    """Ensure existing raw input types still work after adding Source support."""

    def test_dataframe_still_works(self, tmp_path: Path):
        pd = pytest.importorskip("pandas")
        df = pd.DataFrame({"col": [10, 20, 30]})
        manifest = prepare_workspace({"df": df}, tmp_path)
        assert manifest["df"]["type"] == "dataframe"
        csv_path = tmp_path / manifest["df"]["workspace_path"]
        assert csv_path.exists()
        loaded = pd.read_csv(csv_path)
        assert list(loaded["col"]) == [10, 20, 30]

    def test_dict_still_works(self, tmp_path: Path):
        data = {"nested": {"key": [1, 2, 3]}}
        manifest = prepare_workspace({"cfg": data}, tmp_path)
        assert manifest["cfg"]["type"] == "dict"
        json_path = tmp_path / manifest["cfg"]["workspace_path"]
        loaded = json.loads(json_path.read_text())
        assert loaded == data

    def test_str_still_works(self, tmp_path: Path):
        manifest = prepare_workspace({"msg": "hello"}, tmp_path)
        assert manifest["msg"]["type"] == "string"
        assert manifest["msg"]["value"] == "hello"

    def test_file_path_still_works(self, tmp_path: Path):
        src_file = tmp_path / "source.txt"
        src_file.write_text("file content")
        workspace = tmp_path / "ws"
        manifest = prepare_workspace({"doc": str(src_file)}, workspace)
        assert manifest["doc"]["type"] == "file_path"
        copied = workspace / manifest["doc"]["workspace_path"]
        assert copied.exists()
        assert copied.read_text() == "file content"

    def test_bytes_still_works(self, tmp_path: Path):
        manifest = prepare_workspace({"raw": b"\xde\xad\xbe\xef"}, tmp_path)
        assert manifest["raw"]["type"] == "bytes"
        bin_path = tmp_path / manifest["raw"]["workspace_path"]
        assert bin_path.read_bytes() == b"\xde\xad\xbe\xef"

    def test_numeric_still_works(self, tmp_path: Path):
        manifest = prepare_workspace({"n": 42, "f": 3.14}, tmp_path)
        assert manifest["n"]["type"] == "numeric"
        assert manifest["n"]["value"] == 42
        assert manifest["f"]["type"] == "numeric"
        assert manifest["f"]["value"] == 3.14

    def test_none_still_works(self, tmp_path: Path):
        manifest = prepare_workspace({"x": None}, tmp_path)
        assert manifest["x"]["type"] == "none"
        assert manifest["x"]["value"] is None

    def test_bool_still_works(self, tmp_path: Path):
        manifest = prepare_workspace({"flag": True}, tmp_path)
        assert manifest["flag"]["type"] == "boolean"
        assert manifest["flag"]["value"] is True

    def test_list_still_works(self, tmp_path: Path):
        manifest = prepare_workspace({"items": [1, "two", 3.0]}, tmp_path)
        assert manifest["items"]["type"] == "list"
        json_path = tmp_path / manifest["items"]["workspace_path"]
        loaded = json.loads(json_path.read_text())
        assert loaded == [1, "two", 3.0]


# ---------------------------------------------------------------------------
# Source.glob with real files
# ---------------------------------------------------------------------------


class TestGlobWithRealFiles:
    """Test AgentWorkflow-style flow with Source.glob pointing to real tmp_path files."""

    def test_glob_resolves_to_file_list(self, csv_files: list[Path], tmp_path: Path):
        ir = InputResolver()
        from awp.data.resolvers.glob_resolver import GlobResolver

        ir.register("glob", GlobResolver())

        source = Source.glob(str(tmp_path / "*.csv"))
        inputs = {"data_files": source}
        resolved = ir.resolve_all(inputs)

        assert isinstance(resolved["data_files"], list)
        assert len(resolved["data_files"]) == 2
        # All paths should exist
        for p in resolved["data_files"]:
            assert Path(p).exists()

    def test_glob_resolved_then_workspace(self, csv_files: list[Path], tmp_path: Path):
        """Resolved glob paths can be passed to prepare_workspace as a list."""
        ir = InputResolver()
        from awp.data.resolvers.glob_resolver import GlobResolver

        ir.register("glob", GlobResolver())

        source = Source.glob(str(tmp_path / "*.csv"))
        resolved = ir.resolve_all({"files": source})

        workspace = tmp_path / "workspace"
        manifest = prepare_workspace({"files": resolved["files"]}, workspace)

        assert manifest["files"]["type"] == "list"
        assert (workspace / "inputs" / "files.json").exists()


# ---------------------------------------------------------------------------
# Source.url with mocked httpx
# ---------------------------------------------------------------------------


class TestUrlWithMockedHttp:
    """Test AgentWorkflow-style flow with Source.url mocking httpx to return CSV."""

    def test_url_resolves_csv_to_dataframe(self):
        pd = pytest.importorskip("pandas")
        ir = InputResolver()
        from awp.data.resolvers.url_resolver import UrlResolver

        ir.register("url", UrlResolver())

        csv_bytes = b"name,score\nAlice,95\nBob,87\n"
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = csv_bytes
        mock_resp.text = csv_bytes.decode()
        mock_resp.headers = {"content-type": "text/csv"}
        mock_resp.raise_for_status = MagicMock()

        with patch("httpx.Client") as MockClient:
            client_instance = MockClient.return_value.__enter__.return_value
            client_instance.get.return_value = mock_resp

            inputs = {"scores": Source.url("https://example.com/scores.csv")}
            resolved = ir.resolve_all(inputs)

        assert isinstance(resolved["scores"], pd.DataFrame)
        assert len(resolved["scores"]) == 2
        assert "name" in resolved["scores"].columns

    def test_url_resolved_then_workspace(self, tmp_path: Path):
        pytest.importorskip("pandas")
        ir = InputResolver()
        from awp.data.resolvers.url_resolver import UrlResolver

        ir.register("url", UrlResolver())

        csv_bytes = b"id,value\n1,100\n2,200\n"
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = csv_bytes
        mock_resp.text = csv_bytes.decode()
        mock_resp.headers = {"content-type": "text/csv"}
        mock_resp.raise_for_status = MagicMock()

        with patch("httpx.Client") as MockClient:
            client_instance = MockClient.return_value.__enter__.return_value
            client_instance.get.return_value = mock_resp

            resolved = ir.resolve_all({"remote": Source.url("https://data.example.com/api")})

        manifest = prepare_workspace({"remote": resolved["remote"]}, tmp_path)
        assert manifest["remote"]["type"] == "dataframe"
        assert (tmp_path / "inputs" / "remote.csv").exists()


# ---------------------------------------------------------------------------
# Full pipeline: resolve -> prepare_workspace -> manifest
# ---------------------------------------------------------------------------


class TestFullPipeline:
    """End-to-end: multiple Source types resolved, then workspace prepared."""

    def test_mixed_sources_full_pipeline(self, tmp_path: Path):
        pytest.importorskip("pandas")
        ir = InputResolver()

        from awp.data.resolvers.base64_resolver import Base64Resolver
        from awp.data.resolvers.glob_resolver import GlobResolver

        ir.register("base64", Base64Resolver())
        ir.register("glob", GlobResolver())

        # Create a real file for glob
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "report.csv").write_text("metric,value\naccuracy,0.95\n")

        encoded_json = base64.b64encode(b'{"model": "v2", "epochs": 10}').decode()

        inputs = {
            "task_config": {"objective": "classify"},
            "model_params": Source.base64(encoded_json, format="text"),
            "data_files": Source.glob(str(data_dir / "*.csv")),
            "threshold": 0.8,
        }

        resolved = ir.resolve_all(inputs)

        # Verify resolution
        assert resolved["task_config"] == {"objective": "classify"}
        assert resolved["model_params"] == '{"model": "v2", "epochs": 10}'
        # Glob with single match returns a path string, not a list
        assert isinstance(resolved["data_files"], str)
        assert resolved["data_files"].endswith("report.csv")
        assert resolved["threshold"] == 0.8

        # Prepare workspace
        workspace = tmp_path / "workspace"
        manifest = prepare_workspace(resolved, workspace)

        assert manifest["task_config"]["type"] == "dict"
        assert manifest["model_params"]["type"] == "string"
        assert manifest["data_files"]["type"] == "file_path"
        assert manifest["threshold"]["type"] == "numeric"

        # Manifest JSON written
        manifest_json = json.loads((workspace / "input_manifest.json").read_text())
        expected_keys = {"task_config", "model_params", "data_files", "threshold"}
        assert set(manifest_json.keys()) == expected_keys


# ---------------------------------------------------------------------------
# classify_input does not break on Source objects
# ---------------------------------------------------------------------------


class TestClassifyInputWithSources:
    """Ensure classify_input handles Source objects gracefully.

    Sources should be resolved BEFORE calling classify_input, but if
    one slips through, it should not crash.
    """

    def test_source_classified_as_something(self):
        source = Source.base64("dGVzdA==")
        # Should not raise — classify as dict or string or whatever
        result = classify_input("src", source)
        # Source is a frozen dataclass, should not crash classify_input
        assert result is not None
