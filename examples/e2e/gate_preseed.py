#!/usr/bin/env python3
"""E2E test: gate verification with pre-seeded dynamic tool.

Skips Phase 1 (tool registration) by placing the tool descriptor in
``shared/dynamic_tools/`` BEFORE the workflow starts. This leaves the
LLM only one job: invoke the pre-registered tool via the tool protocol
with ``required_tool_invocations`` set. Eliminates Phase 1 repair-loop
variance and proves the gate mechanism end-to-end within a tight budget.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_project_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_project_root / "packages" / "awp-core" / "src"))
sys.path.insert(0, str(_project_root / "packages" / "awp-runtime" / "src"))
sys.path.insert(0, str(_project_root / "packages" / "awp-ui" / "server"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _harness import _ensure_experiment_shared_symlinks, make_experiment_dir, run_e2e  # noqa: E402

TOOL_DESCRIPTOR = {
    "fqn": "dynamic.reverse_text",
    "name": "dynamic.reverse_text",
    "description": "Reverse a string (character order).",
    "creator_agent": "preseed_harness",
    "parameters": {
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
    },
    "code": (
        "def handler(*, text):\n"
        "    return {\"ok\": True, \"status\": 200, "
        "\"data\": {\"reversed\": text[::-1]}, \"error\": None}\n"
    ),
    "required_secrets": [],
}


TASK = r"""\
The dynamic tool ``dynamic.reverse_text`` is already registered (see
the Tool Registry on the side panel). It reverses a string.

Your job: invoke this tool via the tool protocol on three inputs and
write two small artefacts. Do NOT reimplement string reversal in
``code.execute`` — the runtime enforces this with a deterministic gate.

## Phase 1 — Invoke the tool three times

In a single DELEGATE decision, spawn ONE worker. Set its envelope's
``required_tool_invocations`` to ``["dynamic.reverse_text"]``. The
worker MUST call ``dynamic.reverse_text`` via the tool protocol on:

  - ``"kayak"``
  - ``"hello"``
  - ``"AWP"``

and collect each tool's returned ``data.reversed`` value. Then write
``_output_dir/reverse_results.json`` as
``{"samples": [{"input": "kayak", "reversed": "kayak"}, {"input": "hello", "reversed": "olleh"}, {"input": "AWP", "reversed": "PWA"}]}``.

## Phase 2 — Write gate_report.md

Produce ``_output_dir/gate_report.md`` (>=50 words) stating which
dynamic tool was used, how many times it was invoked, and confirming
that all three reversals were produced by tool calls rather than by
reimplementation.

## Required deliverables

- ``_output_dir/reverse_results.json``
- ``_output_dir/gate_report.md``
"""


def _preseed_tool(workflow_dir: Path) -> None:
    """Place the tool descriptor in shared/dynamic_tools/ before the run."""
    _ensure_experiment_shared_symlinks(workflow_dir)
    tools_dir = workflow_dir / "shared" / "dynamic_tools"
    tools_dir.mkdir(parents=True, exist_ok=True)
    path = tools_dir / "dynamic.reverse_text.json"
    path.write_text(json.dumps(TOOL_DESCRIPTOR, indent=2), encoding="utf-8")
    print(f"[preseed] wrote tool descriptor to {path}")


def _verify(workflow_dir: Path, _payload: dict) -> dict:
    from server.services.graph_builder import build_graph, find_run_dir
    run_dir = find_run_dir(workflow_dir)
    if run_dir is None:
        return {"ok": False, "error": "no run_dir"}

    graph = build_graph(run_dir)
    registry = graph.tool_registry or []

    # Gate evidence in any worker result.json
    gate_fired = False
    gate_satisfied_eventually = False
    for rj in run_dir.rglob("result.json"):
        try:
            data = json.loads(rj.read_text(encoding="utf-8"))
        except Exception:
            continue
        gate = data.get("_required_tool_gate")
        if isinstance(gate, dict):
            if gate.get("satisfied") is False:
                gate_fired = True
            if gate.get("satisfied") is True:
                gate_satisfied_eventually = True

    tool_called = any(t.get("call_count", 0) >= 1 for t in registry if t.get("fqn") == "dynamic.reverse_text")
    files = {p.name for p in workflow_dir.rglob("*") if p.is_file()}
    missing = {"reverse_results.json", "gate_report.md"} - files

    checks = {
        "preseed_tool_in_registry": any(t.get("fqn") == "dynamic.reverse_text" for t in registry),
        "tool_was_invoked_via_protocol": tool_called,
        "workspace_tools_is_symlink": (workflow_dir / "workspace" / "dynamic_tools").is_symlink(),
        "deliverables_present": not missing,
        "gate_mechanism_exercised": gate_fired or tool_called,
    }
    return {
        "ok": all(checks.values()),
        "checks": checks,
        "tool_registry": [{"fqn": t.get("fqn"), "call_count": t.get("call_count")} for t in registry],
        "gate_fired": gate_fired,
        "gate_satisfied_after_repair": gate_satisfied_eventually,
        "missing_files": sorted(missing),
        "run_dir": str(run_dir),
    }


def main() -> int:
    # Preseed BEFORE run_e2e creates a new experiment dir
    wd = make_experiment_dir("gate-preseed")
    _preseed_tool(wd)

    report = run_e2e(
        slug="gate-preseed",
        title="Gate Preseed — tool already registered, verify invocation gate",
        task=TASK,
        model="openai/gpt-5-mini",
        worker_model="deepseek/deepseek-chat-v3.1",
        max_loops=8,
        max_total_tokens=800_000,
        max_wall_time=600,
        max_total_workers=6,
        max_depth=1,
        max_tool_calls=30,
        verifier=_verify,
        extra_config={
            "code_mode": {"enabled": True},
            "tool_creation": {"enabled": False},
        },
        workflow_dir=wd,
        tags=["e2e", "required-tool-gate", "preseed"],
    )
    status = report["status"]
    verify_ok = report.get("verify_ok")
    wall = report.get("duration_s", 0)
    print(f"\n{'='*64}\n[gate_preseed] status={status} verify={verify_ok} wall={wall:.0f}s")
    if report.get("verification"):
        print(json.dumps(report["verification"], indent=2))
    return 0 if (status == "complete" and verify_ok) else 1


if __name__ == "__main__":
    raise SystemExit(main())
