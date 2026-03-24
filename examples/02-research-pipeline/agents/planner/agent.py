"""Planner agent -- creates research plans."""
from awp import AWPAgent

class Agent(AWPAgent):
    @property
    def name(self) -> str:
        return "planner"

    def run(self, task: str, state: dict) -> dict:
        return {self.name: {"research_questions": [], "search_strategy": "", "confidence": 0.0}}
