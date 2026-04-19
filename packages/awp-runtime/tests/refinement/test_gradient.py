"""Unit tests for gradient extraction and prefix rendering."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from awp.refinement.gradient import (
    extract_gradient,
    render_refinement_prefix,
)


def test_extract_gradient_populates_all_sections(synthetic_run_dir: Path) -> None:
    gradient = extract_gradient(synthetic_run_dir)

    assert gradient.prior_run_id == "run_seed"
    assert len(gradient.defects) == 2
    assert gradient.defects[0].severity == "high"

    # Only last 3 gate rejections retained.
    assert len(gradient.rejected_gates) == 3
    assert gradient.rejected_gates[0].gate == "eval"  # most recent first 3 from events
    assert {g.gate for g in gradient.rejected_gates} == {
        "eval",
        "structural_integrity",
        "deliverable",
    }

    # Eval deltas include only metrics below their thresholds.
    assert "structural_completeness" in gradient.eval_deltas
    assert gradient.eval_deltas["structural_completeness"] == pytest.approx(0.25)
    assert "factual_accuracy" in gradient.eval_deltas
    assert gradient.eval_deltas["factual_accuracy"] == pytest.approx(0.10)
    assert "bilingual_coverage" in gradient.eval_deltas
    # No negative deltas.
    assert all(v > 0 for v in gradient.eval_deltas.values())


def test_extract_gradient_from_perfect_run_is_empty(perfect_run_dir: Path) -> None:
    gradient = extract_gradient(perfect_run_dir)
    assert gradient.defects == []
    assert gradient.rejected_gates == []
    assert gradient.eval_deltas == {}
    assert not gradient.is_non_empty()


def test_extract_gradient_tolerates_missing_sections(tmp_path: Path) -> None:
    run = tmp_path / "minimal"
    run.mkdir()
    (run / "FINAL").mkdir()
    (run / "run_completion.json").write_text(
        json.dumps({"run_id": "minimal", "status": "failed"}),
        encoding="utf-8",
    )
    (run / "events.jsonl").write_text("", encoding="utf-8")

    gradient = extract_gradient(run)  # must not raise
    assert gradient.defects == []
    assert gradient.rejected_gates == []
    assert gradient.eval_deltas == {}


def test_extract_gradient_raises_on_missing_run_completion(tmp_path: Path) -> None:
    run = tmp_path / "no_run_completion"
    run.mkdir()
    with pytest.raises(FileNotFoundError):
        extract_gradient(run)


def test_render_refinement_prefix_omits_empty_sections(
    perfect_run_dir: Path,
) -> None:
    gradient = extract_gradient(perfect_run_dir)
    prefix = render_refinement_prefix(gradient)
    assert "REFINEMENT CONTEXT" in prefix
    assert "Defects identified" not in prefix
    assert "Rejected gates" not in prefix
    assert "Metric gaps" not in prefix
    assert "Objective" in prefix


def test_render_refinement_prefix_includes_all_sections(
    synthetic_run_dir: Path,
) -> None:
    gradient = extract_gradient(synthetic_run_dir)
    prefix = render_refinement_prefix(gradient)
    assert "REFINEMENT CONTEXT" in prefix
    assert "Defects identified" in prefix
    assert "[high] Section 3 missing required citations" in prefix
    assert "Rejected gates" in prefix
    assert "Metric gaps to close" in prefix
    assert "Objective" in prefix
