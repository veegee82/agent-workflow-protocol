"""Report writer agent -- conditional execution based on risk score."""
from awp import AWPAgent

class Agent(AWPAgent):
    @property
    def name(self) -> str:
        return "report_writer"

    def run(self, task: str, state: dict) -> dict:
        return {self.name: {"final_report": "", "confidence": 0.0}}
