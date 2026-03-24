"""Coordinator agent -- manages team via message bus."""
from awp import AWPAgent

class Agent(AWPAgent):
    @property
    def name(self) -> str:
        return "coordinator"

    def run(self, task: str, state: dict) -> dict:
        return {self.name: {"task_breakdown": [], "assignments": [], "confidence": 0.0}}
