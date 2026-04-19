#!/usr/bin/env python3
"""E2E test: cross-run tool/skill reuse within one experiment.

Runs two AgentWorkflow instances under the SAME session_id against the
SAME workflow_dir. The first run registers a dynamic tool and a skill.
The second run is given an unrelated-but-related task; the verifier
checks that the second run's graph payload exposes the tools/skills
persisted by the first run (reuse across runs) and that the shared/
symlinks carry the inventory forward.
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

TASK_A = r"""\
Run 1 of a multi-run experiment. Register ONE reusable tool and ONE
reusable skill that a later run of the same experiment will leverage.

Worker result must contain (at top level) ``tools_created``:

- ``name``: ``"dynamic.shout"``
- ``description``: ``"Upper-case a string."``
- ``parameters``: ``{"type":"object","properties":{"text":{"type":"string"}},"required":["text"]}``
- ``code``: ``def handler(*, text): return {"ok": True, "status": 200, "data": {"shout": str(text).upper()}, "error": None}``

and ``skills_created`` with one markdown string starting with
``# Skill: Shout Tool Usage`` (>=50 words) explaining when to use
``dynamic.shout``.

Write ``_output_dir/run_a_summary.json`` containing
``{"tool_registered": "dynamic.shout", "skill_registered": "shout_tool_usage"}``.
"""

TASK_B = r"""\
Run 2 of the SAME experiment. The previous run already registered
``dynamic.shout`` and a skill ``shout_tool_usage``. Reuse them — do NOT
re-register.

Phase 1: include ``required_tool_invocations: ["dynamic.shout"]`` in a
worker envelope. That worker MUST call ``dynamic.shout`` three times
(on ``"hello"``, ``"world"``, ``"awp"``) via the tool protocol.

Phase 2: Write ``_output_dir/run_b_results.json`` with
``{"samples": [{"input": "hello", "shout": "HELLO"}, ...]}``.

Phase 3: Write ``_output_dir/run_b_report.md`` (>=40 words) summarising
the reuse and confirming the tool and skill were available at the start
of this run.
"""


def _verify_a(workflow_dir: Path, _payload: dict) -> dict:
    shared_tools = workflow_dir / "shared" / "dynamic_tools"
    shared_skills = workflow_dir / "shared" / "skills"
    tool_json = shared_tools / "dynamic.shout.json"
    has_tool = tool_json.exists()
    has_skill = any(p.name.startswith("shout_tool_usage") for p in shared_skills.glob("*.md")) if shared_skills.is_dir() else False
    return {
        "ok": has_tool and has_skill,
        "checks": {
            "tool_persisted_in_shared": has_tool,
            "skill_persisted_in_shared": has_skill,
        },
        "shared_tools": sorted(p.name for p in shared_tools.glob("*.json")) if shared_tools.is_dir() else [],
        "shared_skills": sorted(p.name for p in shared_skills.glob("*.md")) if shared_skills.is_dir() else [],
    }


def _verify_b(workflow_dir: Path, _payload: dict) -> dict:
    from server.services.graph_builder import build_graph, find_run_dir
    run_dir = find_run_dir(workflow_dir)
    if run_dir is None:
        return {"ok": False, "error": "no run_dir"}
    graph = build_graph(run_dir)
    registry = graph.tool_registry or []
    skills = graph.skill_registry or []
    fqns = {t.get("fqn") for t in registry}
    skill_names = {s.get("name") for s in skills}
    tool_called = any(t.get("call_count", 0) >= 1 for t in registry if t.get("fqn") == "dynamic.shout")
    files = {p.name for p in workflow_dir.rglob("*") if p.is_file()}
    missing = {"run_b_results.json", "run_b_report.md"} - files
    checks = {
        "tool_visible_in_run_b_registry": "dynamic.shout" in fqns,
        "skill_visible_in_run_b_registry": any("shout" in n for n in skill_names),
        "tool_invoked_in_run_b": tool_called,
        "deliverables_present": not missing,
        "workspace_tools_is_symlink": (workflow_dir / "workspace" / "dynamic_tools").is_symlink(),
    }
    return {
        "ok": all(checks.values()),
        "checks": checks,
        "tool_registry_fqns": sorted(fqns),
        "skill_names": sorted(skill_names),
        "missing_files": sorted(missing),
    }


def main() -> int:
    print("=== RUN A (register tool+skill) ===")
    report_a = run_e2e(
        slug="cross-run-reuse",
        title="Cross-Run Reuse — shared tool+skill inventory",
        task=TASK_A,
        model="openai/gpt-5-mini",
        worker_model="deepseek/deepseek-chat-v3.1",
        max_loops=10,
        max_total_tokens=1_000_000,
        max_wall_time=600,
        max_total_workers=6,
        max_depth=1,
        max_tool_calls=40,
        verifier=_verify_a,
        extra_config={
            "code_mode": {"enabled": True},
            "tool_creation": {"enabled": True},
        },
        tags=["e2e", "cross-run-reuse", "run-a"],
    )
    session_id = report_a["session_id"]
    workflow_dir_a = report_a["workflow_dir"]
    ok_a = report_a.get("verify_ok")
    print(f"[run A] session={session_id} verify={ok_a}")

    if not ok_a:
        print("Run A did not persist the registry — aborting Run B.")
        return 1

    print("\n=== RUN B (reuse tool+skill from Run A) ===")
    report_b = run_e2e(
        slug="cross-run-reuse",
        title="Cross-Run Reuse — shared tool+skill inventory",
        task=TASK_B,
        model="openai/gpt-5-mini",
        worker_model="deepseek/deepseek-chat-v3.1",
        max_loops=10,
        max_total_tokens=1_000_000,
        max_wall_time=600,
        max_total_workers=6,
        max_depth=1,
        max_tool_calls=40,
        verifier=_verify_b,
        extra_config={
            "code_mode": {"enabled": True},
            "tool_creation": {"enabled": True},
        },
        tags=["e2e", "cross-run-reuse", "run-b"],
        session_id=session_id,
        workflow_dir=Path(workflow_dir_a),  # explicit reuse
    )
    ok_b = report_b.get("verify_ok")
    wall = report_a.get("duration_s", 0) + report_b.get("duration_s", 0)

    print(f"\n{'='*64}")
    print(f"[cross_run_reuse] run_a verify={ok_a} run_b verify={ok_b} total_wall={wall:.0f}s")
    print(json.dumps({"run_a": report_a.get("verification"), "run_b": report_b.get("verification")}, indent=2))

    return 0 if (ok_a and ok_b) else 1


if __name__ == "__main__":
    raise SystemExit(main())
