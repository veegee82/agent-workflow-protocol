<p align="center">
  <img src="assets/awp_logo.png" alt="AWP Logo" width="200" />
</p>

<h1 align="center">AWP -- Agent Workflow Protocol</h1>

<p align="center">
  <strong>The open standard for orchestrating multi-agent AI workflows.</strong><br/>
  Define in YAML. Run in Python. Scale from a single agent to recursive delegation loops.
</p>

<p align="center">
  <a href="https://pypi.org/project/awp-agents/"><img src="https://img.shields.io/pypi/v/awp-agents?color=blue&label=PyPI" alt="PyPI version"/></a>
  <a href="https://pypi.org/project/awp-agents/"><img src="https://img.shields.io/pypi/pyversions/awp-agents" alt="Python versions"/></a>
  <a href="https://pypi.org/project/awp-agents/"><img src="https://img.shields.io/pypi/dm/awp-agents?color=green&label=Downloads" alt="Downloads"/></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="License: MIT"/></a>
  <a href="https://github.com/veegee82/agent-workflow-protocol/stargazers"><img src="https://img.shields.io/github/stars/veegee82/agent-workflow-protocol?style=flat&color=orange" alt="GitHub stars"/></a>
</p>

<p align="center">
  <code>pip install awp-agents</code>
</p>

<p align="center">
  <a href="docs/">Docs</a> &middot;
  <a href="examples/">Examples</a> &middot;
  <a href="spec/versions/1.0/spec.md">Specification</a> &middot;
  <a href="https://pypi.org/project/awp-agents/">PyPI</a> &middot;
  <a href="skill/SKILL.md">AWP Skill</a> &middot;
  <a href="README_GENERATION.md">Workflow Generation</a> &middot;
  <a href="README_NERD.md">Theory</a>
</p>

---

## Table of Contents

**From concrete to abstract:**
1. [Quickstart: 3 Lines of Code](#1-quickstart-3-lines-of-code)
2. [Data Science Integration](#2-data-science-integration)
3. [Enterprise Architecture](#3-enterprise-architecture)
4. [Infrastructure Benchmarking](#4-infrastructure-benchmarking)
5. [YAML Workflows & CLI](#5-yaml-workflows--cli)
6. [The Delegation Loop in Detail](#6-the-delegation-loop-in-detail)
7. [Budget, Safety, Validation](#7-budget-safety-validation)
8. [The Autonomy Spectrum (A0-A4)](#8-the-autonomy-spectrum-a0-a4)
9. [The 7-Layer Model](#9-the-7-layer-model)
10. [Repository & Links](#10-repository--links)

---

## 1. Quickstart: 3 Lines of Code

<p align="center">
  <img src="assets/quickstart-flow.svg" alt="Quickstart Flow" width="100%"/>
</p>

### Installation

```bash
pip install awp-agents

# With data science extras (pandas, numpy, Pillow)
pip install awp-agents[data]

# With all optional dependencies
pip install awp-agents[all]
```

**For local development** (editable install from this repo):

```bash
pip install -e "reference/python/[data]"
```

### What's Inside

| Module | What it provides |
|--------|------------------|
| `awp.models` | Pydantic models for all 7 AWP layers |
| `awp.parser` | Parse `workflow.awp.yaml` and `agent.awp.yaml` into typed objects |
| `awp.validator` | Rule engine (R1-R26): naming, graph structure, budgets |
| `awp.runtime` | DAG engine + delegation loop engine, LLM client, tool registry, code executors |
| `awp.data` | Programmatic API — `AgentWorkflow` for 3-line workflows |
| `awp.cli` | CLI: `awp validate`, `awp compliance`, `awp visualize`, `awp run` |

```python
from awp.models import AWPManifest
from awp.validator import validate_rules
from awp.runtime import WorkflowRunner
from awp.data import AgentWorkflow
```

### Configure LLM Provider

```python
import os

# Option A: OpenRouter (50+ models, one key)
os.environ["LLM_API_KEY"] = "sk-or-v1-..."
os.environ["LLM_BASE_URL"] = "https://openrouter.ai/api/v1"

# Option B: Ollama (local, free)
os.environ["LLM_API_KEY"] = "ollama"
os.environ["LLM_BASE_URL"] = "http://localhost:11434/v1"

# Option C: OpenAI / Azure / Bedrock
os.environ["LLM_API_KEY"] = "sk-..."
os.environ["LLM_BASE_URL"] = "https://api.openai.com/v1"
```

### First Workflow

```python
import numpy as np
import pandas as pd
from awp.data import AgentWorkflow

df = pd.DataFrame({
    "date": pd.date_range("2024-01-01", periods=100, freq="D"),
    "revenue": [100 + i * 2.5 + (i % 7) * 10 for i in range(100)],
    "region": ["EU", "US", "APAC", "EU", "US"] * 20,
})

# Inputs: DataFrames, numpy arrays, images (by path), dicts, strings, ...
result = AgentWorkflow(
    inputs={
        "sales_data": df,                             # pandas DataFrame -> CSV
        "weights": np.array([0.5, 0.3, 0.2]),        # numpy -> .npy
        "logo": "/path/to/company_logo.png",          # image -> copy + metadata
    },
    task="Analyze the sales data: trends per region, weighted growth rates, summary.",
    model="openrouter/anthropic/claude-sonnet-4",
    max_loops=5,
    output_dir="./analysis",
).run()

print(result["status"])      # "complete"
print(result["artifacts"])   # ["./analysis/output/chart.png", ...]
print(result["metadata"])    # {"loops": 3, "tokens_used": 45000, "wall_time": 42.5, ...}
```

**What happens**: AWP creates a manager agent that breaks the task into subtasks. Worker agents execute Python code in sandboxes (pandas, matplotlib, sklearn). Results are validated and aggregated. All in a single call.

---

## 2. Data Science Integration

<p align="center">
  <img src="assets/data-science-workflow.svg" alt="Data Science with AWP" width="100%"/>
</p>

### The Notebook Problem -- and AWP's Solution

| Problem | AWP Solution |
|---------|-------------|
| Monolithic notebooks without structure | Agent-based decomposition into subtasks |
| "It worked on my machine" | Sandbox execution, complete artifact documentation |
| One analysis, many datasets | Delegation loop with dynamic worker creation |
| Results lost in Slack | Persistent workspace artifacts with Markdown reports |

### Supported Input Types

AWP classifies inputs automatically:

| Python Type | InputType | Workspace Format | Processing |
|------------|-----------|-----------------|-------------|
| `pd.DataFrame` | `dataframe` | `.csv` | Schema (shape, dtypes, head, describe) |
| `np.ndarray` | `ndarray` | `.npy` | Schema (shape, dtype, min/max/mean/std) |
| `str` (image path) | `image` | copy to `inputs/` | Auto-detected by extension (.png, .jpg, .gif, .bmp, .tiff, .webp, ...), PIL metadata (width, height, mode) |
| `str` (file path) | `file_path` | copy to `inputs/` | Any files/directories |
| `dict` / `list` | `dict` / `list` | `.json` | JSON export, dicts inlined in manager prompt |
| `str` / `int` / `float` | `string` / `numeric` | inline | Directly in manager prompt |
| `bytes` | `bytes` | `.bin` | Binary file in workspace |

**numpy arrays** are stored losslessly as `.npy`. Workers load them via `np.load()`.
**Images** are detected by file extension (not MIME type). If PIL/Pillow is available, dimensions, color mode, and format are extracted and reported to the manager.

### Workflow Examples

#### Exploratory Data Analysis

```python
result = AgentWorkflow(
    inputs={"dataset": df_raw},
    task="""
    Perform a complete EDA:
    1. Data quality (null values, duplicates, outliers)
    2. Statistical summary per feature
    3. Correlation analysis
    4. Visualizations (histograms, boxplots, scatter)
    5. Actionable recommendations
    """,
    model=MODEL,
    max_loops=8,
    packages=["matplotlib", "seaborn", "scipy"],
    output_dir="./eda",
).run()
```

#### numpy as Data Source

numpy arrays are stored as `.npy` in the workspace and can be loaded by workers via `np.load()`. Schema information (shape, dtype, statistics) is automatically available to the manager.

```python
import numpy as np

# Combination: DataFrame + numpy array
embeddings = np.random.rand(1000, 768)       # e.g. sentence embeddings
labels = np.array(["pos", "neg", "neutral"] * 333 + ["pos"])

result = AgentWorkflow(
    inputs={
        "customers": df_customers,            # DataFrame with customer data
        "embeddings": embeddings,             # numpy: embedding matrix
        "labels": labels,                     # numpy: string array
        "config": {"n_clusters": 5, "metric": "cosine"},
    },
    task="Perform clustering on the embeddings (KMeans), "
         "derive cluster profiles from the customer data, visualize with t-SNE.",
    model=MODEL,
    packages=["scikit-learn", "matplotlib"],
    output_dir="./clustering",
).run()
```

Worker code looks like this:
```python
import numpy as np
import pandas as pd

embeddings = np.load(_workspace_dir + "/inputs/embeddings.npy")  # (1000, 768)
labels = np.load(_workspace_dir + "/inputs/labels.npy")          # (1000,)
df = pd.read_csv(_workspace_dir + "/inputs/customers.csv")
```

#### Image Analysis

Images are automatically detected by file extension, copied to the workspace, and enriched with PIL metadata (dimensions, color mode, format).

```python
result = AgentWorkflow(
    inputs={
        "scan": "/path/to/document_scan.png",        # image by path
        "reference": "/path/to/template.jpg",        # second image
        "rules": {"min_confidence": 0.85, "language": "en"},
    },
    task="Compare the scan with the reference template. "
         "Extract all text fields, check for deviations.",
    model=MODEL,
    packages=["Pillow", "pytesseract"],
).run()
```

#### Feature Engineering & Modeling

```python
result = AgentWorkflow(
    inputs={
        "train": df_train,
        "test": df_test,
        "config": {"target": "churn", "metric": "f1_score"},
    },
    task="Feature engineering, train three models (LogReg, RandomForest, XGBoost), "
         "cross-validation, select best model, create report.",
    model=MODEL,
    packages=["scikit-learn", "xgboost"],
).run()
```

#### Automated Quarterly Reports

```python
result = AgentWorkflow(
    inputs={
        "q4": df_q4, "q3": df_q3,
        "targets": {"revenue_target": 1_000_000, "growth_target": 0.15},
    },
    task="Quarter comparison Q3 vs Q4: target achievement, deviation analysis, "
         "top/bottom products, visualizations, executive summary.",
    model=MODEL,
    output_dir="./quarterly_report",
).run()
```

#### NLP & Sentiment Analysis

```python
result = AgentWorkflow(
    inputs={"reviews": df_reviews},
    task="Sentiment analysis: sentiment distribution, topic modeling, "
         "word clouds, temporal trends.",
    model=MODEL,
    packages=["nltk", "wordcloud"],
).run()
```

### Pipeline Integration

AWP integrates seamlessly into existing data science toolchains:

```python
# In Airflow
def analysis_task(**ctx):
    df = ctx["ti"].xcom_pull(task_ids="load_data")
    return AgentWorkflow(inputs={"data": df}, task="...", model=MODEL).run()

# In FastAPI
@app.post("/analyze")
async def analyze(data: UploadFile):
    df = pd.read_csv(data.file)
    return AgentWorkflow(inputs={"upload": df}, task="...", model=MODEL).run()

# In CI/CD (automated report)
result = AgentWorkflow(
    inputs={"data": "/data/daily_export.csv"},
    task="Daily anomaly report",
    model=MODEL,
).run()
```

### Parameter Reference

| Parameter | Default | Description |
|-----------|---------|-------------|
| `model` | *(required)* | LLM model (e.g. `openrouter/anthropic/claude-sonnet-4`) |
| `worker_model` | = `model` | Separate model for workers |
| `max_loops` | 10 | Max delegation iterations |
| `max_total_tokens` | 500,000 | Total token limit |
| `max_wall_time` | 300 | Time limit in seconds |
| `max_tool_calls` | 100 | Max tool invocations |
| `max_total_workers` | 30 | Max worker agents |
| `max_depth` | 5 | Recursion depth (A4) |
| `sandbox` | `"subprocess"` | subprocess / docker / venv / none |
| `packages` | `[]` | Extra pip packages for sandbox |
| `output_dir` | *(temp)* | Artifact directory |
| `verbose` | `False` | Enable debug logging |
| `tools` | code.execute + file.* | Available worker tools |
| `forbidden_tools` | shell.execute, file.write_outside_workspace | Blocked tools |

---

## 3. Enterprise Architecture

<p align="center">
  <img src="assets/enterprise-architecture.svg" alt="Enterprise Architecture" width="100%"/>
</p>

### AWP in Enterprise Infrastructure

AWP replaces nothing -- it **plugs into existing systems**:

```
  AWP Tool Interface              Your Backend
  ──────────────────              ──────────────────────
  memory.search    ──────────→   Pinecone / Weaviate / pgvector
  web.search       ──────────→   Internal Search API
  custom.erp       ──────────→   SAP / Salesforce
  file.read        ──────────→   S3 / ADLS / GCS
  Skills (.md)     ──────────→   Confluence Export
  Tracing          ──────────→   Datadog / Grafana / Splunk
  Secrets          ──────────→   Vault / AWS SSM / Azure KV
```

The YAML never changes -- only the backend behind the MCP tool interface.

### Governance by Design

| Enterprise Requirement | AWP Mechanism |
|------------------------|----------------|
| **Audit Trail** | Dual logging: JSON (machines) + Markdown (humans) per iteration |
| **Cost Control** | Budget system: 6 hard limits (tokens, time, workers, loops, tools, depth) |
| **Isolation** | Sandbox: subprocess, Docker, venv -- code never runs directly on the host |
| **Compliance** | `awp validate` (R1-R26) + `awp compliance --level A2` as CI/CD gate |
| **Versioning** | YAML in Git, `.awp.zip` for registry and distribution |
| **Secrets** | `required_secrets` mechanism, never stored in YAML |
| **Traceability** | Every manager decision, worker delegation, and tool call documented |

### CI/CD Integration

```bash
# Pre-commit hook: workflow validation
awp validate ./workflows/quarterly-report/

# Pipeline gate: check autonomy level
awp compliance ./workflows/quarterly-report/ --level A2

# Conformance tests
pytest conformance/ -x
```

### Industry Scenarios

#### Finance

```python
AgentWorkflow(
    inputs={"portfolio": df_portfolio, "market_data": df_market,
            "regulation": {"framework": "Basel III"}},
    task="VaR calculation, stress tests, regulatory report.",
    model=MODEL, sandbox="docker",  # max isolation
).run()
```

#### Manufacturing & IoT

```python
AgentWorkflow(
    inputs={"sensors": df_iot},
    task="Anomaly detection on sensor time series, predictive maintenance.",
    model=MODEL, packages=["prophet", "scikit-learn"],
    max_wall_time=120,  # time-critical
).run()
```

#### Healthcare

```python
AgentWorkflow(
    inputs={"study_data": df_clinical,
            "protocol": {"phase": "III", "endpoints": ["primary", "secondary"]}},
    task="Statistical analysis, subgroup analyses, safety report.",
    model=MODEL, sandbox="docker", packages=["scipy", "lifelines"],
).run()
```

### Workspace Artifacts (Audit Trail)

Every run produces complete documentation:

```
output_dir/
+-- workspace/
|   +-- inputs/                     # Prepared inputs
|   +-- input_manifest.json         # Metadata for all inputs
|   +-- runs/{run_id}/
|       +-- RUN_SUMMARY.md          # Human-readable summary
|       +-- run_manifest.json       # Run configuration
|       +-- iterations/
|       |   +-- 001/
|       |   |   +-- ITERATION_SUMMARY.md
|       |   |   +-- manager_decision.json    # Raw manager decision
|       |   |   +-- budget_snapshot.json     # Budget after iteration
|       |   |   +-- delegations/
|       |   |       +-- worker_a/
|       |   |           +-- envelope.json    # Worker assignment
|       |   |           +-- result.json      # Worker result
|       |   |           +-- tool_calls.json  # Executed tools
|       |   |           +-- RESULT.md        # Human-readable
|       |   +-- 002/, 003/, ...
|       +-- history/
|       |   +-- rolling_summary.json         # Context management
|       +-- artifacts/
|           +-- skills/                      # Generated skills
|           +-- tools/                       # Tool calls
+-- output/                                  # Final output files
```

---

## 4. Infrastructure Benchmarking

<p align="center">
  <img src="assets/benchmark-framework.svg" alt="AWP as Benchmark Framework" width="100%"/>
</p>

### The Core Idea: The Workflow Is the Benchmark

Because AWP separates workflow definition from infrastructure, organizations can **run identical agent workflows on different backends** and compare results objectively. No synthetic benchmarks, no framework bias -- real agents, real tasks, different backends.

### What Can Be Benchmarked

| Infrastructure Component | How AWP Benchmarks | Example |
|--------------------------|-------------------|---------|
| **LLM Providers** | Same workflow, different models | Claude vs. GPT-4o vs. Llama: quality, speed, cost |
| **Vector Databases** | Same RAG workflow, different `memory.search` backends | Pinecone vs. Weaviate vs. pgvector: recall, latency |
| **Sandbox Technologies** | Same code-mode workflow, different sandboxes | subprocess vs. Docker vs. venv: startup time, isolation |
| **Observability Platforms** | Same workflow, different tracing backends | Datadog vs. Grafana: overhead, completeness |
| **Orchestration Runtimes** | Same YAML, different engines | Python runtime vs. Cloudflare Workers: throughput |
| **Security Implementations** | Same A3 workflow, different sandbox configs | Rate limiter comparison, sandbox escape tests |

### Example: Setting Up an LLM Benchmark

```python
import json

MODELS = [
    "openrouter/anthropic/claude-sonnet-4",
    "openrouter/openai/gpt-4o",
    "openrouter/meta-llama/llama-3.1-405b-instruct",
    "openrouter/google/gemini-pro-1.5",
]

results = {}
for model in MODELS:
    result = AgentWorkflow(
        inputs={"data": df_benchmark},
        task="Analyze the dataset: trends, outliers, top 3 insights.",
        model=model,
        max_loops=5,
        max_wall_time=300,
        output_dir=f"./benchmark/{model.split('/')[-1]}",
    ).run()

    results[model] = {
        "status": result["status"],
        "confidence": result["result"].get("confidence", 0),
        "tokens": result["metadata"]["tokens_used"],
        "wall_time": result["metadata"]["wall_time"],
        "loops": result["metadata"]["loops"],
        "workers": result["metadata"]["workers_spawned"],
    }

# Result: objective comparison across identical tasks
print(json.dumps(results, indent=2))
```

### Comparable Metrics

Because all runs share the same output contract, results are directly comparable:

| Metric | What It Measures | Source |
|--------|-------------|--------|
| **Confidence** | Result quality (self-reported) | `result.confidence` |
| **Wall Time** | Total runtime | `metadata.wall_time` |
| **Tokens Used** | LLM consumption | `metadata.tokens_used` |
| **Workers Spawned** | How many agents were needed | `metadata.workers_spawned` |
| **Loops** | Iteration efficiency | `metadata.loops` |
| **Status** | Success rate | `result.status` |
| **Artifacts** | What was produced | `result.artifacts` |

### Community Benchmark Suites

AWP enables standardized benchmark suites:

```bash
# Run all example workflows as benchmarks
for dir in examples/0{1..6}*/; do
    awp run "$dir" --task "Standard benchmark" \
        --manager-model "$MODEL_A" \
        --output-dir "./bench/model_a/$(basename $dir)"
done

# Same workflows with a different backend
for dir in examples/0{1..6}*/; do
    awp run "$dir" --task "Standard benchmark" \
        --manager-model "$MODEL_B" \
        --output-dir "./bench/model_b/$(basename $dir)"
done

# Comparison: same workflows, same tasks, different models
```

**The paradigm shift**: Instead of "who has the best framework?" the question becomes "who has the best infrastructure?" -- which is what the real competition should be.

---

## 5. YAML Workflows & CLI

### For Reproducible, Versionable Pipelines

In addition to the programmatic API (`AgentWorkflow`), AWP offers declarative YAML workflows:

#### A0: Static DAG

```yaml
awp: "1.0.0"
name: analysis_pipeline
execution:
  mode: sequential
agents:
  - id: load_data
    path: agents/load_data
  - id: analyze
    path: agents/analyze
    depends_on: [load_data]
  - id: report
    path: agents/report
    depends_on: [analyze]
state:
  sharing:
    - from: load_data
      share_output: [dataframe_path]
```

#### A1: DAG with Conditions

```yaml
- id: deep_analysis
  agent: deep_analyzer
  depends_on: [initial_scan]
  when: "state.initial_scan.risk_score > 0.7"
```

#### A2: Delegation Loop

```yaml
orchestration:
  engine: delegation_loop
  delegation_loop:
    manager: agents/manager
    models:
      manager: openrouter/anthropic/claude-sonnet-4
      worker: openrouter/anthropic/claude-sonnet-4
    budget:
      max_loops: 10
      max_total_workers: 20
      max_total_tokens: 500000
      max_wall_time: 600
    worker_policy:
      enforced:
        sandbox: { type: subprocess }
        forbidden_tools: [shell.execute]
      manager_controlled:
        - instructions
        - skills
        - tools_allowed
        - codemode.enabled
```

### CLI Reference

```bash
awp run <dir> --task "..."                        # Execute workflow
awp run <dir> --task "..." --manager-model opus   # Model split
awp validate <dir>                                # Check rules R1-R26
awp compliance <dir> --level A2                   # Check autonomy level
awp visualize <dir> --format mermaid              # Visualize DAG
awp pack <dir>                                    # Create .awp.zip
awp identity-card <agent.awp.yaml>                # Show agent capabilities
```

### Design Patterns

```
Pipeline (A0-A1)         planner -> researcher -> writer
Fan-Out/Fan-In (A1)      splitter -> [w1, w2, w3] -> aggregator
Conditional (A1)         analyzer -> (risk>0.7) -> deep | summary
Manager-Worker (A2)      manager -> [workers] -> validate -> iterate
Tool Builder (A3)        iter1: build tools -> iter2: use tools
Self-Organizing (A4)     manager -> [sub_mgr_a, sub_mgr_b] -> recursive
```

---

## 6. The Delegation Loop in Detail

The delegation loop is the engine behind A2-A4 -- and behind `AgentWorkflow`:

<p align="center">
  <img src="assets/delegation-loop.svg" alt="Delegation Loop" width="100%"/>
</p>

### Flow per Iteration

1. **Manager receives**: Task + previous results + rolling summary + budget status
2. **Manager decides**: `DELEGATE` (new workers) | `COMPLETE` (done) | `FAIL` (give up)
3. **On DELEGATE**:
   - Generate worker envelopes (instructions, skills, tools, output_contract)
   - Start workers in parallel in sandboxes (**fan-out**)
   - Collect results
4. **Two-Tier Validation**:
   - Tier 1: Deterministic (schema, required fields, types) -- always runs
   - Tier 2: Semantic (LLM checks plausibility) -- only at low confidence
5. **Budget check** + **stall detection**
6. **Update rolling summary** -> next iteration

### Fan-Out: Parallel Workers

```json
{
  "decision": "delegate",
  "delegations": [
    { "worker_id": "trend_analysis", "instructions": "..." },
    { "worker_id": "outlier_detection", "instructions": "..." },
    { "worker_id": "visualization", "instructions": "..." }
  ]
}
```

All workers run in parallel -- like a DAG within a single iteration.

### Code Mode: Full Programs Instead of Individual Tool Calls

```
Classic:    Agent -> LLM -> tool -> result -> LLM -> tool -> result  (3 roundtrips)
Code Mode:  Agent -> LLM -> Python program -> sandbox executes      (1 roundtrip)
```

Workers write complete programs with `_workspace_dir` and `_output_dir` as predefined variables.

### Rolling Summary: Context Window Management

Older iterations are compressed, latest remain in full text:

```yaml
history:
  rolling_summary: true       # Enabled
  full_results_window: 3      # Last 3 iterations in full
  persist_to_disk: true       # Older ones to disk
```

---

## 7. Budget, Safety, Validation

### Budget System (Required from A2)

Six hard limits -- the manager cannot override them:

```yaml
budget:
  max_loops: 20              # Delegation iterations
  max_total_workers: 30      # Total workers
  max_total_tokens: 1000000  # LLM token cap
  max_wall_time: 600         # Seconds
  max_tool_calls: 200        # Tool invocations
  max_depth: 5               # Recursion depth (A4)
```

On exceeding a limit: graceful termination with a report of which limit was reached.

### Run Budget Limits (for any workflow type)

Independent of the delegation loop budget, there are global limits:

```yaml
orchestration:
  run_budget:
    max_wall_time: 300
    max_total_tokens: 500000
    max_cost_usd: 5.0
    enabled_limits: [max_wall_time, max_total_tokens]
```

For free models (`:free` suffix), `max_cost_usd` is automatically disabled.

### Safety Envelope (Required from A3)

The manager controls *what* workers do -- but not *how safely*:

```yaml
worker_policy:
  enforced:                         # IMMUTABLE
    sandbox: {type: subprocess, max_memory_mb: 512}
    rate_limiting: {max_llm_calls_per_minute: 30}
    forbidden_tools: [shell.execute]
    codemode: {max_tools_per_worker: 10}
  manager_controlled:               # Manager may change
    - instructions
    - skills
    - tools_allowed
    - output_contract
    - codemode.enabled
```

### Stall Detection

```yaml
termination:
  enabled: true
  window: 3                    # Last 3 iterations
  min_confidence_delta: 0.05   # Minimum progress
  action: warn_then_stop
```

### Validation Rules R1-R26

```bash
awp validate ./my-workflow/    # Checks all 26 rules
```

| Category | Rules | Checks |
|-----------|--------|--------|
| Identity | R1-R4 | Naming, uniqueness, conventions |
| Structure | R5-R10 | Directories, config files, prompts |
| Graph | R11-R13 | No cycles, dependencies, state sharing |
| Tools & Output | R14-R18 | Tool references, **confidence (R17)**, JSON schema |
| Budget & Security | R19-R26 | Budget limits, memory, namespaces, sandbox |

### Two-Tier Validation

<p align="center">
  <img src="assets/validation-pipeline.svg" alt="Two-Tier Validation" width="100%"/>
</p>

- **Tier 1** (deterministic, always): Schema, required fields, types
- **Tier 2** (semantic, optional): LLM checks whether the result *makes sense* -- only at low confidence

---

## 8. The Autonomy Spectrum (A0-A4)

<p align="center">
  <img src="assets/autonomy-spectrum.svg" alt="Autonomy Spectrum" width="100%"/>
</p>

### Five Levels, Proportional Safety

| Level | Name | Orchestration | Safety |
|-------|------|---------------|------------|
| **A0** | Prescribed | Static DAG, fixed agents | Schema validation |
| **A1** | Adaptive | DAG + conditions (`when`) | + state sharing validation |
| **A2** | Delegating | Manager-worker loop, dynamic workers | + **budget (required)** |
| **A3** | Self-Tooling | + dynamic tool creation, skill generation | + **safety envelope (required)** |
| **A4** | Self-Organizing | + recursive delegation, sub-managers | + **full observability (required)** |

### Safety Scales with Autonomy

<p align="center">
  <img src="assets/safety-scaling.svg" alt="Safety Scaling" width="100%"/>
</p>

**Core principle**: More autonomy requires proportionally more safety. An A3 workflow without a safety envelope fails the compliance check. This is by design.

```bash
awp compliance ./workflow/ --level A3   # Checks whether safety envelope is present
```

### Cross-Cutting: Available at Every Level

Memory, Communication, Observability, and Security are **not** tied to autonomy levels:

| Capability | Available | Required |
|------------|-----------|---------|
| Memory (4 tiers) | Every level | Never |
| Message Bus | Every level | Never |
| Observability | Every level | From A4 |
| Security | Every level | From A3 |

---

## 9. The 7-Layer Model

<p align="center">
  <img src="assets/7-layer-model.svg" alt="7-Layer Model" width="100%"/>
</p>

Every AWP workflow is organized into 7 semantic layers:

| Layer | Name | Question | Required |
|-------|------|-------|---------|
| 0 | **Manifest** | What is this workflow? | Always |
| 1 | **Agent Identity** | Who is this agent? | Always |
| 2 | **Capabilities** | What can it do? (Tools, Skills, Code Mode) | Optional |
| 3 | **Communication** | How do agents talk? (Message Bus) | Optional |
| 4 | **Memory & State** | What does the system remember? | Optional |
| 5 | **Orchestration** | In what order? (DAG / Loop) | Multi-Agent |
| 6 | **Observability** | How do I monitor? (Tracing, Audit) | Optional (A4: required) |
| | **Security** | Cross-cutting across all layers | Optional (A3: required) |

**Opt-in principle**: Only layers 0+1 are required. A minimal workflow needs 5 lines of YAML. Complexity is only introduced where it's needed.

For the complete theoretical derivation of all concepts (mental models, emergence theory, cybernetics parallels, analogies) see the [Theory Reference (README_NERD.md)](README_NERD.md).

---

## 10. Repository & Links

### Directory Structure

```
agent-workflow-protocol/
  reference/python/           PyPI package: awp-agents (pip install awp-agents)
    src/awp/                    models/, parser/, validator/, runtime/, data/, cli.py
    tests/                      Unit + E2E tests
    pyproject.toml              Build config
  packages/                   Development split (awp-core + awp-runtime)
    awp-core/                   Protocol layer: models, parser, validator
    awp-runtime/                Execution layer: engines, LLM, tools
  spec/versions/1.0/          Normative specification (RFC 2119)
  schemas/                    JSON Schemas
  docs/                       Complete protocol reference (16 files)
  examples/                   12 workflows (A0-A4) + Jupyter
    01-hello-world/           A0: Minimal workflow
    02-research-pipeline/     A1: 3-agent DAG with state sharing
    03-chat-team/             A1 + Message Bus
    04-memory-workflow/       A1 + 4-tier memory
    05-observable-analytics/  A1 + Tracing & Metrics
    06-enterprise/            A1 + All features
    07-dynamic-tools/         A3: Dynamic Tool Creation
    08-delegation-loop/       A2: Manager-Worker Loop
    09-recursive-delegation/  A4: Recursive Sub-Managers
    10-skill-and-tool-gen/    A3: Skill Generation
    11-tool-creation-loop/    A3: Iterative Tool Creation
    12-full-autonomy-test/    A4: Full A4 Test
    jupyter/                  Programmatic API (Notebook)
  skill/                      AWP Skill for Claude
  conformance/                Conformance tests
  assets/                     SVG diagrams
  README_NERD.md              Theory reference
```

### SVG Diagrams (assets/)

| File | Content |
|-------|--------|
| `quickstart-flow.svg` | 3-step quickstart |
| `data-science-workflow.svg` | Data science integration |
| `enterprise-architecture.svg` | Enterprise architecture |
| `benchmark-framework.svg` | Infrastructure benchmarking |
| `7-layer-model.svg` | 7-layer model |
| `autonomy-spectrum.svg` | A0-A4 spectrum |
| `safety-scaling.svg` | Safety scales with autonomy |
| `delegation-loop.svg` | Delegation loop flow |
| `dag-engine.svg` | DAG engine |
| `recursive-delegation.svg` | Recursive delegation (A4) |
| `validation-pipeline.svg` | Two-tier validation |
| `agent-output-contract.svg` | Output contract |
| `concept-map.svg` | Concept map |
| `impact-levels.svg` | Impact analysis |
| `generation-pipeline.svg` | Workflow generation pipeline |
| `architecture-selection.svg` | LLM architecture selection tree |

### Quick Links

| Resource | When you... |
|-----------|------------|
| [Docs](docs/) | need the complete protocol reference |
| [Workflow Generation](README_GENERATION.md) | want to understand how skills generate workflows |
| [Theory Reference](README_NERD.md) | want to understand the conceptual foundations |
| [Orchestration Engines](docs/ORCHESTRATION_ENGINES.md) | want to compare DAG vs. Delegation Loop |
| [Specification](spec/versions/1.0/spec.md) | want to read the normative specification |
| [Examples](examples/) | want to see runnable workflows |
| [Jupyter Notebook](examples/jupyter/) | want to try the programmatic API |
| [Skill](skill/SKILL.md) | want to generate workflows with Claude |

### License

MIT License. See [LICENSE](LICENSE).
