#!/usr/bin/env python3
"""Quick smoke E2E test to verify live monitoring in the UI.

This is a lightweight test (tagged 'quick') that runs a small delegation
loop and verifies that:
  1. The experiment appears in the SQLite DB with status='running'.
  2. Events (iteration.start, worker.spawn, etc.) are persisted live.
  3. The final status is updated to 'complete' or 'partial'.

Usage:
    # Start the UI server first:
    python packages/awp-ui/start_debug.py --skip-build --no-reload

    # Then run this test:
    python examples/e2e/quick_smoke.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# Wire up import paths so _harness and server modules are importable.
_project_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_project_root / "packages" / "awp-core" / "src"))
sys.path.insert(0, str(_project_root / "packages" / "awp-runtime" / "src"))
sys.path.insert(0, str(_project_root / "packages" / "awp-ui" / "server"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _harness import run_e2e  # noqa: E402


def main() -> int:
    report = run_e2e(
        slug="quick-smoke",
        title="Quick Smoke Test — Live Monitoring",
        task=(
            "Calculate the sum of the first 10 prime numbers. "
            "Use code execution to compute the answer. "
            "Return the final sum as a JSON object with keys: "
            "'primes' (list of primes), 'sum' (the total), 'confidence' (0-1)."
        ),
        model="openai/gpt-4.1-nano",
        max_loops=5,
        max_total_tokens=500_000,
        max_wall_time=120,
        max_total_workers=5,
        max_depth=2,
        max_tool_calls=20,
        tags=["e2e", "quick", "smoke"],
    )

    if report["status"] in ("complete", "partial"):
        print("\n[quick_smoke] SUCCESS — experiment tracked live in DB")
        return 0
    else:
        print(f"\n[quick_smoke] FAIL — status={report['status']}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
