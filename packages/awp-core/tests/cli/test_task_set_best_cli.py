"""CLI tests for `awp task set-best --run <id>` and `--auto`."""

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


def _mk_run_in_task(task_dir: Path, run_id: str, score: float) -> Path:
    output_dir = task_dir / "seed" / "output" / run_id
    output_dir.mkdir(parents=True)
    (output_dir / "FINAL").mkdir()
    (output_dir / "FINAL" / "art.md").write_text(f"run={run_id}")
    (output_dir / "events.jsonl").write_text("")
    (output_dir / "metrics.jsonl").write_text("")
    (output_dir / "run_completion.json").write_text(json.dumps({
        "run_id": run_id,
        "status": "complete",
        "task": "t",
        "final_budget": {"loops": {"used": 1, "cap": 10}, "tokens": {"used": 1, "cap": 100}},
        "evaluation": {"score": score},
        "critique": {"defects": []},
        "gate_rejections": 0,
    }))
    return output_dir


def _setup(env: dict, tmp_path: Path) -> tuple[str, str, Path]:
    r = _run_cli(["experiment", "create", "E"], env=env)
    exp_id = json.loads(r.stdout)["experiment_id"]
    r = _run_cli(["task", "create", exp_id, "seed"], env=env)
    tid = json.loads(r.stdout)["task_id"]
    return exp_id, tid, tmp_path / exp_id / "tasks" / tid


def test_set_best_with_run_sets_user_override(env: dict, tmp_path: Path) -> None:
    exp_id, tid, task_dir = _setup(env, tmp_path)
    _mk_run_in_task(task_dir, "run_low", score=0.1)
    _mk_run_in_task(task_dir, "run_high", score=0.99)

    r = _run_cli(
        ["task", "set-best", f"{exp_id}:{tid}", "--run", "run_low"],
        env=env,
    )
    assert r.returncode == 0, r.stderr

    manifest = json.loads((task_dir / "BEST" / "manifest.json").read_text())
    assert manifest["winner_run_id"] == "run_low"
    assert manifest["reason"] == "user_override"


def test_set_best_auto_clears_override(env: dict, tmp_path: Path) -> None:
    exp_id, tid, task_dir = _setup(env, tmp_path)
    _mk_run_in_task(task_dir, "run_low", score=0.1)
    _mk_run_in_task(task_dir, "run_high", score=0.99)

    _run_cli(["task", "set-best", f"{exp_id}:{tid}", "--run", "run_low"], env=env)
    r = _run_cli(["task", "set-best", f"{exp_id}:{tid}", "--auto"], env=env)
    assert r.returncode == 0, r.stderr
    manifest = json.loads((task_dir / "BEST" / "manifest.json").read_text())
    assert manifest["winner_run_id"] == "run_high"
    assert manifest["reason"] == "auto_loss"


def test_set_best_requires_run_or_auto(env: dict, tmp_path: Path) -> None:
    exp_id, tid, _ = _setup(env, tmp_path)
    r = _run_cli(["task", "set-best", f"{exp_id}:{tid}"], env=env)
    assert r.returncode != 0


def test_set_best_rejects_unknown_run(env: dict, tmp_path: Path) -> None:
    exp_id, tid, task_dir = _setup(env, tmp_path)
    _mk_run_in_task(task_dir, "run1", score=0.5)
    r = _run_cli(
        ["task", "set-best", f"{exp_id}:{tid}", "--run", "does-not-exist"],
        env=env,
    )
    assert r.returncode != 0
    assert "not found" in (r.stderr + r.stdout).lower()
