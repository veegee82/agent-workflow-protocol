"""Tests for awp.data — input processing, config generation, and workflow setup.

These tests do NOT call LLMs. They validate the input classification,
workspace preparation, config building, and prompt generation.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from awp.data.inputs import InputType, classify_input, prepare_workspace
from awp.data.prompts import build_manager_system_prompt
from awp.data.workflow import AgentWorkflow


# ---------------------------------------------------------------------------
# Input classification
# ---------------------------------------------------------------------------


class TestClassifyInput:
    def test_string(self):
        assert classify_input("text", "hello world") == InputType.STRING

    def test_numeric_int(self):
        assert classify_input("count", 42) == InputType.NUMERIC

    def test_numeric_float(self):
        assert classify_input("score", 0.95) == InputType.NUMERIC

    def test_boolean(self):
        assert classify_input("flag", True) == InputType.BOOLEAN

    def test_none(self):
        assert classify_input("empty", None) == InputType.NONE

    def test_dict(self):
        assert classify_input("config", {"a": 1}) == InputType.DICT

    def test_list(self):
        assert classify_input("items", [1, 2, 3]) == InputType.LIST

    def test_bytes(self):
        assert classify_input("raw", b"\x00\x01") == InputType.BYTES

    def test_file_path(self, tmp_path: Path):
        f = tmp_path / "test.txt"
        f.write_text("data")
        assert classify_input("file", str(f)) == InputType.FILE_PATH

    def test_nonexistent_path_is_string(self):
        assert classify_input("path", "/nonexistent/file.txt") == InputType.STRING

    def test_dataframe(self):
        pd = pytest.importorskip("pandas")
        df = pd.DataFrame({"a": [1, 2], "b": [3, 4]})
        assert classify_input("data", df) == InputType.DATAFRAME

    def test_ndarray(self):
        np = pytest.importorskip("numpy")
        arr = np.array([[1, 2], [3, 4]])
        assert classify_input("matrix", arr) == InputType.NDARRAY

    def test_image_path(self, tmp_path: Path):
        img = tmp_path / "photo.png"
        img.write_bytes(b"\x89PNG\r\n\x1a\n")  # minimal PNG header
        assert classify_input("img", str(img)) == InputType.IMAGE

    def test_nonexistent_image_is_string(self):
        assert classify_input("img", "/nonexistent/photo.png") == InputType.STRING

    def test_non_image_file_is_file_path(self, tmp_path: Path):
        f = tmp_path / "data.csv"
        f.write_text("a,b\n1,2")
        assert classify_input("f", str(f)) == InputType.FILE_PATH


# ---------------------------------------------------------------------------
# Workspace preparation
# ---------------------------------------------------------------------------


class TestPrepareWorkspace:
    def test_string_input(self, tmp_path: Path):
        manifest = prepare_workspace({"text": "hello"}, tmp_path)
        assert manifest["text"]["type"] == "string"
        assert manifest["text"]["value"] == "hello"

    def test_numeric_input(self, tmp_path: Path):
        manifest = prepare_workspace({"n": 42}, tmp_path)
        assert manifest["n"]["type"] == "numeric"
        assert manifest["n"]["value"] == 42

    def test_dict_input(self, tmp_path: Path):
        data = {"threshold": 0.8, "mode": "fast"}
        manifest = prepare_workspace({"config": data}, tmp_path)
        assert manifest["config"]["type"] == "dict"
        # workspace_path is relative to workspace dir
        assert manifest["config"]["workspace_path"] == "inputs/config.json"
        json_path = tmp_path / manifest["config"]["workspace_path"]
        assert json_path.exists()
        loaded = json.loads(json_path.read_text())
        assert loaded == data

    def test_list_input(self, tmp_path: Path):
        manifest = prepare_workspace({"items": [1, 2, 3]}, tmp_path)
        assert manifest["items"]["type"] == "list"
        assert (tmp_path / manifest["items"]["workspace_path"]).exists()

    def test_bytes_input(self, tmp_path: Path):
        manifest = prepare_workspace({"raw": b"\x00\x01\x02"}, tmp_path)
        assert manifest["raw"]["type"] == "bytes"
        bin_path = tmp_path / manifest["raw"]["workspace_path"]
        assert bin_path.exists()
        assert bin_path.read_bytes() == b"\x00\x01\x02"

    def test_file_path_input(self, tmp_path: Path):
        src = tmp_path / "source.txt"
        src.write_text("content")
        workspace = tmp_path / "workspace"
        manifest = prepare_workspace({"doc": str(src)}, workspace)
        assert manifest["doc"]["type"] == "file_path"
        copied = workspace / manifest["doc"]["workspace_path"]
        assert copied.exists()
        assert copied.read_text() == "content"

    def test_dataframe_input(self, tmp_path: Path):
        pd = pytest.importorskip("pandas")
        df = pd.DataFrame({"x": [1, 2, 3], "y": [4, 5, 6]})
        manifest = prepare_workspace({"data": df}, tmp_path)
        assert manifest["data"]["type"] == "dataframe"
        csv_path = tmp_path / manifest["data"]["workspace_path"]
        assert csv_path.exists()
        assert manifest["data"]["schema"]["shape"] == [3, 2]
        assert "x" in manifest["data"]["schema"]["columns"]

    def test_ndarray_input(self, tmp_path: Path):
        np = pytest.importorskip("numpy")
        arr = np.array([[1.0, 2.0], [3.0, 4.0]])
        manifest = prepare_workspace({"matrix": arr}, tmp_path)
        assert manifest["matrix"]["type"] == "ndarray"
        npy_path = tmp_path / manifest["matrix"]["workspace_path"]
        assert npy_path.exists()
        assert manifest["matrix"]["workspace_path"] == "inputs/matrix.npy"
        schema = manifest["matrix"]["schema"]
        assert schema["shape"] == [2, 2]
        assert schema["dtype"] == "float64"
        assert schema["min"] == 1.0
        assert schema["max"] == 4.0
        # Verify round-trip
        loaded = np.load(npy_path)
        np.testing.assert_array_equal(loaded, arr)

    def test_ndarray_non_numeric(self, tmp_path: Path):
        np = pytest.importorskip("numpy")
        arr = np.array(["a", "b", "c"])
        manifest = prepare_workspace({"labels": arr}, tmp_path)
        schema = manifest["labels"]["schema"]
        assert schema["shape"] == [3]
        # No numeric stats for string arrays
        assert "mean" not in schema

    def test_image_input(self, tmp_path: Path):
        # Create a minimal valid image via PIL or raw bytes
        img_path = tmp_path / "photo.png"
        try:
            from PIL import Image

            img = Image.new("RGB", (64, 48), color=(255, 0, 0))
            img.save(img_path)
        except ImportError:
            img_path.write_bytes(b"\x89PNG\r\n\x1a\n")

        workspace = tmp_path / "workspace"
        manifest = prepare_workspace({"img": str(img_path)}, workspace)
        assert manifest["img"]["type"] == "image"
        assert manifest["img"]["workspace_path"] == "inputs/photo.png"
        copied = workspace / manifest["img"]["workspace_path"]
        assert copied.exists()
        assert manifest["img"]["original_path"] == str(img_path)
        # image_metadata should be present
        meta = manifest["img"].get("image_metadata", {})
        assert "file_size" in meta
        assert meta["extension"] == ".png"

    def test_image_with_pil_metadata(self, tmp_path: Path):
        pytest.importorskip("PIL")
        from PIL import Image

        img_path = tmp_path / "test.jpg"
        Image.new("RGB", (100, 50)).save(img_path)
        workspace = tmp_path / "workspace"
        manifest = prepare_workspace({"pic": str(img_path)}, workspace)
        meta = manifest["pic"]["image_metadata"]
        assert meta["width"] == 100
        assert meta["height"] == 50
        assert meta["mode"] == "RGB"

    def test_manifest_json_written(self, tmp_path: Path):
        prepare_workspace({"a": "hello"}, tmp_path)
        manifest_path = tmp_path / "input_manifest.json"
        assert manifest_path.exists()

    def test_mixed_inputs(self, tmp_path: Path):
        manifest = prepare_workspace(
            {"text": "hello", "n": 42, "config": {"k": "v"}, "flag": True},
            tmp_path,
        )
        assert len(manifest) == 4
        assert manifest["text"]["type"] == "string"
        assert manifest["n"]["type"] == "numeric"
        assert manifest["config"]["type"] == "dict"
        assert manifest["flag"]["type"] == "boolean"


# ---------------------------------------------------------------------------
# Prompt generation
# ---------------------------------------------------------------------------


class TestBuildManagerPrompt:
    def test_basic_prompt(self):
        manifest = {
            "data": {
                "type": "dataframe",
                "key": "data",
                "workspace_path": "/tmp/data.csv",
                "preview": "DataFrame 100 rows x 5 cols",
                "schema": {
                    "shape": [100, 5],
                    "columns": ["a", "b", "c", "d", "e"],
                    "dtypes": {
                        "a": "int64",
                        "b": "float64",
                        "c": "object",
                        "d": "int64",
                        "e": "float64",
                    },
                },
            },
        }
        prompt = build_manager_system_prompt(
            input_manifest=manifest,
            sandbox_type="subprocess",
            forbidden_tools=["shell.execute"],
            max_tools_per_worker=10,
        )
        assert "data" in prompt
        assert "DataFrame" in prompt
        assert "code.execute" in prompt
        assert "subprocess" in prompt
        assert "shell.execute" in prompt

    def test_empty_inputs(self):
        prompt = build_manager_system_prompt(
            input_manifest={},
            sandbox_type="subprocess",
            forbidden_tools=[],
            max_tools_per_worker=10,
        )
        assert "No pre-loaded input files were provided" in prompt
        assert "generate or fetch data programmatically" in prompt

    def test_empty_inputs_instructs_data_generation(self):
        """When no inputs are provided, the manager prompt should instruct
        workers to generate data rather than failing."""
        prompt = build_manager_system_prompt(
            input_manifest={},
            sandbox_type="subprocess",
            forbidden_tools=[],
            max_tools_per_worker=10,
        )
        # Must NOT contain contradictory "all required information is in the inputs"
        assert "all required information is in the Available Inputs" not in prompt
        # Must instruct workers to generate data
        assert "generate" in prompt.lower() or "fetch" in prompt.lower()
        # Must mention saving to _workspace_dir for other workers
        assert "_workspace_dir" in prompt


# ---------------------------------------------------------------------------
# AgentWorkflow config building
# ---------------------------------------------------------------------------


class TestAgentWorkflowConfig:
    def test_requires_model(self):
        with pytest.raises(ValueError, match="model is required"):
            AgentWorkflow(inputs={}, task="test", model="")

    def test_requires_task(self):
        with pytest.raises(ValueError, match="task is required"):
            AgentWorkflow(inputs={}, task="", model="test-model")

    def test_default_tools(self):
        wf = AgentWorkflow(inputs={}, task="test", model="test-model")
        assert "code.execute" in wf.tools
        assert "file.read" in wf.tools

    def test_custom_budget(self):
        wf = AgentWorkflow(
            inputs={},
            task="test",
            model="test-model",
            max_loops=5,
            max_total_tokens=100_000,
            max_wall_time=60,
        )
        config = wf._build_config()
        assert config.budget.max_loops == 5
        assert config.budget.max_total_tokens == 100_000
        assert config.budget.max_wall_time == 60

    def test_custom_sandbox(self):
        wf = AgentWorkflow(inputs={}, task="test", model="m", sandbox="docker")
        config = wf._build_config()
        assert config.worker_policy.enforced.sandbox.type == "docker"

    def test_custom_forbidden_tools(self):
        wf = AgentWorkflow(
            inputs={},
            task="test",
            model="m",
            forbidden_tools=["web.search", "shell.execute"],
        )
        config = wf._build_config()
        assert "web.search" in config.worker_policy.enforced.forbidden_tools

    def test_worker_model_defaults_to_model(self):
        wf = AgentWorkflow(inputs={}, task="test", model="my-model")
        assert wf.worker_model == "my-model"

    def test_worker_model_override(self):
        wf = AgentWorkflow(
            inputs={},
            task="test",
            model="manager-model",
            worker_model="worker-model",
        )
        assert wf.worker_model == "worker-model"

    def test_config_has_codemode_in_manager_controlled(self):
        wf = AgentWorkflow(inputs={}, task="test", model="m")
        config = wf._build_config()
        assert "codemode.enabled" in config.worker_policy.manager_controlled

    def test_determine_status_complete(self):
        assert AgentWorkflow._determine_status({"confidence": 0.9}) == "complete"

    def test_determine_status_error(self):
        assert AgentWorkflow._determine_status({"error": "boom"}) == "error"

    def test_determine_status_budget(self):
        assert (
            AgentWorkflow._determine_status(
                {"partial": True, "termination_reason": "budget exhausted"}
            )
            == "budget_exceeded"
        )

    def test_determine_status_stall(self):
        assert (
            AgentWorkflow._determine_status(
                {"partial": True, "termination_reason": "stall_detected"}
            )
            == "stall_detected"
        )


# ---------------------------------------------------------------------------
# E2E: Input handling robustness
# ---------------------------------------------------------------------------


class TestInputRobustness:
    """End-to-end tests for input handling edge cases.

    These tests verify that the workspace, manifest, and prompts are
    correctly set up — they do NOT call LLMs.
    """

    def test_empty_inputs_workspace_still_created(self, tmp_path: Path):
        """When inputs={}, workspace/inputs/ dir should still be created
        and the manifest should be empty but valid."""
        workspace = tmp_path / "workspace"
        manifest = prepare_workspace({}, workspace)
        assert manifest == {}
        assert (workspace / "inputs").exists()
        manifest_path = workspace / "input_manifest.json"
        assert manifest_path.exists()
        loaded = json.loads(manifest_path.read_text())
        assert loaded == {}

    def test_empty_inputs_manager_prompt_guides_data_generation(self):
        """When no inputs are provided, the manager prompt must instruct
        workers to generate or fetch data rather than claiming 'all required
        information is in the inputs'."""
        prompt = build_manager_system_prompt(
            input_manifest={},
            sandbox_type="subprocess",
            forbidden_tools=["shell.execute"],
            max_tools_per_worker=10,
        )
        # Should mention generating/fetching data
        assert "generate" in prompt.lower()
        # Should NOT have the misleading "all required information" clause
        # when there are actually no inputs
        assert "No pre-loaded input files" in prompt
        # Should tell workers to save data to _workspace_dir for reuse
        assert "_workspace_dir" in prompt

    def test_empty_inputs_worker_prompt_guides_data_generation(self):
        """When inputs/ is empty, the worker system prompt should include
        a hint about generating data programmatically."""
        from awp.runtime.context_sharing import build_input_registry

        workspace = tmp_path = Path("/tmp/test_empty_inputs_worker")
        workspace.mkdir(parents=True, exist_ok=True)
        (workspace / "inputs").mkdir(exist_ok=True)

        registry = build_input_registry(workspace)
        # Empty registry means no files found
        assert registry.strip() == ""

        import shutil
        shutil.rmtree(workspace, ignore_errors=True)

    def test_dataframe_input_roundtrip(self, tmp_path: Path):
        """DataFrame inputs must be serialized to CSV, described in manifest,
        and referenced correctly in the manager prompt."""
        pd = pytest.importorskip("pandas")
        np = pytest.importorskip("numpy")

        # Create realistic FAANG-like data
        np.random.seed(42)
        tickers = ["AAPL", "MSFT", "GOOGL"]
        dates = pd.bdate_range("2024-01-01", periods=20)
        rows = []
        for t in tickers:
            base = {"AAPL": 178, "MSFT": 375, "GOOGL": 140}[t]
            close = base + np.cumsum(np.random.randn(20) * 2)
            for i, d in enumerate(dates):
                rows.append({
                    "Date": d, "Open": close[i] - 1, "High": close[i] + 2,
                    "Low": close[i] - 2, "Close": close[i], "Volume": 1_000_000,
                    "Ticker": t,
                })
        df = pd.DataFrame(rows)

        workspace = tmp_path / "workspace"
        manifest = prepare_workspace({"stock_data": df}, workspace)

        # 1. CSV file must exist
        csv_path = workspace / "inputs" / "stock_data.csv"
        assert csv_path.exists()

        # 2. Manifest must have correct metadata
        entry = manifest["stock_data"]
        assert entry["type"] == "dataframe"
        assert entry["workspace_path"] == "inputs/stock_data.csv"
        assert entry["schema"]["shape"] == [60, 7]
        assert "Ticker" in entry["schema"]["columns"]

        # 3. Manager prompt must reference the exact file path
        prompt = build_manager_system_prompt(
            input_manifest=manifest,
            sandbox_type="subprocess",
            forbidden_tools=["shell.execute"],
            max_tools_per_worker=10,
        )
        assert "inputs/stock_data.csv" in prompt
        assert "60 rows x 7 cols" in prompt

        # 4. CSV must be readable and match original data
        loaded = pd.read_csv(csv_path)
        assert len(loaded) == 60
        assert set(loaded["Ticker"].unique()) == {"AAPL", "MSFT", "GOOGL"}

    def test_dict_input_inline_in_prompt(self, tmp_path: Path):
        """Dict inputs (like portfolio_config) should appear inline in the
        manager prompt so the manager can use them for delegation planning."""
        config = {
            "tickers": ["AAPL", "MSFT"],
            "risk_free_rate": 0.05,
        }
        workspace = tmp_path / "workspace"
        manifest = prepare_workspace({"portfolio_config": config}, workspace)

        prompt = build_manager_system_prompt(
            input_manifest=manifest,
            sandbox_type="subprocess",
            forbidden_tools=[],
            max_tools_per_worker=10,
        )
        # Dict content should be shown inline
        assert "portfolio_config" in prompt
        assert "tickers" in prompt
        assert "risk_free_rate" in prompt

    def test_mixed_inputs_all_referenced(self, tmp_path: Path):
        """When multiple input types are provided, all must appear in the
        manifest and the prompt."""
        pd = pytest.importorskip("pandas")

        inputs = {
            "data": pd.DataFrame({"a": [1, 2], "b": [3, 4]}),
            "config": {"mode": "fast"},
            "label": "experiment-1",
            "threshold": 0.95,
        }
        workspace = tmp_path / "workspace"
        manifest = prepare_workspace(inputs, workspace)

        assert len(manifest) == 4
        assert (workspace / "inputs" / "data.csv").exists()
        assert (workspace / "inputs" / "config.json").exists()

        prompt = build_manager_system_prompt(
            input_manifest=manifest,
            sandbox_type="subprocess",
            forbidden_tools=[],
            max_tools_per_worker=10,
        )
        assert "inputs/data.csv" in prompt
        assert "inputs/config.json" in prompt
        assert "experiment-1" in prompt
        assert "0.95" in prompt
