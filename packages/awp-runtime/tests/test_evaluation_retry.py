"""Tests for the evaluation retry policy."""

import pytest

from awp.runtime.evaluation.retry import EvalRetryPolicy


class TestEvalRetryPolicy:
    def test_disabled_always_accepts(self):
        policy = EvalRetryPolicy(enabled=False)
        assert policy.decide(0.9, accept=0.8, retry=0.5, fail=0.2) == "accept"
        assert policy.decide(0.3, accept=0.8, retry=0.5, fail=0.2) == "accept_with_warning"

    def test_above_accept(self):
        policy = EvalRetryPolicy(enabled=True, max_repairs=2)
        assert policy.decide(0.9, accept=0.8, retry=0.5, fail=0.2) == "accept"

    def test_between_retry_and_accept(self):
        policy = EvalRetryPolicy(enabled=True, max_repairs=2)
        assert policy.decide(0.6, accept=0.8, retry=0.5, fail=0.2) == "accept_with_warning"

    def test_between_fail_and_retry(self):
        policy = EvalRetryPolicy(enabled=True, max_repairs=2)
        result = policy.decide(0.3, accept=0.8, retry=0.5, fail=0.2)
        assert result == "retry_with_repair"

    def test_below_fail(self):
        policy = EvalRetryPolicy(enabled=True, max_repairs=2)
        result = policy.decide(0.1, accept=0.8, retry=0.5, fail=0.2)
        assert result == "fail_workflow"

    def test_max_repairs_exhausted(self):
        policy = EvalRetryPolicy(enabled=True, max_repairs=1)
        policy.record_retry()
        # Now at max — should not retry even below fail
        result = policy.decide(0.1, accept=0.8, retry=0.5, fail=0.2)
        assert result == "fail_workflow"

    def test_max_repairs_respected_in_retry_zone(self):
        policy = EvalRetryPolicy(enabled=True, max_repairs=1)
        policy.record_retry()
        # Between fail and retry, but no retries left
        result = policy.decide(0.3, accept=0.8, retry=0.5, fail=0.2)
        assert result == "accept_with_warning"

    def test_can_retry_with_budget(self):
        policy = EvalRetryPolicy(enabled=True, max_repairs=5)

        class FakeBudget:
            def can_continue(self):
                return True, "ok"

        assert policy.can_retry(FakeBudget()) is True

    def test_cannot_retry_budget_exhausted(self):
        policy = EvalRetryPolicy(enabled=True, max_repairs=5)

        class FakeBudget:
            def can_continue(self):
                return False, "max_loops"

        assert policy.can_retry(FakeBudget()) is False

    def test_record_retry_increments(self):
        policy = EvalRetryPolicy(enabled=True, max_repairs=3)
        assert policy.retries_used == 0
        policy.record_retry()
        assert policy.retries_used == 1
        policy.record_retry()
        assert policy.retries_used == 2

    def test_from_config(self):
        from awp.models.evaluation import RetryPolicyConfig, RetryActionConfig

        cfg = RetryPolicyConfig(
            enabled=True,
            max_repairs=5,
            actions=RetryActionConfig(
                below_retry="accept_with_warning",
                below_fail="fail_workflow",
            ),
        )
        policy = EvalRetryPolicy.from_config(cfg)
        assert policy.enabled is True
        assert policy.max_repairs == 5
        assert policy.below_retry_action == "accept_with_warning"

    def test_from_none_config(self):
        policy = EvalRetryPolicy.from_config(None)
        assert policy.enabled is False
