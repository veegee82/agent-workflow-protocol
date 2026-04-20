"""Integration tests for RefinementLoop + TierPlan wiring.

Spec: ``docs/superpowers/specs/2026-04-20-refinement-model-tiers-design.md``
§13.2 (cases A / B / C). The workflow factory is stubbed so no LLM call
happens; the factory records every ``(model, worker_model)`` pair it
receives and the test asserts the sequence against the spec tables.
"""

from __future__ import annotations

import json
from pathlib import Path

from awp.refinement.loop import RefinementLoop
from awp.refinement.tiers import ModelPair, TierPlan


def _make_seed(tmp_path: Path) -> Path:
    """Seed with a non-empty gradient and a known positive loss.

    Same shape as ``test_loop._make_seed(with_gradient=True)`` — kept local
    so this test file does not depend on the neighbouring test module's
    private helpers.
    """
    seed = tmp_path / "seed"
    (seed / "FINAL").mkdir(parents=True)
    (seed / "FINAL" / "paper.md").write_text("# seed\n", encoding="utf-8")
    (seed / "run_completion.json").write_text(
        json.dumps(
            {
                "run_id": "run_seed",
                "status": "partial",
                "confidence": 0.6,
                "task": "write a paper",
                "critique": {"defects": [{"summary": "missing", "severity": "high"}]},
                "evaluation": {
                    "per_metric": {"m1": 0.5},
                    "thresholds": {"m1": 0.9},
                    "total_score": 0.5,
                },
            }
        ),
        encoding="utf-8",
    )
    (seed / "events.jsonl").write_text("", encoding="utf-8")
    return seed


class RecordingFactory:
    """Stub workflow factory — records every model pair it sees.

    Also writes a minimal ``run_completion.json`` so the loop's loss/status
    readers can proceed. ``scripted_losses`` must be long enough for every
    iteration the loop will execute.
    """

    def __init__(self, scripted_losses: list[float]) -> None:
        self._losses = iter(scripted_losses)
        self.calls: list[dict] = []

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
        self.calls.append({"model": model, "worker_model": worker_model})

        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "FINAL").mkdir(exist_ok=True)
        (output_dir / "FINAL" / "paper.md").write_text("# improved\n", encoding="utf-8")

        loss = next(self._losses)
        run_id = f"run_iter_{output_dir.name}"
        (output_dir / "run_completion.json").write_text(
            json.dumps(
                {
                    "run_id": run_id,
                    "status": "partial",
                    "confidence": 0.8,
                    "parent_run_id": parent_run_id,
                    "tags": tags,
                    "task": "write a paper",
                    "loss_total": loss,
                    # Keep the gradient non-empty across iterations so the
                    # loop does not short-circuit on "empty_gradient_midloop".
                    "critique": {
                        "defects": [
                            {"summary": "still needs polish", "severity": "low"}
                        ]
                    },
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


def _patch_loss(monkeypatch, scripted_losses: list[float], *, seed_loss: float = 0.7) -> None:
    """Patch ``compute_run_loss`` in the refinement loop module.

    Seed read is consumed first, then iterations in order.
    """
    losses = iter([seed_loss] + list(scripted_losses))
    from awp.refinement import loop as loop_mod

    def fake_compute(run_dir, *args, **kwargs):
        class B:
            total = next(losses)
            raw_signals: dict = {}

        return B()

    monkeypatch.setattr(loop_mod, "compute_run_loss", fake_compute)


# ---------------------------------------------------------------------------
# Case A — tier_plan=None → legacy path (regression proof for §13.3 mechanic)
# ---------------------------------------------------------------------------


def test_case_a_tier_plan_none_uses_legacy_single_model(
    monkeypatch, tmp_path: Path
) -> None:
    seed = _make_seed(tmp_path)
    _patch_loss(monkeypatch, [0.5, 0.4, 0.3])

    factory = RecordingFactory(scripted_losses=[0.5, 0.4, 0.3])
    loop = RefinementLoop(
        seed_run_dir=seed,
        workflow_factory=factory,
        iterations_root=tmp_path / "iters",
        model="session_manager_model",
        worker_model="session_worker_model",
        tier_plan=None,
    )
    result = loop.run(iterations=3)

    assert len(result.iterations) == 3
    assert len(factory.calls) == 3
    for call in factory.calls:
        assert call["model"] == "session_manager_model"
        assert call["worker_model"] == "session_worker_model"

    # IterationOutcome carries the model pair for observability but
    # ``tier`` stays None on the legacy path (spec §8 / §11).
    for outcome in result.iterations:
        assert outcome.tier is None
        assert outcome.model_manager == "session_manager_model"
        assert outcome.model_worker == "session_worker_model"


# ---------------------------------------------------------------------------
# Case B — 3 iterations, all tiers fully set → (L, M, H) per §5 table
# ---------------------------------------------------------------------------


def test_case_b_three_iterations_full_tiers(monkeypatch, tmp_path: Path) -> None:
    seed = _make_seed(tmp_path)
    _patch_loss(monkeypatch, [0.5, 0.4, 0.3])

    plan = TierPlan(
        low=ModelPair(manager="low_mgr", worker="low_wkr"),
        mid=ModelPair(manager="mid_mgr", worker="mid_wkr"),
        high=ModelPair(manager="high_mgr", worker="high_wkr"),
        seed_manager="seed_mgr",
        seed_worker="seed_wkr",
    )

    factory = RecordingFactory(scripted_losses=[0.5, 0.4, 0.3])
    loop = RefinementLoop(
        seed_run_dir=seed,
        workflow_factory=factory,
        iterations_root=tmp_path / "iters",
        tier_plan=plan,
    )
    result = loop.run(iterations=3)

    assert len(factory.calls) == 3
    assert factory.calls[0] == {"model": "low_mgr", "worker_model": "low_wkr"}
    assert factory.calls[1] == {"model": "mid_mgr", "worker_model": "mid_wkr"}
    assert factory.calls[2] == {"model": "high_mgr", "worker_model": "high_wkr"}

    # Outcomes carry both tier + model pair.
    assert [o.tier for o in result.iterations] == ["low", "mid", "high"]
    assert [o.model_manager for o in result.iterations] == [
        "low_mgr",
        "mid_mgr",
        "high_mgr",
    ]
    assert [o.model_worker for o in result.iterations] == [
        "low_wkr",
        "mid_wkr",
        "high_wkr",
    ]


# ---------------------------------------------------------------------------
# Case C — 5 iterations, only `high` set → seed fallback for iter 1-4, user's
# high pair for iter 5. Per §5 table (N=5: L, L, M, M, H) combined with §7.
# ---------------------------------------------------------------------------


def test_case_c_five_iterations_only_high_set(monkeypatch, tmp_path: Path) -> None:
    seed = _make_seed(tmp_path)
    _patch_loss(monkeypatch, [0.5, 0.4, 0.3, 0.2, 0.1])

    plan = TierPlan(
        # low + mid intentionally empty → fall back to seed for every
        # iteration that resolves to those tiers.
        low=ModelPair(),
        mid=ModelPair(),
        high=ModelPair(manager="high_mgr", worker="high_wkr"),
        seed_manager="seed_mgr",
        seed_worker="seed_wkr",
    )

    factory = RecordingFactory(scripted_losses=[0.5, 0.4, 0.3, 0.2, 0.1])
    loop = RefinementLoop(
        seed_run_dir=seed,
        workflow_factory=factory,
        iterations_root=tmp_path / "iters",
        tier_plan=plan,
    )
    result = loop.run(iterations=5)

    assert len(factory.calls) == 5
    # N=5 mapping: [L, L, M, M, H]. L and M fall back to seed (per §7).
    assert factory.calls[0] == {"model": "seed_mgr", "worker_model": "seed_wkr"}  # low
    assert factory.calls[1] == {"model": "seed_mgr", "worker_model": "seed_wkr"}  # low
    assert factory.calls[2] == {"model": "seed_mgr", "worker_model": "seed_wkr"}  # mid
    assert factory.calls[3] == {"model": "seed_mgr", "worker_model": "seed_wkr"}  # mid
    assert factory.calls[4] == {"model": "high_mgr", "worker_model": "high_wkr"}  # high

    assert [o.tier for o in result.iterations] == ["low", "low", "mid", "mid", "high"]
