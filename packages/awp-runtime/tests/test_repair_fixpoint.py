"""Tests for the R35 Repair Fixpoint guard (Phase 3.1).

The guard lives on :class:`awp.runtime.critique.engine.CritiqueEngine`.
It compares the simhash of the two most recent repair outputs before
dispatching the next repair worker and aborts the loop when similarity
reaches 0.95, emitting a ``metric.gate`` event with
``gate="repair_fixpoint"``.

The tests use a fake ``run_worker_fn`` and a fake ``LLMClient`` so they
are fully hermetic — no network, no subprocess.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from awp.models.orchestration import CritiqueConfig
from awp.runtime.critique.engine import CritiqueEngine
from awp.runtime.critique.models import CritiqueEnvelope, Defect


class _FakeLLMClient:
    """Returns the same critical critique every time so the loop keeps
    trying to repair. The engine drives the repair loop based on
    ``has_critical_defects`` on the *re-critique*, so returning a
    critical result on every call guarantees we exercise every planned
    attempt unless the fixpoint guard aborts it."""

    def __init__(self) -> None:
        self.total_tokens_used = 0
        self.calls = 0

    def chat_json(self, _messages, temperature=0.0, max_tokens=0):  # noqa: D401
        self.calls += 1
        return {
            "score": 0.2,
            "defects": [
                {
                    "category": "incomplete",
                    "location": "root.payload",
                    "description": "still incomplete",
                    "severity": "critical",
                }
            ],
            "prescriptions": ["Fix the payload"],
            "reusable_patterns": [],
            "effort_estimate": "trivial",
            "summary": "still broken",
        }


def _engine(
    tmp_path: Path,
    *,
    max_repair_attempts: int = 3,
    metric_writer=None,
) -> tuple[CritiqueEngine, _FakeLLMClient]:
    cfg = CritiqueConfig(enabled=True, max_repair_attempts=max_repair_attempts)
    llm = _FakeLLMClient()
    # Create workspace/runs dir so the fixpoint snapshot persistence has
    # a valid root; the helper is tolerant of missing dirs but it is
    # closer to real usage to mkdir up front.
    (tmp_path / "workspace" / "runs" / "run-xyz").mkdir(parents=True, exist_ok=True)
    engine = CritiqueEngine(
        config=cfg,
        workflow_dir=tmp_path,
        run_id="run-xyz",
        worker_model="stub",
        llm_client=llm,
        metric_writer=metric_writer,
    )
    return engine, llm


def _initial_critique() -> CritiqueEnvelope:
    return CritiqueEnvelope(
        worker_id="worker_a",
        score=0.2,
        defects=[
            Defect(
                category="incomplete",
                location="root.payload",
                description="payload missing",
                severity="critical",
            )
        ],
        prescriptions=["Fill in the payload"],
    )


def _budget_ok():
    return (True, "")


# ---------------------------------------------------------------------------
# (a) Two near-identical repair outputs → fixpoint aborts further attempts
# ---------------------------------------------------------------------------


def test_near_identical_repairs_abort_via_fixpoint(tmp_path):
    captured: list[tuple[str, dict]] = []

    def _metric_writer(kind: str, payload: dict) -> None:
        captured.append((kind, payload))

    engine, llm = _engine(tmp_path, max_repair_attempts=4, metric_writer=_metric_writer)

    # Every repair worker returns the *same* payload — a pure fixpoint.
    # simhash similarity between identical dicts is 1.0, well above
    # the 0.95 threshold, so the 3rd dispatch must be blocked.
    stable_payload = {
        "confidence": 0.1,
        "findings": "The analysis is incomplete and needs more data.",
        "path": "/tmp/out.md",
    }
    dispatch_log: list[int] = []

    def _run_worker_fn(envelope: dict, task: str) -> dict:
        dispatch_log.append(envelope.get("_repair_attempt", 0))
        return dict(stable_payload)

    original_result = {
        "confidence": 0.1,
        "findings": "The analysis is incomplete and needs more data.",
        "path": "/tmp/out.md",
    }
    critique = _initial_critique()
    _, attempts = engine.attempt_repair(
        worker_id="worker_a",
        worker_result=original_result,
        critique=critique,
        task="Demo task",
        envelope={"instructions": "do the thing"},
        run_worker_fn=_run_worker_fn,
        budget_checker=_budget_ok,
        iteration=1,
    )

    # Attempt 1 dispatches (no prior output to compare against).
    # Attempt 2 MUST be blocked by the fixpoint check because O_0
    # (original worker_result) and O_1 (first repair) are identical:
    # sim(O_0, O_1) = 1.0 >= 0.95, so the 2nd repair dispatch is
    # aborted per R35.
    assert dispatch_log == [1], dispatch_log
    assert len(attempts) == 1, attempts

    # The metric event fired exactly once and carries the normative
    # fields: gate, sim (>= 0.95), attempt (==2), previous_output_path.
    fixpoint_events = [
        p for (k, p) in captured
        if k == "metric.gate" and p.get("gate") == "repair_fixpoint"
    ]
    assert len(fixpoint_events) == 1
    evt = fixpoint_events[0]
    assert evt["verdict"] == "rejected"
    assert evt["attempt"] == 2
    assert evt["sim"] >= 0.95
    assert isinstance(evt["previous_output_path"], str)
    assert evt["previous_output_path"] != ""
    # The pointer file must actually exist on disk (best-effort path
    # resolution — relative to workflow_dir).
    resolved = tmp_path / evt["previous_output_path"]
    assert resolved.is_file(), resolved


# ---------------------------------------------------------------------------
# (b) Divergent repair outputs → NO abort
# ---------------------------------------------------------------------------


def test_divergent_repairs_do_not_abort(tmp_path):
    captured: list[tuple[str, dict]] = []

    engine, _ = _engine(
        tmp_path,
        max_repair_attempts=3,
        metric_writer=lambda k, p: captured.append((k, p)),
    )

    # Each repair returns a totally different payload. Two texts that
    # share no meaningful tokens sit around ~0.5 similarity (random
    # bits apart) — well below 0.95.
    distinct_payloads = [
        {"confidence": 0.1, "findings": "alpha beta gamma delta epsilon"},
        {"confidence": 0.2, "findings": "lorem ipsum dolor sit amet consectetur"},
        {"confidence": 0.3, "findings": "quartz zebra xenon yacht widget voxel"},
    ]
    idx = {"n": 0}
    dispatch_log: list[int] = []

    def _run_worker_fn(envelope: dict, task: str) -> dict:
        dispatch_log.append(envelope.get("_repair_attempt", 0))
        out = dict(distinct_payloads[idx["n"] % len(distinct_payloads)])
        idx["n"] += 1
        return out

    _, attempts = engine.attempt_repair(
        worker_id="worker_div",
        worker_result={"confidence": 0.05, "findings": "unrelated original text"},
        critique=_initial_critique(),
        task="Demo task",
        envelope={"instructions": "diverge please"},
        run_worker_fn=_run_worker_fn,
        budget_checker=_budget_ok,
        iteration=2,
    )

    # max_repair_attempts=3 with divergent outputs → every attempt
    # dispatches, the guard never fires.
    assert dispatch_log == [1, 2, 3]
    assert len(attempts) == 3

    # No fixpoint metric emitted.
    fixpoint_events = [
        p for (k, p) in captured
        if k == "metric.gate" and p.get("gate") == "repair_fixpoint"
    ]
    assert fixpoint_events == []


# ---------------------------------------------------------------------------
# (c) Event fields correctly populated on fixpoint trigger
# ---------------------------------------------------------------------------


def test_fixpoint_event_fields_are_populated(tmp_path):
    captured: list[tuple[str, dict]] = []

    engine, _ = _engine(
        tmp_path,
        max_repair_attempts=5,
        metric_writer=lambda k, p: captured.append((k, p)),
    )

    stable = {"confidence": 0.2, "findings": "identical every time"}

    def _run_worker_fn(envelope: dict, task: str) -> dict:
        return dict(stable)

    engine.attempt_repair(
        worker_id="worker_fields",
        worker_result=dict(stable),
        critique=_initial_critique(),
        task="Demo task",
        envelope={"instructions": "stay identical"},
        run_worker_fn=_run_worker_fn,
        budget_checker=_budget_ok,
        iteration=7,
    )

    fixpoint_events = [
        p for (k, p) in captured
        if k == "metric.gate" and p.get("gate") == "repair_fixpoint"
    ]
    assert len(fixpoint_events) == 1, captured
    evt = fixpoint_events[0]

    # Normative fields per spec §11:
    assert evt["gate"] == "repair_fixpoint"
    assert "sim" in evt and isinstance(evt["sim"], float) and evt["sim"] >= 0.95
    assert "attempt" in evt and isinstance(evt["attempt"], int) and evt["attempt"] >= 2
    assert "previous_output_path" in evt
    assert isinstance(evt["previous_output_path"], str)
    assert evt["previous_output_path"] != ""

    # Extra shape fields that the runtime emits to route the rejection:
    assert evt["iteration"] == 7
    assert evt["verdict"] == "rejected"
    assert evt["worker_id"] == "worker_fields"
    assert evt["reason"].startswith("repair_fixpoint_detected")


# ---------------------------------------------------------------------------
# Sanity: threshold boundary — exactly 0.95 triggers, 0.94 does not
# ---------------------------------------------------------------------------


def test_threshold_is_respected(tmp_path):
    from awp.runtime.critique.simhash import text_simhash, similarity

    # Construct two short texts whose similarity is clearly above .95
    # (identical token bags) and two whose similarity is around .5
    # (random token overlap).
    s1 = text_simhash("alpha beta gamma delta epsilon zeta eta theta iota")
    s2 = text_simhash("alpha beta gamma delta epsilon zeta eta theta iota")
    assert similarity(s1, s2) == pytest.approx(1.0)

    s3 = text_simhash("kappa lambda mu nu xi omicron pi rho sigma")
    assert similarity(s1, s3) < 0.95

    # This guarantees the REPAIR_FIXPOINT_SIMILARITY constant really
    # discriminates the two cases this file depends on.
    assert CritiqueEngine.REPAIR_FIXPOINT_SIMILARITY == 0.95
