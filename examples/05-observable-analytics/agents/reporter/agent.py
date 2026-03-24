"""Reporter agent -- generates analytics reports."""
from awp import AWPAgent

class Agent(AWPAgent):
    @property
    def name(self) -> str:
        return "reporter"

    def run(self, task: str, state: dict) -> dict:
        return {self.name: {"report": "", "confidence": 0.0}}
