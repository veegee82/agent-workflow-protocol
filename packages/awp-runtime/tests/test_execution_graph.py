"""Tests for execution_graph module."""

import json
from pathlib import Path

import pytest

from awp.runtime.execution_graph import (
    _confidence_color,
    _truncate,
    _read_json,
    _collect_delegation_data,
    generate_execution_graph,
)


# ---------------------------------------------------------------------------
# Unit tests for helpers
# ---------------------------------------------------------------------------


class TestConfidenceColor:
    def test_high_confidence_green(self):
        color = _confidence_color(0.9)
        assert color == "#00E676"

    def test_medium_confidence_yellow(self):
        color = _confidence_color(0.7)
        assert color == "#FFD600"

    def test_low_confidence_orange(self):
        color = _confidence_color(0.4)
        assert color == "#FF9100"

    def test_very_low_confidence_red(self):
        color = _confidence_color(0.1)
        assert color == "#FF1744"

    def test_none_confidence_grey(self):
        color = _confidence_color(None)
        assert color == "#78909C"


class TestTruncate:
    def test_short_text_unchanged(self):
        assert _truncate("hello") == "hello"

    def test_long_text_truncated(self):
        result = _truncate("a" * 300, max_len=200)
        assert len(result) == 203  # 200 + "..."
        assert result.endswith("...")

    def test_newlines_replaced(self):
        assert "line1 line2" in _truncate("line1\nline2\nline3")

    def test_empty_string(self):
        assert _truncate("") == ""


class TestReadJson:
    def test_valid_json(self, tmp_path):
        f = tmp_path / "test.json"
        f.write_text('{"key": "value"}')
        assert _read_json(f) == {"key": "value"}

    def test_missing_file(self, tmp_path):
        assert _read_json(tmp_path / "nope.json") is None

    def test_invalid_json(self, tmp_path):
        f = tmp_path / "bad.json"
        f.write_text("not json")
        assert _read_json(f) is None


# ---------------------------------------------------------------------------
# Integration tests with mock run directories
# ---------------------------------------------------------------------------


@pytest.fixture
def delegation_run_dir(tmp_path: Path) -> Path:
    """Create a realistic delegation loop run directory."""
    run_dir = tmp_path / "workspace" / "runs" / "test-run"
    run_dir.mkdir(parents=True)

    (run_dir / "run_manifest.json").write_text(json.dumps({
        "run_id": "test-run",
        "task": "Analyze the quarterly report for key metrics",
        "models": {"manager": "claude-opus-4", "worker": "claude-sonnet-4"},
        "budget": {"max_loops": 10, "max_total_workers": 20, "max_total_tokens": 500000},
    }))

    iter_dir = run_dir / "iterations" / "001"
    iter_dir.mkdir(parents=True)

    (iter_dir / "manager_decision.json").write_text(json.dumps({
        "decision": "delegate",
        "reasoning": "Need to split into analysis and validation tasks",
        "confidence": 0.6,
    }))
    (iter_dir / "budget_snapshot.json").write_text(json.dumps({
        "budget_remaining_pct": 97.0,
    }))

    analyst_dir = iter_dir / "delegations" / "analyst"
    analyst_dir.mkdir(parents=True)
    (analyst_dir / "envelope.json").write_text(json.dumps({
        "worker_id": "analyst",
        "instructions": "Analyze revenue trends for Q2",
        "tools_allowed": ["code.execute", "file.read"],
    }))
    (analyst_dir / "result.json").write_text(json.dumps({
        "findings": "Revenue grew 15% YoY",
        "confidence": 0.85,
    }))
    (analyst_dir / "tool_calls.json").write_text(json.dumps([
        {"tool": "code.execute", "result": {"ok": True, "data": {"stdout": "done"}}},
        {"tool": "file.read", "result": {"ok": True, "data": {"content": "..."}}},
    ]))

    validator_dir = iter_dir / "delegations" / "validator"
    validator_dir.mkdir(parents=True)
    (validator_dir / "envelope.json").write_text(json.dumps({
        "worker_id": "validator",
        "instructions": "Check data completeness",
        "tools_allowed": ["file.read"],
    }))
    (validator_dir / "result.json").write_text(json.dumps({
        "validation": "All data present",
        "confidence": 0.92,
    }))

    iter2_dir = run_dir / "iterations" / "002"
    iter2_dir.mkdir(parents=True)
    (iter2_dir / "manager_decision.json").write_text(json.dumps({
        "decision": "complete",
        "reasoning": "All analysis done with high confidence",
        "confidence": 0.95,
    }))

    (run_dir / "run_completion.json").write_text(json.dumps({
        "status": "complete",
        "total_iterations": 2,
        "final_budget": {
            "budget_remaining_pct": 90.0,
            "tokens": {"consumed": 50000},
            "workers": {"spawned": 2},
            "wall_time": {"elapsed_s": 45.2},
        },
    }))

    return run_dir


class TestCollectDelegationData:
    def test_collects_nodes_and_edges(self, delegation_run_dir):
        data = _collect_delegation_data(delegation_run_dir)
        assert len(data["nodes"]) >= 6  # task, manager, 2 decisions, 2 workers, completion
        assert len(data["edges"]) >= 5

    def test_stats(self, delegation_run_dir):
        data = _collect_delegation_data(delegation_run_dir)
        assert data["stats"]["total_workers"] == 2
        assert data["stats"]["total_iterations"] == 2
        assert data["stats"]["total_tool_calls"] == 2  # analyst has 2 tool calls

    def test_task_in_data(self, delegation_run_dir):
        data = _collect_delegation_data(delegation_run_dir)
        assert "quarterly" in data["task"]

    def test_groups_assigned(self, delegation_run_dir):
        data = _collect_delegation_data(delegation_run_dir)
        groups = {n["group"] for n in data["nodes"]}
        assert "task" in groups
        assert "manager" in groups
        assert "worker" in groups
        assert "decision" in groups
        assert "completion" in groups

    def test_tool_call_nodes(self, delegation_run_dir):
        data = _collect_delegation_data(delegation_run_dir)
        tc_nodes = [n for n in data["nodes"] if n["group"] == "tool_call"]
        assert len(tc_nodes) == 2  # analyst has 2 tool calls


class TestDelegationGraph:
    def test_generates_html(self, delegation_run_dir):
        output = delegation_run_dir / "execution_graph.html"
        result = generate_execution_graph(delegation_run_dir, output)
        assert result == output
        assert output.exists()
        html = output.read_text()
        assert "vis-network" in html

    def test_contains_task(self, delegation_run_dir):
        output = delegation_run_dir / "execution_graph.html"
        generate_execution_graph(delegation_run_dir, output)
        html = output.read_text()
        assert "quarterly" in html

    def test_contains_workers(self, delegation_run_dir):
        output = delegation_run_dir / "execution_graph.html"
        generate_execution_graph(delegation_run_dir, output)
        html = output.read_text()
        assert "analyst" in html
        assert "validator" in html

    def test_contains_sidebar(self, delegation_run_dir):
        output = delegation_run_dir / "execution_graph.html"
        generate_execution_graph(delegation_run_dir, output)
        html = output.read_text()
        assert "sidebar" in html
        assert "Legend" in html
        assert "toggleTools" in html

    def test_contains_stats(self, delegation_run_dir):
        output = delegation_run_dir / "execution_graph.html"
        generate_execution_graph(delegation_run_dir, output)
        html = output.read_text()
        assert "Iterations" in html
        assert "Workers" in html
        assert "Tool Calls" in html

    def test_default_output_path(self, delegation_run_dir):
        result = generate_execution_graph(delegation_run_dir)
        assert result == delegation_run_dir / "execution_graph.html"
        assert result.exists()


class TestEdgeCases:
    def test_empty_run_dir(self, tmp_path):
        result = generate_execution_graph(tmp_path, tmp_path / "graph.html")
        assert result is None or result.exists()

    def test_partial_delegation_data(self, tmp_path):
        run_dir = tmp_path / "run"
        run_dir.mkdir()
        (run_dir / "run_manifest.json").write_text(json.dumps({
            "run_id": "partial", "task": "Partial run",
            "models": {"manager": "m", "worker": "w"}, "budget": {},
        }))
        iter_dir = run_dir / "iterations" / "001"
        iter_dir.mkdir(parents=True)
        (iter_dir / "manager_decision.json").write_text(json.dumps({
            "decision": "delegate", "confidence": 0.5,
        }))
        worker_dir = iter_dir / "delegations" / "w1"
        worker_dir.mkdir(parents=True)
        (worker_dir / "envelope.json").write_text(json.dumps({
            "worker_id": "w1", "instructions": "do something",
        }))
        # No result.json

        output = run_dir / "execution_graph.html"
        result = generate_execution_graph(run_dir, output)
        assert result == output
        assert output.exists()

    def test_worker_with_error(self, delegation_run_dir):
        iter_dir = delegation_run_dir / "iterations" / "001"
        error_dir = iter_dir / "delegations" / "error_worker"
        error_dir.mkdir(parents=True)
        (error_dir / "envelope.json").write_text(json.dumps({
            "worker_id": "error_worker", "instructions": "This will fail",
        }))
        (error_dir / "result.json").write_text(json.dumps({
            "error": "Something went wrong", "confidence": 0.0,
        }))

        output = delegation_run_dir / "execution_graph.html"
        generate_execution_graph(delegation_run_dir, output)
        html = output.read_text()
        assert "error_worker" in html
