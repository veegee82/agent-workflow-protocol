"""Deterministic scalar-loss function for completed AWP runs (Phase A2).

The outer loop treats a single AWP run as one training example: artifacts
are the parameters, the run is the forward pass, and this module computes
the loss that a future optimizer (Phase A3) will backpropagate through.

The loss is a weighted sum of five components, each in [0, 1]:

* ``1 - eval_score`` — quality from the evaluation layer.
* ``1 - critique_score`` — defect signal from the critique loop.
* ``min(1, gate_rejection_count / max_rejections)`` — completion-gate friction.
* ``max(0, 1 - budget_remaining_pct)`` — budget burn.
* ``status_penalty`` — terminal-state penalty (complete=0, partial=0.5, failed/aborted=1.0).

All inputs come from artifacts that the runner already writes:
``run_completion.json`` and ``metrics.jsonl``. Missing signals fall back
to the neutral 0.5 so a run without an evaluation layer still produces a
finite, well-defined loss.

This module is pure I/O + arithmetic — no LLM calls, no network, no random.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Default fallback values when a signal is absent from the run artifacts.
_NEUTRAL_SCORE = 0.5
# Default for ``max_rejected_completions`` when run_completion.json does not
# carry the runtime config — mirrors the runner's circuit-breaker default.
_DEFAULT_MAX_REJECTIONS = 2

_REJECTED_VERDICTS = frozenset({"reject", "rejected", "fail", "failed"})

_STATUS_PENALTY: dict[str, float] = {
    "complete": 0.0,
    "partial": 0.5,
    "failed": 1.0,
    "aborted": 1.0,
}


@dataclass
class LossWeights:
    """Per-component weights for :func:`compute_run_loss`.

    Defaults sum to 1.0, so the total loss is in [0, 1] for the default
    configuration. Custom weights are accepted and *not* renormalised.
    """

    eval: float = 0.4
    critique: float = 0.3
    gate_rejections: float = 0.15
    budget: float = 0.05
    status: float = 0.1


@dataclass
class LossBreakdown:
    """Per-component breakdown returned by :func:`compute_run_loss`.

    ``raw_signals`` carries the underlying numbers (eval_score,
    critique_score, etc.) so callers can persist them for inspection
    without re-parsing the run directory.
    """

    total: float
    eval_component: float
    critique_component: float
    gate_component: float
    budget_component: float
    status_component: float
    raw_signals: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Helpers — file I/O
# ---------------------------------------------------------------------------


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    # Skip malformed lines silently — the loss must always be
                    # computable from a partial artifact set.
                    continue
    except OSError:
        return out
    return out


# ---------------------------------------------------------------------------
# Helpers — signal extraction
# ---------------------------------------------------------------------------


def _coerce_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _extract_eval_score(
    run_completion: dict[str, Any] | None, metrics: list[dict[str, Any]]
) -> tuple[float, str]:
    """Return ``(score, source)`` where source is for diagnostics only."""
    if run_completion is not None:
        ev = run_completion.get("eval")
        if isinstance(ev, dict):
            score = _coerce_float(ev.get("score"))
            if score is not None:
                return max(0.0, min(1.0, score)), "run_completion.eval.score"
    eval_metrics = [
        _coerce_float(m.get("score")) for m in metrics if m.get("kind") == "metric.eval"
    ]
    eval_metrics = [s for s in eval_metrics if s is not None]
    if eval_metrics:
        mean = sum(eval_metrics) / len(eval_metrics)
        return max(0.0, min(1.0, mean)), "metrics.metric.eval.mean"
    return _NEUTRAL_SCORE, "neutral_default"


def _extract_critique_score(
    run_completion: dict[str, Any] | None, metrics: list[dict[str, Any]]
) -> tuple[float, str]:
    if run_completion is not None:
        c = run_completion.get("critique")
        if isinstance(c, dict):
            score = _coerce_float(c.get("score"))
            if score is not None:
                return max(0.0, min(1.0, score)), "run_completion.critique.score"
        # Some pipelines flatten critique_score onto the top level.
        flat = _coerce_float(run_completion.get("critique_score"))
        if flat is not None:
            return max(0.0, min(1.0, flat)), "run_completion.critique_score"
    crit_metrics = [
        _coerce_float(m.get("score")) for m in metrics if m.get("kind") == "metric.critique"
    ]
    crit_metrics = [s for s in crit_metrics if s is not None]
    if crit_metrics:
        mean = sum(crit_metrics) / len(crit_metrics)
        return max(0.0, min(1.0, mean)), "metrics.metric.critique.mean"
    return _NEUTRAL_SCORE, "neutral_default"


def _count_gate_rejections(metrics: list[dict[str, Any]]) -> int:
    n = 0
    for m in metrics:
        if m.get("kind") != "metric.gate":
            continue
        verdict = str(m.get("verdict", "")).lower()
        if verdict in _REJECTED_VERDICTS:
            n += 1
    return n


def _extract_max_rejections(run_completion: dict[str, Any] | None) -> int:
    if run_completion is None:
        return _DEFAULT_MAX_REJECTIONS
    cfg = run_completion.get("config_used")
    if isinstance(cfg, dict):
        v = cfg.get("max_rejected_completions")
        try:
            iv = int(v) if v is not None else _DEFAULT_MAX_REJECTIONS
        except (TypeError, ValueError):
            iv = _DEFAULT_MAX_REJECTIONS
        return iv if iv > 0 else _DEFAULT_MAX_REJECTIONS
    return _DEFAULT_MAX_REJECTIONS


def _extract_budget_remaining(run_completion: dict[str, Any] | None) -> float:
    """Return budget_remaining in [0, 1] (1.0 = full budget left)."""
    if run_completion is None:
        return 1.0
    fb = run_completion.get("final_budget")
    if not isinstance(fb, dict):
        return 1.0
    pct = _coerce_float(fb.get("budget_remaining_pct"))
    if pct is None:
        return 1.0
    # The runner stores this as 0..100; clamp + scale to 0..1.
    pct = max(0.0, min(100.0, pct))
    return pct / 100.0


def _extract_status_penalty(run_completion: dict[str, Any] | None) -> tuple[float, str]:
    if run_completion is None:
        return _NEUTRAL_SCORE, "missing_run_completion"
    status = str(run_completion.get("status", "")).lower()
    if status in _STATUS_PENALTY:
        return _STATUS_PENALTY[status], status
    return _NEUTRAL_SCORE, status or "unknown"


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def compute_run_loss(run_dir: Path, weights: LossWeights | None = None) -> LossBreakdown:
    """Compute the scalar loss for one completed run.

    Parameters
    ----------
    run_dir
        Directory holding ``run_completion.json`` and (optionally)
        ``metrics.jsonl``. Both files may be missing — the loss is
        well-defined under partial information.
    weights
        Optional :class:`LossWeights` override. Defaults to
        ``LossWeights()`` (sums to 1.0).

    Returns
    -------
    :class:`LossBreakdown` with the total and per-component losses, plus
    the raw underlying signals for inspection.
    """
    weights = weights or LossWeights()

    run_completion = _load_json(run_dir / "run_completion.json")
    metrics = _load_jsonl(run_dir / "metrics.jsonl")

    eval_score, eval_source = _extract_eval_score(run_completion, metrics)
    critique_score, critique_source = _extract_critique_score(run_completion, metrics)
    gate_rejections = _count_gate_rejections(metrics)
    max_rejections = _extract_max_rejections(run_completion)
    budget_remaining = _extract_budget_remaining(run_completion)
    status_penalty, status = _extract_status_penalty(run_completion)

    # Per-component losses, each clamped to [0, 1].
    eval_loss = max(0.0, min(1.0, 1.0 - eval_score))
    critique_loss = max(0.0, min(1.0, 1.0 - critique_score))
    gate_loss = min(1.0, gate_rejections / max(1, max_rejections))
    budget_loss = max(0.0, 1.0 - budget_remaining)
    status_loss = max(0.0, min(1.0, status_penalty))

    eval_component = weights.eval * eval_loss
    critique_component = weights.critique * critique_loss
    gate_component = weights.gate_rejections * gate_loss
    budget_component = weights.budget * budget_loss
    status_component = weights.status * status_loss

    total = (
        eval_component + critique_component + gate_component + budget_component + status_component
    )

    return LossBreakdown(
        total=total,
        eval_component=eval_component,
        critique_component=critique_component,
        gate_component=gate_component,
        budget_component=budget_component,
        status_component=status_component,
        raw_signals={
            "eval_score": eval_score,
            "eval_source": eval_source,
            "critique_score": critique_score,
            "critique_source": critique_source,
            "gate_rejection_count": gate_rejections,
            "max_rejections": max_rejections,
            "budget_remaining_pct": round(budget_remaining * 100.0, 4),
            "status": status,
            "status_penalty": status_penalty,
            "weights": {
                "eval": weights.eval,
                "critique": weights.critique,
                "gate_rejections": weights.gate_rejections,
                "budget": weights.budget,
                "status": weights.status,
            },
        },
    )


__all__ = [
    "LossBreakdown",
    "LossWeights",
    "compute_run_loss",
]
