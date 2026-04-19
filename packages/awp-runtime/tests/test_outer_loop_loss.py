"""Unit tests for the outer-loop loss function (Phase A2).

Each test feeds a hand-crafted ``run_completion.json`` (and optionally a
``metrics.jsonl``) into a tmp directory and asserts the resulting
:class:`LossBreakdown` matches a hand-computed value within 1e-9.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest
from awp.outer_loop.loss import LossWeights, compute_run_loss


def _write_run_completion(run_dir: Path, payload: dict) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "run_completion.json").write_text(json.dumps(payload), encoding="utf-8")


def _write_metrics(run_dir: Path, entries: list[dict]) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "metrics.jsonl").write_text(
        "\n".join(json.dumps(e) for e in entries) + "\n",
        encoding="utf-8",
    )


def test_hand_computed_loss_matches_default_weights(tmp_path: Path) -> None:
    """eval=0.8, critique=0.6, 1 rejection (max=2), budget=40%, partial."""
    _write_run_completion(
        tmp_path,
        {
            "status": "partial",
            "eval": {"score": 0.8},
            "critique": {"score": 0.6},
            "config_used": {"max_rejected_completions": 2},
            "final_budget": {"budget_remaining_pct": 40.0},
        },
    )
    _write_metrics(
        tmp_path,
        [
            {"kind": "metric.gate", "verdict": "rejected"},
            {"kind": "metric.gate", "verdict": "passed"},
        ],
    )

    breakdown = compute_run_loss(tmp_path)
    # Hand computation:
    #   eval_loss = 1 - 0.8 = 0.2 → 0.4 * 0.2 = 0.08
    #   crit_loss = 1 - 0.6 = 0.4 → 0.3 * 0.4 = 0.12
    #   gate_loss = min(1, 1/2) = 0.5 → 0.15 * 0.5 = 0.075
    #   budget_loss = 1 - 0.4 = 0.6 → 0.05 * 0.6 = 0.03
    #   status_loss = 0.5 → 0.1 * 0.5 = 0.05
    expected_total = 0.08 + 0.12 + 0.075 + 0.03 + 0.05
    assert math.isclose(breakdown.total, expected_total, abs_tol=1e-9)
    assert math.isclose(breakdown.eval_component, 0.08, abs_tol=1e-9)
    assert math.isclose(breakdown.critique_component, 0.12, abs_tol=1e-9)
    assert math.isclose(breakdown.gate_component, 0.075, abs_tol=1e-9)
    assert math.isclose(breakdown.budget_component, 0.03, abs_tol=1e-9)
    assert math.isclose(breakdown.status_component, 0.05, abs_tol=1e-9)


def test_weight_overrides_are_respected(tmp_path: Path) -> None:
    _write_run_completion(
        tmp_path,
        {
            "status": "complete",
            "eval": {"score": 0.5},
            "critique": {"score": 0.5},
            "final_budget": {"budget_remaining_pct": 100.0},
        },
    )
    weights = LossWeights(eval=1.0, critique=0.0, gate_rejections=0.0, budget=0.0, status=0.0)
    breakdown = compute_run_loss(tmp_path, weights=weights)
    # eval_loss = 0.5 → 1.0 * 0.5 = 0.5; everything else is masked out.
    assert math.isclose(breakdown.total, 0.5, abs_tol=1e-9)
    assert math.isclose(breakdown.eval_component, 0.5, abs_tol=1e-9)
    assert breakdown.critique_component == 0.0
    assert breakdown.gate_component == 0.0


@pytest.mark.parametrize(
    ("status", "expected_status_penalty"),
    [
        ("complete", 0.0),
        ("partial", 0.5),
        ("failed", 1.0),
        ("aborted", 1.0),
    ],
)
def test_all_status_values_produce_canonical_penalty(
    tmp_path: Path, status: str, expected_status_penalty: float
) -> None:
    _write_run_completion(
        tmp_path,
        {
            "status": status,
            "eval": {"score": 1.0},
            "critique": {"score": 1.0},
            "final_budget": {"budget_remaining_pct": 100.0},
        },
    )
    breakdown = compute_run_loss(tmp_path)
    expected_status_component = 0.1 * expected_status_penalty
    assert math.isclose(breakdown.status_component, expected_status_component, abs_tol=1e-9)
    assert breakdown.raw_signals["status_penalty"] == expected_status_penalty


def test_unknown_status_is_neutral_05(tmp_path: Path) -> None:
    _write_run_completion(
        tmp_path,
        {
            "status": "weird_unknown_value",
            "eval": {"score": 1.0},
            "critique": {"score": 1.0},
            "final_budget": {"budget_remaining_pct": 100.0},
        },
    )
    breakdown = compute_run_loss(tmp_path)
    # Unknown → 0.5 penalty → 0.1 * 0.5 = 0.05.
    assert math.isclose(breakdown.status_component, 0.05, abs_tol=1e-9)


def test_missing_metrics_uses_neutral_for_eval_and_critique(tmp_path: Path) -> None:
    """No metrics.jsonl AND no eval/critique fields → 0.5 fallback for both."""
    _write_run_completion(
        tmp_path,
        {
            "status": "complete",
            "final_budget": {"budget_remaining_pct": 100.0},
        },
    )
    # Note: NO metrics.jsonl is written.
    breakdown = compute_run_loss(tmp_path)
    # eval_loss = 1 - 0.5 = 0.5 → 0.4 * 0.5 = 0.2
    # crit_loss = 1 - 0.5 = 0.5 → 0.3 * 0.5 = 0.15
    # gate_loss = 0 (no metrics)
    # budget_loss = 0 (full budget)
    # status_loss = 0 (complete)
    expected = 0.2 + 0.15 + 0.0 + 0.0 + 0.0
    assert math.isclose(breakdown.total, expected, abs_tol=1e-9)
    assert breakdown.raw_signals["eval_source"] == "neutral_default"
    assert breakdown.raw_signals["critique_source"] == "neutral_default"


def test_eval_falls_back_to_metrics_mean(tmp_path: Path) -> None:
    """If run_completion lacks eval.score, the metrics mean is used."""
    _write_run_completion(
        tmp_path,
        {
            "status": "complete",
            "final_budget": {"budget_remaining_pct": 100.0},
        },
    )
    _write_metrics(
        tmp_path,
        [
            {"kind": "metric.eval", "score": 0.4},
            {"kind": "metric.eval", "score": 0.8},
            {"kind": "metric.gate", "verdict": "passed"},
        ],
    )
    breakdown = compute_run_loss(tmp_path)
    assert math.isclose(breakdown.raw_signals["eval_score"], 0.6, abs_tol=1e-9)


def test_max_rejections_uses_config_used(tmp_path: Path) -> None:
    _write_run_completion(
        tmp_path,
        {
            "status": "complete",
            "eval": {"score": 1.0},
            "critique": {"score": 1.0},
            "config_used": {"max_rejected_completions": 5},
            "final_budget": {"budget_remaining_pct": 100.0},
        },
    )
    _write_metrics(
        tmp_path,
        [
            {"kind": "metric.gate", "verdict": "rejected"},
            {"kind": "metric.gate", "verdict": "rejected"},
        ],
    )
    breakdown = compute_run_loss(tmp_path)
    # 2 rejections / 5 cap = 0.4 → 0.15 * 0.4 = 0.06
    assert math.isclose(breakdown.gate_component, 0.06, abs_tol=1e-9)


def test_completely_missing_run_completion_yields_neutral_loss(tmp_path: Path) -> None:
    """No artifacts at all — loss must still be defined and finite."""
    breakdown = compute_run_loss(tmp_path)
    # eval=0.5, crit=0.5, gates=0, budget=0 (full), status=0.5 (missing rc).
    expected = 0.4 * 0.5 + 0.3 * 0.5 + 0.0 + 0.0 + 0.1 * 0.5
    assert math.isclose(breakdown.total, expected, abs_tol=1e-9)
    assert 0.0 <= breakdown.total <= 1.0


def test_loss_is_clamped_to_unit_interval(tmp_path: Path) -> None:
    """Pathological signals (eval > 1, budget > 100, etc.) must not blow up."""
    _write_run_completion(
        tmp_path,
        {
            "status": "complete",
            "eval": {"score": 2.0},
            "critique": {"score": -0.5},
            "final_budget": {"budget_remaining_pct": 200.0},
        },
    )
    breakdown = compute_run_loss(tmp_path)
    assert 0.0 <= breakdown.eval_component <= 0.4
    assert 0.0 <= breakdown.critique_component <= 0.3
    assert 0.0 <= breakdown.budget_component <= 0.05
    assert 0.0 <= breakdown.total <= 1.0
