#!/usr/bin/env python3
"""E2E test: required_tool_invocations deterministic gate.

Exercises the full pipeline for the anti-reimplementation gate:

  * Phase 1: register one dynamic tool via ``tools_created``.
  * Phase 2: the manager delegates with
    ``required_tool_invocations: ["dynamic.reverse_text"]`` in the
    worker envelope. The worker MUST invoke the tool via the tool
    protocol (not reimplement ``[::-1]`` inside ``code.execute``).
  * The deterministic gate in the runtime rejects any worker that
    omits the required invocation and triggers a repair iteration.

Verifier checks:
  - tool was registered in the registry
  - at least one worker has a ``_required_tool_gate.satisfied=True``
    OR ``tool_registry.call_count >= 1`` (i.e. the tool WAS invoked
    by the final passing worker)
  - if any worker record contains ``_required_tool_gate.satisfied=False``
    that's evidence the gate fired and caused a repair (expected for
    the first attempt with models that instinctively reimplement).
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

from _harness import run_e2e  # noqa: E402

TASK = r"""\
Compact two-phase test that exercises the runtime's
``required_tool_invocations`` gate.

## Phase 1 — Register ONE dynamic tool

Spawn ONE worker whose result JSON contains ``tools_created`` with
EXACTLY this entry:

- ``name``: ``"dynamic.reverse_text"``
- ``description``: ``"Reverse a string (character order)."``
- ``parameters``: ``{"type":"object","properties":{"text":{"type":"string"}},"required":["text"]}``
- ``code``: Python module defining
  ``def handler(*, text):`` that returns
  ``{"ok": True, "status": 200, "data": {"reversed": text[::-1]}, "error": None}``.

Do NOT write ``.py`` files to disk for this tool. The ONLY valid
registration path is ``tools_created`` in the worker result. The
runtime will persist ``workspace/dynamic_tools/dynamic.reverse_text.json``.

## Phase 2 — Invoke the tool via the tool protocol (GATE)

Next DELEGATE MUST include ``"required_tool_invocations":
["dynamic.reverse_text"]`` in the single worker envelope. The worker
MUST call ``dynamic.reverse_text`` via the tool protocol on the three
inputs below — NOT reimplement ``[::-1]`` inside ``code.execute``:

  - ``"kayak"``
  - ``"hello"``
  - ``"AWP"``

Write ``_output_dir/reverse_results.json`` in the shape
``{"samples": [{"input": "kayak", "reversed": "..."}, ...]}``.

If the worker skips the tool and reimplements the logic, the runtime
gate will reject the result and spawn a repair worker. Design the
prompt so the first worker calls the tool correctly.

## Phase 3 — Tiny synthesis

Produce ``_output_dir/gate_report.md`` (>=60 words) explaining:
- which dynamic tool was registered
- how many times it was called
- whether the ``required_tool_invocations`` gate was satisfied on the
  first attempt (if available in the run metadata)

## Required deliverables

- ``_output_dir/reverse_results.json``
- ``_output_dir/gate_report.md``
- ``workspace/dynamic_tools/dynamic.reverse_text.json``
"""


def _verify(workflow_dir: Path, _payload: dict) -> dict:
    from server.services.graph_builder import build_graph, find_run_dir

    run_dir = find_run_dir(workflow_dir)
    if run_dir is None:
        return {"ok": False, "error": "no run_dir"}

    graph = build_graph(run_dir)
    types: dict[str, int] = {}
    for n in graph.nodes:
        types[n.type] = types.get(n.type, 0) + 1

    registry = graph.tool_registry or []

    # Walk worker result.json files to find gate evidence
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

    # tool invocation count from the aggregated registry
    tool_called = any(t.get("call_count", 0) >= 1 for t in registry)

    files = {p.name for p in workflow_dir.rglob("*") if p.is_file()}
    required_files = {"reverse_results.json", "gate_report.md"}
    missing = required_files - files

    shared_tools = workflow_dir / "shared" / "dynamic_tools"
    shared_has = sorted(p.name for p in shared_tools.glob("*.json")) if shared_tools.is_dir() else []

    checks = {
        "tool_registered": len(registry) >= 1,
        "workspace_tools_is_symlink": (workflow_dir / "workspace" / "dynamic_tools").is_symlink(),
        "shared_dynamic_tools_populated": len(shared_has) >= 1,
        "tool_was_invoked_via_protocol": tool_called,
        "required_files_present": not missing,
        # Gate activity: at least one of these must be True. If the first
        # worker honoured the constraint, gate_fired stays False but
        # tool_called is True. If the first worker reimplemented, gate
        # fires AND a subsequent repair must have satisfied it.
        "gate_mechanism_exercised": gate_fired or tool_called,
    }
    return {
        "ok": all(checks.values()),
        "checks": checks,
        "node_type_counts": types,
        "tool_registry": [
            {"fqn": t.get("fqn"), "call_count": t.get("call_count")} for t in registry
        ],
        "gate_fired_at_least_once": gate_fired,
        "gate_satisfied_after_repair": gate_satisfied_eventually,
        "shared_dynamic_tools": shared_has,
        "missing_files": sorted(missing),
        "run_dir": str(run_dir),
    }


def main() -> int:
    report = run_e2e(
        slug="required-tool-gate",
        title="Required Tool Invocations Gate — deterministic enforcement",
        task=TASK,
        model="openai/gpt-5-mini",
        worker_model="deepseek/deepseek-chat-v3.1",
        max_loops=12,
        max_total_tokens=1_500_000,
        max_wall_time=900,
        max_total_workers=10,
        max_depth=2,
        max_tool_calls=60,
        verifier=_verify,
        extra_config={
            "code_mode": {"enabled": True},
            "tool_creation": {"enabled": True},
        },
        tags=["e2e", "tool-creation", "required-tool-gate", "registry"],
    )

    status = report["status"]
    verify_ok = report.get("verify_ok")
    verification = report.get("verification", {})
    wall = report.get("duration_s", 0)

    print(f"\n{'='*64}")
    print(f"[required_tool_gate] status={status} verify={verify_ok} wall={wall:.0f}s")
    if verification:
        print(json.dumps(verification, indent=2))
    return 0 if (status == "complete" and verify_ok) else 1


if __name__ == "__main__":
    raise SystemExit(main())
