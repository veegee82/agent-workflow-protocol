"""Tool Creation Manager."""
from awp.agent import AWPAgent

class Agent(AWPAgent):
    @property
    def name(self) -> str:
        return "manager"

    def run(self, task: str, state: dict) -> dict:
        return {self.name: {"decision": "complete", "confidence": 0.5}}
