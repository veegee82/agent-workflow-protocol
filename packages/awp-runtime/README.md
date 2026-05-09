# awp-runtime

**Agent Workflow Protocol -- Execution Runtime**

DAG engine, delegation loop engine, LLM client, and tool registry for running [AWP workflows](https://github.com/veegee82/agent-workflow-protocol).

## Installation

```bash
# Full runtime
pip install awp-runtime

# With data science extras (pandas, numpy, Pillow)
pip install awp-runtime[data]

# With Docker executor support
pip install awp-runtime[docker]
```

This automatically installs [awp-core](https://pypi.org/project/awp-core/) as a dependency.

## What's included

- **DAG Engine** (`awp.runtime.WorkflowRunner`) -- Topological execution for A0-A1 workflows
- **Delegation Loop** (`awp.runtime.DelegationLoopRunner`) -- Manager-worker loop for A2-A4 workflows
- **LLM Client** (`awp.runtime.llm`) -- OpenAI-compatible LLM integration
- **Tool Registry** (`awp.runtime.ToolRegistry`) -- Tool management with namespace enforcement
- **Code Executors** -- Sandbox, venv, and Docker execution environments
- **Programmatic API** (`awp.data.AgentWorkflow`) -- Run workflows from Python in 3 lines

## Quick Start

```python
from awp.data import AgentWorkflow

result = AgentWorkflow(
    inputs={"data": my_dataframe},
    task="Analyze trends and create visualizations",
    model="openrouter/anthropic/claude-sonnet-4",
).run()
```

## License

Apache License 2.0 — see [LICENSE](https://github.com/veegee82/agent-workflow-protocol/blob/main/LICENSE) and [NOTICE](https://github.com/veegee82/agent-workflow-protocol/blob/main/NOTICE). (Versions ≤ 1.0.56 were released under MIT.)
