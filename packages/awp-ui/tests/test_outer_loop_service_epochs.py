"""Tests for the outer-loop epochs + artifact-versions endpoints (Phase B3).

These endpoints back the OptimizerPanel's three charts (LossCurve,
ArtifactDeltaTimeline, PerTaskLossBoxplot) and the diff drawer. We cover:

* ``list_suite_epochs`` on an empty DB, a populated DB with two epochs
  (normal + rollback), and an unknown suite.
* ``list_artifact_versions`` in read-only v0 fallback (no DB) and with a
  persisted v1.
* The REST endpoints return 404 on unknown suite / artifact, and degrade
  gracefully when the DB is absent.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from httpx import AsyncClient

pytest.importorskip("awp.outer_loop.store")  # skip if runtime not installed

from awp.outer_loop.store import SqliteArtifactStore  # noqa: E402


def _seed_two_epochs(db_path: Path) -> dict[str, str]:
    """Populate a suite with two epochs: first normal (update), second rollback.

    The shape of ``child_artifacts_json`` mirrors what
    :meth:`awp.outer_loop.runner.SuiteRunner.optimize` emits in A3 — a
    richer ``{"artifacts": {...}, "events": [...]}`` record, not the
    legacy flat map.
    """
    store = SqliteArtifactStore(str(db_path))
    suite_id = "suite-xyz"
    epoch_1 = "epoch-1"
    epoch_2 = "epoch-2"

    store.upsert_task_suite(
        suite_id=suite_id,
        name="research",
        tasks_json=json.dumps([]),
        baseline_artifacts_json=json.dumps({}),
        created_at="2026-04-18T10:00:00Z",
    )

    # -- Epoch 1: normal update ----------------------------------------------
    store.insert_epoch(
        epoch_id=epoch_1,
        suite_id=suite_id,
        epoch_num=1,
        started_at="2026-04-18T10:01:00Z",
        parent_artifacts_json=json.dumps(
            {"worker_pitfalls": 0, "critique_rubric": 0}
        ),
    )
    store.finalize_epoch(
        epoch_id=epoch_1,
        completed_at="2026-04-18T10:05:00Z",
        mean_loss=0.4,
        child_artifacts_json=json.dumps(
            {
                "artifacts": {"worker_pitfalls": 1, "critique_rubric": 0},
                "events": [
                    {
                        "type": "update",
                        "artifact": "worker_pitfalls",
                        "from_version": 0,
                        "to_version": 1,
                        "rationale": "Add retry guidance.",
                        "expected_loss_reduction": 0.12,
                        "confidence": 0.8,
                        "learning_rate": 0.5,
                    }
                ],
            }
        ),
    )
    store.insert_epoch_run(
        epoch_id=epoch_1,
        run_id="run-e1-a",
        task_name="task_a",
        loss=0.3,
        scores_json=json.dumps({"eval": 0.7}),
    )
    store.insert_epoch_run(
        epoch_id=epoch_1,
        run_id="run-e1-b",
        task_name="task_b",
        loss=0.5,
        scores_json=json.dumps({"eval": 0.6}),
    )

    # -- Epoch 2: regression → rollback --------------------------------------
    store.insert_epoch(
        epoch_id=epoch_2,
        suite_id=suite_id,
        epoch_num=2,
        started_at="2026-04-18T10:06:00Z",
        parent_artifacts_json=json.dumps(
            {"worker_pitfalls": 1, "critique_rubric": 0}
        ),
    )
    store.finalize_epoch(
        epoch_id=epoch_2,
        completed_at="2026-04-18T10:10:00Z",
        mean_loss=0.55,  # regression vs epoch 1
        child_artifacts_json=json.dumps(
            {
                "artifacts": {"worker_pitfalls": 0, "critique_rubric": 0},
                "events": [
                    {
                        "type": "rollback",
                        "artifact": "worker_pitfalls",
                        "from_version": 1,
                        "to_version": 0,
                        "reason": "mean_loss_regression",
                        "mean_loss_prev": 0.4,
                        "mean_loss_current": 0.55,
                        "new_learning_rate": 0.25,
                    }
                ],
            }
        ),
    )
    store.insert_epoch_run(
        epoch_id=epoch_2,
        run_id="run-e2-a",
        task_name="task_a",
        loss=0.5,
        scores_json=json.dumps({"eval": 0.5}),
    )
    store.insert_epoch_run(
        epoch_id=epoch_2,
        run_id="run-e2-b",
        task_name="task_b",
        loss=0.6,
        scores_json=json.dumps({"eval": 0.4}),
    )
    store.close()
    return {"suite_id": suite_id, "epoch_1": epoch_1, "epoch_2": epoch_2}


# ---------------------------------------------------------------------------
# Service-level tests
# ---------------------------------------------------------------------------


def test_list_suite_epochs_returns_none_when_db_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Absent DB must degrade to None so the REST layer returns 404."""
    monkeypatch.setenv("AWP_OUTER_LOOP_DB", str(tmp_path / "missing.db"))
    from server.services.outer_loop_service import list_suite_epochs

    assert list_suite_epochs("anything") is None


def test_list_suite_epochs_unknown_suite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = tmp_path / "outer_loop.db"
    _seed_two_epochs(db)
    monkeypatch.setenv("AWP_OUTER_LOOP_DB", str(db))
    from server.services.outer_loop_service import list_suite_epochs

    assert list_suite_epochs("no-such-suite") is None


def test_list_suite_epochs_populated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = tmp_path / "outer_loop.db"
    ids = _seed_two_epochs(db)
    monkeypatch.setenv("AWP_OUTER_LOOP_DB", str(db))
    from server.services.outer_loop_service import list_suite_epochs

    epochs = list_suite_epochs(ids["suite_id"])
    assert epochs is not None
    assert len(epochs) == 2

    e1, e2 = epochs
    # Ordering: epoch_num ASC
    assert e1["epoch_num"] == 1
    assert e2["epoch_num"] == 2

    # Richer payload is unwrapped — artifact map is flat.
    assert e1["child_artifacts"] == {"worker_pitfalls": 1, "critique_rubric": 0}
    assert e1["parent_artifacts"] == {"worker_pitfalls": 0, "critique_rubric": 0}
    assert e1["mean_loss"] == pytest.approx(0.4)

    # Epoch 1 has an update event.
    assert len(e1["events"]) == 1
    assert e1["events"][0]["type"] == "update"
    assert e1["events"][0]["artifact"] == "worker_pitfalls"
    assert e1["events"][0]["from_version"] == 0
    assert e1["events"][0]["to_version"] == 1

    # Per-task losses come through with their scores.
    assert len(e1["per_task_losses"]) == 2
    assert {p["task_name"] for p in e1["per_task_losses"]} == {"task_a", "task_b"}
    loss_by_task = {p["task_name"]: p["loss"] for p in e1["per_task_losses"]}
    assert loss_by_task["task_a"] == pytest.approx(0.3)

    # Epoch 2 is a rollback.
    assert len(e2["events"]) == 1
    assert e2["events"][0]["type"] == "rollback"
    assert e2["events"][0]["from_version"] == 1
    assert e2["events"][0]["to_version"] == 0
    assert e2["mean_loss"] == pytest.approx(0.55)


def test_list_artifact_versions_unknown_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AWP_OUTER_LOOP_DB", str(tmp_path / "missing.db"))
    from server.services.outer_loop_service import list_artifact_versions

    assert list_artifact_versions("not_a_real_artifact") is None


def test_list_artifact_versions_v0_only_when_db_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With no DB, only the synthetic v0 default is served — and it is active."""
    monkeypatch.setenv("AWP_OUTER_LOOP_DB", str(tmp_path / "missing.db"))
    from server.services.outer_loop_service import list_artifact_versions

    versions = list_artifact_versions("worker_pitfalls")
    assert versions is not None
    assert [v["version"] for v in versions] == [0]
    assert versions[0]["is_active"] is True
    assert versions[0]["content"]  # non-empty default


def test_list_artifact_versions_with_db_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A persisted v1 shows up alongside v0."""
    db = tmp_path / "outer_loop.db"
    monkeypatch.setenv("AWP_OUTER_LOOP_DB", str(db))

    # Persist v1 via the registry so we go through the same write path the
    # runtime uses.
    from awp.outer_loop.artifacts import ArtifactRegistry

    registry = ArtifactRegistry(db_path=str(db))
    registry.put_version(
        "worker_pitfalls", "UPDATED CONTENT", parent_version=0, epoch_id="e-1"
    )
    registry.set_active("worker_pitfalls", 1)

    from server.services.outer_loop_service import list_artifact_versions

    versions = list_artifact_versions("worker_pitfalls")
    assert versions is not None
    assert [v["version"] for v in versions] == [0, 1]
    assert versions[0]["is_active"] is False
    assert versions[1]["is_active"] is True
    assert versions[1]["content"] == "UPDATED CONTENT"


# ---------------------------------------------------------------------------
# REST endpoint tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_suite_epochs_endpoint_404_when_db_missing(
    client: AsyncClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AWP_OUTER_LOOP_DB", str(tmp_path / "missing.db"))
    resp = await client.get("/api/suites/any/epochs")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_suite_epochs_endpoint_populated(
    client: AsyncClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = tmp_path / "outer_loop.db"
    ids = _seed_two_epochs(db)
    monkeypatch.setenv("AWP_OUTER_LOOP_DB", str(db))

    resp = await client.get(f"/api/suites/{ids['suite_id']}/epochs")
    assert resp.status_code == 200
    payload = resp.json()
    assert "epochs" in payload
    assert len(payload["epochs"]) == 2
    first = payload["epochs"][0]
    assert first["mean_loss"] == pytest.approx(0.4)
    assert first["events"][0]["type"] == "update"
    assert len(first["per_task_losses"]) == 2


@pytest.mark.asyncio
async def test_artifact_versions_endpoint_unknown_name(
    client: AsyncClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AWP_OUTER_LOOP_DB", str(tmp_path / "missing.db"))
    resp = await client.get("/api/artifacts/not_real/versions")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_artifact_versions_endpoint_v0_fallback(
    client: AsyncClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AWP_OUTER_LOOP_DB", str(tmp_path / "missing.db"))
    resp = await client.get("/api/artifacts/worker_pitfalls/versions")
    assert resp.status_code == 200
    versions = resp.json()["versions"]
    assert [v["version"] for v in versions] == [0]
    assert versions[0]["is_active"] is True
