"""End-to-end smoke test for the continuation pipeline (no LLM).

Exercises: CLI experiment+task CRUD → fake finished seed run →
fake finished continuation run → BEST promotion through both tasks.
Catches the "fixtures disagree with production schema" class of bug.
"""

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


def _mk_fake_run(output_dir: Path, run_id: str, score: float) -> None:
    rd = output_dir / "output" / run_id
    rd.mkdir(parents=True)
    (rd / "FINAL").mkdir()
    (rd / "FINAL" / "paper.md").write_text(f"draft-from-{run_id}")
    (rd / "events.jsonl").write_text("")
    (rd / "metrics.jsonl").write_text("")
    (rd / "run_completion.json").write_text(json.dumps({
        "run_id": run_id,
        "status": "complete",
        "task": "t",
        "final_budget": {"loops": {"used": 1, "cap": 10}, "tokens": {"used": 1, "cap": 100}},
        "eval": {"score": score},
        "critique": {"defects": []},
        "gate_rejections": 0,
    }))


def test_seed_then_continuation_smoke(env: dict, tmp_path: Path) -> None:
    # Set env vars in the current process so direct imports work
    os.environ.update(env)

    # 1. Experiment + seed task
    r = _run_cli(["experiment", "create", "Smoke"], env=env)
    exp_id = json.loads(r.stdout)["experiment_id"]
    r = _run_cli(["task", "create", exp_id, "Write paper"], env=env)
    seed_id = json.loads(r.stdout)["task_id"]
    seed_output = tmp_path / exp_id / "tasks" / seed_id / "seed"

    # 2. Fake a finished seed run + finalise
    _mk_fake_run(seed_output, "seed_run_1", score=0.9)
    import importlib
    cli_handlers = importlib.import_module("awp.experiment.cli_handlers")
    rc = cli_handlers._post_run_finalise(
        output_dir=seed_output,
        run_id="seed_run_1",
        exp_id=exp_id,
        task_key=f"{exp_id}:{seed_id}",
        task_text="Write paper",
        model="m",
    )
    assert rc == 0
    seed_best = tmp_path / exp_id / "tasks" / seed_id / "BEST"
    assert (seed_best / "paper.md").read_text() == "draft-from-seed_run_1"

    # 3. Continuation task
    r = _run_cli(
        [
            "task", "create", exp_id, "deepen section 2",
            "--continuation", "--from-task", seed_id, "--primary", "BEST/",
        ],
        env=env,
    )
    cont_id = json.loads(r.stdout)["task_id"]

    # 4. Exercise the CLI continuation path in CAPTURE_ONLY mode:
    #    ensures the bundle + prefix were built correctly before any LLM call
    capture = tmp_path / "captured.json"
    env2 = env.copy()
    env2["AWP_CONTINUATION_CAPTURE_ONLY"] = str(capture)
    r = _run_cli(
        [
            "run", "nonexistent-wf.yaml",
            "--task", "ignored",
            "--target", f"{exp_id}:{cont_id}",
        ],
        env=env2,
    )
    assert r.returncode == 0, r.stderr + r.stdout
    cap = json.loads(capture.read_text())
    assert cap["mode"] == "continuation"
    assert "## Continuation Context" in cap["manager_prompt_prefix"]
    assert "draft-from-seed_run_1" in cap["manager_prompt_prefix"]
    assert "deepen section 2" in cap["manager_prompt_prefix"]
    assert cap["task"] == "deepen section 2"

    # 5. Fake a finished continuation run + finalise
    cont_output = tmp_path / exp_id / "tasks" / cont_id / "seed"
    _mk_fake_run(cont_output, "cont_run_1", score=0.95)
    rc = cli_handlers._post_run_finalise(
        output_dir=cont_output,
        run_id="cont_run_1",
        exp_id=exp_id,
        task_key=f"{exp_id}:{cont_id}",
        task_text="deepen section 2",
        model="m",
    )
    assert rc == 0

    # 6. BEST for the continuation task
    cont_best = tmp_path / exp_id / "tasks" / cont_id / "BEST"
    assert (cont_best / "manifest.json").exists()
    m = json.loads((cont_best / "manifest.json").read_text())
    assert m["winner_run_id"] == "cont_run_1"

    # 7. DB state: both runs present with correct task_id
    import sqlite3
    con = sqlite3.connect(env["AWP_UI_DB_PATH"])
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT id, task_id FROM runs WHERE experiment_id = ? ORDER BY id",
        (exp_id,),
    ).fetchall()
    con.close()
    assert {r["id"] for r in rows} == {"seed_run_1", "cont_run_1"}
    assert dict((r["id"], r["task_id"]) for r in rows) == {
        "seed_run_1": f"{exp_id}:{seed_id}",
        "cont_run_1": f"{exp_id}:{cont_id}",
    }
