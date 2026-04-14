"""Tests for the graph builder service."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from server.models import GraphData
from server.services.graph_builder import (
    build_graph,
    build_incremental_graph,
    find_run_dir,
    _confidence_color,
    _truncate,
)
from tests.conftest import make_run_dir


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _node_ids(graph: GraphData) -> list[str]:
    return [n.id for n in graph.nodes]


def _node_types(graph: GraphData) -> list[str]:
    return [n.type for n in graph.nodes]


def _edge_sources(graph: GraphData) -> list[str]:
    return [e.source for e in graph.edges]


def _nodes_by_type(graph: GraphData, ntype: str) -> list:
    return [n for n in graph.nodes if n.type == ntype]


# ---------------------------------------------------------------------------
# Fictional run directory fixture
# ---------------------------------------------------------------------------


class TestBuildGraphFromFixture:
    """Test graph building using the full fictional run fixture."""

    def test_build_graph_nodes(self, fictional_run_dir: Path) -> None:
        graph = build_graph(fictional_run_dir)
        assert len(graph.nodes) > 0

        types = _node_types(graph)
        assert "task" in types
        assert "manager" in types
        assert "iteration" in types
        assert "worker" in types
        # Completion node was removed — status is now shown on the root task node

    def test_build_graph_has_root_task(self, fictional_run_dir: Path) -> None:
        graph = build_graph(fictional_run_dir)
        root = [n for n in graph.nodes if n.id == "task_root"]
        assert len(root) == 1
        assert "Analyze Q4 sales" in root[0].data["label"]

    def test_build_graph_iterations(self, fictional_run_dir: Path) -> None:
        graph = build_graph(fictional_run_dir)
        iters = _nodes_by_type(graph, "iteration")
        assert len(iters) == 2
        # Both should be "delegate" decisions
        for it in iters:
            assert it.data["decision"] == "delegate"

    def test_build_graph_workers(self, fictional_run_dir: Path) -> None:
        graph = build_graph(fictional_run_dir)
        workers = _nodes_by_type(graph, "worker")
        worker_ids = [w.data["worker_id"] for w in workers]
        assert "data_analyzer" in worker_ids
        assert "chart_generator" in worker_ids
        assert "report_writer" in worker_ids
        assert len(workers) == 3

    def test_build_graph_worker_confidence(self, fictional_run_dir: Path) -> None:
        graph = build_graph(fictional_run_dir)
        workers = _nodes_by_type(graph, "worker")
        da = [w for w in workers if w.data["worker_id"] == "data_analyzer"][0]
        assert da.data["confidence"] == 0.85
        assert da.data["hasError"] is False

    def test_build_graph_tool_calls(self, fictional_run_dir: Path) -> None:
        graph = build_graph(fictional_run_dir)
        tc_nodes = _nodes_by_type(graph, "toolCall")
        assert len(tc_nodes) >= 3  # data_analyzer has 3 tool calls
        tools = [t.data["tool"] for t in tc_nodes]
        assert "file.read" in tools
        assert "code.execute" in tools
        assert "file.write" in tools

    def test_build_graph_root_status_from_completion(self, fictional_run_dir: Path) -> None:
        """After completion, the root task node carries the final status."""
        graph = build_graph(fictional_run_dir)
        root = [n for n in graph.nodes if n.id == "task_root"]
        assert len(root) == 1
        assert root[0].data["status"] == "complete"

    def test_build_graph_edges(self, fictional_run_dir: Path) -> None:
        graph = build_graph(fictional_run_dir)
        assert len(graph.edges) > 0

    def test_build_graph_stats(self, fictional_run_dir: Path) -> None:
        graph = build_graph(fictional_run_dir)
        assert graph.stats["total_workers"] == 3
        assert graph.stats["total_iterations"] == 2
        assert graph.stats["total_tool_calls"] >= 3


# ---------------------------------------------------------------------------
# Programmatic run directory tests
# ---------------------------------------------------------------------------


class TestBuildGraphProgrammatic:
    """Test graph building from programmatically created run directories."""

    def test_empty_run(self, temp_dir: Path) -> None:
        """A run with only a manifest produces task + manager nodes."""
        run_dir = make_run_dir(temp_dir, task="Empty run")
        graph = build_graph(run_dir)
        types = _node_types(graph)
        assert "task" in types
        assert "manager" in types

    def test_single_iteration_single_worker(self, temp_dir: Path) -> None:
        run_dir = make_run_dir(
            temp_dir,
            iterations=[
                {
                    "decision": {"decision": "delegate", "confidence": None, "reasoning": "Go"},
                    "budget": {"loops_used": 1},
                    "workers": {
                        "solver": {
                            "envelope": {"instructions": "Solve it", "tools_allowed": []},
                            "result": {"confidence": 0.75, "answer": "Done"},
                        }
                    },
                }
            ],
            completion={"status": "complete", "total_iterations": 1},
        )
        graph = build_graph(run_dir)
        workers = _nodes_by_type(graph, "worker")
        assert len(workers) == 1
        assert workers[0].data["confidence"] == 0.75

    def test_worker_with_error(self, temp_dir: Path) -> None:
        run_dir = make_run_dir(
            temp_dir,
            iterations=[
                {
                    "decision": {"decision": "delegate"},
                    "workers": {
                        "failing_worker": {
                            "envelope": {"instructions": "Try this"},
                            "result": {"confidence": 0.2, "error": "Timeout exceeded"},
                        }
                    },
                }
            ],
        )
        graph = build_graph(run_dir)
        workers = _nodes_by_type(graph, "worker")
        assert len(workers) == 1
        assert workers[0].data["hasError"] is True
        assert "Timeout" in workers[0].data["error"]

    def test_worker_with_tool_calls(self, temp_dir: Path) -> None:
        run_dir = make_run_dir(
            temp_dir,
            iterations=[
                {
                    "decision": {"decision": "delegate"},
                    "workers": {
                        "coder": {
                            "envelope": {"instructions": "Code it"},
                            "result": {"confidence": 0.9},
                            "tool_calls": [
                                {"tool": "code.execute", "result": {"ok": True, "data": {"stdout": "42"}}},
                                {"tool": "file.write", "result": {"ok": False, "error": "Permission denied"}},
                            ],
                        }
                    },
                }
            ],
        )
        graph = build_graph(run_dir)
        tc_nodes = _nodes_by_type(graph, "toolCall")
        assert len(tc_nodes) == 2
        ok_nodes = [t for t in tc_nodes if t.data["ok"]]
        err_nodes = [t for t in tc_nodes if not t.data["ok"]]
        assert len(ok_nodes) == 1
        assert len(err_nodes) == 1
        assert graph.stats["tools_ok"] == 1
        assert graph.stats["tools_failed"] == 1

    def test_multiple_iterations(self, temp_dir: Path) -> None:
        run_dir = make_run_dir(
            temp_dir,
            iterations=[
                {
                    "decision": {"decision": "delegate"},
                    "workers": {"w1": {"envelope": {}, "result": {"confidence": 0.5}}},
                },
                {
                    "decision": {"decision": "delegate"},
                    "workers": {"w2": {"envelope": {}, "result": {"confidence": 0.8}}},
                },
                {
                    "decision": {"decision": "complete", "confidence": 0.9},
                    "workers": {},
                },
            ],
            completion={"status": "complete", "total_iterations": 3},
        )
        graph = build_graph(run_dir)
        assert graph.stats["total_iterations"] == 3
        assert graph.stats["total_workers"] == 2

    def test_failed_completion_status_on_root(self, temp_dir: Path) -> None:
        run_dir = make_run_dir(
            temp_dir,
            iterations=[
                {
                    "decision": {"decision": "fail", "reasoning": "Budget exceeded"},
                    "workers": {},
                }
            ],
            completion={"status": "failed", "total_iterations": 1},
        )
        graph = build_graph(run_dir)
        root = [n for n in graph.nodes if n.id == "task_root"]
        assert len(root) == 1
        assert root[0].data["status"] == "failed"


# ---------------------------------------------------------------------------
# Recursive sub-delegation (A4)
# ---------------------------------------------------------------------------


class TestSubDelegation:
    """Test recursive sub-run graph building."""

    def test_sub_run_in_worker(self, temp_dir: Path) -> None:
        """A worker that itself contains a nested run_manifest + iterations."""
        run_dir = make_run_dir(temp_dir, task="Top level")

        # Create iteration with a worker
        iter_dir = run_dir / "iterations" / "001"
        iter_dir.mkdir(parents=True)
        (iter_dir / "manager_decision.json").write_text(
            json.dumps({"decision": "delegate"})
        )
        (iter_dir / "budget_snapshot.json").write_text(json.dumps({}))

        w_dir = iter_dir / "delegations" / "sub_manager"
        w_dir.mkdir(parents=True)
        (w_dir / "envelope.json").write_text(
            json.dumps({"instructions": "Manage sub-tasks"})
        )
        (w_dir / "result.json").write_text(
            json.dumps({"confidence": 0.88})
        )

        # Sub-run inside the worker directory
        sub_run_dir = w_dir / "runs" / "sub_run_001"
        sub_run_dir.mkdir(parents=True)
        (sub_run_dir / "run_manifest.json").write_text(
            json.dumps({
                "run_id": "sub_001",
                "task": "Sub task",
                "models": {"manager": "sub-model", "worker": "sub-model"},
                "budget": {},
            })
        )
        sub_iter = sub_run_dir / "iterations" / "001"
        sub_iter.mkdir(parents=True)
        (sub_iter / "manager_decision.json").write_text(
            json.dumps({"decision": "delegate"})
        )
        (sub_iter / "budget_snapshot.json").write_text(json.dumps({}))

        sub_w = sub_iter / "delegations" / "leaf_worker"
        sub_w.mkdir(parents=True)
        (sub_w / "envelope.json").write_text(json.dumps({"instructions": "Leaf"}))
        (sub_w / "result.json").write_text(json.dumps({"confidence": 0.95}))

        graph = build_graph(run_dir)

        # Should have workers from both levels
        workers = _nodes_by_type(graph, "worker")
        worker_ids = [w.data["worker_id"] for w in workers]
        assert "sub_manager" in worker_ids
        assert "leaf_worker" in worker_ids

        # Should have 1 root manager + at least 1 sub-manager
        managers = _nodes_by_type(graph, "manager")
        submanagers = _nodes_by_type(graph, "submanager")
        assert len(managers) == 1  # exactly 1 root manager
        assert len(submanagers) >= 1  # sub-runs render as submanager nodes


# ---------------------------------------------------------------------------
# Incremental graph building
# ---------------------------------------------------------------------------


class TestIncrementalGraph:
    def test_incremental_returns_new_nodes(self, fictional_run_dir: Path) -> None:
        full = build_graph(fictional_run_dir)
        known = {full.nodes[0].id}  # mark the task root as known
        incremental = build_incremental_graph(fictional_run_dir, known)
        new_ids = {n.id for n in incremental.nodes}
        assert full.nodes[0].id not in new_ids
        assert len(incremental.nodes) < len(full.nodes)

    def test_incremental_no_known(self, fictional_run_dir: Path) -> None:
        """With no known nodes, incremental == full."""
        full = build_graph(fictional_run_dir)
        incremental = build_incremental_graph(fictional_run_dir, None)
        assert len(incremental.nodes) == len(full.nodes)


# ---------------------------------------------------------------------------
# find_run_dir
# ---------------------------------------------------------------------------


class TestFindRunDir:
    def test_find_run_dir(self, temp_dir: Path) -> None:
        runs_dir = temp_dir / "workspace" / "runs" / "run_20251215"
        runs_dir.mkdir(parents=True)
        result = find_run_dir(temp_dir)
        assert result is not None
        assert result.name == "run_20251215"

    def test_find_run_dir_picks_latest(self, temp_dir: Path) -> None:
        for name in ["run_001", "run_002", "run_003"]:
            (temp_dir / "workspace" / "runs" / name).mkdir(parents=True)
        result = find_run_dir(temp_dir)
        assert result is not None
        assert result.name == "run_003"

    def test_find_run_dir_missing(self, temp_dir: Path) -> None:
        result = find_run_dir(temp_dir)
        assert result is None

    def test_find_run_dir_empty_runs(self, temp_dir: Path) -> None:
        (temp_dir / "workspace" / "runs").mkdir(parents=True)
        result = find_run_dir(temp_dir)
        assert result is None


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------


class TestConfidenceColor:
    def test_high_confidence(self) -> None:
        assert _confidence_color(0.95) == "#00E676"  # green

    def test_medium_confidence(self) -> None:
        assert _confidence_color(0.6) == "#FFD600"  # yellow

    def test_low_confidence(self) -> None:
        assert _confidence_color(0.35) == "#FF9100"  # orange

    def test_very_low_confidence(self) -> None:
        assert _confidence_color(0.1) == "#FF1744"  # red

    def test_none_confidence(self) -> None:
        assert _confidence_color(None) == "#78909C"  # grey

    def test_boundary_08(self) -> None:
        assert _confidence_color(0.8) == "#00E676"

    def test_boundary_05(self) -> None:
        assert _confidence_color(0.5) == "#FFD600"

    def test_boundary_03(self) -> None:
        assert _confidence_color(0.3) == "#FF9100"


class TestTruncate:
    def test_short_string(self) -> None:
        assert _truncate("hello") == "hello"

    def test_long_string(self) -> None:
        result = _truncate("a" * 300, max_len=10)
        assert len(result) == 13  # 10 + "..."
        assert result.endswith("...")

    def test_none_input(self) -> None:
        assert _truncate(None) == ""

    def test_non_string(self) -> None:
        assert _truncate(42) == "42"
