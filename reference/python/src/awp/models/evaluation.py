"""AWP Evaluation models (Layer 6 — Observability) — Quality scoring configuration."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field, model_validator

# --- Constants ---------------------------------------------------------------

VALID_METRIC_KINDS = frozenset(
    {
        "deterministic_test",
        "deterministic_assertion",
        "rubric_judge",
        "budget_utility",
        "policy_score",
    }
)

VALID_HOOKS = frozenset({"worker_result", "generated_tool", "final_answer"})

VALID_ACTIONS = frozenset({"retry_with_repair", "fail_workflow", "accept_with_warning"})


# --- Metric configuration ----------------------------------------------------


class EvalMetricConfig(BaseModel):
    """A single evaluation metric."""

    name: str
    kind: str  # one of VALID_METRIC_KINDS
    weight: float = 1.0
    params: dict[str, Any] = Field(default_factory=dict)

    model_config = {"extra": "allow"}


# --- Thresholds --------------------------------------------------------------


class EvalThresholds(BaseModel):
    """Score thresholds that drive accept / retry / fail decisions."""

    accept: float = 0.85
    retry: float = 0.65
    fail: float = 0.40

    @model_validator(mode="after")
    def _check_ordering(self) -> "EvalThresholds":
        for name, val in [
            ("accept", self.accept),
            ("retry", self.retry),
            ("fail", self.fail),
        ]:
            if not 0.0 <= val <= 1.0:
                raise ValueError(
                    f"Threshold '{name}' must be in [0.0, 1.0], got {val}"
                )
        if not (self.accept >= self.retry >= self.fail):
            raise ValueError(
                f"Thresholds must satisfy accept >= retry >= fail, "
                f"got accept={self.accept}, retry={self.retry}, fail={self.fail}"
            )
        return self

    model_config = {"extra": "allow"}


# --- Step scores --------------------------------------------------------------


class StepScoreConfig(BaseModel):
    """Which hooks trigger step-level scoring."""

    enabled: bool = True
    hooks: list[str] = Field(
        default_factory=lambda: ["worker_result", "final_answer"]
    )

    model_config = {"extra": "allow"}


# --- Retry policy -------------------------------------------------------------


class RetryActionConfig(BaseModel):
    """Maps score zones to actions."""

    below_retry: str = "retry_with_repair"
    below_fail: str = "fail_workflow"

    model_config = {"extra": "allow"}


class RetryPolicyConfig(BaseModel):
    """Score-driven retry / repair policy."""

    enabled: bool = False
    max_repairs: int = 2
    actions: RetryActionConfig = Field(default_factory=RetryActionConfig)

    model_config = {"extra": "allow"}


# --- Rubric judge -------------------------------------------------------------


class RubricJudgeConfig(BaseModel):
    """Configuration for the LLM-based rubric judge scorer."""

    model: Optional[str] = None
    temperature: float = 0.0

    model_config = {"extra": "allow"}


# --- Root evaluation config ---------------------------------------------------


class EvaluationConfig(BaseModel):
    """Complete evaluation / quality-scoring configuration.

    Lives under ``observability.evaluation`` in workflow.awp.yaml.
    When ``enabled`` is *False* (the default), the entire evaluation
    subsystem is a no-op and existing workflows behave identically.
    """

    enabled: bool = False
    metrics: list[EvalMetricConfig] = Field(default_factory=list)
    thresholds: EvalThresholds = Field(default_factory=EvalThresholds)
    step_scores: StepScoreConfig = Field(default_factory=StepScoreConfig)
    retry_policy: RetryPolicyConfig = Field(default_factory=RetryPolicyConfig)
    rubric_judge: RubricJudgeConfig = Field(default_factory=RubricJudgeConfig)
    artifact_path: str = "data/evaluation"

    model_config = {"extra": "allow"}
