"""Shared fixtures for refinement tests — synthetic prior-run artifacts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest


@pytest.fixture
def synthetic_run_dir(tmp_path: Path) -> Path:
    """A prior-run directory with populated critique, gates, and eval signals."""
    run = tmp_path / "run_seed"
    (run / "FINAL").mkdir(parents=True)
    (run / "FINAL" / "paper.md").write_text(
        "# Draft paper (missing section 3)\n", encoding="utf-8"
    )

    (run / "run_completion.json").write_text(
        json.dumps(
            {
                "run_id": "run_seed",
                "status": "partial",
                "confidence": 0.55,
                "task": "write a bilingual paper",
                "critique": {
                    "defects": [
                        {
                            "summary": "Section 3 missing required citations",
                            "severity": "high",
                        },
                        {
                            "summary": "German abstract is shorter than required",
                            "severity": "medium",
                        },
                    ]
                },
                "evaluation": {
                    "per_metric": {
                        "structural_completeness": 0.60,
                        "factual_accuracy": 0.80,
                        "bilingual_coverage": 0.50,
                    },
                    "thresholds": {
                        "structural_completeness": 0.85,
                        "factual_accuracy": 0.90,
                        "bilingual_coverage": 0.75,
                    },
                    "total_score": 0.63,
                },
            }
        ),
        encoding="utf-8",
    )

    events = [
        {
            "type": "gate.reject",
            "gate": "deliverable_presence",
            "reason": "section_3_incomplete",
            "ts": "2026-04-19T10:00:00Z",
        },
        {
            "type": "gate.reject",
            "gate": "eval",
            "reason": "bilingual_coverage_below_threshold",
            "ts": "2026-04-19T10:02:00Z",
        },
        {"type": "worker.spawn", "ts": "2026-04-19T10:03:00Z"},
        {
            "type": "gate.reject",
            "gate": "structural_integrity",
            "reason": "abstract_too_short",
            "ts": "2026-04-19T10:05:00Z",
        },
        {
            "type": "gate.reject",
            "gate": "deliverable",
            "reason": "missing_references",
            "ts": "2026-04-19T10:07:00Z",
        },
    ]
    (run / "events.jsonl").write_text(
        "\n".join(json.dumps(e) for e in events) + "\n",
        encoding="utf-8",
    )
    return run


@pytest.fixture
def perfect_run_dir(tmp_path: Path) -> Path:
    """A prior run with no defects, no rejections, all eval metrics above threshold."""
    run = tmp_path / "run_perfect"
    (run / "FINAL").mkdir(parents=True)
    (run / "FINAL" / "paper.md").write_text("# Perfect\n", encoding="utf-8")

    (run / "run_completion.json").write_text(
        json.dumps(
            {
                "run_id": "run_perfect",
                "status": "complete",
                "confidence": 0.95,
                "task": "trivial",
                "critique": {"defects": []},
                "evaluation": {
                    "per_metric": {"quality": 0.95},
                    "thresholds": {"quality": 0.80},
                    "total_score": 0.95,
                },
            }
        ),
        encoding="utf-8",
    )
    (run / "events.jsonl").write_text("", encoding="utf-8")
    return run
