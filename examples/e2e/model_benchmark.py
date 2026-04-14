#!/usr/bin/env python3
"""Model Benchmark — compare manager/worker model combinations.

Runs the same complex multi-step task with different model combos and
compares cost, quality, and speed.  Each combo gets its own experiment
in /tmp/awp-experiments/ so results are visible in the UI.

Usage:
    python examples/e2e/model_benchmark.py
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _harness import run_e2e  # noqa: E402

# ---------------------------------------------------------------------------
# Task: complex enough to need sub-managers, tool creation, and synthesis
# ---------------------------------------------------------------------------
TASK = (
    "Design a comprehensive disaster response system for a fictional "
    "megacity called 'Nova Arcadia' (population 12 million). The system "
    "must cover THREE domains:\n\n"
    "1. EARTHQUAKE — seismic early warning, structural triage, evacuation "
    "routing for 4 districts (Downtown, Harbor, Hillside, Suburbs)\n\n"
    "2. FLOOD — river monitoring, pump station coordination, shelter "
    "allocation with capacity constraints\n\n"
    "3. PANDEMIC — contact tracing architecture, hospital load balancing, "
    "supply chain for medical equipment\n\n"
    "For each domain, produce:\n"
    "- A technical architecture (components, data flows, APIs)\n"
    "- A resource budget estimate (personnel, hardware, annual cost)\n"
    "- A 72-hour activation timeline\n\n"
    "Finally, synthesize a UNIFIED command center design that integrates "
    "all three domains, showing how they share resources and communicate "
    "during a compound disaster (earthquake + flood simultaneously).\n\n"
    "Deliver the result as a structured report with clear sections for "
    "each domain and the unified design. Use code execution to compute "
    "any numeric estimates (e.g. evacuation capacity, hospital bed math)."
)


# ---------------------------------------------------------------------------
# Model combinations to benchmark
# ---------------------------------------------------------------------------
COMBOS: list[dict[str, str]] = [
    # Combo 1: Baseline — current default for both
    {
        "label": "gpt5mini-gpt5mini",
        "manager": "openai/gpt-5-mini",
        "worker": "openai/gpt-5-mini",
    },
    # Combo 2: Cheap worker — gpt-5-nano
    {
        "label": "gpt5mini-gpt5nano",
        "manager": "openai/gpt-5-mini",
        "worker": "openai/gpt-5-nano",
    },
    # Combo 3: Nemotron as worker
    {
        "label": "gpt5mini-nemotron3super",
        "manager": "openai/gpt-5-mini",
        "worker": "nvidia/nemotron-3-super-120b-a12b",
    },
    # Combo 4: Gemini 2.5 Flash as worker
    {
        "label": "gpt5mini-gemini25flash",
        "manager": "openai/gpt-5-mini",
        "worker": "google/gemini-2.5-flash",
    },
    # Combo 5: Gemini 2.5 Flash as manager + gpt-5-nano worker
    {
        "label": "gemini25flash-gpt5nano",
        "manager": "google/gemini-2.5-flash",
        "worker": "openai/gpt-5-nano",
    },
    # Combo 6: DeepSeek V3.1 as worker
    {
        "label": "gpt5mini-deepseekv31",
        "manager": "openai/gpt-5-mini",
        "worker": "deepseek/deepseek-chat-v3.1",
    },
]


def verify(workflow_dir: Path, result: dict) -> dict:
    """Check that all three domains appear and a unified section exists."""
    text_blob = json.dumps(result, default=str).lower()
    output_files = result.get("output_files") or []
    for fp in output_files:
        try:
            text_blob += "\n" + Path(fp).read_text(errors="replace").lower()
        except Exception:
            pass

    domains = {
        "earthquake": "earthquake" in text_blob,
        "flood": "flood" in text_blob,
        "pandemic": "pandemic" in text_blob,
    }
    unified = "unified" in text_blob or "command center" in text_blob
    all_domains = all(domains.values())

    return {
        "ok": all_domains and unified,
        "domains_found": domains,
        "unified_section": unified,
    }


def run_combo(combo: dict, session_id: str | None = None) -> dict:
    """Run a single model combination and return the report."""
    label = combo["label"]
    manager = combo["manager"]
    worker = combo["worker"]

    print(f"\n{'='*70}")
    print(f"  BENCHMARK: {label}")
    print(f"  Manager:   {manager}")
    print(f"  Worker:    {worker}")
    print(f"{'='*70}\n")

    t0 = time.time()
    report = run_e2e(
        slug=f"bench-{label}",
        title=f"Model Benchmark — {label}",
        task=TASK,
        model=manager,
        worker_model=worker,
        max_loops=25,
        max_total_tokens=3_000_000,
        max_wall_time=1800,
        max_total_workers=40,
        max_depth=3,
        max_tool_calls=500,
        verifier=verify,
        tags=["e2e", "benchmark", "model-comparison"],
        session_id=session_id,
    )
    report["combo"] = combo
    report["wall_time_s"] = round(time.time() - t0, 1)
    return report


def print_summary(results: list[dict]) -> None:
    """Print a comparison table of all benchmark results."""
    print(f"\n\n{'='*80}")
    print("  MODEL BENCHMARK SUMMARY")
    print(f"{'='*80}\n")

    header = f"{'Combo':<35} {'Status':<10} {'Verify':<8} {'Time(s)':<10} {'Term Reason'}"
    print(header)
    print("-" * len(header))

    for r in results:
        combo_label = r.get("combo", {}).get("label", r["slug"])
        status = r.get("status", "?")
        verify_ok = "OK" if r.get("verify_ok") else "FAIL"
        wall = r.get("wall_time_s", r.get("duration_s", "?"))
        term = r.get("termination_reason", "")[:30]
        print(f"{combo_label:<35} {status:<10} {verify_ok:<8} {str(wall):<10} {term}")

    print(f"\n{'='*80}")

    # Write machine-readable summary
    summary_path = Path("/tmp/awp-experiments/model_benchmark_summary.json")
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(results, indent=2, default=str))
    print(f"Full results: {summary_path}")


def main() -> int:
    results: list[dict] = []

    # All combos share one session so they appear grouped in the UI.
    first_report = run_combo(COMBOS[0])
    results.append(first_report)
    session_id = first_report.get("session_id")

    for combo in COMBOS[1:]:
        report = run_combo(combo, session_id=session_id)
        results.append(report)

    print_summary(results)

    passed = sum(1 for r in results if r.get("status") == "complete")
    print(f"\n{passed}/{len(results)} combos completed successfully.")
    return 0 if passed > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
