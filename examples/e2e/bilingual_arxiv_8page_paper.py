#!/usr/bin/env python
"""E2E: bilingual (DE+EN) 8-page arXiv two-column paper about AWP autonomy
extension via tool- and skill-generation vs other frameworks.

The task requires TWO PDFs (one per language), each rendered from a LaTeX
source using tectonic (downloaded once into ``~/.local/bin``), each exactly
8 pages at the arxiv_two_column template's density, both accompanied by
full Markdown versions and at least one programmatically-generated SGD
diagram PNG.

Budget is sized for a multi-hour run — the task is deliberately dense
(>9000 words across DE+EN), so the delegation loop must plan, delegate,
write, compile, verify page count, and repair when the page count drifts.

Tags: e2e, s5, paper-pipeline, bilingual, tool-creation, critique, planning
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _harness import run_e2e  # noqa: E402


# Make tectonic visible to every subprocess the delegation loop spawns.
_LOCAL_BIN = str(Path.home() / ".local" / "bin")
if _LOCAL_BIN not in os.environ.get("PATH", ""):
    os.environ["PATH"] = _LOCAL_BIN + os.pathsep + os.environ.get("PATH", "")


PAPER_INPUTS_SRC = Path("/tmp/paper_inputs")


TASK = """\
## Objective
Produce a **complete, arXiv-style, two-column, 8-page scientific paper** on
the topic **"Autonomy extension through tool- and skill-generation and
comparison to other agent frameworks"**. Deliver **two language versions**
(German + English), both compiled to PDF from a real LaTeX source using
`tectonic` (available on PATH), and both accompanied by full Markdown
versions.

## Workspace layout (READ FIRST)
- `_workspace_dir/inputs/agent-workflow-protocol/` — the complete AWP
  repository (source of truth for methodology). Read its README, CLAUDE.md,
  spec/, docs/, and `packages/awp-runtime/src/awp/runtime/` to ground the
  paper in real code. **All code references in the paper MUST come from
  this repository — no hallucinated APIs.**
- `_workspace_dir/inputs/arxiv_two_column/` — LaTeX two-column template
  (`main.tex`, `references.bib`, `README.md`). Use this as the layout
  baseline. Copy it per language and adapt.

## Required deliverables (ALL on disk under `_output_dir/`, non-empty)
1. `paper_de.pdf` — German PDF, arxiv two-column, **exactly 8 pages**.
2. `paper_en.pdf` — English PDF, arxiv two-column, **exactly 8 pages**.
3. `paper_de.md` — German Markdown, full prose matching the PDF.
4. `paper_en.md` — English Markdown, full prose matching the PDF.
5. `figures/` — at least one **self-generated SGD diagram** as PNG,
   clean typography, non-overlapping arrows, consistent style. Generate
   programmatically with matplotlib or graphviz.
6. `latex_de/` — complete LaTeX source bundle for DE (`main.tex`,
   `references.bib`, figures). Must compile with `tectonic main.tex`.
7. `latex_en/` — complete LaTeX source bundle for EN. Must compile.
8. `references.bib` — full BibTeX with **every citation used in the text**.
   Citations appear as `\\cite{key}` in LaTeX and render as `[1]`, `[2]`,
   ... in the PDF. **Every `[N]` in the PDF MUST correspond to an entry
   in the bib file — no dangling or fictitious numbers.**

## Section word targets (verified per language)
- Abstract: **≈ 500 words**
- Introduction: **> 2500 words** — include state of the art and placement
  on autonomy scales (A0-A4).
- Methodology: **> 5000 words** — detailed description of AWP, tool- and
  skill-generation, delegation loop, validation rules.
- Results: **> 1000 words** — evaluation and comparison to existing
  frameworks (LangChain, AutoGen, CrewAI, MetaGPT, OpenAI Assistants, etc.).
- Discussion / Conclusion: reasonable length.
- References: complete list, every `[N]` used in-text.

## Page count enforcement (HARD)
Each PDF MUST be **exactly 8 pages**. This is verified with PyPDF2. If the
compile yields 7 or 9 pages, tune `\\vspace{...}`, figure sizes, or
paragraph density and recompile. Do not cheat the page count by shipping
blank pages.

## Process (recommended)
1. **Analyze the AWP repo** — extract methodology concepts (autonomy
   spectrum, layers, delegation loop, tool factory, critique engine, R1-R32
   rules).
2. **Research comparable frameworks** — citations with DOI/URL.
3. **Write master content in English** — all sections at target word count.
4. **Translate** to German — preserve technical terms, keep section
   structure identical.
5. **Generate SGD diagrams** as PNGs.
6. **Render LaTeX** per language, compile with tectonic.
7. **Verify** — PyPDF2 page count, bib citation match, word count per
   section, file presence. Iterate until all checks green.

## Constraints
- `tectonic` is available on PATH — prefer it over programmatic PDF libs.
- NO hallucinated citations — every `\\cite{key}` resolves to a real
  paper with a DOI or stable URL.
- NO placeholders (`TODO`, `XXX`, `???`, `Lorem ipsum`) in final deliverables.
- Markdown files must contain the SAME prose as the PDFs (not shortened).

## Tool-Registry discipline (REQUIRED — not optional)
Whenever a worker performs a **repeatable** operation — compiling LaTeX,
counting PDF pages, extracting sections from Markdown, rendering a figure —
it MUST register that operation as a persistent dynamic tool via the
`tool.create` tool (instead of / in addition to `code.execute`). These
tools persist in `shared/dynamic_tools/` and become available to every
subsequent worker in the same experiment.

Mandatory tools to create (at minimum):
- `dynamic.latex_compile` — wrap `tectonic main.tex` with timeout + error capture.
- `dynamic.pdf_pages` — return page count via PyPDF2.
- `dynamic.word_count_section` — count words in a specific `#` section of
  a Markdown file.
- `dynamic.render_sgd_diagram` — generate a consistent-style SGD PNG via
  matplotlib given a node/edge spec.
- `dynamic.verify_citations` — cross-check `\\cite{key}` occurrences
  against `references.bib` entries.

Skills (`.md` documentation of procedures) are NOT a substitute for tools.
Tools are executable; skills are documentation. Both are welcome, but the
registry MUST contain real dynamic tools when you reach the compile /
verify phase.
"""


def _count_pdf_pages(path: Path) -> int | None:
    """Best-effort page count via PyPDF2. Returns None if unreadable."""
    try:
        from PyPDF2 import PdfReader  # type: ignore
    except Exception:
        try:
            from pypdf import PdfReader  # type: ignore
        except Exception:
            return None
    try:
        reader = PdfReader(str(path))
        return len(reader.pages)
    except Exception:
        return None


def _count_words(text: str) -> int:
    return len([w for w in text.split() if w.strip()])


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def _seed_inputs_into_workspace(workflow_dir: Path) -> None:
    """Copy /tmp/paper_inputs/* into the experiment's shared/inputs and
    workspace/inputs so workers can read them via `_workspace_dir/inputs/`.
    """
    shared_inputs = workflow_dir / "shared" / "inputs"
    workspace_inputs = workflow_dir / "workspace" / "inputs"
    for target in (shared_inputs, workspace_inputs):
        target.mkdir(parents=True, exist_ok=True)
        # Symlink the whole AWP repo (read-only, large)
        awp_link = target / "agent-workflow-protocol"
        if not awp_link.exists():
            try:
                awp_link.symlink_to(
                    PAPER_INPUTS_SRC / "agent-workflow-protocol", target_is_directory=True
                )
            except OSError:
                # Fallback: copy (slow, but robust)
                shutil.copytree(
                    PAPER_INPUTS_SRC / "agent-workflow-protocol",
                    awp_link,
                    symlinks=True,
                    ignore=shutil.ignore_patterns(
                        ".git", "__pycache__", "node_modules", "*.pyc", ".venv"
                    ),
                )
        # Copy the arxiv template (small, editable)
        tpl_src = PAPER_INPUTS_SRC / "arxiv_two_column"
        tpl_dst = target / "arxiv_two_column"
        if not tpl_dst.exists():
            shutil.copytree(tpl_src, tpl_dst)


def _check_tectonic() -> bool:
    try:
        r = subprocess.run(
            ["tectonic", "--version"], capture_output=True, text=True, timeout=10
        )
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def verify(workflow_dir: Path, report: dict) -> dict:
    """Hard verification. Every sub-check appears in the return dict so
    the operator can see exactly which deliverable failed."""
    wd = Path(workflow_dir)
    out = wd / "output"
    ws = wd / "workspace"

    # Collect candidates from output/ and workspace/ (excluding runs/ chaff)
    def _gather(base: Path) -> list[Path]:
        if not base.exists():
            return []
        return [
            f
            for f in base.rglob("*")
            if "runs" not in str(f) and "repo_workdir" not in str(f) and f.is_file()
        ]

    all_files = _gather(out) + _gather(ws)
    by_name = {f.name.lower(): f for f in all_files}

    def _find(name: str) -> Path | None:
        name = name.lower()
        if name in by_name:
            return by_name[name]
        # Match suffix (e.g. paper_de.pdf anywhere)
        for f in all_files:
            if f.name.lower() == name:
                return f
        return None

    pdf_de = _find("paper_de.pdf")
    pdf_en = _find("paper_en.pdf")
    md_de = _find("paper_de.md")
    md_en = _find("paper_en.md")

    # Diagram: any PNG under output/ or workspace/figures
    diagrams = [
        f
        for f in all_files
        if f.suffix.lower() == ".png"
        and ("figure" in str(f).lower() or "diagram" in str(f).lower() or f.parent.name == "figures")
    ]
    if not diagrams:
        diagrams = [f for f in all_files if f.suffix.lower() == ".png"]

    tex_files = [f for f in all_files if f.suffix == ".tex"]
    bib_files = [f for f in all_files if f.suffix == ".bib"]

    # Page counts (must be 8 exactly)
    pages_de = _count_pdf_pages(pdf_de) if pdf_de else None
    pages_en = _count_pdf_pages(pdf_en) if pdf_en else None

    # Word counts per MD (rough sanity check)
    md_de_txt = _read_text(md_de) if md_de else ""
    md_en_txt = _read_text(md_en) if md_en else ""
    words_de = _count_words(md_de_txt)
    words_en = _count_words(md_en_txt)

    checks = {
        "pdf_de": str(pdf_de) if pdf_de else None,
        "pdf_en": str(pdf_en) if pdf_en else None,
        "md_de": str(md_de) if md_de else None,
        "md_en": str(md_en) if md_en else None,
        "pages_de": pages_de,
        "pages_en": pages_en,
        "words_de": words_de,
        "words_en": words_en,
        "n_diagrams": len(diagrams),
        "diagram_examples": [str(d) for d in diagrams[:3]],
        "n_tex": len(tex_files),
        "n_bib": len(bib_files),
        "pdf_de_size": pdf_de.stat().st_size if pdf_de else 0,
        "pdf_en_size": pdf_en.stat().st_size if pdf_en else 0,
    }

    # Hard gates
    ok = bool(
        pdf_de
        and pdf_en
        and pdf_de.stat().st_size > 20_000
        and pdf_en.stat().st_size > 20_000
        and pages_de == 8
        and pages_en == 8
        and md_de
        and md_en
        # Lower-bound word counts: 9000 target; accept 7000 as soft pass
        and words_de >= 7000
        and words_en >= 7000
        and len(diagrams) >= 1
        and len(tex_files) >= 1
        and len(bib_files) >= 1
    )
    return {"ok": ok, **checks}


if __name__ == "__main__":
    if not _check_tectonic():
        print(
            "[e2e] WARNING: `tectonic` not on PATH — LaTeX compilation will fail. "
            "Install with: curl -sSL https://github.com/tectonic-typesetting/tectonic/releases/download/tectonic@0.15.0/tectonic-0.15.0-x86_64-unknown-linux-musl.tar.gz -o /tmp/t.tgz && tar xzf /tmp/t.tgz -C ~/.local/bin/",
            file=sys.stderr,
        )

    slug = "bilingual-arxiv-8p-paper"
    title = "Bilingual arXiv 8-page Paper (DE+EN) on AWP Tool/Skill Generation"

    # Pre-create the experiment directory and seed inputs BEFORE run_e2e
    # so the first worker can read `_workspace_dir/inputs/` on dispatch.
    from _harness import make_experiment_dir  # type: ignore

    workflow_dir = make_experiment_dir(slug)
    _seed_inputs_into_workspace(workflow_dir)
    print(f"[e2e] seeded inputs into: {workflow_dir}")

    report = run_e2e(
        slug=slug,
        title=title,
        task=TASK,
        model="openai/gpt-5-mini",
        worker_model="openai/gpt-5-mini",
        max_loops=200,
        max_total_tokens=80_000_000,
        max_wall_time=54_000,       # 15 hours
        max_total_workers=300,
        max_depth=4,
        max_tool_calls=10_000,
        workflow_dir=workflow_dir,
        extra_config={
            "critique": {
                "enabled": True,
                "min_score_to_complete": 0.4,
                "max_repair_attempts": 6,
                "phase_aware_incomplete": True,
                "defect_category_hard_cap": 60,
                "defect_category_diagnose_threshold": 15,
                "min_score_to_delegate": 0.25,
                "max_delegation_blocks": 6,
            },
            "planning": {
                "plan_commit_mode": "strict",
            },
            "trace_enabled": True,
            "tool_creation": {"enabled": True},
            "code_mode": True,
        },
        verifier=verify,
        tags=[
            "e2e",
            "s5",
            "paper-pipeline",
            "bilingual",
            "tool-creation",
            "critique",
            "planning",
        ],
    )

    status = report.get("status", "unknown")
    duration = report.get("duration_s", 0)
    verification = report.get("verification", {})
    print(f"\n{'=' * 60}")
    print(f"E2E Result: {status}")
    print(f"Duration: {duration:.0f}s" if isinstance(duration, (int, float)) else f"Duration: {duration}")
    print(f"Workflow dir: {report.get('workflow_dir', '?')}")
    print(f"Verification: {verification}")
    print(f"{'=' * 60}")
    sys.exit(0 if status in ("complete", "partial_complete", "partial") else 1)
