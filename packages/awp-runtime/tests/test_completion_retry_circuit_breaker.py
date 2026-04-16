"""Tests for the completion-retry circuit breaker (Fix C).

After ``DelegationBudget.max_rejected_completions`` consecutive
rejections of a manager COMPLETE decision, the runner either:

* synthesizes a concrete repair subtask from the last rejection payload
  and forces a DELEGATE on the next iteration, OR
* terminates the run as ``partial`` with reason
  ``max_rejected_completions`` when no repair can be derived.

The counter resets on any successful DELEGATE.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from awp.models.orchestration import DelegationBudget
from awp.runtime.delegation_loop_runner import (
    DelegationLoopRunner,
    _finalize_terminal_status,
)


@pytest.fixture
def runner() -> DelegationLoopRunner:
    r = DelegationLoopRunner.__new__(DelegationLoopRunner)
    r._budget = DelegationBudget(max_rejected_completions=2)
    r._iter_counter = 3
    r._logger = MagicMock()
    r._logger.trace_gate = MagicMock()
    return r


def test_budget_model_default_rejected_completions():
    b = DelegationBudget()
    assert b.max_rejected_completions == 2


def test_counter_bumps_and_trips_with_repair(runner):
    state: dict = {}
    runner._record_completion_rejection(
        state,
        gate="deliverable_presence",
        reason="1 missing",
        repair_payload={"missing": ["report.md"]},
    )
    tripped, repaired = runner._maybe_trip_completion_circuit_breaker(state)
    assert not tripped  # still below cap (1/2)

    runner._record_completion_rejection(
        state,
        gate="deliverable_presence",
        reason="1 missing",
        repair_payload={"missing": ["report.md"]},
    )
    tripped, repaired = runner._maybe_trip_completion_circuit_breaker(state)
    assert tripped and repaired
    assert "_forced_repair_subtask" in state
    repair = state["_forced_repair_subtask"]
    assert "report.md" in repair["required_outputs"]
    assert repair["priority"] == "critical"
    # Counter resets after repair synthesis so the manager gets one more shot
    assert state["_rejected_completions"] == 0


def test_counter_trips_to_partial_when_no_repair_possible(runner):
    state: dict = {}
    # Payloads without any concrete defect → no repair can be synthesized
    for _ in range(2):
        runner._record_completion_rejection(
            state,
            gate="critique",
            reason="low score",
            repair_payload={},
        )
    tripped, repaired = runner._maybe_trip_completion_circuit_breaker(state)
    assert tripped and not repaired


def test_counter_resets_on_successful_delegate(runner):
    state = {"_rejected_completions": 1, "_last_completion_rejection": {}}
    runner._reset_completion_rejection_counter(state)
    assert state["_rejected_completions"] == 0
    assert "_last_completion_rejection" not in state


def test_terminal_status_mapping_for_forced_partial():
    # Session 1 added ``max_rejected_completions`` to _FORCED_PARTIAL_REASONS.
    assert _finalize_terminal_status("max_rejected_completions") == "partial"


def test_synthesize_repair_covers_all_payload_shapes(runner):
    cases = [
        ({"missing": ["a.md"]}, "a.md"),
        ({"empty": ["b.csv"]}, "b.csv"),
        ({"placeholder_findings": ["XX%"]}, "Placeholder"),
        ({"critical_files": ["bad.png"]}, "Broken"),
        ({"structural_failures": ["dup paragraph"]}, "Structural"),
    ]
    for payload, needle in cases:
        repair = runner._synthesize_repair_subtask(payload)
        assert repair is not None
        assert needle.lower() in repair["success_criteria"].lower()

    assert runner._synthesize_repair_subtask({}) is None
    assert runner._synthesize_repair_subtask({"unrelated": "x"}) is None
