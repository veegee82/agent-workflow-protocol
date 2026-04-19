"""Unit tests for RefinementLoop orchestration — stubbed workflow factory."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from awp.refinement.loop import (
    NothingToRefine,
    RefinementLoop,
    RefinementResult,
)


def _make_seed(tmp_path: Path, *, with_gradient: bool = True) -> Path:
    seed = tmp_path / "seed"
    (seed / "FINAL").mkdir(parents=True)
    (seed / "FINAL" / "paper.md").write_text("# seed\n", encoding="utf-8")
    critique = (
        {"defects": [{"summary": "missing", "severity": "high"}]}
        if with_gradient
        else {"defects": []}
    )
    eval_ = (
        {
            "per_metric": {"m1": 0.5},
            "thresholds": {"m1": 0.9},
            "total_score": 0.5,
        }
        if with_gradient
        else {
            "per_metric": {"m1": 1.0},
            "thresholds": {"m1": 0.5},
            "total_score": 1.0,
        }
    )
    (seed / "run_completion.json").write_text(
        json.dumps(
            {
                "run_id": "run_seed",
                "status": "partial" if with_gradient else "complete",
                "confidence": 0.6 if with_gradient else 1.0,
                "task": "write a paper",
                "critique": critique,
                "evaluation": eval_,
            }
        ),
        encoding="utf-8",
    )
    (seed / "events.jsonl").write_text("", encoding="utf-8")
    return seed


class StubWorkflow:
    """Stand-in for AgentWorkflow that writes a minimal run_completion.json."""

    def __init__(self, losses: list[float], statuses: list[str] | None = None):
        self._losses = iter(losses)
        self._statuses = iter(statuses or ["partial"] * len(losses))

    def __call__(
        self,
        *,
        task: str,
        inputs,
        initial_state,
        output_dir: Path,
        parent_run_id,
        tags,
        manager_prompt_prefix,
        budget,
        model,
        worker_model,
    ):
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "FINAL").mkdir(exist_ok=True)
        (output_dir / "FINAL" / "paper.md").write_text("# improved\n", encoding="utf-8")
        loss = next(self._losses)
        status = next(self._statuses)
        run_id = f"run_iter_{output_dir.name}"
        (output_dir / "run_completion.json").write_text(
            json.dumps(
                {
                    "run_id": run_id,
                    "status": status,
                    "confidence": 0.8,
                    "parent_run_id": parent_run_id,
                    "tags": tags,
                    "task": "write a paper",
                    "loss_total": loss,
                    # Non-empty gradient signal so extract_gradient stays
                    # non-empty for subsequent iterations; the loop's
                    # stop-condition state machine is what we're testing,
                    # not the empty-gradient short-circuit.
                    "critique": {"defects": [{"summary": "still needs polish", "severity": "low"}]},
                    "evaluation": {
                        "total_score": 1.0 - loss,
                        "per_metric": {"q": max(0.0, 1.0 - loss)},
                        "thresholds": {"q": 0.99},
                    },
                }
            ),
            encoding="utf-8",
        )
        (output_dir / "events.jsonl").write_text("", encoding="utf-8")
        return run_id, output_dir


def _patch_loss(
    monkeypatch,
    scripted_losses: list[float],
    *,
    seed_loss: float = 0.7,
) -> None:
    """Patch compute_run_loss. First value goes to the seed read; the rest
    are doled out to iterations in order."""
    losses = iter([seed_loss] + list(scripted_losses))
    from awp.refinement import loop as loop_mod

    def fake_compute(run_dir, *args, **kwargs):
        class B:
            total = next(losses)
            raw_signals: dict = {}

        return B()

    monkeypatch.setattr(loop_mod, "compute_run_loss", fake_compute)


def test_loop_runs_until_max_iterations(monkeypatch, tmp_path: Path) -> None:
    seed = _make_seed(tmp_path)
    _patch_loss(monkeypatch, [0.5, 0.4, 0.3])

    workflow = StubWorkflow(losses=[0.5, 0.4, 0.3])
    loop = RefinementLoop(
        seed_run_dir=seed,
        workflow_factory=workflow,
        iterations_root=tmp_path / "iters",
    )
    result: RefinementResult = loop.run(iterations=3)

    assert result.stop_reason == "max_iterations"
    assert len(result.iterations) == 3
    assert result.best_iter == 3


def test_loop_stops_on_regression_after_two_worse_iterations(monkeypatch, tmp_path: Path) -> None:
    seed = _make_seed(tmp_path)
    # iter 1 improves, iter 2 regresses, iter 3 regresses → stop.
    _patch_loss(monkeypatch, [0.3, 0.4, 0.5])

    workflow = StubWorkflow(losses=[0.3, 0.4, 0.5])
    loop = RefinementLoop(
        seed_run_dir=seed,
        workflow_factory=workflow,
        iterations_root=tmp_path / "iters",
    )
    result = loop.run(iterations=5)

    assert result.stop_reason == "regression"
    assert result.best_iter == 1
    assert len(result.iterations) == 3  # stopped after 3, did not run 4-5


def test_loop_stops_on_plateau(monkeypatch, tmp_path: Path) -> None:
    seed = _make_seed(tmp_path)
    # 0.40 → 0.395 → 0.394 → deltas <0.01 twice in a row.
    _patch_loss(monkeypatch, [0.40, 0.395, 0.394])

    workflow = StubWorkflow(losses=[0.40, 0.395, 0.394])
    loop = RefinementLoop(
        seed_run_dir=seed,
        workflow_factory=workflow,
        iterations_root=tmp_path / "iters",
    )
    result = loop.run(iterations=5)
    assert result.stop_reason == "plateau"


def test_loop_aborts_on_empty_gradient(tmp_path: Path) -> None:
    seed = _make_seed(tmp_path, with_gradient=False)
    loop = RefinementLoop(
        seed_run_dir=seed,
        workflow_factory=lambda **_: None,
        iterations_root=tmp_path / "iters",
    )
    with pytest.raises(NothingToRefine):
        loop.run(iterations=2)


def test_loop_writes_gradient_input_and_r36_is_enforced(monkeypatch, tmp_path: Path) -> None:
    seed = _make_seed(tmp_path)
    _patch_loss(monkeypatch, [0.3])

    workflow = StubWorkflow(losses=[0.3])
    loop = RefinementLoop(
        seed_run_dir=seed,
        workflow_factory=workflow,
        iterations_root=tmp_path / "iters",
    )
    loop.run(iterations=1)

    # R36: gradient_input.json must have been persisted before iter 1 ran.
    iter1_dir = next((tmp_path / "iters").iterdir())
    assert (iter1_dir / "gradient_input.json").exists()
    content = json.loads((iter1_dir / "gradient_input.json").read_text(encoding="utf-8"))
    assert content["defects"], "gradient must carry defects"


def test_loop_parent_run_id_chain(monkeypatch, tmp_path: Path) -> None:
    seed = _make_seed(tmp_path)
    _patch_loss(monkeypatch, [0.4, 0.3])

    workflow = StubWorkflow(losses=[0.4, 0.3])
    loop = RefinementLoop(
        seed_run_dir=seed,
        workflow_factory=workflow,
        iterations_root=tmp_path / "iters",
    )
    result = loop.run(iterations=2)

    assert result.iterations[0].parent_run_id == "run_seed"
    assert result.iterations[1].parent_run_id == result.iterations[0].run_id
