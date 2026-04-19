"""Release D-2 — reservation-based token budget tests.

Covers the ``token_budget_reservation`` toggle on
:class:`DelegationLoopConfig` and the corresponding reserve / commit /
release API on :class:`BudgetSnapshot`:

* Happy path roundtrip — reserve, commit, state returns clean.
* Over-budget rejection — ``reserve_tokens`` returns ``None`` and does
  not mutate ``pending_reserved``.
* Release on failure — reservation held, call failed, pending counter
  returns to zero.
* Parallel race — 20 threads reserve+commit concurrently, effective
  budget holds; the legacy consume-after-call path would overshoot.
* Double-commit tolerance — second commit for the same handle logs a
  warning but preserves actual usage.
* Flag off — ``LLMClient`` with budget unwired leaves
  ``pending_reserved`` untouched; totals match the legacy path.
* Flag on integration — parallel workers against a mock LLM respect the
  cap and leave no stale reservations.
"""

from __future__ import annotations

import threading
import time
from typing import Any

import pytest

from awp.runtime.delegation_loop_runner import (
    BudgetExceededError,
    BudgetSnapshot,
    TokenReservation,
    estimate_llm_tokens,
)
from awp.runtime.llm import LLMClient


class _FakeBudgetCfg:
    """Minimal stand-in for ``DelegationBudget``.

    ``BudgetSnapshot`` only reads a handful of attributes; constructing
    the real Pydantic model would pull in unrelated orchestration config.
    """

    def __init__(self, max_total_tokens: int = 10_000) -> None:
        self.max_loops = 100
        self.max_total_workers = 100
        self.max_total_tokens = max_total_tokens
        self.max_wall_time = 600
        self.max_tool_calls = 1000
        self.max_depth = 3
        self.max_concurrent_submanagers = 3
        self.max_total_submanagers_per_run = 6
        self.max_workers_per_iteration = 6
        self.max_rejected_completions = 2


def _fresh_budget(max_tokens: int = 10_000) -> BudgetSnapshot:
    return BudgetSnapshot(_FakeBudgetCfg(max_total_tokens=max_tokens))


# ---------------------------------------------------------------------------
# 1. Reserve / commit roundtrip
# ---------------------------------------------------------------------------


class TestReservationRoundtrip:
    def test_reserve_then_commit_updates_counters(self):
        budget = _fresh_budget(max_tokens=10_000)
        reservation = budget.reserve_tokens(500)
        assert isinstance(reservation, TokenReservation)
        assert budget._pending_reserved == 500
        assert budget.tokens_consumed == 0
        budget.commit_tokens(reservation, 450)
        assert budget._pending_reserved == 0
        assert budget.tokens_consumed == 450
        assert budget._active_reservations == {}

    def test_multiple_reservations_accumulate_pending(self):
        budget = _fresh_budget(max_tokens=10_000)
        r1 = budget.reserve_tokens(300)
        r2 = budget.reserve_tokens(200)
        assert r1 is not None and r2 is not None
        assert budget._pending_reserved == 500
        budget.commit_tokens(r1, 250)
        assert budget._pending_reserved == 200
        budget.commit_tokens(r2, 150)
        assert budget._pending_reserved == 0
        assert budget.tokens_consumed == 400


# ---------------------------------------------------------------------------
# 2. Over-budget rejection
# ---------------------------------------------------------------------------


class TestOverBudgetRejection:
    def test_reserve_rejects_when_sum_exceeds_cap(self):
        budget = _fresh_budget(max_tokens=1000)
        # Pre-load tokens_consumed so headroom is 100.
        budget.tokens_consumed = 900
        assert budget.reserve_tokens(200) is None
        # Rejection must not mutate pending counters.
        assert budget._pending_reserved == 0
        assert budget._active_reservations == {}
        # Fitting reservation still works.
        r = budget.reserve_tokens(100)
        assert r is not None
        assert budget._pending_reserved == 100

    def test_pending_plus_consumed_forms_effective_ceiling(self):
        budget = _fresh_budget(max_tokens=1000)
        r1 = budget.reserve_tokens(600)
        assert r1 is not None
        # Headroom is now 400 regardless of tokens_consumed.
        assert budget.reserve_tokens(500) is None
        r2 = budget.reserve_tokens(400)
        assert r2 is not None


# ---------------------------------------------------------------------------
# 3. Release on failure
# ---------------------------------------------------------------------------


class TestReleaseOnFailure:
    def test_release_restores_pending(self):
        budget = _fresh_budget(max_tokens=1000)
        r = budget.reserve_tokens(300)
        assert r is not None
        budget.release_reservation(r)
        assert budget._pending_reserved == 0
        assert budget.tokens_consumed == 0

    def test_release_then_commit_is_noop_on_pending(self):
        """Second disposition of a handle must not drive pending negative."""
        budget = _fresh_budget(max_tokens=1000)
        r = budget.reserve_tokens(300)
        assert r is not None
        budget.release_reservation(r)
        # commit after release: double-commit path → only tokens_consumed bumps
        budget.commit_tokens(r, 250)
        assert budget._pending_reserved == 0
        assert budget.tokens_consumed == 250


# ---------------------------------------------------------------------------
# 4. Race — the headline test
# ---------------------------------------------------------------------------


class TestReservationRace:
    def test_parallel_reservations_cannot_exceed_cap(self):
        budget = _fresh_budget(max_tokens=1500)
        succeeded: list[TokenReservation] = []
        failed = 0
        lock = threading.Lock()

        def _worker() -> None:
            nonlocal failed
            r = budget.reserve_tokens(100)
            if r is None:
                with lock:
                    failed += 1
                return
            # simulate HTTP call completing with actual=100
            budget.commit_tokens(r, 100)
            with lock:
                succeeded.append(r)

        threads = [threading.Thread(target=_worker) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Exactly 15 reservations must succeed (1500 / 100).
        assert len(succeeded) == 15
        assert failed == 5
        assert budget.tokens_consumed == 1500
        assert budget._pending_reserved == 0
        assert budget._active_reservations == {}

    def test_without_reservation_parallel_overshoots(self):
        """Counterfactual: the legacy consume-after-call path overshoots.

        Uses a barrier to force every thread to observe the budget
        *before* any of them has recorded. This is exactly the race
        reservation-based accounting is designed to prevent: each thread
        reads ``tokens_consumed=0``, decides 'budget ok', then fires its
        LLM call; all N actual usages land at the end and the cap is
        blown past.
        """
        budget = _fresh_budget(max_tokens=1500)
        n_threads = 20
        # Barrier ensures all threads take the check-decision in lockstep.
        barrier = threading.Barrier(n_threads)

        def _worker() -> None:
            # All threads read the same pre-call state.
            barrier.wait()
            ok, _ = budget.can_continue()
            if not ok:
                return
            # Simulate the LLM call sitting between check and record —
            # in production this is a multi-second HTTP round-trip, long
            # enough that every concurrent thread takes its decision
            # against the same (pre-record) snapshot.
            time.sleep(0.05)
            budget.record_tokens(100)

        threads = [threading.Thread(target=_worker) for _ in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # 20 threads × 100 tokens = 2000 > 1500 cap. The legacy path has
        # no mechanism to prevent this; only reservation does.
        assert budget.tokens_consumed == 2000
        assert budget.tokens_consumed > budget.max_total_tokens


# ---------------------------------------------------------------------------
# 5. Double-commit tolerance
# ---------------------------------------------------------------------------


class TestDoubleCommit:
    def test_double_commit_logs_and_records_actual(self, caplog):
        budget = _fresh_budget(max_tokens=1000)
        r = budget.reserve_tokens(200)
        assert r is not None
        budget.commit_tokens(r, 180)
        with caplog.at_level("WARNING"):
            budget.commit_tokens(r, 50)
        # First commit released reservation; second added to consumed.
        assert budget.tokens_consumed == 180 + 50
        assert budget._pending_reserved == 0
        assert any(
            "commit_tokens" in rec.message and "double-commit" in rec.message
            for rec in caplog.records
        )


# ---------------------------------------------------------------------------
# 6. Flag-off keeps legacy accounting
# ---------------------------------------------------------------------------


class _StubResponse:
    def __init__(self, total_tokens: int) -> None:
        self._total = total_tokens

    def raise_for_status(self) -> None:  # noqa: D401
        return None

    def json(self) -> dict[str, Any]:
        return {
            "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
            "usage": {"total_tokens": self._total},
        }


def _install_stub_http(monkeypatch: pytest.MonkeyPatch, llm: LLMClient, total: int) -> None:
    """Replace the client's HTTP POST with a deterministic in-memory stub."""

    def _fake_post(url: str, *, json: dict, headers: dict):  # noqa: ARG001
        return _StubResponse(total)

    monkeypatch.setattr(llm._client, "post", _fake_post)


class TestFlagOff:
    def test_legacy_path_leaves_pending_reserved_at_zero(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        budget = _fresh_budget(max_tokens=10_000)
        llm = LLMClient(api_key="k", base_url="http://x", model="gpt-4o")
        # Intentionally NOT calling set_budget — flag off.
        _install_stub_http(monkeypatch, llm, total=500)
        for _ in range(3):
            llm.chat([{"role": "user", "content": "hi"}])
        assert budget._pending_reserved == 0
        assert budget._active_reservations == {}
        # Caller-side record_tokens is still the way token usage lands.
        budget.record_tokens(llm.total_tokens_used)
        assert budget.tokens_consumed == 1500


# ---------------------------------------------------------------------------
# 7. Flag-on integration with parallel workers
# ---------------------------------------------------------------------------


class TestFlagOnIntegration:
    def test_parallel_workers_respect_budget(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        budget = _fresh_budget(max_tokens=5000)
        # Each call consumes exactly 500 actual tokens, regardless of
        # estimate — mirrors real LLM behaviour where the estimate can be
        # off but the response usage is authoritative.
        actuals: list[int] = []
        rejected = 0
        lock = threading.Lock()

        def _spawn_worker() -> None:
            nonlocal rejected
            llm = LLMClient(api_key="k", base_url="http://x", model="gpt-4o")
            llm.set_budget(budget, reservation_enabled=True, default_max_output_tokens=200)
            _install_stub_http(monkeypatch, llm, total=500)
            try:
                llm.chat([{"role": "user", "content": "tiny prompt"}])
                with lock:
                    actuals.append(500)
            except BudgetExceededError:
                with lock:
                    rejected += 1

        threads = [threading.Thread(target=_spawn_worker) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Effective budget must hold — actual tokens never exceed cap.
        assert budget.tokens_consumed == sum(actuals)
        assert budget.tokens_consumed <= budget.max_total_tokens
        # No stale reservations leak.
        assert budget._pending_reserved == 0
        assert budget._active_reservations == {}
        # Some calls must have succeeded and some must have been rejected
        # pre-LLM (this is the entire point of the feature).
        assert len(actuals) > 0
        assert rejected > 0

    def test_http_failure_releases_reservation(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        budget = _fresh_budget(max_tokens=1000)
        llm = LLMClient(api_key="k", base_url="http://x", model="gpt-4o")
        llm.set_budget(budget, reservation_enabled=True, default_max_output_tokens=100)

        def _boom(url: str, *, json: dict, headers: dict):  # noqa: ARG001
            raise RuntimeError("simulated network error")

        monkeypatch.setattr(llm._client, "post", _boom)

        with pytest.raises(RuntimeError):
            llm.chat([{"role": "user", "content": "will fail"}])

        # Release path must wipe the reservation even though the call blew up.
        assert budget._pending_reserved == 0
        assert budget._active_reservations == {}
        assert budget.tokens_consumed == 0


# ---------------------------------------------------------------------------
# 8. Estimate heuristic
# ---------------------------------------------------------------------------


class TestEstimateHeuristic:
    def test_estimate_scales_with_prompt_length(self):
        short = estimate_llm_tokens("hi", max_output_tokens=100)
        long = estimate_llm_tokens("x" * 4000, max_output_tokens=100)
        # input_estimate: ~0 vs 1000 → long must be ~1000 more.
        assert long - short >= 900

    def test_estimate_uses_default_output_cap(self):
        est = estimate_llm_tokens("hello", max_output_tokens=None)
        # Default output cap is 4096; input at 1 token minimum.
        assert est >= 4096
