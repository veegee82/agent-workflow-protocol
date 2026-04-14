#!/usr/bin/env python
"""E2E test: Phase-aware gates + critique delegation gate + auto-blackboard.

Reproduces the failed run from experiment_1342026_085354_b3aeb60f8bd0 with
the structural fixes applied:

- phase_aware_incomplete prevents premature defect_category_cap firing
- plan_commit_mode="strict" reduces plan waste to 1 iteration max
- min_score_to_delegate=0.4 blocks new work when old work is failing
- blackboard_auto_post=True enables cross-worker coordination
- Budget warning injected when plan exceeds loop budget

Tags: e2e, s5, tool-creation, critique, planning
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _harness import run_e2e  # noqa: E402

TASK = """\
## Objective
Create a complete, arXiv-suitable LaTeX paper (including source package and
compiled PDF) based on a deep analysis of the GitHub repository
https://github.com/veegee82/agent-workflow-protocol.  The paper should cover
runtime generation of Tools, Skills, and Instructions in agent systems.

## Deliverables
1. **Repository analysis report** (2-4 pages, Markdown): concrete code patterns,
   modules, functions, and data flows for runtime tool/skill/instruction generation.
2. **Literature review** (BibTeX .bib + summary): 10+ relevant references from
   arXiv / conferences on dynamic tool creation, program synthesis, and agent
   architectures.  Each reference MUST have a DOI or URL.
3. **Diagrams** (SVG or PDF): at least 2 architecture diagrams showing the
   runtime generation pipeline and the tool factory lifecycle.
4. **LaTeX source bundle**: arXiv-style paper (~10 pages), sections: Introduction,
   Related Work, Methodology, Implementation, Evaluation, Conclusion.
5. **Compiled PDF**: the final paper rendered from the LaTeX source.
6. **Package**: all deliverables zipped into a single archive.

## Constraints
- Use real references only — no hallucinated citations.
- Code snippets in the paper must be from the actual repository.
- Diagrams must be generated programmatically (matplotlib, graphviz, or tikz).
"""


def verify(workflow_dir: Path, report: dict) -> dict:
    """Check that the run produced the required deliverables.

    Returns a dict with ``ok`` (bool) and per-deliverable status.
    The run passes if BibTeX + analysis artifacts are present.
    """
    _dir = Path(workflow_dir)
    if not _dir.exists():
        return {"ok": False, "reason": "workflow_dir does not exist"}
    # Only check output/ and workspace/ — skip repo_workdir/
    output_files = list((_dir / "output").rglob("*")) if (_dir / "output").exists() else []
    ws_files = [
        f for f in (_dir / "workspace").rglob("*")
        if "repo_workdir" not in str(f) and "runs" not in str(f)
    ] if (_dir / "workspace").exists() else []
    all_files = output_files + ws_files
    names_lower = [f.name.lower() for f in all_files]

    has_bib = any(f.suffix == ".bib" for f in all_files)
    has_tex = any(f.suffix == ".tex" for f in all_files)
    has_paper_pdf = any(
        f.suffix == ".pdf" and "paper" in f.name.lower()
        or f.suffix == ".pdf" and "main" in f.name.lower()
        or f.suffix == ".pdf" and f.parent.name in ("paper", "latex")
        for f in all_files
    )
    has_diagram = any(
        (f.suffix in (".svg", ".png", ".pdf"))
        and any(kw in f.name.lower() for kw in ("pipeline", "lifecycle", "diagram", "architecture"))
        for f in all_files
    )
    has_analysis = any("analysis" in n or "report" in n or "patterns" in n for n in names_lower)

    checks = {
        "bib": has_bib,
        "tex": has_tex,
        "paper_pdf": has_paper_pdf,
        "diagram": has_diagram,
        "analysis": has_analysis,
    }
    # Core: BibTeX + analysis is minimum viable output.
    ok = has_bib and has_analysis
    return {"ok": ok, **checks}


if __name__ == "__main__":
    report = run_e2e(
        slug="s5-phase-aware-paper-gen",
        title="S5 Phase-Aware Paper Generation (Fix Validation)",
        task=TASK,
        model="openai/gpt-5-mini",
        max_loops=80,
        max_total_tokens=10_000_000,
        max_wall_time=7200,
        max_total_workers=200,
        max_depth=4,
        max_tool_calls=5000,
        extra_config={
            "critique": {
                "enabled": True,
                "min_score_to_complete": 0.4,
                "max_repair_attempts": 3,
                "phase_aware_incomplete": True,
                "defect_category_hard_cap": 25,
                "defect_category_diagnose_threshold": 8,
                "min_score_to_delegate": 0.3,
                "max_delegation_blocks": 3,
            },
            "planning": {
                "plan_commit_mode": "strict",
            },
            "trace_enabled": True,
        },
        verifier=verify,
        tags=["e2e", "s5", "tool-creation", "critique", "planning"],
    )
    status = report.get("status", "unknown")
    duration = report.get("duration_s", 0)
    print(f"\n{'=' * 60}")
    print(f"E2E Result: {status}")
    print(f"Duration: {duration:.0f}s" if isinstance(duration, (int, float)) else f"Duration: {duration}")
    print(f"Workflow dir: {report.get('workflow_dir', '?')}")
    print(f"Termination: {report.get('termination_reason', '?')}")
    print(f"{'=' * 60}")
    sys.exit(0 if status in ("complete", "partial_complete", "partial") else 1)
