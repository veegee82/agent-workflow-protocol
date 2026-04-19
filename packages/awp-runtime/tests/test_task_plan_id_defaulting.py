"""Regression test for TaskPlan.set_subtasks defensive id defaulting.

Submanager LLM outputs occasionally omit the ``id`` key on subtasks. The
downstream methods ``get_next_actionable`` / ``to_prompt_section`` /
``get_stuck_subtasks`` used to raise ``KeyError('id')`` in that case,
aborting the manager loop with a generic "Manager execution failed: 'id'"
error. ``set_subtasks`` now fills an index-based default so the plan stays
usable even when the LLM slips.
"""

from __future__ import annotations

import pytest

from awp.runtime.delegation_loop_runner import TaskPlan


def test_set_subtasks_defaults_id_when_missing():
    plan = TaskPlan(max_subtasks=10)
    plan.set_subtasks([
        {"description": "claim compound A", "priority": "high"},
        {"description": "claim compound B"},
    ])
    ids = [st["id"] for st in plan._subtasks]
    assert ids == ["subtask_0", "subtask_1"]


def test_set_subtasks_preserves_explicit_id():
    plan = TaskPlan(max_subtasks=10)
    plan.set_subtasks([
        {"id": "subtask_zylithium", "description": "x"},
        {"id": "subtask_auralium", "description": "y"},
    ])
    assert [st["id"] for st in plan._subtasks] == [
        "subtask_zylithium",
        "subtask_auralium",
    ]


def test_set_subtasks_mixed_id_fills_gaps():
    plan = TaskPlan(max_subtasks=10)
    plan.set_subtasks([
        {"id": "subtask_known", "description": "x"},
        {"description": "y"},
    ])
    assert [st["id"] for st in plan._subtasks] == [
        "subtask_known",
        "subtask_1",
    ]


def test_get_next_actionable_does_not_crash_without_ids():
    plan = TaskPlan(max_subtasks=10)
    plan.set_subtasks([{"description": "x"}, {"description": "y"}])
    for st in plan._subtasks:
        assert st["status"] == "pending"
    actionable = plan.get_next_actionable()
    assert len(actionable) == 2
    assert all("id" in st for st in actionable)


def test_to_prompt_section_renders_without_ids():
    plan = TaskPlan(max_subtasks=10)
    plan.set_subtasks([{"description": "x"}])
    rendered = plan.to_prompt_section()
    assert "subtask_0" in rendered
