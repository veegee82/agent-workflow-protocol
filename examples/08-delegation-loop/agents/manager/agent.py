"""Research Manager Agent — Delegates research subtasks to worker agents."""

from awp.agent import AWPAgent


class Agent(AWPAgent):
    @property
    def name(self) -> str:
        return "manager"

    def run(self, task: str, state: dict) -> dict:
        # In delegation_loop mode, the DelegationLoopRunner handles
        # this agent's execution. This class is provided for AWP
        # interface compliance and alternative runtime compatibility.
        return {self.name: {"decision": "complete", "confidence": 0.5}}
