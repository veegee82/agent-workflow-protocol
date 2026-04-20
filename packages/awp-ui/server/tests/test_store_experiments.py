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
