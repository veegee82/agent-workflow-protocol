"""Tests for the AWP evaluation engine and scorers."""

import json
import pytest
from pathlib import Path

from awp.models.evaluation import (
    EvalMetricConfig,
    EvalThresholds,
    EvaluationConfig,
    RetryPolicyConfig,
    StepScoreConfig,
)
from awp.runtime.evaluation.engine import EvaluationEngine
from awp.runtime.evaluation.scorers import (
    score_budget_utility,
    score_deterministic_assertion,
    score_deterministic_test,
    score_policy_score,
)
from awp.runtime.evaluation.models import EvalResult


# -- Deterministic test scorer ------------------------------------------------


class TestDeterministicTest:
    def test_truthy_expr(self):
        score, evidence = score_deterministic_test(
            result={"confidence": 0.9},
            state={},
            params={"expr": "result.confidence > 0.5"},
        )
        assert score == 1.0

    def test_falsy_expr(self):
        score, evidence = score_deterministic_test(
            result={"confidence": 0.2},
            state={},
            params={"expr": "result.confidence > 0.5"},
        )
        assert score == 0.0

    def test_no_expr(self):
        score, evidence = score_deterministic_test(
            result={}, state={}, params={}
        )
        assert score == 0.0
        assert "No 'expr'" in evidence

    def test_bad_expr(self):
        score, evidence = score_deterministic_test(
            result={}, state={}, params={"expr": "import os"}
        )
        assert score == 0.0
        assert "error" in evidence.lower() or "Error" in evidence

    def test_uses_state(self):
        score, _ = score_deterministic_test(
            result={},
            state={"task": "test"},
            params={"expr": "state.task == 'test'"},
        )
        assert score == 1.0


# -- Deterministic assertion scorer -------------------------------------------


class TestDeterministicAssertion:
    def test_all_pass(self):
        score, evidence = score_deterministic_assertion(
            result={"a": 1, "b": 2},
            state={},
            params={"assertions": ["result.a == 1", "result.b == 2"]},
        )
        assert score == 1.0

    def test_partial_pass(self):
        score, evidence = score_deterministic_assertion(
            result={"a": 1, "b": 99},
            state={},
            params={"assertions": ["result.a == 1", "result.b == 2"]},
        )
        assert score == 0.5

    def test_no_assertions(self):
        score, evidence = score_deterministic_assertion(
            result={}, state={}, params={}
        )
        assert score == 0.0

    def test_all_fail(self):
        score, _ = score_deterministic_assertion(
            result={"a": 0},
            state={},
            params={"assertions": ["result.a == 1", "result.a == 2"]},
        )
        assert score == 0.0


# -- Budget utility scorer ----------------------------------------------------


class TestBudgetUtility:
    def test_no_budget(self):
        score, _ = score_budget_utility(result={}, state={}, params={})
        assert score == 1.0

    def test_half_budget_used(self):
        score, _ = score_budget_utility(
            result={},
            state={
                "_run_budget": {
                    "tokens_used": 500,
                    "max_total_tokens": 1000,
                }
            },
            params={},
        )
        assert score == pytest.approx(0.5)

    def test_budget_exhausted(self):
        score, _ = score_budget_utility(
            result={},
            state={
                "_run_budget": {
                    "tokens_used": 1000,
                    "max_total_tokens": 1000,
                }
            },
            params={},
        )
        assert score == pytest.approx(0.0)


# -- Policy score -------------------------------------------------------------


class TestPolicyScore:
    def test_no_assertions(self):
        score, _ = score_policy_score(result={}, state={}, params={})
        assert score == 1.0

    def test_all_pass(self):
        score, _ = score_policy_score(
            result={"safe": True},
            state={},
            params={"assertions": ["result.safe == True"]},
        )
        assert score == 1.0


# -- EvaluationEngine ---------------------------------------------------------


class TestEvaluationEngine:
    def _make_engine(self, tmp_path: Path, **overrides) -> EvaluationEngine:
        defaults = dict(
            enabled=True,
            metrics=[
                EvalMetricConfig(
                    name="check",
                    kind="deterministic_test",
                    weight=1.0,
                    params={"expr": "result.confidence > 0.5"},
                ),
            ],
            thresholds=EvalThresholds(accept=0.8, retry=0.4, fail=0.2),
            step_scores=StepScoreConfig(hooks=["worker_result", "final_answer"]),
        )
        defaults.update(overrides)
        cfg = EvaluationConfig(**defaults)
        return EvaluationEngine(
            config=cfg,
            workflow_dir=tmp_path,
            run_id="test-run-001",
        )

    def test_disabled_engine_is_noop(self, tmp_path):
        cfg = EvaluationConfig(enabled=False)
        engine = EvaluationEngine(cfg, tmp_path, "test")
        assert engine.evaluate_step("worker_result", {}, {}) is None
        assert engine.evaluate_final({}, {}) is None
        assert engine.decide_retry(None) == "accept"

    def test_step_evaluation(self, tmp_path):
        engine = self._make_engine(tmp_path)
        result = engine.evaluate_step(
            hook="worker_result",
            result={"confidence": 0.9},
            state={},
        )
        assert result is not None
        assert result.score == 1.0

    def test_step_wrong_hook_skipped(self, tmp_path):
        engine = self._make_engine(tmp_path)
        result = engine.evaluate_step(
            hook="generated_tool",
            result={"confidence": 0.9},
            state={},
        )
        assert result is None

    def test_final_evaluation(self, tmp_path):
        engine = self._make_engine(tmp_path)
        result = engine.evaluate_final(
            result={"confidence": 0.9},
            state={},
        )
        assert result is not None
        assert result.score == 1.0

    def test_weighted_aggregation(self, tmp_path):
        engine = self._make_engine(
            tmp_path,
            metrics=[
                EvalMetricConfig(
                    name="a",
                    kind="deterministic_test",
                    weight=2.0,
                    params={"expr": "True"},
                ),
                EvalMetricConfig(
                    name="b",
                    kind="deterministic_test",
                    weight=1.0,
                    params={"expr": "False"},
                ),
            ],
        )
        result = engine.evaluate_final(result={}, state={})
        # weighted: (1.0*2 + 0.0*1) / (2+1) = 0.667
        assert result is not None
        assert result.score == pytest.approx(2.0 / 3.0, abs=0.01)

    def test_threshold_accept(self, tmp_path):
        engine = self._make_engine(tmp_path)
        result = engine.evaluate_final(
            result={"confidence": 0.9}, state={}
        )
        action = engine.decide_retry(result)
        assert action == "accept"

    def test_threshold_below_fail(self, tmp_path):
        engine = self._make_engine(
            tmp_path,
            metrics=[
                EvalMetricConfig(
                    name="check",
                    kind="deterministic_test",
                    weight=1.0,
                    params={"expr": "False"},
                ),
            ],
            retry_policy=RetryPolicyConfig(enabled=True),
        )
        result = engine.evaluate_final(result={}, state={})
        action = engine.decide_retry(result)
        assert action == "fail_workflow"

    def test_artifact_written(self, tmp_path):
        engine = self._make_engine(tmp_path)
        engine.evaluate_final(result={"confidence": 0.9}, state={})
        path = engine.flush()
        assert path is not None
        assert path.exists()
        data = json.loads(path.read_text())
        assert data["run_id"] == "test-run-001"
        assert data["final_score"] is not None

    def test_summary(self, tmp_path):
        engine = self._make_engine(tmp_path)
        engine.evaluate_final(result={"confidence": 0.9}, state={})
        summary = engine.get_summary()
        assert "final_score" in summary
        assert "metrics" in summary
        assert len(summary["metrics"]) == 1

    def test_graceful_scorer_failure(self, tmp_path):
        engine = self._make_engine(
            tmp_path,
            metrics=[
                EvalMetricConfig(
                    name="bad",
                    kind="rubric_judge",
                    weight=1.0,
                ),
            ],
        )
        # No LLM client — rubric_judge should degrade to 0.0
        result = engine.evaluate_final(result={}, state={})
        assert result is not None
        assert result.score == 0.0
        assert result.metric_scores[0].evidence is not None
