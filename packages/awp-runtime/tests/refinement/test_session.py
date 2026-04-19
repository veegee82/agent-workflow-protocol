"""Unit tests for RefinementSession sidecar + BEST pointer writers."""

from __future__ import annotations

import json
from pathlib import Path

from awp.refinement.session import (
    RefinementIteration,
    RefinementSession,
    write_best_pointer,
    write_session_sidecar,
)


def _make_fake_iteration_dir(root: Path, run_id: str, payload: dict) -> Path:
    d = root / run_id
    (d / "FINAL").mkdir(parents=True)
    (d / "FINAL" / "paper.md").write_text(f"# Paper from {run_id}\n", encoding="utf-8")
    (d / "run_completion.json").write_text(json.dumps(payload), encoding="utf-8")
    return d


def test_session_sidecar_written_to_seed_dir(tmp_path: Path) -> None:
    seed = tmp_path / "seed"
    seed.mkdir()
    session = RefinementSession(
        session_id="refine_20260419T153000Z",
        seed_run_id="run_seed",
        started_at="2026-04-19T15:30:00Z",
        completed_at="2026-04-19T15:40:00Z",
        stop_reason="max_iterations",
        best_iter=2,
        iterations=[
            RefinementIteration(k=1, run_id="run_iter_1", loss=0.42, status="partial"),
            RefinementIteration(k=2, run_id="run_iter_2", loss=0.31, status="complete"),
        ],
    )
    path = write_session_sidecar(seed_run_dir=seed, session=session)
    assert path.exists()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["best_iter"] == 2
    assert data["iterations"][1]["run_id"] == "run_iter_2"


def test_best_pointer_contains_manifest_and_winner_files(tmp_path: Path) -> None:
    seed = tmp_path / "seed"
    seed.mkdir()
    iterations_root = tmp_path / "iterations"
    win = _make_fake_iteration_dir(iterations_root, "run_iter_2", {"run_id": "run_iter_2"})

    write_best_pointer(
        seed_run_dir=seed,
        winning_run_dir=win,
        session_id="refine_20260419T153000Z",
        best_loss=0.31,
        seed_loss=0.47,
    )

    best = seed / "BEST"
    manifest = json.loads((best / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["best_run_id"] == "run_iter_2"
    assert manifest["best_loss"] == 0.31
    assert manifest["seed_loss"] == 0.47
    assert (best / "paper.md").read_text(encoding="utf-8") == "# Paper from run_iter_2\n"


def test_best_pointer_only_overwrites_on_improvement(tmp_path: Path) -> None:
    seed = tmp_path / "seed"
    seed.mkdir()
    iterations_root = tmp_path / "iterations"

    win_a = _make_fake_iteration_dir(iterations_root, "run_iter_A", {"run_id": "run_iter_A"})
    write_best_pointer(
        seed_run_dir=seed,
        winning_run_dir=win_a,
        session_id="A",
        best_loss=0.30,
        seed_loss=0.50,
    )

    win_b = _make_fake_iteration_dir(iterations_root, "run_iter_B", {"run_id": "run_iter_B"})
    write_best_pointer(
        seed_run_dir=seed,
        winning_run_dir=win_b,
        session_id="B",
        best_loss=0.40,
        seed_loss=0.50,
    )

    manifest = json.loads((seed / "BEST" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["best_run_id"] == "run_iter_A", "BEST must not regress"


def test_best_pointer_overwrites_when_new_loss_is_lower(tmp_path: Path) -> None:
    seed = tmp_path / "seed"
    seed.mkdir()
    iterations_root = tmp_path / "iterations"

    win_a = _make_fake_iteration_dir(iterations_root, "run_iter_A", {"run_id": "run_iter_A"})
    write_best_pointer(
        seed_run_dir=seed,
        winning_run_dir=win_a,
        session_id="A",
        best_loss=0.40,
        seed_loss=0.50,
    )

    win_b = _make_fake_iteration_dir(iterations_root, "run_iter_B", {"run_id": "run_iter_B"})
    write_best_pointer(
        seed_run_dir=seed,
        winning_run_dir=win_b,
        session_id="B",
        best_loss=0.25,
        seed_loss=0.50,
    )

    manifest = json.loads((seed / "BEST" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["best_run_id"] == "run_iter_B"
