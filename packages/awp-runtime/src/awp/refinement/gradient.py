"""Gradient extraction from a prior run's artifacts.

The gradient is the deterministic signal that drives refinement: a
structured summary of what the prior run got wrong, built from:

* critique defects (``run_completion.json.critique.defects``),
* the last 3 gate rejections (``events.jsonl`` where ``type`` ==
  ``"gate.reject"``),
* eval metric deltas — for every metric whose observed score is below
  its configured threshold, ``gap = threshold - observed``.

An empty gradient (no defects, no rejections, no gaps) aborts the
refinement loop early (R36).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class Defect(BaseModel):
    summary: str
    severity: str = "medium"
    evidence: str | None = None


class RejectedGate(BaseModel):
    gate: str
    reason: str
    ts: str | None = None


class RefinementGradient(BaseModel):
    prior_run_id: str
    prior_loss_total: float | None = None
    prior_raw_signals: dict[str, Any] = Field(default_factory=dict)
    defects: list[Defect] = Field(default_factory=list)
    rejected_gates: list[RejectedGate] = Field(default_factory=list)
    eval_deltas: dict[str, float] = Field(default_factory=dict)

    def is_non_empty(self) -> bool:
        return bool(self.defects or self.rejected_gates or self.eval_deltas)


def extract_gradient(prior_run_dir: Path) -> RefinementGradient:
    """Read the prior run and produce a structured gradient.

    Missing sections (no critique configured, no events, no eval) degrade
    gracefully to empty — they do not raise. Only a missing or malformed
    ``run_completion.json`` is a hard error.
    """
    rc_path = prior_run_dir / "run_completion.json"
    if not rc_path.exists():
        raise FileNotFoundError(f"run_completion.json not found in {prior_run_dir}")
    data = json.loads(rc_path.read_text(encoding="utf-8"))

    defects = [
        Defect(
            summary=str(d.get("summary", "")),
            severity=str(d.get("severity", "medium")),
            evidence=d.get("evidence"),
        )
        for d in (data.get("critique") or {}).get("defects", [])
        if d.get("summary")
    ]

    rejected_gates = _extract_last_rejections(prior_run_dir / "events.jsonl", limit=3)
    eval_deltas = _extract_eval_deltas(data.get("evaluation") or {})

    return RefinementGradient(
        prior_run_id=str(data.get("run_id") or prior_run_dir.name),
        prior_loss_total=_safe_float(data.get("loss_total")),
        prior_raw_signals=_collect_raw_signals(data),
        defects=defects,
        rejected_gates=rejected_gates,
        eval_deltas=eval_deltas,
    )


def _extract_last_rejections(events_path: Path, limit: int) -> list[RejectedGate]:
    if not events_path.exists():
        return []
    rejects: list[RejectedGate] = []
    for line in events_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if ev.get("type") == "gate.reject" and ev.get("gate"):
            rejects.append(
                RejectedGate(
                    gate=str(ev["gate"]),
                    reason=str(ev.get("reason", "")),
                    ts=ev.get("ts"),
                )
            )
    return rejects[-limit:]  # last N in chronological order (most recent last)


def _extract_eval_deltas(evaluation: dict[str, Any]) -> dict[str, float]:
    per_metric = evaluation.get("per_metric") or {}
    thresholds = evaluation.get("thresholds") or {}
    out: dict[str, float] = {}
    for name, observed in per_metric.items():
        try:
            o = float(observed)
        except (TypeError, ValueError):
            continue
        t = thresholds.get(name)
        try:
            t_f = float(t) if t is not None else None
        except (TypeError, ValueError):
            t_f = None
        if t_f is not None and o < t_f:
            out[name] = round(t_f - o, 4)
    return out


def _collect_raw_signals(data: dict[str, Any]) -> dict[str, Any]:
    signals: dict[str, Any] = {}
    ev = data.get("evaluation") or {}
    if "total_score" in ev:
        signals["eval_score"] = ev["total_score"]
    if "confidence" in data:
        signals["confidence"] = data["confidence"]
    crit = data.get("critique") or {}
    if "defects" in crit:
        signals["critique_defect_count"] = len(crit["defects"])
    return signals


def _safe_float(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def render_refinement_prefix(gradient: RefinementGradient) -> str:
    """Deterministic template. Empty sections are omitted from the output."""
    lines: list[str] = []
    lines.append("## REFINEMENT CONTEXT")
    lines.append("")
    lines.append("You are refining an existing deliverable for the task below.")
    lines.append("")
    lines.append("Prior deliverable is available at: input/")
    if gradient.prior_loss_total is not None:
        lines.append(f"Prior loss: {gradient.prior_loss_total:.3f}")
    if gradient.prior_raw_signals:
        for k, v in gradient.prior_raw_signals.items():
            lines.append(f"  - {k}: {v}")
    lines.append("")

    if gradient.defects:
        lines.append("Defects identified by prior critique:")
        for d in gradient.defects:
            lines.append(f"  - [{d.severity}] {d.summary}")
        lines.append("")

    if gradient.rejected_gates:
        lines.append("Rejected gates in prior run:")
        for g in gradient.rejected_gates:
            lines.append(f"  - {g.gate}: {g.reason}")
        lines.append("")

    if gradient.eval_deltas:
        lines.append("Metric gaps to close:")
        for metric, gap in gradient.eval_deltas.items():
            lines.append(f"  - {metric}: +{gap:.2f} needed")
        lines.append("")

    lines.append("Objective: produce an improved deliverable that reduces total loss.")
    lines.append("Preserve what works; fix what the gradient identifies above.")
    lines.append(
        "Do not rewrite from scratch — iterate on the prior deliverable in input/."
    )
    return "\n".join(lines)
