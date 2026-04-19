#!/usr/bin/env python
"""E2E: Multilingual (DE+EN+FR) dataset analyzer — stress-fix-a coverage.

Generates a noisy dataset (~3000 rows with nulls, type mixing, malformed
timestamps) and asks the manager to:

  * Ingest the dataset defensively.
  * Compute summary statistics (mean, median, stddev, percentiles,
    per-category counts).
  * Produce three matplotlib PNGs (distribution histogram, correlation
    scatter, timeseries trend).
  * Write a trilingual DE+EN+FR markdown report and render it as PDF.
  * Exercise cross-run memory (prior stats summary is seeded under
    ``shared/memory/`` before the run starts).

Exercises Fixes A-H under real LLM variability, with a particular focus
on Fix A (``validate_python_source()`` + worker-prompt guardrails against
malformed code emitted by the LLM while parsing messy data).

Tags: e2e, s5, dataset-analysis, multilingual, all-session-fixes,
stress-fix-a
"""
from __future__ import annotations

import json
import random
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _harness import make_experiment_dir, run_e2e  # noqa: E402

TASK = """\
## Objective

Ingest the noisy dataset at ``_workspace_dir/inputs/dataset.json`` (about
3000 rows with deliberate noise: ~5% nulls, mixed str/number types in
``value_a``, and malformed timestamps in ~2% of rows). Produce a
production-grade, defensively engineered analysis.

## Cross-run memory (REQUIRED)

A prior stats summary has been seeded into the experiment's memory layer
at ``shared/memory/prior_stats_summary.json``. Consult it before
re-computing (to compare distribution drift) and reference its headline
numbers in the final report.

## Required deliverables (ALL MUST exist on disk, non-empty)

1. ``_output_dir/data/summary_stats.json`` — JSON with keys for all
   numeric columns (``value_a``, ``value_b``) each containing
   ``{mean, median, stddev, p25, p50, p75, p95, count, nulls}``, plus a
   top-level ``per_category_counts`` mapping.
2. ``_output_dir/figs/distribution.png`` — distribution histogram
   (matplotlib). Non-empty, >1KB.
3. ``_output_dir/figs/correlation.png`` — correlation scatter of
   ``value_a`` vs ``value_b``. Non-empty, >1KB.
4. ``_output_dir/figs/timeseries.png`` — timeseries trend plot over
   ``timestamp``. Non-empty, >1KB.
5. ``_output_dir/report.md`` — trilingual DE+EN+FR report with clear
   ``## Zusammenfassung`` (DE), ``## Summary`` (EN), and ``## Résumé``
   (FR) headings. At least 4000 characters total. Must reference each
   figure by path.
6. ``_output_dir/report.pdf`` — rendered PDF of the report. >10KB.

## Constraints

- Defensive parsing: null-safe, type-coerce ``value_a`` (try int → float
  → drop), skip rows with malformed timestamps but log them.
- No placeholders (``TODO``, ``???``, ``XX%``) in the final report.
- Figures must be generated programmatically (matplotlib preferred) from
  the real cleaned data — no stub/dummy images.
- Keep within the budget — no exhaustive literature or schema search.
"""


def _generate_dataset(dst: Path, n_rows: int = 3000, seed: int = 1337) -> None:
    """Produce a noisy dataset with the spec-mandated defects."""
    rng = random.Random(seed)
    categories = ["alpha", "beta", "gamma", "delta", "epsilon"]
    t0 = datetime(2025, 1, 1, 0, 0, 0)
    rows: list[dict] = []
    for i in range(n_rows):
        ts = (t0 + timedelta(minutes=i * 7)).isoformat()
        if rng.random() < 0.02:
            # ~2% malformed timestamps
            ts = rng.choice([
                "not-a-date", "2025-13-40T99:99:99", "", "1970-00-00",
            ])
        value_a: object = rng.gauss(50.0, 12.0)
        if rng.random() < 0.12:
            # mixed str/number types in value_a
            value_a = f"{value_a:.3f}"
        elif rng.random() < 0.03:
            value_a = "N/A"
        value_b: object = rng.gauss(100.0, 25.0) + (
            float(value_a) * 0.4 if isinstance(value_a, (int, float)) else 0.0
        )
        label = rng.choice(["low", "medium", "high"])
        # Inject ~5% nulls across fields
        if rng.random() < 0.05:
            value_a = None
        if rng.random() < 0.05:
            value_b = None
        if rng.random() < 0.05:
            label = None
        rows.append({
            "id": i,
            "timestamp": ts,
            "category": rng.choice(categories),
            "value_a": value_a,
            "value_b": value_b,
            "label": label,
        })
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(json.dumps(rows, indent=1), encoding="utf-8")


def _seed_prior_memory(workflow_dir: Path) -> None:
    """Seed a fake prior-run stats summary into shared/memory/."""
    memory_dir = workflow_dir / "shared" / "memory"
    memory_dir.mkdir(parents=True, exist_ok=True)
    prior = {
        "source": "prior_run_2025Q4",
        "note": (
            "Headline statistics from the previous quarterly run. Use as a "
            "drift baseline in the new report."
        ),
        "value_a": {
            "mean": 49.8, "median": 49.6, "stddev": 11.9,
            "p25": 41.7, "p75": 57.9, "count": 2847, "nulls": 153,
        },
        "value_b": {
            "mean": 120.4, "median": 119.2, "stddev": 26.1,
            "p25": 102.5, "p75": 138.0, "count": 2851, "nulls": 149,
        },
        "per_category_counts": {
            "alpha": 605, "beta": 598, "gamma": 611, "delta": 592,
            "epsilon": 594,
        },
    }
    (memory_dir / "prior_stats_summary.json").write_text(
        json.dumps(prior, indent=2), encoding="utf-8"
    )


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

    report_md = _find("report.md", 4000)
    report_pdf = _find("report.pdf", 10_000)
    fig_dist = _find("distribution.png", 1000)
    fig_corr = _find("correlation.png", 1000)
    fig_ts = _find("timeseries.png", 1000)
    stats_json = _find("summary_stats.json", 10)

    # Trilingual header check: DE + EN + FR distinct H2 headings.
    md_has_trilingual = False
    md_has_placeholder = False
    if report_md:
        text = report_md.read_text(encoding="utf-8", errors="replace")
        de = bool(re.search(r"(?im)^#+\s+.*Zusammenfassung", text))
        en = bool(re.search(r"(?im)^#+\s+.*Summary", text))
        fr = bool(re.search(r"(?im)^#+\s+.*R[eé]sum[eé]", text))
        md_has_trilingual = de and en and fr
        md_has_placeholder = bool(
            re.search(r"TODO|XX%|\?\?\?|<placeholder", text, re.I)
        )

    stats_ok = False
    stats_payload: dict = {}
    if stats_json:
        try:
            stats_payload = json.loads(
                stats_json.read_text(encoding="utf-8", errors="replace")
            )
            stats_ok = (
                isinstance(stats_payload, dict)
                and "value_a" in stats_payload
                and "value_b" in stats_payload
            )
        except json.JSONDecodeError:
            stats_ok = False

    # Cross-run memory evidence.
    memory_evidence = False
    for p in root.rglob("*.json"):
        s = str(p)
        if "prior_stats_summary" in s or "shared/memory" in s:
            memory_evidence = True
            break
    if not memory_evidence:
        for p in root.rglob("tool_calls.json"):
            try:
                t = p.read_text(encoding="utf-8", errors="replace")
                if "memory." in t or "prior_stats_summary" in t:
                    memory_evidence = True
                    break
            except OSError:
                continue

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
            "validate_python_source",
            "max_workers_per_iteration",
        ):
            if key in t and key not in gates_fired:
                gates_fired.append(key)

    checks = {
        "report_md": str(report_md) if report_md else None,
        "report_pdf": str(report_pdf) if report_pdf else None,
        "fig_distribution": str(fig_dist) if fig_dist else None,
        "fig_correlation": str(fig_corr) if fig_corr else None,
        "fig_timeseries": str(fig_ts) if fig_ts else None,
        "summary_stats_json": str(stats_json) if stats_json else None,
        "md_has_trilingual": md_has_trilingual,
        "md_has_placeholder": md_has_placeholder,
        "stats_ok": stats_ok,
        "memory_evidence": memory_evidence,
        "gates_fired": gates_fired,
    }
    ok = bool(
        report_md and report_pdf and fig_dist and fig_corr and fig_ts
        and stats_json and stats_ok
        and md_has_trilingual and not md_has_placeholder
    )
    return {"ok": ok, **checks}


if __name__ == "__main__":
    workflow_dir = make_experiment_dir("multilingual-dataset-analyzer")

    # Generate dataset + seed prior memory.
    dataset_path = workflow_dir / "shared" / "inputs" / "dataset.json"
    _generate_dataset(dataset_path)
    _seed_prior_memory(workflow_dir)

    inputs = {
        "dataset": str(dataset_path),
    }

    report = run_e2e(
        slug="multilingual-dataset-analyzer",
        title="Multilingual (DE+EN+FR) Dataset Analyzer — stress-fix-a",
        task=TASK,
        inputs=inputs,
        model="openai/gpt-5-mini",
        worker_model="deepseek/deepseek-chat-v3.1",
        max_loops=25,
        max_total_tokens=4_000_000,
        max_wall_time=5400,
        max_total_workers=50,
        max_depth=2,
        max_tool_calls=3000,
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
            "trace_enabled": True,
        },
        verifier=verify,
        tags=[
            "e2e", "s5", "dataset-analysis", "multilingual",
            "all-session-fixes", "stress-fix-a",
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
