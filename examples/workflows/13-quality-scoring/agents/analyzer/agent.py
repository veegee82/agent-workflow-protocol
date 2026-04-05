"""Analyzer agent for the quality-scoring example."""


class Agent:
    def __init__(self, agent_dir, workflow_dir, llm=None, tool_registry=None):
        self.name = "analyzer"
        self._llm = llm

    def run(self, task, state=None):
        return {
            self.name: {
                "analysis": f"Analysis of: {task}",
                "confidence": 0.85,
            }
        }
