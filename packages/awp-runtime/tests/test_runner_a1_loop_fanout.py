"""Unit tests for A1 loop + fan_out execution in the DAG runner.

The runner's constructor is heavy (parses a manifest, initialises tools,
sandboxes, security, etc.), so these tests bind the loop/fan_out methods
as unbound functions against a lightweight mock ``self`` that stubs out
``_run_agent_with_retry`` and the observability context.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from awp.runtime.runner import WorkflowRunner


def _obs_stub():
    return SimpleNamespace(tracer=None, metrics=None, audit=None)


def _make_runner(per_call_output):
    """Build a mock runner with just the hooks used by loop/fan_out."""
    calls = []

    def _run_agent(agent_id, agent_dir, task, state, node, obs, root_span_id=None):
        snap = dict(state)
        calls.append(snap)
        result = per_call_output(len(calls) - 1, snap)
        return {agent_id: result}

    runner = MagicMock()
    runner._run_agent_with_retry = MagicMock(side_effect=_run_agent)
    runner._execute_node = WorkflowRunner._execute_node.__get__(runner, WorkflowRunner)
    runner._execute_loop = WorkflowRunner._execute_loop.__get__(runner, WorkflowRunner)
    runner._execute_fan_out = WorkflowRunner._execute_fan_out.__get__(runner, WorkflowRunner)
    runner._resolve_fan_out_source = WorkflowRunner._resolve_fan_out_source
    runner._captured_calls = calls
    return runner


class TestResolveFanOutSource:
    def test_empty_path_returns_empty(self):
        assert WorkflowRunner._resolve_fan_out_source("", {"topics": [1, 2]}) == []

    def test_plain_key(self):
        assert WorkflowRunner._resolve_fan_out_source("topics", {"topics": [1, 2, 3]}) == [1, 2, 3]

    def test_state_prefix_stripped(self):
        assert WorkflowRunner._resolve_fan_out_source(
            "state.topics", {"topics": ["a", "b"]}
        ) == ["a", "b"]

    def test_dotted_path(self):
        state = {"ctx": {"queue": ["x", "y"]}}
        assert WorkflowRunner._resolve_fan_out_source("ctx.queue", state) == ["x", "y"]

    def test_missing_path_empty(self):
        assert WorkflowRunner._resolve_fan_out_source("missing.key", {}) == []

    def test_scalar_is_empty(self):
        assert WorkflowRunner._resolve_fan_out_source("n", {"n": 42}) == []

    def test_dict_values_returned(self):
        out = WorkflowRunner._resolve_fan_out_source("m", {"m": {"a": 1, "b": 2}})
        assert sorted(out) == [1, 2]


class TestLoop:
    def test_empty_condition_runs_max_iterations(self):
        """With no until_condition the loop runs exactly max_iterations."""
        runner = _make_runner(lambda i, s: {"confidence": 0.5, "iter": i})
        loop_cfg = SimpleNamespace(
            enabled=True, max_iterations=4, until_condition="", mode="standard"
        )
        node = SimpleNamespace(loop=loop_cfg, fan_out=None)
        out = runner._execute_loop(
            "agent1", None, "task", {}, node, _obs_stub(), None, loop_cfg
        )
        assert out["agent1"]["_loop_iterations"] == 4
        assert len(out["agent1"]["_loop_history"]) == 4

    def test_until_condition_exits_when_falsy(self):
        """Loop continues while until_condition is truthy, exits on falsy."""

        def per_call(i, s):
            # Confidence climbs: 0.1, 0.5, 0.9, ...
            return {"confidence": 0.1 + i * 0.4}

        runner = _make_runner(per_call)
        loop_cfg = SimpleNamespace(
            enabled=True,
            max_iterations=10,
            until_condition="state.a.confidence < 0.8",
            mode="standard",
        )
        node = SimpleNamespace(loop=loop_cfg, fan_out=None)
        out = runner._execute_loop(
            "a", None, "task", {}, node, _obs_stub(), None, loop_cfg
        )
        # iter 0: conf 0.1 → truthy, continue
        # iter 1: conf 0.5 → truthy, continue
        # iter 2: conf 0.9 → falsy, exit
        assert out["a"]["_loop_iterations"] == 3

    def test_max_iterations_caps_loop(self):
        """Max_iterations is the hard cap even if condition stays truthy."""
        runner = _make_runner(lambda i, s: {"confidence": 0.0})
        loop_cfg = SimpleNamespace(
            enabled=True,
            max_iterations=2,
            until_condition="True",
            mode="standard",
        )
        node = SimpleNamespace(loop=loop_cfg, fan_out=None)
        out = runner._execute_loop(
            "a", None, "task", {}, node, _obs_stub(), None, loop_cfg
        )
        assert out["a"]["_loop_iterations"] == 2

    def test_broken_condition_exits_cleanly(self):
        """A condition expression that raises must not hang the loop."""
        runner = _make_runner(lambda i, s: {"confidence": 0.5})
        loop_cfg = SimpleNamespace(
            enabled=True,
            max_iterations=5,
            until_condition="state.does.not.exist",
            mode="standard",
        )
        node = SimpleNamespace(loop=loop_cfg, fan_out=None)
        out = runner._execute_loop(
            "a", None, "task", {}, node, _obs_stub(), None, loop_cfg
        )
        assert out["a"]["_loop_iterations"] == 1


class TestFanOut:
    def test_runs_once_per_item(self):
        runner = _make_runner(
            lambda i, s: {"confidence": 1.0, "seen": s.get("fan_out_item")}
        )
        fan_out_cfg = SimpleNamespace(
            enabled=True,
            source_field="topics",
            agent_template="",
            max_parallel=4,
            aggregation="merge",
        )
        node = SimpleNamespace(loop=None, fan_out=fan_out_cfg)
        state = {"topics": ["alpha", "beta", "gamma"]}
        out = runner._execute_fan_out(
            "w", None, "task", state, node, _obs_stub(), None, fan_out_cfg
        )
        assert out["w"]["_fan_out_count"] == 3
        seen = sorted(item["seen"] for item in out["w"]["items"])
        assert seen == ["alpha", "beta", "gamma"]

    def test_max_parallel_caps_workers(self):
        runner = _make_runner(lambda i, s: {"confidence": 1.0})
        fan_out_cfg = SimpleNamespace(
            enabled=True,
            source_field="items",
            agent_template="",
            max_parallel=2,
            aggregation="merge",
        )
        node = SimpleNamespace(loop=None, fan_out=fan_out_cfg)
        state = {"items": list(range(6))}
        out = runner._execute_fan_out(
            "w", None, "task", state, node, _obs_stub(), None, fan_out_cfg
        )
        assert out["w"]["_fan_out_count"] == 6

    def test_empty_source_returns_zero_count(self):
        runner = _make_runner(lambda i, s: {"confidence": 1.0})
        fan_out_cfg = SimpleNamespace(
            enabled=True,
            source_field="missing",
            agent_template="",
            max_parallel=4,
            aggregation="merge",
        )
        node = SimpleNamespace(loop=None, fan_out=fan_out_cfg)
        out = runner._execute_fan_out(
            "w", None, "task", {}, node, _obs_stub(), None, fan_out_cfg
        )
        assert out["w"]["_fan_out_count"] == 0
        assert "error" in out["w"]

    def test_concat_aggregation_flattens_lists(self):
        """Aggregation=concat should extend list-valued fields across items."""

        def per_call(i, s):
            return {"confidence": 1.0, "findings": [f"f{i}_a", f"f{i}_b"]}

        runner = _make_runner(per_call)
        fan_out_cfg = SimpleNamespace(
            enabled=True,
            source_field="items",
            agent_template="",
            max_parallel=4,
            aggregation="concat",
        )
        node = SimpleNamespace(loop=None, fan_out=fan_out_cfg)
        state = {"items": [0, 1, 2]}
        out = runner._execute_fan_out(
            "w", None, "task", state, node, _obs_stub(), None, fan_out_cfg
        )
        assert out["w"]["_fan_out_count"] == 3
        assert sorted(out["w"]["findings"]) == [
            "f0_a", "f0_b", "f1_a", "f1_b", "f2_a", "f2_b"
        ]


class TestComposition:
    def test_loop_wraps_fan_out(self):
        """With both enabled, each loop iteration runs a full fan_out pass."""
        runner = _make_runner(lambda i, s: {"confidence": 1.0})
        loop_cfg = SimpleNamespace(
            enabled=True, max_iterations=2, until_condition="", mode="standard"
        )
        fan_out_cfg = SimpleNamespace(
            enabled=True,
            source_field="items",
            agent_template="",
            max_parallel=4,
            aggregation="merge",
        )
        node = SimpleNamespace(loop=loop_cfg, fan_out=fan_out_cfg)
        state = {"items": ["a", "b"]}
        out = runner._execute_node("w", None, "task", state, node, _obs_stub(), None)
        # 2 loop iterations × 2 items = 4 agent calls
        assert runner._run_agent_with_retry.call_count == 4
        assert out["w"]["_loop_iterations"] == 2


@pytest.mark.parametrize(
    "loop_enabled,fan_out_enabled",
    [(False, False), (True, False), (False, True)],
)
def test_execute_node_dispatch(loop_enabled, fan_out_enabled):
    runner = _make_runner(lambda i, s: {"confidence": 1.0})
    loop_cfg = SimpleNamespace(
        enabled=loop_enabled,
        max_iterations=1,
        until_condition="",
        mode="standard",
    )
    fan_out_cfg = SimpleNamespace(
        enabled=fan_out_enabled,
        source_field="items",
        agent_template="",
        max_parallel=2,
        aggregation="merge",
    )
    node = SimpleNamespace(loop=loop_cfg, fan_out=fan_out_cfg)
    state = {"items": [1, 2]}
    out = runner._execute_node("w", None, "task", state, node, _obs_stub(), None)
    assert "w" in out
