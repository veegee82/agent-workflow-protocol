"""End-to-end smoke test for optimize --target (no LLM, dry-run path only)."""

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


def test_optimize_target_creates_per_exp_db_path(env: dict, tmp_path: Path) -> None:
    """DRY_RUN shows that the resolved db_path lives under the experiment dir."""
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
    assert r.returncode == 0
    payload = json.loads(r.stdout)
    expected_db = tmp_path / exp_id / "outer_loop.db"
    expected_output_prefix = tmp_path / exp_id / "tasks" / tid / "optimizations"
    assert payload["db_path"] == str(expected_db)
    assert payload["output_dir"].startswith(str(expected_output_prefix))


def test_optimize_task_aware_finalise_records_epoch_run_role(
    env: dict, tmp_path: Path,
) -> None:
    """_post_run_finalise accepts run_role='optimize_epoch_run'."""
    import os as _os
    _os.environ["AWP_EXPERIMENTS_ROOT"] = env["AWP_EXPERIMENTS_ROOT"]
    _os.environ["AWP_UI_DB_PATH"] = env["AWP_UI_DB_PATH"]

    r = _run_cli(["experiment", "create", "E"], env=env)
    exp_id = json.loads(r.stdout)["experiment_id"]
    r = _run_cli(["task", "create", exp_id, "seed"], env=env)
    tid = json.loads(r.stdout)["task_id"]

    opt_dir = tmp_path / exp_id / "tasks" / tid / "optimizations" / "suite_x" / "epoch_1"
    opt_dir.mkdir(parents=True)
    run_dir = opt_dir / "output" / "epoch_run_1"
    run_dir.mkdir(parents=True)
    (run_dir / "FINAL").mkdir()
    (run_dir / "FINAL" / "x.md").write_text("x")
    (run_dir / "events.jsonl").write_text("")
    (run_dir / "metrics.jsonl").write_text("")
    (run_dir / "run_completion.json").write_text(json.dumps({
        "run_id": "epoch_run_1", "status": "complete", "task": "t",
        "final_budget": {"loops": {"used": 1, "cap": 10}, "tokens": {"used": 1, "cap": 100}},
        "eval": {"score": 0.8}, "critique": {"defects": []}, "gate_rejections": 0,
    }))

    import importlib
    ch = importlib.import_module("awp.experiment.cli_handlers")
    rc = ch._post_run_finalise(
        output_dir=opt_dir, run_id="epoch_run_1", exp_id=exp_id,
        task_key=f"{exp_id}:{tid}", task_text="opt", model="m",
        run_role="optimize_epoch_run",
    )
    assert rc == 0

    import sqlite3
    con = sqlite3.connect(env["AWP_UI_DB_PATH"])
    con.row_factory = sqlite3.Row
    row = con.execute(
        "SELECT run_role FROM runs WHERE id = ?", ("epoch_run_1",),
    ).fetchone()
    con.close()
    assert row["run_role"] == "optimize_epoch_run"
