"""E2E test for awp refine — the north star for the refinement implementation plan.

This test is progressively un-skipped as tasks land. Each task's
'E2E Progress' acceptance line maps to a concrete assertion or a
removed `pytest.skip`.

Tags: ["e2e", "refinement", "critique"]
Budget: >=25 loops / 3M tokens / 1h wall-time across the whole session.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest

pytestmark = pytest.mark.e2e


E2E_BASE = Path("/tmp/awp-experiments/e2e-refinement")
SEED_RUN_DIR = E2E_BASE / "seed"


def _has_llm_key() -> bool:
    return any(
        os.environ.get(k)
        for k in ("OPENROUTER_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY")
    )


@pytest.fixture(scope="module")
def seed_run_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Produce (or reuse) a seed run that lands at `partial` with a critique-detectable defect.

    Task 15 replaces this body with a real AgentWorkflow run. For now
    the fixture raises so sub-tests skip cleanly until wired up.
    """
    pytest.skip("seed run fixture not yet wired (Task 15)")


# -- Assertions the plan's tasks light up one by one --


def test_e2e_seed_run_has_expected_artifacts(seed_run_dir: Path) -> None:
    """Baseline: seed completed with FINAL/ and a non-trivial loss."""
    assert (seed_run_dir / "run_completion.json").exists()
    assert (seed_run_dir / "FINAL").exists()
    assert any((seed_run_dir / "FINAL").iterdir())


def test_e2e_gradient_is_non_empty(seed_run_dir: Path) -> None:
    """After Task 2: gradient extraction finds at least one defect/rejection/eval delta."""
    from awp.refinement.gradient import extract_gradient

    gradient = extract_gradient(seed_run_dir)
    assert gradient.is_non_empty(), f"seed gradient was empty: {gradient}"


def test_e2e_refinement_prefix_includes_defects(seed_run_dir: Path) -> None:
    """After Task 3: prefix template renders with defect bullets."""
    from awp.refinement.gradient import extract_gradient, render_refinement_prefix

    gradient = extract_gradient(seed_run_dir)
    prefix = render_refinement_prefix(gradient)
    assert "REFINEMENT CONTEXT" in prefix
    assert "Objective:" in prefix


def test_e2e_seed_workspace_prepared_for_iteration(
    seed_run_dir: Path, tmp_path: Path
) -> None:
    """After Task 4: workspace prep copies/hard-links FINAL into input/."""
    from awp.refinement.seed import prepare_iteration_workspace

    workspace = tmp_path / "iter_1"
    prepare_iteration_workspace(
        workspace_dir=workspace,
        prior_final_dir=seed_run_dir / "FINAL",
    )
    assert (workspace / "input").exists()
    assert any((workspace / "input").iterdir())


def test_e2e_budget_halved_per_iteration() -> None:
    """After Task 5: budget scaler halves counts with floor clamps."""
    from awp.refinement.budget import budget_for_iteration

    out = budget_for_iteration(
        seed_budget={
            "max_loops": 20,
            "max_total_workers": 40,
            "max_total_tokens": 1_000_000,
            "max_wall_time": 3600,
            "max_depth": 4,
        },
        observed_wall_time=1800,
    )
    assert out["max_loops"] == 10
    assert out["max_total_workers"] == 20
    assert out["max_total_tokens"] == 500_000
    assert out["max_wall_time"] == 900
    assert out["max_depth"] == 4


def test_e2e_manager_prefix_reaches_first_iteration_user_message(
    seed_run_dir: Path, tmp_path: Path
) -> None:
    """After Task 6: DelegationLoopRunner injects prefix into iteration-1 user message only."""
    pytest.skip("unit-verified in Task 6; this E2E hook is covered by test_loop.py")


def test_e2e_iteration_has_parent_run_id_chain(seed_run_dir: Path) -> None:
    """After Task 8: iteration runs carry parent_run_id pointing at seed or prior iter."""
    session = _load_latest_session(seed_run_dir)
    iter1_run_dir = _find_iteration_run_dir(session["iterations"][0]["run_id"])
    rc = json.loads((iter1_run_dir / "run_completion.json").read_text())
    assert rc["parent_run_id"] == session["seed_run_id"]
    if len(session["iterations"]) >= 2:
        iter2_run_dir = _find_iteration_run_dir(session["iterations"][1]["run_id"])
        rc2 = json.loads((iter2_run_dir / "run_completion.json").read_text())
        assert rc2["parent_run_id"] == session["iterations"][0]["run_id"]


def test_e2e_best_pointer_and_session_sidecar_exist(seed_run_dir: Path) -> None:
    """After Task 9: seed/BEST/ and seed/refinement_sessions/<ts>.json are written."""
    assert (seed_run_dir / "BEST" / "manifest.json").exists()
    sessions = list((seed_run_dir / "refinement_sessions").glob("*.json"))
    assert sessions, "at least one session sidecar required"


def test_e2e_r36_aborts_on_empty_gradient(tmp_path: Path) -> None:
    """After Task 10: a completed-perfect seed yields 'nothing to refine' exit 0."""
    from awp.refinement.loop import RefinementLoop, NothingToRefine

    fake_seed = tmp_path / "perfect_seed"
    fake_seed.mkdir()
    (fake_seed / "FINAL").mkdir()
    (fake_seed / "run_completion.json").write_text(
        json.dumps({
            "status": "complete",
            "confidence": 1.0,
            "critique": {"defects": []},
            "evaluation": {"per_metric": {}, "total_score": 1.0},
        }),
        encoding="utf-8",
    )
    (fake_seed / "events.jsonl").write_text("", encoding="utf-8")

    loop = RefinementLoop(seed_run_dir=fake_seed)
    with pytest.raises(NothingToRefine):
        loop.run(iterations=2)


def test_e2e_cli_invocation_produces_session(seed_run_dir: Path) -> None:
    """After Task 11: `awp refine <seed>` creates a new session + BEST/."""
    # Verified in test_cli.py with a stubbed workflow. The real-LLM
    # assertion lives below in test_e2e_final_refinement_reduces_loss.
    pass


def test_e2e_final_refinement_reduces_loss(seed_run_dir: Path) -> None:
    """Task 15 terminal assertion: BEST/ has strictly lower loss than seed."""
    if not _has_llm_key():
        pytest.skip("real LLM required; no key configured")
    from awp.outer_loop.loss import compute_run_loss

    session = _load_latest_session(seed_run_dir)
    best_iter_run_id = session["iterations"][session["best_iter"] - 1]["run_id"]
    best_run_dir = _find_iteration_run_dir(best_iter_run_id)

    seed_loss = compute_run_loss(seed_run_dir).total
    best_loss = compute_run_loss(best_run_dir).total
    assert best_loss < seed_loss, f"refinement did not reduce loss: {best_loss} >= {seed_loss}"


# -- Helpers (stub until Task 15 fills them in) --


def _load_latest_session(seed_run_dir: Path) -> dict:
    sessions = sorted((seed_run_dir / "refinement_sessions").glob("*.json"))
    assert sessions, "no refinement session found"
    return json.loads(sessions[-1].read_text(encoding="utf-8"))


def _find_iteration_run_dir(run_id: str) -> Path:
    """Locate an iteration's run directory by run_id.

    Implemented in Task 15 once the experiment root layout is concrete.
    """
    roots = [Path("/tmp/awp-experiments"), Path.home() / ".awp" / "experiments"]
    for root in roots:
        if not root.exists():
            continue
        for p in root.rglob("run_completion.json"):
            data = json.loads(p.read_text(encoding="utf-8"))
            if data.get("run_id") == run_id:
                return p.parent
    raise FileNotFoundError(f"no run dir for {run_id}")
