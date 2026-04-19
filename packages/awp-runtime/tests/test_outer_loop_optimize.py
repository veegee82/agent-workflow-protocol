"""Integration tests for :meth:`SuiteRunner.optimize` (Phase A3).

These exercise the 3-epoch SGD loop: apply, apply, regress + rollback.
A scripted optimiser and a stub workflow factory keep the tests
deterministic — no real LLM call, no real run.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest
from awp.outer_loop import (
    ALL_OPTIMIZABLE_ARTIFACTS,
    ArtifactRegistry,
    ArtifactUpdate,
    SuiteRunner,
    TaskSuiteSpec,
)
from awp.outer_loop.store import SqliteArtifactStore
from awp.outer_loop.suite import SuiteTask

# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------


class _LossScriptedFactory:
    """Workflow factory that writes a canned ``run_completion.json`` per epoch.

    The per-epoch loss is controlled by the ``eval_scores`` list: one
    entry per epoch, values in [0, 1]. Higher eval ⇒ lower loss.
    """

    def __init__(self, eval_scores):
        self._eval_scores = list(eval_scores)
        self._epoch = 0
        self._task_count_in_epoch = 0
        self._tasks_per_epoch = None

    def set_tasks_per_epoch(self, n: int) -> None:
        self._tasks_per_epoch = n

    def __call__(self, task, output_dir):
        # Advance per-epoch counter manually — the SuiteRunner doesn't
        # tell us which epoch we're in, so we bucket by task counts.
        if self._tasks_per_epoch is None:
            raise RuntimeError("set_tasks_per_epoch() must be called first")
        eval_score = self._eval_scores[self._epoch]
        run_id = f"run-{task.name}-{self._epoch}-{uuid.uuid4().hex[:4]}"
        run_dir = Path(output_dir) / "runs" / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "run_completion.json").write_text(
            json.dumps(
                {
                    "run_id": run_id,
                    "status": "complete",
                    "eval": {"score": eval_score},
                    "critique": {"score": eval_score},
                    "final_budget": {"budget_remaining_pct": 90.0},
                    "config_used": {"max_rejected_completions": 2},
                }
            ),
            encoding="utf-8",
        )
        (run_dir / "metrics.jsonl").write_text("", encoding="utf-8")
        self._task_count_in_epoch += 1
        if self._task_count_in_epoch >= self._tasks_per_epoch:
            self._task_count_in_epoch = 0
            self._epoch += 1
        return run_id, run_dir


class _ScriptedOptimizer:
    """Returns a pre-scripted :class:`ArtifactUpdate` per epoch."""

    def __init__(self, updates):
        self._updates = list(updates)
        self._idx = 0
        self.calls: list[dict] = []

    def propose_update(self, epoch_result, candidate_artifacts, *, learning_rate):
        self.calls.append(
            {
                "epoch_num": epoch_result.epoch_num,
                "candidates": list(candidate_artifacts),
                "learning_rate": learning_rate,
            }
        )
        if self._idx >= len(self._updates):
            return None
        upd = self._updates[self._idx]
        self._idx += 1
        return upd


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _suite() -> TaskSuiteSpec:
    return TaskSuiteSpec(
        name=f"opt_suite_{uuid.uuid4().hex[:6]}",
        tasks=[SuiteTask(name="alpha", task="do alpha")],
    )


def _new_store(tmp_path: Path):
    db_path = tmp_path / "outer_loop.db"
    registry = ArtifactRegistry(db_path=str(db_path))
    store = SqliteArtifactStore(str(db_path))
    return registry, store, db_path


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_three_epoch_apply_apply_rollback(tmp_path) -> None:
    registry, store, _ = _new_store(tmp_path)

    suite = _suite()
    # Epoch 1: eval=0.5 → loss ≈ 0.5.
    # Epoch 2: eval=0.6 → loss ≈ 0.4.       (improvement)
    # Epoch 3: eval=0.55 → loss ≈ 0.45.     (regression vs. e2)
    factory = _LossScriptedFactory(eval_scores=[0.5, 0.6, 0.55])
    factory.set_tasks_per_epoch(len(suite.tasks))
    runner = SuiteRunner(registry=registry, store=store, workflow_factory=factory)

    updates = [
        ArtifactUpdate(
            artifact_name="worker_pitfalls",
            proposed_content="v1 of worker_pitfalls",
            rationale="add pitfall",
            expected_loss_reduction=0.3,
            confidence=0.8,
        ),
        ArtifactUpdate(
            artifact_name="critique_rubric",
            proposed_content="v1 of critique_rubric",
            rationale="tighten rubric",
            expected_loss_reduction=0.4,
            confidence=0.7,
        ),
        # Epoch 3 regressed → no proposal should be requested in regression path,
        # but the scripted optimiser still has a pending one that must NOT be consumed.
        ArtifactUpdate(
            artifact_name="pattern_library",
            proposed_content="v1 of pattern_library",
            rationale="should-not-apply",
            expected_loss_reduction=1.0,
            confidence=1.0,
        ),
    ]
    optimizer = _ScriptedOptimizer(updates)

    results = runner.optimize(
        suite,
        n_epochs=3,
        learning_rate=0.5,
        optimizer=optimizer,
        output_dir=tmp_path / "out",
        rollback_on_regression=True,
    )

    assert len(results) == 3
    e1, e2, e3 = results

    assert e1.mean_loss is not None and e2.mean_loss is not None and e3.mean_loss is not None
    # Loss monotonicity per the scripted eval scores.
    assert e1.mean_loss > e2.mean_loss
    assert e3.mean_loss > e2.mean_loss  # regression

    # After epoch 1 we applied worker_pitfalls → v1.
    assert e1.child_artifacts["worker_pitfalls"] == 1
    # After epoch 2 we applied critique_rubric → v1.
    assert e2.child_artifacts["worker_pitfalls"] == 1
    assert e2.child_artifacts["critique_rubric"] == 1
    # Epoch 3 regressed → critique_rubric rolled back to v0.
    assert e3.child_artifacts["critique_rubric"] == 0
    assert e3.child_artifacts["worker_pitfalls"] == 1

    # Optimizer was called exactly twice (after e1 and e2); e3 regression path
    # must SKIP the propose_update call entirely.
    assert len(optimizer.calls) == 2
    # Learning-rate passed into 2nd call is still 0.5 (no regression before e2).
    assert optimizer.calls[0]["learning_rate"] == pytest.approx(0.5)
    assert optimizer.calls[1]["learning_rate"] == pytest.approx(0.5)

    # DB state: two versions beyond v0 were ever written.
    wp = registry.list_versions("worker_pitfalls")
    cr = registry.list_versions("critique_rubric")
    # worker_pitfalls: v0 + v1 (still active)
    assert [v.version for v in wp] == [0, 1]
    assert registry.get_active("worker_pitfalls").version == 1
    # critique_rubric: v0 + v1, but rollback → active = v0.
    assert [v.version for v in cr] == [0, 1]
    assert registry.get_active("critique_rubric").version == 0

    # child_artifacts_json for epoch 3 must carry the rollback event.
    epochs = store.list_epochs(e3.suite_id)
    ep3_row = [e for e in epochs if e["epoch_num"] == 3][0]
    payload = json.loads(ep3_row["child_artifacts_json"])
    assert "events" in payload
    assert any(ev["type"] == "rollback" for ev in payload["events"])
    rb = [ev for ev in payload["events"] if ev["type"] == "rollback"][0]
    assert rb["artifact"] == "critique_rubric"
    assert rb["from_version"] == 1
    assert rb["to_version"] == 0
    # Learning rate halved on rollback.
    assert rb["new_learning_rate"] == pytest.approx(0.25)


def test_optimize_without_optimizer_still_runs(tmp_path) -> None:
    """Passing ``optimizer=None`` collapses to a multi-epoch no-op."""
    registry, store, _ = _new_store(tmp_path)
    suite = _suite()
    factory = _LossScriptedFactory(eval_scores=[0.5, 0.5])
    factory.set_tasks_per_epoch(len(suite.tasks))
    runner = SuiteRunner(registry=registry, store=store, workflow_factory=factory)

    results = runner.optimize(
        suite,
        n_epochs=2,
        learning_rate=0.5,
        optimizer=None,
        output_dir=tmp_path / "out",
    )
    assert len(results) == 2
    # No versions beyond v0 exist.
    for name in ALL_OPTIMIZABLE_ARTIFACTS:
        assert [v.version for v in registry.list_versions(name)] == [0]


def test_optimize_respects_no_rollback(tmp_path) -> None:
    """With ``rollback_on_regression=False`` the update stays even on regression."""
    registry, store, _ = _new_store(tmp_path)
    suite = _suite()
    factory = _LossScriptedFactory(eval_scores=[0.6, 0.3])  # worse second
    factory.set_tasks_per_epoch(len(suite.tasks))
    runner = SuiteRunner(registry=registry, store=store, workflow_factory=factory)

    optimizer = _ScriptedOptimizer(
        [
            ArtifactUpdate(
                artifact_name="worker_pitfalls",
                proposed_content="v1",
                rationale="",
                expected_loss_reduction=0.5,
                confidence=0.8,
            )
        ]
    )

    results = runner.optimize(
        suite,
        n_epochs=2,
        learning_rate=0.5,
        optimizer=optimizer,
        output_dir=tmp_path / "out",
        rollback_on_regression=False,
    )
    assert len(results) == 2
    # worker_pitfalls was applied and NOT rolled back despite regression.
    assert registry.get_active("worker_pitfalls").version == 1
