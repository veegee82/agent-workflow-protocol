# AWP Example Workflows

Complete example workflows covering all AWP autonomy levels and cross-cutting features.

## Examples

| Example | Level | Features Demonstrated |
|---------|-------|----------------------|
| [01-hello-world](workflows/01-hello-world/) | A0 Prescribed | Single agent, static DAG, output contract |
| [02-research-pipeline](workflows/02-research-pipeline/) | A1 Adaptive | Multi-agent DAG, state sharing, web search tools |
| [03-chat-team](workflows/03-chat-team/) | A1 Adaptive + Communication | Multi-agent DAG, message bus, agent communication, channels |
| [04-memory-workflow](workflows/04-memory-workflow/) | A1 Adaptive + Memory | Multi-agent DAG, long-term memory, daily logs, memory tools |
| [05-observable-analytics](workflows/05-observable-analytics/) | A1 Adaptive + Observability | Multi-agent DAG, tracing, metrics, audit trail, code execution |
| [06-enterprise](workflows/06-enterprise/) | A1 Adaptive + All Features | All cross-cutting features: security, communication, memory, observability, skills, MCPs, code mode, conditional execution |

## Feature Coverage Matrix

| Feature | A0 | A1 | A1+Comm | A1+Mem | A1+Obs | A1+All |
|---------|----|----|---------|--------|--------|--------|
| Agent DAG | x | x | x | x | x | x |
| State Sharing | | x | x | x | x | x |
| Tool Calling (MCP) | | x | x | x | x | x |
| Message Bus | | | x | | | x |
| Agent Communication | | | x | | | x |
| Long-term Memory | | | | x | x | x |
| Daily Logs | | | | x | x | x |
| Memory Tools | | | | x | x | x |
| Observability/Tracing | | | | | x | x |
| Metrics Collection | | | | | x | x |
| Audit Trail | | | | | x | x |
| Code Execution | | | | | x | x |
| Security/ACL | | | | | | x |
| Circuit Breaker | | | | | | x |
| Rate Limiting | | | | | | x |
| Custom MCP Tools | | | | | | x |
| Skills Injection | | | | | | x |
| Conditional Execution | | | | | | x |
| Code Mode | | | | | | x |

## Running Examples

```bash
# Set your LLM API key
export LLM_API_KEY="your-openrouter-key"
export LLM_MODEL="anthropic/claude-sonnet-4"

# Run a specific example
cd reference/python
python -m awp run ../../examples/workflows/01-hello-world --task "Greet Alice"

# Run E2E tests (requires LLM_API_KEY)
pytest tests/test_examples_e2e.py -v --tb=short

# Run validation-only tests (no LLM needed)
pytest tests/test_e2e.py -v
```

## Autonomy Levels

- **A0 Prescribed**: Static DAG, predefined agents, fixed tools
- **A1 Adaptive**: Conditional execution, loops, fan-out, multi-agent DAG with state sharing
- **A2 Delegating**: Manager spawns workers dynamically (delegation loop)
- **A3 Self-Tooling**: Agents create tools and skills at runtime
- **A4 Self-Organizing**: Recursive delegation, budget distribution

**Cross-cutting features** (available at any level): Communication (message bus), Memory, Observability, Security.

**Safety scales with autonomy**: A2+ requires budget controls, A3+ requires safety envelope, A4+ requires observability.

## Data Sources (Universal Data Importer)

The `AgentWorkflow` API supports declarative data sources via `Source` objects. Instead of writing boilerplate data-loading code before each workflow, you declare what data you need and the runtime handles fetching, caching, retries, and secret injection.

`Source` objects mix freely with regular Python values in the `inputs` dict. Existing workflows are fully backwards compatible.

### Basic Usage

```python
from awp.data import AgentWorkflow
from awp.data.sources import Source

result = AgentWorkflow(
    inputs={
        "sales_data": Source.url("https://example.com/data/sales.csv"),
        "config": {"threshold": 0.8, "top_n": 10},  # inline dict (as before)
    },
    task="Identify top-performing products from the sales data",
    model="openrouter/anthropic/claude-sonnet-4",
).run()
```

### Available Source Types

| Factory Method | Description | Example |
|----------------|-------------|---------|
| `Source.url()` | HTTP/HTTPS download | `Source.url("https://example.com/data.csv")` |
| `Source.sql()` | SQL query | `Source.sql("SELECT * FROM t", dsn="postgresql://...")` |
| `Source.s3()` | S3 object | `Source.s3("s3://bucket/key.parquet")` |
| `Source.glob()` | Local file glob | `Source.glob("*.csv", root="/data/reports/")` |
| `Source.api()` | REST API call | `Source.api("https://api.example.com/v1/data")` |
| `Source.base64()` | Inline base64 data | `Source.base64(encoded_string)` |
| `Source.clipboard()` | System clipboard | `Source.clipboard()` |

### Secrets in Sources

API keys and credentials use `$SECRET_NAME` placeholders that are resolved at runtime:

```python
result = AgentWorkflow(
    inputs={
        "market_data": Source.api(
            "https://api.polygon.io/v2/aggs/ticker/AAPL/range/1/day/2024-01-01/2024-12-31",
            headers={"Authorization": "Bearer $POLYGON_API_KEY"},
            jq=".results",
        ),
    },
    task="Analyze AAPL price trends",
    model="openrouter/anthropic/claude-sonnet-4",
    secrets={"POLYGON_API_KEY": "your-key-here"},
).run()
```

### Multiple Sources (Parallel Resolution)

When multiple `Source` objects are present, they are resolved concurrently:

```python
result = AgentWorkflow(
    inputs={
        "users": Source.sql("SELECT * FROM users", dsn="postgresql://..."),
        "events": Source.url("https://analytics.example.com/events.csv"),
        "reports": Source.glob("*.csv", root="/data/weekly/"),
    },
    task="Cross-reference users with events and weekly reports",
    model="openrouter/anthropic/claude-sonnet-4",
).run()
# All three sources are fetched in parallel via ThreadPoolExecutor
```

For full documentation, see [docs/data-importer.md](../docs/data-importer.md).
