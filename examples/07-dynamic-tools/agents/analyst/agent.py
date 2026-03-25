"""Analyst agent -- uses dynamically created scoring tools to rank items."""
from awp import AWPAgent


class Agent(AWPAgent):
    @property
    def name(self) -> str:
        return "analyst"

    def run(self, task: str, state: dict) -> dict:
        return {self.name: {"rankings": [], "summary": "", "confidence": 0.0}}
