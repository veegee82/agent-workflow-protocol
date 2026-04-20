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


class _PartialNoFinalWorkflow:
    """Stub that simulates a ``partial`` iteration which produces NO FINAL/.

    Mirrors the real-world failure mode: delegation loop hits a budget cap
    or a late-stage gate-chain rejection before the file-writing step,
    so ``output/<run_id>/`` is empty and ``_ensure_final_dir`` has nothing
    to promote. Before the fallback fix this would abort the loop at iter 2
    with ``no_prior_deliverable``.
    """

    def __init__(self, losses: list[float]) -> None:
        self._losses = iter(losses)

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
        # Deliberately do NOT create FINAL/, and create an EMPTY output/<run_id>/
        # to mirror a partial iter that produced no deliverable (budget cap
        # hit before the file-writing gate).
        run_id = f"run_iter_{output_dir.name}"
        (output_dir / "output" / run_id).mkdir(parents=True, exist_ok=True)
        loss = next(self._losses)
        (output_dir / "run_completion.json").write_text(
            json.dumps(
                {
                    "run_id": run_id,
                    "status": "partial",
                    "confidence": 0.4,
                    "parent_run_id": parent_run_id,
                    "tags": tags,
                    "task": "write a paper",
                    "loss_total": loss,
                    # Keep gradient non-empty so the empty-gradient short
                    # circuit doesn't mask the behavior we're testing.
                    "critique": {"defects": [{"summary": "still rough", "severity": "high"}]},
                    "evaluation": {
                        "total_score": 1.0 - loss,
                        "per_metric": {"q": 1.0 - loss},
                        "thresholds": {"q": 0.99},
                    },
                }
            ),
            encoding="utf-8",
        )
        (output_dir / "events.jsonl").write_text("", encoding="utf-8")
        return run_id, output_dir


def test_loop_reseeds_from_last_good_when_iter_produces_no_final(
    monkeypatch, tmp_path: Path, caplog
) -> None:
    """Partial iterations with no FINAL/ MUST NOT abort the chain.

    Structural fix (spec 2026-04-20 §13.5 follow-up): the refinement loop
    tracks a ``last_good_final`` pointer initialized to the seed's FINAL/.
    When iter k fails to produce a non-empty FINAL/, iter k+1 re-seeds
    from ``last_good_final`` instead of aborting with ``no_prior_deliverable``.
    This is especially important for tiered refinement: a low-tier
    iteration that runs out of budget before writing deliverables must
    not prevent the mid/high tiers from getting a shot at the same seed.
    """
    seed = _make_seed(tmp_path)
    # Seed_loss=0.7; three partial-no-FINAL iterations with distinct losses
    # so neither plateau nor regression short-circuits first.
    _patch_loss(monkeypatch, [0.6, 0.55, 0.50])

    workflow = _PartialNoFinalWorkflow(losses=[0.6, 0.55, 0.50])

    import logging as _logging
    caplog.set_level(_logging.INFO, logger="awp.refinement.loop")

    loop = RefinementLoop(
        seed_run_dir=seed,
        workflow_factory=workflow,
        iterations_root=tmp_path / "iters",
    )
    result = loop.run(iterations=3)

    # With the fallback: all 3 iterations run; stop_reason is
    # max_iterations (not no_prior_deliverable).
    assert result.stop_reason == "max_iterations", (
        f"expected max_iterations, got {result.stop_reason!r}"
    )
    assert len(result.iterations) == 3
    # The reseed log fires starting at iter 2 (iter 1 seeds directly from
    # the seed's FINAL, iter 2+ is where the fallback kicks in).
    reseed_records = [r for r in caplog.records if "reseed_from_last_good" in r.getMessage()]
    assert len(reseed_records) >= 2, (
        f"expected ≥2 reseed log entries (iter 2 and iter 3), "
        f"got {len(reseed_records)}: {[r.getMessage() for r in reseed_records]}"
    )
