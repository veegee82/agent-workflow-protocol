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


def test_continuation_dispatch_passes_prefix_to_agentworkflow(
    env: dict, tmp_path: Path, monkeypatch
) -> None:
    """Verify that continuation mode calls AgentWorkflow with manager_prompt_prefix set."""
    r = _run_cli(["experiment", "create", "E"], env=env)
    exp_id = json.loads(r.stdout)["experiment_id"]
    r = _run_cli(["task", "create", exp_id, "seed"], env=env)
    seed_id = json.loads(r.stdout)["task_id"]

    best = tmp_path / exp_id / "tasks" / seed_id / "BEST"
    best.mkdir(parents=True)
    (best / "manifest.json").write_text('{"winner_run_id":"fake"}')
    (best / "paper.md").write_text("prior draft body")

    r = _run_cli(
        [
            "task", "create", exp_id, "deepen section 2",
            "--continuation", "--from-task", seed_id, "--primary", "BEST/",
        ],
        env=env,
    )
    cont_id = json.loads(r.stdout)["task_id"]

    # Use a runtime hook that captures AgentWorkflow kwargs and exits before LLM
    env2 = env.copy()
    env2["AWP_CONTINUATION_CAPTURE_ONLY"] = str(tmp_path / "captured_kwargs.json")

    r = _run_cli(
        [
            "run", "nonexistent-wf.yaml",
            "--task", "fallback",
            "--target", f"{exp_id}:{cont_id}",
        ],
        env=env2,
    )
    assert r.returncode == 0, r.stderr + r.stdout
    captured = json.loads((tmp_path / "captured_kwargs.json").read_text())
    prefix = captured["manager_prompt_prefix"]
    assert "## Continuation Context" in prefix
    assert "paper.md" in prefix
    assert "prior draft body" in prefix
    assert "deepen section 2" in prefix
    # Confirm AgentWorkflow also got output_dir pointing at the continuation task's seed
    assert captured["output_dir"].endswith(f"{cont_id}/seed")
    # Task text becomes the user_feedback for continuation
    assert captured["task"] == "deepen section 2"


def test_post_run_finalise_updates_continuation_best(
    env: dict, tmp_path: Path
) -> None:
    """A continuation task's run also lands BEST/ and DB row like a seed run."""
    import os as _os
    _os.environ["AWP_EXPERIMENTS_ROOT"] = env["AWP_EXPERIMENTS_ROOT"]
    _os.environ["AWP_UI_DB_PATH"] = env["AWP_UI_DB_PATH"]

    r = _run_cli(["experiment", "create", "E"], env=env)
    exp_id = json.loads(r.stdout)["experiment_id"]
    r = _run_cli(["task", "create", exp_id, "seed"], env=env)
    seed_id = json.loads(r.stdout)["task_id"]
    best = tmp_path / exp_id / "tasks" / seed_id / "BEST"
    best.mkdir(parents=True)
    (best / "manifest.json").write_text('{"winner_run_id":"fake"}')
    (best / "paper.md").write_text("prior")

    r = _run_cli(
        [
            "task", "create", exp_id, "deepen",
            "--continuation", "--from-task", seed_id, "--primary", "BEST/",
        ],
        env=env,
    )
    cont_id = json.loads(r.stdout)["task_id"]

    # Build a fake finished run for the continuation task
    output_dir = tmp_path / exp_id / "tasks" / cont_id / "seed"
    run_id = "cont_run_1"
    run_dir = output_dir / "output" / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "FINAL").mkdir()
    (run_dir / "FINAL" / "paper.md").write_text("improved draft")
    (run_dir / "events.jsonl").write_text("")
    (run_dir / "metrics.jsonl").write_text("")
    (run_dir / "run_completion.json").write_text(json.dumps({
        "run_id": run_id,
        "status": "complete",
        "task": "deepen",
        "final_budget": {"loops": {"used": 1, "cap": 10}, "tokens": {"used": 100, "cap": 1000}},
        "eval": {"score": 0.9},
        "critique": {"defects": []},
        "gate_rejections": 0,
    }))

    import importlib
    cli_handlers = importlib.import_module("awp.experiment.cli_handlers")
    rc = cli_handlers._post_run_finalise(
        output_dir=output_dir,
        run_id=run_id,
        exp_id=exp_id,
        task_key=f"{exp_id}:{cont_id}",
        task_text="deepen",
        model="m",
    )
    assert rc == 0

    # BEST for the continuation task
    best_manifest = output_dir.parent / "BEST" / "manifest.json"
    assert best_manifest.exists()
    m = json.loads(best_manifest.read_text())
    assert m["winner_run_id"] == run_id

    # DB row for the continuation run
    import sqlite3
    con = sqlite3.connect(env["AWP_UI_DB_PATH"])
    con.row_factory = sqlite3.Row
    row = con.execute(
        "SELECT task_id, run_role FROM runs WHERE id = ?", (run_id,),
    ).fetchone()
    con.close()
    assert row["task_id"] == f"{exp_id}:{cont_id}"
    assert row["run_role"] == "seed"  # continuation runs are still the "seed" run of the continuation task
