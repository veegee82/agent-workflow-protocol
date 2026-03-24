"""Code executor agent -- runs computations."""
from awp import AWPAgent

class Agent(AWPAgent):
    @property
    def name(self) -> str:
        return "code_executor"

    def run(self, task: str, state: dict) -> dict:
        return {self.name: {"computation_result": {}, "metrics": {}, "confidence": 0.0}}
