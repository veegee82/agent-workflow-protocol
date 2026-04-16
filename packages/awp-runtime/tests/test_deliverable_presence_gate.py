"""Tests for the ``deliverable_presence`` gate (Fix B).

The gate verifies that every manager-declared deliverable path exists
on disk and is non-empty before a COMPLETE decision is accepted. It
derives the required paths from, in order:

1. ``required_outputs`` on each subtask of the active task plan.
2. Path tokens scraped from each subtask's ``success_criteria`` /
   ``description`` via the ``_output_dir`` / ``_workspace_dir`` anchor.
3. Path tokens scraped from the original task string.

When none of the three yield any path, the gate emits a warning and
becomes a non-blocking no-op.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from awp.runtime.delegation_loop_runner import DelegationLoopRunner, TaskPlan


@pytest.fixture
def runner(tmp_path: Path) -> DelegationLoopRunner:
    r = DelegationLoopRunner.__new__(DelegationLoopRunner)
    run_id = "2026-04-14_test"
    r._dir = tmp_path
    r._run_id = run_id
    r._iter_counter = 1
    (tmp_path / "output" / run_id).mkdir(parents=True)
    (tmp_path / "workspace" / "inputs").mkdir(parents=True)
    r._task_plan = None
    r._logger = MagicMock()
    return r


def _output_file(runner: DelegationLoopRunner, name: str, content: bytes = b"") -> Path:
    p = runner._dir / "output" / runner._run_id / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(content)
    return p


def test_gate_passes_when_all_required_outputs_present(runner):
    plan = TaskPlan()
    plan.set_subtasks(
        [
            {
                "id": "s1",
                "description": "produce report",
                "required_outputs": ["report.md", "charts/plot.png"],
            }
        ]
    )
    runner._task_plan = plan
    _output_file(runner, "report.md", b"# real content\n")
    _output_file(runner, "charts/plot.png", b"\x89PNG\r\n\x1a\n" + b"x" * 512)
    assert runner._deliverable_presence_gate("task text") is None


def test_gate_rejects_on_missing_required_output(runner):
    plan = TaskPlan()
    plan.set_subtasks([{"id": "s1", "required_outputs": ["report.md"]}])
    runner._task_plan = plan
    # Do not create the file
    verdict = runner._deliverable_presence_gate("task text")
    assert verdict is not None
    assert any("report.md" in m for m in verdict["missing"])
    assert verdict["empty"] == []
    assert verdict["source"] == "required_outputs"


def test_gate_rejects_on_empty_required_output(runner):
    plan = TaskPlan()
    plan.set_subtasks([{"id": "s1", "required_outputs": ["empty.md"]}])
    runner._task_plan = plan
    _output_file(runner, "empty.md", b"")  # zero bytes
    verdict = runner._deliverable_presence_gate("task text")
    assert verdict is not None
    assert verdict["missing"] == []
    assert any("empty.md" in m for m in verdict["empty"])


def test_gate_falls_back_to_success_criteria_regex(runner):
    plan = TaskPlan()
    plan.set_subtasks(
        [
            {
                "id": "s1",
                "success_criteria": 'File _output_dir + "/analysis.csv" must exist with real rows.',
            }
        ]
    )
    runner._task_plan = plan
    verdict = runner._deliverable_presence_gate("outer task")
    assert verdict is not None
    assert any("analysis.csv" in m for m in verdict["missing"])
    assert verdict["source"] == "success_criteria"


def test_gate_skips_non_blockingly_when_no_paths_derivable(runner):
    plan = TaskPlan()
    plan.set_subtasks([{"id": "s1", "description": "abstract task, no file mentioned"}])
    runner._task_plan = plan
    verdict = runner._deliverable_presence_gate("write a haiku")
    assert verdict is None
    # Warning is logged but gate is non-blocking
