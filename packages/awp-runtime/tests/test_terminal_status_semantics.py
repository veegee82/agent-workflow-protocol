"""Fix H — terminal status helper semantics.

Verifies that :func:`_finalize_terminal_status` always maps cap/limit-forced
exits to ``partial``, hard failures to ``failed``, signals/abrupt exits to
``aborted``, and only explicit success signals to ``complete``.
"""

from __future__ import annotations

from awp.runtime.delegation_loop_runner import _finalize_terminal_status


class TestFinalizeTerminalStatus:
    def test_complete_passes_through(self):
        assert _finalize_terminal_status("complete") == "complete"
        assert _finalize_terminal_status("success") == "complete"
        assert _finalize_terminal_status("ok") == "complete"

    def test_defect_cap_is_partial_not_complete(self):
        # Critical: cap-forced exits MUST NOT be reported as complete.
        assert _finalize_terminal_status("defect_category_cap") == "partial"
        assert (
            _finalize_terminal_status(
                "defect_category_cap: 5 missing_data defects"
            )
            == "partial"
        )

    def test_plan_loop_is_partial(self):
        assert _finalize_terminal_status("plan_loop") == "partial"

    def test_budget_caps_are_partial(self):
        for reason in (
            "max_total_tokens",
            "max_total_workers",
            "max_wall_time",
            "max_loops",
            "max_tool_calls",
            "budget_exhausted",
        ):
            assert _finalize_terminal_status(reason) == "partial", reason

    def test_forced_convergence_is_partial(self):
        assert _finalize_terminal_status("forced_convergence") == "partial"

    def test_hard_failures_are_failed(self):
        assert _finalize_terminal_status("eval_fail") == "failed"
        assert _finalize_terminal_status("fail") == "failed"
        assert _finalize_terminal_status("error: boom") == "failed"

    def test_signals_are_aborted(self):
        assert _finalize_terminal_status("sigterm") == "aborted"
        assert _finalize_terminal_status("sigint") == "aborted"
        assert (
            _finalize_terminal_status("process_exit_without_terminal_event")
            == "aborted"
        )

    def test_empty_reason_is_aborted(self):
        assert _finalize_terminal_status("") == "aborted"

    def test_unknown_reason_defaults_partial(self):
        # Unknown reasons are conservatively partial (never claim complete).
        assert _finalize_terminal_status("some_weird_unknown_reason") == "partial"

    def test_max_rejected_completions_is_partial(self):
        # Session 2 will add this reason; the helper already knows it.
        assert _finalize_terminal_status("max_rejected_completions") == "partial"
