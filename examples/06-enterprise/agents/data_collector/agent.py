"""Data collector agent -- gathers data from multiple sources."""
from awp import AWPAgent

class Agent(AWPAgent):
    @property
    def name(self) -> str:
        return "data_collector"

    def run(self, task: str, state: dict) -> dict:
        return {self.name: {"collected_data": {}, "data_summary": "", "confidence": 0.0}}
