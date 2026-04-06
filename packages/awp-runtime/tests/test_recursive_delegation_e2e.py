"""Unit + integration tests for A4 recursive delegation (submanagers).

These tests verify the four termination guarantees:

1. **Budget cascade**: a child runner cannot exceed the fraction allocated.
2. **Reclaim**: ungeused child capacity flows back to the parent on finish.
3. **Depth limit**: ``as_submanager`` is silently downgraded when depth maxed.
4. **No-hang on failure**: a child that raises still produces a normalised
   result with ``confidence: 0.0`` so the parent never blocks.

All tests run without LLM calls — the manager and workers are mocked at the
``DelegationLoopRunner._run_manager`` / ``_run_ephemeral_worker`` boundary.
"""

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from awp.models.orchestration import (
    DelegationBudget,
    DelegationLoopConfig,
)
from awp.runtime.delegation_loop_runner import (
    BudgetSnapshot,
    DelegationLoopRunner,
    TaskPlan,
)


# --------------------------------------------------------------------------- #
# 1. BudgetSnapshot.allocate_child / reclaim_child                            #
# --------------------------------------------------------------------------- #


class TestBudgetCascade:
    def _make_parent(self, **kw) -> BudgetSnapshot:
        b = DelegationBudget(
            max_loops=kw.get("max_loops", 100),
            max_total_workers=kw.get("max_total_workers", 50),
            max_total_tokens=kw.get("max_total_tokens", 1_000_000),
            max_wall_time=kw.get("max_wall_time", 600),
            max_tool_calls=kw.get("max_tool_calls", 200),
            max_depth=kw.get("max_depth", 3),
        )
        return BudgetSnapshot(b)

    def test_child_is_hard_capped_fraction_of_remaining(self):
        parent = self._make_parent(max_loops=100, max_total_tokens=1000)
        parent.loops_used = 20  # 80 remaining
        parent.tokens_consumed = 200  # 800 remaining

        child = parent.allocate_child(fraction=0.5)
        assert child.max_loops == 40  # 80 * 0.5
        assert child.max_total_tokens == 400  # 800 * 0.5

    def test_child_max_depth_decrements(self):
        parent = self._make_parent(max_depth=3)
        child = parent.allocate_child()
        assert child.max_depth == 2
        grandchild = child.allocate_child()
        assert grandchild.max_depth == 1

    def test_child_walltime_inherits_parent_remaining(self):
        parent = self._make_parent(max_wall_time=600)
        child = parent.allocate_child(fraction=0.9)
        # child wall-time is parent's remaining wall-time, NOT a fraction —
        # the global timeout always wins
        assert child.max_wall_time <= 600
        assert child.max_wall_time >= 1

    def test_reclaim_folds_child_usage_into_parent(self):
        parent = self._make_parent(max_loops=100, max_total_tokens=1000)
        child = parent.allocate_child(fraction=0.5)

        # Simulate child consumption
        child.loops_used = 10
        child.workers_spawned = 3
        child.tokens_consumed = 250
        child.tool_calls_used = 8

        parent.reclaim_child(child)

        assert parent.loops_used == 10
        assert parent.workers_spawned == 3
        assert parent.tokens_consumed == 250
        assert parent.tool_calls_used == 8

    def test_double_reclaim_is_noop(self):
        parent = self._make_parent()
        child = parent.allocate_child()
        child.loops_used = 5
        parent.reclaim_child(child)
        parent.reclaim_child(child)  # second call must not double-charge
        assert parent.loops_used == 5

    def test_reclaim_wrong_parent_is_noop(self):
        parent_a = self._make_parent()
        parent_b = self._make_parent()
        child = parent_a.allocate_child()
        child.loops_used = 7
        parent_b.reclaim_child(child)  # wrong parent
        assert parent_b.loops_used == 0
        # original parent still works
        parent_a.reclaim_child(child)
        assert parent_a.loops_used == 7

    def test_fraction_clamped_to_safe_range(self):
        parent = self._make_parent(max_loops=100)
        # too low
        c1 = parent.allocate_child(fraction=0.001)
        assert c1.max_loops >= 1
        # too high
        c2 = parent.allocate_child(fraction=2.0)
        # 0.95 of remaining, not the original max
        assert c2.max_loops <= 100


# --------------------------------------------------------------------------- #
# 2. TaskPlan: submanager promotion                                           #
# --------------------------------------------------------------------------- #


class TestTaskPlanPromotion:
    def test_force_advance_promotes_when_allowed(self):
        tp = TaskPlan()
        tp.set_subtasks([
            {"id": "subtask_research", "description": "research stuff", "dependencies": []},
        ])
        for _ in range(TaskPlan.MAX_SUBTASK_ITERATIONS + 1):
            tp.record_iteration("research_worker")
        tp.update_status("research_worker", "failed")

        advanced = tp.force_advance_stuck(promote_to_submanager=True)
        assert "subtask_research" in advanced
        # Promoted subtasks stay in_progress with the submanager strategy
        st = tp._subtasks[0]
        assert st["delegation_strategy"] == "submanager"
        assert st["status"] == "in_progress"
        # Iteration counter is reset so submanager gets a fresh window
        assert tp._subtask_iterations["subtask_research"] == 0

    def test_force_advance_completes_when_not_allowed(self):
        tp = TaskPlan()
        tp.set_subtasks([
            {"id": "subtask_research", "description": "do research", "dependencies": []},
        ])
        for _ in range(TaskPlan.MAX_SUBTASK_ITERATIONS + 1):
            tp.record_iteration("research_worker")
        advanced = tp.force_advance_stuck(promote_to_submanager=False)
        assert "subtask_research" in advanced
        assert tp._subtasks[0]["status"] == "completed"

    def test_promotion_idempotent(self):
        """Already-promoted subtasks should not be re-promoted."""
        tp = TaskPlan()
        tp.set_subtasks([
            {
                "id": "subtask_analysis",
                "description": "do analysis",
                "dependencies": [],
                "delegation_strategy": "submanager",
            },
        ])
        for _ in range(TaskPlan.MAX_SUBTASK_ITERATIONS + 1):
            tp.record_iteration("analysis_worker")
        tp.update_status("analysis_worker", "failed")
        advanced = tp.force_advance_stuck(promote_to_submanager=True)
        # Already submanager — should be force-completed instead
        assert tp._subtasks[0]["status"] == "completed"


# --------------------------------------------------------------------------- #
# 3. DelegationLoopRunner: submanager spawn / depth gate                      #
# --------------------------------------------------------------------------- #


def _make_runner(tmp_path: Path, max_depth: int = 2) -> DelegationLoopRunner:
    """Build a minimal DelegationLoopRunner with no LLM."""
    workflow_dir = tmp_path / "wf"
    (workflow_dir / "workspace").mkdir(parents=True)
    (workflow_dir / "agents" / "manager").mkdir(parents=True)
    (workflow_dir / "agents" / "manager" / "system_prompt.md").write_text(
        "You are the manager."
    )

    cfg = DelegationLoopConfig(
        manager="agents/manager",
        budget=DelegationBudget(
            max_loops=20,
            max_total_workers=20,
            max_total_tokens=100_000,
            max_wall_time=300,
            max_tool_calls=50,
            max_depth=max_depth,
        ),
    )
    return DelegationLoopRunner(
        workflow_dir=workflow_dir,
        config=cfg,
        run_id="test_run",
    )


class TestSubmanagerGate:
    def test_is_submanager_envelope_true_when_flagged(self, tmp_path):
        r = _make_runner(tmp_path, max_depth=2)
        env = {"as_submanager": True, "worker_id": "w1"}
        assert r._is_submanager_envelope(env) is True

    def test_is_submanager_envelope_false_when_depth_maxed(self, tmp_path):
        r = _make_runner(tmp_path, max_depth=1)
        r._depth = 1  # at the limit
        env = {"as_submanager": True, "worker_id": "w1"}
        assert r._is_submanager_envelope(env) is False, (
            "Depth gate must override the as_submanager flag — otherwise "
            "the loop could recurse forever."
        )

    def test_is_submanager_via_plan_strategy(self, tmp_path):
        r = _make_runner(tmp_path, max_depth=2)
        r._task_plan = TaskPlan()
        r._task_plan.set_subtasks([
            {
                "id": "subtask_a",
                "description": "a",
                "dependencies": [],
                "delegation_strategy": "submanager",
            }
        ])
        env = {"worker_id": "w1", "subtask_id": "subtask_a"}
        assert r._is_submanager_envelope(env) is True

    def test_is_submanager_default_false(self, tmp_path):
        r = _make_runner(tmp_path, max_depth=2)
        env = {"worker_id": "w1", "instructions": "do stuff"}
        assert r._is_submanager_envelope(env) is False


class TestSubmanagerSpawnNoHang:
    """Submanager spawning must never hang the parent loop on failure."""

    def test_failing_submanager_returns_normalized_result(self, tmp_path, monkeypatch):
        r = _make_runner(tmp_path, max_depth=2)
        # Patch DelegationLoopRunner.run on the CHILD instance to raise.
        # We do this by patching the class method then restoring.
        original_run = DelegationLoopRunner.run

        def boom(self, task, state=None):
            if self._depth > 0:
                raise RuntimeError("submanager exploded")
            return original_run(self, task, state)

        monkeypatch.setattr(DelegationLoopRunner, "run", boom)

        env = {
            "worker_id": "w_explode",
            "as_submanager": True,
            "submanager_budget_fraction": 0.3,
            "instructions": "test",
        }
        result = r._spawn_submanager("w_explode", env, "task", {}, iteration=1)
        # Must NOT raise — must return a normalised dict
        assert result["status"] == "ok"
        assert result["result"]["confidence"] == 0.0
        assert result["result"]["submanager_failed"] is True

    def test_spawning_creates_sub_run_directory(self, tmp_path, monkeypatch):
        r = _make_runner(tmp_path, max_depth=2)
        # Mock child run to immediately complete
        original_run = DelegationLoopRunner.run

        def fake_run(self, task, state=None):
            if self._depth > 0:
                # write a manifest to prove the child ran
                self._logger.run_dir.mkdir(parents=True, exist_ok=True)
                (self._logger.run_dir / "run_manifest.json").write_text(
                    json.dumps({"run_id": self._run_id})
                )
                self._logger.flush()
                return {"finding": "child done", "confidence": 0.8}
            return original_run(self, task, state)

        monkeypatch.setattr(DelegationLoopRunner, "run", fake_run)

        env = {
            "worker_id": "w_child",
            "as_submanager": True,
            "submanager_budget_fraction": 0.3,
            "instructions": "test",
        }
        result = r._spawn_submanager("w_child", env, "task", {}, iteration=1)
        assert result["status"] == "ok"
        assert result["result"]["_submanager"] is True
        assert result["result"]["_submanager_depth"] == 1
        # Verify the sub-run directory was created under the worker dir
        # so the visualizer can find it
        sub_dir = (
            r._run_dir
            / "iterations"
            / "001"
            / "delegations"
            / "w_child"
            / "runs"
        )
        assert sub_dir.exists(), "sub_run dir must be under <worker>/runs/"
        sub_runs = list(sub_dir.iterdir())
        assert len(sub_runs) == 1
        assert (sub_runs[0] / "run_manifest.json").exists()

    def test_budget_reclaimed_after_child_failure(self, tmp_path, monkeypatch):
        r = _make_runner(tmp_path, max_depth=2)

        def boom(self, task, state=None):
            if self._depth > 0:
                # Pretend the child consumed some budget before crashing
                self._budget.loops_used = 3
                self._budget.tokens_consumed = 1500
                raise RuntimeError("crash")
            return None

        monkeypatch.setattr(DelegationLoopRunner, "run", boom)

        loops_before = r._budget.loops_used
        tokens_before = r._budget.tokens_consumed
        env = {
            "worker_id": "w",
            "as_submanager": True,
            "instructions": "x",
        }
        r._spawn_submanager("w", env, "task", {}, iteration=1)
        # Reclaim folds the partial child usage into the parent
        assert r._budget.loops_used >= loops_before + 3
        assert r._budget.tokens_consumed >= tokens_before + 1500

    def test_inherited_state_subset_only(self, tmp_path, monkeypatch):
        r = _make_runner(tmp_path, max_depth=2)
        seen_state: dict = {}

        def capture(self, task, state=None):
            if self._depth > 0:
                seen_state.update(state or {})
                return {"confidence": 0.7}
            return None

        monkeypatch.setattr(DelegationLoopRunner, "run", capture)

        parent_state = {
            "data_summary": "important",
            "secret_token": "should_not_leak",
            "another_field": 42,
        }
        env = {
            "worker_id": "w",
            "as_submanager": True,
            "inherited_state_keys": ["data_summary"],
            "instructions": "x",
        }
        r._spawn_submanager("w", env, "task", parent_state, iteration=1)
        # Only the explicitly listed keys should reach the child
        assert "data_summary" in seen_state
        assert "secret_token" not in seen_state
        assert "another_field" not in seen_state
