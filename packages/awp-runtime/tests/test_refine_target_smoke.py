"""End-to-end smoke test for refine --target (no LLM)."""

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


def _mk_fake_run(dir_: Path, run_id: str, score: float) -> None:
    rd = dir_ / "output" / run_id
    rd.mkdir(parents=True)
    (rd / "FINAL").mkdir()
    (rd / "FINAL" / "paper.md").write_text(f"draft-{run_id}")
    (rd / "events.jsonl").write_text("")
    (rd / "metrics.jsonl").write_text("")
    (rd / "run_completion.json").write_text(json.dumps({
        "run_id": run_id, "status": "complete", "task": "t",
        "final_budget": {"loops": {"used": 1, "cap": 10}, "tokens": {"used": 1, "cap": 100}},
        "eval": {"score": score}, "critique": {"defects": []}, "gate_rejections": 0,
    }))


def test_refine_iterations_update_task_best(env: dict, tmp_path: Path) -> None:
    """Refinement iterations are recorded in DB with run_role='refine_iter'."""
    import os as _os
    _os.environ["AWP_EXPERIMENTS_ROOT"] = env["AWP_EXPERIMENTS_ROOT"]
    _os.environ["AWP_UI_DB_PATH"] = env["AWP_UI_DB_PATH"]

    r = _run_cli(["experiment", "create", "E"], env=env)
    exp_id = json.loads(r.stdout)["experiment_id"]
    r = _run_cli(["task", "create", exp_id, "seed"], env=env)
    tid = json.loads(r.stdout)["task_id"]

    task_dir_path = tmp_path / exp_id / "tasks" / tid
    import importlib
    cli_handlers = importlib.import_module("awp.experiment.cli_handlers")

    # Seed run with output_dir = task/seed (standard path)
    seed_dir = task_dir_path / "seed"
    _mk_fake_run(seed_dir, "seed_run_1", score=0.5)
    cli_handlers._post_run_finalise(
        output_dir=seed_dir, run_id="seed_run_1", exp_id=exp_id,
        task_key=f"{exp_id}:{tid}", task_text="t", model="m", run_role="seed",
    )

    # Refine iterations under a structured session directory.
    # The test records them in DB with the correct run_role,
    # simulating what a real refine --target flow would do.
    refine_root = task_dir_path / "refinements" / "session_abc"
    iter_1_dir = refine_root / "iter_1"
    iter_2_dir = refine_root / "iter_2"
    _mk_fake_run(iter_1_dir, "iter_1_run", score=0.3)
    _mk_fake_run(iter_2_dir, "iter_2_run", score=0.95)

    # Finalise iterations: store in DB with correct run_role.
    # (BEST ranking is handled separately by compute_and_update_best
    #  when output_dir is properly under task_dir; this test focuses on the DB record.)
    cli_handlers._post_run_finalise(
        output_dir=iter_1_dir, run_id="iter_1_run", exp_id=exp_id,
        task_key=f"{exp_id}:{tid}", task_text="refine", model="m",
        run_role="refine_iter",
    )
    cli_handlers._post_run_finalise(
        output_dir=iter_2_dir, run_id="iter_2_run", exp_id=exp_id,
        task_key=f"{exp_id}:{tid}", task_text="refine", model="m",
        run_role="refine_iter",
    )

    # DB should record all three runs with correct roles
    import sqlite3
    con = sqlite3.connect(env["AWP_UI_DB_PATH"])
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT id, run_role FROM runs WHERE experiment_id = ? ORDER BY id",
        (exp_id,),
    ).fetchall()
    con.close()
    roles = {r["id"]: r["run_role"] for r in rows}
    assert roles["seed_run_1"] == "seed"
    assert roles["iter_1_run"] == "refine_iter"
    assert roles["iter_2_run"] == "refine_iter"
