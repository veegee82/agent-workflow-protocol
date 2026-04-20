"""CLI-level tests for `awp task ...`."""

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


def _mk_exp(env: dict) -> str:
    r = _run_cli(["experiment", "create", "E"], env=env)
    return json.loads(r.stdout)["experiment_id"]


def test_task_create_seed_writes_manifest_and_db(env: dict, tmp_path: Path) -> None:
    exp_id = _mk_exp(env)
    result = _run_cli(
        ["task", "create", exp_id, "Write a paper about AWP"], env=env
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    task_id = payload["task_id"]
    assert task_id.startswith("001-")
    # Disk
    manifest_path = (
        tmp_path / exp_id / "tasks" / task_id / "task.json"
    )
    assert manifest_path.exists()
    manifest = json.loads(manifest_path.read_text())
    assert manifest["mode"] == "seed"
    assert manifest["user_prompt"] == "Write a paper about AWP"
    # Experiment task_order updated
    exp_manifest = json.loads((tmp_path / exp_id / "experiment.json").read_text())
    assert exp_manifest["task_order"] == [task_id]


def test_task_create_seed_increments_number(env: dict, tmp_path: Path) -> None:
    exp_id = _mk_exp(env)
    _run_cli(["task", "create", exp_id, "first"], env=env)
    r2 = _run_cli(["task", "create", exp_id, "second"], env=env)
    assert r2.returncode == 0
    second_id = json.loads(r2.stdout)["task_id"]
    assert second_id.startswith("002-")


def test_task_list_and_show(env: dict) -> None:
    exp_id = _mk_exp(env)
    r1 = _run_cli(["task", "create", exp_id, "first"], env=env)
    task_id = json.loads(r1.stdout)["task_id"]

    r_list = _run_cli(["task", "list", exp_id], env=env)
    assert r_list.returncode == 0
    items = json.loads(r_list.stdout)
    assert len(items) == 1

    r_show = _run_cli(
        ["task", "show", f"{exp_id}:{task_id}"], env=env
    )
    assert r_show.returncode == 0
    payload = json.loads(r_show.stdout)
    assert payload["task_id"] == task_id
    assert payload["mode"] == "seed"


def test_task_delete_removes_dir(env: dict, tmp_path: Path) -> None:
    exp_id = _mk_exp(env)
    r = _run_cli(["task", "create", exp_id, "first"], env=env)
    task_id = json.loads(r.stdout)["task_id"]
    task_path = tmp_path / exp_id / "tasks" / task_id
    assert task_path.exists()

    r_del = _run_cli(
        ["task", "delete", f"{exp_id}:{task_id}", "--yes"], env=env
    )
    assert r_del.returncode == 0
    assert not task_path.exists()


def test_continuation_requires_from_task(env: dict) -> None:
    exp_id = _mk_exp(env)
    _run_cli(["task", "create", exp_id, "seed"], env=env)
    r = _run_cli(
        ["task", "create", exp_id, "fb", "--continuation"], env=env
    )
    assert r.returncode != 0
    assert "requires at least one --from-task" in (r.stderr + r.stdout)


def test_continuation_rejects_nonexistent_from_task(env: dict) -> None:
    exp_id = _mk_exp(env)
    r = _run_cli(
        [
            "task",
            "create",
            exp_id,
            "fb",
            "--continuation",
            "--from-task",
            "001-nope",
        ],
        env=env,
    )
    assert r.returncode != 0
    assert "not found" in (r.stderr + r.stdout).lower()


def test_continuation_with_valid_parent(env: dict, tmp_path: Path) -> None:
    exp_id = _mk_exp(env)
    r1 = _run_cli(["task", "create", exp_id, "seed"], env=env)
    seed_id = json.loads(r1.stdout)["task_id"]
    # Fake a BEST/ directory so R37 parent-has-BEST check passes.
    best = tmp_path / exp_id / "tasks" / seed_id / "BEST"
    best.mkdir(parents=True)
    (best / "manifest.json").write_text('{"winner_run_id":"dummy"}')

    r2 = _run_cli(
        [
            "task",
            "create",
            exp_id,
            "improve",
            "--continuation",
            "--from-task",
            seed_id,
            "--primary",
            "BEST/",
        ],
        env=env,
    )
    assert r2.returncode == 0, r2.stderr + r2.stdout
    task_id = json.loads(r2.stdout)["task_id"]
    assert task_id.startswith("002-")
    manifest = json.loads(
        (tmp_path / exp_id / "tasks" / task_id / "task.json").read_text()
    )
    assert manifest["mode"] == "continuation"
    assert manifest["user_feedback"] == "improve"
    assert manifest["inputs"][0]["from_task"] == seed_id
    assert manifest["inputs"][0]["role"] == "primary"
    assert manifest["inputs"][0]["bundle"] == "BEST/"


def test_continuation_reference_paths(env: dict, tmp_path: Path) -> None:
    exp_id = _mk_exp(env)
    r1 = _run_cli(["task", "create", exp_id, "seed"], env=env)
    seed_id = json.loads(r1.stdout)["task_id"]
    best = tmp_path / exp_id / "tasks" / seed_id / "BEST"
    best.mkdir(parents=True)
    (best / "manifest.json").write_text("{}")

    r2 = _run_cli(
        [
            "task",
            "create",
            exp_id,
            "improve",
            "--continuation",
            "--from-task",
            seed_id,
            "--primary",
            "BEST/",
            "--reference",
            "BEST/analysis/facts.json",
        ],
        env=env,
    )
    assert r2.returncode == 0, r2.stderr + r2.stdout
    task_id = json.loads(r2.stdout)["task_id"]
    manifest = json.loads(
        (tmp_path / exp_id / "tasks" / task_id / "task.json").read_text()
    )
    roles = [inp["role"] for inp in manifest["inputs"]]
    assert "primary" in roles
    assert "reference" in roles
