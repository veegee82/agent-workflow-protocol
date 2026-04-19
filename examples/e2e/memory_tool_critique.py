#!/usr/bin/env python3
"""E2E Scenario — Memory persistence + tool creation + critique integration.

Exercises the full feature stack including all v1.0.43 fixes:
  * B4: Auto-curation of run knowledge into long-term memory
  * Tool creation: dynamic tool factory generates and validates new tools
  * Critique: inline critique with repair cycles (A2 max-rejection bypass)
  * Memory: cross-run memory persistence (two sequential runs)
  * A3: DB status promotion after verification

Run 1: Research and create a custom analysis tool, exercise critique loop.
Run 2: Reuse prior memory to build on run 1's findings.

Tags: e2e, s5, memory, tool-creation, critique
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

from _harness import make_experiment_dir, run_e2e  # noqa: E402

TASK_1 = (
    "Research the energy efficiency of three data center cooling methods: "
    "(1) Liquid immersion cooling, (2) Free-air cooling, (3) Rear-door "
    "heat exchangers. For each method, determine: PUE improvement "
    "(a percentage number, NOT a placeholder), typical deployment cost "
    "range, and one key limitation. "
    "\n\n"
    "Use code execution to create a Python function that calculates "
    "annual energy savings given a baseline PUE and the improved PUE. "
    "Test the function with sample data. "
    "\n\n"
    "Produce a final JSON report with key 'methods' (list of 3 dicts, "
    "each with 'name', 'pue_improvement_pct', 'cost_range', 'limitation') "
    "and 'energy_calculator_tested' (boolean)."
)

TASK_2 = (
    "Based on prior knowledge about data center cooling methods "
    "(liquid immersion, free-air, rear-door heat exchangers), "
    "recommend the optimal cooling strategy for a 10MW hyperscale "
    "data center in Northern Europe. Consider the climate advantage "
    "of the location. Cite specific PUE numbers from prior findings. "
    "Produce a recommendation report with the chosen method, "
    "estimated annual energy savings in MWh (compute using code), "
    "and a 3-point implementation roadmap."
)


def _scan_all_text(workflow_dir: Path, result: dict) -> str:
    """Collect all text from result dict and workspace files."""
    text = json.dumps(result, default=str).lower()
    for fp in (result.get("output_files") or []):
        try:
            text += "\n" + Path(fp).read_text(errors="replace").lower()
        except Exception:
            pass
    # Scan workspace for JSON, MD, TXT, CSV files
    for p in workflow_dir.rglob("*"):
        if p.is_file() and p.suffix in (".json", ".md", ".txt", ".csv", ".log"):
            try:
                content = p.read_text(errors="replace").lower()
                if len(content) < 50_000:  # skip huge files
                    text += "\n" + content
            except Exception:
                pass
    return text


def verify_run1(workflow_dir: Path, result: dict) -> dict:
    """Verify run 1 produced cooling method analysis + tool creation."""
    text = _scan_all_text(workflow_dir, result)

    # Check all 3 cooling methods mentioned
    methods = ["immersion", "free-air", "rear-door"]
    methods_found = sum(1 for m in methods if m in text)

    # Check for PUE numbers (not placeholders)
    import re
    pue_numbers = re.findall(r"pue[_\s]*improvement[^\d]*(\d+\.?\d*)", text)
    has_pue = len(pue_numbers) >= 1

    # Check for code execution evidence
    code_evidence = "energy" in text and ("savings" in text or "calculator" in text)

    # Check for curation report
    curation = result.get("curation_report") is not None

    # Check no placeholders
    has_placeholders = any(p in text for p in ("xx%", "todo", "???", "tbd"))

    ok = methods_found >= 2 and not has_placeholders and (has_pue or code_evidence)
    return {
        "ok": ok,
        "methods_found": methods_found,
        "has_pue_numbers": has_pue,
        "pue_extracted": pue_numbers[:5],
        "code_evidence": code_evidence,
        "curation_present": curation,
        "has_placeholders": has_placeholders,
    }


def verify_run2(workflow_dir: Path, result: dict) -> dict:
    """Verify run 2 builds on prior memory and produces recommendation."""
    text = _scan_all_text(workflow_dir, result)

    # Check recommendation content
    has_recommendation = any(
        w in text for w in ("recommend", "optimal", "chosen", "best")
    )
    has_europe = "europe" in text or "northern" in text
    has_roadmap = "roadmap" in text or "implementation" in text

    # Check for prior memory evidence
    b4_active = result.get("curation_report") is not None
    digest_active = result.get("_digest_sha") is not None

    # Check for memory files from run 1
    memory_dir = workflow_dir / "memory"
    has_memory_files = (
        memory_dir.exists()
        and any(memory_dir.rglob("*.md"))
    )

    # Check prior memory injection
    prior_memory_injected = False
    for p in workflow_dir.rglob("*.json"):
        try:
            content = p.read_text(errors="replace")
            if "PRIOR RUN MEMORY" in content:
                prior_memory_injected = True
                break
        except Exception:
            pass

    ok = has_recommendation and (b4_active or digest_active)
    return {
        "ok": ok,
        "has_recommendation": has_recommendation,
        "has_europe_context": has_europe,
        "has_roadmap": has_roadmap,
        "curation_present": b4_active,
        "digest_active": digest_active,
        "has_memory_files": has_memory_files,
        "prior_memory_injected": prior_memory_injected,
    }


def main() -> int:
    shared_dir = make_experiment_dir("s5-memory-tool-critique")
    print(f"[memory_tool_critique] shared workflow_dir={shared_dir}")

    r1 = run_e2e(
        slug="s5-memory-tool-critique-run1",
        title="S5 Memory/Tool/Critique — Cooling Research (Run 1)",
        task=TASK_1,
        model="openai/gpt-4.1-nano",
        max_loops=20,
        max_total_tokens=2_000_000,
        max_wall_time=900,
        max_total_workers=30,
        max_depth=3,
        max_tool_calls=200,
        workflow_dir=shared_dir,
        extra_config={
            "critique": {
                "enabled": True,
                "min_score_to_complete": 0.5,
                "max_repair_attempts": 2,
            },
        },
        verifier=verify_run1,
        tags=["e2e", "s5", "memory", "tool-creation", "critique"],
    )
    if r1["status"] not in ("complete", "partial"):
        print(f"[memory_tool_critique] run1 failed — status={r1['status']}")
        return 1

    r2 = run_e2e(
        slug="s5-memory-tool-critique-run2",
        title="S5 Memory/Tool/Critique — Cooling Recommendation (Run 2)",
        task=TASK_2,
        model="openai/gpt-4.1-nano",
        max_loops=15,
        max_total_tokens=1_500_000,
        max_wall_time=600,
        max_total_workers=20,
        max_depth=2,
        max_tool_calls=100,
        workflow_dir=shared_dir,
        verifier=verify_run2,
        tags=["e2e", "s5", "memory", "critique"],
    )

    combined_ok = (
        r1["status"] in ("complete", "partial")
        and r1.get("verify_ok")
        and r2["status"] in ("complete", "partial")
        and r2.get("verify_ok")
    )
    print(f"\n[memory_tool_critique] combined_ok={combined_ok}")
    print(f"  run1: status={r1['status']} verify={r1.get('verify_ok')}")
    print(f"  run2: status={r2['status']} verify={r2.get('verify_ok')}")
    return 0 if combined_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
