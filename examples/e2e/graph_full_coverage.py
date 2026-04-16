#!/usr/bin/env python3
"""E2E test: Full graph-element coverage for the UI visualisation.

Fictional task designed so the resulting run populates **every** graph
layer the UI renders:

  * Root task node
  * Root Manager
  * Multiple Iterations (mix of DELEGATE + COMPLETE)
  * Multiple Workers (parallel fan-out in at least one iteration)
  * Sub-Manager (naturally emerges from nested planning)
  * Tool Calls (file.write, code.execute, plus the dynamic-factory tools)
  * Dynamic Tool Registry side panel (tools invoked multiple times so
    the registry shows non-zero ``call_count``)

Usage
-----
    python packages/awp-ui/start_debug.py --skip-build --no-reload
    python examples/e2e/graph_full_coverage.py
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
Build a tiny text-analytics pipeline. You MUST register two reusable tools
through the runtime's Dynamic Tool Factory (NOT as plain .py files on
disk). The factory is activated automatically when a worker returns a
``tools_created`` array in its result JSON. The created tools then become
callable by name in later iterations — and they MUST be reused.

## Phase 1 — Register two reusable tools via the Dynamic Tool Factory

Spawn a worker whose result JSON contains ``tools_created`` with EXACTLY
these two entries (both in the ``dynamic`` namespace):

### Tool 1: dynamic.text_stats
- ``name``: ``"dynamic.text_stats"``
- ``description``: ``"Compute basic stats for a text."``
- ``parameters``: ``{"type":"object","properties":{"text":{"type":"string"}},"required":["text"]}``
- ``code``: a Python module string defining
  ``def handler(*, text):`` that returns
  ``{"ok": True, "status": 200, "data": {"word_count": <int>, "sentence_count": <int>, "avg_word_len": <float>, "unique_ratio": <float>}, "error": None}``.

### Tool 2: dynamic.keyword_density
- ``name``: ``"dynamic.keyword_density"``
- ``description``: ``"Top-k non-stopword tokens with frequency and density."``
- ``parameters``: ``{"type":"object","properties":{"text":{"type":"string"},"top_k":{"type":"integer","default":5}},"required":["text"]}``
- ``code``: a Python module string defining
  ``def handler(*, text, top_k=5):`` returning
  ``{"ok": True, "status": 200, "data": {"top": [{"token": str, "count": int, "density": float}, ...]}, "error": None}``.

STRICT RULES for this phase:
- Do NOT write these tools as ``.py`` files to ``workspace/tools/`` or anywhere else on disk.
- Do NOT call ``file.write`` for the tool implementations.
- The ONLY valid way to register them is by returning a ``tools_created``
  array in the worker result JSON. The runtime's DynamicToolFactory will
  persist them to ``workspace/dynamic_tools/*.json`` automatically.
- After the worker returns, verify registration by calling ``tool.list``
  and confirm both ``dynamic.text_stats`` and ``dynamic.keyword_density``
  are listed.

## Phase 2 — Parallel analysis reusing the registered tools

Create two short fictional paragraphs (6-8 sentences each) inline via
``code.execute`` and write them to ``_output_dir``:

  - ``doc_A.txt`` — a paragraph about a fictional lunar observatory
    named "Selene Array" discovering rhythmic radio pulses.
  - ``doc_B.txt`` — a paragraph about a deep-sea station "Abyssal-9"
    cataloguing bioluminescent fauna.

Then in ONE DELEGATE decision spawn TWO parallel workers. Each worker MUST:

  - Read its assigned document via ``file.read``.
  - Call BOTH ``dynamic.text_stats`` AND ``dynamic.keyword_density`` on
    the document — direct tool invocations, not reimplementations.
  - Write its findings to ``_output_dir/analysis_<X>.json`` with schema
    ``{"doc": "<name>", "stats": {...}, "keywords": [...]}``.

This drives ``call_count >= 2`` for both dynamic tools in the registry.

## Phase 3 — Final synthesis

Produce ``_output_dir/report.md`` (>=250 words) summarising:

  - A markdown table with word_count / sentence_count / avg_word_len /
    unique_ratio for both documents.
  - Top keywords per document (from keyword_density).
  - Which dynamic tools were created and how often each was invoked.

## Required deliverables on disk

  - ``_output_dir/doc_A.txt``
  - ``_output_dir/doc_B.txt``
  - ``_output_dir/analysis_A.json``
  - ``_output_dir/analysis_B.json``
  - ``_output_dir/report.md``
  - ``workspace/dynamic_tools/dynamic.text_stats.json``       (auto-written by factory)
  - ``workspace/dynamic_tools/dynamic.keyword_density.json``  (auto-written by factory)

Do NOT include TODO/FIXME/placeholder strings in any deliverable.
"""


def _verify(workflow_dir: Path, _payload: dict) -> dict:
    """Check that the produced run exercises every graph element."""
    from server.services.graph_builder import build_graph, find_run_dir

    run_dir = find_run_dir(workflow_dir)
    if run_dir is None:
        return {"ok": False, "error": "no run_dir found under workflow_dir"}

    graph = build_graph(run_dir)
    node_types: dict[str, int] = {}
    for n in graph.nodes:
        node_types[n.type] = node_types.get(n.type, 0) + 1

    registry = graph.tool_registry or []
    called_tools = [t for t in registry if t.get("call_count", 0) > 0]
    reused_tools = [t for t in registry if t.get("call_count", 0) >= 2]

    files = {p.name for p in workflow_dir.rglob("*") if p.is_file()}
    required_files = {
        "doc_A.txt", "doc_B.txt",
        "analysis_A.json", "analysis_B.json",
        "report.md",
    }
    missing_files = required_files - files

    checks = {
        "has_task": node_types.get("task", 0) >= 1,
        "has_manager": node_types.get("manager", 0) >= 1,
        "has_iteration": node_types.get("iteration", 0) >= 2,
        "has_worker": node_types.get("worker", 0) >= 2,
        "has_submanager": (
            node_types.get("submanager", 0) >= 1
            or any(n.data.get("isSubmanager") for n in graph.nodes)
        ),
        "has_toolCall": node_types.get("toolCall", 0) >= 5,
        "has_tool_registry": len(registry) >= 2,
        "tools_were_called": len(called_tools) >= 1,
        "tools_were_reused": len(reused_tools) >= 1,
        "required_files_present": not missing_files,
    }

    return {
        "ok": all(checks.values()),
        "checks": checks,
        "node_type_counts": node_types,
        "registry_size": len(registry),
        "registry_called": len(called_tools),
        "registry_reused": len(reused_tools),
        "missing_files": sorted(missing_files),
        "run_dir": str(run_dir),
    }


def main() -> int:
    report = run_e2e(
        slug="graph-full-coverage",
        title="Graph Full Coverage — Manager + SubManager + Workers + ToolCalls + Registry",
        task=TASK,
        model="openai/gpt-5-mini",
        worker_model="deepseek/deepseek-chat-v3.1",
        max_loops=30,
        max_total_tokens=4_000_000,
        max_wall_time=3000,
        max_total_workers=30,
        max_depth=3,
        max_tool_calls=300,
        verifier=_verify,
        extra_config={
            "code_mode": {"enabled": True},
            "tool_creation": {"enabled": True},
        },
        tags=[
            "e2e",
            "s5",
            "tool-creation",
            "sub-manager",
            "planning",
            "graph-coverage",
        ],
    )

    status = report["status"]
    verify_ok = report.get("verify_ok")
    verification = report.get("verification", {})
    wall = report.get("duration_s", 0)

    print(f"\n{'='*64}")
    print(f"[graph_full_coverage] status={status} verify={verify_ok} wall={wall:.0f}s")
    if verification:
        print("[graph_full_coverage] checks:")
        print(json.dumps(verification, indent=2))

    if status == "complete" and verify_ok:
        print("[graph_full_coverage] PASS")
        return 0
    print("[graph_full_coverage] FAIL")
    if report.get("error"):
        print(f"  error: {report['error']}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
