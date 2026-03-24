from __future__ import annotations

from typing import Any, Dict

from awp.agent import AWPAgent


class Agent(AWPAgent):
    """AWP agent: analyst."""

    @property
    def name(self) -> str:
        return "analyst"

    def run(self, task: str, state: Dict[str, Any]) -> Dict[str, Any]:
        state = state or {}
        return {self.name: {"result": "default", "confidence": 0.0}}
