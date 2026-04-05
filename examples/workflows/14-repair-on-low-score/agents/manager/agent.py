"""Manager agent for the repair-on-low-score example."""


class Agent:
    def __init__(self, agent_dir, workflow_dir, llm=None, tool_registry=None):
        self.name = "manager"
        self._llm = llm

    def run(self, task, state=None):
        return {
            self.name: {
                "confidence": 0.8,
                "report_md": f"# Analysis Report\n\nTask: {task}\n",
            }
        }
