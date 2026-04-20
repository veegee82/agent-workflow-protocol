"""CLI-level tests for `awp refine --target`."""

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


def test_refine_target_rejects_missing_task(env: dict) -> None:
    r = _run_cli(["refine", "--target", "exp_nosuch1:001-x"], env=env)
    assert r.returncode != 0
    lower = (r.stderr + r.stdout).lower()
    assert "not found" in lower or "experiment" in lower


def test_refine_target_rejects_task_without_best(env: dict, tmp_path: Path) -> None:
    """Refinement needs a completed run under the task; without BEST/, reject."""
    r = _run_cli(["experiment", "create", "E"], env=env)
    exp_id = json.loads(r.stdout)["experiment_id"]
    r = _run_cli(["task", "create", exp_id, "seed"], env=env)
    tid = json.loads(r.stdout)["task_id"]
    # No BEST/ under the task
    r = _run_cli(["refine", "--target", f"{exp_id}:{tid}"], env=env)
    assert r.returncode != 0
    lower = (r.stderr + r.stdout).lower()
    assert "best" in lower


def test_refine_target_dry_run_computes_session_dir(env: dict, tmp_path: Path) -> None:
    """DRY_RUN prints the computed session dir + seed resolution."""
    r = _run_cli(["experiment", "create", "E"], env=env)
    exp_id = json.loads(r.stdout)["experiment_id"]
    r = _run_cli(["task", "create", exp_id, "seed"], env=env)
    tid = json.loads(r.stdout)["task_id"]

    # Build fake BEST pointing at a fake run
    task_dir = tmp_path / exp_id / "tasks" / tid
    seed_run_dir = task_dir / "seed" / "output" / "seed_run_1"
    seed_run_dir.mkdir(parents=True)
    (seed_run_dir / "run_completion.json").write_text("{}")

    best = task_dir / "BEST"
    best.mkdir(parents=True)
    (best / "manifest.json").write_text(json.dumps({
        "winner_run_id": "seed_run_1",
        "winner_source": str(seed_run_dir),
        "reason": "auto_loss", "loss": 0.4,
    }))

    env2 = env.copy()
    env2["AWP_REFINE_TARGET_DRY_RUN"] = "1"
    r = _run_cli(["refine", "--target", f"{exp_id}:{tid}"], env=env2)
    assert r.returncode == 0, r.stderr + r.stdout
    payload = json.loads(r.stdout)
    assert str(task_dir / "refinements") in payload["iterations_root"]
    assert payload["seed_run_dir"].endswith("seed_run_1")
    assert payload["target"] == f"{exp_id}:{tid}"
