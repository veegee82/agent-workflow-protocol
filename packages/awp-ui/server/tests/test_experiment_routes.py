"""Plan 5 — backend route + store tests for experiment/task hierarchy."""

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
async def test_list_runs_for_task_ordered_by_created_at(store: StoreService) -> None:
    await store.create_experiment("exp_a", "E", "", "/tmp/a", 1.0)
    await store.create_task(
        "exp_a:001-s", "exp_a", 1, "s", "seed", "p", None, "[]", 1.0,
    )
    await store.upsert_run_for_task("r1", "exp_a", "exp_a:001-s", "seed", 0.5, "complete", "t", "m")
    await store.upsert_run_for_task("r2", "exp_a", "exp_a:001-s", "refine_iter", 0.3, "complete", "t", "m")
    await store.upsert_run_for_task("r3", "exp_a", "exp_a:001-s", "seed", 0.4, "complete", "t", "m")
    rows = await store.list_runs_for_task("exp_a:001-s")
    assert [r["id"] for r in rows] == ["r1", "r2", "r3"]
    roles = {r["id"]: r["run_role"] for r in rows}
    assert roles == {"r1": "seed", "r2": "refine_iter", "r3": "seed"}


@pytest.mark.asyncio
async def test_get_task_loss_series(store: StoreService) -> None:
    await store.create_experiment("exp_a", "E", "", "/tmp/a", 1.0)
    await store.create_task(
        "exp_a:001-s", "exp_a", 1, "s", "seed", "p", None, "[]", 1.0,
    )
    await store.upsert_run_for_task("r1", "exp_a", "exp_a:001-s", "seed", 0.5, "complete", "t", "m")
    await store.upsert_run_for_task("r2", "exp_a", "exp_a:001-s", "refine_iter", 0.3, "complete", "t", "m")
    series = await store.get_task_loss_series("exp_a:001-s")
    assert len(series) == 2
    assert series[0]["loss"] == pytest.approx(0.5)
    assert series[1]["loss"] == pytest.approx(0.3)
    assert series[0]["run_role"] == "seed"
    assert series[1]["run_role"] == "refine_iter"


@pytest.mark.asyncio
async def test_get_experiment_loss_curve(store: StoreService) -> None:
    """One point per task: (task_number, best_loss)."""
    await store.create_experiment("exp_a", "E", "", "/tmp/a", 1.0)
    await store.create_task(
        "exp_a:001-s", "exp_a", 1, "s", "seed", "p", None, "[]", 1.0,
    )
    await store.create_task(
        "exp_a:002-t", "exp_a", 2, "t", "seed", "p", None, "[]", 2.0,
    )
    await store.upsert_run_for_task("r1", "exp_a", "exp_a:001-s", "seed", 0.5, "complete", "t", "m")
    await store.upsert_run_for_task("r2", "exp_a", "exp_a:002-t", "seed", 0.2, "complete", "t", "m")
    await store.set_task_best("exp_a:001-s", "r1", "auto_loss")
    await store.set_task_best("exp_a:002-t", "r2", "auto_loss")
    curve = await store.get_experiment_loss_curve("exp_a")
    assert curve == [
        {"task_number": 1, "task_id": "exp_a:001-s", "best_loss": pytest.approx(0.5)},
        {"task_number": 2, "task_id": "exp_a:002-t", "best_loss": pytest.approx(0.2)},
    ]
