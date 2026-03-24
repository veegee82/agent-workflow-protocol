from __future__ import annotations

from typing import Any, Dict

from awp.agent import AWPAgent


class Agent(AWPAgent):
    """AWP agent: code_executor."""

    @property
    def name(self) -> str:
        return "code_executor"

    def run(self, task: str, state: Dict[str, Any]) -> Dict[str, Any]:
        state = state or {}
        return {self.name: {"result": "default", "confidence": 0.0}}
