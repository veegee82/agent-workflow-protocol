"""Tests for the opt-in ready-queue DAG scheduler.

These tests construct minimal workflow directories on disk with synchronous
mock agents (no LLM calls) and run them through ``WorkflowRunner`` under
both scheduler modes (``levels`` vs ``ready_queue``).
"""

from __future__ import annotations

import textwrap
import time
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

import pytest

from awp.runtime.runner import WorkflowRunner


# ---------------------------------------------------------------------------
# Helpers for building ephemeral workflow directories with mock agents.
# ---------------------------------------------------------------------------


def _write_workflow(
    root: Path,
    graph: Iterable[Dict[str, Any]],
    scheduler: str = "levels",
) -> None:
    """Write a minimal ``workflow.awp.yaml`` under ``root``.

    ``graph`` is a list of ``{id, depends_on, when?}`` dicts; all nodes reuse
    the agent directory name equal to ``id``.
    """
    lines = [
        'awp: "1.0.0"',
        "",
        "workflow:",
        "  name: ready-queue-test",
        '  version: "1.0.0"',
        '  description: "Test workflow for ready-queue scheduler"',
        '  author: "AWP tests"',
        "",
        "orchestration:",
        "  execution:",
        "    mode: parallel",
        "    timeout:",
        "      per_agent: 30",
        "      total: 300",
        "    max_parallel_agents: 8",
        "    error_handling:",
        "      default: continue",
        "      max_retries: 0",
        "      retry_delay: 0.1",
        f"    scheduler: {scheduler}",
        "  graph:",
    ]
    for node in graph:
        lines.append(f"    - id: {node['id']}")
        lines.append(f"      agent: {node['id']}")
        deps = node.get("depends_on", [])
        if deps:
            lines.append("      depends_on:")
            for d in deps:
                lines.append(f"        - {d}")
        else:
            lines.append("      depends_on: []")
        if "when" in node:
            lines.append(f'      when: "{node["when"]}"')
        if "share_output" in node:
            lines.append("      share_output:")
            for s in node["share_output"]:
                lines.append(f"        - {s}")
    lines.append("")
    lines.append("state:")
    lines.append("  model: shared_dict")
    lines.append("  sharing:")
    lines.append("    strategy: full")
    lines.append("")
    (root / "workflow.awp.yaml").write_text("\n".join(lines), encoding="utf-8")


def _write_agent(agents_dir: Path, agent_id: str, agent_py_body: str) -> None:
    """Create an agent directory with ``agent.awp.yaml`` and ``agent.py``.

    ``agent_py_body`` is appended after the standard imports/class header so
    tests can customize the ``run`` method.
    """
    adir = agents_dir / agent_id
    adir.mkdir(parents=True, exist_ok=True)
    (adir / "agent.awp.yaml").write_text(
        textwrap.dedent(
            f"""
            awp_agent: "1.0.0"

            identity:
              id: {agent_id}
              role: test_agent
              description: "Test agent"

            model:
              name: ""

            prompt:
              system: ""

            output:
              format: json
              contract:
                confidence:
                  type: number
                  minimum: 0.0
                  maximum: 1.0
                  required: true
            """
        ).strip() + "\n",
        encoding="utf-8",
    )
    (adir / "agent.py").write_text(agent_py_body, encoding="utf-8")


_AGENT_PY_HEADER = """\
from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Dict, Optional

from awp.runtime.agent import StandaloneAgent
from awp.runtime.llm import LLMClient
from awp.runtime.tools import ToolRegistry


class Agent(StandaloneAgent):
    def __init__(
        self,
        agent_dir=None,
        workflow_dir=None,
        llm: Optional[LLMClient] = None,
        tool_registry: Optional[ToolRegistry] = None,
    ) -> None:
        super().__init__(
            agent_dir=agent_dir or Path(__file__).parent,
            workflow_dir=workflow_dir or Path(__file__).parents[2],
            llm=llm,
            tool_registry=tool_registry,
        )

    def run(self, task: str, state: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
"""


def _agent_body(sleep: float = 0.0, extra_keys: Optional[Dict[str, Any]] = None) -> str:
    """Return a full ``agent.py`` source that sleeps then emits fixed keys."""
    extra = extra_keys or {}
    payload_lines = [f'            "confidence": 1.0,']
    for k, v in extra.items():
        payload_lines.append(f"            {k!r}: {v!r},")
    payload = "\n".join(payload_lines)
    return (
        _AGENT_PY_HEADER
        + f"        time.sleep({sleep})\n"
        + f"        agent_id = Path(__file__).parent.name\n"
        + "        payload = {\n"
        + payload
        + "\n        }\n"
        + "        return {agent_id: payload}\n"
    )


def _agent_body_condition(sleep: float, found: bool) -> str:
    """Agent that emits ``found`` flag so downstream ``when`` can be tested."""
    return _agent_body(sleep=sleep, extra_keys={"found": found})


def _agent_body_many_keys(sleep: float, count: int) -> str:
    """Agent that writes ``count`` keys inside its own namespace."""
    return (
        _AGENT_PY_HEADER
        + f"        time.sleep({sleep})\n"
        + f"        agent_id = Path(__file__).parent.name\n"
        + "        payload = {'confidence': 1.0}\n"
        + f"        for i in range({count}):\n"
        + "            payload[f'k{i}'] = i\n"
        + "        return {agent_id: payload}\n"
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestFunctionalEquivalence:
    """Same DAG, both modes, state must match modulo timing keys."""

    def test_diamond_dag_equivalent(self, tmp_path: Path):
        def build(root: Path, scheduler: str) -> WorkflowRunner:
            agents_dir = root / "agents"
            agents_dir.mkdir(parents=True, exist_ok=True)
            for aid in ("a", "b", "c", "d"):
                _write_agent(agents_dir, aid, _agent_body(sleep=0.0))
            _write_workflow(
                root,
                [
                    {"id": "a", "depends_on": []},
                    {"id": "b", "depends_on": ["a"]},
                    {"id": "c", "depends_on": ["a"]},
                    {"id": "d", "depends_on": ["b", "c"]},
                ],
                scheduler=scheduler,
            )
            return WorkflowRunner(root)

        levels_dir = tmp_path / "levels"
        ready_dir = tmp_path / "ready"
        levels_dir.mkdir()
        ready_dir.mkdir()

        r1 = build(levels_dir, "levels")
        r2 = build(ready_dir, "ready_queue")

        out1 = r1.run("hello")
        out2 = r2.run("hello")

        for aid in ("a", "b", "c", "d"):
            assert aid in out1, f"levels missing {aid}"
            assert aid in out2, f"ready_queue missing {aid}"
            assert out1[aid]["confidence"] == out2[aid]["confidence"]


class TestAsymmetricTiming:
    """Ready-queue must unblock fast branch independently of slow sibling.

    The canonical pattern from the design brief is:

        A -> B (slow), A -> C (fast), B -> D, C -> E (work)

    Under the level scheduler E sits at level 2 and waits for the barrier,
    which is dominated by B. Under the ready-queue scheduler E fires as
    soon as C completes, so the tail of the fast branch runs in parallel
    with the slow branch instead of after it.
    """

    def test_chain_tail_unblocked(self, tmp_path: Path):
        """DAG: A -> {B-slow, C-fast}; C -> E-slow. Levels: C-E serial after
        B because E starts at level 2 (after B barrier). Ready: E begins as
        soon as C done.

        We choose timings such that ready_queue's critical path is
        A + C + E = ~0.05 + 1.0 = ~1.05s, and levels' is max(B, C) + E =
        1.5 + 1.0 = ~2.5s. The 80% threshold is easily beaten.
        """

        def build(root: Path, scheduler: str) -> WorkflowRunner:
            agents_dir = root / "agents"
            agents_dir.mkdir(parents=True, exist_ok=True)
            _write_agent(agents_dir, "a", _agent_body(sleep=0.0))
            _write_agent(agents_dir, "b", _agent_body(sleep=1.5))
            _write_agent(agents_dir, "c", _agent_body(sleep=0.05))
            _write_agent(agents_dir, "e", _agent_body(sleep=1.0))
            _write_workflow(
                root,
                [
                    {"id": "a", "depends_on": []},
                    {"id": "b", "depends_on": ["a"]},
                    {"id": "c", "depends_on": ["a"]},
                    {"id": "e", "depends_on": ["c"]},
                ],
                scheduler=scheduler,
            )
            return WorkflowRunner(root)

        levels_dir = tmp_path / "levels"
        ready_dir = tmp_path / "ready"
        levels_dir.mkdir()
        ready_dir.mkdir()

        r1 = build(levels_dir, "levels")
        t0 = time.monotonic()
        r1.run("task")
        levels_wall = time.monotonic() - t0

        r2 = build(ready_dir, "ready_queue")
        t0 = time.monotonic()
        r2.run("task")
        ready_wall = time.monotonic() - t0

        print(
            f"\n[timing] levels={levels_wall:.2f}s  ready_queue={ready_wall:.2f}s  "
            f"ratio={ready_wall/levels_wall:.2f}"
        )
        assert ready_wall < levels_wall * 0.8, (
            f"Expected ready_queue wall-clock < 80% of levels "
            f"(ready={ready_wall:.2f}s, levels={levels_wall:.2f}s)"
        )


class TestBudgetLimit:
    """Both modes stop at budget=0; identical final state shape."""

    def test_zero_token_budget_stops_both_modes(self, tmp_path: Path):
        def build(root: Path, scheduler: str) -> WorkflowRunner:
            agents_dir = root / "agents"
            agents_dir.mkdir(parents=True, exist_ok=True)
            for aid in ("a", "b"):
                _write_agent(agents_dir, aid, _agent_body(sleep=0.0))
            # Override workflow.awp.yaml to inject run_budget
            _write_workflow(
                root,
                [
                    {"id": "a", "depends_on": []},
                    {"id": "b", "depends_on": ["a"]},
                ],
                scheduler=scheduler,
            )
            # Append run_budget section
            wf = root / "workflow.awp.yaml"
            existing = wf.read_text(encoding="utf-8")
            existing = existing.replace(
                "  graph:",
                "  run_budget:\n"
                "    max_wall_time: 600\n"
                "    max_total_tokens: 0\n"
                "    max_tool_calls: 1500\n"
                "    max_agent_runs: 50\n"
                "    max_cost_usd: 5.0\n"
                "    enabled_limits:\n"
                "      - max_total_tokens\n"
                "  graph:",
            )
            wf.write_text(existing, encoding="utf-8")
            return WorkflowRunner(root)

        levels_dir = tmp_path / "levels"
        ready_dir = tmp_path / "ready"
        levels_dir.mkdir()
        ready_dir.mkdir()

        r1 = build(levels_dir, "levels")
        r2 = build(ready_dir, "ready_queue")

        out1 = r1.run("task")
        out2 = r2.run("task")

        # Both should stop before executing any agent.
        assert "a" not in out1
        assert "a" not in out2
        assert out1.get("_run_budget", {}).get("exceeded")
        assert out2.get("_run_budget", {}).get("exceeded")


class TestWhenCondition:
    """when expression must be honored in both modes."""

    def test_when_condition_evaluated_at_dispatch(self, tmp_path: Path):
        def build(root: Path, scheduler: str, found: bool) -> WorkflowRunner:
            agents_dir = root / "agents"
            agents_dir.mkdir(parents=True, exist_ok=True)
            _write_agent(agents_dir, "b", _agent_body_condition(0.0, found=found))
            _write_agent(agents_dir, "c", _agent_body(sleep=0.0))
            _write_workflow(
                root,
                [
                    {"id": "b", "depends_on": []},
                    {
                        "id": "c",
                        "depends_on": ["b"],
                        "when": "state['b']['found'] == True",
                    },
                ],
                scheduler=scheduler,
            )
            return WorkflowRunner(root)

        for scheduler in ("levels", "ready_queue"):
            d_true = tmp_path / f"{scheduler}_true"
            d_true.mkdir()
            r = build(d_true, scheduler, found=True)
            out = r.run("task")
            assert "c" in out, f"{scheduler}: c should run when b.found=True"

            d_false = tmp_path / f"{scheduler}_false"
            d_false.mkdir()
            r = build(d_false, scheduler, found=False)
            out = r.run("task")
            assert "c" not in out, f"{scheduler}: c should be skipped when b.found=False"


class TestRaceFreedom:
    """Ten parallel siblings all writing 100 keys — no lost writes."""

    def test_no_lost_writes_under_parallelism(self, tmp_path: Path):
        root = tmp_path / "race"
        agents_dir = root / "agents"
        agents_dir.mkdir(parents=True, exist_ok=True)

        _write_agent(agents_dir, "root", _agent_body(sleep=0.0))

        graph = [{"id": "root", "depends_on": []}]
        n_siblings = 10
        keys_per_sibling = 100
        for i in range(n_siblings):
            aid = f"w{i}"
            _write_agent(
                agents_dir,
                aid,
                _agent_body_many_keys(sleep=0.02, count=keys_per_sibling),
            )
            graph.append({"id": aid, "depends_on": ["root"]})

        _write_workflow(root, graph, scheduler="ready_queue")
        r = WorkflowRunner(root)
        out = r.run("task")

        for i in range(n_siblings):
            aid = f"w{i}"
            assert aid in out, f"missing {aid}"
            for k in range(keys_per_sibling):
                assert f"k{k}" in out[aid], f"{aid} missing key k{k}"
