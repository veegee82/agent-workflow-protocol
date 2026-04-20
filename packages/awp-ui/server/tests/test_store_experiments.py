"""Tests for the experiments + tasks tables added by the hierarchy plan."""

from __future__ import annotations

from pathlib import Path

import pytest

from server.services.store import StoreService


@pytest.fixture
async def store(tmp_path: Path) -> StoreService:
    s = StoreService(db_path=tmp_path / "test.db")
    await s.init_db()
    yield s
    await s.close()


@pytest.mark.asyncio
async def test_experiments_table_created(store: StoreService) -> None:
    cur = await store.db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='experiments'"
    )
    row = await cur.fetchone()
    assert row is not None


@pytest.mark.asyncio
async def test_tasks_table_created(store: StoreService) -> None:
    cur = await store.db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='tasks'"
    )
    row = await cur.fetchone()
    assert row is not None


@pytest.mark.asyncio
async def test_runs_has_hierarchy_columns(store: StoreService) -> None:
    cur = await store.db.execute("PRAGMA table_info(runs)")
    cols = {row["name"] for row in await cur.fetchall()}
    assert "experiment_id" in cols
    assert "task_id" in cols
    assert "run_role" in cols
    assert "parent_run_id" in cols
    assert "loss" in cols


@pytest.mark.asyncio
async def test_create_and_get_experiment(store: StoreService) -> None:
    await store.create_experiment(
        experiment_id="exp_aaaaaaaa",
        name="E",
        goal="G",
        base_dir="/tmp/awp-experiments/exp_aaaaaaaa",
        created_at=1_700_000_000.0,
    )
    row = await store.get_experiment("exp_aaaaaaaa")
    assert row["id"] == "exp_aaaaaaaa"
    assert row["name"] == "E"
    assert row["goal"] == "G"
    assert row["archived_at"] is None


@pytest.mark.asyncio
async def test_list_experiments_newest_first(store: StoreService) -> None:
    await store.create_experiment("exp_aaaaaaaa", "First", "", "/tmp/a", 1_000.0)
    await store.create_experiment("exp_bbbbbbbb", "Second", "", "/tmp/b", 2_000.0)
    rows = await store.list_experiments()
    assert [r["id"] for r in rows] == ["exp_bbbbbbbb", "exp_aaaaaaaa"]


@pytest.mark.asyncio
async def test_delete_experiment_cascades(store: StoreService) -> None:
    await store.create_experiment("exp_aaaaaaaa", "E", "", "/tmp/a", 1.0)
    await store.create_task(
        task_id_key="exp_aaaaaaaa:001-draft",
        experiment_id="exp_aaaaaaaa",
        task_number=1,
        slug="draft",
        mode="seed",
        user_prompt="p",
        user_feedback=None,
        inputs_json="[]",
        created_at=1.0,
    )
    await store.delete_experiment("exp_aaaaaaaa")
    assert await store.get_experiment("exp_aaaaaaaa") is None
    cur = await store.db.execute("SELECT COUNT(*) AS c FROM tasks")
    row = await cur.fetchone()
    assert row["c"] == 0


@pytest.mark.asyncio
async def test_create_and_get_task(store: StoreService) -> None:
    await store.create_experiment("exp_aaaaaaaa", "E", "", "/tmp/a", 1.0)
    await store.create_task(
        task_id_key="exp_aaaaaaaa:001-draft",
        experiment_id="exp_aaaaaaaa",
        task_number=1,
        slug="draft",
        mode="seed",
        user_prompt="p",
        user_feedback=None,
        inputs_json="[]",
        created_at=2.0,
    )
    row = await store.get_task("exp_aaaaaaaa:001-draft")
    assert row["id"] == "exp_aaaaaaaa:001-draft"
    assert row["mode"] == "seed"
    assert row["user_prompt"] == "p"


@pytest.mark.asyncio
async def test_list_tasks_for_experiment(store: StoreService) -> None:
    await store.create_experiment("exp_aaaaaaaa", "E", "", "/tmp/a", 1.0)
    await store.create_task(
        "exp_aaaaaaaa:001-a", "exp_aaaaaaaa", 1, "a", "seed", "p1", None, "[]", 10.0
    )
    await store.create_task(
        "exp_aaaaaaaa:002-b",
        "exp_aaaaaaaa",
        2,
        "b",
        "continuation",
        None,
        "fb",
        '[{"from_task":"001-a","role":"primary","bundle":"BEST/"}]',
        20.0,
    )
    rows = await store.list_tasks("exp_aaaaaaaa")
    assert [r["id"] for r in rows] == [
        "exp_aaaaaaaa:001-a",
        "exp_aaaaaaaa:002-b",
    ]


@pytest.mark.asyncio
async def test_unique_task_number_per_experiment(store: StoreService) -> None:
    await store.create_experiment("exp_aaaaaaaa", "E", "", "/tmp/a", 1.0)
    await store.create_task(
        "exp_aaaaaaaa:001-a", "exp_aaaaaaaa", 1, "a", "seed", "p", None, "[]", 1.0
    )
    with pytest.raises(Exception):
        await store.create_task(
            "exp_aaaaaaaa:001-b",
            "exp_aaaaaaaa",
            1,
            "b",
            "seed",
            "p",
            None,
            "[]",
            2.0,
        )


@pytest.mark.asyncio
async def test_delete_task(store: StoreService) -> None:
    await store.create_experiment("exp_aaaaaaaa", "E", "", "/tmp/a", 1.0)
    await store.create_task(
        "exp_aaaaaaaa:001-a", "exp_aaaaaaaa", 1, "a", "seed", "p", None, "[]", 1.0
    )
    await store.delete_task("exp_aaaaaaaa:001-a")
    assert await store.get_task("exp_aaaaaaaa:001-a") is None
