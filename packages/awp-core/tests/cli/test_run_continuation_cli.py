"""CLI-level tests for `awp run --target <continuation>`."""

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


def test_run_continuation_no_longer_rejected(env: dict, tmp_path: Path) -> None:
    """Continuation target is accepted (previously blocked in Plan 2 Task 1)."""
    r = _run_cli(["experiment", "create", "E"], env=env)
    exp_id = json.loads(r.stdout)["experiment_id"]
    r = _run_cli(["task", "create", exp_id, "seed"], env=env)
    seed_id = json.loads(r.stdout)["task_id"]

    # Build a BEST dir so continuation creation passes
    best = tmp_path / exp_id / "tasks" / seed_id / "BEST"
    best.mkdir(parents=True)
    (best / "manifest.json").write_text('{"winner_run_id":"fake"}')
    (best / "paper.md").write_text("prior draft")

    r = _run_cli(
        [
            "task", "create", exp_id, "improve",
            "--continuation", "--from-task", seed_id, "--primary", "BEST/",
        ],
        env=env,
    )
    cont_id = json.loads(r.stdout)["task_id"]

    env2 = env.copy()
    env2["AWP_RUN_TASK_DRY_RUN"] = "1"

    r = _run_cli(
        [
            "run", "nonexistent-wf.yaml",
            "--task", "dummy",
            "--target", f"{exp_id}:{cont_id}",
        ],
        env=env2,
    )
    # The validator no longer rejects continuation tasks.
    # The dry-run branch prints the output_dir and exits 0.
    combined = r.stdout + r.stderr
    assert r.returncode == 0, combined
    assert "continuation" not in combined.lower() or "mode=continuation" not in combined.lower()
    assert str(tmp_path / exp_id / "tasks" / cont_id / "seed") in combined
