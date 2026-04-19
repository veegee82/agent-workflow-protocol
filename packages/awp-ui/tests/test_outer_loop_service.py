"""Tests for the outer-loop UI service + REST endpoints.

The service is the read-only bridge from the UI to the outer-loop DB
(``~/.awp/outer_loop.db``). These tests populate a temp DB via
:class:`awp.outer_loop.store.SqliteArtifactStore`, point
``$AWP_OUTER_LOOP_DB`` at it, and assert:

* ``get_run_epoch`` returns ``None`` for unknown runs and a populated dict
  for a run that was registered in ``epoch_runs``.
* ``list_suites`` reflects the rows in ``task_suites``.
* ``get_suite_graph_runs`` returns runs ordered by ``(epoch_num, run_id)``.
* The three REST endpoints degrade gracefully when no DB exists and
  mirror the service output when it does.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from httpx import AsyncClient

pytest.importorskip("awp.outer_loop.store")  # skip if runtime not installed

from awp.outer_loop.store import SqliteArtifactStore  # noqa: E402


def _seed_db(db_path: Path) -> dict[str, str]:
    """Populate the outer-loop DB with a single suite / epoch / run."""
    store = SqliteArtifactStore(str(db_path))
    suite_id = "suite-abc"
    epoch_id = "epoch-xyz"
    store.upsert_task_suite(
        suite_id=suite_id,
        name="codegen",
        tasks_json=json.dumps([]),
        baseline_artifacts_json=json.dumps({}),
        created_at="2026-04-18T12:00:00Z",
    )
    store.insert_epoch(
        epoch_id=epoch_id,
        suite_id=suite_id,
        epoch_num=1,
        started_at="2026-04-18T12:00:01Z",
        parent_artifacts_json=json.dumps(
            {"worker_pitfalls": 0, "critique_rubric": 0}
        ),
    )
    store.finalize_epoch(
        epoch_id=epoch_id,
        completed_at="2026-04-18T12:05:00Z",
        mean_loss=0.25,
        child_artifacts_json=json.dumps(
            {"worker_pitfalls": 2, "critique_rubric": 1}
        ),
    )
    store.insert_epoch_run(
        epoch_id=epoch_id,
        run_id="run-1",
        task_name="task_a",
        loss=0.2,
        scores_json=json.dumps({}),
    )
    store.insert_epoch_run(
        epoch_id=epoch_id,
        run_id="run-2",
        task_name="task_b",
        loss=0.3,
        scores_json=json.dumps({}),
    )
    store.close()
    return {"suite_id": suite_id, "epoch_id": epoch_id}


# ---------------------------------------------------------------------------
# Service-level tests (no HTTP layer)
# ---------------------------------------------------------------------------


def test_get_run_epoch_returns_none_when_db_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Absent DB must degrade to None rather than raising."""
    monkeypatch.setenv("AWP_OUTER_LOOP_DB", str(tmp_path / "nonexistent.db"))
    from server.services.outer_loop_service import get_run_epoch

    assert get_run_epoch("any-run") is None


def test_list_suites_empty_when_db_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AWP_OUTER_LOOP_DB", str(tmp_path / "nonexistent.db"))
    from server.services.outer_loop_service import list_suites

    assert list_suites() == []


def test_get_run_epoch_populated_db(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = tmp_path / "outer_loop.db"
    ids = _seed_db(db)
    monkeypatch.setenv("AWP_OUTER_LOOP_DB", str(db))
    from server.services.outer_loop_service import get_run_epoch

    ctx = get_run_epoch("run-1")
    assert ctx is not None
    assert ctx["epoch_id"] == ids["epoch_id"]
    assert ctx["suite_id"] == ids["suite_id"]
    assert ctx["epoch_num"] == 1
    assert ctx["parent_artifacts"] == {"worker_pitfalls": 0, "critique_rubric": 0}
    assert ctx["child_artifacts"] == {"worker_pitfalls": 2, "critique_rubric": 1}
    assert ctx["mean_loss"] == pytest.approx(0.25)


def test_get_run_epoch_unknown_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = tmp_path / "outer_loop.db"
    _seed_db(db)
    monkeypatch.setenv("AWP_OUTER_LOOP_DB", str(db))
    from server.services.outer_loop_service import get_run_epoch

    assert get_run_epoch("run-that-does-not-exist") is None


def test_list_suites_populated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = tmp_path / "outer_loop.db"
    _seed_db(db)
    monkeypatch.setenv("AWP_OUTER_LOOP_DB", str(db))
    from server.services.outer_loop_service import list_suites

    suites = list_suites()
    assert len(suites) == 1
    summary = suites[0]
    assert summary["id"] == "suite-abc"
    assert summary["name"] == "codegen"
    assert summary["epoch_count"] == 1
    assert summary["latest_epoch"] == 1
    assert summary["latest_mean_loss"] == pytest.approx(0.25)


def test_get_suite_graph_runs_ordered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = tmp_path / "outer_loop.db"
    _seed_db(db)
    monkeypatch.setenv("AWP_OUTER_LOOP_DB", str(db))
    from server.services.outer_loop_service import get_suite_graph_runs

    rows = get_suite_graph_runs("suite-abc")
    assert [r["run_id"] for r in rows] == ["run-1", "run-2"]
    assert rows[0]["epoch_num"] == 1
    assert rows[0]["parent_artifacts"] == {"worker_pitfalls": 0, "critique_rubric": 0}
    assert rows[0]["child_artifacts"] == {"worker_pitfalls": 2, "critique_rubric": 1}
    assert rows[0]["loss"] == pytest.approx(0.2)
    assert rows[1]["loss"] == pytest.approx(0.3)


def test_get_suite_graph_runs_unknown_suite_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = tmp_path / "outer_loop.db"
    _seed_db(db)
    monkeypatch.setenv("AWP_OUTER_LOOP_DB", str(db))
    from server.services.outer_loop_service import get_suite_graph_runs

    assert get_suite_graph_runs("no-such-suite") == []


# ---------------------------------------------------------------------------
# REST endpoint tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_epoch_endpoint_unknown_run_returns_null(
    client: AsyncClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AWP_OUTER_LOOP_DB", str(tmp_path / "missing.db"))
    resp = await client.get("/api/runs/does-not-exist/epoch")
    assert resp.status_code == 200
    assert resp.json() is None


@pytest.mark.asyncio
async def test_epoch_endpoint_populated(
    client: AsyncClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = tmp_path / "outer_loop.db"
    _seed_db(db)
    monkeypatch.setenv("AWP_OUTER_LOOP_DB", str(db))

    resp = await client.get("/api/runs/run-1/epoch")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload is not None
    assert payload["epoch_num"] == 1
    assert payload["child_artifacts"] == {"worker_pitfalls": 2, "critique_rubric": 1}


@pytest.mark.asyncio
async def test_suites_endpoint_empty_and_populated(
    client: AsyncClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Empty DB → empty list
    monkeypatch.setenv("AWP_OUTER_LOOP_DB", str(tmp_path / "missing.db"))
    resp = await client.get("/api/suites")
    assert resp.status_code == 200
    assert resp.json() == {"suites": []}

    # Populated DB → one suite
    db = tmp_path / "outer_loop.db"
    _seed_db(db)
    monkeypatch.setenv("AWP_OUTER_LOOP_DB", str(db))
    resp = await client.get("/api/suites")
    assert resp.status_code == 200
    suites = resp.json()["suites"]
    assert len(suites) == 1
    assert suites[0]["name"] == "codegen"


@pytest.mark.asyncio
async def test_suite_graph_endpoint_missing_suite(
    client: AsyncClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AWP_OUTER_LOOP_DB", str(tmp_path / "missing.db"))
    resp = await client.get("/api/suites/no-such-suite/graph")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_suite_graph_endpoint_empty_suite_no_runs(
    client: AsyncClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A suite with no epoch_runs yields an empty nodes/edges graph."""
    db = tmp_path / "outer_loop.db"
    store = SqliteArtifactStore(str(db))
    store.upsert_task_suite(
        suite_id="empty-suite",
        name="empty",
        tasks_json=json.dumps([]),
        baseline_artifacts_json=json.dumps({}),
        created_at="2026-04-18T12:00:00Z",
    )
    store.close()
    monkeypatch.setenv("AWP_OUTER_LOOP_DB", str(db))

    resp = await client.get("/api/suites/empty-suite/graph")
    assert resp.status_code == 200
    body = resp.json()
    assert body["nodes"] == []
    assert body["edges"] == []
    assert body["stats"]["suite_name"] == "empty"
