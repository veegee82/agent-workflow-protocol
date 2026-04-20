"""CLI tests for `awp experiment purge-legacy`."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest


def _run_cli(args: list[str], env: dict) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "awp", *args],
        capture_output=True, text=True, env=env,
    )


@pytest.fixture
def env(tmp_path: Path) -> dict:
    env = os.environ.copy()
    env["AWP_EXPERIMENTS_ROOT"] = str(tmp_path)
    env["AWP_UI_DB_PATH"] = str(tmp_path / "awp_ui.db")
    return env


def test_purge_legacy_deletes_flat_dirs(env: dict, tmp_path: Path) -> None:
    # Build a legacy flat dir (no experiment.json at root)
    legacy = tmp_path / "legacy-run-abc123"
    legacy.mkdir()
    (legacy / "run_completion.json").write_text('{"run_id":"abc123"}')

    # Build a hierarchy dir (has experiment.json)
    r = _run_cli(["experiment", "create", "H"], env=env)
    exp_id = json.loads(r.stdout)["experiment_id"]
    hierarchy = tmp_path / exp_id
    assert hierarchy.exists()
    assert (hierarchy / "experiment.json").exists()

    # Run purge with --yes
    r = _run_cli(["experiment", "purge-legacy", "--yes"], env=env)
    assert r.returncode == 0, r.stderr

    # Legacy gone, hierarchy preserved
    assert not legacy.exists()
    assert hierarchy.exists()


def test_purge_legacy_lists_before_delete(env: dict, tmp_path: Path) -> None:
    """Without --yes, purge prints the list and prompts (we skip input + abort)."""
    legacy = tmp_path / "legacy-xyz"
    legacy.mkdir()

    # Send "n\n" to stdin to decline confirmation
    r = subprocess.run(
        [sys.executable, "-m", "awp", "experiment", "purge-legacy"],
        capture_output=True, text=True, env=env, input="n\n",
    )
    assert r.returncode != 0 or "aborted" in (r.stderr + r.stdout).lower()
    # Directory still present after decline
    assert legacy.exists()


def test_purge_legacy_deletes_orphan_runs_rows(env: dict, tmp_path: Path) -> None:
    """`runs` rows with experiment_id IS NULL are deleted."""
    db = tmp_path / "awp_ui.db"

    # Seed the DB with: one orphan run + one hierarchy-attached run
    from server.services.store import StoreService
    import asyncio

    async def _seed():
        s = StoreService(db_path=db)
        await s.init_db()
        # Hierarchy experiment + task + run
        await s.create_experiment("exp_x", "E", "", str(tmp_path / "exp_x"), 1.0)
        await s.create_task("exp_x:001-s", "exp_x", 1, "s", "seed", "p", None, "[]", 1.0)
        await s.upsert_run_for_task(
            "kept_run", "exp_x", "exp_x:001-s", "seed", 0.3, "complete", "t", "m",
        )
        # Orphan: insert raw (no experiment_id)
        import time
        await s.db.execute(
            "INSERT INTO runs (id, task, model, status, config_json, created_at) "
            "VALUES (?, ?, ?, ?, '{}', ?)",
            ("orphan_run", "legacy", "m", "complete", str(time.time())),
        )
        await s.db.commit()
        await s.close()

    asyncio.run(_seed())

    r = _run_cli(["experiment", "purge-legacy", "--yes"], env=env)
    assert r.returncode == 0, r.stderr

    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    rows = con.execute("SELECT id, experiment_id FROM runs").fetchall()
    con.close()
    ids = {row["id"]: row["experiment_id"] for row in rows}
    assert "kept_run" in ids
    assert ids["kept_run"] == "exp_x"
    assert "orphan_run" not in ids
