"""Analysis Manager Agent — Delegates analysis subtasks with recursive support."""

from awp.agent import AWPAgent


class Agent(AWPAgent):
    @property
    def name(self) -> str:
        return "analyzer"

    def run(self, task: str, state: dict) -> dict:
        return {self.name: {"decision": "complete", "confidence": 0.5}}
