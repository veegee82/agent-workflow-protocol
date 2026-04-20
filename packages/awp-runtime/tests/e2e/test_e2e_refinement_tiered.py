"""E2E test for ``awp refine`` with model tiering (spec 2026-04-20 §13.5).

Tags: ``["e2e", "refinement", "tiered"]``

Proves the tiered refinement code path closes end-to-end with real LLMs:

1. ``tier_plan_used == true`` on the session sidecar.
2. ``iterations[0..2].tier == ["low", "mid", "high"]`` (spec §5, N=3).
3. ``iterations[k].model_manager`` / ``.model_worker`` match the TierPlan
   entries we passed via ``--tier-*`` flags (no seed fallback required in
   this test — every tier ships both models).
4. Every iteration's terminal ``status`` is a known AWP status.
5. The session reaches a known terminal ``stop_reason`` — the tiered path
   does not crash silently.

Seed strategy: reuses the cached seed produced by ``test_e2e_refinement.py``
(pointer at ``/tmp/awp-experiments/e2e-refinement/seed_run_dir.txt``). If the
pointer is missing, the test skips with a message directing the runner to
populate the seed first — this avoids burning ~30 min of LLM tokens per E2E
invocation when a reusable seed already exists on disk.

Tier choice (three distinct model strings so the routing assertion is
sharp; all three are CLAUDE.md-documented and OpenRouter-routable):

* low  — ``deepseek/deepseek-chat-v3.1`` / ``deepseek/deepseek-chat-v3.1``
* mid  — ``openai/gpt-5-mini``          / ``deepseek/deepseek-chat-v3.1``
* high — ``anthropic/claude-sonnet-4-6``/ ``deepseek/deepseek-chat-v3.1``
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = [pytest.mark.e2e]


SEED_BASE = Path("/tmp/awp-experiments/e2e-refinement")
SEED_POINTER = SEED_BASE / "seed_run_dir.txt"

TIER_LOW_MANAGER = "deepseek/deepseek-chat-v3.1"
TIER_LOW_WORKER = "deepseek/deepseek-chat-v3.1"
TIER_MID_MANAGER = "openai/gpt-5-mini"
TIER_MID_WORKER = "deepseek/deepseek-chat-v3.1"
TIER_HIGH_MANAGER = "anthropic/claude-sonnet-4-6"
TIER_HIGH_WORKER = "deepseek/deepseek-chat-v3.1"

# Hard cap per refinement session: 3 iterations * (halved seed budget) fits
# comfortably under 40 minutes on gpt-5-mini / claude-sonnet / deepseek-v3.
REFINE_TIMEOUT_SECONDS = 2400


def _has_llm_key() -> bool:
    return any(
        os.environ.get(k)
        for k in ("OPENROUTER_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY")
    )


def _resolve_cached_seed() -> Path | None:
    """Return the cached seed run_dir if the pointer exists and is usable."""
    if not SEED_POINTER.exists():
        return None
    try:
        candidate = Path(SEED_POINTER.read_text(encoding="utf-8").strip())
    except OSError:
        return None
    if not candidate.exists():
        return None
    if not (candidate / "run_completion.json").exists():
        return None
    if not (candidate / "FINAL").exists():
        return None
    if not any((candidate / "FINAL").iterdir()):
        return None
    return candidate


def _latest_tiered_session(seed_run_dir: Path) -> dict | None:
    """Return the most recent session sidecar that was driven by a TierPlan.

    Falls back to ``None`` if no tiered session exists yet. Used as a cache
    key so repeated test invocations do not re-run the refinement.
    """
    d = seed_run_dir / "refinement_sessions"
    if not d.exists():
        return None
    for path in sorted(d.glob("*.json"), reverse=True):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if data.get("tier_plan_used") is True:
            return data
    return None


@pytest.fixture(scope="module")
def seed_run_dir() -> Path:
    if not _has_llm_key():
        pytest.skip("real LLM required; no key configured")
    cached = _resolve_cached_seed()
    if cached is None:
        pytest.skip(
            f"no cached seed run found at {SEED_POINTER}. "
            "Run the sibling E2E first to populate it: "
            "`pytest packages/awp-runtime/tests/e2e/test_e2e_refinement.py`. "
            "Re-using the existing seed avoids burning ~30 min of LLM tokens."
        )
    return cached


@pytest.fixture(scope="module")
def tiered_session(seed_run_dir: Path) -> dict:
    """Run ``awp refine --tier-*`` once (N=3), or reuse the latest tiered
    session sidecar on the seed if one already exists.

    The tiered and non-tiered sessions co-exist under the seed's
    ``refinement_sessions/`` directory; they are distinguishable via the
    ``tier_plan_used`` flag so the cache lookup is unambiguous.
    """
    if not _has_llm_key():
        pytest.skip("real LLM required; no key configured")

    existing = _latest_tiered_session(seed_run_dir)
    if existing is not None:
        return existing

    awp_bin = shutil.which("awp") or "awp"
    cmd = [
        awp_bin,
        "refine",
        str(seed_run_dir),
        "--iterations",
        "3",
        "--tier-low",
        f"{TIER_LOW_MANAGER}:{TIER_LOW_WORKER}",
        "--tier-mid",
        f"{TIER_MID_MANAGER}:{TIER_MID_WORKER}",
        "--tier-high",
        f"{TIER_HIGH_MANAGER}:{TIER_HIGH_WORKER}",
    ]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=REFINE_TIMEOUT_SECONDS,
    )
    # `awp refine` returns:
    #   0 on improvement (BEST/ updated) OR empty gradient ("nothing to refine")
    #   1 on no improvement across iterations
    #   2 on setup failure (missing seed, no FINAL/, etc.)
    assert result.returncode in (0, 1), (
        f"awp refine exited {result.returncode}\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )

    session = _latest_tiered_session(seed_run_dir)
    assert session is not None, (
        f"no tiered session sidecar produced under "
        f"{seed_run_dir}/refinement_sessions after awp refine"
    )
    return session


# -- Assertions (spec §13.5) --------------------------------------------------


def test_tiered_session_uses_tier_plan(tiered_session: dict) -> None:
    """Assertion 1: the session was driven by a TierPlan, not the legacy path."""
    assert tiered_session.get("tier_plan_used") is True, (
        f"tier_plan_used was {tiered_session.get('tier_plan_used')!r} — "
        "expected True (session should have taken the tiered code path)"
    )


def test_tiered_session_ran_all_three_iterations(tiered_session: dict) -> None:
    """Strong assertion: N=3 requested, 3 iterations must actually have run.

    This proves that a ``partial`` iter with no fresh deliverable does NOT
    abort the chain via ``no_prior_deliverable`` (the last_good_final
    fallback fix). Without the fix, a low-tier iter that doesn't write
    output would kill the chain at iter 2 and the L→M→H ordering would
    never be exercised end-to-end.
    """
    iters = tiered_session.get("iterations", [])
    assert len(iters) == 3, (
        f"N=3 requested but session recorded {len(iters)} iteration(s); "
        f"stop_reason={tiered_session.get('stop_reason')!r}. "
        f"A count < 3 indicates the chain aborted prematurely — "
        f"likely ``no_prior_deliverable`` on iter 2+."
    )


def test_tiered_mapping_is_low_mid_high_in_order(tiered_session: dict) -> None:
    """Assertion 2 (spec §5, N=3): k=1 → low, k=2 → mid, k=3 → high."""
    expected = ["low", "mid", "high"]
    iters = tiered_session.get("iterations", [])
    assert len(iters) >= len(expected), (
        f"need {len(expected)} iterations to verify full L→M→H mapping, "
        f"got {len(iters)}"
    )
    for i, expected_tier in enumerate(expected):
        actual = iters[i]
        assert actual.get("tier") == expected_tier, (
            f"iteration k={i + 1}: tier was "
            f"{actual.get('tier')!r}, expected {expected_tier!r}"
        )


def test_tiered_models_resolve_per_tier(tiered_session: dict) -> None:
    """Assertion 3: each iteration's resolved model_manager / model_worker
    matches the TierPlan entries we passed via ``--tier-*`` flags.

    Every tier in this test provides both manager and worker, so no seed
    fallback is exercised — the resolved values must equal the CLI args
    exactly.
    """
    expected_pairs = [
        (TIER_LOW_MANAGER, TIER_LOW_WORKER),
        (TIER_MID_MANAGER, TIER_MID_WORKER),
        (TIER_HIGH_MANAGER, TIER_HIGH_WORKER),
    ]
    iters = tiered_session.get("iterations", [])
    for i, actual in enumerate(iters):
        if i >= len(expected_pairs):
            pytest.fail(
                f"session has {len(iters)} iterations; plan expected at most "
                f"{len(expected_pairs)}"
            )
        em, ew = expected_pairs[i]
        assert actual.get("model_manager") == em, (
            f"iter k={i + 1}: model_manager was "
            f"{actual.get('model_manager')!r}, expected {em!r}"
        )
        assert actual.get("model_worker") == ew, (
            f"iter k={i + 1}: model_worker was "
            f"{actual.get('model_worker')!r}, expected {ew!r}"
        )


def test_tiered_iteration_statuses_are_terminal(tiered_session: dict) -> None:
    """Assertion 4: every recorded iteration ended in a valid AWP status."""
    valid = {"complete", "partial", "failed", "aborted"}
    iters = tiered_session.get("iterations", [])
    for i, actual in enumerate(iters):
        status = actual.get("status")
        assert status in valid, (
            f"iter k={i + 1}: status={status!r} not in {valid}"
        )


def test_tiered_session_closes_with_known_stop_reason(tiered_session: dict) -> None:
    """Assertion 5: the session reaches a stop_reason AWP recognises.

    Smoke assertion (deliberately does NOT require ``best_iter > 0``):
    a short residual may legitimately plateau before improvement. The
    point of this E2E is to prove the tiered code path closes normally —
    loss-reduction is already asserted by ``test_e2e_refinement.py`` for
    the non-tiered path, and the tiering change is routing-only, not
    loss-changing.
    """
    stop = tiered_session.get("stop_reason", "")
    assert isinstance(stop, str) and stop, (
        f"stop_reason was {stop!r} — must be a non-empty string"
    )
    known = {
        "max_iterations",
        "regression",
        "plateau",
        "wall_time_exhausted",
        "empty_gradient_midloop",
        "no_prior_deliverable",
    }
    assert stop in known or stop.startswith("error:"), (
        f"unexpected stop_reason: {stop!r}"
    )
    best_iter = tiered_session.get("best_iter", 0)
    assert isinstance(best_iter, int) and best_iter >= 0, (
        f"best_iter was {best_iter!r} — must be a non-negative int"
    )
