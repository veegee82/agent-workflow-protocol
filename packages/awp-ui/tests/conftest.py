"""Shared fixtures for AWP UI tests."""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from server.services.store import StoreService

FIXTURES_DIR = Path(__file__).parent / "fixtures"
FICTIONAL_RUN_DIR = FIXTURES_DIR / "fictional_run"


# ---------------------------------------------------------------------------
# Event loop
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def event_loop():
    """Create a single event loop for the entire test session."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# ---------------------------------------------------------------------------
# Temp directory
# ---------------------------------------------------------------------------


@pytest.fixture
def temp_dir():
    """Provide a temporary directory that is cleaned up after the test."""
    d = tempfile.mkdtemp(prefix="awp_test_")
    yield Path(d)
    shutil.rmtree(d, ignore_errors=True)


# ---------------------------------------------------------------------------
# Store (standalone, no app dependency)
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def store(temp_dir: Path) -> StoreService:
    """Create and initialise a StoreService with a temp database."""
    db_path = temp_dir / "test.db"
    svc = StoreService(db_path=db_path)
    await svc.init_db()
    yield svc
    await svc.close()


# ---------------------------------------------------------------------------
# FastAPI app + async HTTP client
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def app(temp_dir: Path):
    """Create a test FastAPI app with a temp DB and initialised store."""
    os.environ["AWP_UI_DB_PATH"] = str(temp_dir / "test.db")
    from server.app import create_app, store as app_store, event_bus

    application = create_app()
    # Override the global store's db path and initialise it
    app_store._db_path = str(temp_dir / "test.db")
    await app_store.init_db()
    # Bind event bus to the current loop
    event_bus.bind_loop(asyncio.get_running_loop())
    yield application
    await app_store.close()


@pytest_asyncio.fixture
async def client(app) -> AsyncClient:
    """Async HTTP test client backed by the ASGI app."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# ---------------------------------------------------------------------------
# Fictional run directory (copy to temp)
# ---------------------------------------------------------------------------


@pytest.fixture
def fictional_run_dir(temp_dir: Path) -> Path:
    """Copy the fictional run fixture to a temp directory and return its path."""
    dest = temp_dir / "fictional_run"
    shutil.copytree(FICTIONAL_RUN_DIR, dest)
    return dest


# ---------------------------------------------------------------------------
# Helper: create a run directory programmatically
# ---------------------------------------------------------------------------


def make_run_dir(
    base: Path,
    *,
    task: str = "Test task",
    run_id: str = "test_run_001",
    iterations: list[dict[str, Any]] | None = None,
    completion: dict[str, Any] | None = None,
) -> Path:
    """Build a minimal run directory structure for testing."""
    run_dir = base / "run"
    run_dir.mkdir(parents=True, exist_ok=True)

    manifest = {
        "run_id": run_id,
        "task": task,
        "models": {"manager": "test-model", "worker": "test-model"},
        "budget": {"max_loops": 10, "max_total_tokens": 100000},
    }
    (run_dir / "run_manifest.json").write_text(json.dumps(manifest))

    if iterations:
        for i, it in enumerate(iterations, start=1):
            iter_dir = run_dir / "iterations" / f"{i:03d}"
            iter_dir.mkdir(parents=True, exist_ok=True)

            decision = it.get("decision", {})
            (iter_dir / "manager_decision.json").write_text(json.dumps(decision))

            budget = it.get("budget", {})
            (iter_dir / "budget_snapshot.json").write_text(json.dumps(budget))

            for worker_name, worker_data in it.get("workers", {}).items():
                w_dir = iter_dir / "delegations" / worker_name
                w_dir.mkdir(parents=True, exist_ok=True)

                envelope = worker_data.get("envelope", {})
                (w_dir / "envelope.json").write_text(json.dumps(envelope))

                result = worker_data.get("result", {})
                (w_dir / "result.json").write_text(json.dumps(result))

                tool_calls = worker_data.get("tool_calls")
                if tool_calls is not None:
                    (w_dir / "tool_calls.json").write_text(json.dumps(tool_calls))

    if completion:
        (run_dir / "run_completion.json").write_text(json.dumps(completion))

    return run_dir
