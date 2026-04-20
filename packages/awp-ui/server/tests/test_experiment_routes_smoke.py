"""Smoke test for the full experiment/task UI backend pipeline (no browser)."""

from __future__ import annotations

from pathlib import Path

import pytest
import pytest_asyncio

from server.services.store import StoreService


@pytest_asyncio.fixture
async def store(tmp_path: Path) -> StoreService:
    s = StoreService(db_path=tmp_path / "test.db")
    await s.init_db()
    yield s
    await s.close()


@pytest.mark.asyncio
async def test_full_experiment_task_hierarchy_pipeline(store: StoreService) -> None:
    """Smoke test: create experiment → task → seed runs → check all API endpoints."""
    # 1. Create experiment
    exp_id = "exp_smoke_001"
    await store.create_experiment(exp_id, "Smoke", "Test goal", "/tmp/smoke", 1.0)

    # 2. Create task
    task_key = f"{exp_id}:001-test"
    await store.create_task(
        task_id_key=task_key,
        experiment_id=exp_id,
        task_number=1,
        slug="test",
        mode="seed",
        user_prompt="Test prompt",
        user_feedback=None,
        inputs_json="[]",
        created_at=1.0,
    )

    # 3. Seed two runs with losses
    await store.upsert_run_for_task("r1", exp_id, task_key, "seed", 0.5, "complete", "P", "m")
    await store.upsert_run_for_task("r2", exp_id, task_key, "refine_iter", 0.3, "complete", "P", "m")
    await store.set_task_best(task_key, "r2", "auto_loss")

    # 4. Test list_runs_for_task
    runs = await store.list_runs_for_task(task_key)
    assert len(runs) == 2
    assert runs[0]["id"] == "r1"
    assert runs[1]["id"] == "r2"

    # 5. Test get_task_loss_series
    series = await store.get_task_loss_series(task_key)
    assert len(series) == 2
    assert series[0]["loss"] == pytest.approx(0.5)
    assert series[1]["loss"] == pytest.approx(0.3)
    assert series[1]["run_role"] == "refine_iter"

    # 6. Test get_experiment_loss_curve
    curve = await store.get_experiment_loss_curve(exp_id)
    assert len(curve) == 1
    assert curve[0]["task_number"] == 1
    assert curve[0]["best_loss"] == pytest.approx(0.3)

    # 7. Test set_task_best (override)
    await store.set_task_best(task_key, "r1", "user_override")
    task = await store.get_task(task_key)
    assert task["best_run_id"] == "r1"
    assert task["best_reason"] == "user_override"

    # 8. Verify the override changes the loss curve
    curve_after = await store.get_experiment_loss_curve(exp_id)
    assert curve_after[0]["best_loss"] == pytest.approx(0.5)
