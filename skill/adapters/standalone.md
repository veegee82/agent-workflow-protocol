# AWP Platform Adapter: Standalone (awp-agents)

This adapter generates `agent.py` files for the **AWP standalone runtime**
included in the `awp-agents` package.

## When to Use

Use this adapter when:
- You want to run AWP workflows without installing any external agent framework
- You are prototyping or testing a workflow
- You want the simplest possible setup

## agent.py Template

For each agent, generate this `agent.py`:

```python
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from awp.runtime.agent import StandaloneAgent
from awp.runtime.llm import LLMClient
from awp.runtime.tools import ToolRegistry


class Agent(StandaloneAgent):
    """AWP agent: {{AGENT_ID}}."""

    def __init__(
        self,
        agent_dir: str | Path | None = None,
        workflow_dir: str | Path | None = None,
        llm: Optional[LLMClient] = None,
        tool_registry: Optional[ToolRegistry] = None,
    ) -> None:
        super().__init__(
            agent_dir=agent_dir or Path(__file__).parent,
            workflow_dir=workflow_dir or Path(__file__).parents[2],
            llm=llm,
            tool_registry=tool_registry,
        )
```

## How Execution Works

The standalone runtime (`awp.runtime.WorkflowRunner`) dynamically imports the
`Agent` class from each agent's `agent.py` file. Because `Agent` inherits from
`StandaloneAgent`, it has full runtime capabilities out of the box:

1. Reads `agent.awp.yaml` for configuration
2. Loads prompts from `workflow/instructions/SYSTEM_PROMPT.md`
3. Loads user prompt from `workflow/prompt/00_INTRO.md`
4. Injects skills and memory into the system prompt
5. Builds context from previous agent outputs in state
6. Calls the LLM via an OpenAI-compatible API
7. Handles tool calling loops (if tools are configured)
8. Parses the response as JSON matching `output_schema.json`
9. Enforces R17 confidence field
10. Returns `{agent_id: parsed_result}`

If the import fails, the runner falls back to creating a `StandaloneAgent`
directly, ensuring backwards compatibility.

## Running a Workflow

```python
from awp.runtime import WorkflowRunner

runner = WorkflowRunner("path/to/my-workflow")
result = runner.run("Analyze the quarterly report")
print(result)
```

Or via CLI:

```bash
awp run path/to/my-workflow --task "Analyze the quarterly report"
```

Direct agent usage (no runner needed):

```python
from my_workflow.agents.researcher.agent import Agent

agent = Agent()  # auto-detects paths from __file__
result = agent.run("Research quantum computing", {})
print(result)
```

## Override Hooks

Every generated `Agent` inherits these methods from `StandaloneAgent`, all of
which can be overridden for custom behaviour:

| Method | Purpose |
|--------|---------|
| `run(task, state)` | Full execution pipeline — override for completely custom logic |
| `_build_system_prompt()` | Assemble system prompt (base + skills + memory) |
| `_build_user_message(task, state)` | Assemble user message (template + context + schema + task) |
| `_run_simple(messages, **kwargs)` | Single LLM call, parse as JSON |
| `_run_with_tools(messages, tool_defs, **kwargs)` | LLM call with tool calling loop |
| `_load_skills()` | Load and concatenate skill files |
| `_load_memory()` | Load MEMORY.md for injection |
| `_extract_context(state)` | Extract context from previous agent outputs |

### Example: Custom Post-Processing

```python
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from awp.runtime.agent import StandaloneAgent
from awp.runtime.llm import LLMClient
from awp.runtime.tools import ToolRegistry


class Agent(StandaloneAgent):
    """Researcher agent with custom post-processing."""

    def __init__(
        self,
        agent_dir: str | Path | None = None,
        workflow_dir: str | Path | None = None,
        llm: Optional[LLMClient] = None,
        tool_registry: Optional[ToolRegistry] = None,
    ) -> None:
        super().__init__(
            agent_dir=agent_dir or Path(__file__).parent,
            workflow_dir=workflow_dir or Path(__file__).parents[2],
            llm=llm,
            tool_registry=tool_registry,
        )

    def run(self, task: str, state: Dict[str, Any]) -> Dict[str, Any]:
        # Run the standard LLM pipeline
        result = super().run(task, state)

        # Custom post-processing
        agent_result = result[self.name]
        agent_result["custom_field"] = "enriched"

        return result
```

### Example: Custom System Prompt

```python
class Agent(StandaloneAgent):
    # ... __init__ as above ...

    def _build_system_prompt(self) -> str:
        base = super()._build_system_prompt()
        return base + "\n\nAlways respond in formal academic English."
```

## Dependencies

```
pip install awp-agents
```

Environment variables for LLM access:
```bash
export LLM_API_KEY=sk-...          # API key
export LLM_MODEL=provider/model    # Model identifier
export LLM_BASE_URL=https://...    # API endpoint (default: OpenRouter)
```
