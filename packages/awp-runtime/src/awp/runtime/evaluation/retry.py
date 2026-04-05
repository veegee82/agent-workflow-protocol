"""Score-driven retry / repair policy."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class EvalRetryPolicy:
    """Decides what action to take based on score vs thresholds."""

    def __init__(
        self,
        enabled: bool = False,
        max_repairs: int = 2,
        below_retry_action: str = "retry_with_repair",
        below_fail_action: str = "fail_workflow",
    ) -> None:
        self.enabled = enabled
        self.max_repairs = max_repairs
        self.below_retry_action = below_retry_action
        self.below_fail_action = below_fail_action
        self.retries_used: int = 0

    @classmethod
    def from_config(cls, config: Any) -> "EvalRetryPolicy":
        """Build from a RetryPolicyConfig Pydantic model."""
        if config is None:
            return cls(enabled=False)
        return cls(
            enabled=config.enabled,
            max_repairs=config.max_repairs,
            below_retry_action=getattr(config.actions, "below_retry", "retry_with_repair"),
            below_fail_action=getattr(config.actions, "below_fail", "fail_workflow"),
        )

    def decide(
        self,
        score: float,
        accept: float,
        retry: float,
        fail: float,
        budget: Any = None,
    ) -> str:
        """Return the action to take for the given score.

        Returns one of: "accept", "accept_with_warning", "retry_with_repair", "fail_workflow".
        """
        if not self.enabled:
            if score >= accept:
                return "accept"
            return "accept_with_warning"

        if score >= accept:
            return "accept"

        if score >= retry:
            # Between retry and accept — acceptable but warn
            return "accept_with_warning"

        if score >= fail:
            # Between fail and retry — try repair if budget allows
            if self.can_retry(budget):
                return self.below_retry_action
            logger.warning(
                "Score %.2f is below retry threshold but no retries left "
                "(used %d/%d)",
                score,
                self.retries_used,
                self.max_repairs,
            )
            return "accept_with_warning"

        # Below fail threshold
        if self.can_retry(budget):
            return self.below_fail_action
        return "fail_workflow"

    def can_retry(self, budget: Any = None) -> bool:
        """Check if a retry is possible given repair count and budget."""
        if self.retries_used >= self.max_repairs:
            return False
        if budget is not None and hasattr(budget, "can_continue"):
            can_go, _ = budget.can_continue()
            if not can_go:
                return False
        return True

    def record_retry(self) -> None:
        """Record that a retry was used."""
        self.retries_used += 1
