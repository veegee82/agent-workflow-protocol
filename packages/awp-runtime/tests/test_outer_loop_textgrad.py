"""Unit tests for :class:`awp.outer_loop.textgrad.TextGradOptimizer` (Phase A3).

The optimiser calls an LLM once per candidate artifact. Every test here
injects a scripted stub LLM client so the tests are deterministic and do
not hit the network.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from awp.outer_loop import (
    ALL_OPTIMIZABLE_ARTIFACTS,
    ArtifactRegistry,
    ArtifactUpdate,
    TextGradOptimizer,
)
from awp.outer_loop.loss import LossBreakdown
from awp.outer_loop.runner import EpochResult, TaskRunResult

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class ScriptedLLM:
    """Minimal ``chat_text`` stub driven by a callable or a mapping."""

    def __init__(self, *, responder) -> None:
        self._responder = responder
        self.calls: list[list[dict]] = []

    def chat_text(self, messages, **_kwargs):
        self.calls.append(messages)
        if callable(self._responder):
            return self._responder(messages)
        # Mapping from candidate_name -> response.
        name = _extract_candidate_name(messages)
        return self._responder[name]


def _extract_candidate_name(messages):
    """Pull ``Candidate artifact: <name>`` out of the user message."""
    for m in messages:
        if m.get("role") == "user":
            for line in m.get("content", "").splitlines():
                if line.startswith("Candidate artifact:"):
                    return line.split(":", 1)[1].strip()
    return None


def _registry(tmp_path: Path) -> ArtifactRegistry:
    """Fresh SQLite-backed registry in a throwaway tmp dir."""
    return ArtifactRegistry(db_path=str(tmp_path / "outer_loop.db"))


def _epoch_result() -> EpochResult:
    """Tiny epoch result with one failing task — enough for a defect summary."""
    breakdown = LossBreakdown(
        total=0.6,
        eval_component=0.2,
        critique_component=0.2,
        gate_component=0.1,
        budget_component=0.0,
        status_component=0.1,
        raw_signals={
            "eval_score": 0.3,
            "critique_score": 0.4,
            "gate_rejection_count": 2,
            "status": "partial",
        },
    )
    task = TaskRunResult(
        task_name="alpha",
        run_id="run-alpha",
        run_dir="/tmp/run-alpha",
        status="partial",
        loss=0.6,
        breakdown=breakdown,
    )
    return EpochResult(
        epoch_id="ep-1",
        suite_id="suite-1",
        suite_name="suite_x",
        epoch_num=1,
        parent_artifacts={n: 0 for n in ALL_OPTIMIZABLE_ARTIFACTS},
        child_artifacts={n: 0 for n in ALL_OPTIMIZABLE_ARTIFACTS},
        task_results=[task],
        mean_loss=0.6,
        started_at="2026-04-18T00:00:00Z",
        completed_at="2026-04-18T00:05:00Z",
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_valid_json_yields_update(tmp_path) -> None:
    reg = _registry(tmp_path)

    def respond(messages):
        name = _extract_candidate_name(messages)
        if name == "worker_pitfalls":
            return json.dumps(
                {
                    "artifact_name": "worker_pitfalls",
                    "proposed_content": "NEW pitfalls text.",
                    "rationale": "Add a missing pitfall.",
                    "expected_loss_reduction": 0.3,
                    "confidence": 0.8,
                }
            )
        # Every other candidate declines.
        return json.dumps({"artifact_name": None, "confidence": 0.0})

    opt = TextGradOptimizer(llm_client=ScriptedLLM(responder=respond), registry=reg)
    update = opt.propose_update(
        _epoch_result(),
        candidate_artifacts=list(ALL_OPTIMIZABLE_ARTIFACTS),
        learning_rate=0.5,
    )
    assert update is not None
    assert update.artifact_name == "worker_pitfalls"
    assert update.proposed_content == "NEW pitfalls text."
    assert update.expected_loss_reduction == pytest.approx(0.3)
    assert update.confidence == pytest.approx(0.8)


def test_all_null_returns_none(tmp_path) -> None:
    reg = _registry(tmp_path)

    def respond(_messages):
        return json.dumps({"artifact_name": None, "confidence": 0.0})

    opt = TextGradOptimizer(llm_client=ScriptedLLM(responder=respond), registry=reg)
    assert (
        opt.propose_update(
            _epoch_result(),
            candidate_artifacts=list(ALL_OPTIMIZABLE_ARTIFACTS),
            learning_rate=0.5,
        )
        is None
    )


def test_invalid_json_skipped(tmp_path) -> None:
    reg = _registry(tmp_path)

    def respond(messages):
        name = _extract_candidate_name(messages)
        if name == "worker_pitfalls":
            return "this is not JSON at all"
        if name == "critique_rubric":
            return json.dumps(
                {
                    "artifact_name": "critique_rubric",
                    "proposed_content": "Revised rubric.",
                    "rationale": "Tighten severity rubric.",
                    "expected_loss_reduction": 0.4,
                    "confidence": 0.7,
                }
            )
        return json.dumps({"artifact_name": None, "confidence": 0.0})

    opt = TextGradOptimizer(llm_client=ScriptedLLM(responder=respond), registry=reg)
    update = opt.propose_update(
        _epoch_result(),
        candidate_artifacts=list(ALL_OPTIMIZABLE_ARTIFACTS),
        learning_rate=0.5,
    )
    assert update is not None
    # The invalid-JSON candidate was silently dropped; the rubric wins.
    assert update.artifact_name == "critique_rubric"


def test_markdown_fence_unwrapped(tmp_path) -> None:
    reg = _registry(tmp_path)

    payload = {
        "artifact_name": "pattern_library",
        "proposed_content": "Updated pattern library.",
        "rationale": "Add missing pattern.",
        "expected_loss_reduction": 0.2,
        "confidence": 0.6,
    }
    fenced = "```json\n" + json.dumps(payload) + "\n```"

    def respond(messages):
        name = _extract_candidate_name(messages)
        if name == "pattern_library":
            return fenced
        return json.dumps({"artifact_name": None, "confidence": 0.0})

    opt = TextGradOptimizer(llm_client=ScriptedLLM(responder=respond), registry=reg)
    update = opt.propose_update(
        _epoch_result(),
        candidate_artifacts=list(ALL_OPTIMIZABLE_ARTIFACTS),
        learning_rate=0.5,
    )
    assert update is not None
    assert update.artifact_name == "pattern_library"
    assert update.proposed_content == "Updated pattern library."


def test_unknown_artifact_name_rejected(tmp_path) -> None:
    reg = _registry(tmp_path)

    def respond(_messages):
        return json.dumps(
            {
                "artifact_name": "HALLUCINATED",
                "proposed_content": "irrelevant",
                "rationale": "irrelevant",
                "expected_loss_reduction": 1.0,
                "confidence": 1.0,
            }
        )

    opt = TextGradOptimizer(llm_client=ScriptedLLM(responder=respond), registry=reg)
    assert (
        opt.propose_update(
            _epoch_result(),
            candidate_artifacts=list(ALL_OPTIMIZABLE_ARTIFACTS),
            learning_rate=0.5,
        )
        is None
    )


def test_candidate_selection_picks_highest_score(tmp_path) -> None:
    """Three candidates with scores 0.72, 0.63, 0.40 → winner is the 0.72 one."""
    reg = _registry(tmp_path)

    responses = {
        "worker_pitfalls": {
            "artifact_name": "worker_pitfalls",
            "proposed_content": "A",
            "rationale": "...",
            "expected_loss_reduction": 0.9,
            "confidence": 0.8,  # 0.72
        },
        "critique_rubric": {
            "artifact_name": "critique_rubric",
            "proposed_content": "B",
            "rationale": "...",
            "expected_loss_reduction": 0.7,
            "confidence": 0.9,  # 0.63
        },
        "pattern_library": {
            "artifact_name": "pattern_library",
            "proposed_content": "C",
            "rationale": "...",
            "expected_loss_reduction": 0.8,
            "confidence": 0.5,  # 0.40
        },
    }

    def respond(messages):
        name = _extract_candidate_name(messages)
        if name in responses:
            return json.dumps(responses[name])
        return json.dumps({"artifact_name": None, "confidence": 0.0})

    opt = TextGradOptimizer(llm_client=ScriptedLLM(responder=respond), registry=reg)
    update = opt.propose_update(
        _epoch_result(),
        candidate_artifacts=list(ALL_OPTIMIZABLE_ARTIFACTS),
        learning_rate=0.5,
    )
    assert update is not None
    assert update.artifact_name == "worker_pitfalls"


def test_unchanged_content_treated_as_noop(tmp_path) -> None:
    reg = _registry(tmp_path)
    current = reg.get_active("worker_pitfalls").content  # v0 default

    def respond(messages):
        name = _extract_candidate_name(messages)
        if name == "worker_pitfalls":
            return json.dumps(
                {
                    "artifact_name": "worker_pitfalls",
                    "proposed_content": current,  # identical
                    "rationale": "no change",
                    "expected_loss_reduction": 0.9,
                    "confidence": 0.9,
                }
            )
        return json.dumps({"artifact_name": None, "confidence": 0.0})

    opt = TextGradOptimizer(llm_client=ScriptedLLM(responder=respond), registry=reg)
    assert (
        opt.propose_update(
            _epoch_result(),
            candidate_artifacts=list(ALL_OPTIMIZABLE_ARTIFACTS),
            learning_rate=0.5,
        )
        is None
    )


def test_content_too_long_rejected(tmp_path) -> None:
    reg = _registry(tmp_path)
    huge = "x" * 25_000

    def respond(messages):
        name = _extract_candidate_name(messages)
        if name == "worker_pitfalls":
            return json.dumps(
                {
                    "artifact_name": "worker_pitfalls",
                    "proposed_content": huge,
                    "rationale": "huge",
                    "expected_loss_reduction": 1.0,
                    "confidence": 1.0,
                }
            )
        return json.dumps({"artifact_name": None, "confidence": 0.0})

    opt = TextGradOptimizer(llm_client=ScriptedLLM(responder=respond), registry=reg)
    assert (
        opt.propose_update(
            _epoch_result(),
            candidate_artifacts=list(ALL_OPTIMIZABLE_ARTIFACTS),
            learning_rate=0.5,
        )
        is None
    )


def test_llm_exception_skipped(tmp_path) -> None:
    """A raising LLM per candidate collapses to None (no partial update)."""
    reg = _registry(tmp_path)

    def responder(_messages):
        raise RuntimeError("boom")

    opt = TextGradOptimizer(llm_client=ScriptedLLM(responder=responder), registry=reg)
    assert (
        opt.propose_update(
            _epoch_result(),
            candidate_artifacts=list(ALL_OPTIMIZABLE_ARTIFACTS),
            learning_rate=0.5,
        )
        is None
    )


def test_clamp_values_outside_envelope(tmp_path) -> None:
    reg = _registry(tmp_path)

    def respond(messages):
        name = _extract_candidate_name(messages)
        if name == "worker_pitfalls":
            return json.dumps(
                {
                    "artifact_name": "worker_pitfalls",
                    "proposed_content": "NEW pitfalls.",
                    "rationale": "...",
                    "expected_loss_reduction": 1.5,  # out of range
                    "confidence": -0.3,  # out of range
                }
            )
        return json.dumps({"artifact_name": None, "confidence": 0.0})

    opt = TextGradOptimizer(llm_client=ScriptedLLM(responder=respond), registry=reg)
    update = opt.propose_update(
        _epoch_result(),
        candidate_artifacts=list(ALL_OPTIMIZABLE_ARTIFACTS),
        learning_rate=0.5,
    )
    # Confidence clamped to 0.0 → score=0 → no winner.
    assert update is None


def test_artifact_update_score_is_product() -> None:
    upd = ArtifactUpdate(
        artifact_name="worker_pitfalls",
        proposed_content="x",
        rationale="",
        expected_loss_reduction=0.4,
        confidence=0.5,
    )
    assert upd.score == pytest.approx(0.2)
