"""Tests for the REST API endpoints.

All tests mock the runner service to avoid real LLM calls.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import pytest_asyncio
from httpx import AsyncClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_MOCK_RUNNER = MagicMock()
_MOCK_RUNNER.start_run.return_value = "mock_run_id"
_MOCK_RUNNER.stop_run.return_value = False  # default: run not found


def _run_config(task: str = "Test task", model: str = "test-model") -> dict:
    return {"task": task, "model": model}


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_health(client: AsyncClient) -> None:
    resp = await client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_run(client: AsyncClient) -> None:
    with patch("server.services.runner_service.runner_service", _MOCK_RUNNER):
        resp = await client.post("/api/runs", json=_run_config())
    assert resp.status_code == 200
    data = resp.json()
    assert "run_id" in data
    assert data["status"] == "running"


@pytest.mark.asyncio
async def test_list_runs(client: AsyncClient) -> None:
    # Create a run first
    with patch("server.services.runner_service.runner_service", _MOCK_RUNNER):
        await client.post("/api/runs", json=_run_config("List test"))
    resp = await client.get("/api/runs")
    assert resp.status_code == 200
    data = resp.json()
    assert "runs" in data
    assert len(data["runs"]) >= 1


@pytest.mark.asyncio
async def test_list_runs_pagination(client: AsyncClient) -> None:
    with patch("server.services.runner_service.runner_service", _MOCK_RUNNER):
        for i in range(3):
            await client.post("/api/runs", json=_run_config(f"Paginated {i}"))
    resp = await client.get("/api/runs", params={"limit": 2, "offset": 0})
    assert resp.status_code == 200
    assert len(resp.json()["runs"]) == 2


@pytest.mark.asyncio
async def test_get_run(client: AsyncClient) -> None:
    with patch("server.services.runner_service.runner_service", _MOCK_RUNNER):
        create_resp = await client.post("/api/runs", json=_run_config("Get test"))
    run_id = create_resp.json()["run_id"]

    resp = await client.get(f"/api/runs/{run_id}")
    assert resp.status_code == 200
    detail = resp.json()
    assert detail["run_id"] == run_id
    assert detail["task"] == "Get test"


@pytest.mark.asyncio
async def test_get_run_not_found(client: AsyncClient) -> None:
    resp = await client.get("/api/runs/nonexistent")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_run(client: AsyncClient) -> None:
    with patch("server.services.runner_service.runner_service", _MOCK_RUNNER):
        create_resp = await client.post("/api/runs", json=_run_config("Delete me"))
    run_id = create_resp.json()["run_id"]

    resp = await client.delete(f"/api/runs/{run_id}")
    assert resp.status_code == 200
    assert resp.json()["status"] == "deleted"

    # Verify it is gone
    resp = await client.get(f"/api/runs/{run_id}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_run_not_found(client: AsyncClient) -> None:
    resp = await client.delete("/api/runs/nonexistent")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_run_events(client: AsyncClient) -> None:
    with patch("server.services.runner_service.runner_service", _MOCK_RUNNER):
        create_resp = await client.post("/api/runs", json=_run_config("Events test"))
    run_id = create_resp.json()["run_id"]

    resp = await client.get(f"/api/runs/{run_id}/events")
    assert resp.status_code == 200
    assert "events" in resp.json()


@pytest.mark.asyncio
async def test_get_run_graph_empty(client: AsyncClient) -> None:
    """Run without a workspace returns an empty graph."""
    with patch("server.services.runner_service.runner_service", _MOCK_RUNNER):
        create_resp = await client.post("/api/runs", json=_run_config("Graph test"))
    run_id = create_resp.json()["run_id"]

    resp = await client.get(f"/api/runs/{run_id}/graph")
    assert resp.status_code == 200
    graph = resp.json()
    assert graph["nodes"] == []
    assert graph["edges"] == []


@pytest.mark.asyncio
async def test_stop_run_not_found(client: AsyncClient) -> None:
    with patch("server.services.runner_service.runner_service", _MOCK_RUNNER):
        resp = await client.post("/api/runs/nonexistent/stop")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# File upload
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upload_csv(client: AsyncClient) -> None:
    content = b"col1,col2\na,1\nb,2"
    resp = await client.post(
        "/api/upload",
        files=[("files", ("data.csv", content, "text/csv"))],
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["paths"]) == 1
    assert data["paths"][0].endswith("data.csv")


@pytest.mark.asyncio
async def test_upload_json(client: AsyncClient) -> None:
    content = b'{"key": "value"}'
    resp = await client.post(
        "/api/upload",
        files=[("files", ("config.json", content, "application/json"))],
    )
    assert resp.status_code == 200
    assert len(resp.json()["paths"]) == 1


@pytest.mark.asyncio
async def test_upload_multiple_files(client: AsyncClient) -> None:
    files = [
        ("files", ("a.txt", b"hello", "text/plain")),
        ("files", ("b.txt", b"world", "text/plain")),
        ("files", ("c.png", b"\x89PNG\r\n", "image/png")),
    ]
    resp = await client.post("/api/upload", files=files)
    assert resp.status_code == 200
    assert len(resp.json()["paths"]) == 3


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_settings(client: AsyncClient) -> None:
    resp = await client.get("/api/settings")
    assert resp.status_code == 200
    data = resp.json()
    assert "model" in data
    assert "max_loops" in data


@pytest.mark.asyncio
async def test_update_settings(client: AsyncClient) -> None:
    resp = await client.post("/api/settings", json={"max_loops": 42})
    assert resp.status_code == 200
    assert resp.json()["max_loops"] == 42


@pytest.mark.asyncio
async def test_update_settings_partial(client: AsyncClient) -> None:
    """Updating one field should not reset others."""
    resp = await client.post("/api/settings", json={"verbose": True})
    assert resp.status_code == 200
    data = resp.json()
    assert data["verbose"] is True
    assert "model" in data  # other fields preserved


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_session(client: AsyncClient) -> None:
    resp = await client.post("/api/sessions", json={"title": "Test Session"})
    assert resp.status_code == 200
    data = resp.json()
    assert "id" in data
    assert data["title"] == "Test Session"


@pytest.mark.asyncio
async def test_list_sessions(client: AsyncClient) -> None:
    await client.post("/api/sessions", json={"title": "S1"})
    await client.post("/api/sessions", json={"title": "S2"})
    resp = await client.get("/api/sessions")
    assert resp.status_code == 200
    assert len(resp.json()["sessions"]) >= 2


@pytest.mark.asyncio
async def test_get_session(client: AsyncClient) -> None:
    create_resp = await client.post("/api/sessions", json={"title": "Detail"})
    sid = create_resp.json()["id"]
    resp = await client.get(f"/api/sessions/{sid}")
    assert resp.status_code == 200
    assert resp.json()["title"] == "Detail"


@pytest.mark.asyncio
async def test_get_session_not_found(client: AsyncClient) -> None:
    resp = await client.get("/api/sessions/nonexistent")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_session(client: AsyncClient) -> None:
    create_resp = await client.post("/api/sessions", json={"title": "Delete me"})
    sid = create_resp.json()["id"]
    resp = await client.delete(f"/api/sessions/{sid}")
    assert resp.status_code == 200
    assert resp.json()["status"] == "deleted"
    assert (await client.get(f"/api/sessions/{sid}")).status_code == 404


@pytest.mark.asyncio
async def test_delete_session_not_found(client: AsyncClient) -> None:
    resp = await client.delete("/api/sessions/nonexistent")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_session_history_empty(client: AsyncClient) -> None:
    create_resp = await client.post("/api/sessions", json={"title": "Empty"})
    sid = create_resp.json()["id"]
    resp = await client.get(f"/api/sessions/{sid}/history")
    assert resp.status_code == 200
    assert resp.json()["history"] == []


@pytest.mark.asyncio
async def test_session_history_not_found(client: AsyncClient) -> None:
    resp = await client.get("/api/sessions/nonexistent/history")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Secrets
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_and_list_secrets(client: AsyncClient) -> None:
    resp = await client.post("/api/secrets", json={"key": "MY_KEY", "value": "secret123"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "saved"

    resp = await client.get("/api/secrets")
    assert resp.status_code == 200
    keys = [s["key"] for s in resp.json()["secrets"]]
    assert "MY_KEY" in keys


@pytest.mark.asyncio
async def test_delete_secret(client: AsyncClient) -> None:
    await client.post("/api/secrets", json={"key": "DEL_KEY", "value": "val"})
    resp = await client.delete("/api/secrets/DEL_KEY")
    assert resp.status_code == 200
    assert resp.json()["status"] == "deleted"


@pytest.mark.asyncio
async def test_delete_secret_not_found(client: AsyncClient) -> None:
    resp = await client.delete("/api/secrets/nonexistent")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Tools / Available
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_available_tools(client: AsyncClient) -> None:
    resp = await client.get("/api/tools/available")
    assert resp.status_code == 200
    tools = resp.json()["tools"]
    names = [t["name"] for t in tools]
    assert "code.execute" in names
    assert "file.read" in names


# ---------------------------------------------------------------------------
# Create run with session_id
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_run_with_session(client: AsyncClient) -> None:
    sess_resp = await client.post("/api/sessions", json={"title": "Run Session"})
    sid = sess_resp.json()["id"]

    with patch("server.services.runner_service.runner_service", _MOCK_RUNNER):
        run_resp = await client.post(
            "/api/runs",
            json=_run_config("Session run"),
            params={"session_id": sid},
        )
    assert run_resp.status_code == 200
    assert run_resp.json()["session_id"] == sid

    # The run should appear in the session
    detail = (await client.get(f"/api/sessions/{sid}")).json()
    assert len(detail["runs"]) == 1


# ---------------------------------------------------------------------------
# Artifact isolation between runs in the same experiment
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_artifact_isolation_between_runs(client: AsyncClient, temp_dir: Path) -> None:
    """Each run should only see its own output files, not files from other runs."""
    from server.app import store

    # Simulate experiment directory structure (as the DelegationLoopRunner creates it)
    experiment_dir = temp_dir / "experiment"
    output_root = experiment_dir / "output"

    # Run 1: internal run_id "2026-01-01_10-00-00_aaa11111"
    run1_internal = "2026-01-01_10-00-00_aaa11111"
    run1_output = output_root / run1_internal
    run1_output.mkdir(parents=True)
    (run1_output / "run1_chart.png").write_bytes(b"\x89PNG")
    (run1_output / "run1_results.csv").write_text("a,b\n1,2")

    # Run 2: internal run_id "2026-01-01_11-00-00_bbb22222"
    run2_internal = "2026-01-01_11-00-00_bbb22222"
    run2_output = output_root / run2_internal
    run2_output.mkdir(parents=True)
    (run2_output / "run2_report.json").write_text('{"x": 1}')
    (run2_output / "run2_plot.png").write_bytes(b"\x89PNG")

    # Create two DB runs with result metadata pointing to the correct dirs
    run1_id = "ui_run_1_aaaa"
    run2_id = "ui_run_2_bbbb"

    await store.save_run(
        run_id=run1_id,
        task="Task 1",
        model="test",
        config={"output_dir": str(experiment_dir)},
        status="complete",
    )
    await store.update_run(run1_id, result={
        "status": "complete",
        "metadata": {
            "run_id": run1_internal,
            "output_dir": str(run1_output),
            "workspace": str(experiment_dir),
        },
    })

    await store.save_run(
        run_id=run2_id,
        task="Task 2",
        model="test",
        config={"output_dir": str(experiment_dir)},
        status="complete",
    )
    await store.update_run(run2_id, result={
        "status": "complete",
        "metadata": {
            "run_id": run2_internal,
            "output_dir": str(run2_output),
            "workspace": str(experiment_dir),
        },
    })

    # Fetch artifacts for each run
    resp1 = await client.get(f"/api/runs/{run1_id}/artifacts")
    assert resp1.status_code == 200
    arts1 = resp1.json()["artifacts"]
    art1_names = {a["name"] for a in arts1 if a["source"] == "output"}

    resp2 = await client.get(f"/api/runs/{run2_id}/artifacts")
    assert resp2.status_code == 200
    arts2 = resp2.json()["artifacts"]
    art2_names = {a["name"] for a in arts2 if a["source"] == "output"}

    # Run 1 should see its own files, not run 2's
    assert "run1_chart.png" in art1_names
    assert "run1_results.csv" in art1_names
    assert "run2_report.json" not in art1_names
    assert "run2_plot.png" not in art1_names

    # Run 2 should see its own files, not run 1's
    assert "run2_report.json" in art2_names
    assert "run2_plot.png" in art2_names
    assert "run1_chart.png" not in art2_names
    assert "run1_results.csv" not in art2_names


@pytest.mark.asyncio
async def test_artifact_isolation_legacy_output_dir(client: AsyncClient, temp_dir: Path) -> None:
    """Runs with legacy output_dir (pointing to experiment base) should still resolve
    to the correct run-specific subdirectory using internal_run_id."""
    from server.app import store

    experiment_dir = temp_dir / "legacy_experiment"
    output_root = experiment_dir / "output"

    run1_internal = "2026-01-01_12-00-00_ccc33333"
    run1_output = output_root / run1_internal
    run1_output.mkdir(parents=True)
    (run1_output / "data.json").write_text('{"result": true}')

    run_id = "legacy_run_1"
    await store.save_run(
        run_id=run_id,
        task="Legacy task",
        model="test",
        config={"output_dir": str(experiment_dir)},
        status="complete",
    )
    # Simulate the OLD behavior: output_dir is the experiment base, not the run dir
    await store.update_run(run_id, result={
        "status": "complete",
        "metadata": {
            "run_id": run1_internal,
            "output_dir": str(experiment_dir),  # OLD: points to base, not run dir
            "workspace": str(experiment_dir),
        },
    })

    resp = await client.get(f"/api/runs/{run_id}/artifacts")
    assert resp.status_code == 200
    arts = resp.json()["artifacts"]
    output_arts = [a for a in arts if a["source"] == "output"]
    output_names = {a["name"] for a in output_arts}

    # Should still find the file in the run-specific subdirectory
    assert "data.json" in output_names
