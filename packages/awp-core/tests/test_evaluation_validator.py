"""Tests for evaluation-specific validation rules (R27-R30)."""

import pytest

from awp.models.evaluation import (
    EvalMetricConfig,
    EvalThresholds,
    EvaluationConfig,
    RetryActionConfig,
    RetryPolicyConfig,
    StepScoreConfig,
)
from awp.models.manifest import AWPManifest
from awp.models.observability import ObservabilityConfig
from awp.validator.rules import validate_rules


def _make_manifest(eval_cfg: EvaluationConfig) -> AWPManifest:
    """Build a minimal AWPManifest with the given EvaluationConfig."""
    return AWPManifest(
        awp="1.0.0",
        workflow={"name": "test-eval", "version": "1.0.0", "description": "test"},
        observability=ObservabilityConfig(evaluation=eval_cfg),
    )


class TestR27MetricKinds:
    def test_valid_kinds(self):
        cfg = EvaluationConfig(
            enabled=True,
            metrics=[
                EvalMetricConfig(name="a", kind="deterministic_test"),
                EvalMetricConfig(name="b", kind="rubric_judge"),
                EvalMetricConfig(name="c", kind="budget_utility"),
                EvalMetricConfig(name="d", kind="policy_score"),
                EvalMetricConfig(name="e", kind="deterministic_assertion"),
            ],
        )
        result = validate_rules(_make_manifest(cfg), {}, pytest.importorskip("pathlib").Path("/tmp/test-eval"))
        # R27 should not fire
        r27_errors = [e for e in result.errors if e.startswith("R27")]
        assert r27_errors == []

    def test_invalid_kind(self):
        cfg = EvaluationConfig(
            enabled=True,
            metrics=[
                EvalMetricConfig(name="bad", kind="llm_vibe_check"),
            ],
        )
        result = validate_rules(_make_manifest(cfg), {}, pytest.importorskip("pathlib").Path("/tmp/test-eval"))
        r27_errors = [e for e in result.errors if e.startswith("R27")]
        assert len(r27_errors) == 1
        assert "llm_vibe_check" in r27_errors[0]


class TestR28Thresholds:
    def test_valid_thresholds(self):
        cfg = EvaluationConfig(
            enabled=True,
            metrics=[EvalMetricConfig(name="a", kind="deterministic_test")],
            thresholds=EvalThresholds(accept=0.9, retry=0.5, fail=0.2),
        )
        result = validate_rules(_make_manifest(cfg), {}, pytest.importorskip("pathlib").Path("/tmp/test-eval"))
        r28_errors = [e for e in result.errors if e.startswith("R28")]
        assert r28_errors == []


class TestR29Weights:
    def test_negative_weight(self):
        cfg = EvaluationConfig(
            enabled=True,
            metrics=[
                EvalMetricConfig(name="a", kind="deterministic_test", weight=-1.0),
            ],
        )
        result = validate_rules(_make_manifest(cfg), {}, pytest.importorskip("pathlib").Path("/tmp/test-eval"))
        r29_errors = [e for e in result.errors if e.startswith("R29")]
        assert len(r29_errors) >= 1

    def test_all_zero_weights(self):
        cfg = EvaluationConfig(
            enabled=True,
            metrics=[
                EvalMetricConfig(name="a", kind="deterministic_test", weight=0.0),
                EvalMetricConfig(name="b", kind="budget_utility", weight=0.0),
            ],
        )
        result = validate_rules(_make_manifest(cfg), {}, pytest.importorskip("pathlib").Path("/tmp/test-eval"))
        r29_errors = [e for e in result.errors if e.startswith("R29")]
        assert any("weight > 0" in e for e in r29_errors)

    def test_valid_weights(self):
        cfg = EvaluationConfig(
            enabled=True,
            metrics=[
                EvalMetricConfig(name="a", kind="deterministic_test", weight=0.5),
                EvalMetricConfig(name="b", kind="budget_utility", weight=0.0),
            ],
        )
        result = validate_rules(_make_manifest(cfg), {}, pytest.importorskip("pathlib").Path("/tmp/test-eval"))
        r29_errors = [e for e in result.errors if e.startswith("R29")]
        assert r29_errors == []


class TestR30HooksAndActions:
    def test_invalid_hook(self):
        cfg = EvaluationConfig(
            enabled=True,
            metrics=[EvalMetricConfig(name="a", kind="deterministic_test")],
            step_scores=StepScoreConfig(hooks=["worker_result", "magic_hook"]),
        )
        result = validate_rules(_make_manifest(cfg), {}, pytest.importorskip("pathlib").Path("/tmp/test-eval"))
        r30_errors = [e for e in result.errors if e.startswith("R30")]
        assert any("magic_hook" in e for e in r30_errors)

    def test_invalid_action(self):
        cfg = EvaluationConfig(
            enabled=True,
            metrics=[EvalMetricConfig(name="a", kind="deterministic_test")],
            retry_policy=RetryPolicyConfig(
                enabled=True,
                actions=RetryActionConfig(below_retry="explode"),
            ),
        )
        result = validate_rules(_make_manifest(cfg), {}, pytest.importorskip("pathlib").Path("/tmp/test-eval"))
        r30_errors = [e for e in result.errors if e.startswith("R30")]
        assert any("explode" in e for e in r30_errors)

    def test_valid_hooks_and_actions(self):
        cfg = EvaluationConfig(
            enabled=True,
            metrics=[EvalMetricConfig(name="a", kind="deterministic_test")],
            step_scores=StepScoreConfig(hooks=["worker_result", "final_answer"]),
            retry_policy=RetryPolicyConfig(
                enabled=True,
                actions=RetryActionConfig(
                    below_retry="retry_with_repair",
                    below_fail="fail_workflow",
                ),
            ),
        )
        result = validate_rules(_make_manifest(cfg), {}, pytest.importorskip("pathlib").Path("/tmp/test-eval"))
        r30_errors = [e for e in result.errors if e.startswith("R30")]
        assert r30_errors == []


class TestDisabledEvalSkipsRules:
    def test_disabled_eval_no_rules(self):
        """When evaluation is disabled, R27-R30 should not fire even with bad config."""
        cfg = EvaluationConfig(
            enabled=False,
            metrics=[EvalMetricConfig(name="bad", kind="invalid_kind")],
        )
        result = validate_rules(_make_manifest(cfg), {}, pytest.importorskip("pathlib").Path("/tmp/test-eval"))
        eval_errors = [e for e in result.errors if e.startswith(("R27", "R28", "R29", "R30"))]
        assert eval_errors == []
