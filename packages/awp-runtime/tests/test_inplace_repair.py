"""Tests for α-fix-2: soft in-place repair via per-logical-worker executor registry.

When the manager spawns a repair variant of a previously-dispatched worker
(``_repair``, ``_retry``, ``_v2``, ``_strict``, ``_final``, ``_runN``,
``_subtask_N``), the runner reuses the same executor so α-fix-1's warm
namespace (imports, variables, helpers) is preserved across attempts.

These tests pin:
1. The logical-id stripping heuristic.
2. Re-entry reuses the same executor and the namespace survives.
3. ``fresh_worker=True`` in the envelope forces a new executor.
4. ``run()`` finalizer cleans up every registered executor.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from awp.runtime.delegation_loop_runner import (
    DelegationLoopRunner,
    logical_worker_id,
)

# ---------------------------------------------------------------------------
# 1. Logical-id stripping
# ---------------------------------------------------------------------------


class TestLogicalWorkerIdStripping:
    """The stripping helper is applied to a fixpoint and is case-insensitive."""

    @pytest.mark.parametrize(
        "worker_id,expected",
        [
            # No suffix — identity.
            ("compose_awp_concepts_worker", "compose_awp_concepts_worker"),
            # Simple repair.
            ("compose_awp_concepts_worker_repair", "compose_awp_concepts_worker"),
            # Stacked suffixes — strip to fixpoint.
            ("compose_awp_concepts_worker_v2_repair", "compose_awp_concepts_worker"),
            ("foo_retry_strict", "foo"),
            ("foo_retry2_strict", "foo"),
            ("bar_v1", "bar"),
            ("baz_final", "baz"),
            # Numbered subtask suffix.
            ("plot_runner_run3_subtask_7", "plot_runner"),
            ("worker_subtask_42", "worker"),
            # Several versions stacked.
            ("w_v2_v3", "w"),
            # No-ops on empty.
            ("", ""),
            # Guard: stripping everything still returns the original id.
            ("_repair", "_repair"),
            ("_v2", "_v2"),
            # Short unique id unchanged.
            ("simple", "simple"),
        ],
    )
    def test_logical_worker_id_stripping(self, worker_id: str, expected: str) -> None:
        assert logical_worker_id(worker_id) == expected

    def test_stripping_is_case_insensitive(self) -> None:
        # The regex is case-insensitive so capitalised suffixes also collapse.
        assert logical_worker_id("FooWorker_REPAIR") == "FooWorker"
        assert logical_worker_id("bar_Retry") == "bar"


# ---------------------------------------------------------------------------
# Fixture: minimal runner for registry-level tests (no real LLM loop)
# ---------------------------------------------------------------------------


class _FakeExecutor:
    """Stand-in for a PersistentExecutor so the registry logic can be tested
    without spawning real subprocesses."""

    _instances: list["_FakeExecutor"] = []

    def __init__(self, **kwargs) -> None:
        self._namespace: dict = {}
        self._max_timeout = kwargs.get("max_timeout", 30)
        self._max_output = kwargs.get("max_output_bytes", 1_048_576)
        self._cwd = kwargs.get("working_dir")
        self.cleanup_calls = 0
        self.executed: list[str] = []
        type(self)._instances.append(self)

    def execute(self, code: str, timeout=None) -> dict:
        # Minimal: evaluate in persistent namespace so variables survive.
        self.executed.append(code)
        try:
            exec(code, self._namespace)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "status": 500, "data": {}, "error": str(exc)}
        return {"ok": True, "status": 200, "data": {}, "error": None}

    def cleanup(self) -> None:
        self.cleanup_calls += 1


class _FakeToolRegistry:
    def __init__(self, executor) -> None:
        self._code_executor = executor


@pytest.fixture
def runner_with_fake_executor(monkeypatch):
    """Build a DelegationLoopRunner instance with the minimum state
    needed to exercise the per-worker executor registry helpers."""
    # Patch the fallback spawn helper so _spawn_new_executor always uses
    # our FakeExecutor regardless of whether introspection succeeds.
    _FakeExecutor._instances = []

    r = DelegationLoopRunner.__new__(DelegationLoopRunner)
    initial = _FakeExecutor()
    r._tools = _FakeToolRegistry(initial)
    r._shared_code_executor_original = initial
    r._worker_executors = {}
    r._worker_call_counts = {}
    r._dir = None  # Not used on the registry path.

    # Patch _spawn_new_executor to return fresh FakeExecutors so we don't
    # depend on the real PersistentExecutor subprocess.
    monkeypatch.setattr(
        r,
        "_spawn_new_executor",
        lambda: _FakeExecutor(),
    )
    return r, initial


# ---------------------------------------------------------------------------
# 2. Re-entry preserves the namespace
# ---------------------------------------------------------------------------


class TestReentryPreservesNamespace:
    def test_reentry_reuses_same_executor_instance(self, runner_with_fake_executor) -> None:
        r, initial = runner_with_fake_executor

        ex1, count1, reentry1 = r._get_executor_for_worker(
            logical_worker_id("compose_worker"), fresh_worker=False
        )
        # First call: claims the shared executor.
        assert ex1 is initial
        assert count1 == 1
        assert reentry1 is False

        # Repair variant: same logical id, same executor.
        ex2, count2, reentry2 = r._get_executor_for_worker(
            logical_worker_id("compose_worker_repair"), fresh_worker=False
        )
        assert ex2 is ex1
        assert count2 == 2
        assert reentry2 is True

        # A stacked repair suffix still maps to the same logical id.
        ex3, count3, reentry3 = r._get_executor_for_worker(
            logical_worker_id("compose_worker_v2_repair"), fresh_worker=False
        )
        assert ex3 is ex1
        assert count3 == 3
        assert reentry3 is True

    def test_namespace_variables_survive_across_reentries(
        self, runner_with_fake_executor
    ) -> None:
        r, _ = runner_with_fake_executor

        ex1, *_ = r._get_executor_for_worker("compose_worker", fresh_worker=False)
        # First call writes a variable into the namespace.
        ex1.execute("x = 42")
        assert ex1._namespace.get("x") == 42

        # Re-entered repair variant sees the same namespace.
        ex2, count2, reentry2 = r._get_executor_for_worker(
            logical_worker_id("compose_worker_repair"), fresh_worker=False
        )
        assert reentry2 is True
        # Same executor → same namespace.
        assert ex2._namespace.get("x") == 42
        ex2.execute("y = x + 1")
        assert ex2._namespace.get("y") == 43

    def test_different_logical_ids_get_isolated_executors(
        self, runner_with_fake_executor
    ) -> None:
        r, initial = runner_with_fake_executor

        ex_a, *_ = r._get_executor_for_worker("worker_a", fresh_worker=False)
        ex_b, *_ = r._get_executor_for_worker("worker_b", fresh_worker=False)
        # worker_a claims the initial shared executor; worker_b gets a new one.
        assert ex_a is initial
        assert ex_b is not initial
        assert ex_a is not ex_b
        # Namespaces are independent.
        ex_a.execute("shared = 'a'")
        ex_b.execute("shared = 'b'")
        assert ex_a._namespace["shared"] == "a"
        assert ex_b._namespace["shared"] == "b"


# ---------------------------------------------------------------------------
# 3. fresh_worker forces a new executor
# ---------------------------------------------------------------------------


class TestFreshWorkerFlag:
    def test_fresh_worker_true_discards_prior_executor(
        self, runner_with_fake_executor
    ) -> None:
        r, _ = runner_with_fake_executor

        ex1, *_ = r._get_executor_for_worker("compose_worker", fresh_worker=False)
        ex1.execute("secret = 'ALPHA'")
        assert ex1._namespace.get("secret") == "ALPHA"

        # fresh_worker=True: spawn a new executor, retire the old one.
        ex2, count2, reentry2 = r._get_executor_for_worker(
            logical_worker_id("compose_worker_repair"), fresh_worker=True
        )
        assert ex2 is not ex1
        assert count2 == 1
        assert reentry2 is False
        # The new executor starts with an empty namespace — prior variable gone.
        assert "secret" not in ex2._namespace
        # Old executor received a cleanup call when it was retired.
        assert ex1.cleanup_calls == 1

    def test_fresh_worker_false_default_keeps_executor(
        self, runner_with_fake_executor
    ) -> None:
        r, _ = runner_with_fake_executor

        ex1, *_ = r._get_executor_for_worker("w", fresh_worker=False)
        ex2, count2, reentry2 = r._get_executor_for_worker(
            "w", fresh_worker=False
        )
        assert ex1 is ex2
        assert reentry2 is True
        assert count2 == 2
        # No premature cleanup on plain reuse.
        assert ex1.cleanup_calls == 0


# ---------------------------------------------------------------------------
# 4. Run-end cleanup
# ---------------------------------------------------------------------------


class TestCleanupOnRunEnd:
    def test_cleanup_runs_on_every_registered_executor(
        self, runner_with_fake_executor
    ) -> None:
        r, initial = runner_with_fake_executor

        # Dispatch three distinct logical workers — three executors.
        ex_a, *_ = r._get_executor_for_worker("w_a", fresh_worker=False)
        ex_b, *_ = r._get_executor_for_worker("w_b", fresh_worker=False)
        ex_c, *_ = r._get_executor_for_worker("w_c", fresh_worker=False)
        assert len({id(ex_a), id(ex_b), id(ex_c)}) == 3

        r._cleanup_worker_executors()

        for ex in (ex_a, ex_b, ex_c):
            assert ex.cleanup_calls == 1, (
                f"Executor {ex} did not receive cleanup() at run end"
            )
        # Registry is emptied.
        assert r._worker_executors == {}
        assert r._worker_call_counts == {}

    def test_cleanup_is_idempotent(self, runner_with_fake_executor) -> None:
        r, _ = runner_with_fake_executor
        r._get_executor_for_worker("only", fresh_worker=False)
        r._cleanup_worker_executors()
        # Second call is a no-op — must not raise.
        r._cleanup_worker_executors()

    def test_cleanup_swallows_executor_errors(
        self, runner_with_fake_executor
    ) -> None:
        r, _ = runner_with_fake_executor
        r._get_executor_for_worker("w_ok", fresh_worker=False)
        ex_bad, *_ = r._get_executor_for_worker("w_bad", fresh_worker=False)

        # Make one executor's cleanup raise; the other must still be cleaned.
        def boom() -> None:
            raise RuntimeError("intentional failure")

        ex_bad.cleanup = boom  # type: ignore[assignment]

        # Must not propagate.
        r._cleanup_worker_executors()
        assert r._worker_executors == {}

    def test_cleanup_restores_shared_executor_reference(
        self, runner_with_fake_executor
    ) -> None:
        r, initial = runner_with_fake_executor
        # Spawn a second worker to prove the registry deviates from initial.
        r._get_executor_for_worker("w_a", fresh_worker=False)
        r._get_executor_for_worker("w_b", fresh_worker=False)
        # Simulate a mid-run swap on the ToolRegistry.
        r._tools._code_executor = MagicMock()

        r._cleanup_worker_executors()
        assert r._tools._code_executor is initial
