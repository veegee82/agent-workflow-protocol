"""Tests for AWP evaluation models (EvaluationConfig and related)."""

import pytest
from pydantic import ValidationError

from awp.models.evaluation import (
    EvalMetricConfig,
    EvalThresholds,
    EvaluationConfig,
    RetryActionConfig,
    RetryPolicyConfig,
    RubricJudgeConfig,
    StepScoreConfig,
)
from awp.models.observability import ObservabilityConfig


# -- EvalThresholds -----------------------------------------------------------


class TestEvalThresholds:
    def test_defaults(self):
        t = EvalThresholds()
        assert t.accept == 0.85
        assert t.retry == 0.65
        assert t.fail == 0.40

    def test_valid_custom(self):
        t = EvalThresholds(accept=0.9, retry=0.5, fail=0.1)
        assert t.accept == 0.9

    def test_invalid_ordering_accept_lt_retry(self):
        with pytest.raises(ValidationError, match="accept >= retry >= fail"):
            EvalThresholds(accept=0.3, retry=0.5, fail=0.1)

    def test_invalid_ordering_retry_lt_fail(self):
        with pytest.raises(ValidationError, match="accept >= retry >= fail"):
            EvalThresholds(accept=0.9, retry=0.2, fail=0.5)

    def test_out_of_range_high(self):
        with pytest.raises(ValidationError, match="must be in"):
            EvalThresholds(accept=1.5, retry=0.5, fail=0.1)

    def test_out_of_range_negative(self):
        with pytest.raises(ValidationError, match="must be in"):
            EvalThresholds(accept=0.9, retry=-0.1, fail=0.0)

    def test_all_equal(self):
        t = EvalThresholds(accept=0.5, retry=0.5, fail=0.5)
        assert t.accept == t.retry == t.fail


# -- EvalMetricConfig ---------------------------------------------------------


class TestEvalMetricConfig:
    def test_basic(self):
        m = EvalMetricConfig(name="test", kind="deterministic_test")
        assert m.weight == 1.0
        assert m.params == {}

    def test_with_params(self):
        m = EvalMetricConfig(
            name="check",
            kind="deterministic_test",
            weight=2.0,
            params={"expr": "result.get('ok')"},
        )
        assert m.params["expr"] == "result.get('ok')"


# -- EvaluationConfig ---------------------------------------------------------


class TestEvaluationConfig:
    def test_defaults(self):
        cfg = EvaluationConfig()
        assert cfg.enabled is False
        assert cfg.metrics == []
        assert cfg.thresholds.accept == 0.85
        assert cfg.step_scores.enabled is True
        assert cfg.retry_policy.enabled is False
        assert cfg.artifact_path == "data/evaluation"

    def test_full_config(self):
        cfg = EvaluationConfig(
            enabled=True,
            metrics=[
                EvalMetricConfig(name="a", kind="deterministic_test", weight=0.5),
                EvalMetricConfig(name="b", kind="budget_utility", weight=0.5),
            ],
            thresholds=EvalThresholds(accept=0.8, retry=0.5, fail=0.2),
            step_scores=StepScoreConfig(on=["worker_result"]),
            retry_policy=RetryPolicyConfig(enabled=True, max_repairs=3),
            rubric_judge=RubricJudgeConfig(model="test-model"),
        )
        assert cfg.enabled is True
        assert len(cfg.metrics) == 2
        assert cfg.retry_policy.max_repairs == 3

    def test_extra_fields_allowed(self):
        cfg = EvaluationConfig(enabled=False, custom_field="hello")
        assert cfg.custom_field == "hello"  # type: ignore[attr-defined]


# -- ObservabilityConfig nesting ----------------------------------------------


class TestObservabilityWithEval:
    def test_without_evaluation(self):
        obs = ObservabilityConfig()
        assert obs.evaluation is None

    def test_with_evaluation(self):
        eval_cfg = EvaluationConfig(enabled=True)
        obs = ObservabilityConfig(evaluation=eval_cfg)
        assert obs.evaluation is not None
        assert obs.evaluation.enabled is True

    def test_from_dict(self):
        obs = ObservabilityConfig(
            **{
                "evaluation": {
                    "enabled": True,
                    "metrics": [
                        {"name": "test", "kind": "deterministic_test"},
                    ],
                    "thresholds": {"accept": 0.9, "retry": 0.6, "fail": 0.3},
                }
            }
        )
        assert obs.evaluation is not None
        assert obs.evaluation.enabled is True
        assert len(obs.evaluation.metrics) == 1


# -- RetryPolicyConfig --------------------------------------------------------


class TestRetryPolicyConfig:
    def test_defaults(self):
        rp = RetryPolicyConfig()
        assert rp.enabled is False
        assert rp.max_repairs == 2
        assert rp.actions.below_retry == "retry_with_repair"
        assert rp.actions.below_fail == "fail_workflow"

    def test_custom_actions(self):
        rp = RetryPolicyConfig(
            enabled=True,
            actions=RetryActionConfig(
                below_retry="accept_with_warning",
                below_fail="fail_workflow",
            ),
        )
        assert rp.actions.below_retry == "accept_with_warning"
