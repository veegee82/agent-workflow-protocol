"""Gradient extraction from a prior run's artifacts.

The gradient is the deterministic signal that drives refinement: a
structured summary of what the prior run got wrong, built from:

* critique defects — aggregated from ``iterations/*/critique.json``
  (each ``critiques[].defects[]`` entry), with a fallback to the
  synthetic ``run_completion.json.critique.defects`` shape used by
  unit-test fixtures;
* the last N gate rejections — from ``events.jsonl``, supporting both
  the real runtime schema (``{category: "gate", fields: {triggered:
  true, reason, gate}}``) and the synthetic schema (``{type:
  "gate.reject", gate, reason}``);
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

    Defects are sourced in priority order:

    1. ``iterations/<k>/critique.json`` — the real runtime's per-iteration
       critique artifacts, where each ``critiques[].defects[]`` entry is
       ``{category, location, description, severity}``.
    2. Fallback: ``run_completion.json.critique.defects`` — the synthetic
       schema used by unit-test fixtures, where each entry is
       ``{summary, severity}``.
    """
    rc_path = prior_run_dir / "run_completion.json"
    if not rc_path.exists():
        raise FileNotFoundError(f"run_completion.json not found in {prior_run_dir}")
    data = json.loads(rc_path.read_text(encoding="utf-8"))

    defects = _extract_defects_from_iterations(prior_run_dir / "iterations")
    if not defects:
        # Fallback: synthetic schema in run_completion.json.
        defects = [
            Defect(
                summary=str(d.get("summary") or d.get("description", "")),
                severity=str(d.get("severity", "medium")),
                evidence=d.get("evidence") or d.get("location"),
            )
            for d in (data.get("critique") or {}).get("defects", [])
            if d.get("summary") or d.get("description")
        ]

    rejected_gates = _extract_last_rejections(_resolve_events_path(prior_run_dir), limit=3)
    eval_deltas = _extract_eval_deltas(data.get("evaluation") or {})

    return RefinementGradient(
        prior_run_id=str(data.get("run_id") or prior_run_dir.name),
        prior_loss_total=_safe_float(data.get("loss_total")),
        prior_raw_signals=_collect_raw_signals(data, defect_count=len(defects)),
        defects=defects,
        rejected_gates=rejected_gates,
        eval_deltas=eval_deltas,
    )


def _extract_defects_from_iterations(iterations_dir: Path) -> list[Defect]:
    """Aggregate defects from ``iterations/<k>/critique.json``.

    The runtime writes one ``critique.json`` per iteration that contained
    critique work. Each file has ``critiques[]`` — one entry per worker
    critiqued — and each entry carries ``defects[]`` with schema
    ``{category, location, description, severity}``. We flatten all
    defects across all iterations and workers, preserving iteration order
    (most recent iteration last), de-duplicated by
    ``(description[:120], severity)``.
    """
    if not iterations_dir.exists():
        return []
    ordered_files = sorted(iterations_dir.glob("*/critique.json"))
    seen: set[tuple[str, str]] = set()
    defects: list[Defect] = []
    for path in ordered_files:
        try:
            content = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for critique in content.get("critiques") or []:
            for d in critique.get("defects") or []:
                desc = str(d.get("description") or d.get("summary") or "")
                if not desc:
                    continue
                severity = str(d.get("severity", "medium"))
                key = (desc[:120], severity)
                if key in seen:
                    continue
                seen.add(key)
                defects.append(
                    Defect(
                        summary=desc,
                        severity=severity,
                        evidence=d.get("location") or d.get("evidence"),
                    )
                )
    return defects


def _resolve_events_path(prior_run_dir: Path) -> Path:
    """Locate ``events.jsonl`` — it may live alongside ``run_completion.json``
    (synthetic fixtures) or in a sibling ``logs/<run_id>/`` directory
    (real runtime, where the typical layout is
    ``<workspace>/workspace/runs/<run_id>/`` for artifacts and
    ``<workspace>/logs/<run_id>/`` for the event log).
    """
    colocated = prior_run_dir / "events.jsonl"
    if colocated.exists():
        return colocated

    run_id = prior_run_dir.name
    # Walk up the parent chain looking for a ``logs/<run_id>/events.jsonl``
    # sibling. Stops at the filesystem root.
    current = prior_run_dir.parent
    while True:
        candidate = current / "logs" / run_id / "events.jsonl"
        if candidate.exists():
            return candidate
        if current == current.parent:
            break
        current = current.parent

    return colocated  # non-existent — caller handles missing file gracefully


def _extract_last_rejections(events_path: Path, limit: int) -> list[RejectedGate]:
    """Return up to ``limit`` rejected-gate events, most recent last.

    Supports two event schemas:

    1. Real runtime: ``{ts, level, category: "gate", msg, fields: {gate,
       reason, triggered: true}}``. A rejection is identified by
       ``category == "gate"`` and ``fields.triggered is True``.
    2. Synthetic (unit-test fixtures): ``{type: "gate.reject", gate,
       reason, ts}``.

    Both shapes are parsed; the resulting list is the last ``limit``
    rejections in on-disk order.
    """
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

        # Real runtime schema
        if ev.get("category") == "gate":
            fields = ev.get("fields") or {}
            if fields.get("triggered"):
                gate_name = str(fields.get("gate") or "unknown")
                reason = str(fields.get("reason") or ev.get("msg") or "")
                rejects.append(
                    RejectedGate(gate=gate_name, reason=reason, ts=ev.get("ts"))
                )
            continue

        # Synthetic schema
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


def _collect_raw_signals(
    data: dict[str, Any], *, defect_count: int | None = None
) -> dict[str, Any]:
    signals: dict[str, Any] = {}
    ev = data.get("evaluation") or {}
    if "total_score" in ev:
        signals["eval_score"] = ev["total_score"]
    if "confidence" in data:
        signals["confidence"] = data["confidence"]
    if defect_count is not None and defect_count > 0:
        signals["critique_defect_count"] = defect_count
    else:
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
    lines.append("Do not rewrite from scratch — iterate on the prior deliverable in input/.")
    return "\n".join(lines)
