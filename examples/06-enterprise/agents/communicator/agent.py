"""Communicator agent -- inter-agent communication hub."""
from awp import AWPAgent

class Agent(AWPAgent):
    @property
    def name(self) -> str:
        return "communicator"

    def run(self, task: str, state: dict) -> dict:
        return {self.name: {"communication_log": [], "confidence": 0.0}}
