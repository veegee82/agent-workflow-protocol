# Universal Data Importer

## Mental Model

Every non-trivial workflow starts with the same chore: fetch some data, clean it up, drop it where the agents can see it. The Universal Data Importer kills that chore. Instead of writing twenty lines of `httpx`, `pandas`, and `pathlib` before every run, you declare *what* data the workflow needs — a URL, a SQL query, an S3 object, a glob pattern, an API call — and the runtime resolves, caches, retries, and stages it into the agent workspace for you. The agent layer above never sees the difference between data you handed it inline and data the importer fetched on its behalf.

The importer sits **upstream of** [`prepare_workspace()`](runtime.md), the function that lays out the on-disk inputs for the manager and workers. That ordering is the whole trick: by the time `prepare_workspace()` runs, every `Source` has already been turned into a concrete Python value (DataFrame, dict, bytes, file path), so the rest of the runtime treats imported data and inline data identically. This is what makes workflows portable — the same `workflow.awp.yaml` can run against a live API in production and a fixture file in tests without changing a single agent.

The same `Source` descriptors are also the integration point for [secrets injection](security.md): a `$SECRET_NAME` placeholder inside a header or DSN is resolved at fetch time and never appears in any prompt or log.

## Overview

The Universal Data Importer is a declarative data source layer for `AgentWorkflow` that handles both inline Python objects and remote/offline data sources. Instead of writing boilerplate code to download CSVs, query databases, or call APIs before passing data to your workflow, you declare **what** data you need and the importer fetches, caches, and prepares it automatically.

**Why it exists:**

- Eliminates repetitive data loading code before every workflow run
- Enables reproducible workflows with external data (URLs, databases, S3, APIs)
- Centralizes retry logic, caching, and secret injection
- Keeps workflow definitions declarative and portable

**Backwards compatible:** Raw values in the `inputs` dict work exactly as before. DataFrames, dicts, strings, file paths, and all other previously supported types are unchanged. `Source` objects are an optional addition -- you can mix them freely with raw values.

### Key files

| File | Purpose |
|------|---------|
| `packages/awp-runtime/src/awp/data/sources.py` | `Source` descriptor, `SourceResolver` protocol, resolver registry |
| `packages/awp-runtime/src/awp/data/inputs.py` | Input classification and workspace preparation |
| `packages/awp-runtime/src/awp/data/workflow.py` | `AgentWorkflow` class that orchestrates everything |
| `packages/awp-runtime/src/awp/data/__init__.py` | Public API surface |

---

## Quick Start

### 1. Simple: Load a CSV from a URL

```python
from awp.data import AgentWorkflow
from awp.data.sources import Source

result = AgentWorkflow(
    inputs={
        "sales": Source.url("https://example.com/data/sales_2024.csv"),
    },
    task="Analyze Q4 sales trends and identify top-performing regions",
    model="openrouter/anthropic/claude-sonnet-4",
).run()
```

The runtime fetches the CSV, writes it to the workspace as `inputs/sales.csv`, and passes the file path to the manager agent. No manual `httpx.get()` or `pd.read_csv()` needed.

### 2. Medium: Mix inline data with remote sources

```python
import pandas as pd
from awp.data import AgentWorkflow
from awp.data.sources import Source

# Local DataFrame stays inline (works as before)
config_df = pd.DataFrame({"region": ["US", "EU", "APAC"], "weight": [0.5, 0.3, 0.2]})

result = AgentWorkflow(
    inputs={
        "config": config_df,
        "transactions": Source.sql(
            "SELECT * FROM transactions WHERE date >= '2024-01-01'",
            dsn="postgresql://user:pass@db.example.com/analytics",
        ),
        "exchange_rates": Source.url(
            "https://api.exchangerate.host/latest",
            format="json",
        ),
    },
    task="Weight transactions by region using config and current exchange rates",
    model="openrouter/anthropic/claude-sonnet-4",
).run()
```

### 3. Advanced: API with secrets, S3, and local glob

```python
from awp.data import AgentWorkflow
from awp.data.sources import Source

result = AgentWorkflow(
    inputs={
        "market_data": Source.api(
            "https://api.polygon.io/v2/aggs/ticker/AAPL/range/1/day/2024-01-01/2024-12-31",
            headers={"Authorization": "Bearer $POLYGON_API_KEY"},
            jq=".results",
            format="json",
        ),
        "model_weights": Source.s3(
            "s3://ml-artifacts/models/latest/weights.npy",
            region="us-east-1",
        ),
        "local_reports": Source.glob(
            "*.csv",
            root="/data/weekly_reports/",
            merge="directory",
        ),
    },
    task="Combine market data with model predictions and weekly reports",
    model="openrouter/anthropic/claude-sonnet-4",
    secrets={
        "POLYGON_API_KEY": "your-polygon-api-key",
        "AWS_ACCESS_KEY_ID": "AKIA...",
        "AWS_SECRET_ACCESS_KEY": "...",
    },
).run()
```

Note how `$POLYGON_API_KEY` in the header value is resolved at runtime from the `secrets` dict. The secret value never appears in logs or prompts.

---

## Source Types Reference

### `Source.url()`

Fetches data from an HTTP or HTTPS URL.

```python
Source.url(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    format: str | None = None,
    cache: bool = True,
    retries: int = 2,
    timeout: float = 30.0,
) -> Source
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `url` | `str` | required | Full HTTP/HTTPS URL |
| `headers` | `dict` | `None` | Request headers. Values may contain `$SECRET_NAME` placeholders. |
| `format` | `str` | `None` | Force output format: `"csv"`, `"json"`, `"text"`, `"bytes"`. Auto-detected from URL extension or Content-Type if `None`. |
| `cache` | `bool` | `True` | Cache the response for the duration of this workflow run |
| `retries` | `int` | `2` | Number of retry attempts on transient errors |
| `timeout` | `float` | `30.0` | Request timeout in seconds |

**Example:**

```python
Source.url(
    "https://data.gov/api/v1/dataset.csv",
    headers={"Accept": "text/csv"},
    format="csv",
    timeout=60.0,
)
```

**Dependencies:** None (uses `httpx`, already a runtime dependency).

---

### `Source.sql()`

Executes a SQL query and returns the result set.

```python
Source.sql(
    query: str,
    *,
    dsn: str,
    params: dict[str, Any] | None = None,
    format: str = "dataframe",
    cache: bool = True,
    timeout: float = 30.0,
) -> Source
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `query` | `str` | required | SQL query string |
| `dsn` | `str` | required | Database connection string (SQLAlchemy format). May contain `$SECRET_NAME`. |
| `params` | `dict` | `None` | Bind parameters for parameterized queries |
| `format` | `str` | `"dataframe"` | Output format: `"dataframe"` (CSV in workspace), `"json"`, `"records"` |
| `cache` | `bool` | `True` | Cache the query result for this run |
| `timeout` | `float` | `30.0` | Query timeout in seconds |

**Example:**

```python
Source.sql(
    "SELECT user_id, event, ts FROM events WHERE ts > :cutoff",
    dsn="postgresql://$DB_USER:$DB_PASS@db.internal:5432/analytics",
    params={"cutoff": "2024-06-01"},
)
```

**Dependencies:** `sqlalchemy` (optional). Install with:

```bash
pip install sqlalchemy
# Plus your database driver, e.g.:
pip install psycopg2-binary   # PostgreSQL
pip install pymysql            # MySQL
```

---

### `Source.s3()`

Fetches an object from Amazon S3.

```python
Source.s3(
    uri: str,
    *,
    region: str | None = None,
    format: str | None = None,
    cache: bool = True,
    timeout: float = 30.0,
) -> Source
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `uri` | `str` | required | S3 URI in `s3://bucket/key` format |
| `region` | `str` | `None` | AWS region. Falls back to `AWS_DEFAULT_REGION` env var. |
| `format` | `str` | `None` | Force output format. Auto-detected from key extension if `None`. |
| `cache` | `bool` | `True` | Cache the object for this run |
| `timeout` | `float` | `30.0` | Download timeout in seconds |

**Example:**

```python
Source.s3(
    "s3://my-data-lake/raw/customers/2024/customers.parquet",
    region="eu-west-1",
    format="parquet",
)
```

**Dependencies:** `boto3` (optional). Install with:

```bash
pip install boto3
```

AWS credentials are resolved from the standard chain: environment variables (`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`), `~/.aws/credentials`, IAM role, etc. You can also pass them via `secrets={}`.

---

### `Source.glob()`

Matches files on the local filesystem using a glob pattern.

```python
Source.glob(
    pattern: str,
    *,
    root: str = ".",
    merge: str = "directory",
    format: str | None = None,
) -> Source
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `pattern` | `str` | required | Glob pattern (e.g. `"*.csv"`, `"**/*.json"`) |
| `root` | `str` | `"."` | Root directory to search from |
| `merge` | `str` | `"directory"` | How to present matches: `"directory"` copies all into a workspace folder, `"concat"` merges CSV/JSON files |
| `format` | `str` | `None` | Force output format for matched files |

**Example:**

```python
Source.glob(
    "report_*.csv",
    root="/shared/finance/monthly/",
    merge="directory",
)
```

**Dependencies:** None (uses Python stdlib `pathlib.Path.glob`).

**Notes:** Caching is disabled by default for glob sources (files are local). Retries and timeout are set to 0.

---

### `Source.api()`

Calls a generic REST API endpoint.

```python
Source.api(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    body: Any = None,
    jq: str | None = None,
    format: str = "json",
    cache: bool = True,
    retries: int = 2,
    timeout: float = 30.0,
) -> Source
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `url` | `str` | required | API endpoint URL |
| `method` | `str` | `"GET"` | HTTP method: `"GET"`, `"POST"`, `"PUT"`, `"PATCH"`, `"DELETE"` |
| `headers` | `dict` | `None` | Request headers. Values may contain `$SECRET_NAME` placeholders. |
| `body` | `Any` | `None` | Request body. Dicts are sent as JSON. Strings are sent as-is. |
| `jq` | `str` | `None` | JSONPath-style expression to extract a subset of the response (e.g. `".results"`, `".data[].name"`) |
| `format` | `str` | `"json"` | Output format: `"json"`, `"text"`, `"bytes"` |
| `cache` | `bool` | `True` | Cache the response for this run |
| `retries` | `int` | `2` | Retry count on transient errors |
| `timeout` | `float` | `30.0` | Request timeout in seconds |

**Example:**

```python
Source.api(
    "https://api.github.com/repos/awp-project/awp/issues",
    headers={
        "Authorization": "token $GITHUB_TOKEN",
        "Accept": "application/vnd.github.v3+json",
    },
    jq=".[].title",
    format="json",
)
```

**Dependencies:** None (uses `httpx`).

---

### `Source.base64()`

Wraps inline base64-encoded data as a source.

```python
Source.base64(
    data: str,
    *,
    format: str = "bytes",
) -> Source
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `data` | `str` | required | Base64-encoded string |
| `format` | `str` | `"bytes"` | Output format: `"bytes"`, `"text"`, `"json"` |

**Example:**

```python
import base64

raw = b'{"key": "value"}'
Source.base64(base64.b64encode(raw).decode(), format="json")
```

**Dependencies:** None (uses Python stdlib `base64`).

---

### `Source.clipboard()`

Reads the current system clipboard contents.

```python
Source.clipboard(
    *,
    format: str = "text",
) -> Source
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `format` | `str` | `"text"` | Output format: `"text"`, `"json"`, `"bytes"` |

**Example:**

```python
Source.clipboard(format="text")
```

**Dependencies:** Platform-dependent clipboard access. Works in environments with `xclip` (Linux), `pbpaste` (macOS), or `win32clipboard` (Windows).

**Notes:** Caching is disabled. Timeout is 5 seconds. This is primarily useful in notebook/interactive workflows.

---

## Secret Integration

### The `$SECRET_NAME` Pattern

Any string value inside a `Source`'s `headers`, `dsn`, or other params can contain `$SECRET_NAME` placeholders. At resolve time, the runtime replaces these with actual values from the secrets store.

```python
# The literal string "$POLYGON_API_KEY" is stored in the Source descriptor
Source.api(
    "https://api.polygon.io/v2/aggs/...",
    headers={"Authorization": "Bearer $POLYGON_API_KEY"},
)
```

### How Secrets Flow

1. You pass secrets to `AgentWorkflow(secrets={...})`
2. Secrets are injected into the `ToolRegistry` via `tool_registry.inject_secrets()`
3. When a `Source` is resolved, the resolver receives the secrets dict
4. The resolver substitutes `$SECRET_NAME` patterns with actual values
5. Secret values never appear in logs, prompts, or the input manifest

```python
result = AgentWorkflow(
    inputs={
        "data": Source.api(
            "https://api.example.com/v1/data",
            headers={"X-API-Key": "$MY_API_KEY"},
        ),
    },
    task="Analyze the API data",
    model="openrouter/anthropic/claude-sonnet-4",
    secrets={
        "MY_API_KEY": "sk-live-abc123...",
    },
).run()
```

Secrets can also be loaded from environment variables, `.env` files, or `secrets.yaml` -- the `secrets={}` dict is merged with those sources, with explicit values taking priority.

---

## Caching and Retry

### Caching

Each `Source` has a `cache` flag (default `True` for remote sources). When enabled:

- The runtime computes a hash of the source descriptor (kind + uri + params)
- If a cached result exists for this run, it is reused without re-fetching
- Caching is **per-run** -- it does not persist across workflow invocations
- Local sources (`glob`, `base64`, `clipboard`) have caching disabled by default

To disable caching for a specific source:

```python
Source.url("https://api.example.com/realtime", cache=False)
```

### Retry

Each `Source` has a `retries` field (default `2` for remote sources). On transient errors:

- The runtime uses exponential backoff: 1s, 2s, 4s, ...
- Only transient errors trigger retry: HTTP 429, 500, 502, 503, 504, connection timeouts, DNS resolution failures
- Client errors (4xx except 429) and permanent failures are not retried
- SQL sources have retries disabled by default (`retries=0`) because queries should be idempotent or explicitly retried

To adjust retry behavior:

```python
Source.url("https://flaky-api.example.com/data", retries=5, timeout=60.0)
```

---

## Parallel Resolution

When your `inputs` dict contains multiple `Source` objects, the runtime resolves them concurrently using a `ThreadPoolExecutor`. This is especially useful when you have several independent API calls or database queries.

```python
inputs = {
    "source_a": Source.url("https://api-a.example.com/data"),  # ~2s
    "source_b": Source.url("https://api-b.example.com/data"),  # ~3s
    "source_c": Source.sql("SELECT ...", dsn="postgresql://..."),  # ~1s
    "config": {"threshold": 0.8},  # Inline, no resolution needed
}
# Total time: ~3s (max of individual times), not 6s (sum)
```

The `max_workers` for the thread pool defaults to `min(len(sources), 8)`. Sources that do not need resolution (raw Python values) are passed through directly.

---

## YAML Source Definitions (Experimental)

In addition to the Python API, sources can be defined declaratively in `workflow.awp.yaml`. This is useful for fully YAML-driven workflows that do not use the `AgentWorkflow` Python API.

```yaml
awp: "1.0.0"
name: market-analysis
version: "1.0.0"

inputs:
  market_data:
    source: url
    uri: "https://api.polygon.io/v2/aggs/ticker/AAPL/range/1/day/2024-01-01/2024-12-31"
    headers:
      Authorization: "Bearer $POLYGON_API_KEY"
    format: json
    cache: true
    retries: 2
    timeout: 30

  historical_prices:
    source: sql
    uri: "SELECT * FROM prices WHERE date >= '2024-01-01'"
    dsn: "postgresql://$DB_USER:$DB_PASS@db.internal/finance"
    format: dataframe

  local_config:
    source: glob
    uri: "config_*.yaml"
    root: "./configs/"

agents:
  # ... agent definitions
```

> **Status:** YAML source definitions are experimental and may change. The Python `Source` API is the stable interface.

---

## Custom Resolvers

The resolver system is extensible. You can write custom resolvers for data sources not covered by the built-in types (BigQuery, Snowflake, Kafka, custom internal APIs, etc.).

### Writing a Custom Resolver

A resolver must implement the `SourceResolver` protocol:

```python
from awp.data.sources import Source, SourceResolver, ResolverResult, register_resolver


class BigQueryResolver:
    """Resolver for Google BigQuery sources."""

    def can_handle(self, source: Source) -> bool:
        return source.kind == "bigquery"

    def resolve(self, source: Source, secrets: dict[str, str]) -> ResolverResult:
        from google.cloud import bigquery

        # Substitute secrets in project/dataset params
        project = source.params.get("project", "")
        for key, value in secrets.items():
            project = project.replace(f"${key}", value)

        client = bigquery.Client(project=project)
        query_job = client.query(source.uri)
        df = query_job.to_dataframe()

        return ResolverResult(
            data=df,
            metadata={
                "rows": len(df),
                "bytes_processed": query_job.total_bytes_processed,
            },
        )


# Register at import time
register_resolver(BigQueryResolver())
```

### Using Your Custom Source

Once the resolver is registered, create `Source` objects with your custom kind:

```python
from awp.data.sources import Source

bq_source = Source(
    kind="bigquery",
    uri="SELECT * FROM `project.dataset.table` WHERE date > '2024-01-01'",
    params={"project": "$GCP_PROJECT"},
    cache=True,
    retries=1,
    timeout=120.0,
)

result = AgentWorkflow(
    inputs={"analytics": bq_source},
    task="Summarize the analytics data",
    model="openrouter/anthropic/claude-sonnet-4",
    secrets={"GCP_PROJECT": "my-gcp-project"},
).run()
```

### Registration Order

Resolvers are checked in registration order. The first resolver whose `can_handle()` returns `True` wins. Built-in resolvers are registered at module import time and checked first.

---

## Architecture

### Data Flow

  <img src="diagrams/inline-data-importer.svg" alt="data-importer diagram" width="100%"/>

### Key Classes

| Class | Module | Role |
|-------|--------|------|
| `Source` | `awp.data.sources` | Immutable, frozen dataclass describing a data source. Constructed via factory classmethods. Serializable to/from dict. |
| `SourceResolver` | `awp.data.sources` | Protocol (structural typing). Any class with `can_handle(source) -> bool` and `resolve(source, secrets) -> ResolverResult` qualifies. |
| `ResolverResult` | `awp.data.sources` | Named tuple: `(data: Any, metadata: dict[str, Any])`. The `data` field is the fetched value; `metadata` carries stats like row count or bytes fetched. |
| `InputResolver` | `awp.data.inputs` | Orchestrates parallel resolution of all `Source` objects in the inputs dict, then hands resolved values to `prepare_workspace()`. |
| `AgentWorkflow` | `awp.data.workflow` | Top-level API. Accepts `inputs` with mixed raw values and `Source` objects. Calls `InputResolver` during `run()`. |

### Integration with `prepare_workspace()`

The `prepare_workspace()` function in `awp.data.inputs` already handles all Python types (DataFrame, ndarray, dict, list, str, bytes, etc.). The data importer sits **upstream**: it resolves `Source` objects into concrete Python values, then passes those values to `prepare_workspace()` as if the user had provided them directly.

This means:

- A `Source.url()` that returns CSV data becomes a string or DataFrame before `prepare_workspace()` sees it
- A `Source.sql()` with `format="dataframe"` becomes a `pd.DataFrame`
- A `Source.s3()` for a `.npy` file becomes `bytes` or an `np.ndarray`

The agent workspace and input manifest look identical regardless of whether data came from a `Source` or was passed inline.

---

## API Reference

### `Source` (dataclass)

```python
@dataclass(frozen=True)
class Source:
    kind: str                          # Source type identifier
    uri: str                           # Primary locator (URL, query, pattern, etc.)
    params: dict[str, Any]             # Additional parameters (headers, dsn, etc.)
    cache: bool = True                 # Enable per-run caching
    retries: int = 2                   # Retry count for transient errors
    timeout: float = 30.0              # Timeout in seconds
    format: str | None = None          # Force output format

    # Factory methods
    @classmethod
    def url(cls, url, *, headers, format, cache, retries, timeout) -> Source: ...
    @classmethod
    def sql(cls, query, *, dsn, params, format, cache, timeout) -> Source: ...
    @classmethod
    def s3(cls, uri, *, region, format, cache, timeout) -> Source: ...
    @classmethod
    def glob(cls, pattern, *, root, merge, format) -> Source: ...
    @classmethod
    def api(cls, url, *, method, headers, body, jq, format, cache, retries, timeout) -> Source: ...
    @classmethod
    def base64(cls, data, *, format) -> Source: ...
    @classmethod
    def clipboard(cls, *, format) -> Source: ...

    # Serialization
    def to_dict(self) -> dict[str, Any]: ...
    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Source: ...
```

### `SourceResolver` (protocol)

```python
@runtime_checkable
class SourceResolver(Protocol):
    def can_handle(self, source: Source) -> bool: ...
    def resolve(self, source: Source, secrets: dict[str, str]) -> ResolverResult: ...
```

### `ResolverResult` (named tuple)

```python
class ResolverResult(NamedTuple):
    data: Any                          # The fetched/resolved data
    metadata: dict[str, Any]           # Resolver metadata (rows, bytes, timing, etc.)
```

### `register_resolver()`

```python
def register_resolver(resolver: SourceResolver) -> None:
    """Add a resolver to the global registry.

    Resolvers are checked in registration order. The first resolver
    whose can_handle() returns True for a given Source is used.
    """
```

### `get_resolver()`

```python
def get_resolver(source: Source) -> SourceResolver:
    """Return the first registered resolver that can handle the source.

    Raises ValueError if no resolver matches.
    """
```

---

## Dependencies

### Core (no new dependencies)

The `Source` dataclass and resolver protocol require no additional packages. `httpx` is already a runtime dependency of `awp-runtime`.

### Optional Dependencies

| Source kind | Package | Install command |
|-------------|---------|-----------------|
| `sql` | `sqlalchemy` + DB driver | `pip install sqlalchemy psycopg2-binary` |
| `s3` | `boto3` | `pip install boto3` |
| `clipboard` | Platform tools | `apt install xclip` (Linux) or built-in (macOS/Windows) |

### Install Everything

```bash
# Core runtime (includes httpx)
pip install -e "packages/awp-runtime/[data]"

# Optional: SQL support
pip install sqlalchemy psycopg2-binary

# Optional: S3 support
pip install boto3
```

---

## Error Handling

When a source fails to resolve:

- **Retryable errors** (HTTP 429/5xx, timeouts, DNS failures): retried up to `retries` times with exponential backoff
- **Non-retryable errors** (HTTP 4xx, invalid SQL, missing bucket): raised immediately as `ValueError` or the underlying library exception
- **Missing resolver**: `ValueError` with message indicating the unhandled source kind
- **Missing secrets**: `KeyError` with the unresolved `$SECRET_NAME` placeholder

All errors include the source `kind` and `uri` in the error message for debugging.
