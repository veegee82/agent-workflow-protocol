"""Tests for awp.runtime.context_sharing — smart spillover + InputRegistry."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from awp.runtime.context_sharing import (
    ContextBudgetConfig,
    build_input_registry,
    prepare_context,
    _human_size,
    _preview_csv,
    _preview_json,
)


# ---------------------------------------------------------------------------
# ContextBudgetConfig
# ---------------------------------------------------------------------------


class TestContextBudgetConfig:
    def test_defaults(self):
        cfg = ContextBudgetConfig()
        assert cfg.total_chars == 64_000
        assert cfg.min_per_entry == 4_000
        assert cfg.preview_chars == 2_000

    def test_from_config_none(self):
        cfg = ContextBudgetConfig.from_config(None)
        assert cfg.total_chars == 64_000

    def test_from_config_custom(self):
        cfg = ContextBudgetConfig.from_config(
            {"total_chars": 128_000, "min_per_entry": 8_000, "preview_chars": 4_000}
        )
        assert cfg.total_chars == 128_000
        assert cfg.min_per_entry == 8_000
        assert cfg.preview_chars == 4_000

    def test_per_entry_budget_divides_evenly(self):
        cfg = ContextBudgetConfig(total_chars=30_000, min_per_entry=2_000)
        assert cfg.per_entry_budget(3) == 10_000

    def test_per_entry_budget_respects_floor(self):
        cfg = ContextBudgetConfig(total_chars=10_000, min_per_entry=4_000)
        # 10000 / 5 = 2000, but floor is 4000
        assert cfg.per_entry_budget(5) == 4_000

    def test_per_entry_budget_zero_entries(self):
        cfg = ContextBudgetConfig(total_chars=30_000)
        assert cfg.per_entry_budget(0) == 30_000

    def test_per_entry_budget_single_entry(self):
        cfg = ContextBudgetConfig(total_chars=30_000)
        assert cfg.per_entry_budget(1) == 30_000


# ---------------------------------------------------------------------------
# prepare_context — inline vs spillover
# ---------------------------------------------------------------------------


class TestPrepareContext:
    def test_empty_state(self, tmp_path: Path):
        result = prepare_context({}, tmp_path)
        assert result == ""

    def test_skips_task_and_underscore_keys(self, tmp_path: Path):
        state = {"task": "do stuff", "_internal": {"x": 1}, "worker_1": {"a": "b"}}
        result = prepare_context(state, tmp_path)
        assert "task" not in result.split("Context:")[0] if "Context:" in result else True
        assert "_internal" not in result
        assert "worker_1" in result

    def test_small_result_inlined(self, tmp_path: Path):
        state = {"worker_1": {"confidence": 0.9, "result": "hello"}}
        result = prepare_context(state, tmp_path)
        assert "### Context: worker_1" in result
        assert '"confidence": 0.9' in result
        # No truncation message
        assert "truncated" not in result

    def test_large_result_spills_to_file(self, tmp_path: Path):
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        large_data = {"data": "x" * 100_000}
        state = {"big_worker": large_data}
        budget = ContextBudgetConfig(total_chars=10_000, preview_chars=500)
        result = prepare_context(state, workspace, budget)

        # Should mention truncation
        assert "truncated" in result.lower()
        assert "context/big_worker.json" in result

        # File should exist with full data
        spill_file = workspace / "context" / "big_worker.json"
        assert spill_file.exists()
        content = json.loads(spill_file.read_text())
        assert len(content["data"]) == 100_000

    def test_mixed_small_and_large(self, tmp_path: Path):
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        state = {
            "small": {"value": 42},
            "large": {"data": "y" * 50_000},
        }
        budget = ContextBudgetConfig(total_chars=10_000, preview_chars=300)
        result = prepare_context(state, workspace, budget)

        # Small should be fully inlined
        assert '"value": 42' in result
        # Large should be spilled
        assert "context/large.json" in result

    def test_no_workspace_falls_back_to_inline_truncation(self):
        large_data = {"data": "z" * 50_000}
        state = {"worker": large_data}
        budget = ContextBudgetConfig(total_chars=1_000, preview_chars=200)
        result = prepare_context(state, None, budget)
        assert "truncated" in result.lower()
        assert "No workspace directory" in result

    def test_string_values_handled(self, tmp_path: Path):
        state = {"note": "some plain text note"}
        result = prepare_context(state, tmp_path)
        # String values should not be wrapped in ```json
        assert "some plain text note" in result

    def test_auto_detect_budget(self, tmp_path: Path):
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        # 10 workers, default budget 64K → ~6400 per entry
        state = {f"w{i}": {"val": "a" * 5000} for i in range(10)}
        result = prepare_context(state, workspace)
        # All should be inlined (5000 < 6400)
        assert "truncated" not in result.lower()


# ---------------------------------------------------------------------------
# InputRegistry
# ---------------------------------------------------------------------------


class TestInputRegistry:
    def test_no_inputs_dir(self, tmp_path: Path):
        result = build_input_registry(tmp_path)
        assert result == ""

    def test_empty_inputs_dir(self, tmp_path: Path):
        (tmp_path / "inputs").mkdir()
        result = build_input_registry(tmp_path)
        assert result == ""

    def test_csv_file_with_preview(self, tmp_path: Path):
        inputs = tmp_path / "inputs"
        inputs.mkdir()
        csv_content = "name,age,salary\nAlice,30,80000\nBob,25,60000\nCharlie,35,90000\n"
        (inputs / "employees.csv").write_text(csv_content)

        result = build_input_registry(tmp_path)
        assert "employees.csv" in result
        assert "Columns (3)" in result
        assert "name" in result
        assert "age" in result
        assert "salary" in result

    def test_json_file_with_preview(self, tmp_path: Path):
        inputs = tmp_path / "inputs"
        inputs.mkdir()
        data = {"users": [{"id": 1}], "meta": {"version": 2}}
        (inputs / "data.json").write_text(json.dumps(data))

        result = build_input_registry(tmp_path)
        assert "data.json" in result
        assert "object" in result.lower()
        assert "users" in result

    def test_context_dir_listed(self, tmp_path: Path):
        context = tmp_path / "context"
        context.mkdir()
        (context / "worker_1.json").write_text('{"result": "done"}')

        result = build_input_registry(tmp_path)
        assert "worker_1.json" in result
        assert "Previous Worker Results" in result

    def test_tsv_file(self, tmp_path: Path):
        inputs = tmp_path / "inputs"
        inputs.mkdir()
        tsv_content = "col1\tcol2\tcol3\nval1\tval2\tval3\n"
        (inputs / "data.tsv").write_text(tsv_content)

        result = build_input_registry(tmp_path)
        assert "data.tsv" in result
        assert "col1" in result

    def test_binary_file_listed_without_preview(self, tmp_path: Path):
        inputs = tmp_path / "inputs"
        inputs.mkdir()
        (inputs / "model.pkl").write_bytes(b"\x80\x04\x95")

        result = build_input_registry(tmp_path)
        assert "model.pkl" in result

    def test_hidden_files_skipped(self, tmp_path: Path):
        inputs = tmp_path / "inputs"
        inputs.mkdir()
        (inputs / ".hidden").write_text("secret")
        (inputs / "visible.csv").write_text("a,b\n1,2\n")

        result = build_input_registry(tmp_path)
        assert ".hidden" not in result
        assert "visible.csv" in result

    def test_parquet_hint(self, tmp_path: Path):
        inputs = tmp_path / "inputs"
        inputs.mkdir()
        (inputs / "big_data.parquet").write_bytes(b"PAR1...")

        result = build_input_registry(tmp_path)
        assert "PARQUET" in result
        assert "pd.read_parquet" in result

    def test_multiple_files_sorted(self, tmp_path: Path):
        inputs = tmp_path / "inputs"
        inputs.mkdir()
        (inputs / "c.csv").write_text("x\n1\n")
        (inputs / "a.json").write_text("{}")
        (inputs / "b.txt").write_text("hello")

        result = build_input_registry(tmp_path)
        # All files present
        assert "a.json" in result
        assert "b.txt" in result
        assert "c.csv" in result


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


class TestHumanSize:
    def test_bytes(self):
        assert _human_size(500) == "500 B"

    def test_kilobytes(self):
        result = _human_size(2048)
        assert "KB" in result

    def test_megabytes(self):
        result = _human_size(5 * 1024 * 1024)
        assert "MB" in result


class TestPreviewCSV:
    def test_basic_csv(self, tmp_path: Path):
        f = tmp_path / "test.csv"
        f.write_text("a,b,c\n1,2,3\n4,5,6\n")
        result = _preview_csv(f)
        assert "Columns (3)" in result
        assert "a, b, c" in result

    def test_empty_csv(self, tmp_path: Path):
        f = tmp_path / "empty.csv"
        f.write_text("")
        result = _preview_csv(f)
        assert "empty" in result.lower()

    def test_many_columns(self, tmp_path: Path):
        cols = [f"col_{i}" for i in range(30)]
        f = tmp_path / "wide.csv"
        f.write_text(",".join(cols) + "\n" + ",".join(["v"] * 30) + "\n")
        result = _preview_csv(f)
        assert "+10 more" in result


class TestPreviewJSON:
    def test_object(self, tmp_path: Path):
        f = tmp_path / "obj.json"
        f.write_text('{"key1": "val1", "key2": [1,2,3]}')
        result = _preview_json(f)
        assert "object" in result.lower()
        assert "key1" in result

    def test_array(self, tmp_path: Path):
        f = tmp_path / "arr.json"
        f.write_text('[{"id": 1}, {"id": 2}]')
        result = _preview_json(f)
        assert "array" in result.lower()

    def test_jsonl(self, tmp_path: Path):
        f = tmp_path / "data.jsonl"
        f.write_text('{"a": 1}\n{"a": 2}\n')
        result = _preview_json(f)
        assert "JSONL" in result


# ---------------------------------------------------------------------------
# Pydantic model integration
# ---------------------------------------------------------------------------


class TestContextBudgetModel:
    def test_model_has_defaults(self):
        from awp.models.orchestration import ContextBudget

        cb = ContextBudget()
        assert cb.total_chars == 64_000
        assert cb.min_per_entry == 4_000
        assert cb.preview_chars == 2_000

    def test_delegation_loop_config_has_context_budget(self):
        from awp.models.orchestration import DelegationLoopConfig

        cfg = DelegationLoopConfig()
        assert cfg.context_budget.total_chars == 64_000

    def test_orchestration_config_has_context_budget(self):
        from awp.models.orchestration import AWPOrchestrationConfig

        cfg = AWPOrchestrationConfig()
        assert cfg.context_budget.total_chars == 64_000

    def test_context_budget_exported(self):
        from awp.models import ContextBudget

        cb = ContextBudget(total_chars=100_000)
        assert cb.total_chars == 100_000
