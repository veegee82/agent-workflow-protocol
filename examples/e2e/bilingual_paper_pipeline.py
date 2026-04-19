#!/usr/bin/env python
"""E2E: Bilingual (DE+EN) academic paper pipeline — Session 3 hardening validation.

Validates Fixes A-H under real LLM variability:
  A: validate_python_source()    + worker-prompt guardrails
  B: _deliverable_presence_gate  (blocks COMPLETE on missing/empty files)
  C: max_rejected_completions    (synthesize repair or terminate partial)
  D: plan_loop deterministic transition (forced_delegate / plan_loop_stall)
  E: try/except/finally + SIGTERM/SIGINT + guaranteed run.complete
  F: R31 errors carry full known pattern_id list; plan-prompt cheat-sheet
  G: max_workers_per_iteration   budget (default 6)
  H: _finalize_terminal_status() forced exits -> partial/failed/aborted

Consumes three prior DE drafts (abstract, introduction, methodology) and
produces a bilingual (DE+EN) paper with figures, citations, and PDF.

Tags: e2e, s5, paper-pipeline, cross-run-memory, all-session-fixes
"""
from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _harness import run_e2e  # noqa: E402

PRIOR_INPUTS_DIR = Path(
    "/tmp/awp-experiments/experiment_005a0e20131a/runs/"
    "e59f474d9dcf/workspace/inputs"
)
PRIOR_MEMORY_DIR = Path(
    "/tmp/awp-experiments/experiment_005a0e20131a/shared/memory"
)


TASK = """\
## Objective

Produce a **bilingual (German + English) academic paper** that builds on the
three prior German drafts (`prior_abstract_de.md`, `prior_introduction_de.md`,
`prior_methodology_de.md`) available under `_workspace_dir/inputs/`.

The paper's topic is the same as the prior drafts: **iterative tool and
skill synthesis in autonomous multi-agent workflows (AWP)**. Build on the
prior work — do not start from scratch. Improve the German text where
appropriate, and provide a full English counterpart.

## Cross-run memory (REQUIRED)

Build on prior drafts from earlier runs of THIS experiment. Query the
experiment's memory layer for `prior_abstract_de`, `prior_introduction_de`,
`prior_methodology_de` context before polishing, and reference the earlier
polished versions if present.

## Required deliverables (ALL MUST exist on disk, non-empty)

1. `_output_dir/paper.md` — bilingual paper with side-by-side DE and EN
   sections. Must contain `## Abstract (DE)`, `## Abstract (EN)`,
   `## Einleitung / Introduction`, `## Methodik / Methodology`,
   `## Ergebnisse / Results`, `## Diskussion / Discussion`,
   `## Referenzen / References`. Citations `[1]..[N]` inline, numeric.
   At least 3000 characters total.
2. `_output_dir/paper.pdf` — rendered PDF of the paper. Non-empty, >10KB.
   If pdflatex is unavailable, generate via Python (reportlab, fpdf2, or
   matplotlib). Do NOT skip the PDF.
3. `_output_dir/figs/figure1.png` — iterative tool synthesis diagram
   (a schematic of the tool-factory lifecycle). Non-empty, >1KB.
4. `_output_dir/figs/figure2.png` — skill accumulation diagram
   (a schematic of cross-run skill memory growth). Non-empty, >1KB.

## Constraints

- Real citations only — no hallucinated references. If you cannot verify
  a citation, omit it.
- No placeholders (`TODO`, `<REF 1>`, `placeholder`) in the final paper.
- Figures must be generated programmatically (matplotlib preferred).
- Keep within the budget — do not attempt exhaustive literature search.
"""


def verify(workflow_dir: Path, report: dict) -> dict:
    """Verification aligned with the E2E Pass Rubric.

    Returns {ok: bool, ...details}.
    """
    root = Path(workflow_dir)
    if not root.exists():
        return {"ok": False, "reason": "workflow_dir missing"}

    # The output_dir inside a run is typically: output/<run_id>/...
    # Collect any file matching the declared deliverables anywhere under
    # `output/` or the workspace output locations.
    candidates: list[Path] = []
    for base in (root / "output", root / "workspace"):
        if base.exists():
            candidates.extend(p for p in base.rglob("*") if p.is_file())

    def _find(basename: str, min_size: int = 1) -> Path | None:
        for p in candidates:
            if p.name == basename and p.stat().st_size >= min_size:
                return p
        return None

    paper_md = _find("paper.md", 3000)
    paper_pdf = _find("paper.pdf", 10_000)
    fig1 = _find("figure1.png", 1000)
    fig2 = _find("figure2.png", 1000)

    md_has_de_en = False
    md_has_placeholder = False
    if paper_md:
        text = paper_md.read_text(encoding="utf-8", errors="replace")
        md_has_de_en = (
            ("(DE)" in text or "Deutsch" in text or "Einleitung" in text)
            and ("(EN)" in text or "English" in text or "Introduction" in text)
        )
        md_has_placeholder = bool(
            re.search(r"placeholder|<\s*ref\s*\d+\s*>|\[TODO\]", text, re.I)
        )

    # Cross-run memory evidence: a worker tool call against a memory.*
    # tool, a read of `shared/memory/`, or an explicit mention in manager
    # decisions. We scan events/*.json and the delegation logs.
    memory_evidence = False
    for p in candidates:
        s = str(p)
        if any(k in s for k in ("memory/", "cross_run", "prior_abstract_de")):
            memory_evidence = True
            break
    if not memory_evidence:
        # Secondary: look for memory.* tool calls or matching strings in
        # any tool_calls.json / manager_decision.json
        for p in root.rglob("tool_calls.json"):
            try:
                t = p.read_text(encoding="utf-8", errors="replace")
                if "memory." in t or "prior_abstract_de" in t:
                    memory_evidence = True
                    break
            except OSError:
                continue

    # Gate/circuit-breaker evidence (non-fatal — they may cleanly not fire)
    gates_fired: list[str] = []
    for p in root.rglob("manager_decision.json"):
        try:
            t = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for key in (
            "deliverable_presence",
            "max_rejected_completions",
            "forced_delegate",
            "plan_loop_stall",
            "max_workers_per_iteration",
        ):
            if key in t and key not in gates_fired:
                gates_fired.append(key)

    checks = {
        "paper_md": str(paper_md) if paper_md else None,
        "paper_pdf": str(paper_pdf) if paper_pdf else None,
        "fig1": str(fig1) if fig1 else None,
        "fig2": str(fig2) if fig2 else None,
        "md_has_de_en": md_has_de_en,
        "md_has_placeholder": md_has_placeholder,
        "memory_evidence": memory_evidence,
        "gates_fired": gates_fired,
    }
    ok = bool(
        paper_md and paper_pdf and fig1 and fig2
        and md_has_de_en and not md_has_placeholder
    )
    return {"ok": ok, **checks}


def _copy_prior_memory(workflow_dir: Path) -> None:
    """Copy prior experiment memory into the new experiment's shared/memory/."""
    if not PRIOR_MEMORY_DIR.exists():
        return
    dst = workflow_dir / "shared" / "memory"
    dst.mkdir(parents=True, exist_ok=True)
    for src in PRIOR_MEMORY_DIR.rglob("*"):
        if src.is_file():
            rel = src.relative_to(PRIOR_MEMORY_DIR)
            tgt = dst / rel
            tgt.parent.mkdir(parents=True, exist_ok=True)
            try:
                shutil.copy2(src, tgt)
            except OSError:
                pass


if __name__ == "__main__":
    # Resolve prior input files. If missing, abort early with a clear message.
    abstract = PRIOR_INPUTS_DIR / "prior_abstract_de.md"
    introduction = PRIOR_INPUTS_DIR / "prior_introduction_de.md"
    methodology = PRIOR_INPUTS_DIR / "prior_methodology_de.md"
    for p in (abstract, introduction, methodology):
        if not p.is_file():
            print(f"[e2e] FATAL: missing prior input {p}", file=sys.stderr)
            sys.exit(2)

    # Pre-create the experiment dir so we can seed `shared/memory/` from the
    # prior experiment before the run starts. run_e2e's make_experiment_dir
    # is called internally; we pre-create our own here to keep control.
    from _harness import make_experiment_dir  # noqa: E402

    workflow_dir = make_experiment_dir("bilingual-paper-pipeline")
    _copy_prior_memory(workflow_dir)

    inputs = {
        # FILE_PATH inputs — the harness will copy them into workspace/inputs/
        # preserving their basenames (prior_abstract_de.md, ...).
        "prior_abstract_de": str(abstract),
        "prior_introduction_de": str(introduction),
        "prior_methodology_de": str(methodology),
    }

    report = run_e2e(
        slug="bilingual-paper-pipeline",
        title="Bilingual DE+EN Paper Pipeline — Session 3 All-Fix Validation",
        task=TASK,
        inputs=inputs,
        model="openai/gpt-5-mini",
        worker_model="deepseek/deepseek-chat-v3.1",
        max_loops=30,
        max_total_tokens=4_000_000,
        max_wall_time=5400,          # 90 min
        max_total_workers=60,
        max_depth=3,
        max_tool_calls=3000,
        workflow_dir=workflow_dir,
        extra_config={
            "budget": {
                "max_workers_per_iteration": 6,   # Fix G
                "max_rejected_completions": 2,    # Fix C
            },
            "critique": {
                "enabled": True,
                "min_score_to_complete": 0.5,
                "max_repair_attempts": 3,
            },
            "planning": {
                "enabled": True,
                "plan_commit_mode": "strict",
            },
            "trace_enabled": True,
        },
        verifier=verify,
        tags=["e2e", "s5", "paper-pipeline", "cross-run-memory",
              "all-session-fixes"],
    )
    status = report.get("status", "unknown")
    print(f"\n{'=' * 60}")
    print(f"E2E Result: {status} (verify_ok={report.get('verify_ok')})")
    print(f"Workflow dir: {report.get('workflow_dir')}")
    print(f"Termination: {report.get('termination_reason')}")
    print(f"Verification: {report.get('verification')}")
    print(f"{'=' * 60}")
    sys.exit(0 if (status == "complete" and report.get("verify_ok")) else 1)
