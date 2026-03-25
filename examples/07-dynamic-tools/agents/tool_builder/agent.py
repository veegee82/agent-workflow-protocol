"""Tool Builder agent -- creates scoring tools dynamically via Code Mode."""
from awp import AWPAgent


class Agent(AWPAgent):
    @property
    def name(self) -> str:
        return "tool_builder"

    def run(self, task: str, state: dict) -> dict:
        return {self.name: {"tools_created": 0, "tool_names": [], "confidence": 0.0}}
