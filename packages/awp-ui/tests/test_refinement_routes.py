"""Tests for the refinement REST API endpoints.

Mocks RefinementLoop so no real LLM calls are made; only the routing
contract (status codes, payload shapes) is asserted here.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from httpx import AsyncClient


def _make_partial_seed(tmp_path: Path) -> Path:
    seed = tmp_path / "seed"
    (seed / "FINAL").mkdir(parents=True)
    (seed / "FINAL" / "paper.md").write_text("# seed\n", encoding="utf-8")
    (seed / "run_completion.json").write_text(
        json.dumps(
            {
                "run_id": "run_seed",
                "status": "partial",
                "task": "test task",
                "critique": {
                    "defects": [{"summary": "missing", "severity": "high"}]
                },
                "evaluation": {
                    "per_metric": {"q": 0.5},
                    "thresholds": {"q": 0.9},
                    "total_score": 0.5,
                },
            }
        ),
        encoding="utf-8",
    )
    (seed / "events.jsonl").write_text("", encoding="utf-8")
    return seed


async def _register_seed_run(
    app, store, seed_dir: Path, run_id: str = "run_seed"
) -> str:
    """Insert a synthetic run row whose result.metadata.run_dir points at seed_dir."""
    await store.save_run(
        run_id=run_id,
        task="test task",
        model="openai/gpt-5-mini",
        status="partial",
        config={"task": "test task", "model": "openai/gpt-5-mini"},
    )
    await store.update_run(
        run_id=run_id,
        result={
            "status": "partial",
            "metadata": {
                "run_id": run_id,
                "run_dir": str(seed_dir),
                "workspace": str(seed_dir.parent),
            },
        },
    )
    return run_id


@pytest.mark.asyncio
async def test_refine_endpoint_accepts_valid_iterations(
    client: AsyncClient, app, store, temp_dir: Path
) -> None:
    seed = _make_partial_seed(temp_dir)
    run_id = await _register_seed_run(app, store, seed)

    # Stub RefinementLoop.run so no real LLM call happens.
    from awp.refinement import loop as loop_mod

    def fake_run(self, *, iterations):
        class R:
            session_id = "refine_STUB"
            seed_run_id = "run_seed"
            seed_loss = 0.5
            best_iter = 1
            best_loss = 0.3
            stop_reason = "max_iterations"
            iterations: list = []

        return R()

    with patch.object(loop_mod.RefinementLoop, "run", fake_run):
        resp = await client.post(
            f"/api/experiments/{run_id}/refine",
            json={"iterations": 2, "model": None, "worker_model": None},
        )
    assert resp.status_code == 202, resp.text
    data = resp.json()
    assert "session_id" in data
    assert data["session_id"].startswith("refine_")
    assert data["status"] == "running"


@pytest.mark.asyncio
async def test_refine_endpoint_rejects_out_of_range_iterations(
    client: AsyncClient, app, store, temp_dir: Path
) -> None:
    seed = _make_partial_seed(temp_dir)
    run_id = await _register_seed_run(app, store, seed)

    resp = await client.post(
        f"/api/experiments/{run_id}/refine",
        json={"iterations": 11},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_refine_endpoint_404_on_missing_run(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/experiments/does_not_exist/refine",
        json={"iterations": 2},
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Tier handling — spec 2026-04-20 §10
# ---------------------------------------------------------------------------


class _CapturingLoopStub:
    """Replacement for RefinementLoop that records its kwargs.

    The real constructor call is intercepted in `__init__`; `run` is a
    no-op so no real LLM call happens.
    """

    last: "dict" = {}

    def __init__(self, **kwargs):
        _CapturingLoopStub.last = dict(kwargs)

    def run(self, *, iterations):
        class R:
            session_id = "refine_CAPTURED"
            seed_run_id = "run_seed"
            seed_loss = 0.5
            best_iter = 0
            best_loss = 0.5
            stop_reason = "max_iterations"
            iterations: list = []

        return R()


@pytest.mark.asyncio
async def test_refine_endpoint_legacy_body_takes_legacy_path(
    client: AsyncClient, app, store, temp_dir: Path, caplog
) -> None:
    """Case (a): body without tier_* → legacy path, no warning."""
    seed = _make_partial_seed(temp_dir)
    run_id = await _register_seed_run(app, store, seed)

    from awp.refinement import loop as loop_mod

    with patch.object(loop_mod, "RefinementLoop", _CapturingLoopStub):
        with caplog.at_level("WARNING"):
            resp = await client.post(
                f"/api/experiments/{run_id}/refine",
                json={
                    "iterations": 2,
                    "model": "legacy_mgr",
                    "worker_model": "legacy_wkr",
                },
            )

    assert resp.status_code == 202
    assert _CapturingLoopStub.last["tier_plan"] is None
    assert _CapturingLoopStub.last["model"] == "legacy_mgr"
    assert _CapturingLoopStub.last["worker_model"] == "legacy_wkr"
    assert not any("refinement.mixed_body" in rec.message for rec in caplog.records)


@pytest.mark.asyncio
async def test_refine_endpoint_tier_high_only_builds_plan(
    client: AsyncClient, app, store, temp_dir: Path
) -> None:
    """Case (b): ``tier_high`` only → TierPlan constructed, seed fallback set."""
    seed = _make_partial_seed(temp_dir)
    run_id = await _register_seed_run(app, store, seed)

    from awp.refinement import loop as loop_mod

    with patch.object(loop_mod, "RefinementLoop", _CapturingLoopStub):
        resp = await client.post(
            f"/api/experiments/{run_id}/refine",
            json={
                "iterations": 3,
                "tier_high": {"manager": "high_mgr", "worker": "high_wkr"},
            },
        )

    assert resp.status_code == 202
    call = _CapturingLoopStub.last
    assert call["model"] is None
    assert call["worker_model"] is None
    plan = call["tier_plan"]
    assert plan is not None
    assert plan.high.manager == "high_mgr"
    assert plan.high.worker == "high_wkr"
    # low + mid stay empty → seed fallback applies per §7
    assert (plan.low.manager, plan.low.worker) == (None, None)
    assert (plan.mid.manager, plan.mid.worker) == (None, None)
    # seed fallback was parsed from run_completion.json (no model keys
    # in the synthetic seed → both stay None, matching §12 row).
    assert plan.seed_manager is None
    assert plan.seed_worker is None


@pytest.mark.asyncio
async def test_refine_endpoint_mixed_body_tiers_win_and_warning_emitted(
    client: AsyncClient, app, store, temp_dir: Path, caplog
) -> None:
    """Case (c): ``model`` + ``tier_*`` present → tier_* wins, warning emitted."""
    seed = _make_partial_seed(temp_dir)
    run_id = await _register_seed_run(app, store, seed)

    from awp.refinement import loop as loop_mod

    with patch.object(loop_mod, "RefinementLoop", _CapturingLoopStub):
        with caplog.at_level("WARNING"):
            resp = await client.post(
                f"/api/experiments/{run_id}/refine",
                json={
                    "iterations": 2,
                    "model": "legacy_mgr",
                    "worker_model": "legacy_wkr",
                    "tier_high": {"manager": "high_mgr", "worker": "high_wkr"},
                },
            )

    assert resp.status_code == 202
    call = _CapturingLoopStub.last
    # Tier wins: legacy fields are fully ignored on the construction path.
    assert call["model"] is None
    assert call["worker_model"] is None
    assert call["tier_plan"] is not None
    assert call["tier_plan"].high.manager == "high_mgr"
    # Warning present.
    assert any("refinement.mixed_body" in rec.message for rec in caplog.records)


@pytest.mark.asyncio
async def test_refine_endpoint_all_tiers_empty_still_builds_plan(
    client: AsyncClient, app, store, temp_dir: Path
) -> None:
    """§12 last row: every tier present but all sub-fields empty → tiered
    path is still exercised; every iteration resolves to the seed pair.
    """
    seed = _make_partial_seed(temp_dir)
    run_id = await _register_seed_run(app, store, seed)

    from awp.refinement import loop as loop_mod

    with patch.object(loop_mod, "RefinementLoop", _CapturingLoopStub):
        resp = await client.post(
            f"/api/experiments/{run_id}/refine",
            json={
                "iterations": 3,
                "tier_low": {"manager": "", "worker": ""},
                "tier_mid": {"manager": "", "worker": ""},
                "tier_high": {"manager": "", "worker": ""},
            },
        )

    assert resp.status_code == 202
    plan = _CapturingLoopStub.last["tier_plan"]
    assert plan is not None
    assert plan.is_trivial() is True


@pytest.mark.asyncio
async def test_refinement_sessions_endpoint_returns_sessions_and_best(
    client: AsyncClient, app, store, temp_dir: Path
) -> None:
    seed = _make_partial_seed(temp_dir)
    # Write a session sidecar and a BEST manifest so the GET has something.
    (seed / "refinement_sessions").mkdir()
    (seed / "refinement_sessions" / "refine_123.json").write_text(
        json.dumps(
            {
                "session_id": "refine_123",
                "seed_run_id": "run_seed",
                "best_iter": 1,
                "stop_reason": "max_iterations",
                "iterations": [
                    {"k": 1, "run_id": "iter_1", "loss": 0.3, "status": "complete"}
                ],
            }
        ),
        encoding="utf-8",
    )
    (seed / "BEST").mkdir()
    (seed / "BEST" / "manifest.json").write_text(
        json.dumps(
            {
                "best_run_id": "iter_1",
                "best_loss": 0.3,
                "seed_loss": 0.5,
                "session_id": "refine_123",
            }
        ),
        encoding="utf-8",
    )

    run_id = await _register_seed_run(app, store, seed)
    resp = await client.get(f"/api/experiments/{run_id}/refinement_sessions")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "sessions" in data
    assert len(data["sessions"]) == 1
    assert data["sessions"][0]["session_id"] == "refine_123"
    assert data["best"] is not None
    assert data["best"]["best_run_id"] == "iter_1"
