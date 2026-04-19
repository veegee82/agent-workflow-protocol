"""Fix E — ``run.complete`` finalizer is emitted on every exit path.

Covers:
1. Normal termination writes ``run_completion.json`` with canonical status.
2. An unhandled exception inside ``_loop`` still triggers ``log_completion``
   with ``status="failed"`` and a non-empty reason.
3. Emulated SIGINT (via KeyboardInterrupt raised from ``_loop``) triggers
   ``log_completion`` with ``status="aborted"``.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from awp.runtime.delegation_loop_runner import (
    DelegationLoopRunner,
    _finalize_terminal_status,
)


def _make_runner() -> DelegationLoopRunner:
    r = DelegationLoopRunner.__new__(DelegationLoopRunner)
    # Wire minimal attributes consulted by ``run()``
    r._run_id = "test-run"
    r._depth = 0
    r._tools = None
    r._logger = MagicMock()
    r._logger.log_run_start = MagicMock()
    r._logger.log_completion = MagicMock()
    r._logger.flush = MagicMock()
    r._profiler = MagicMock()
    r._profiler.write_report = MagicMock()
    r._config = MagicMock()
    r._config.auto_curation_enabled = False
    r._manager_model = "test-manager"
    r._worker_model = "test-worker"
    r._budget = MagicMock()
    r._iter_counter = 0
    r._blackboard = None
    r._digest_store = None
    r._current_digest_sha = None
    r._parent_digest_sha = None
    r._dir = MagicMock()
    r._dir.__truediv__ = lambda self, other: MagicMock()
    r._failed_signatures = []
    r._run_started_at = 0.0
    # Refinement-mode plumbing (Task 0 of refinement-mode implementation).
    r._parent_run_id = None
    r._tags = []
    r._manager_prompt_prefix = None
    return r


def test_normal_termination_emits_complete():
    r = _make_runner()
    with patch.object(r, "_loop", return_value=({"confidence": 0.9}, "complete")):
        r.run("hello")
    # log_completion should have been called with status="complete"
    args, kwargs = r._logger.log_completion.call_args
    # Positional signature: (run_id, final_result, budget, total_iter, status)
    status = args[4] if len(args) >= 5 else kwargs.get("status")
    assert status == "complete"


def test_exception_in_loop_emits_failed():
    r = _make_runner()
    with patch.object(r, "_loop", side_effect=RuntimeError("boom")):
        r.run("hello")
    args, kwargs = r._logger.log_completion.call_args
    status = args[4] if len(args) >= 5 else kwargs.get("status")
    assert status == "failed"
    # Final result should carry a terminal reason
    final = args[1]
    assert isinstance(final, dict)
    assert final.get("_terminal_status") == "failed"
    assert "boom" in (final.get("_terminal_reason") or final.get("error") or "")


def test_keyboard_interrupt_emits_aborted():
    r = _make_runner()
    with patch.object(r, "_loop", side_effect=KeyboardInterrupt):
        r.run("hello")
    args, kwargs = r._logger.log_completion.call_args
    status = args[4] if len(args) >= 5 else kwargs.get("status")
    assert status == "aborted"
    final = args[1]
    assert final.get("_terminal_status") == "aborted"
    assert final.get("_terminal_reason") == "sigint"


def test_cap_forced_exit_is_partial_not_complete():
    """A ``_loop`` that returns status="defect_category_cap" MUST be
    canonicalized to ``partial`` by the finalizer (Fix H)."""
    r = _make_runner()
    with patch.object(
        r, "_loop", return_value=({"partial": True}, "defect_category_cap")
    ):
        r.run("hello")
    args, kwargs = r._logger.log_completion.call_args
    status = args[4] if len(args) >= 5 else kwargs.get("status")
    assert status == "partial"


def test_forced_convergence_is_partial_not_complete():
    r = _make_runner()
    with patch.object(
        r, "_loop", return_value=({"partial": True}, "forced_convergence")
    ):
        r.run("hello")
    args, kwargs = r._logger.log_completion.call_args
    status = args[4] if len(args) >= 5 else kwargs.get("status")
    assert status == "partial"


def test_finalize_status_helper_is_source_of_truth():
    # Sanity: Fix H helper matches the exit-path canonicalization above.
    assert _finalize_terminal_status("defect_category_cap") == "partial"
    assert _finalize_terminal_status("forced_convergence") == "partial"
    assert _finalize_terminal_status("complete") == "complete"
    assert _finalize_terminal_status("sigint") == "aborted"
    assert _finalize_terminal_status("error: boom") == "failed"
