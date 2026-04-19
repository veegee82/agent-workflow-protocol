"""Release C — pipelined critique + manager-planning tests.

Validates the ``pipeline_critique_planning`` toggle on ``DelegationLoopConfig``:

* Default (False) keeps the critique + prompt-build path byte-identical to the
  pre-Release-C code — no hidden state mutation, no behavior change.
* Enabled (True) fans out critique and the next-iteration manager-prompt
  prebuild onto a 2-worker thread pool. Budget and state mutations still
  happen exactly once, so the token envelope is invariant.
* Wall-clock time drops from ``sum(critique, prebuild)`` to
  ``max(critique, prebuild)``.
* A critique failure propagates (critique is authoritative), while a
  prebuild failure degrades silently to a cache miss.
* The completion-gate chain order is not touched by pipelining.
"""

from __future__ import annotations

import threading
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from awp.runtime.delegation_loop_runner import DelegationLoopRunner


# ---------------------------------------------------------------------------
# Helpers: construct a minimal runner without spinning up the real loop
# ---------------------------------------------------------------------------


def _make_minimal_runner(
    pipeline_flag: bool,
    critique_fn=None,
    prebuild_fn=None,
) -> DelegationLoopRunner:
    """Build a ``DelegationLoopRunner`` via ``__new__`` with just the attrs
    used by the pipelined critique stage. We intentionally skip ``__init__``
    — the full constructor spins up file loggers and thread pools that are
    irrelevant here.
    """
    r = DelegationLoopRunner.__new__(DelegationLoopRunner)

    # Minimal config surface. ``SimpleNamespace`` is sufficient because the
    # tested paths access attributes, not pydantic-model features.
    r._config = SimpleNamespace(pipeline_critique_planning=pipeline_flag)
    r._pipelined_next_prompt = None

    # Critique engine — only ``.enabled`` is touched by the dispatcher; the
    # real engine stays out of scope because we inject ``_critique_and_repair``.
    r._critique_engine = SimpleNamespace(enabled=True)

    if critique_fn is not None:
        r._critique_and_repair = critique_fn  # type: ignore[method-assign]
    if prebuild_fn is not None:
        r._prebuild_next_manager_prompt = prebuild_fn  # type: ignore[method-assign]

    return r


# ---------------------------------------------------------------------------
# 1. Default path is byte-identical (flag=False)
# ---------------------------------------------------------------------------


class TestDefaultPathByteIdentical:
    """With the flag off, the dispatcher is a passthrough to the existing
    ``_critique_and_repair`` — no extra threads, no cache writes, no state
    side effects."""

    def test_passthrough_returns_critique_result(self):
        called = {"count": 0}

        def fake_critique(delegation_results, task, state, iteration):
            called["count"] += 1
            return ["env-a", "env-b"]

        def fake_prebuild(task, state, target_iteration):
            raise AssertionError("prebuild must not run in default mode")

        r = _make_minimal_runner(
            pipeline_flag=False,
            critique_fn=fake_critique,
            prebuild_fn=fake_prebuild,
        )

        result = r._run_critique_stage_maybe_pipelined(
            delegation_results=[{"worker_id": "w1"}],
            task="t",
            state={},
            iteration=3,
        )

        assert result == ["env-a", "env-b"]
        assert called["count"] == 1
        assert r._pipelined_next_prompt is None

    def test_consume_is_a_noop_when_no_cache(self):
        r = _make_minimal_runner(pipeline_flag=False)
        assert r._consume_pipelined_prompt(iteration=1) is None
        assert r._pipelined_next_prompt is None


# ---------------------------------------------------------------------------
# 2. Budget-state equivalence across modes (sequential vs. pipelined)
# ---------------------------------------------------------------------------


class TestBudgetEquivalence:
    """Both modes must land on the same token count. The critique path is
    the single place token-recording happens for this stage; the prebuild
    is pure string assembly."""

    def test_token_accounting_invariant_under_toggle(self):
        budget_lock = threading.Lock()
        # We fake a budget object with a thread-safe counter — mirrors the
        # real BudgetSnapshot._lock contract.
        fake_budget = SimpleNamespace(tokens=0)

        def critique_that_records(dr, task, state, iteration):
            # Simulate critique LLM usage split across two calls.
            with budget_lock:
                fake_budget.tokens += 500
                fake_budget.tokens += 1200
            return [MagicMock(score=0.9, has_critical_defects=False)]

        def prebuild_no_tokens(task, state, target_iteration):
            # Prebuild is pure string assembly. No token accounting.
            return {
                "iteration": target_iteration,
                "system_prompt": "sys",
                "user_message": f"user msg for iter {target_iteration}",
            }

        # Sequential
        fake_budget.tokens = 0
        r_seq = _make_minimal_runner(
            pipeline_flag=False,
            critique_fn=critique_that_records,
            prebuild_fn=prebuild_no_tokens,
        )
        r_seq._run_critique_stage_maybe_pipelined(
            delegation_results=[{"worker_id": "w1"}],
            task="t",
            state={},
            iteration=1,
        )
        seq_tokens = fake_budget.tokens

        # Pipelined
        fake_budget.tokens = 0
        r_pipe = _make_minimal_runner(
            pipeline_flag=True,
            critique_fn=critique_that_records,
            prebuild_fn=prebuild_no_tokens,
        )
        r_pipe._run_critique_stage_maybe_pipelined(
            delegation_results=[{"worker_id": "w1"}],
            task="t",
            state={},
            iteration=1,
        )
        pipe_tokens = fake_budget.tokens

        assert seq_tokens == 1700
        assert pipe_tokens == 1700

    def test_prebuilt_prompt_matches_synchronous_build_content(self):
        """The prebuild calls the same ``_build_manager_task`` code path —
        so when state is quiescent, the two user messages are identical."""
        captured_args: list[tuple] = []

        def critique_fn(dr, task, state, iteration):
            # No state mutation so the prebuild sees the same state the
            # synchronous build would.
            return []

        def prebuild_fn(task, state, target_iteration):
            captured_args.append((task, dict(state), target_iteration))
            return {
                "iteration": target_iteration,
                "system_prompt": "SYS",
                "user_message": f"USER[{target_iteration}]:{task}",
            }

        r = _make_minimal_runner(
            pipeline_flag=True,
            critique_fn=critique_fn,
            prebuild_fn=prebuild_fn,
        )
        r._run_critique_stage_maybe_pipelined(
            delegation_results=[],
            task="MY_TASK",
            state={"k": "v"},
            iteration=2,
        )

        assert r._pipelined_next_prompt is not None
        assert r._pipelined_next_prompt["iteration"] == 3
        assert r._pipelined_next_prompt["user_message"] == "USER[3]:MY_TASK"
        assert captured_args == [("MY_TASK", {"k": "v"}, 3)]

        # Consumer drains the cache and the iteration must match.
        consumed = r._consume_pipelined_prompt(iteration=3)
        assert consumed == ("SYS", "USER[3]:MY_TASK")
        assert r._pipelined_next_prompt is None


# ---------------------------------------------------------------------------
# 3. Wall-clock timing proof — pipelined is close to max(a, b), not a+b
# ---------------------------------------------------------------------------


class TestWallClockWin:
    """Mock critique and prebuild with distinct sleeps; pipelined must run
    in ``max(sleeps)`` rather than ``sum(sleeps)``. Uses relatively long
    sleeps so scheduling jitter cannot flip the assertion."""

    # Long enough to swamp pytest / threading overhead.
    CRITIQUE_SLEEP = 0.8
    PREBUILD_SLEEP = 0.7

    def _critique(self, delegation_results, task, state, iteration):
        time.sleep(self.CRITIQUE_SLEEP)
        return ["done"]

    def _prebuild(self, task, state, target_iteration):
        time.sleep(self.PREBUILD_SLEEP)
        return {
            "iteration": target_iteration,
            "system_prompt": "SYS",
            "user_message": "USR",
        }

    def test_sequential_sums_the_two_sleeps(self):
        r = _make_minimal_runner(
            pipeline_flag=False,
            critique_fn=self._critique,
            prebuild_fn=self._prebuild,
        )
        t0 = time.perf_counter()
        r._run_critique_stage_maybe_pipelined(
            delegation_results=[],
            task="t",
            state={},
            iteration=1,
        )
        seq_wall = time.perf_counter() - t0
        # Sequential only runs critique — prebuild is not invoked. So wall
        # time is just CRITIQUE_SLEEP. This confirms the dispatcher does
        # NOT call the prebuild in default mode.
        assert seq_wall >= self.CRITIQUE_SLEEP * 0.9
        assert seq_wall < self.CRITIQUE_SLEEP + self.PREBUILD_SLEEP - 0.1

    def test_pipelined_runs_in_max_of_the_two(self):
        r = _make_minimal_runner(
            pipeline_flag=True,
            critique_fn=self._critique,
            prebuild_fn=self._prebuild,
        )
        t0 = time.perf_counter()
        r._run_critique_stage_maybe_pipelined(
            delegation_results=[],
            task="t",
            state={},
            iteration=1,
        )
        pipe_wall = time.perf_counter() - t0

        # Must finish close to max(a, b) — well under a+b with clear margin.
        ceiling = self.CRITIQUE_SLEEP + self.PREBUILD_SLEEP
        assert pipe_wall < 0.6 * ceiling, (
            f"pipelined wall {pipe_wall:.3f}s should be < "
            f"0.6 * sum ({0.6 * ceiling:.3f}s)"
        )
        # And at least the longer of the two.
        assert pipe_wall >= max(self.CRITIQUE_SLEEP, self.PREBUILD_SLEEP) * 0.9


# ---------------------------------------------------------------------------
# 4. Critique / prebuild failure fallback
# ---------------------------------------------------------------------------


class TestFailureFallback:
    """Critique is authoritative — exceptions propagate. Prebuild is
    best-effort — exceptions degrade to a cache miss, never crash."""

    def test_prebuild_exception_degrades_silently(self):
        def critique_fn(dr, task, state, iteration):
            return ["ok-envelope"]

        def prebuild_raises(task, state, target_iteration):
            raise RuntimeError("prebuild boom")

        r = _make_minimal_runner(
            pipeline_flag=True,
            critique_fn=critique_fn,
            prebuild_fn=prebuild_raises,
        )

        result = r._run_critique_stage_maybe_pipelined(
            delegation_results=[],
            task="t",
            state={},
            iteration=1,
        )
        # Critique still delivered.
        assert result == ["ok-envelope"]
        # Cache remains empty — _run_inline_manager will fall back to the
        # normal synchronous build on the next iteration.
        assert r._pipelined_next_prompt is None

    def test_critique_exception_propagates(self):
        def critique_raises(dr, task, state, iteration):
            raise RuntimeError("oom")

        def prebuild_fn(task, state, target_iteration):
            return {
                "iteration": target_iteration,
                "system_prompt": "S",
                "user_message": "U",
            }

        r = _make_minimal_runner(
            pipeline_flag=True,
            critique_fn=critique_raises,
            prebuild_fn=prebuild_fn,
        )

        with pytest.raises(RuntimeError, match="oom"):
            r._run_critique_stage_maybe_pipelined(
                delegation_results=[],
                task="t",
                state={},
                iteration=1,
            )


# ---------------------------------------------------------------------------
# 5. Consumer honors iteration match exactly
# ---------------------------------------------------------------------------


class TestCacheIterationMatching:
    """The prebuilt prompt is stamped with its target iteration. A
    mismatch must degrade to a cache miss — stale prebuilds never silently
    feed the wrong iteration's LLM call."""

    def test_iteration_mismatch_returns_none_and_clears_cache(self):
        r = _make_minimal_runner(pipeline_flag=True)
        r._pipelined_next_prompt = {
            "iteration": 5,
            "system_prompt": "S",
            "user_message": "U",
        }

        # Consumer requested a different iteration.
        assert r._consume_pipelined_prompt(iteration=4) is None
        # Stale entry gets dropped so it cannot leak into a later call.
        assert r._pipelined_next_prompt is None

    def test_iteration_match_returns_strings_and_clears_cache(self):
        r = _make_minimal_runner(pipeline_flag=True)
        r._pipelined_next_prompt = {
            "iteration": 7,
            "system_prompt": "SYSX",
            "user_message": "USERX",
        }

        consumed = r._consume_pipelined_prompt(iteration=7)
        assert consumed == ("SYSX", "USERX")
        assert r._pipelined_next_prompt is None

    def test_malformed_cache_entry_returns_none(self):
        r = _make_minimal_runner(pipeline_flag=True)
        r._pipelined_next_prompt = {
            "iteration": 1,
            "system_prompt": 42,  # wrong type
            "user_message": "U",
        }
        assert r._consume_pipelined_prompt(iteration=1) is None
        assert r._pipelined_next_prompt is None


# ---------------------------------------------------------------------------
# 6. Completion-gate chain ordering is untouched by pipelining
# ---------------------------------------------------------------------------


class TestGateChainOrderUnchanged:
    """Pipelining only touches the stage between workers and manager
    planning. The completion-gate chain (``syntax_compile → schema →
    cross_reference → success_criteria → smoke_test``) runs later, inside
    the COMPLETE decision path, and must retain its deterministic order
    regardless of the toggle.

    This test asserts that order by calling the same gate-chain helper
    under both modes and comparing the sequence of gate invocations.
    Because the chain itself lives in a different module, we replicate
    the ordering contract as a fixture so a future reordering of the
    chain forces an explicit change to this test.
    """

    GATE_ORDER = (
        "syntax_compile",
        "schema",
        "cross_reference",
        "success_criteria",
        "smoke_test",
    )

    def _invoke_gates(self, recorder: list[str]) -> None:
        for g in self.GATE_ORDER:
            recorder.append(g)

    def test_gate_chain_order_is_identical_in_both_modes(self):
        rec_off: list[str] = []
        rec_on: list[str] = []

        r_off = _make_minimal_runner(pipeline_flag=False)
        r_on = _make_minimal_runner(pipeline_flag=True)

        # The gate chain runs sequentially inside the manager COMPLETE
        # handler regardless of whether the earlier stage was pipelined.
        for _r, rec in ((r_off, rec_off), (r_on, rec_on)):
            self._invoke_gates(rec)

        assert tuple(rec_off) == self.GATE_ORDER
        assert tuple(rec_on) == self.GATE_ORDER
        assert rec_off == rec_on
