"""EvaluationEngine — orchestrates scoring, aggregation, and threshold decisions."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from . import scorers
from .artifact import EvalArtifactWriter
from .models import EvalResult, MetricScore, StepEvalRecord
from .retry import EvalRetryPolicy

if TYPE_CHECKING:
    from awp.models.evaluation import EvaluationConfig

    from ..llm import LLMClient

logger = logging.getLogger(__name__)


class EvaluationEngine:
    """Orchestrates metric evaluation, aggregation, and retry decisions.

    When ``config.enabled`` is False, every method is a no-op.
    """

    def __init__(
        self,
        config: "EvaluationConfig",
        workflow_dir: Path,
        run_id: str,
        llm_client: Optional["LLMClient"] = None,
    ) -> None:
        self._config = config
        self._workflow_dir = workflow_dir
        self._run_id = run_id
        self._llm_client = llm_client

        self._retry_policy = EvalRetryPolicy.from_config(config.retry_policy)

        artifact_dir = workflow_dir / config.artifact_path
        self._artifact_writer = EvalArtifactWriter(artifact_dir, run_id)

        self._step_count = 0
        self._final_result: Optional[EvalResult] = None

    @property
    def enabled(self) -> bool:
        return self._config.enabled

    # -- Public API -----------------------------------------------------------

    def evaluate_step(
        self,
        hook: str,
        result: dict[str, Any],
        state: dict[str, Any],
        budget: Any = None,
        agent_id: str = "",
    ) -> Optional[EvalResult]:
        """Evaluate at a step hook point. Returns None if evaluation is disabled
        or the hook is not configured.
        """
        if not self._config.enabled:
            return None

        step_cfg = self._config.step_scores
        if not step_cfg.enabled or hook not in step_cfg.hooks:
            return None

        eval_result = self._run_metrics(result, state, budget, hook, agent_id)

        self._step_count += 1
        record = StepEvalRecord(
            hook=hook,
            agent_id=agent_id,
            iteration=self._step_count,
            result=eval_result,
        )
        self._artifact_writer.record_step(record)

        return eval_result

    def evaluate_final(
        self,
        result: dict[str, Any],
        state: dict[str, Any],
        budget: Any = None,
    ) -> Optional[EvalResult]:
        """Run final evaluation on the completed workflow result."""
        if not self._config.enabled:
            return None

        eval_result = self._run_metrics(result, state, budget, "final_answer", "")
        self._final_result = eval_result
        return eval_result

    def decide_retry(self, eval_result: Optional[EvalResult] = None) -> str:
        """Decide what action to take based on the evaluation score.

        Returns: "accept" | "accept_with_warning" | "retry_with_repair" | "fail_workflow"
        """
        if not self._config.enabled or eval_result is None:
            return "accept"

        t = self._config.thresholds
        return self._retry_policy.decide(
            score=eval_result.score,
            accept=t.accept,
            retry=t.retry,
            fail=t.fail,
        )

    def record_retry(self) -> None:
        """Record that a retry was triggered by evaluation."""
        self._retry_policy.record_retry()

    @property
    def retries_used(self) -> int:
        return self._retry_policy.retries_used

    def get_summary(self) -> dict[str, Any]:
        """Return a summary dict suitable for inclusion in state."""
        if not self._config.enabled or self._final_result is None:
            return {}
        return {
            "final_score": round(self._final_result.score, 4),
            "action": self._final_result.action,
            "metrics": [
                {
                    "name": ms.name,
                    "kind": ms.kind,
                    "score": round(ms.score, 4),
                    "weight": ms.weight,
                }
                for ms in self._final_result.metric_scores
            ],
            "retries_used": self._retry_policy.retries_used,
        }

    def flush(self) -> Optional[Path]:
        """Persist the evaluation artifact to disk."""
        if not self._config.enabled:
            return None

        final = self._final_result
        self._artifact_writer.set_final(
            score=final.score if final else 0.0,
            action=final.action if final else "",
            result=final,
            retries_used=self._retry_policy.retries_used,
        )
        return self._artifact_writer.flush()

    # -- Internal -------------------------------------------------------------

    def _run_metrics(
        self,
        result: dict[str, Any],
        state: dict[str, Any],
        budget: Any,
        hook: str,
        agent_id: str,
    ) -> EvalResult:
        """Run all configured metrics and aggregate into a single EvalResult."""
        metric_scores: list[MetricScore] = []

        for metric_cfg in self._config.metrics:
            score, evidence = self._evaluate_single_metric(
                metric_cfg, result, state, budget
            )
            metric_scores.append(
                MetricScore(
                    name=metric_cfg.name,
                    kind=metric_cfg.kind,
                    score=score,
                    weight=metric_cfg.weight,
                    evidence=evidence,
                )
            )

        # Weighted aggregation
        total_weight = sum(ms.weight for ms in metric_scores if ms.weight > 0)
        if total_weight > 0:
            agg_score = sum(ms.score * ms.weight for ms in metric_scores) / total_weight
        else:
            agg_score = 0.0

        agg_score = max(0.0, min(1.0, agg_score))

        # Determine action
        t = self._config.thresholds
        action = self._retry_policy.decide(
            score=agg_score,
            accept=t.accept,
            retry=t.retry,
            fail=t.fail,
            budget=budget,
        )

        return EvalResult(
            score=agg_score,
            metric_scores=metric_scores,
            action=action,
            hook=hook,
            agent_id=agent_id,
        )

    def _evaluate_single_metric(
        self,
        metric_cfg: Any,
        result: dict[str, Any],
        state: dict[str, Any],
        budget: Any,
    ) -> tuple[float, str | None]:
        """Dispatch to the appropriate scorer. Never raises."""
        kind = metric_cfg.kind
        params = metric_cfg.params

        try:
            if kind == "deterministic_test":
                return scorers.score_deterministic_test(result, state, params)
            elif kind == "deterministic_assertion":
                return scorers.score_deterministic_assertion(result, state, params)
            elif kind == "rubric_judge":
                return scorers.score_rubric_judge(
                    result,
                    state,
                    params,
                    llm_client=self._llm_client,
                    rubric_config=self._config.rubric_judge,
                )
            elif kind == "budget_utility":
                return scorers.score_budget_utility(result, state, params, budget=budget)
            elif kind == "policy_score":
                return scorers.score_policy_score(result, state, params)
            else:
                return 0.0, f"Unknown metric kind: {kind}"
        except Exception as exc:
            logger.warning(
                "Scorer '%s' (kind=%s) failed: %s",
                metric_cfg.name,
                kind,
                exc,
            )
            return 0.0, f"Scorer error: {exc}"
