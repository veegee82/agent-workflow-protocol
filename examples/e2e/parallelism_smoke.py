#!/usr/bin/env python3
"""E2E smoke test for parallelism flags.

Exercises all opt-in parallelism improvements in a single run:
  - Release A: thread-safety locks (always on, no flag)
  - Release C: ``pipeline_critique_planning`` (opt-in, enabled here)
  - Release D-1: ``parallel_gate_chain`` (opt-in, enabled here)
  - Release D-2: ``token_budget_reservation`` (opt-in, enabled here)

Task intentionally avoids shared mutable state — each worker writes only
its own per-compound output file, never a shared coordination file. This
keeps the smoke-test resilient to LLM worker-code variability while still
driving parallel worker spawns through the delegation loop.
"""

from __future__ import annotations

import sys
from pathlib import Path

_project_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_project_root / "packages" / "awp-core" / "src"))
sys.path.insert(0, str(_project_root / "packages" / "awp-runtime" / "src"))
sys.path.insert(0, str(_project_root / "packages" / "awp-ui" / "server"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _harness import run_e2e  # noqa: E402

COMPOUNDS = ["Zylithium", "Auralium", "Pyroxene-X", "Cryogel"]

TASK = (
    "Classify 4 fictional chemical compounds into exactly 4 categories: "
    "(A) structural metals, (B) energy carriers, "
    "(C) exotic / quantum materials, (D) biological / life-support reagents. "
    "The 4 compounds are: " + ", ".join(COMPOUNDS) + ". "
    "Spawn parallel workers — one worker per compound. Each worker is "
    "fully independent: it reads no shared files, writes no shared files, "
    "and its only job is to (1) classify its assigned compound into A/B/C/D "
    "and (2) write exactly one per-compound JSON to "
    "_output_dir + '/result_<compound_lowercase>.json' with keys "
    "'compound', 'category', 'reason'. "
    "After all workers finish, produce one final summary listing all 4 "
    "compounds grouped by their assigned category A, B, C, D."
)


def main() -> int:
    report = run_e2e(
        slug="parallelism-smoke",
        title="Parallelism Smoke — Release A/C/D flags on",
        task=TASK,
        max_loops=15,
        max_total_tokens=1_500_000,
        max_wall_time=1800,
        max_depth=2,
        max_total_workers=20,
        max_tool_calls=300,
        extra_config={
            "pipeline_critique_planning": True,
            "parallel_gate_chain": True,
            "token_budget_reservation": True,
        },
        tags=["e2e", "parallelism", "release-acd", "smoke"],
    )
    status = report.get("status", "unknown")
    print(f"\n[parallelism_smoke] final status={status}")
    return 0 if status in ("complete", "partial") else 1


if __name__ == "__main__":
    sys.exit(main())
