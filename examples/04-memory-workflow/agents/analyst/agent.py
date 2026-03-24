"""Analyst agent -- analyzes with memory context."""
from awp import AWPAgent

class Agent(AWPAgent):
    @property
    def name(self) -> str:
        return "analyst"

    def run(self, task: str, state: dict) -> dict:
        return {self.name: {"analysis": "", "insights": [], "confidence": 0.0}}
