"""CLI-level tests for `awp run --target <exp>:<task_id>`."""

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
        [
            "run", "nonexistent-workflow.yaml",
            "--task", "dummy",
            "--target", f"{exp_id}:{cont_id}",
        ],
        env=env,
    )
    assert r.returncode != 0
    combined = r.stderr + r.stdout
    assert "continuation" in combined.lower()
    assert "plan 3" in combined.lower()


def test_run_rejects_unknown_task(env: dict) -> None:
    r = _run_cli(
        [
            "run", "nonexistent-workflow.yaml",
            "--task", "dummy",
            "--target", "exp_nosuch1:001-x",
        ],
        env=env,
    )
    assert r.returncode != 0
    assert "experiment not found" in (r.stderr + r.stdout).lower() or \
           "task not found" in (r.stderr + r.stdout).lower()


def test_run_rejects_malformed_task_key(env: dict) -> None:
    r = _run_cli(
        [
            "run", "nonexistent-workflow.yaml",
            "--task", "dummy",
            "--target", "not-a-key",
        ],
        env=env,
    )
    assert r.returncode != 0
    assert "<experiment_id>:<task_id>" in (r.stderr + r.stdout)


def test_run_with_target_calls_agentworkflow_with_task_output_dir(
    env: dict, tmp_path: Path
) -> None:
    """Verify cmd_run with --target routes through the task-aware path."""
    r = _run_cli(["experiment", "create", "E"], env=env)
    exp_id = json.loads(r.stdout)["experiment_id"]
    r = _run_cli(["task", "create", exp_id, "seed"], env=env)
    task_id = json.loads(r.stdout)["task_id"]

    wf = tmp_path / "wf"
    wf.mkdir()
    (wf / "workflow.awp.yaml").write_text("name: test\n")

    env2 = env.copy()
    env2["AWP_RUN_TASK_DRY_RUN"] = "1"

    r = _run_cli(
        [
            "run", str(wf),
            "--task", "dummy task text",
            "--target", f"{exp_id}:{task_id}",
        ],
        env=env2,
    )
    combined = r.stdout + r.stderr
    expected_prefix = str(tmp_path / exp_id / "tasks" / task_id / "seed")
    assert r.returncode == 0, combined
    assert expected_prefix in combined


def test_post_run_finalise_updates_db_and_best(env: dict, tmp_path: Path) -> None:
    """End-to-end of the post-run hook using a pre-built fake run_dir."""
    import os
    # Set env vars in this process too, so the handler module sees them
    os.environ["AWP_EXPERIMENTS_ROOT"] = env["AWP_EXPERIMENTS_ROOT"]
    os.environ["AWP_UI_DB_PATH"] = env["AWP_UI_DB_PATH"]

    # Setup: experiment + task via CLI
    r = _run_cli(["experiment", "create", "E"], env=env)
    exp_id = json.loads(r.stdout)["experiment_id"]
    r = _run_cli(["task", "create", exp_id, "seed"], env=env)
    task_id = json.loads(r.stdout)["task_id"]

    # Build a fake finished run_dir
    output_dir = tmp_path / exp_id / "tasks" / task_id / "seed"
    run_id = "2026-04-20_15-00-00_abc12345"
    run_dir = output_dir / "output" / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "FINAL").mkdir()
    (run_dir / "FINAL" / "paper.md").write_text("fake deliverable")
    (run_dir / "events.jsonl").write_text("")
    (run_dir / "metrics.jsonl").write_text("")
    (run_dir / "run_completion.json").write_text(json.dumps({
        "run_id": run_id,
        "status": "complete",
        "task": "t",
        "final_budget": {"loops": {"used": 1, "cap": 10}, "tokens": {"used": 100, "cap": 1000}},
        "eval": {"score": 0.9},
        "critique": {"defects": []},
        "gate_rejections": 0,
    }))

    # Call the hook directly
    import importlib
    cli_handlers = importlib.import_module("awp.experiment.cli_handlers")
    rc = cli_handlers._post_run_finalise(
        output_dir=output_dir,
        run_id=run_id,
        exp_id=exp_id,
        task_key=f"{exp_id}:{task_id}",
        task_text="t",
        model="m",
    )
    assert rc == 0

    # Verify BEST was written
    best_manifest = output_dir.parent / "BEST" / "manifest.json"
    assert best_manifest.exists()
    m = json.loads(best_manifest.read_text())
    assert m["winner_run_id"] == run_id
    # Verify BEST contains the deliverable
    assert (output_dir.parent / "BEST" / "paper.md").exists()

    # Verify the DB row
    import sqlite3
    con = sqlite3.connect(env["AWP_UI_DB_PATH"])
    con.row_factory = sqlite3.Row
    row = con.execute(
        "SELECT experiment_id, task_id, run_role, loss, status FROM runs WHERE id = ?",
        (run_id,),
    ).fetchone()
    con.close()
    assert row is not None
    assert row["experiment_id"] == exp_id
    assert row["task_id"] == f"{exp_id}:{task_id}"
    assert row["run_role"] == "seed"
    assert row["status"] == "complete"
    assert row["loss"] is not None
