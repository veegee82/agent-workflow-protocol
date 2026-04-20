"""Consolidated smoke test — Plans 1-5 combined pipeline (no LLM)."""

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


def test_full_arc_seed_continuation_refine_optimize(env: dict, tmp_path: Path) -> None:
    """End-to-end: experiment → seed task → continuation task → refine → optimize.

    Every step uses the real CLI. Runs are faked (no LLM).
    """
    import os as _os
    _os.environ["AWP_EXPERIMENTS_ROOT"] = env["AWP_EXPERIMENTS_ROOT"]
    _os.environ["AWP_UI_DB_PATH"] = env["AWP_UI_DB_PATH"]

    # ---- Plan 1: create experiment + seed task
    r = _run_cli(["experiment", "create", "Full-Arc"], env=env)
    exp_id = json.loads(r.stdout)["experiment_id"]
    r = _run_cli(["task", "create", exp_id, "Write paper"], env=env)
    seed_task_id = json.loads(r.stdout)["task_id"]

    # ---- Plan 2: fake seed run + post-finalise
    seed_dir = tmp_path / exp_id / "tasks" / seed_task_id / "seed"
    _mk_fake_run(seed_dir, "seed_r1", score=0.5)
    import importlib
    ch = importlib.import_module("awp.experiment.cli_handlers")
    ch._post_run_finalise(
        output_dir=seed_dir, run_id="seed_r1", exp_id=exp_id,
        task_key=f"{exp_id}:{seed_task_id}", task_text="Write paper",
        model="m", run_role="seed",
    )

    # Assert: seed task has BEST
    seed_best = tmp_path / exp_id / "tasks" / seed_task_id / "BEST"
    assert (seed_best / "manifest.json").exists()
    assert (seed_best / "paper.md").read_text() == "draft-seed_r1"

    # ---- Plan 3: create continuation task + fake its seed run
    r = _run_cli(
        [
            "task", "create", exp_id, "deepen sec 3",
            "--continuation", "--from-task", seed_task_id, "--primary", "BEST/",
        ],
        env=env,
    )
    cont_task_id = json.loads(r.stdout)["task_id"]

    # Dry-run the continuation dispatch to verify the prefix builds
    capture = tmp_path / "captured.json"
    env2 = env.copy()
    env2["AWP_CONTINUATION_CAPTURE_ONLY"] = str(capture)
    r = _run_cli(
        [
            "run", "nonexistent.yaml", "--task", "ignored",
            "--target", f"{exp_id}:{cont_task_id}",
        ],
        env=env2,
    )
    assert r.returncode == 0, r.stderr + r.stdout
    cap = json.loads(capture.read_text())
    assert "## Continuation Context" in cap["manager_prompt_prefix"]
    assert "draft-seed_r1" in cap["manager_prompt_prefix"]

    cont_dir = tmp_path / exp_id / "tasks" / cont_task_id / "seed"
    _mk_fake_run(cont_dir, "cont_r1", score=0.8)
    ch._post_run_finalise(
        output_dir=cont_dir, run_id="cont_r1", exp_id=exp_id,
        task_key=f"{exp_id}:{cont_task_id}", task_text="deepen sec 3",
        model="m", run_role="seed",
    )
    cont_best = tmp_path / exp_id / "tasks" / cont_task_id / "BEST"
    assert (cont_best / "manifest.json").exists()

    # ---- Plan 4: fake refine iteration for seed_task (better loss)
    refine_root = (
        tmp_path / exp_id / "tasks" / seed_task_id / "refinements" / "session_x"
    )
    iter_1 = refine_root / "iter_1"
    _mk_fake_run(iter_1, "refine_r1", score=0.95)
    ch._post_run_finalise(
        output_dir=iter_1, run_id="refine_r1", exp_id=exp_id,
        task_key=f"{exp_id}:{seed_task_id}", task_text="refine", model="m",
        run_role="refine_iter",
    )
    seed_best_m = json.loads((seed_best / "manifest.json").read_text())
    # refine_r1 beats seed_r1 since score 0.95 > 0.5 → lower loss
    assert seed_best_m["winner_run_id"] == "refine_r1"

    # ---- Plan 4: fake optimize epoch run (even better loss)
    opt_root = (
        tmp_path / exp_id / "tasks" / seed_task_id / "optimizations"
        / "suite_x" / "epoch_1"
    )
    _mk_fake_run(opt_root, "opt_r1", score=0.99)
    ch._post_run_finalise(
        output_dir=opt_root, run_id="opt_r1", exp_id=exp_id,
        task_key=f"{exp_id}:{seed_task_id}", task_text="opt",
        model="m", run_role="optimize_epoch_run",
    )
    seed_best_m = json.loads((seed_best / "manifest.json").read_text())
    assert seed_best_m["winner_run_id"] == "opt_r1"

    # ---- Plan 5-ish: DB state is coherent
    con = sqlite3.connect(env["AWP_UI_DB_PATH"])
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT id, run_role FROM runs WHERE experiment_id = ? ORDER BY id",
        (exp_id,),
    ).fetchall()
    con.close()
    roles = {r["id"]: r["run_role"] for r in rows}
    assert roles["seed_r1"] == "seed"
    assert roles["cont_r1"] == "seed"
    assert roles["refine_r1"] == "refine_iter"
    assert roles["opt_r1"] == "optimize_epoch_run"
