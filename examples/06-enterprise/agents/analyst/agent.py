"""Analyst agent -- risk analysis with memory and skills."""
from awp import AWPAgent

class Agent(AWPAgent):
    @property
    def name(self) -> str:
        return "analyst"

    def run(self, task: str, state: dict) -> dict:
        return {self.name: {"risk_score": 0.0, "analysis": "", "confidence": 0.0}}
