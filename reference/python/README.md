# AWP Protocol — Agent Workflow Protocol

Open standard for defining and orchestrating multi-agent workflows.
Separates workflow definition (YAML) from implementation (Python), spanning
an autonomy spectrum from **A0** (prescribed DAG) to **A4** (self-organizing
recursive delegation).

## Install

```bash
pip install awp-agents

# With DataFrame + numpy + image support
pip install awp-agents[data]
```

## Quick Start

### CLI — Validate & Run Workflows

```bash
# Validate a workflow (rules R1-R32)
awp validate path/to/workflow/

# Check autonomy level (A0-A4)
awp compliance path/to/workflow/ --level A2

# Visualize the agent DAG
awp visualize path/to/workflow/ --format mermaid

# Run a workflow
awp run path/to/workflow/ --task "Analyze quarterly report"
```

### Python — Programmatic API

```python
from awp.runtime import WorkflowRunner

runner = WorkflowRunner("path/to/my-workflow")
result = runner.run("Analyze the latest quarterly report")
```

### Data API — No YAML Required

Pass arbitrary inputs + a task, get JSON results back. Uses A4 delegation loop
with code_mode under the hood.

```python
import numpy as np
from awp.data import AgentWorkflow

result = AgentWorkflow(
    inputs={
        "data": df,                          # pandas DataFrame
        "matrix": np.random.rand(100, 50),   # numpy ndarray
        "photo": "/path/to/image.png",       # image (auto-detected by extension)
        "config": {"threshold": 0.8},        # dict
        "report": "/path/to/report.pdf",     # file path
    },
    task="Analyze trends and create visualizations",
    model="openrouter/anthropic/claude-sonnet-4",
    max_loops=5,
    max_wall_time=120,
    output_dir="./output",
).run()

# result: {"status": "complete", "result": {...}, "artifacts": [...], "metadata": {...}}
```

#### Supported Input Types

| Python type | InputType | Workspace format | Notes |
|------------|-----------|-----------------|-------|
| `pd.DataFrame` | `dataframe` | `.csv` | Schema with shape, columns, dtypes, stats |
| `np.ndarray` | `ndarray` | `.npy` | Schema with shape, dtype, min/max/mean/std |
| `str` (image path) | `image` | copy to `inputs/` | Auto-detected by extension (.png, .jpg, etc.). PIL metadata extracted if available |
| `str` (file path) | `file_path` | copy to `inputs/` | Any existing file/directory |
| `dict` | `dict` | `.json` | Full content inlined in manager prompt |
| `list` | `list` | `.json` | |
| `str` | `string` | inline | Stored in manifest, not as file |
| `int`/`float` | `numeric` | inline | |
| `bool` | `boolean` | inline | |
| `bytes` | `bytes` | `.bin` | |
| `None` | `none` | inline | |

## Architecture

### Two Orchestration Engines

| Engine | Autonomy | How it works |
|--------|----------|-------------|
| **DAG Engine** | A0–A1 | Topological execution, agents run in dependency order |
| **Delegation Loop** | A2–A4 | Manager-worker loop, dynamic task delegation, budget enforcement |

### 7 Semantic Layers

1. **Manifest** — workflow metadata and versioning
2. **Identity** — agent naming and description
3. **Capabilities** — tools, sandbox, code execution
4. **Communication** — message bus, inter-agent messaging
5. **Memory** — long-term, episodic, semantic memory
6. **Orchestration** — DAG, delegation loop, fan-out
7. **Observability** — logging, metrics, tracing, audit trail

## Package Structure

```
awp/
  models/     — Pydantic models for all 7 layers
  parser/     — YAML parser for workflow.awp.yaml and agent.awp.yaml
  validator/  — Rule engine (R1-R32)
  runtime/    — Execution engines, agents, tools, LLM client
  data/       — Programmatic AgentWorkflow API (no YAML required)
  cli.py      — CLI entry point
```

## Library Usage

```python
from awp.parser import parse_manifest, parse_agent
from awp.validator import validate_graph, validate_contracts, check_compliance

manifest = parse_manifest("workflow.awp.yaml")
agent = parse_agent("agents/researcher/agent.awp.yaml")
```

## Links

- [Specification](https://github.com/veegee82/agent-workflow-protocol/tree/main/spec)
- [Documentation](https://github.com/veegee82/agent-workflow-protocol/tree/main/docs)
- [Examples (A0-A4)](https://github.com/veegee82/agent-workflow-protocol/tree/main/examples)
- [Changelog](https://github.com/veegee82/agent-workflow-protocol/blob/main/CHANGELOG.md)

## License

MIT
