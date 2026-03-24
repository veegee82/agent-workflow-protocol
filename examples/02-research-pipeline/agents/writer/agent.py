"""Writer agent -- produces research reports."""
from awp import AWPAgent

class Agent(AWPAgent):
    @property
    def name(self) -> str:
        return "writer"

    def run(self, task: str, state: dict) -> dict:
        return {self.name: {"report": "", "confidence": 0.0}}
