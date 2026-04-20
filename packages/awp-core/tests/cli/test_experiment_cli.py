"""CLI-level tests for `awp experiment ...`."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


def _run_cli(args: list[str], env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "awp", *args],
        capture_output=True,
        text=True,
        env=env,
    )


@pytest.fixture
def tmp_experiments(tmp_path: Path) -> Path:
    return tmp_path


def test_experiment_create_writes_disk_and_prints_id(tmp_experiments: Path) -> None:
    env = os.environ.copy()
    env["AWP_EXPERIMENTS_ROOT"] = str(tmp_experiments)
    env["AWP_UI_DB_PATH"] = str(tmp_experiments / "awp_ui.db")

    result = _run_cli(["experiment", "create", "AWP Paper", "--goal", "For pub"], env=env)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    exp_id = payload["experiment_id"]
    assert exp_id.startswith("exp_")
    assert (tmp_experiments / exp_id / "experiment.json").exists()
    manifest = json.loads(
        (tmp_experiments / exp_id / "experiment.json").read_text()
    )
    assert manifest["name"] == "AWP Paper"
    assert manifest["goal"] == "For pub"


def test_experiment_list_shows_created(tmp_experiments: Path) -> None:
    env = os.environ.copy()
    env["AWP_EXPERIMENTS_ROOT"] = str(tmp_experiments)
    env["AWP_UI_DB_PATH"] = str(tmp_experiments / "awp_ui.db")

    _run_cli(["experiment", "create", "First"], env=env)
    _run_cli(["experiment", "create", "Second"], env=env)
    result = _run_cli(["experiment", "list"], env=env)
    assert result.returncode == 0
    items = json.loads(result.stdout)
    assert len(items) == 2
    names = {item["name"] for item in items}
    assert names == {"First", "Second"}


def test_experiment_show_includes_tasks(tmp_experiments: Path) -> None:
    env = os.environ.copy()
    env["AWP_EXPERIMENTS_ROOT"] = str(tmp_experiments)
    env["AWP_UI_DB_PATH"] = str(tmp_experiments / "awp_ui.db")

    created = _run_cli(["experiment", "create", "E"], env=env)
    exp_id = json.loads(created.stdout)["experiment_id"]
    result = _run_cli(["experiment", "show", exp_id], env=env)
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["experiment_id"] == exp_id
    assert payload["task_order"] == []


def test_experiment_delete_removes_dir_and_db_row(tmp_experiments: Path) -> None:
    env = os.environ.copy()
    env["AWP_EXPERIMENTS_ROOT"] = str(tmp_experiments)
    env["AWP_UI_DB_PATH"] = str(tmp_experiments / "awp_ui.db")

    created = _run_cli(["experiment", "create", "E"], env=env)
    exp_id = json.loads(created.stdout)["experiment_id"]
    assert (tmp_experiments / exp_id).exists()
    result = _run_cli(["experiment", "delete", exp_id, "--yes"], env=env)
    assert result.returncode == 0
    assert not (tmp_experiments / exp_id).exists()
