"""Researcher agent -- conducts research using tools."""
from awp import AWPAgent

class Agent(AWPAgent):
    @property
    def name(self) -> str:
        return "researcher"

    def run(self, task: str, state: dict) -> dict:
        return {self.name: {"findings": [], "sources": [], "confidence": 0.0}}
