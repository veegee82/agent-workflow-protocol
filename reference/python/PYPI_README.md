# AWP — Agent Workflow Protocol

**An open standard for orchestrating multi-agent AI workflows.**

Define workflows in YAML. Run them in Python. Scale from a single agent to recursive delegation loops — with built-in budgets, validation, and safety controls.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)

---

## Why AWP?

Most agent frameworks couple workflow logic to a specific runtime. AWP separates **what** your agents do (YAML definitions) from **how** they run (Python runtime), giving you:

- **Declarative workflows** — Define agents, dependencies, and data flow in YAML
- **Two execution engines** — DAG engine (topological order) or delegation loop (manager-worker)
- **5 autonomy levels** — From prescribed pipelines (A0) to self-organizing recursive delegation (A4)
- **Built-in safety** — Token budgets, loop limits, wall-time caps, confidence thresholds
- **Any LLM provider** — OpenRouter, OpenAI, Anthropic, Ollama, Azure, or any OpenAI-compatible API
- **Code execution** — Sandboxed Python execution with venv or Docker isolation

## Quick Start

### Installation

```bash
pip install awp-agents

# With data science extras (pandas, numpy, Pillow)
pip install awp-agents[data]
```

### 3 Lines to a Running Workflow

```python
import os
os.environ["LLM_API_KEY"] = "sk-..."          # OpenRouter, OpenAI, etc.
os.environ["LLM_BASE_URL"] = "https://openrouter.ai/api/v1"

from awp.data import AgentWorkflow

result = AgentWorkflow(
    inputs={"data": {"revenue": [100, 200, 150], "month": ["Jan", "Feb", "Mar"]}},
    task="Analyze the revenue trend and identify the peak month",
    model="openrouter/anthropic/claude-sonnet-4",
).run()

print(result["status"])   # "complete"
print(result["result"])   # Analysis with insights
```

### Data Science with DataFrames

```python
import pandas as pd
from awp.data import AgentWorkflow

df = pd.DataFrame({
    "date": pd.date_range("2024-01-01", periods=90, freq="D"),
    "revenue": [100 + i * 2.5 + (i % 7) * 10 for i in range(90)],
    "region": ["EU", "US", "APAC"] * 30,
})

result = AgentWorkflow(
    inputs={"data": df, "config": {"threshold": 0.8}},
    task="Analyze revenue trends by region. Create visualizations and a summary report.",
    model="openrouter/anthropic/claude-sonnet-4",
    packages=["matplotlib", "scikit-learn"],
).run()
```

## YAML Workflow Definition

AWP separates workflow definition from execution. Define your agents in YAML:

```yaml
# workflow.awp.yaml
awp: "1.0"
name: research-pipeline
version: "1.0.0"

agents:
  - name: planner
    role: "Research planner"
    model: "openrouter/anthropic/claude-sonnet-4"
    share_output: [research_plan]

  - name: researcher
    role: "Deep researcher"
    model: "openrouter/anthropic/claude-sonnet-4"
    depends_on: [planner]
    share_output: [findings]

  - name: writer
    role: "Report writer"
    model: "openrouter/anthropic/claude-sonnet-4"
    depends_on: [researcher]
```

Run it:

```bash
awp run research-pipeline/ --task "Research quantum computing advances in 2024"
```

Or from Python:

```python
from awp.runtime import WorkflowRunner

runner = WorkflowRunner("research-pipeline/")
result = runner.run("Research quantum computing advances in 2024")
```

## The Autonomy Spectrum

| Level | Name | Engine | Description |
|-------|------|--------|-------------|
| **A0** | Prescribed | DAG | Fixed pipeline, no LLM decisions |
| **A1** | Guided | DAG | Agents use LLMs within fixed graph |
| **A2** | Delegating | Delegation Loop | Manager dispatches tasks to workers |
| **A3** | Creative | Delegation Loop | Workers can create tools and skills |
| **A4** | Autonomous | Recursive Delegation | Sub-managers spawn their own workers |

## Delegation Loop (A2-A4)

For complex tasks, AWP's delegation loop lets a manager agent dynamically create and assign tasks to worker agents:

```python
from awp.data import AgentWorkflow

result = AgentWorkflow(
    inputs={"dataset": my_data},
    task="Build a complete ML pipeline: EDA, feature engineering, model selection, and reporting",
    model="openrouter/anthropic/claude-sonnet-4",
    max_loops=10,
    max_workers=5,
    code_mode=True,        # Workers can execute Python
    tool_creation=True,    # Workers can create new tools
).run()
```

The manager:
1. Analyzes the task and creates a plan
2. Spawns specialized workers (EDA agent, modeling agent, reporting agent)
3. Validates each worker's output against confidence thresholds
4. Iterates until the task is complete or budget is exhausted

## CLI Tools

```bash
awp validate my-workflow/          # Validate against rules R1-R26
awp compliance my-workflow/ --level A2  # Check autonomy level compliance
awp visualize my-workflow/ --format mermaid  # Render workflow DAG
awp pack my-workflow/              # Package as .awp.zip archive
awp run my-workflow/ --task "..."  # Execute the workflow
```

## LLM Provider Configuration

AWP works with any OpenAI-compatible API:

```bash
# OpenRouter (50+ models, one key)
export LLM_API_KEY="sk-or-v1-..."
export LLM_BASE_URL="https://openrouter.ai/api/v1"

# OpenAI direct
export LLM_API_KEY="sk-..."
export LLM_BASE_URL="https://api.openai.com/v1"

# Ollama (local, free)
export LLM_API_KEY="ollama"
export LLM_BASE_URL="http://localhost:11434/v1"

# Azure OpenAI
export LLM_API_KEY="your-azure-key"
export LLM_BASE_URL="https://your-resource.openai.azure.com/openai/deployments/your-deployment/v1"
```

## Safety & Budget Controls

Every delegation loop runs within a hard safety envelope:

```yaml
delegation:
  budget:
    max_loops: 15          # Maximum manager iterations
    max_total_workers: 20  # Maximum worker spawns
    max_total_tokens: 500000  # Token budget across all agents
    max_wall_time: 300     # Wall-time limit in seconds
    max_depth: 3           # Recursive delegation depth (A4)
```

The manager cannot override these limits — they are enforced by the runtime.

## The 7-Layer Model

AWP organizes agent configuration into 7 semantic layers:

1. **Manifest** — Workflow metadata, version, agent list
2. **Identity** — Agent name, role, model selection
3. **Capabilities** — Tools, skills, data sources
4. **Communication** — Message bus, channels, protocols
5. **Memory** — 4-tier memory (working, episodic, semantic, procedural)
6. **Orchestration** — Graph structure, delegation config, budget
7. **Observability** — Tracing, metrics, audit trail

## Architecture

```
awp-agents
├── awp.models      — Pydantic models for all 7 layers
├── awp.parser      — YAML → typed Python objects
├── awp.validator   — Rule engine (R1-R26)
├── awp.runtime     — DAG engine + delegation loop engine
├── awp.data        — Programmatic API (AgentWorkflow)
├── awp.packager    — .awp.zip archive support
├── awp.visualizer  — Mermaid DAG rendering
└── awp.cli         — Command-line interface
```

## Links

- **GitHub**: [github.com/veegee82/agent-workflow-protocol](https://github.com/veegee82/agent-workflow-protocol)
- **Documentation**: [docs/](https://github.com/veegee82/agent-workflow-protocol/tree/main/docs)
- **Specification**: [spec/versions/1.0/spec.md](https://github.com/veegee82/agent-workflow-protocol/blob/main/spec/versions/1.0/spec.md)
- **Examples**: [examples/](https://github.com/veegee82/agent-workflow-protocol/tree/main/examples) — 12 runnable workflows (A0-A4)

## License

MIT License. See [LICENSE](https://github.com/veegee82/agent-workflow-protocol/blob/main/LICENSE).
