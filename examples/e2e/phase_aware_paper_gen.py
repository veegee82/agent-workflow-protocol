#!/usr/bin/env python
"""E2E test: Full paper generation pipeline with PDF output.

Budget sized for a multi-hour run that produces a complete 10-page
arXiv-style paper as PDF with embedded diagrams. The verifier
requires a real PDF file in the output directory — without it the
run is not considered complete.

Tags: e2e, s5, tool-creation, critique, planning
"""
from __future__ import annotations

import os
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

## Deliverables (ALL required)
1. **Repository analysis report** (2-4 pages, Markdown): concrete code patterns,
   modules, functions, and data flows for runtime tool/skill/instruction generation.
2. **Literature review** (BibTeX .bib + summary): 10+ relevant references from
   arXiv / conferences on dynamic tool creation, program synthesis, and agent
   architectures.  Each reference MUST have a DOI or URL.
3. **Diagrams** (SVG or PDF): at least 2 architecture diagrams showing the
   runtime generation pipeline and the tool factory lifecycle.
4. **LaTeX source bundle**: arXiv-style paper (~10 pages), sections: Introduction,
   Related Work, Methodology, Implementation, Evaluation, Conclusion.
5. **Compiled PDF**: the final paper rendered from the LaTeX source.  If pdflatex
   is not available, generate a PDF programmatically using reportlab or
   matplotlib.  The PDF MUST exist in _output_dir.
6. **Package**: all deliverables zipped into a single archive.

## Constraints
- Use real references only — no hallucinated citations.
- Code snippets in the paper must be from the actual repository.
- Diagrams must be generated programmatically (matplotlib, graphviz, or tikz).
- The final PDF MUST be at least 5 pages long.

## CRITICAL: PDF compilation
If pdflatex/xelatex are not available in the execution environment, you MUST
generate the PDF programmatically using Python libraries (reportlab, fpdf2,
or matplotlib).  Write the full paper content into the PDF including section
headers, body text, code listings, and references.  Do NOT skip PDF generation.
"""


def verify(workflow_dir: Path, report: dict) -> dict:
    """Hard verification: requires a PDF file in output/.

    Returns a dict with ``ok`` (bool) and per-deliverable status.
    """
    _dir = Path(workflow_dir)
    if not _dir.exists():
        return {"ok": False, "reason": "workflow_dir does not exist"}

    output_files = list((_dir / "output").rglob("*")) if (_dir / "output").exists() else []
    ws_files = [
        f for f in (_dir / "workspace").rglob("*")
        if "repo_workdir" not in str(f) and "runs" not in str(f)
    ] if (_dir / "workspace").exists() else []
    all_files = output_files + ws_files
    names_lower = [f.name.lower() for f in all_files]

    has_bib = any(f.suffix == ".bib" for f in all_files)
    has_tex = any(f.suffix == ".tex" for f in all_files)

    # Any PDF that is not a diagram counts as paper PDF
    pdf_files = [
        f for f in all_files
        if f.suffix == ".pdf" and f.stat().st_size > 10_000  # >10KB = real content
    ]
    has_paper_pdf = len(pdf_files) > 0

    has_diagram = any(
        (f.suffix in (".svg", ".png", ".pdf"))
        and any(kw in f.name.lower() for kw in (
            "pipeline", "lifecycle", "diagram", "architecture", "factory",
        ))
        for f in all_files
    )
    has_analysis = any(
        "analysis" in n or "report" in n or "patterns" in n
        for n in names_lower
    )

    checks = {
        "bib": has_bib,
        "tex": has_tex,
        "paper_pdf": has_paper_pdf,
        "pdf_files": [str(f.name) for f in pdf_files[:5]],
        "diagram": has_diagram,
        "analysis": has_analysis,
    }

    # HARD requirement: BibTeX + analysis + at least one substantial PDF
    ok = has_bib and has_analysis and has_paper_pdf
    return {"ok": ok, **checks}


if __name__ == "__main__":
    report = run_e2e(
        slug="s5-phase-aware-paper-gen",
        title="S5 Full Paper Generation (10h budget, PDF required)",
        task=TASK,
        model="openai/gpt-5-mini",
        max_loops=1000,
        max_total_tokens=50_000_000,
        max_wall_time=36000,       # 10 hours
        max_total_workers=1000,
        max_depth=4,
        max_tool_calls=20000,
        extra_config={
            "critique": {
                "enabled": True,
                "min_score_to_complete": 0.3,
                "max_repair_attempts": 5,
                "phase_aware_incomplete": True,
                "defect_category_hard_cap": 50,
                "defect_category_diagnose_threshold": 15,
                "min_score_to_delegate": 0.2,
                "max_delegation_blocks": 5,
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
    verification = report.get("verification", {})
    print(f"\n{'=' * 60}")
    print(f"E2E Result: {status}")
    print(f"Duration: {duration:.0f}s" if isinstance(duration, (int, float)) else f"Duration: {duration}")
    print(f"Workflow dir: {report.get('workflow_dir', '?')}")
    print(f"Termination: {report.get('termination_reason', '?')}")
    print(f"Verification: {verification}")
    print(f"{'=' * 60}")
    sys.exit(0 if status in ("complete", "partial_complete", "partial") else 1)
