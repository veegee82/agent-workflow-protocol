"""CLI-level tests for `awp run --task`."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


def _run_cli(args: list[str], env: dict) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "awp", *args],
        capture_output=True,
        text=True,
        env=env,
    )


@pytest.fixture
def env(tmp_path: Path) -> dict:
    env = os.environ.copy()
    env["AWP_EXPERIMENTS_ROOT"] = str(tmp_path)
    env["AWP_UI_DB_PATH"] = str(tmp_path / "awp_ui.db")
    return env


def test_run_rejects_continuation_task(env: dict, tmp_path: Path) -> None:
    r = _run_cli(["experiment", "create", "E"], env=env)
    exp_id = json.loads(r.stdout)["experiment_id"]
    r = _run_cli(["task", "create", exp_id, "seed"], env=env)
    seed_id = json.loads(r.stdout)["task_id"]
    best = tmp_path / exp_id / "tasks" / seed_id / "BEST"
    best.mkdir(parents=True)
    (best / "manifest.json").write_text("{}")
    r = _run_cli(
        [
            "task", "create", exp_id, "fb",
            "--continuation", "--from-task", seed_id, "--primary", "BEST/",
        ],
        env=env,
    )
    cont_id = json.loads(r.stdout)["task_id"]

    r = _run_cli(
        ["run", "nonexistent-workflow.yaml", "--task", f"{exp_id}:{cont_id}"],
        env=env,
    )
    assert r.returncode != 0
    combined = r.stderr + r.stdout
    assert "continuation" in combined.lower()
    assert "plan 3" in combined.lower()


def test_run_rejects_unknown_task(env: dict) -> None:
    r = _run_cli(
        ["run", "nonexistent-workflow.yaml", "--task", "exp_nosuch1:001-x"],
        env=env,
    )
    assert r.returncode != 0
    assert "experiment not found" in (r.stderr + r.stdout).lower() or \
           "task not found" in (r.stderr + r.stdout).lower()


def test_run_rejects_malformed_task_key(env: dict) -> None:
    r = _run_cli(
        ["run", "nonexistent-workflow.yaml", "--task", "not-a-key"],
        env=env,
    )
    assert r.returncode != 0
    assert "<experiment_id>:<task_id>" in (r.stderr + r.stdout)
