"""Plan 5 — backend route + store tests for experiment/task hierarchy."""

from __future__ import annotations

from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

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


# --- Route-level tests ---


@pytest_asyncio.fixture
async def client(tmp_path: Path, monkeypatch) -> AsyncClient:
    """FastAPI test client backed by an isolated tmp_path DB."""
    monkeypatch.setenv("AWP_UI_DB_PATH", str(tmp_path / "test.db"))
    # Force the store + app singletons to rebuild with this path.
    from server import app as app_mod
    import importlib
    importlib.reload(app_mod)
    # Ensure DB is initialized
    await app_mod.store.init_db()
    transport = ASGITransport(app=app_mod.app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_list_experiments_route(client: AsyncClient) -> None:
    r = await client.post("/api/experiments", json={"name": "E", "goal": "G"})
    assert r.status_code == 200
    exp = r.json()
    r = await client.get("/api/experiments")
    assert r.status_code == 200
    assert any(e["id"] == exp["id"] for e in r.json())


@pytest.mark.asyncio
async def test_experiment_detail_includes_tasks(client: AsyncClient) -> None:
    r = await client.post("/api/experiments", json={"name": "E", "goal": "G"})
    exp_id = r.json()["id"]
    r = await client.post(
        f"/api/experiments/{exp_id}/tasks",
        json={"user_prompt": "Write a paper"},
    )
    assert r.status_code == 200
    r = await client.get(f"/api/experiments/{exp_id}")
    assert r.status_code == 200
    detail = r.json()
    assert detail["id"] == exp_id
    assert len(detail["tasks"]) == 1
    assert detail["tasks"][0]["mode"] == "seed"


@pytest.mark.asyncio
async def test_set_best_route(client: AsyncClient) -> None:
    r = await client.post("/api/experiments", json={"name": "E"})
    exp_id = r.json()["id"]
    r = await client.post(
        f"/api/experiments/{exp_id}/tasks", json={"user_prompt": "t"},
    )
    task_id = r.json()["id"]
    # Seed a run row + call set-best
    from server.services.store import StoreService
    import os
    s = StoreService(db_path=os.environ["AWP_UI_DB_PATH"])
    await s.init_db()
    await s.upsert_run_for_task("rX", exp_id, task_id, "seed", 0.4, "complete", "t", "m")
    await s.close()
    r = await client.post(f"/api/tasks/{task_id}/best", json={"run_id": "rX"})
    assert r.status_code == 200
    assert r.json()["best_run_id"] == "rX"


@pytest.mark.asyncio
async def test_experiment_loss_curve_route(client: AsyncClient) -> None:
    r = await client.post("/api/experiments", json={"name": "E"})
    exp_id = r.json()["id"]
    r = await client.get(f"/api/experiments/{exp_id}/loss-curve")
    assert r.status_code == 200
    # Empty curve for fresh experiment
    assert r.json() == []


@pytest.mark.asyncio
async def test_task_loss_series_route(client: AsyncClient) -> None:
    r = await client.post("/api/experiments", json={"name": "E"})
    exp_id = r.json()["id"]
    r = await client.post(
        f"/api/experiments/{exp_id}/tasks", json={"user_prompt": "t"},
    )
    task_id = r.json()["id"]
    r = await client.get(f"/api/tasks/{task_id}/loss-series")
    assert r.status_code == 200
    assert r.json() == []
