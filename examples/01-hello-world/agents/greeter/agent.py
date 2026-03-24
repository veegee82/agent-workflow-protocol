"""Greeter agent -- L0 Core example."""
from awp import AWPAgent

class Agent(AWPAgent):
    @property
    def name(self) -> str:
        return "greeter"

    def run(self, task: str, state: dict) -> dict:
        return {self.name: {"greeting": "", "tone": "", "confidence": 0.0}}
