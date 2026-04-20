"""CLI-level tests for `awp optimize --target`."""

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
        capture_output=True, text=True, env=env,
    )


@pytest.fixture
def env(tmp_path: Path) -> dict:
    env = os.environ.copy()
    env["AWP_EXPERIMENTS_ROOT"] = str(tmp_path)
    env["AWP_UI_DB_PATH"] = str(tmp_path / "awp_ui.db")
    return env


def test_optimize_target_rejects_missing_task(env: dict, tmp_path: Path) -> None:
    suite = tmp_path / "s.yaml"
    suite.write_text("name: s\ndescription: s\nbaseline_artifacts: {}\ntasks: []\n")
    r = _run_cli(
        ["optimize", str(suite), "--target", "exp_nosuch1:001-x"], env=env,
    )
    assert r.returncode != 0
    assert "not found" in (r.stderr + r.stdout).lower()


def test_optimize_target_dry_run_resolves_paths(env: dict, tmp_path: Path) -> None:
    r = _run_cli(["experiment", "create", "E"], env=env)
    exp_id = json.loads(r.stdout)["experiment_id"]
    r = _run_cli(["task", "create", exp_id, "seed"], env=env)
    tid = json.loads(r.stdout)["task_id"]
    suite = tmp_path / "s.yaml"
    suite.write_text("name: s\ndescription: s\nbaseline_artifacts: {}\ntasks: []\n")

    env2 = env.copy()
    env2["AWP_OPTIMIZE_TARGET_DRY_RUN"] = "1"
    r = _run_cli(
        ["optimize", str(suite), "--target", f"{exp_id}:{tid}"], env=env2,
    )
    assert r.returncode == 0, r.stderr + r.stdout
    payload = json.loads(r.stdout)
    assert payload["db_path"].endswith(f"{exp_id}/outer_loop.db")
    assert str(tmp_path / exp_id / "tasks" / tid / "optimizations") in payload["output_dir"]
    assert payload["target"] == f"{exp_id}:{tid}"
