#!/usr/bin/env python3
"""E2E Scenario — 5 progressive runs in a single experiment.

Exercises the full AWP feature stack across 5 sequential runs that
build on each other within a single experiment (session):

  Run 1: Foundation research + dynamic tool creation
  Run 2: Build on Run 1 memory, use prior tool, create second tool
  Run 3: Deep analysis with critique loop, leverage accumulated memory
  Run 4: Sub-manager delegation using shared tools/memory/artifacts
  Run 5: Final synthesis pulling from all prior runs' knowledge

Tested features:
  * B4: Auto-curation of run knowledge into long-term memory
  * B1: Hierarchical context digest + PRIOR RUN MEMORY injection
  * Tool creation: Dynamic tool factory across multiple runs
  * Tool sharing: Tools from earlier runs available in later runs
  * Critique: Inline critique with repair cycles
  * Sub-manager: Recursive delegation (A4)
  * Artifact sharing: Output files accessible across runs
  * Single-session multi-run: All 5 runs in one experiment

Tags: e2e, s5, memory, tool-creation, critique, sub-manager, planning
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

_project_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_project_root / "packages" / "awp-core" / "src"))
sys.path.insert(0, str(_project_root / "packages" / "awp-runtime" / "src"))
sys.path.insert(0, str(_project_root / "packages" / "awp-ui" / "server"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _harness import make_experiment_dir, run_e2e  # noqa: E402

# ---------------------------------------------------------------------------
# Tasks — each builds on the previous
# ---------------------------------------------------------------------------

TASK_1 = (
    "Research quantum computing error correction methods. Focus on three "
    "approaches: (1) Surface codes, (2) Color codes, (3) Topological codes. "
    "For each, determine: logical qubit overhead ratio (a specific number), "
    "error threshold percentage, and one key advantage. "
    "\n\n"
    "Create a Python tool that calculates the total physical qubits needed "
    "given a target number of logical qubits and the overhead ratio. "
    "Test it with sample data (e.g., 100 logical qubits with each method). "
    "\n\n"
    "Produce a structured report with key findings for each method."
)

TASK_2 = (
    "Building on the quantum error correction research from the previous "
    "run (surface codes, color codes, topological codes — their overhead "
    "ratios and error thresholds are available in prior memory), create a "
    "comparative analysis. "
    "\n\n"
    "Create a Python scoring tool that ranks the three methods based on "
    "weighted criteria: overhead efficiency (40%), error threshold (35%), "
    "and implementation maturity (25%). The tool should accept custom "
    "weights and return a ranked list with scores. "
    "\n\n"
    "Use the physical qubit calculator from the previous run if available. "
    "Produce a ranked comparison table with scores."
)

TASK_3 = (
    "Using all accumulated knowledge about quantum error correction "
    "(method properties, overhead ratios, rankings from prior runs), "
    "perform a deep feasibility analysis for building a 1000-logical-qubit "
    "quantum computer. "
    "\n\n"
    "For each of the three methods, calculate: total physical qubits "
    "required (use the calculator tool), estimated hardware cost at "
    "$10K per physical qubit, and time-to-deployment estimate. "
    "\n\n"
    "Apply critical analysis: identify the single biggest technical "
    "barrier for each method. Produce a feasibility matrix with "
    "go/no-go recommendations."
)

TASK_4 = (
    "Based on all prior research (error correction methods, rankings, "
    "feasibility analysis), design a phased roadmap for deploying a "
    "fault-tolerant quantum computer using the top-ranked method. "
    "\n\n"
    "Delegate the work into specialized areas: "
    "(a) Hardware scaling plan with milestone qubit counts, "
    "(b) Software stack requirements including compiler and "
    "error decoder specifications, "
    "(c) Cost and timeline projection with yearly budgets. "
    "\n\n"
    "Each area should produce a detailed sub-report. Synthesize "
    "into a unified 5-year roadmap. Use any tools created in "
    "prior runs for calculations."
)

TASK_5 = (
    "Final synthesis: Create an executive briefing document that "
    "consolidates ALL findings from this experiment's prior runs: "
    "\n\n"
    "1. Quantum error correction landscape (from Run 1) "
    "2. Comparative rankings (from Run 2) "
    "3. Feasibility analysis for 1000 logical qubits (from Run 3) "
    "4. Deployment roadmap (from Run 4) "
    "\n\n"
    "The briefing must: cite specific numbers from prior analyses, "
    "name the recommended method and justify why, provide a one-page "
    "summary suitable for a CTO audience, and include a risk matrix. "
    "\n\n"
    "Verify key claims by recalculating physical qubit requirements "
    "using the tools from earlier runs. The final output must be a "
    "complete, self-contained document."
)


# ---------------------------------------------------------------------------
# Verifiers
# ---------------------------------------------------------------------------

def _scan_all_text(workflow_dir: Path, result: dict) -> str:
    """Collect all text from result dict and workspace files."""
    text = json.dumps(result, default=str).lower()
    for fp in (result.get("output_files") or []):
        try:
            text += "\n" + Path(fp).read_text(errors="replace").lower()
        except Exception:
            pass
    for p in workflow_dir.rglob("*"):
        if p.is_file() and p.suffix in (".json", ".md", ".txt", ".csv", ".log"):
            try:
                content = p.read_text(errors="replace").lower()
                if len(content) < 50_000:
                    text += "\n" + content
            except Exception:
                pass
    return text


def verify_run1(workflow_dir: Path, result: dict) -> dict:
    """Run 1: research + tool creation."""
    text = _scan_all_text(workflow_dir, result)

    methods = ["surface", "color", "topological"]
    methods_found = sum(1 for m in methods if m in text)

    # Check for numeric content (overhead ratios, thresholds)
    has_numbers = bool(re.findall(r"\d+\.?\d*", text))

    # Check for tool/code evidence
    code_evidence = any(
        w in text for w in ("qubit", "calculator", "physical_qubit", "def ")
    )

    # Check for curation
    curation = result.get("curation_report") is not None

    ok = methods_found >= 2 and has_numbers and code_evidence
    return {
        "ok": ok,
        "methods_found": methods_found,
        "has_numbers": has_numbers,
        "code_evidence": code_evidence,
        "curation_present": curation,
    }


def verify_run2(workflow_dir: Path, result: dict) -> dict:
    """Run 2: comparative analysis + second tool."""
    text = _scan_all_text(workflow_dir, result)

    has_ranking = any(w in text for w in ("rank", "score", "comparison", "weighted"))
    has_prior = result.get("curation_report") is not None or result.get("_digest_sha") is not None
    has_methods = sum(1 for m in ("surface", "color", "topological") if m in text) >= 2

    ok = has_ranking and has_methods
    return {
        "ok": ok,
        "has_ranking": has_ranking,
        "has_prior_context": has_prior,
        "has_methods": has_methods,
    }


def verify_run3(workflow_dir: Path, result: dict) -> dict:
    """Run 3: feasibility analysis with critique."""
    text = _scan_all_text(workflow_dir, result)

    has_feasibility = any(
        w in text for w in ("feasibility", "physical qubit", "cost", "barrier")
    )
    has_numbers = bool(re.findall(r"\$?\d[\d,]*\.?\d*[kmb]?", text))
    has_recommendation = any(
        w in text for w in ("recommend", "go/no-go", "feasible", "viable")
    )

    ok = has_feasibility and has_numbers
    return {
        "ok": ok,
        "has_feasibility": has_feasibility,
        "has_numbers": has_numbers,
        "has_recommendation": has_recommendation,
    }


def verify_run4(workflow_dir: Path, result: dict) -> dict:
    """Run 4: roadmap with delegation."""
    text = _scan_all_text(workflow_dir, result)

    has_roadmap = any(w in text for w in ("roadmap", "phase", "milestone", "year"))
    has_delegation = any(
        w in text for w in ("hardware", "software", "cost", "timeline")
    )
    has_synthesis = any(w in text for w in ("unified", "synthesize", "consolidated", "plan"))

    ok = has_roadmap and has_delegation
    return {
        "ok": ok,
        "has_roadmap": has_roadmap,
        "has_delegation_areas": has_delegation,
        "has_synthesis": has_synthesis,
    }


def verify_run5(workflow_dir: Path, result: dict) -> dict:
    """Run 5: executive briefing synthesis."""
    text = _scan_all_text(workflow_dir, result)

    has_briefing = any(
        w in text for w in ("executive", "briefing", "summary", "cto")
    )
    has_citations = any(
        w in text for w in ("surface code", "color code", "topological", "overhead")
    )
    has_risk = any(w in text for w in ("risk", "challenge", "barrier", "limitation"))
    has_recommendation = any(
        w in text for w in ("recommend", "conclusion", "verdict", "chosen")
    )

    ok = has_briefing and has_citations
    return {
        "ok": ok,
        "has_briefing": has_briefing,
        "has_citations": has_citations,
        "has_risk_analysis": has_risk,
        "has_recommendation": has_recommendation,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

RUNS = [
    {
        "slug": "progressive-run1-research",
        "title": "Run 1 — QEC Research + Tool Creation",
        "task": TASK_1,
        "verifier": verify_run1,
        "max_loops": 15,
        "max_total_tokens": 2_000_000,
        "max_wall_time": 600,
        "max_total_workers": 20,
        "max_depth": 2,
        "extra_config": {},
    },
    {
        "slug": "progressive-run2-compare",
        "title": "Run 2 — Comparative Ranking + Scoring Tool",
        "task": TASK_2,
        "verifier": verify_run2,
        "max_loops": 15,
        "max_total_tokens": 2_000_000,
        "max_wall_time": 600,
        "max_total_workers": 20,
        "max_depth": 2,
        "extra_config": {},
    },
    {
        "slug": "progressive-run3-feasibility",
        "title": "Run 3 — Feasibility Analysis + Critique",
        "task": TASK_3,
        "verifier": verify_run3,
        "max_loops": 18,
        "max_total_tokens": 2_500_000,
        "max_wall_time": 900,
        "max_total_workers": 25,
        "max_depth": 2,
        "extra_config": {
            "critique": {
                "enabled": True,
                "min_score_to_complete": 0.5,
                "max_repair_attempts": 2,
            },
        },
    },
    {
        "slug": "progressive-run4-roadmap",
        "title": "Run 4 — Deployment Roadmap (Sub-Manager)",
        "task": TASK_4,
        "verifier": verify_run4,
        "max_loops": 20,
        "max_total_tokens": 3_000_000,
        "max_wall_time": 1200,
        "max_total_workers": 30,
        "max_depth": 3,
        "extra_config": {},
    },
    {
        "slug": "progressive-run5-synthesis",
        "title": "Run 5 — Executive Briefing Synthesis",
        "task": TASK_5,
        "verifier": verify_run5,
        "max_loops": 15,
        "max_total_tokens": 2_000_000,
        "max_wall_time": 600,
        "max_total_workers": 20,
        "max_depth": 2,
        "extra_config": {},
    },
]


def main() -> int:
    shared_dir = make_experiment_dir("s5-progressive-experiment")
    print(f"[progressive] shared workflow_dir={shared_dir}")
    print("[progressive] running 5 sequential runs in one experiment\n")

    session_id: str | None = None
    results: list[dict] = []
    all_ok = True

    for i, run_cfg in enumerate(RUNS, 1):
        print(f"\n{'='*60}")
        print(f"[progressive] Starting Run {i}/5: {run_cfg['title']}")
        print(f"{'='*60}\n")

        r = run_e2e(
            slug=run_cfg["slug"],
            title=run_cfg["title"],
            task=run_cfg["task"],
            model="openai/gpt-4.1-nano",
            max_loops=run_cfg["max_loops"],
            max_total_tokens=run_cfg["max_total_tokens"],
            max_wall_time=run_cfg["max_wall_time"],
            max_total_workers=run_cfg["max_total_workers"],
            max_depth=run_cfg["max_depth"],
            max_tool_calls=500,
            workflow_dir=shared_dir,
            verifier=run_cfg["verifier"],
            extra_config=run_cfg.get("extra_config"),
            tags=["e2e", "s5", "memory", "tool-creation", "critique",
                  "sub-manager", "planning"],
            session_id=session_id,
        )

        # Capture session_id from first run for subsequent runs
        if session_id is None:
            session_id = r["session_id"]

        results.append(r)
        run_ok = r["status"] in ("complete", "partial") and r.get("verify_ok")

        if not run_ok:
            print(f"[progressive] Run {i} DID NOT PASS — continuing anyway")
            all_ok = False
        else:
            print(f"[progressive] Run {i} PASSED")

    # Final summary
    print(f"\n{'='*60}")
    print("[progressive] FINAL SUMMARY")
    print(f"{'='*60}")
    for i, r in enumerate(results, 1):
        passed = r["status"] in ("complete", "partial") and r.get("verify_ok")
        status_icon = "PASS" if passed else "FAIL"
        print(
            f"  Run {i}: {status_icon} | status={r['status']} "
            f"verify={r.get('verify_ok')} | {r['duration_s']}s"
        )
    print(f"\n  Overall: {'ALL PASSED' if all_ok else 'SOME FAILED'}")
    print(f"  Session: {session_id}")
    print(f"  Dir: {shared_dir}")

    # Write combined report
    try:
        report = {
            "experiment": "s5-progressive-experiment",
            "session_id": session_id,
            "all_ok": all_ok,
            "runs": results,
        }
        (shared_dir / "progressive_report.json").write_text(
            json.dumps(report, indent=2, default=str)
        )
    except Exception:
        pass

    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
