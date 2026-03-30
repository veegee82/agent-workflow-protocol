"""Tests for the SQLite store service."""
from __future__ import annotations

import asyncio

import pytest
import pytest_asyncio

from server.services.store import StoreService


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_save_and_get_run(store: StoreService) -> None:
    await store.save_run(
        run_id="r1",
        task="Hello world",
        model="test-model",
        config={"task": "Hello world", "model": "test-model"},
        status="running",
    )
    row = await store.get_run("r1")
    assert row is not None
    assert row["run_id"] == "r1"
    assert row["task"] == "Hello world"
    assert row["model"] == "test-model"
    assert row["status"] == "running"
    assert row["config"]["task"] == "Hello world"


@pytest.mark.asyncio
async def test_list_runs_ordering(store: StoreService) -> None:
    for i in range(5):
        await store.save_run(
            run_id=f"r{i}",
            task=f"Task {i}",
            model="m",
            config={},
            status="complete",
        )
    rows = await store.list_runs(limit=3)
    assert len(rows) == 3
    # Most recent first (last inserted has latest created_at)
    assert rows[0]["run_id"] == "r4"


@pytest.mark.asyncio
async def test_list_runs_pagination(store: StoreService) -> None:
    for i in range(5):
        await store.save_run(
            run_id=f"r{i}", task=f"T{i}", model="m", config={}, status="complete"
        )
    page1 = await store.list_runs(limit=2, offset=0)
    page2 = await store.list_runs(limit=2, offset=2)
    assert len(page1) == 2
    assert len(page2) == 2
    ids = [r["run_id"] for r in page1 + page2]
    assert len(set(ids)) == 4  # no duplicates


@pytest.mark.asyncio
async def test_update_run(store: StoreService) -> None:
    await store.save_run(run_id="r1", task="T", model="m", config={}, status="running")
    await store.update_run("r1", status="complete", result={"answer": "done"})
    row = await store.get_run("r1")
    assert row["status"] == "complete"
    assert row["result"]["answer"] == "done"


@pytest.mark.asyncio
async def test_delete_run(store: StoreService) -> None:
    await store.save_run(run_id="r1", task="T", model="m", config={}, status="running")
    deleted = await store.delete_run("r1")
    assert deleted is True
    assert await store.get_run("r1") is None


@pytest.mark.asyncio
async def test_delete_nonexistent_run(store: StoreService) -> None:
    deleted = await store.delete_run("nonexistent")
    assert deleted is False


@pytest.mark.asyncio
async def test_get_nonexistent_run(store: StoreService) -> None:
    assert await store.get_run("nope") is None


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_save_and_get_events(store: StoreService) -> None:
    await store.save_run(run_id="r1", task="T", model="m", config={}, status="running")
    await store.save_event("r1", seq=1, event_type="run.start", data={"foo": "bar"})
    await store.save_event("r1", seq=2, event_type="agent.complete", data={"x": 1})

    events = await store.get_events("r1")
    assert len(events) == 2
    assert events[0]["seq"] == 1
    assert events[0]["type"] == "run.start"
    assert events[1]["data"]["x"] == 1


@pytest.mark.asyncio
async def test_get_events_since_seq(store: StoreService) -> None:
    await store.save_run(run_id="r1", task="T", model="m", config={}, status="running")
    for i in range(5):
        await store.save_event("r1", seq=i, event_type="log", data={"i": i})

    events = await store.get_events("r1", since_seq=3)
    assert len(events) == 2
    assert events[0]["seq"] == 3


@pytest.mark.asyncio
async def test_delete_run_cascades_events(store: StoreService) -> None:
    await store.save_run(run_id="r1", task="T", model="m", config={}, status="running")
    await store.save_event("r1", seq=1, event_type="log", data={})
    await store.delete_run("r1")
    events = await store.get_events("r1")
    assert len(events) == 0


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_and_get_session(store: StoreService) -> None:
    await store.create_session("s1", "My Session")
    session = await store.get_session("s1")
    assert session is not None
    assert session["id"] == "s1"
    assert session["title"] == "My Session"
    assert session["run_count"] == 0
    assert session["last_run_status"] is None


@pytest.mark.asyncio
async def test_list_sessions(store: StoreService) -> None:
    await store.create_session("s1", "First")
    await store.create_session("s2", "Second")
    sessions = await store.list_sessions()
    assert len(sessions) == 2


@pytest.mark.asyncio
async def test_update_session_title(store: StoreService) -> None:
    await store.create_session("s1", "Original")
    await store.update_session("s1", title="Renamed")
    session = await store.get_session("s1")
    assert session["title"] == "Renamed"


@pytest.mark.asyncio
async def test_delete_session(store: StoreService) -> None:
    await store.create_session("s1", "Temp")
    deleted = await store.delete_session("s1")
    assert deleted is True
    assert await store.get_session("s1") is None


@pytest.mark.asyncio
async def test_delete_nonexistent_session(store: StoreService) -> None:
    assert await store.delete_session("nope") is False


@pytest.mark.asyncio
async def test_add_run_to_session(store: StoreService) -> None:
    await store.create_session("s1", "Sess")
    await store.save_run(run_id="r1", task="T1", model="m", config={}, status="complete")
    await store.save_run(run_id="r2", task="T2", model="m", config={}, status="running")

    await store.add_run_to_session("s1", "r1")
    await store.add_run_to_session("s1", "r2")

    runs = await store.get_session_runs("s1")
    assert len(runs) == 2
    assert runs[0]["run_id"] == "r1"
    assert runs[1]["run_id"] == "r2"

    session = await store.get_session("s1")
    assert session["run_count"] == 2
    assert session["last_run_status"] == "running"


@pytest.mark.asyncio
async def test_session_history(store: StoreService) -> None:
    await store.create_session("s1", "Sess")
    await store.save_run(run_id="r1", task="What is 2+2?", model="m", config={}, status="complete")
    await store.update_run("r1", result={"answer": "4"})
    await store.add_run_to_session("s1", "r1")

    history = await store.get_session_history("s1")
    assert len(history) == 2
    assert history[0]["role"] == "user"
    assert history[0]["content"] == "What is 2+2?"
    assert history[1]["role"] == "assistant"
    assert "4" in history[1]["content"]


@pytest.mark.asyncio
async def test_session_history_empty(store: StoreService) -> None:
    await store.create_session("s1", "Empty")
    history = await store.get_session_history("s1")
    assert history == []


# ---------------------------------------------------------------------------
# Secrets
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_save_and_get_secret(store: StoreService) -> None:
    await store.save_secret("API_KEY", "sk-test-12345")
    value = await store.get_secret("API_KEY")
    assert value == "sk-test-12345"


@pytest.mark.asyncio
async def test_secret_upsert(store: StoreService) -> None:
    """Saving the same key twice should update the value."""
    await store.save_secret("KEY", "old-value")
    await store.save_secret("KEY", "new-value")
    value = await store.get_secret("KEY")
    assert value == "new-value"


@pytest.mark.asyncio
async def test_list_secrets(store: StoreService) -> None:
    await store.save_secret("A_KEY", "val1")
    await store.save_secret("B_KEY", "val2")
    keys = await store.list_secrets()
    assert "A_KEY" in keys
    assert "B_KEY" in keys


@pytest.mark.asyncio
async def test_list_secrets_metadata(store: StoreService) -> None:
    await store.save_secret("MY_SECRET", "val")
    metadata = await store.list_secrets_metadata()
    assert len(metadata) >= 1
    entry = [m for m in metadata if m["key"] == "MY_SECRET"][0]
    assert "created_at" in entry
    assert "updated_at" in entry


@pytest.mark.asyncio
async def test_delete_secret(store: StoreService) -> None:
    await store.save_secret("TEMP", "val")
    deleted = await store.delete_secret("TEMP")
    assert deleted is True
    assert await store.get_secret("TEMP") is None


@pytest.mark.asyncio
async def test_delete_nonexistent_secret(store: StoreService) -> None:
    assert await store.delete_secret("nope") is False


@pytest.mark.asyncio
async def test_get_nonexistent_secret(store: StoreService) -> None:
    assert await store.get_secret("nope") is None


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_save_and_get_settings(store: StoreService) -> None:
    data = {"model": "test-model", "max_loops": 5}
    await store.save_settings(data)
    loaded = await store.get_settings()
    assert loaded is not None
    assert loaded["model"] == "test-model"
    assert loaded["max_loops"] == 5


@pytest.mark.asyncio
async def test_settings_upsert(store: StoreService) -> None:
    await store.save_settings({"model": "old"})
    await store.save_settings({"model": "new", "verbose": True})
    loaded = await store.get_settings()
    assert loaded["model"] == "new"
    assert loaded["verbose"] is True


@pytest.mark.asyncio
async def test_get_settings_empty(store: StoreService) -> None:
    loaded = await store.get_settings()
    assert loaded is None
