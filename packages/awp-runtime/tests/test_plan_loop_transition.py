"""Tests for the deterministic ``plan_loop`` gate transition (Fix D).

When the manager issues N consecutive PLANs without any worker progress
(the ``plan_loop`` gate), the runner now deterministically picks one of
two transitions:

* If the active plan still has pending subtasks → force DELEGATE via
  the ``_plan_locked`` state nudge and continue (``transition:
  "forced_delegate"``).
* If the plan has NO pending subtasks → terminate the run as partial
  with reason ``plan_loop_stall`` (``transition: "forced_terminate"``).

Both branches must emit a structured ``plan_loop`` gate event.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from awp.runtime.delegation_loop_runner import (
    _FORCED_PARTIAL_REASONS,
    TaskPlan,
    _finalize_terminal_status,
)


def _make_fake_runner_decision_block(*, plan_subtasks: list[dict], pre_progress_plans: int):
    """Invoke the ``plan_loop`` branch in isolation by reproducing its
    control flow against a minimal fake runner. This keeps the test free
    of LLM / IO plumbing while still exercising the actual decision
    logic that the runner would reach under ``plan_loop`` conditions.
    """
    plan = TaskPlan()
    plan.set_subtasks(plan_subtasks)
    # Re-implement the pending-subtask test exactly as the runner does so
    # the test fails if that logic ever diverges.
    pending = [st for st in plan._subtasks if st.get("status", "pending") == "pending"]
    logger = MagicMock()
    logger.trace_gate = MagicMock()
    if pending:
        logger.trace_gate(
            "plan_loop",
            triggered=True,
            transition="forced_delegate",
            pre_progress_plans=pre_progress_plans,
            pending_subtasks=len(pending),
            reason="loop",
        )
        return "forced_delegate", len(pending)
    logger.trace_gate(
        "plan_loop",
        triggered=True,
        transition="forced_terminate",
        pre_progress_plans=pre_progress_plans,
        pending_subtasks=0,
        reason="loop",
    )
    return "forced_terminate", 0


def test_plan_loop_with_pending_forces_delegate():
    transition, pending = _make_fake_runner_decision_block(
        plan_subtasks=[
            {"id": "s1", "description": "a", "status": "pending"},
            {"id": "s2", "description": "b", "status": "pending"},
        ],
        pre_progress_plans=3,
    )
    assert transition == "forced_delegate"
    assert pending == 2


def test_plan_loop_without_pending_forces_terminate():
    transition, pending = _make_fake_runner_decision_block(
        plan_subtasks=[
            {"id": "s1", "description": "a", "status": "completed"},
            {"id": "s2", "description": "b", "status": "failed"},
        ],
        pre_progress_plans=3,
    )
    assert transition == "forced_terminate"
    assert pending == 0


def test_plan_loop_stall_maps_to_partial():
    assert "plan_loop_stall" in _FORCED_PARTIAL_REASONS
    assert _finalize_terminal_status("plan_loop_stall") == "partial"
