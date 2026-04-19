#!/usr/bin/env python
"""E2E: Recursive research compiler — stress-fix-c + stress-fix-d coverage.

Forces recursive sub-manager delegation: exactly four thematic sub-surveys
on iterative tool synthesis in LLM agents, each handled by a distinct
sub-manager at ``depth>=2``. Dynamic tool creation is mandatory for
citation extraction and coverage-check.

Exercises:
  * Fix C — ``max_rejected_completions`` circuit breaker (the manager is
    pushed to COMPLETE prematurely several times under this budget).
  * Fix D — plan-loop deterministic transition (``forced_delegate`` when
    pending thematic sub-surveys exist but the manager keeps PLANning).
  * Tool creation (dynamic_tools) and sub-manager delegation up to
    depth 3.

Tags: e2e, s5, recursive-delegation, tool-creation, sub-manager,
all-session-fixes, stress-fix-c, stress-fix-d
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _harness import make_experiment_dir, run_e2e  # noqa: E402

TASK = """\
## Objective

Produce a **technical survey** of iterative tool synthesis in LLM agents
with **exactly four thematic sub-surveys**:

  1. **Tool-generation primitives** — code synthesis, sandboxed
     execution, signature discovery, typed-I/O contracts.
  2. **Skill persistence and retrieval** — episodic/semantic skill
     stores, retrieval policies, skill-vs-tool distinction.
  3. **Recursive delegation patterns** — manager-worker trees,
     sub-manager promotion, budget reservations, cycle detection.
  4. **Evaluation and critique loops** — reflective critique, rubric
     scoring, targeted repair, cross-worker pattern memory.

## Delegation structure (REQUIRED)

Each of the four thematic sub-surveys MUST be **delegated to a
sub-manager at depth >= 2**. The root manager is the top-level
coordinator; it must spawn four sub-managers, one per theme. Each
sub-manager orchestrates its own workers (drafting, citation extraction,
coverage verification). Do NOT compress this into a single flat
delegation — the recursive structure is part of the deliverable.

## Dynamic tool creation (REQUIRED)

Create at least two dynamic tools via the tool factory:

  * A **citation extractor** that parses markdown/LaTeX and returns
    normalized BibTeX entries.
  * A **coverage checker** that maps citations to themes and returns a
    theme → citation_count histogram.

Reuse these tools across sub-managers.

## Required deliverables (ALL MUST exist on disk, non-empty)

1. ``_output_dir/survey.md`` — master survey with four distinct thematic
   ``## Theme: <name>`` (or equivalent) H2 headings, one per sub-survey.
   At least 15000 characters total.
2. ``_output_dir/survey.pdf`` — rendered PDF of the survey. >20KB.
3. ``_output_dir/references.bib`` — BibTeX file with **at least 20
   entries**. Every entry must match ``@\\w+\\{`` and carry ``author``,
   ``title``, and ``year`` fields. No duplicates.
4. ``_output_dir/section_coverage_report.json`` — JSON
   ``{"themes": {<theme>: <citation_count>, ...}, "total": N}`` covering
   all four themes with non-zero counts.

## Constraints

- Real citations only — no hallucinated references. Prefer well-known
  papers (ReAct, Toolformer, Reflexion, Voyager, etc.).
- No placeholders (``TODO``, ``XX%``, ``???``) in deliverables.
- Keep within budget — four tight thematic sub-surveys beat one bloated
  mega-survey.
"""


def verify(workflow_dir: Path, report: dict) -> dict:
    root = Path(workflow_dir)
    if not root.exists():
        return {"ok": False, "reason": "workflow_dir missing"}

    candidates: list[Path] = []
    for base in (root / "output", root / "workspace"):
        if base.exists():
            candidates.extend(p for p in base.rglob("*") if p.is_file())

    def _find(basename: str, min_size: int = 1) -> Path | None:
        for p in candidates:
            if p.name == basename and p.stat().st_size >= min_size:
                return p
        return None

    survey_md = _find("survey.md", 15_000)
    survey_pdf = _find("survey.pdf", 20_000)
    refs_bib = _find("references.bib", 200)
    coverage_json = _find("section_coverage_report.json", 10)

    themes_found: list[str] = []
    if survey_md:
        text = survey_md.read_text(encoding="utf-8", errors="replace")
        heading_patterns = [
            (r"(?im)^#{1,3}\s+.*(tool[-\s]?gen|primitive)", "primitives"),
            (r"(?im)^#{1,3}\s+.*(skill).*(persist|retriev|memor)",
             "skill_persistence"),
            (r"(?im)^#{1,3}\s+.*(recursive|delegation|sub[-\s]?manager)",
             "recursive_delegation"),
            (r"(?im)^#{1,3}\s+.*(evaluation|critique|reflection)",
             "evaluation_critique"),
        ]
        for pat, name in heading_patterns:
            if re.search(pat, text):
                themes_found.append(name)

    bib_entries: list[str] = []
    bib_fields_ok = False
    if refs_bib:
        bib_text = refs_bib.read_text(encoding="utf-8", errors="replace")
        bib_entries = re.findall(r"@\w+\{[^,]+,", bib_text)
        # Author / title / year presence across file (cheap aggregate)
        bib_fields_ok = (
            len(re.findall(r"(?im)^\s*author\s*=", bib_text)) >= 20
            and len(re.findall(r"(?im)^\s*title\s*=", bib_text)) >= 20
            and len(re.findall(r"(?im)^\s*year\s*=", bib_text)) >= 20
        )

    coverage_ok = False
    coverage_payload: dict = {}
    if coverage_json:
        try:
            import json as _json
            coverage_payload = _json.loads(
                coverage_json.read_text(encoding="utf-8", errors="replace")
            )
            themes_map = coverage_payload.get("themes", {})
            if isinstance(themes_map, dict) and len(themes_map) >= 4:
                coverage_ok = all(
                    isinstance(v, (int, float)) and v > 0
                    for v in themes_map.values()
                )
        except Exception:
            coverage_ok = False

    # Sub-manager depth evidence — a delegation path with depth >= 2.
    submanager_evidence = False
    runs_root = root / "workspace" / "runs"
    if runs_root.exists():
        for p in runs_root.rglob("run_manifest.json"):
            rel = str(p.relative_to(runs_root))
            # runs/<root_run>/delegations/<wid>/runs/<child>/... => depth>=2
            if rel.count("/runs/") >= 1 and "delegations" in rel:
                submanager_evidence = True
                break

    # Tool-creation evidence.
    tool_creation_evidence = False
    for p in root.rglob("*.json"):
        s = str(p)
        if "dynamic_tools" in s or "tool_factory" in s:
            tool_creation_evidence = True
            break

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
        "survey_md": str(survey_md) if survey_md else None,
        "survey_pdf": str(survey_pdf) if survey_pdf else None,
        "references_bib": str(refs_bib) if refs_bib else None,
        "coverage_json": str(coverage_json) if coverage_json else None,
        "themes_found": themes_found,
        "bib_entries": len(bib_entries),
        "bib_fields_ok": bib_fields_ok,
        "coverage_ok": coverage_ok,
        "coverage_payload": coverage_payload,
        "submanager_evidence": submanager_evidence,
        "tool_creation_evidence": tool_creation_evidence,
        "gates_fired": gates_fired,
    }
    ok = bool(
        survey_md and survey_pdf and refs_bib and coverage_json
        and len(themes_found) >= 4
        and len(bib_entries) >= 20 and bib_fields_ok
        and coverage_ok
    )
    return {"ok": ok, **checks}


if __name__ == "__main__":
    workflow_dir = make_experiment_dir("recursive-research-compiler")

    report = run_e2e(
        slug="recursive-research-compiler",
        title="Recursive Research Compiler — stress-fix-c + stress-fix-d",
        task=TASK,
        inputs={},
        model="openai/gpt-5-mini",
        worker_model="deepseek/deepseek-chat-v3.1",
        max_loops=35,
        max_total_tokens=6_000_000,
        max_wall_time=7200,
        max_total_workers=80,
        max_depth=3,
        max_tool_calls=4000,
        workflow_dir=workflow_dir,
        extra_config={
            "budget": {
                "max_workers_per_iteration": 6,
                "max_rejected_completions": 2,
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
            "dynamic_tools": {
                "enabled": True,
            },
            "trace_enabled": True,
        },
        verifier=verify,
        tags=[
            "e2e", "s5", "recursive-delegation", "tool-creation",
            "sub-manager", "all-session-fixes",
            "stress-fix-c", "stress-fix-d",
        ],
    )
    status = report.get("status", "unknown")
    print(f"\n{'=' * 60}")
    print(f"E2E Result: {status} (verify_ok={report.get('verify_ok')})")
    print(f"Workflow dir: {report.get('workflow_dir')}")
    print(f"Termination: {report.get('termination_reason')}")
    print(f"Verification: {report.get('verification')}")
    print(f"{'=' * 60}")
    sys.exit(0 if (status == "complete" and report.get("verify_ok")) else 1)
