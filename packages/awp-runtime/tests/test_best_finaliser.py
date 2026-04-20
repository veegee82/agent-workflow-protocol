"""Tests for the BEST finaliser."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from awp.outer_loop.best_finaliser import compute_and_update_best


def _mk_run_dir(
    base: Path,
    run_id: str,
    status: str = "complete",
    eval_score: float = 0.8,
    gate_rejections: int = 0,
) -> Path:
    """Build a minimal run_dir with a run_completion.json + FINAL/."""
    run_dir = base / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "FINAL").mkdir(exist_ok=True)
    (run_dir / "FINAL" / "paper.md").write_text(f"draft from {run_id}")
    completion = {
        "run_id": run_id,
        "status": status,
        "task": "t",
        "final_budget": {"loops": {"used": 1, "cap": 10}, "tokens": {"used": 1000, "cap": 100000}},
        "eval": {"score": eval_score},
        "critique": {"defects": []},
        "gate_rejections": gate_rejections,
    }
    (run_dir / "run_completion.json").write_text(json.dumps(completion))
    (run_dir / "events.jsonl").write_text("")
    (run_dir / "metrics.jsonl").write_text("")
    return run_dir


def test_first_run_becomes_best(tmp_path: Path) -> None:
    task_dir = tmp_path / "task"
    task_dir.mkdir()
    run = _mk_run_dir(task_dir / "seed" / "output", "run1", eval_score=0.8)

    result = compute_and_update_best(task_dir=task_dir, new_run_dir=run)

    assert result.updated is True
    assert result.reason == "auto_loss"
    manifest_path = task_dir / "BEST" / "manifest.json"
    assert manifest_path.exists()
    manifest = json.loads(manifest_path.read_text())
    assert manifest["winner_run_id"] == "run1"
    assert manifest["reason"] == "auto_loss"
    assert manifest["loss"] == pytest.approx(result.new_loss)
    assert (task_dir / "BEST" / "paper.md").exists()


def test_lower_loss_wins(tmp_path: Path) -> None:
    task_dir = tmp_path / "task"
    task_dir.mkdir()
    run1 = _mk_run_dir(task_dir / "seed" / "output", "run1", eval_score=0.5)
    compute_and_update_best(task_dir=task_dir, new_run_dir=run1)
    run2 = _mk_run_dir(task_dir / "seed" / "output", "run2", eval_score=0.95, gate_rejections=0)

    result = compute_and_update_best(task_dir=task_dir, new_run_dir=run2)

    assert result.updated is True
    manifest = json.loads((task_dir / "BEST" / "manifest.json").read_text())
    assert manifest["winner_run_id"] == "run2"
    assert (task_dir / "BEST" / "paper.md").read_text() == "draft from run2"


def test_higher_loss_does_not_win(tmp_path: Path) -> None:
    task_dir = tmp_path / "task"
    task_dir.mkdir()
    run1 = _mk_run_dir(task_dir / "seed" / "output", "run1", eval_score=0.95)
    compute_and_update_best(task_dir=task_dir, new_run_dir=run1)
    run2 = _mk_run_dir(task_dir / "seed" / "output", "run2", eval_score=0.1)

    result = compute_and_update_best(task_dir=task_dir, new_run_dir=run2)

    assert result.updated is False
    manifest = json.loads((task_dir / "BEST" / "manifest.json").read_text())
    assert manifest["winner_run_id"] == "run1"


def test_user_override_is_preserved(tmp_path: Path) -> None:
    task_dir = tmp_path / "task"
    task_dir.mkdir()
    run1 = _mk_run_dir(task_dir / "seed" / "output", "run1", eval_score=0.5)
    compute_and_update_best(task_dir=task_dir, new_run_dir=run1)
    manifest_path = task_dir / "BEST" / "manifest.json"
    m = json.loads(manifest_path.read_text())
    m["reason"] = "user_override"
    manifest_path.write_text(json.dumps(m))

    run2 = _mk_run_dir(task_dir / "seed" / "output", "run2", eval_score=0.99)
    result = compute_and_update_best(task_dir=task_dir, new_run_dir=run2)

    assert result.updated is False
    assert result.skip_reason == "user_override"
    m2 = json.loads(manifest_path.read_text())
    assert m2["winner_run_id"] == "run1"
    assert m2["reason"] == "user_override"


def test_force_override_replaces_any(tmp_path: Path) -> None:
    task_dir = tmp_path / "task"
    task_dir.mkdir()
    run1 = _mk_run_dir(task_dir / "seed" / "output", "run1", eval_score=0.95)
    compute_and_update_best(task_dir=task_dir, new_run_dir=run1)
    run2 = _mk_run_dir(task_dir / "seed" / "output", "run2", eval_score=0.1)

    result = compute_and_update_best(
        task_dir=task_dir,
        new_run_dir=run2,
        force_override=True,
    )

    assert result.updated is True
    assert result.reason == "user_override"
    m = json.loads((task_dir / "BEST" / "manifest.json").read_text())
    assert m["winner_run_id"] == "run2"
    assert m["reason"] == "user_override"


def test_non_terminal_run_is_skipped(tmp_path: Path) -> None:
    task_dir = tmp_path / "task"
    task_dir.mkdir()
    run = _mk_run_dir(task_dir / "seed" / "output", "run1", status="failed")

    result = compute_and_update_best(task_dir=task_dir, new_run_dir=run)

    assert result.updated is False
    assert result.skip_reason == "non_terminal"
    assert not (task_dir / "BEST" / "manifest.json").exists()


def test_workspace_level_final_is_found(tmp_path: Path) -> None:
    """AgentWorkflow writes FINAL at <workspace>/output/FINAL/ (not <run>/FINAL/).

    Build that layout and verify compute_and_update_best still promotes the
    deliverables to <task>/BEST/.
    """
    task_dir = tmp_path / "task"
    task_dir.mkdir()
    workspace = task_dir / "seed"
    run_dir = workspace / "workspace" / "runs" / "run1"
    run_dir.mkdir(parents=True)
    (run_dir / "run_completion.json").write_text(json.dumps({
        "run_id": "run1", "status": "complete", "task": "t",
        "final_budget": {"loops": {"used": 1, "cap": 10}, "tokens": {"used": 1, "cap": 100}},
        "eval": {"score": 0.9}, "critique": {"defects": []}, "gate_rejections": 0,
    }))
    (run_dir / "events.jsonl").write_text("")
    (run_dir / "metrics.jsonl").write_text("")
    # FINAL lives at workspace level, NOT under run_dir
    workspace_final = workspace / "output" / "FINAL"
    workspace_final.mkdir(parents=True)
    (workspace_final / "paper.md").write_text("workspace-level deliverable")

    result = compute_and_update_best(task_dir=task_dir, new_run_dir=run_dir)

    assert result.updated is True
    # BEST/paper.md should now be hardlinked from the workspace-level FINAL
    assert (task_dir / "BEST" / "paper.md").exists()
    assert (task_dir / "BEST" / "paper.md").read_text() == "workspace-level deliverable"
