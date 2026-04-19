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
    _build_tool_registry,
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
# Live-run state: running-node derivation + active-path marking
# ---------------------------------------------------------------------------


class TestLiveRunState:
    """Root-cause tests for the 'graph renders wrong on reopen' bug.

    The disk state has no explicit 'running' flag — the absence of
    run_completion.json / manager_decision.json / result.json is the
    authoritative signal that a node is still in flight. These tests pin
    that contract so a future refactor cannot silently re-break running
    status in the UI.
    """

    def _make_live_run(
        self,
        base: Path,
        *,
        finish_worker: bool = False,
        finish_run: bool = False,
    ) -> Path:
        run_dir = base / "live_run"
        run_dir.mkdir(parents=True)
        (run_dir / "run_manifest.json").write_text(
            json.dumps({
                "run_id": "live_001",
                "task": "Live task",
                "models": {"manager": "m", "worker": "w"},
                "budget": {},
            })
        )
        it_dir = run_dir / "iterations" / "001"
        it_dir.mkdir(parents=True)
        (it_dir / "manager_decision.json").write_text(
            json.dumps({"decision": "delegate", "confidence": 0.7})
        )
        (it_dir / "budget_snapshot.json").write_text(json.dumps({}))

        w_dir = it_dir / "delegations" / "live_worker"
        w_dir.mkdir(parents=True)
        (w_dir / "envelope.json").write_text(json.dumps({"instructions": "go"}))
        if finish_worker:
            (w_dir / "result.json").write_text(json.dumps({"confidence": 0.9}))
        if finish_run:
            (run_dir / "run_completion.json").write_text(
                json.dumps({"status": "complete"})
            )
        return run_dir

    def test_worker_with_envelope_but_no_result_is_running(
        self, temp_dir: Path
    ) -> None:
        run_dir = self._make_live_run(temp_dir, finish_worker=False, finish_run=False)
        graph = build_graph(run_dir)
        workers = _nodes_by_type(graph, "worker")
        assert len(workers) == 1
        assert workers[0].data["status"] == "running", (
            "a worker whose result.json has not yet landed must read as running"
        )

    def test_worker_with_result_is_complete(self, temp_dir: Path) -> None:
        run_dir = self._make_live_run(temp_dir, finish_worker=True, finish_run=False)
        graph = build_graph(run_dir)
        workers = _nodes_by_type(graph, "worker")
        assert workers[0].data["status"] == "complete"

    def test_run_complete_demotes_running_manager(self, temp_dir: Path) -> None:
        """Once run_completion.json lands, stale 'running' managers roll up to the
        final status. This prevents the post-mortem graph from showing a ghost
        running pulse for a finished run."""
        run_dir = self._make_live_run(temp_dir, finish_worker=True, finish_run=True)
        graph = build_graph(run_dir)
        managers = _nodes_by_type(graph, "manager")
        assert managers[0].data["status"] == "complete"

    def test_active_path_flag_propagates_to_ancestors(self, temp_dir: Path) -> None:
        """A running worker must light up the whole branch: worker → iteration
        → manager → task_root. Otherwise the user can't see where progress is."""
        run_dir = self._make_live_run(temp_dir, finish_worker=False, finish_run=False)
        graph = build_graph(run_dir)
        active_ids = {n.id for n in graph.nodes if n.data.get("onActivePath")}
        # Root task, manager, iteration, and the running worker all on path
        task = [n for n in graph.nodes if n.type == "task"][0]
        mgr = [n for n in graph.nodes if n.type == "manager"][0]
        it = [n for n in graph.nodes if n.type == "iteration"][0]
        w = [n for n in graph.nodes if n.type == "worker"][0]
        assert task.id in active_ids
        assert mgr.id in active_ids
        assert it.id in active_ids
        assert w.id in active_ids

    def test_active_path_edges_animated(self, temp_dir: Path) -> None:
        """Edges along the active branch must carry `animated=True` and a
        thicker strokeWidth so the frontend can draw the pulse without extra
        state tracking."""
        run_dir = self._make_live_run(temp_dir, finish_worker=False, finish_run=False)
        graph = build_graph(run_dir)
        animated = [e for e in graph.edges if e.animated]
        assert len(animated) >= 3, (
            "task→manager, manager→iter, iter→worker should all animate"
        )
        for e in animated:
            assert e.data.get("onActivePath") is True
            assert float(e.style.get("strokeWidth", 0)) >= 2.5

    def test_finished_run_has_no_active_path(self, temp_dir: Path) -> None:
        run_dir = self._make_live_run(temp_dir, finish_worker=True, finish_run=True)
        graph = build_graph(run_dir)
        active_ids = {n.id for n in graph.nodes if n.data.get("onActivePath")}
        assert active_ids == set(), (
            "a completed run must not keep any active-path markers"
        )


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


# ---------------------------------------------------------------------------
# Tool Registry — contract drift between dynamic_tool_factory._persist_tool
# and graph_builder._build_tool_registry. The runtime writes provenance into
# a nested object; the panel reads the same JSON. Without this test the two
# sides have already drifted once (creator_agent showed as "?" in the UI).
# ---------------------------------------------------------------------------


def _persisted_tool_payload(
    fqn: str,
    creator_agent: str,
    description: str = "Sample tool",
) -> dict[str, Any]:
    """Return the on-disk shape that ``dynamic_tool_factory._persist_tool``
    actually writes (verified against /tmp/awp-experiments/.../shared/dynamic_tools/*.json)."""
    return {
        "fqn": fqn,
        "description": description,
        "parameters": {
            "type": "object",
            "properties": {"x": {"type": "string"}},
            "required": ["x"],
        },
        "code": "def handler(*, x):\n    return {'ok': True, 'data': {'x': x}}",
        "meta": {},
        "code_hash": "0" * 64,
        "repair_attempts": 0,
        "provenance": {
            "creator_agent": creator_agent,
            "created_at": "2026-04-19T00:00:00+00:00",
        },
    }


def _make_run_with_persisted_tools(
    base: Path, tools: list[dict[str, Any]]
) -> Path:
    """Mirror the on-disk experiment layout that the runtime produces:

    <exp>/workspace/runs/<id>/run_manifest.json   ← graph_builder.run_dir
    <exp>/workspace/dynamic_tools -> <exp>/shared/dynamic_tools  (symlink)
    <exp>/shared/dynamic_tools/<fqn>.json         ← persisted tools
    """
    exp = base / "exp"
    shared = exp / "shared" / "dynamic_tools"
    shared.mkdir(parents=True)
    (exp / "workspace").mkdir()
    (exp / "workspace" / "dynamic_tools").symlink_to(shared)
    run_dir = exp / "workspace" / "runs" / "2026-04-19_00-00-00_test"
    run_dir.mkdir(parents=True)
    (run_dir / "run_manifest.json").write_text(
        json.dumps({"run_id": "test", "task": "t", "models": {}, "budget": {}})
    )
    for tool in tools:
        (shared / f"{tool['fqn']}.json").write_text(json.dumps(tool, indent=2))
    return run_dir


class TestToolRegistryContract:
    """Pin the JSON contract between the runtime persister and the UI reader."""

    def test_creator_agent_extracted_from_provenance(self, temp_dir: Path) -> None:
        """The runtime writes ``provenance.creator_agent``; the panel must
        surface that real worker name, not the literal '?' placeholder."""
        run_dir = _make_run_with_persisted_tools(
            temp_dir,
            [_persisted_tool_payload("dynamic.foo", creator_agent="worker_alpha")],
        )
        registry = _build_tool_registry(run_dir, [])
        assert len(registry) == 1
        assert registry[0]["fqn"] == "dynamic.foo"
        assert registry[0]["creator_agent"] == "worker_alpha"
        assert registry[0]["creator_agent"] != "?"

    def test_legacy_flat_creator_agent_fallback(self, temp_dir: Path) -> None:
        """Older JSON files (pre-provenance) had a flat ``creator_agent`` key.
        Reading them must still surface a useful name, not '?'."""
        legacy = _persisted_tool_payload("dynamic.bar", creator_agent="ignored")
        del legacy["provenance"]
        legacy["creator_agent"] = "legacy_worker"
        run_dir = _make_run_with_persisted_tools(temp_dir, [legacy])
        registry = _build_tool_registry(run_dir, [])
        assert registry[0]["creator_agent"] == "legacy_worker"

    def test_missing_creator_falls_back_to_persisted(self, temp_dir: Path) -> None:
        """When neither shape carries a creator (corrupt or hand-written file),
        the registry must still render a non-'?' label so the UI is readable."""
        broken = _persisted_tool_payload("dynamic.baz", creator_agent="x")
        broken.pop("provenance")
        run_dir = _make_run_with_persisted_tools(temp_dir, [broken])
        registry = _build_tool_registry(run_dir, [])
        assert registry[0]["creator_agent"] == "persisted"

    def test_signature_falls_back_to_parameters(self, temp_dir: Path) -> None:
        """``signature`` is not part of the persisted shape — only ``parameters``
        is. The registry should expose parameters when signature is missing so
        the inspector has a renderable schema."""
        run_dir = _make_run_with_persisted_tools(
            temp_dir,
            [_persisted_tool_payload("dynamic.foo", "worker_alpha")],
        )
        registry = _build_tool_registry(run_dir, [])
        assert registry[0]["signature"] is not None
        assert registry[0]["signature"] == registry[0]["parameters"]

    def test_build_graph_propagates_tool_registry(self, temp_dir: Path) -> None:
        """End-to-end: build_graph (the function the API endpoint calls) must
        carry the resolved tool_registry through to the GraphData payload."""
        run_dir = _make_run_with_persisted_tools(
            temp_dir,
            [
                _persisted_tool_payload("dynamic.a", "worker_a"),
                _persisted_tool_payload("dynamic.b", "worker_b"),
            ],
        )
        graph = build_graph(run_dir)
        creators = sorted(t["creator_agent"] for t in graph.tool_registry)
        assert creators == ["worker_a", "worker_b"]
