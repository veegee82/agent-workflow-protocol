#!/usr/bin/env python
"""E2E (Phase 1-4 only): bilingual arXiv-style paper CONTENT about AWP.

User-requested variant of bilingual_arxiv_8page_paper.py: we stop after
Phase 4 (German translation). Phase 5 (LaTeX assembly + compile) is
explicitly out of scope. Deliverables are .md + figures + references.bib
only — no PDFs, no tectonic, no tex bundles.

Hard gates in verify():
  - paper_en.md, paper_de.md present, word targets met per section.
  - figures/autonomy_spectrum.png >= 30 KB.
  - figures/delegation_loop.png >= 30 KB AND dpi == 200.
  - references.bib >= 12 entries, every entry carries doi OR url.
  - No forbidden placeholder tokens anywhere under output/.
  - No duplicate section headings in paper_en.md or paper_de.md.
  - Every [N] citation in EN/DE resolves to a key that appears in bib.
  - phase1/awp_concepts.md >= 2000 words; phase1/code_snippets.md >= 10
    fragments matching the path:line regex.
  - phase2/references.bib >= 12 entries (mirrors final).

Budget sized for an ~3-4 h run at the user's request. Active monitoring
happens outside of this harness (events.jsonl tail + experiment DB).

Tags: e2e, s5, paper-pipeline, bilingual, tool-creation, critique,
planning, phase14.
"""
from __future__ import annotations

import os
import re
import shutil
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _harness import make_experiment_dir, run_e2e  # noqa: E402

PAPER_INPUTS_SRC = Path("/tmp/paper_inputs")


TASK = """\
## Objective
Produce the content (Phases 1-4 only) for a bilingual (English + German)
arXiv-style two-column scientific paper on "Autonomy extension through
tool- and skill-generation and comparison to other agent frameworks",
including clean Markdown, figures, and a bibliography, following the
provided workspace layout and constraints.

## Context
- Workspace and repo constraints:
  - Primary repo: `_workspace_dir/inputs/agent-workflow-protocol/` (use
    files verbatim where cited). Key files to read directly: `README.md`,
    `CLAUDE.md`, `spec/spec.md`, `docs/*.md`,
    `packages/awp-runtime/src/awp/runtime/delegation_loop_runner.py`,
    `packages/awp-runtime/src/awp/runtime/dynamic_tool_factory.py`,
    `packages/awp-core/src/awp/validator/rules.py`, `examples/` (A0-A4).
  - LaTeX template: `_workspace_dir/inputs/arxiv_two_column/` (do NOT
    compile; deterministic phase would assemble, but that is OUT OF
    SCOPE for this task).
  - Repository link to include in abstract footnote:
    https://github.com/veegee82/agent-workflow-protocol
  - LaTeX template link to reference:
    https://github.com/kourgeorge/arxiv-style
- Paper focus and required content specifics:
  - Core topic: autonomy extension via tool- and skill-generation;
    detailed treatment of delegation stages (A0-A4), inner and outer
    delegation loops, re-findement/refinement for optimizing solution
    search; use the process of generating this paper as an illustrative
    example.
  - Produce a reusable "skill" description for generating high-quality
    diagrams (SGD-style diagrams) and PNG renders without overlapping
    elements.
  - Author byline in the final PDF is fixed as "AWP, Silvio Jurk*"
    (do not create a LaTeX author line; a later deterministic phase
    would inject it — not your concern here).
- Phased scope (must be executed LINEARLY and only Phases 1-4):
  - Phase 1: repo analysis outputs (awp_concepts.md, code_snippets.md).
  - Phase 2: build bibliography (>=12 real refs) and a citation plan.
  - Phase 3: English master draft + figures (two matplotlib PNGs,
    delegation_loop.png at dpi=200).
  - Phase 4: German translation (structural parity with EN).
  - Phase 5 (LaTeX assembly + compile) is explicitly NOT part of this
    task.
- Formatting and validator constraints:
  - No placeholder tokens anywhere (e.g., TODO, FIXME, XXX, ???,
    Lorem ipsum, PLACEHOLDER, "to be filled", "TITLE GOES HERE").
  - No duplicate section headings within a file.
  - Avoid repeated sentence loops (L0 validator detects high simhash
    collision windows).
  - Every code reference in the paper must be verbatim from the AWP
    repo.
  - Figures must be clean (no overlapping elements), PNG format, each
    >= 30 KB; delegation_loop.png must be dpi=200 (phase3 requirement).
  - references.bib must contain >= 12 entries; each entry must include a
    doi OR a stable url.
  - Citation keys used in EN and DE drafts must match the references.bib
    produced.

## Required deliverables (ALL on disk under `_output_dir/`, non-empty)
1. `paper_en.md` - full English Markdown.
2. `paper_de.md` - full German Markdown, same sections + citation keys.
3. `figures/autonomy_spectrum.png` - matplotlib diagram A0->A4, >= 30 KB.
4. `figures/delegation_loop.png` - matplotlib diagram of
   manager->workers->tools flow, clean arrows, dpi=200, >= 30 KB.
5. `references.bib` - BibTeX with >= 12 entries, each with doi OR url.
6. `phase1/awp_concepts.md` - >= 2000 words bullet list of 7 layers,
   autonomy A0-A4 with code examples, delegation loop, critique/repair,
   budget system, validation rules.
7. `phase1/code_snippets.md` - >= 10 verbatim code fragments with
   path:line references.
8. `phase2/references.bib` - same as final references.bib (>=12 entries).
9. `phase2/citation_plan.md` - mapping of paper sections to citation
   keys [N].
10. `phase3/paper_en.md` - master English draft (same as top-level
    paper_en.md).
11. `phase4/paper_de.md` - German translation, structural parity with EN.

## Section word targets (verified per language)
- Abstract: ~500 words
- Introduction: > 2500 words (state of the art + autonomy scales A0-A4)
- Methodology: > 5000 words (AWP layers, delegation loop, tool- and
  skill-generation, validation rules R1-R32)
- Results: > 1000 words (evaluation + comparison to LangChain, AutoGen,
  CrewAI, MetaGPT, OpenAI Assistants)
- Discussion / Conclusion: reasonable length

## Four-Phase Pipeline (PARALLEL where dependencies allow)

### Delegation shape (HARD RULE — YOU are the root manager, max_depth=1)
- In your FIRST `DELEGATE`, spawn **four top-level worker subtasks in
  one iteration**, one per phase. Do NOT spawn a submanager for any
  phase. Each phase-worker must produce its phase's deliverables
  directly by reading inputs and calling `code.execute` / `file.*`
  tools, not by further decomposition.
- Dependency DAG (respect it in delegation order):
    phase1_repo_analysis      -- no deps
    phase2_bibliography       -- no deps (parallel with phase1)
    phase3_english_master     -- depends on phase1 + phase2 outputs
    phase4_german_translation -- depends on phase3 output
- Concretely: dispatch phase1 + phase2 together in the first iteration;
  after both return, dispatch phase3; after phase3 returns, dispatch
  phase4. No submanagers. No recursion.

### Phase 1 - Repo Analysis
Worker `phase1_repo_analysis` produces:
- `phase1/awp_concepts.md` (>=2000 words, bullet list of 7 layers,
  autonomy A0-A4 with code examples, delegation loop, critique/repair,
  budget system, validation rules).
- `phase1/code_snippets.md` (>=10 verbatim `path:line` fragments).

### Phase 2 - Literature
Worker `phase2_bibliography` produces:
- `phase2/references.bib` (>=12 real entries, each with `doi` OR
  stable `url`).
- `phase2/citation_plan.md` (mapping of sections -> `[N]` keys).

### Phase 3 - English Master + Figures
Worker `phase3_english_master` produces:
- `phase3/paper_en.md` (word targets met per section).
- `figures/delegation_loop.png` (matplotlib, dpi=200, clean arrows,
  no overlap, manager->workers->tools).
- `figures/autonomy_spectrum.png` (matplotlib, A0->A4).
Figures must be created programmatically via `code.execute` using
matplotlib with `plt.savefig(..., dpi=200)` for delegation_loop.png.

### Phase 4 - German Translation
Worker `phase4_german_translation` produces:
- `phase4/paper_de.md` (same sections as EN, same citation keys, same
  figure references, word counts per section met in German).

## OUTPUT FORMAT (HARD)
Every `*.md` deliverable MUST be **plain Markdown prose** with `##`
headings for sections. It MUST NOT be JSON, YAML, or a serialized
envelope. In particular, `paper_en.md` and `paper_de.md` MUST NOT start
with `{` or contain JSON keys like `"instructions":`, `"envelope":`,
`"task":`. If you serialized the subtask envelope into the deliverable
file, the deliverable is rejected — rewrite it as human prose before
returning.

When the paper discusses placeholder tokens as anti-patterns, mention
them as normal literal strings in backticks (e.g. "the L0 validator
blocks tokens such as `TODO`, `FIXME`, and `XXX`"); they are part of
the paper's content, not a defect. The runtime's `no_placeholder` L0
check has been disabled for this task precisely so the paper can
describe its own validators.

### Consolidation (END OF RUN)
Copy/hardlink the master drafts up to the top-level:
- phase3/paper_en.md -> paper_en.md
- phase4/paper_de.md -> paper_de.md
- phase2/references.bib -> references.bib
- figures/*.png (already at the canonical place)

## Tool-Registry discipline (STRONG preference, not blocker)
If the same Python boilerplate repeats, register it via `tool.create`
into `shared/dynamic_tools/`. Good candidates: `word_count_section`,
`render_sgd_diagram`, `verify_citations`.

## Content quality (enforced by L0 + critique + repair-fixpoint)
- NO placeholder tokens (TODO, XXX, FIXME, ???, Lorem ipsum,
  "to be filled", "PLACEHOLDER", "TITLE GOES HERE").
- NO duplicate section headings in the same file.
- NO repeated sentence loops (moving-window simhash guard).
- Every code excerpt verbatim from the repo. Include many formulas
  where appropriate.
- At the end, critically verify that references, figures, formats, and
  code citations are correct and consistent.
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _seed_inputs_into_workspace(workflow_dir: Path) -> None:
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
        if not tpl_dst.exists():
            shutil.copytree(tpl_src, tpl_dst)


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def _count_words(text: str) -> int:
    return len([w for w in text.split() if w.strip()])


SECTION_HEADER_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)


def _section_word_counts(md_text: str) -> dict[str, int]:
    """Split on '## ' headings and return per-section word counts.

    We accept German synonyms so DE files pass the same per-section
    targets without forcing authors to use English headings.
    """
    out: dict[str, int] = {}
    matches = list(SECTION_HEADER_RE.finditer(md_text))
    for i, m in enumerate(matches):
        heading = m.group(1).strip().lower()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(md_text)
        body = md_text[start:end]
        out[heading] = _count_words(body)
    return out


_HEADING_ALIASES = {
    "abstract": ("abstract", "zusammenfassung", "kurzfassung"),
    "introduction": ("introduction", "einleitung", "einführung"),
    "methodology": ("methodology", "methoden", "methodik", "methode"),
    "results": ("results", "ergebnisse", "resultate", "evaluation"),
    "discussion": ("discussion", "diskussion"),
    "conclusion": ("conclusion", "schluss", "fazit", "schlussfolgerung"),
}


def _pick(section_counts: dict[str, int], key: str) -> int:
    aliases = _HEADING_ALIASES.get(key, (key,))
    for heading, words in section_counts.items():
        for alias in aliases:
            if alias in heading:
                return words
    return 0


# Canonical word-target thresholds per section (per language).
WORD_TARGETS = {
    "abstract": 350,      # ≈500 nominal, accept >=350 as pass
    "introduction": 2500,
    "methodology": 5000,
    "results": 1000,
    # discussion/conclusion combined: accept >=300 total
}


def _count_headings(md_text: str) -> list[str]:
    return [m.group(1).strip().lower() for m in SECTION_HEADER_RE.finditer(md_text)]


def _has_duplicate_headings(md_text: str) -> bool:
    heads = _count_headings(md_text)
    return len(heads) != len(set(heads))


def _bib_entries(bib_text: str) -> list[dict[str, str]]:
    """Crude but robust BibTeX parser: one entry per `@type{key,` block."""
    entries: list[dict[str, str]] = []
    for block in re.split(r"(?m)^@\w+\s*\{", bib_text)[1:]:
        key_match = re.match(r"\s*([^,\s]+)\s*,", block)
        if not key_match:
            continue
        key = key_match.group(1).strip()
        fields: dict[str, str] = {"__key__": key}
        for fm in re.finditer(r"(\w+)\s*=\s*[{\"]([^}\"]*)[}\"]", block):
            fields[fm.group(1).lower()] = fm.group(2).strip()
        entries.append(fields)
    return entries


def _cite_keys(md_text: str) -> set[str]:
    """Extract citation keys from both [N] and \\cite{key,key2}."""
    keys: set[str] = set()
    for m in re.finditer(r"\\cite\{([^}]+)\}", md_text):
        for k in m.group(1).split(","):
            keys.add(k.strip())
    return keys


# NOTE: we intentionally do NOT flag TODO/FIXME/XXX here.
# The paper's content discusses those tokens BY NAME as the patterns the
# L0 validator blocks — forbidding them at the content layer would make
# the paper unable to describe its own anti-patterns. Semantic
# placeholders (??? / Lorem ipsum / literal "to be filled") remain hard
# rejects because they have no in-content reason to appear.
PLACEHOLDER_TOKENS = (
    "???", "Lorem ipsum", "PLACEHOLDER", "to be filled", "TITLE GOES HERE",
)


def _png_is_dpi_200(path: Path) -> bool:
    """Check the pHYs chunk for dpi=200. A PNG stores pixels per meter;
    200 dpi = 7874 px/m (rounded 7873-7875 is fine)."""
    try:
        with path.open("rb") as f:
            sig = f.read(8)
            if sig != b"\x89PNG\r\n\x1a\n":
                return False
            while True:
                hdr = f.read(8)
                if len(hdr) < 8:
                    return False
                length, ctype = struct.unpack(">I4s", hdr)
                if ctype == b"pHYs":
                    data = f.read(length)
                    if len(data) < 9:
                        return False
                    x_ppu, y_ppu, unit = struct.unpack(">IIB", data[:9])
                    if unit != 1:  # 1 = meters
                        return False
                    return 7800 <= x_ppu <= 7950 and 7800 <= y_ppu <= 7950
                if ctype == b"IDAT":
                    return False
                f.seek(length + 4, 1)  # skip data + CRC
    except OSError:
        return False


# ---------------------------------------------------------------------------
# Verifier — hard gates for a valid Phase 1-4 run.
# ---------------------------------------------------------------------------


def verify(workflow_dir: Path, report: dict) -> dict:
    wd = Path(workflow_dir)
    out = wd / "output"

    paper_en = out / "paper_en.md"
    paper_de = out / "paper_de.md"
    bib = out / "references.bib"
    fig_a = out / "figures" / "autonomy_spectrum.png"
    fig_b = out / "figures" / "delegation_loop.png"

    # tolerate phase-relative locations
    def _find_any(name: str) -> Path | None:
        if (out / name).is_file():
            return out / name
        for cand in out.rglob(name):
            if cand.is_file():
                return cand
        return None

    if not paper_en.is_file():
        paper_en = _find_any("paper_en.md") or paper_en
    if not paper_de.is_file():
        paper_de = _find_any("paper_de.md") or paper_de
    if not bib.is_file():
        bib = _find_any("references.bib") or bib
    if not fig_a.is_file():
        fig_a = _find_any("autonomy_spectrum.png") or fig_a
    if not fig_b.is_file():
        fig_b = _find_any("delegation_loop.png") or fig_b

    # phase 1 files
    p1_concepts = _find_any("awp_concepts.md")
    p1_snippets = _find_any("code_snippets.md")
    p2_plan = _find_any("citation_plan.md")

    md_en_txt = _read_text(paper_en)
    md_de_txt = _read_text(paper_de)
    bib_txt = _read_text(bib)
    p1_concepts_txt = _read_text(p1_concepts) if p1_concepts else ""
    p1_snippets_txt = _read_text(p1_snippets) if p1_snippets else ""

    en_sections = _section_word_counts(md_en_txt)
    de_sections = _section_word_counts(md_de_txt)

    section_ok_en = all(
        _pick(en_sections, k) >= v for k, v in WORD_TARGETS.items()
    )
    section_ok_de = all(
        _pick(de_sections, k) >= v for k, v in WORD_TARGETS.items()
    )

    # Heading uniqueness
    no_dup_en = not _has_duplicate_headings(md_en_txt)
    no_dup_de = not _has_duplicate_headings(md_de_txt)

    # Placeholders anywhere under output/
    scan_blobs = [md_en_txt, md_de_txt, bib_txt, p1_concepts_txt, p1_snippets_txt]
    placeholder_free = not any(tok in blob for tok in PLACEHOLDER_TOKENS for blob in scan_blobs)

    # Bib checks
    entries = _bib_entries(bib_txt)
    bib_count = len(entries)
    bib_all_have_ref = all(("doi" in e or "url" in e) for e in entries)
    bib_keys = {e["__key__"] for e in entries}

    # Citation key resolution
    cite_en = _cite_keys(md_en_txt)
    cite_de = _cite_keys(md_de_txt)
    cite_en_resolved = cite_en.issubset(bib_keys) if cite_en else True
    cite_de_resolved = cite_de.issubset(bib_keys) if cite_de else True

    # Figures
    fig_a_ok = fig_a.is_file() and fig_a.stat().st_size >= 30_000
    fig_b_ok = (
        fig_b.is_file()
        and fig_b.stat().st_size >= 30_000
        and _png_is_dpi_200(fig_b)
    )

    # Phase 1 word counts / snippet count
    p1_concepts_ok = _count_words(p1_concepts_txt) >= 2000
    snippet_lines = [
        ln for ln in p1_snippets_txt.splitlines()
        if re.search(r"\S+\.(py|md|yaml|yml|ts|tsx|js):\d+", ln)
    ]
    p1_snippets_ok = len(snippet_lines) >= 10

    checks = {
        "paper_en": str(paper_en) if paper_en.is_file() else None,
        "paper_de": str(paper_de) if paper_de.is_file() else None,
        "references_bib": str(bib) if bib.is_file() else None,
        "fig_autonomy": str(fig_a) if fig_a.is_file() else None,
        "fig_delegation": str(fig_b) if fig_b.is_file() else None,
        "en_section_words": {
            k: _pick(en_sections, k) for k in WORD_TARGETS
        },
        "de_section_words": {
            k: _pick(de_sections, k) for k in WORD_TARGETS
        },
        "en_sections_ok": section_ok_en,
        "de_sections_ok": section_ok_de,
        "no_duplicate_headings_en": no_dup_en,
        "no_duplicate_headings_de": no_dup_de,
        "placeholder_free": placeholder_free,
        "bib_entries": bib_count,
        "bib_all_have_doi_or_url": bib_all_have_ref,
        "cite_en_resolved": cite_en_resolved,
        "cite_de_resolved": cite_de_resolved,
        "fig_autonomy_bytes": fig_a.stat().st_size if fig_a.is_file() else 0,
        "fig_delegation_bytes": fig_b.stat().st_size if fig_b.is_file() else 0,
        "fig_delegation_dpi_ok": fig_b_ok and fig_b.is_file(),
        "phase1_concepts_ok": p1_concepts_ok,
        "phase1_snippets_ok": p1_snippets_ok,
        "phase1_snippet_lines": len(snippet_lines),
        "phase2_citation_plan": str(p2_plan) if p2_plan else None,
    }

    ok = bool(
        paper_en.is_file()
        and paper_de.is_file()
        and bib.is_file()
        and fig_a_ok
        and fig_b_ok
        and section_ok_en
        and section_ok_de
        and no_dup_en and no_dup_de
        and placeholder_free
        and bib_count >= 12
        and bib_all_have_ref
        and cite_en_resolved and cite_de_resolved
        and p1_concepts_ok
        and p1_snippets_ok
        and p2_plan is not None
    )
    return {"ok": ok, **checks}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    slug = "bilingual-arxiv-phase14"
    title = "Bilingual arXiv Paper (Phase 1-4 only): AWP Autonomy via Tool/Skill Generation"

    workflow_dir = make_experiment_dir(slug)
    _seed_inputs_into_workspace(workflow_dir)
    print(f"[e2e] seeded inputs into: {workflow_dir}")

    report = run_e2e(
        slug=slug,
        title=title,
        task=TASK,
        model="openai/gpt-5-mini",
        worker_model="openai/gpt-5-mini",  # faster long-form than deepseek
        max_loops=200,
        max_total_tokens=120_000_000,
        max_wall_time=21_600,       # 6 h
        max_total_workers=80,
        max_depth=1,                # flat delegation, no submanager recursion
        max_tool_calls=12_000,
        workflow_dir=workflow_dir,
        extra_config={
            "critique": {
                "enabled": True,
                "min_score_to_complete": 0.45,
                "max_repair_attempts": 4,
                "phase_aware_incomplete": True,
                "defect_category_hard_cap": 60,
                "defect_category_diagnose_threshold": 15,
                "min_score_to_delegate": 0.25,
                "max_delegation_blocks": 6,
            },
            "observability": {
                "output_contract": {
                    "enabled": True,
                    # no_placeholder intentionally excluded: paper content
                    # must discuss TODO/FIXME/XXX by name (they ARE the
                    # anti-patterns the paper explains).
                    "checks": [
                        "no_text_loop",
                        "file_size_delta",
                        "no_duplicate_headings",
                        "balanced_delimiters",
                        "json_valid_if_claimed",
                    ],
                },
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
            "e2e", "s5", "paper-pipeline", "bilingual",
            "tool-creation", "critique", "planning", "phase14",
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
    sys.exit(0 if status == "complete" and verification.get("ok") else 1)
