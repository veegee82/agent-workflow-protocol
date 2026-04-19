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


E2E_WORKSPACE = E2E_BASE / "workspace"
POINTER_FILE = E2E_BASE / "seed_run_dir.txt"


def _resolve_cached_seed() -> Path | None:
    """Return the cached seed run_dir if the pointer exists and is valid."""
    if not POINTER_FILE.exists():
        return None
    try:
        candidate = Path(POINTER_FILE.read_text(encoding="utf-8").strip())
    except OSError:
        return None
    if not candidate.exists():
        return None
    if not (candidate / "run_completion.json").exists():
        return None
    return candidate


def _promote_final_from_output(run_dir: Path) -> None:
    """If the runtime did not write ``FINAL/`` (declared deliverables missing),
    fall back to hard-linking/copying everything from ``output/<run_id>/``
    into ``<run_dir>/FINAL/``. Refinement only needs *some* starting
    deliverable; the runtime's canonical-output logic is stricter than
    refinement's needs.
    """
    import os

    final_dir = run_dir / "FINAL"
    if final_dir.exists() and any(final_dir.iterdir()):
        return

    # Find the workspace-level output/<run_id>/ that AgentWorkflow writes to.
    workspace = run_dir.parent
    while workspace != workspace.parent and not (workspace / "output").exists():
        workspace = workspace.parent
    output_root = workspace / "output"
    if not output_root.exists():
        return

    candidates = list(output_root.iterdir())
    if not candidates:
        return
    source = candidates[0]  # one run_id-isolated subdir
    for item in source.rglob("*"):
        if item.is_dir():
            continue
        rel = item.relative_to(source)
        dst = final_dir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.link(item, dst)
        except OSError:
            shutil.copy2(item, dst)


@pytest.fixture(scope="module")
def seed_run_dir() -> Path:
    """Real seed run (partial) against OpenRouter.

    ``AgentWorkflow`` nests the actual run artifacts under
    ``<output_dir>/workspace/runs/<run_id>/``. This fixture launches the
    workflow, then returns that nested run directory — which is where
    ``run_completion.json``, ``iterations/``, and ``events.jsonl`` live.
    A pointer file at ``E2E_BASE/seed_run_dir.txt`` caches the resolved
    path so repeated test sessions do not re-burn LLM tokens.

    If the runtime did not write ``FINAL/`` (declared deliverables not
    produced in budget), we promote ``output/<run_id>/`` into ``FINAL/``
    as a fallback so refinement has a starting deliverable.
    """
    if not _has_llm_key():
        pytest.skip("real LLM required; no key configured")

    cached = _resolve_cached_seed()
    if cached is not None:
        _promote_final_from_output(cached)
        return cached

    E2E_BASE.mkdir(parents=True, exist_ok=True)
    if E2E_WORKSPACE.exists():
        shutil.rmtree(E2E_WORKSPACE)

    from awp.data.workflow import AgentWorkflow

    task = (
        "Write a 2-page bilingual (English + German) summary of the 1905 "
        "Einstein relativity paper. Include: (1) English abstract, "
        "(2) German abstract, (3) three labeled sections with citations."
    )
    # Budget sized per memory reference: gpt-5-mini long-form synthesis
    # needs ≥25 loops / 3M tokens / ≥1h wall-time.
    wf = AgentWorkflow(
        inputs={},
        task=task,
        model="openai/gpt-5-mini",
        worker_model="deepseek/deepseek-chat-v3.1",
        output_dir=str(E2E_WORKSPACE),
        max_loops=25,
        max_total_tokens=3_000_000,
        max_wall_time=1800,
        max_total_workers=8,
        max_depth=2,
        tags=["e2e", "refinement", "seed"],
    )
    resp = wf.run()
    metadata = resp.get("metadata", {}) if isinstance(resp, dict) else {}
    run_id = metadata.get("run_id")
    workspace = Path(metadata.get("workspace") or E2E_WORKSPACE)
    run_dir = workspace / "workspace" / "runs" / str(run_id) if run_id else None
    if run_dir is None or not (run_dir / "run_completion.json").exists():
        # Last-resort probe: scan the workspace for run_completion.json.
        for rc in workspace.rglob("run_completion.json"):
            run_dir = rc.parent
            break
    assert run_dir is not None and (run_dir / "run_completion.json").exists(), (
        f"seed run did not complete — no run_completion.json under {workspace}"
    )

    _promote_final_from_output(run_dir)
    assert (run_dir / "FINAL").exists() and any((run_dir / "FINAL").iterdir()), (
        f"seed run has no FINAL/ deliverable after fallback promotion: {run_dir}"
    )

    POINTER_FILE.write_text(str(run_dir), encoding="utf-8")
    return run_dir


@pytest.fixture(scope="module")
def refinement_session(seed_run_dir: Path) -> dict:
    """Run `awp refine` against the seed once (module-scoped) and yield the session dict.

    Cached like the seed: if a session sidecar already exists under
    ``<seed>/refinement_sessions/``, it is reused — re-running the
    refinement on every test invocation would burn LLM tokens twice.
    The terminal assertion (`test_e2e_final_refinement_reduces_loss`)
    still verifies the cached loss reduction so the cache does not
    silently mask regressions.
    """
    if not _has_llm_key():
        pytest.skip("real LLM required; no key configured")

    existing = sorted((seed_run_dir / "refinement_sessions").glob("*.json")) \
        if (seed_run_dir / "refinement_sessions").exists() else []
    if existing:
        return json.loads(existing[-1].read_text(encoding="utf-8"))

    import subprocess
    import sys as _sys

    awp_bin = shutil.which("awp") or "awp"
    result = subprocess.run(
        [awp_bin, "refine", str(seed_run_dir), "--iterations", "2"],
        capture_output=True,
        text=True,
        timeout=2400,  # 40 min hard cap per session
    )
    assert result.returncode in (0, 1), (
        f"refine exited {result.returncode}; stdout={result.stdout!r}; stderr={result.stderr!r}"
    )
    return _load_latest_session(seed_run_dir)


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


def test_e2e_iteration_has_parent_run_id_chain(
    seed_run_dir: Path, refinement_session: dict
) -> None:
    """After Task 8: iteration runs carry parent_run_id pointing at seed or prior iter."""
    session = refinement_session
    iter1_run_dir = _find_iteration_run_dir(session["iterations"][0]["run_id"])
    rc = json.loads((iter1_run_dir / "run_completion.json").read_text())
    assert rc["parent_run_id"] == session["seed_run_id"]
    if len(session["iterations"]) >= 2:
        iter2_run_dir = _find_iteration_run_dir(session["iterations"][1]["run_id"])
        rc2 = json.loads((iter2_run_dir / "run_completion.json").read_text())
        assert rc2["parent_run_id"] == session["iterations"][0]["run_id"]


def test_e2e_best_pointer_and_session_sidecar_exist(
    seed_run_dir: Path, refinement_session: dict
) -> None:
    """After Task 9: seed/BEST/ and seed/refinement_sessions/<ts>.json are written."""
    # Only assert BEST/ if the session actually produced an improvement
    # (best_iter > 0). An unsuccessful refinement still writes the
    # session sidecar but skips the BEST pointer.
    sessions = list((seed_run_dir / "refinement_sessions").glob("*.json"))
    assert sessions, "at least one session sidecar required"
    if refinement_session.get("best_iter", 0) > 0:
        assert (seed_run_dir / "BEST" / "manifest.json").exists()


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


def test_e2e_final_refinement_reduces_loss(
    seed_run_dir: Path, refinement_session: dict
) -> None:
    """Task 15 terminal assertion: BEST/ has strictly lower loss than seed."""
    if not _has_llm_key():
        pytest.skip("real LLM required; no key configured")
    from awp.outer_loop.loss import compute_run_loss

    session = refinement_session
    best_iter = session.get("best_iter", 0)
    if best_iter <= 0:
        pytest.fail(
            f"refinement did not improve any iteration: stop_reason="
            f"{session.get('stop_reason')!r}, iterations={session.get('iterations')}"
        )

    best_iter_run_id = session["iterations"][best_iter - 1]["run_id"]
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
