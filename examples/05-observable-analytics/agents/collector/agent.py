"""Collector agent -- gathers analytics data."""
from awp import AWPAgent

class Agent(AWPAgent):
    @property
    def name(self) -> str:
        return "collector"

    def run(self, task: str, state: dict) -> dict:
        return {self.name: {"raw_data": {}, "data_quality": "", "confidence": 0.0}}
