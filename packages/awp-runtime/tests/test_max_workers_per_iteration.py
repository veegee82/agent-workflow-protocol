"""Fix G — ``max_workers_per_iteration`` budget.

Tests:
1. The budget model exposes the new field with default 6.
2. The :class:`BudgetSnapshot` inherits the value.
3. When ``_execute_delegations`` is called with more envelopes than the cap,
   the dispatch list is trimmed and ``state["_deferred_workers"]`` carries
   an instruction telling the manager to merge or defer.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from awp.models.orchestration import DelegationBudget
from awp.runtime.delegation_loop_runner import BudgetSnapshot, DelegationLoopRunner


def test_budget_model_default():
    b = DelegationBudget()
    assert b.max_workers_per_iteration == 6


def test_budget_snapshot_picks_up_cap():
    b = DelegationBudget(max_workers_per_iteration=3)
    snap = BudgetSnapshot(b)
    assert snap.max_workers_per_iteration == 3


def test_budget_snapshot_disabled_when_zero():
    b = DelegationBudget(max_workers_per_iteration=0)
    snap = BudgetSnapshot(b)
    assert snap.max_workers_per_iteration == 0


def test_execute_delegations_trims_over_cap(monkeypatch):
    """When more envelopes arrive than the cap allows, the overflow is
    deferred rather than dispatched — Fix G pre-spawn enforcement."""
    runner = DelegationLoopRunner.__new__(DelegationLoopRunner)

    # Wire minimum state so _execute_delegations can run
    b = DelegationBudget(max_workers_per_iteration=2)
    runner._budget = BudgetSnapshot(b)
    runner._logger = MagicMock()
    runner._logger.trace_gate = MagicMock()
    runner._profiler = MagicMock()
    runner._profiler.start = MagicMock()
    runner._profiler.stop = MagicMock()
    runner._task_plan = None
    runner._current_iteration = 0

    def _fake_execute(envelopes, task, state, iteration=0):
        # Replicate cap check + record "spawned" ids
        cap = runner._budget.max_workers_per_iteration
        if cap > 0 and len(envelopes) > cap:
            # Re-use the real trimming code path
            return DelegationLoopRunner._execute_delegations.__wrapped__(
                runner, envelopes, task, state, iteration
            ) if hasattr(
                DelegationLoopRunner._execute_delegations, "__wrapped__"
            ) else None

    # Rather than stub run_worker (heavy), invoke the real method but patch
    # ThreadPoolExecutor/run_worker via a monkey patch on the inner closure.
    # Easier: call the method, then only check the trimming side-effects
    # recorded in ``state`` and trace_gate — we don't care if downstream
    # raises because real workers cannot run without a real runner.
    state: dict = {}
    envelopes = [
        {"worker_id": f"w{i}", "subtask_id": f"s{i}", "instructions": f"do {i}"}
        for i in range(5)
    ]

    # Provide attributes needed by the later execution path so it fails
    # gracefully (we only want to observe the cap enforcement).
    runner._config = MagicMock()
    runner._config.context_budget = MagicMock(
        total_chars=1000, min_per_entry=100, preview_chars=100
    )
    runner._tools = None
    runner._dir = MagicMock()

    # Patch the spawning inner function by monkey-patching ThreadPoolExecutor
    # with a no-op so the method returns quickly after trimming.
    class _NoopFuture:
        def result(self):
            return {
                "worker_id": "stub",
                "envelope": {},
                "result": {},
                "status": "ok",
            }

    class _NoopExec:
        def __init__(self, *a, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def submit(self, fn, *a, **kw):
            return _NoopFuture()

    monkeypatch.setattr(
        "awp.runtime.delegation_loop_runner.ThreadPoolExecutor", _NoopExec
    )
    monkeypatch.setattr(
        "awp.runtime.delegation_loop_runner.as_completed",
        lambda futs: list(futs),
    )

    try:
        runner._execute_delegations(envelopes, "test task", state, iteration=1)
    except Exception:
        # The downstream path may still fail because _run_ephemeral_worker
        # is not wired — that's fine. We only assert the cap side-effects.
        pass

    # Assert cap triggered
    runner._logger.trace_gate.assert_called()
    call_args = runner._logger.trace_gate.call_args
    assert call_args.args[0] == "max_workers_per_iteration"
    assert call_args.kwargs.get("deferred") == 3
    assert call_args.kwargs.get("dispatched") == 2

    # Assert deferred_workers feedback set in state
    assert "_deferred_workers" in state
    assert "Per-iteration worker cap (2)" in state["_deferred_workers"]


def test_execute_delegations_no_trim_under_cap(monkeypatch):
    """No trimming when envelope count stays at/under the cap."""
    runner = DelegationLoopRunner.__new__(DelegationLoopRunner)
    b = DelegationBudget(max_workers_per_iteration=6)
    runner._budget = BudgetSnapshot(b)
    runner._logger = MagicMock()
    runner._logger.trace_gate = MagicMock()
    runner._profiler = MagicMock()
    runner._task_plan = None
    runner._current_iteration = 0
    runner._config = MagicMock()
    runner._tools = None
    runner._dir = MagicMock()

    class _NoopExec:
        def __init__(self, *a, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def submit(self, fn, *a, **kw):
            class _F:
                def result(self_inner):
                    return {
                        "worker_id": "stub",
                        "envelope": {},
                        "result": {},
                        "status": "ok",
                    }

            return _F()

    monkeypatch.setattr(
        "awp.runtime.delegation_loop_runner.ThreadPoolExecutor", _NoopExec
    )
    monkeypatch.setattr(
        "awp.runtime.delegation_loop_runner.as_completed",
        lambda futs: list(futs),
    )

    state: dict = {}
    envelopes = [
        {"worker_id": f"w{i}", "subtask_id": f"s{i}", "instructions": f"do {i}"}
        for i in range(3)
    ]
    try:
        runner._execute_delegations(envelopes, "test task", state, iteration=1)
    except Exception:
        pass

    # trace_gate for max_workers_per_iteration must NOT have been called
    calls = [c for c in runner._logger.trace_gate.call_args_list
             if c.args and c.args[0] == "max_workers_per_iteration"]
    assert calls == []
    assert "_deferred_workers" not in state
