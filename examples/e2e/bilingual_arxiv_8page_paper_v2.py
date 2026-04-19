#!/usr/bin/env python
"""E2E v2: bilingual (DE+EN) 8-page arXiv paper with Compiler-Layer assembly.

This is the v2 pipeline that validates the Compiler-Layer stack landed
in commits 29083ab / 76a1419 / 561ae31 / b23e262 — especially the
DeterministicPhaseRunner from Phase 2 and the R35 repair-fixpoint guard
from Phase 3.1. The LLM delegation loop produces only the content
artefacts (clean paper_en.md / paper_de.md / figures / references.bib);
Phase 5 (LaTeX assembly + 8-page compile) is handed off to a
deterministic phase powered by ``_paper_assembler.build_bilingual_papers``
so the LLM never touches mechanical string manipulation again.

Content-quality defences on the LLM side:
  * L0 Validator (Phase 1, R34) catches text loops, placeholders,
    duplicate sections, and file-size runaway BEFORE critique runs.
  * Repair-fixpoint guard (Phase 3.1, R35) aborts repair chains that
    converge on near-identical outputs.

The E2E verifier asserts, after the deterministic phase has run:
  * 2 PDFs exist, each exactly 8 pages
  * 2 MD sources exist (paper_{de,en}.md)
  * Figures (autonomy_spectrum.png, delegation_loop.png) >= 30 KB
  * references.bib has >= 12 entries
  * Author line "AWP, Silvio Jurk*" present on page 1 of both PDFs
  * No placeholder tokens in any .md / .tex

Tags: e2e, s5, paper-pipeline, bilingual, tool-creation, critique,
planning, deterministic-assembly, v2.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

# Put the E2E dir on sys.path so _paper_assembler resolves in the parent
# process AND propagates into the DeterministicPhaseRunner subprocess
# (the runner copies parent sys.path into PYTHONPATH).
_E2E_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_E2E_DIR))

from _harness import make_experiment_dir, run_e2e  # noqa: E402


# Make tectonic visible to every subprocess the delegation loop + the
# deterministic phase spawn.
_LOCAL_BIN = str(Path.home() / ".local" / "bin")
if _LOCAL_BIN not in os.environ.get("PATH", ""):
    os.environ["PATH"] = _LOCAL_BIN + os.pathsep + os.environ.get("PATH", "")


PAPER_INPUTS_SRC = Path("/tmp/paper_inputs")


# ---------------------------------------------------------------------------
# Task: Phase 1-4 only. Phase 5 is handled by the deterministic phase.
# Phase 1-4 bullets are kept close to v1 verbatim so the workflow still
# produces the same content; only the Phase 5 compile instructions are
# removed and replaced with a handoff note.
# ---------------------------------------------------------------------------


TASK_V2 = """\
## Objective
Produce the **content** of a bilingual (German + English), arXiv-style,
two-column scientific paper on **"Autonomy extension through tool- and
skill-generation and comparison to other agent frameworks"**. Your only
job is Phases 1-4: clean Markdown + figures + bibliography. Phase 5
(LaTeX assembly + 8-page compile) is NOT your job — a deterministic
phase will run it after you finish.

## Workspace layout (READ FIRST, DO NOT RE-ENUMERATE)
- `_workspace_dir/inputs/agent-workflow-protocol/` — the complete AWP
  repository. Key files (read these directly; do NOT re-list the whole
  tree): `README.md`, `CLAUDE.md`, `spec/spec.md`, `docs/*.md`,
  `packages/awp-runtime/src/awp/runtime/delegation_loop_runner.py`,
  `packages/awp-runtime/src/awp/runtime/dynamic_tool_factory.py`,
  `packages/awp-core/src/awp/validator/rules.py`,
  `examples/` (for autonomy-level examples A0-A4).
  **Every code reference in the paper MUST be verbatim from this repo.**
- `_workspace_dir/inputs/arxiv_two_column/` — reference LaTeX template.
  You do NOT compile LaTeX; the deterministic phase will do that.

## Required deliverables (ALL on disk under `_output_dir/`, non-empty)
1. `paper_en.md` — full English Markdown (word targets below).
2. `paper_de.md` — full German Markdown (same sections as EN).
3. `figures/autonomy_spectrum.png` — matplotlib diagram A0->A4, >= 30 KB.
4. `figures/delegation_loop.png`   — matplotlib diagram of the
   manager->workers->tools flow, >= 30 KB.
5. `references.bib` — BibTeX with >= 12 entries, each with `doi` OR `url`.

## Section word targets (verified per language)
- Abstract: ~500 words
- Introduction: > 2500 words (state of the art + autonomy scales A0-A4)
- Methodology: > 5000 words (AWP layers, delegation loop, tool- and
  skill-generation, validation rules R1-R32)
- Results: > 1000 words (evaluation + comparison to LangChain, AutoGen,
  CrewAI, MetaGPT, OpenAI Assistants)
- Discussion / Conclusion: reasonable length
- References: every `[N]` used in-text

## Content quality (enforced by L0 validator + critique + repair-fixpoint)
- NO placeholder tokens anywhere: `TODO`, `XXX`, `FIXME`, `???`,
  `Lorem ipsum`, "to be filled", "PLACEHOLDER", "TITLE GOES HERE".
- NO duplicate section headings in the same file.
- NO text loops (the same 2-3 sentences repeated). The L0 validator
  blocks output where a moving-window simhash collision rate is high.
- The author byline is fixed: **"AWP, Silvio Jurk*"** (the
  deterministic phase injects it into the PDF title block; you do not
  need to write a LaTeX author line).

## Four-Phase Pipeline (execute LINEARLY, do NOT skip ahead)

### Phase 1 - Repo Analysis (EXIT when criteria met, then MOVE ON)
Extract concrete methodology material from the AWP repo. Produce:
- `_output_dir/phase1/awp_concepts.md` - >= 2000 words bullet list of
  7 layers, autonomy A0-A4 with code examples, delegation loop,
  critique/repair, budget system, validation rules.
- `_output_dir/phase1/code_snippets.md` - 10+ verbatim code fragments
  with `path:line` references.

### Phase 2 - Literature (EXIT when >= 12 real references)
Build BibTeX with >= 12 real citations covering: agent frameworks
(LangChain, AutoGen, CrewAI, MetaGPT, OpenAI Assistants), dynamic tool
creation, program synthesis, autonomy in multi-agent systems.
- `_output_dir/phase2/references.bib` - >= 12 entries, each with `doi`
  OR stable `url`.
- `_output_dir/phase2/citation_plan.md` - maps each section to the
  `[N]` it will cite.

### Phase 3 - English Master Draft
- `_output_dir/phase3/paper_en.md` - full prose, word targets met per
  section. Abstract headed `## Abstract`; body sections `## Introduction`,
  `## Methodology`, `## Results`, `## Discussion`, `## Conclusion`.
- `_output_dir/figures/delegation_loop.png` - matplotlib diagram,
  clean arrows, dpi=200.
- `_output_dir/figures/autonomy_spectrum.png` - second diagram A0->A4.

### Phase 4 - German Translation (EXIT at structural parity)
- `_output_dir/phase4/paper_de.md` - same sections, same figure refs,
  same citation keys. Word counts apply per language.

### Consolidation (final step before COMPLETE)
Copy the final artefacts up to the canonical paths the deterministic
phase reads:
- `_output_dir/paper_en.md`    (from phase3/paper_en.md)
- `_output_dir/paper_de.md`    (from phase4/paper_de.md)
- `_output_dir/references.bib` (from phase2/references.bib)
- `_output_dir/figures/*.png`  (already in place)

The AWP root manager's canonical output promoter (`output/FINAL/`)
will also collect these under a single pointer, but the deterministic
phase prefers the direct `_output_dir/` paths because they are written
by the same root manager.

### Phase 5 — NOT YOUR JOB
Phase 5 (LaTeX assembly + 8-page compile) is handled by a deterministic
phase that runs AFTER you finish. Do not generate main.tex, do not run
tectonic, do not try to tune page count. Your COMPLETE is only the
content phases above.

## Tool-Registry discipline (STRONG preference, not blocker)
Register reusable operations (e.g. `word_count_section`,
`render_sgd_diagram`, `verify_citations`) via `tool.create` so they
persist in `shared/dynamic_tools/` for later workers.
"""


# ---------------------------------------------------------------------------
# Helpers shared with v1 (kept in sync).
# ---------------------------------------------------------------------------


def _count_pdf_pages(path: Path) -> int | None:
    """Best-effort page count via PyPDF2 / pypdf."""
    try:
        from PyPDF2 import PdfReader  # type: ignore
    except ImportError:
        try:
            from pypdf import PdfReader  # type: ignore
        except ImportError:
            return None
    try:
        return len(PdfReader(str(path)).pages)
    except Exception:  # noqa: BLE001
        return None


def _first_page_text(path: Path) -> str:
    try:
        from PyPDF2 import PdfReader  # type: ignore
    except ImportError:
        try:
            from pypdf import PdfReader  # type: ignore
        except ImportError:
            return ""
    try:
        r = PdfReader(str(path))
        if not r.pages:
            return ""
        return r.pages[0].extract_text() or ""
    except Exception:  # noqa: BLE001
        return ""


def _bib_entry_count(path: Path) -> int:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return 0
    return len(re.findall(r"(?m)^\s*@\w+\s*\{", text))


def _check_tectonic() -> bool:
    try:
        r = subprocess.run(
            ["tectonic", "--version"], capture_output=True, text=True, timeout=10
        )
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _seed_inputs_into_workspace(workflow_dir: Path) -> None:
    """Copy /tmp/paper_inputs/* into the experiment's shared/inputs and
    workspace/inputs so workers read them via `_workspace_dir/inputs/`."""
    shared_inputs = workflow_dir / "shared" / "inputs"
    workspace_inputs = workflow_dir / "workspace" / "inputs"
    for target in (shared_inputs, workspace_inputs):
        target.mkdir(parents=True, exist_ok=True)
        awp_link = target / "agent-workflow-protocol"
        if not awp_link.exists():
            try:
                awp_link.symlink_to(
                    PAPER_INPUTS_SRC / "agent-workflow-protocol",
                    target_is_directory=True,
                )
            except OSError:
                shutil.copytree(
                    PAPER_INPUTS_SRC / "agent-workflow-protocol",
                    awp_link,
                    symlinks=True,
                    ignore=shutil.ignore_patterns(
                        ".git", "__pycache__", "node_modules", "*.pyc", ".venv"
                    ),
                )
        tpl_src = PAPER_INPUTS_SRC / "arxiv_two_column"
        tpl_dst = target / "arxiv_two_column"
        if not tpl_dst.exists() and tpl_src.exists():
            shutil.copytree(tpl_src, tpl_dst)


# ---------------------------------------------------------------------------
# Deterministic-phase handoff.
# ---------------------------------------------------------------------------


def _resolve_inputs_for_assembler(workflow_dir: Path) -> dict[str, Path]:
    """Pick the authoritative artefacts for the deterministic phase.

    Prefer ``output/FINAL/`` (written by the root manager on
    complete/partial exit per Phase 3.3). Fall back to the deepest
    non-empty versions elsewhere under ``output/`` when FINAL is empty
    — this mirrors the manager's own promotion logic.
    """
    out = workflow_dir / "output"
    final = out / "FINAL"

    def _pick(basename: str) -> Path | None:
        # 1. FINAL/ first.
        p = final / basename
        if p.is_file() and p.stat().st_size > 0:
            return p
        # 2. Deepest non-empty match under output/ (excluding runs/ chaff).
        candidates: list[tuple[int, Path]] = []
        if out.is_dir():
            for hit in out.rglob(basename):
                if not hit.is_file():
                    continue
                if "runs" in hit.parts:
                    continue
                try:
                    if hit.stat().st_size <= 0:
                        continue
                    candidates.append((len(hit.relative_to(out).parts), hit))
                except OSError:
                    continue
        if not candidates:
            return None
        candidates.sort(key=lambda t: (t[0], t[1].stat().st_mtime), reverse=True)
        return candidates[0][1]

    md_en = _pick("paper_en.md")
    md_de = _pick("paper_de.md")
    bib = _pick("references.bib")

    # Figures dir: if FINAL/figures exists use that, else pick the parent
    # of the deepest autonomy_spectrum.png.
    figs_dir = final / "figures"
    if not (figs_dir.is_dir() and any(figs_dir.glob("*.png"))):
        hit = _pick("autonomy_spectrum.png")
        figs_dir = hit.parent if hit else (out / "figures")

    return {
        "md_en": md_en or (final / "paper_en.md"),
        "md_de": md_de or (final / "paper_de.md"),
        "bib": bib or (final / "references.bib"),
        "figs": figs_dir,
    }


def _run_deterministic_phase(workflow_dir: Path) -> dict[str, Any]:
    """Instantiate DeterministicPhaseRunner and execute the assembler.

    Kept out of ``verify()`` so verification stays read-only on disk —
    this function MUTATES the workflow_dir (writes the PDFs + latex
    bundles into ``output/``).
    """
    try:
        from awp.models.orchestration import DeterministicPhase
        from awp.runtime.deterministic import (
            DeterministicPhaseRunner,
            ExecutionContext,
        )
    except ImportError as exc:
        return {"ok": False, "error": f"awp-runtime import failed: {exc}"}

    srcs = _resolve_inputs_for_assembler(workflow_dir)
    output_dir = workflow_dir / "output"
    output_dir.mkdir(parents=True, exist_ok=True)

    phase = DeterministicPhase(
        id="assemble_papers",
        type="deterministic",
        callable="_paper_assembler:build_bilingual_papers",
        args={
            "input_md_en": str(srcs["md_en"]),
            "input_md_de": str(srcs["md_de"]),
            "refs_bib": str(srcs["bib"]),
            "figures_dir": str(srcs["figs"]),
            "output_dir": str(output_dir),
            "template_path": "",
        },
        timeout_s=1800,  # 30 min — tuning loop is bounded at 6*2 compiles
        invariants=[
            {"kind": "file_exists", "path": "${output}/paper_en.pdf"},
            {"kind": "file_exists", "path": "${output}/paper_de.pdf"},
            {"kind": "file_size_range",
             "path": "${output}/paper_en.pdf",
             "min_bytes": 20_000, "max_bytes": 2_000_000},
            {"kind": "file_size_range",
             "path": "${output}/paper_de.pdf",
             "min_bytes": 20_000, "max_bytes": 2_000_000},
            {"kind": "regex_absent",
             "path": "${output}/paper_en.md",
             "pattern": r"\bTODO\b|TITLE GOES HERE|PLACEHOLDER"},
            {"kind": "regex_absent",
             "path": "${output}/paper_de.md",
             "pattern": r"\bTODO\b|TITLE GOES HERE|PLACEHOLDER"},
            {"kind": "python_predicate",
             "module": "_paper_assembler",
             "function": "verify_eight_pages"},
        ],  # type: ignore[arg-type]
    )

    ctx = ExecutionContext(
        workflow_dir=workflow_dir.resolve(),
        workspace_dir=(workflow_dir / "workspace").resolve(),
        output_dir=output_dir.resolve(),
        state={},
    )
    runner = DeterministicPhaseRunner(workflow_dir=workflow_dir.resolve())
    result = runner.run(phase, ctx)

    # Persist the phase result alongside the run artefacts for debugging.
    try:
        import json as _json
        (output_dir / "phase_assemble_papers").mkdir(parents=True, exist_ok=True)
        (output_dir / "phase_assemble_papers" / "result.json").write_text(
            _json.dumps(result.to_dict(), indent=2, default=str),
            encoding="utf-8",
        )
    except OSError:
        pass

    return {
        "ok": result.status == "complete",
        "status": result.status,
        "reason": result.reason,
        "duration_s": result.duration_s,
        "callable_result": result.callable_result,
        "invariants": [i.to_dict() for i in result.invariants],
    }


# ---------------------------------------------------------------------------
# Final verification (read-only, runs inside run_e2e after the phase).
# ---------------------------------------------------------------------------


def verify(workflow_dir: Path, report: dict) -> dict:
    """Post-deterministic-phase verifier. All checks are hard gates."""
    wd = Path(workflow_dir)
    out = wd / "output"

    pdf_en = out / "paper_en.pdf"
    pdf_de = out / "paper_de.pdf"
    md_en = out / "paper_en.md"
    md_de = out / "paper_de.md"
    bib = out / "references.bib"
    fig_a = out / "figures" / "autonomy_spectrum.png"
    fig_b = out / "figures" / "delegation_loop.png"

    # Fallbacks — tolerate the assembler writing figures into latex_{de,en}/.
    if not fig_a.is_file():
        for cand in out.rglob("autonomy_spectrum.png"):
            if cand.is_file():
                fig_a = cand
                break
    if not fig_b.is_file():
        for cand in out.rglob("delegation_loop.png"):
            if cand.is_file():
                fig_b = cand
                break

    pages_en = _count_pdf_pages(pdf_en) if pdf_en.is_file() else None
    pages_de = _count_pdf_pages(pdf_de) if pdf_de.is_file() else None

    md_en_txt = md_en.read_text(encoding="utf-8", errors="replace") if md_en.is_file() else ""
    md_de_txt = md_de.read_text(encoding="utf-8", errors="replace") if md_de.is_file() else ""
    p1_en = _first_page_text(pdf_en) if pdf_en.is_file() else ""
    p1_de = _first_page_text(pdf_de) if pdf_de.is_file() else ""

    # Aggregate all text files we have and scan for forbidden tokens.
    tex_files = list((out / "latex_en").rglob("*.tex")) + list((out / "latex_de").rglob("*.tex"))
    tex_blob = "\n".join(
        t.read_text(encoding="utf-8", errors="replace") for t in tex_files
    )
    forbidden = ("TODO", "FIXME", "XXX", "TITLE GOES HERE", "PLACEHOLDER", "Lorem ipsum")
    any_placeholder = any(
        tok in blob
        for tok in forbidden
        for blob in (md_en_txt, md_de_txt, tex_blob)
    )

    bib_entries = _bib_entry_count(bib) if bib.is_file() else 0
    fig_a_ok = fig_a.is_file() and fig_a.stat().st_size >= 30_000
    fig_b_ok = fig_b.is_file() and fig_b.stat().st_size >= 30_000
    author_ok_en = "AWP, Silvio Jurk" in p1_en
    author_ok_de = "AWP, Silvio Jurk" in p1_de

    checks = {
        "pdf_en": str(pdf_en) if pdf_en.is_file() else None,
        "pdf_de": str(pdf_de) if pdf_de.is_file() else None,
        "md_en": str(md_en) if md_en.is_file() else None,
        "md_de": str(md_de) if md_de.is_file() else None,
        "pages_en": pages_en,
        "pages_de": pages_de,
        "bib_entries": bib_entries,
        "fig_autonomy_bytes": fig_a.stat().st_size if fig_a.is_file() else 0,
        "fig_loop_bytes": fig_b.stat().st_size if fig_b.is_file() else 0,
        "author_line_en": author_ok_en,
        "author_line_de": author_ok_de,
        "placeholder_free": not any_placeholder,
    }

    ok = bool(
        pdf_en.is_file() and pdf_de.is_file()
        and pages_en == 8 and pages_de == 8
        and md_en.is_file() and md_de.is_file()
        and bib_entries >= 12
        and fig_a_ok and fig_b_ok
        and author_ok_en and author_ok_de
        and not any_placeholder
    )
    return {"ok": ok, **checks}


# ---------------------------------------------------------------------------
# Entry point.
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    if not _check_tectonic():
        print(
            "[e2e] WARNING: `tectonic` not on PATH - the deterministic "
            "phase will fail. Install into ~/.local/bin first.",
            file=sys.stderr,
        )

    slug = "bilingual-arxiv-8p-paper-v2"
    title = "Bilingual arXiv 8-page Paper v2 (Compiler-Layer + DeterministicPhase)"

    # Pre-create the experiment dir + seed inputs BEFORE run_e2e so the
    # first worker can read `_workspace_dir/inputs/` on dispatch.
    workflow_dir = make_experiment_dir(slug)
    _seed_inputs_into_workspace(workflow_dir)
    print(f"[e2e] seeded inputs into: {workflow_dir}")

    report = run_e2e(
        slug=slug,
        title=title,
        task=TASK_V2,
        model="openai/gpt-5-mini",
        worker_model="deepseek/deepseek-chat-v3.1",
        max_loops=120,
        max_total_tokens=50_000_000,
        max_wall_time=7200,         # 2h — delegation loop only, no compile.
        max_total_workers=200,
        max_depth=3,
        max_tool_calls=8_000,
        workflow_dir=workflow_dir,
        extra_config={
            "critique": {
                "enabled": True,
                "min_score_to_complete": 0.55,
                "max_repair_attempts": 3,
                "phase_aware_incomplete": True,
            },
            "observability": {
                "output_contract": {
                    "enabled": True,
                    "checks": ["default"],
                },
            },
            "planning": {
                "plan_commit_mode": "strict",
            },
            "trace_enabled": True,
            "tool_creation": {"enabled": True},
            "code_mode": True,
        },
        verifier=None,  # We run the deterministic phase ourselves below.
        tags=[
            "e2e", "s5", "paper-pipeline", "bilingual",
            "tool-creation", "critique", "planning",
            "deterministic-assembly", "v2",
        ],
    )

    status = report.get("status", "unknown")
    print(f"[e2e] delegation-loop status={status}")

    # Only run the assembler if the loop produced something usable.
    phase_result: dict[str, Any] = {
        "ok": False, "skipped": True, "reason": f"loop_status={status}"
    }
    if status in ("complete", "partial", "partial_complete"):
        print("[e2e] dispatching deterministic assembler phase ...")
        phase_result = _run_deterministic_phase(Path(report["workflow_dir"]))
        print(f"[e2e] phase status={phase_result.get('status')} "
              f"reason={phase_result.get('reason', '')}")

    # Final verification runs AFTER the phase — the PDFs only exist now.
    verification = verify(Path(report["workflow_dir"]), report)
    verify_ok = bool(verification.get("ok"))
    final_status = "complete" if verify_ok else (
        "partial" if status in ("complete", "partial", "partial_complete") else "failed"
    )

    # Persist a v2-specific report so the operator can inspect both the
    # delegation-loop outcome and the deterministic-phase outcome.
    try:
        import json as _json
        (Path(report["workflow_dir"]) / "e2e_report_v2.json").write_text(
            _json.dumps({
                "loop_report": report,
                "phase_result": phase_result,
                "verification": verification,
                "final_status": final_status,
            }, indent=2, default=str),
            encoding="utf-8",
        )
    except OSError:
        pass

    print(f"\n{'=' * 60}")
    print(f"E2E v2 Result: {final_status}")
    print(f"Loop status:   {status}")
    print(f"Phase status:  {phase_result.get('status')}")
    print(f"Verify ok:     {verify_ok}")
    print(f"Workflow dir:  {report.get('workflow_dir')}")
    print(f"Verification:  {verification}")
    print(f"{'=' * 60}")

    sys.exit(0 if verify_ok else 1)
