"""Researcher agent -- uses persistent memory."""
from awp import AWPAgent

class Agent(AWPAgent):
    @property
    def name(self) -> str:
        return "researcher"

    def run(self, task: str, state: dict) -> dict:
        return {self.name: {"findings": [], "key_facts": [], "confidence": 0.0}}
