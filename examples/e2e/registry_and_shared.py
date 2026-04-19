#!/usr/bin/env python3
"""E2E test: Registry panels + ``shared/`` cross-run store integrity.

Verifies the fixes for the UI graph observability stack:

  * The Tool Registry side panel is populated (``workspace/dynamic_tools``).
  * The Skill Registry side panel is populated (``workspace/skills``).
  * ``workspace/dynamic_tools`` and ``workspace/skills`` are **symlinks**
    to ``shared/`` so repeat runs of the same experiment reuse the
    inventory.
  * ``shared/dynamic_tools/*.json`` actually contains the factory
    artefacts (not the empty directory we saw before the fix).
  * The registered tool is **invoked via the tool protocol** (not
    reimplemented inside ``code.execute``) so ``call_count`` increments
    and the registry's "used" indicator lights up.

The task is deliberately compact so the loop closes within ~15 min.
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
Run a compact text-processing loop that registers a reusable tool, a
reusable skill, and invokes the tool twice. All deliverables must be
reachable on disk after the run completes.

## Phase 1 — Register exactly ONE dynamic tool

Spawn one worker whose result JSON contains ``tools_created`` with EXACTLY
this entry:

- ``name``: ``"dynamic.word_count"``
- ``description``: ``"Count words in a text."``
- ``parameters``: ``{"type":"object","properties":{"text":{"type":"string"}},"required":["text"]}``
- ``code``: Python module defining
  ``def handler(*, text):`` that returns
  ``{"ok": True, "status": 200, "data": {"count": <int>}, "error": None}``.

Rules:
- Do NOT write any ``.py`` file to disk for this tool.
- The ONLY valid registration path is returning ``tools_created`` in the
  worker result JSON. The runtime persists the JSON descriptor to
  ``workspace/dynamic_tools/dynamic.word_count.json`` automatically.

## Phase 2 — Persist ONE reusable skill

In the same worker result (or a subsequent worker), return a
``skills_created`` array with EXACTLY one markdown skill:

- A markdown document of at least 50 words describing when to use
  ``dynamic.word_count`` (``# Skill: Word Count Usage`` as the heading).

The runtime persists this under ``workspace/skills/word_count_usage.md``.

## Phase 3 — Invoke the tool TWICE via the tool protocol

The next iteration's DELEGATE decision must spawn ONE worker whose
``tools_allowed`` list contains ``"dynamic.word_count"``. The worker MUST
call the tool via the tool protocol twice (e.g. once on the string
``"hello world"`` and once on ``"the quick brown fox"``). Do NOT
reimplement the logic inline in ``code.execute``.

Write ``_output_dir/word_count_results.json`` with:
``{"samples": [{"text": "hello world", "count": 2}, {"text": "the quick brown fox", "count": 4}]}``.

## Phase 4 — Short synthesis

Produce ``_output_dir/report.md`` (>=80 words) containing:
- Which dynamic tool was created and how many times it was invoked.
- Which skill was persisted.

## Required deliverables

- ``_output_dir/word_count_results.json``
- ``_output_dir/report.md``
- ``workspace/dynamic_tools/dynamic.word_count.json``  (auto-written)
- ``workspace/skills/word_count_usage.md``             (auto-written)
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
    skills = graph.skill_registry or []

    # Shared/ vs workspace/ symlink integrity
    shared_tools = workflow_dir / "shared" / "dynamic_tools"
    shared_skills = workflow_dir / "shared" / "skills"
    ws_tools = workflow_dir / "workspace" / "dynamic_tools"
    ws_skills = workflow_dir / "workspace" / "skills"

    shared_tools_has = sorted(p.name for p in shared_tools.glob("*.json")) if shared_tools.is_dir() else []
    shared_skills_has = sorted(p.name for p in shared_skills.glob("*.md")) if shared_skills.is_dir() else []

    files = {p.name for p in workflow_dir.rglob("*") if p.is_file()}
    required_files = {"word_count_results.json", "report.md"}
    missing = required_files - files

    checks = {
        "has_manager": types.get("manager", 0) >= 1,
        "has_iteration": types.get("iteration", 0) >= 2,
        "has_worker": types.get("worker", 0) >= 2,
        "has_toolCall": types.get("toolCall", 0) >= 1,
        "tool_registry_has_entry": len(registry) >= 1,
        "skill_registry_has_entry": len(skills) >= 1,
        "workspace_tools_is_symlink": ws_tools.is_symlink(),
        "workspace_skills_is_symlink": ws_skills.is_symlink(),
        "shared_dynamic_tools_populated": len(shared_tools_has) >= 1,
        "shared_skills_populated": len(shared_skills_has) >= 1,
        "tool_was_invoked": any(t.get("call_count", 0) >= 1 for t in registry),
        "required_files_present": not missing,
    }
    return {
        "ok": all(checks.values()),
        "checks": checks,
        "node_type_counts": types,
        "tool_registry": [
            {"fqn": t.get("fqn"), "call_count": t.get("call_count")} for t in registry
        ],
        "skill_registry_names": [s.get("name") for s in skills],
        "shared_dynamic_tools": shared_tools_has,
        "shared_skills": shared_skills_has,
        "missing_files": sorted(missing),
        "run_dir": str(run_dir),
    }


def main() -> int:
    report = run_e2e(
        slug="registry-and-shared",
        title="Registry + Shared Store — Tool/Skill reuse verification",
        task=TASK,
        model="openai/gpt-5-mini",
        worker_model="deepseek/deepseek-chat-v3.1",
        max_loops=15,
        max_total_tokens=2_000_000,
        max_wall_time=1500,
        max_total_workers=15,
        max_depth=2,
        max_tool_calls=80,
        verifier=_verify,
        extra_config={
            "code_mode": {"enabled": True},
            "tool_creation": {"enabled": True},
        },
        tags=["e2e", "tool-creation", "skill-persistence", "registry"],
    )

    status = report["status"]
    verify_ok = report.get("verify_ok")
    verification = report.get("verification", {})
    wall = report.get("duration_s", 0)

    print(f"\n{'='*64}")
    print(f"[registry_and_shared] status={status} verify={verify_ok} wall={wall:.0f}s")
    if verification:
        print(json.dumps(verification, indent=2))

    if status == "complete" and verify_ok:
        print("[registry_and_shared] PASS")
        return 0
    print("[registry_and_shared] FAIL")
    if report.get("error"):
        print(f"  error: {report['error']}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
