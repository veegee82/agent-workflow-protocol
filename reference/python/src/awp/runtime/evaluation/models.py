"""Runtime data models for evaluation results."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class MetricScore:
    """Score from a single evaluation metric."""

    name: str
    kind: str
    score: float  # [0.0, 1.0]
    weight: float
    evidence: Optional[str] = None
    error: Optional[str] = None


@dataclass
class EvalResult:
    """Aggregated evaluation result."""

    score: float  # weighted average [0.0, 1.0]
    metric_scores: list[MetricScore] = field(default_factory=list)
    action: str = "accept"  # accept | accept_with_warning | retry_with_repair | fail_workflow
    hook: str = ""
    agent_id: str = ""


@dataclass
class StepEvalRecord:
    """Record of a step-level evaluation."""

    hook: str
    agent_id: str
    iteration: int
    result: EvalResult
    timestamp: Optional[str] = None


@dataclass
class EvalArtifact:
    """Full evaluation artifact for a workflow run."""

    run_id: str
    final_score: Optional[float] = None
    final_action: str = ""
    step_records: list[StepEvalRecord] = field(default_factory=list)
    final_result: Optional[EvalResult] = None
    retries_used: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)
