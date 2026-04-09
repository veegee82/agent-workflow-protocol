#!/usr/bin/env python3
"""E2E Scenario — Stall detection and convergence test.

Exercises the stall-detection and convergence improvements in v1.0.43:
  * B2: Oscillation detection (variance-based stall for flat confidence)
  * B5: Word-boundary decision matching (no false positives on negations)
  * C1: Placeholder-aware confidence derivation
  * General: forced_convergence → complete promotion

This test runs a multi-step analysis task with sub-manager delegation
and verifies that the loop converges or stall-detects gracefully.

Tags: e2e, s5, sub-manager, planning, tool-creation
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


TASK = (
    "You are a technology strategy consultant. Perform a comparative "
    "analysis of three emerging technologies for enterprise adoption: "
    "(1) WebAssembly for server-side computing, "
    "(2) Confidential Computing (TEEs), "
    "(3) Homomorphic Encryption for data processing. "
    "\n\n"
    "For EACH technology:\n"
    "- Write a 3-sentence executive summary of what it does\n"
    "- List exactly 2 concrete advantages and 2 concrete disadvantages\n"
    "- Assign a readiness score from 1-10 (integer, not a placeholder)\n"
    "\n"
    "Then synthesize a final recommendation ranking the three technologies "
    "by enterprise readiness. Use code execution to create a simple "
    "comparison table as a CSV file saved to _output_dir. "
    "The CSV must have columns: technology, readiness_score, top_advantage, "
    "top_disadvantage."
)


def verify(workflow_dir: Path, result: dict) -> dict:
    """Verify analysis quality and file output."""
    text = json.dumps(result, default=str).lower()

    # Also scan all output files for technology mentions
    for fp in (result.get("output_files") or []):
        try:
            text += "\n" + Path(fp).read_text(errors="replace").lower()
        except Exception:
            pass
    # Scan output directories for CSV/text files
    for output_dir in [workflow_dir / "output", workflow_dir / "workspace" / "output"]:
        if output_dir.exists():
            for f in output_dir.rglob("*"):
                if f.is_file() and f.suffix in (".csv", ".txt", ".json", ".md"):
                    try:
                        text += "\n" + f.read_text(errors="replace").lower()
                    except Exception:
                        pass

    # Check all 3 technologies are mentioned
    techs = ["webassembly", "confidential computing", "homomorphic"]
    techs_found = sum(1 for t in techs if t in text)

    # Check for numeric readiness scores (not placeholders)
    import re
    scores = re.findall(r"readiness[_\s]*score[\":\s]*(\d+)", text)
    has_scores = len(scores) >= 2

    # Check for output files (CSV)
    output_dir = workflow_dir / "workspace" / "output"
    csv_files = list(output_dir.rglob("*.csv")) if output_dir.exists() else []
    # Also check direct workspace
    csv_files += list(workflow_dir.rglob("*.csv"))
    has_csv = len(csv_files) > 0

    # Check no obvious placeholders
    has_placeholders = any(
        p in text for p in ("xx%", "todo", "???", "tbd")
    )

    # Check for sub-manager evidence (depth > 0 in any run dir)
    sub_manager_evidence = False
    for p in workflow_dir.rglob("run_manifest.json"):
        try:
            manifest = json.loads(p.read_text())
            if manifest.get("depth", 0) > 0:
                sub_manager_evidence = True
                break
        except Exception:
            pass

    ok = techs_found >= 3 and has_scores and not has_placeholders
    return {
        "ok": ok,
        "technologies_found": techs_found,
        "has_readiness_scores": has_scores,
        "scores_extracted": scores[:5],
        "has_csv": has_csv,
        "csv_files": [str(f) for f in csv_files[:3]],
        "has_placeholders": has_placeholders,
        "sub_manager_evidence": sub_manager_evidence,
    }


def main() -> int:
    report = run_e2e(
        slug="stall-convergence",
        title="Stall/Convergence — Tech Strategy Analysis",
        task=TASK,
        model="openai/gpt-4.1-nano",
        max_loops=20,
        max_total_tokens=2_000_000,
        max_wall_time=900,
        max_total_workers=30,
        max_depth=3,
        max_tool_calls=200,
        extra_config={
            "planning": {"enabled": True, "max_subtasks": 6},
            "stall_detection": {
                "enabled": True,
                "window": 3,
                "min_confidence_delta": 0.05,
                "strategy_switching": {
                    "enabled": True,
                    "strategies": ["decompose_finer", "simplify", "reframe"],
                },
            },
        },
        verifier=verify,
        tags=["e2e", "s5", "sub-manager", "planning", "tool-creation"],
    )

    ok = report["status"] in ("complete", "partial") and report.get("verify_ok")
    print(f"\n[stall_convergence] {'PASS' if ok else 'FAIL'} — status={report['status']}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
