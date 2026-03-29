# AWP — Agent Workflow Protocol

**The open standard for orchestrating multi-agent AI workflows.**

Define workflows in YAML. Run them in Python. Scale from a single agent to recursive delegation loops — with built-in budgets, validation, and safety controls.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)

---

## Installation

```bash
pip install awp-agents

# With data science extras (pandas, numpy, Pillow)
pip install awp-agents[data]

# With data source extras (SQL, S3)
pip install awp-agents[sources-all]

# Everything
pip install awp-agents[all]
```

## 3 Lines to a Running Workflow

```python
import os
os.environ["LLM_API_KEY"] = "sk-or-v1-..."
os.environ["LLM_BASE_URL"] = "https://openrouter.ai/api/v1"

from awp.data import AgentWorkflow

result = AgentWorkflow(
    inputs={"data": {"revenue": [100, 200, 150], "month": ["Jan", "Feb", "Mar"]}},
    task="Analyze the revenue trend and identify the peak month",
    model="openrouter/anthropic/claude-sonnet-4",
).run()

print(result["status"])     # "complete"
print(result["artifacts"])  # ["./output/chart.png", ...]
```

Works with **any OpenAI-compatible API**: OpenRouter (50+ models), OpenAI, Anthropic, Ollama (local, free), Azure, Bedrock.

## What Happens Under the Hood

`AgentWorkflow` creates a **delegation loop**: a manager agent breaks your task into subtasks and spawns specialized worker agents. Workers execute Python code in sandboxes (pandas, matplotlib, sklearn, etc.), create files, and report results. The manager validates outputs, iterates until done, and returns everything in a single call.

## Data Science Integration

Pass DataFrames, numpy arrays, images, and files directly — AWP handles serialization:

```python
import pandas as pd
import numpy as np
from awp.data import AgentWorkflow

result = AgentWorkflow(
    inputs={
        "sales": pd.DataFrame({"date": [...], "revenue": [...], "region": [...]}),
        "embeddings": np.random.rand(1000, 768),
        "logo": "/path/to/logo.png",
        "config": {"target": "churn", "metric": "f1"},
    },
    task="EDA, feature engineering, train 3 models, select best, create report.",
    model="openrouter/anthropic/claude-sonnet-4",
    packages=["scikit-learn", "matplotlib", "seaborn"],
    output_dir="./results",
).run()
```

### Supported Input Types

| Python Type | Processing |
|-------------|-----------|
| `pd.DataFrame` | CSV + schema (shape, dtypes, describe) |
| `np.ndarray` | .npy + schema (shape, dtype, statistics) |
| Image path (.png, .jpg, ...) | Copy + PIL metadata (dimensions, mode) |
| File/directory path | Copy to workspace |
| `dict` / `list` | JSON export |
| `str` / `int` / `float` | Inline in prompt |
| `Source` | Resolved at runtime (see Data Sources) |

## Data Sources — Fetch External Data

Declare external data as inputs. AWP resolves them before the workflow starts:

```python
from awp.data import AgentWorkflow, Source

result = AgentWorkflow(
    inputs={
        "api": Source.url("https://api.example.com/data.json",
                          headers={"Authorization": "Bearer $API_TOKEN"}),
        "db":  Source.sql("SELECT * FROM sales", dsn="sqlite:///data.db"),
        "s3":  Source.s3("s3://bucket/reports/q4.csv"),
        "logs": Source.glob("logs/**/*.json", root="/var/log/app"),
        "rest": Source.api("https://api.github.com/repos/user/repo",
                           jq=".stargazers_count"),
    },
    task="Cross-reference all data sources and produce a report.",
    model="openrouter/anthropic/claude-sonnet-4",
    secrets={"API_TOKEN": os.getenv("API_TOKEN", "")},
).run()
```

Sources: `url`, `sql`, `s3`, `glob`, `api`, `base64`, `clipboard`. All support caching, retries, and timeouts. Secret references (`$SECRET_NAME`) are substituted without exposing values to agents.

## Custom Tools, Skills & Secrets

### External Tools

Register your own Python functions, dict-based tools, or MCP servers:

```python
from awp.data import AgentWorkflow, ExternalTool

@ExternalTool(name="finance.stock_price", secrets=["API_KEY"])
def get_stock_price(*, ticker: str, period: str = "1mo") -> dict:
    """Get stock price data."""
    import yfinance as yf
    return {"prices": yf.download(ticker, period=period).to_dict()}

# MCP server (auto-discovers tools via JSON-RPC)
mcp_tools = ExternalTool.from_mcp("http://localhost:8080/mcp")

result = AgentWorkflow(
    inputs={"tickers": ["AAPL", "MSFT"]},
    task="Compare stock performance.",
    model="openrouter/anthropic/claude-sonnet-4",
    external_tools=[get_stock_price, *mcp_tools],
    secrets={"API_KEY": os.getenv("API_KEY", "")},
).run()
```

### Skills — Domain Knowledge

Inject Markdown-based domain knowledge. The manager selectively forwards relevant skills to workers:

```python
result = AgentWorkflow(
    inputs={"data": df},
    task="Analyze according to internal methodology.",
    model="openrouter/anthropic/claude-sonnet-4",
    skills=["skills/methodology.md", "skills/domain/"],
).run()
```

### Secrets

API keys injected into the tool registry. Agents never see the values:

```python
secrets={"YFINANCE_API_KEY": "...", "SERP_API_KEY": "..."}
```

## Runtime Tool & Skill Generation (A3+)

At autonomy level A3+, agents generate **new tools and skills at runtime**. The workflow author controls what's allowed via **namespace capabilities**:

```yaml
dynamic_tools:
  enabled: true
  allowed_namespaces:
    - "scoring"                               # compute only (default)
    - name: "api_client"                      # grant network access
      capabilities: [compute, network]
      network_allowlist: ["api.example.com"]
    - name: "data_proc"                       # grant filesystem access
      capabilities: [compute, filesystem]
```

| Capability | Unlocks | Always Denied |
|------------|---------|---------------|
| `compute` | pandas, numpy, math, json, ... | `os`, `subprocess`, `sys`, `ctypes`, `importlib`, `signal`, `multiprocessing` |
| `network` | `requests`, `httpx`, `urllib` | (same) |
| `filesystem` | `pathlib`, `glob`, `shutil` | (same) |

Agents cannot grant themselves additional permissions. The "always denied" set is enforced regardless of capabilities or sandbox type.

## YAML Workflows & CLI

Define agents in YAML, run with the CLI:

```yaml
awp: "1.0"
workflow:
  name: research-pipeline
  version: "1.0.0"
  description: "3-agent research pipeline"

orchestration:
  graph:
    - id: planner
      agent: agents/planner
      share_output: [research_plan]
    - id: researcher
      agent: agents/researcher
      depends_on: [planner]
      share_output: [findings]
    - id: writer
      agent: agents/writer
      depends_on: [researcher]
```

```bash
awp validate my-workflow/                      # Validate (R1-R26)
awp compliance my-workflow/ --level A2         # Check autonomy level
awp visualize my-workflow/ --format mermaid    # Render DAG
awp run my-workflow/ --task "..."              # Execute
```

## The Autonomy Spectrum (A0-A4)

| Level | Name | Engine | What's New |
|-------|------|--------|------------|
| **A0** | Prescribed | DAG | Fixed pipeline, no LLM decisions |
| **A1** | Adaptive | DAG | Conditional execution, state sharing |
| **A2** | Delegating | Delegation Loop | Manager-worker with budget |
| **A3** | Self-Tooling | Delegation Loop | Runtime tool/skill creation + safety envelope |
| **A4** | Self-Organizing | Recursive Delegation | Sub-managers, full observability |

**Safety scales with autonomy**: A2 requires budgets, A3 requires a safety envelope, A4 requires full observability. This is enforced by the validator.

## Budget & Safety

Every delegation loop runs within a hard safety envelope:

```yaml
budget:
  max_loops: 15
  max_total_workers: 20
  max_total_tokens: 500000
  max_wall_time: 300
  max_depth: 3
```

The manager cannot override these limits — they are enforced by the runtime.

## Execution Graph Visualization

After a run, generate an interactive HTML graph of the full execution:

```python
from awp.runtime.execution_graph import generate_execution_graph

generate_execution_graph(
    run_dir=Path("./output/workspace/runs/run_abc"),
    output_path=Path("./execution_graph.html"),
)
```

Shows managers, workers, tool calls, confidence levels, timing, and recursive sub-delegations. Self-contained HTML — open in any browser.

## The 7-Layer Model

AWP organizes agent configuration into 7 semantic layers:

1. **Manifest** — Metadata, version, dependencies
2. **Identity** — Agent name, role, model parameters
3. **Capabilities** — Tools, skills, data sources, sandbox
4. **Communication** — Message bus, channels
5. **Memory** — 4-tier memory (working, episodic, semantic, procedural)
6. **Orchestration** — DAG graph, delegation loop, budget
7. **Observability** — Tracing, metrics, audit trail

## Architecture

```
awp-agents
├── awp.models      — Pydantic models for all 7 layers
├── awp.parser      — YAML → typed Python objects
├── awp.validator   — Rule engine (R1-R26)
├── awp.runtime     — DAG engine + delegation loop + code executors
├── awp.data        — Programmatic API (AgentWorkflow, Source, ExternalTool)
├── awp.cli         — Command-line interface
├── awp.packager    — .awp.zip archive support
└── awp.visualizer  — Mermaid DAG rendering
```

## Links

- **GitHub**: [github.com/veegee82/agent-workflow-protocol](https://github.com/veegee82/agent-workflow-protocol)
- **Documentation**: [docs/](https://github.com/veegee82/agent-workflow-protocol/tree/main/docs)
- **Specification**: [spec/versions/1.0/spec.md](https://github.com/veegee82/agent-workflow-protocol/blob/main/spec/versions/1.0/spec.md)
- **Examples**: [examples/](https://github.com/veegee82/agent-workflow-protocol/tree/main/examples) — 12 runnable workflows (A0-A4)
- **Playground**: [Jupyter Notebook](https://github.com/veegee82/agent-workflow-protocol/blob/main/examples/jupyter/playground.ipynb)

## License

MIT License. See [LICENSE](https://github.com/veegee82/agent-workflow-protocol/blob/main/LICENSE).
