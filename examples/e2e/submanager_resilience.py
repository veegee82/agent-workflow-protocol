#!/usr/bin/env python3
"""E2E test: Sub-manager resilience — plan-loop gates, placeholder gate,
and defect-category tracking.

Covers three runtime fixes:
  1. Plan-loop counter is NOT inherited by sub-managers (fresh counters).
  2. Placeholder gate ignores TODO/FIXME in code comments.
  3. Recurring critique defect categories are tracked across delegations
     and force a strategy change after 3 repeats (hard cap at 5).

The task asks the agent to:
  - Write a small Python utility with TODO comments in the code
  - Produce a summary report referencing the code
  - Delegate sub-tasks (triggers sub-manager promotion at depth 2+)

This exercises the full delegation loop with critique, sub-managers, and
code generation — the exact scenario where the three bugs manifested.

Usage:
    python packages/awp-ui/start_debug.py --skip-build --no-reload
    python examples/e2e/submanager_resilience.py
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


def main() -> int:
    report = run_e2e(
        slug="submanager-resilience",
        title="Sub-Manager Resilience — Plan Loop + Placeholder + Defect Tracking",
        task=(
            "Build a small Python data-processing utility and a quality report.\n\n"
            "## Deliverables\n"
            "1. A Python file `data_processor.py` that:\n"
            "   - Defines a function `process(data: list[dict]) -> dict` that "
            "computes basic statistics (count, mean, median, std) for numeric fields\n"
            "   - Include `# TODO: add streaming support for large datasets` and "
            "`# FIXME: handle NaN values gracefully` as legitimate code comments\n"
            "   - Include proper docstrings and type hints\n"
            "2. A test file `test_data_processor.py` that verifies the function "
            "with at least 3 test cases using `assert` statements\n"
            "3. Run both files via `code.execute` to prove they work\n"
            "4. A summary report (as your final answer) listing:\n"
            "   - Functions implemented\n"
            "   - Test results (pass/fail)\n"
            "   - Code quality notes\n\n"
            "IMPORTANT: The code files MUST contain the TODO and FIXME comments "
            "listed above — they are intentional design annotations, NOT placeholders."
        ),
        model="openai/gpt-4.1-mini",
        max_loops=15,
        max_total_tokens=2_000_000,
        max_wall_time=600,
        max_total_workers=20,
        max_depth=3,
        max_tool_calls=80,
        tags=["e2e", "s5", "sub-manager", "critique", "planning"],
    )

    status = report["status"]
    wall = report.get("wall_time_s", 0)

    print(f"\n{'='*60}")
    print(f"[submanager_resilience] status={status}  wall={wall:.0f}s")

    # Acceptance criteria:
    # - Must reach 'complete' or 'partial' (not 'failed')
    # - Must finish within wall-time budget
    if status in ("complete", "partial"):
        print("[submanager_resilience] PASS")
        return 0
    else:
        print(f"[submanager_resilience] FAIL — status={status}")
        if report.get("error"):
            print(f"  error: {report['error']}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
