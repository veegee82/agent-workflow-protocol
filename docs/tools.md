# Tools & Capabilities Reference

Layer 2 defines the capabilities available to an agent: tools, skills, data sources, and sandboxed execution. Capabilities are declared in the `capabilities` section of [agent.awp.yaml](agent.md) and in the `capabilities.custom_tools` section of [workflow.awp.yaml](manifest.md).

## Tool Naming Convention

Every MCP tool in AWP is identified by a Fully Qualified Name (FQN) in the format `namespace.action`.

Examples: `web.search`, `file.read`, `memory.write`, `myns.custom_action`.

## Standard Tool Result Format

All AWP tools must return a response conforming to this structure:

```json
{
  "ok": true,
  "status": 200,
  "data": {},
  "error": null,
  "log": ""
}
```

| Field | Type | Description |
|-------|------|-------------|
| `ok` | boolean | `true` if the tool call succeeded, `false` otherwise. |
| `status` | integer | HTTP-style status code (200 for success, 4xx/5xx for errors). |
| `data` | object | The tool's result payload. Structure is tool-specific. |
| `error` | string or null | Error message if `ok` is `false`, `null` otherwise. |
| `log` | string | Optional diagnostic message. Must not contain sensitive data. |

## Built-In Tools

| Tool | Description |
|------|-------------|
| `web.search` | Search the web for information. |
| `http.request` | Make arbitrary HTTP requests (GET, POST, etc.). |
| `file.read` | Read file contents from disk. |
| `file.write` | Write content to a file. |
| `file.list` | List files in a directory. |
| `shell.execute` | Execute a shell command in a sandbox. |
| `agent.send_message` | Send a message to another agent via the message bus. |
| `agent.list_messages` | List messages received from other agents. |
| `memory.write` | Write to daily log or MEMORY.md. |
| `memory.search` | Keyword or semantic search across memory files. |
| `memory.read` | Read MEMORY.md, daily log, or list available dates. |
| `memory.curate` | LLM-based curation: daily logs to MEMORY.md. |
| `arithmetic.add` | Add two numbers. |
| `arithmetic.subtract` | Subtract two numbers. |
| `arithmetic.multiply` | Multiply two numbers. |
| `arithmetic.divide` | Divide two numbers. |

## Tool Configuration in agent.awp.yaml

The `capabilities.tools` section controls which tools an agent may use.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enabled` | boolean | -- | Whether the agent may invoke tools. If `false`, no tool definitions are presented to the LLM. |
| `max_calls` | integer | `0` (unlimited) | Maximum total tool calls per agent execution. |
| `max_parallel` | integer | `1` | Maximum concurrent tool calls. |
| `timeout_per_call` | integer | `30` | Timeout in seconds per tool invocation. |
| `allowed` | list of strings | `[]` | Tool names or glob patterns the agent may invoke. Empty with `enabled: true` means all non-denied tools. |
| `denied` | list of strings | `[]` | Tool names or glob patterns the agent must not invoke. Denied takes precedence over allowed. |
| `overrides` | object | -- | Per-tool configuration. Keys are tool FQNs, values are objects with `timeout`, `max_calls`, or `rate_limit`. |

### Tool Resolution Rules

1. If `enabled` is `false`, no tools are available.
2. If `allowed` is non-empty, only matching tools are candidates.
3. If `allowed` is empty and `enabled` is `true`, all registered tools are candidates.
4. From the candidate set, any tool matching a `denied` pattern is removed.
5. Per-tool `overrides` apply to the final resolved set.

### Glob Pattern Matching

- `*` matches any characters within a namespace segment.
- `web.*` matches `web.search`, `web.fetch`, etc.
- `*.*` matches all tools.
- Exact names (e.g., `file.read`) match only that tool.

### Example

```yaml
capabilities:
  tools:
    enabled: true
    max_calls: 20
    max_parallel: 3
    timeout_per_call: 30
    allowed:
      - "web.*"
      - "file.read"
      - "memory.*"
    denied:
      - "shell.*"
    overrides:
      web.search:
        timeout: 60
        rate_limit:
          max_per_minute: 10
```

## Custom MCP Tools

Workflows may define custom tools in the `mcp/` directory at the workflow root.

### Configuration in workflow.awp.yaml

```yaml
capabilities:
  custom_tools:
    source_dir: "mcp"
    auto_discovery: true
    auto_inject: true
    declarations:
      - module: custom_tools
        tools:
          - "myns.action_a"
          - "myns.action_b"
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `source_dir` | string | `"mcp"` | Directory containing custom tool modules relative to workflow root. |
| `declarations` | list | `[]` | Explicit tool declarations. Each entry has `module` and `tools` (list of FQNs). |
| `auto_discovery` | boolean | `true` | If `true`, the runtime scans `source_dir` for `@app.tool()` decorated functions. |
| `auto_inject` | boolean | `true` | If `true`, discovered tools are automatically added to every agent's allowed tools. |

### Custom Tool Rules (CT1-CT9)

- **CT1:** Custom tool FQNs must use the `namespace.action` format.
- **CT2:** Custom tool namespaces must not collide with reserved namespaces.
- **CT3:** Custom tools must return the standard AWP tool response format.
- **CT4:** Custom tool modules must be valid Python modules (for the Python reference implementation) or equivalent in other runtimes.
- **CT5:** Custom tools must declare their parameters using JSON Schema-compatible type annotations.
- **CT6:** Custom tools must not modify the agent's state directly; they must return data for the agent to process.
- **CT7:** Custom tools with side effects must be idempotent or clearly document non-idempotent behavior.
- **CT8:** Custom tool names must be unique within a workflow. Duplicates must cause a validation error.
- **CT9:** Custom tools must be unregistered when the workflow is unloaded.

### Reserved Namespaces

Custom tools must not use these namespaces:

| Namespace | Purpose |
|-----------|---------|
| `web` | Web search and browsing |
| `http` | HTTP requests |
| `file` | File system operations |
| `shell` | Shell command execution |
| `agent` | Agent-to-agent messaging |
| `memory` | Memory operations |
| `arithmetic` | Mathematical operations |
| `numpy` | NumPy operations |
| `matplot` | Matplotlib operations |
| `pandas` | Pandas operations |
| `doc` | Document operations |
| `sklearn` | Scikit-learn operations |

### FastMCP Stub Pattern

Custom tools for the Python reference implementation use the FastMCP decorator pattern:

```python
from mcp.server.fastmcp import FastMCP

app = FastMCP("my_tools")


@app.tool("myns.fetch_data")
def fetch_data(url: str, timeout: int = 30) -> dict:
    """Fetch data from an external API.

    Args:
        url: The URL to fetch data from.
        timeout: Request timeout in seconds.

    Returns:
        Standard AWP tool response.
    """
    try:
        # ... implementation ...
        return {"ok": True, "status": 200, "data": {"result": "..."}, "error": None, "log": ""}
    except Exception as e:
        return {"ok": False, "status": 500, "data": {}, "error": str(e), "log": ""}
```

## Skills

Skills are knowledge files (Markdown or `.skill` format) injected into an agent's system prompt to provide domain expertise, constraints, or instructions.

### Skill Loading Order

Skills are loaded and merged in this order (later entries take precedence):

1. **Foundation skills** (`skills_basis/`) -- Always loaded for every agent.
2. **Shared skills** (`{workflow}/skills/`) -- Loaded for all agents in the workflow.
3. **Agent-specific skills** (`{workflow}/agents/{agent_id}/workflow/skills/`) -- Loaded only for the specific agent.
4. **External skills** (referenced via `capabilities.skills.external`) -- Loaded from the global skills directory.

### Skills Configuration

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `capabilities.skills.foundation` | boolean | `true` | Whether to load foundation skills. |
| `capabilities.skills.shared` | boolean | `true` | Whether to load project-level shared skills. |
| `capabilities.skills.agent_specific` | list | -- | List of agent-specific skill files or directories. |
| `capabilities.skills.external` | list | -- | List of external skill references with `name` and `version`. |
| `capabilities.skills.load_order` | list | -- | Override the default skill loading order. |

### Deduplication

When the same skill appears at multiple levels, the runtime deduplicates by skill name and uses the highest-priority version (agent-specific > shared > foundation > external).

## Data Sources

The `capabilities.data_sources` section declares external data sources.

| Type | Fields | Description |
|------|--------|-------------|
| `http` | `url`, `method`, `headers`, `auth` | HTTP API endpoint. |
| `filesystem` | `path`, `format`, `watch` | Local file or directory. |
| `database` | `connection_string`, `query`, `driver` | Database connection. `connection_string` must not appear in logs. |
| `rag` | `index_path`, `embedding_model`, `top_k`, `similarity_threshold` | Vector search / RAG index. |

Common fields for all data sources:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | Yes | Unique identifier. |
| `type` | string | Yes | `"http"`, `"filesystem"`, `"database"`, or `"rag"`. |
| `auth` | object | No | Authentication configuration. Must be marked sensitive. |
| `rate_limit` | object | No | Rate limiting: `max_per_minute`, `max_per_hour`. |
| `retry` | object | No | Retry configuration: `max_attempts`, `backoff`, `retryable_errors`. |

## Sandbox

The `capabilities.sandbox` section configures sandboxed code execution.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `type` | string | `"subprocess"` | Sandbox type: `"subprocess"`, `"docker"`, `"wasm"`, or `"none"`. |
| `constraints.max_memory_mb` | integer | `256` | Maximum memory in megabytes. |
| `constraints.max_cpu_seconds` | integer | `30` | Maximum CPU time in seconds. |
| `constraints.max_output_bytes` | integer | `1048576` | Maximum output size (1 MB default). |
| `filesystem.read` | list | `[]` | Paths the sandbox may read. |
| `filesystem.write` | list | `[]` | Paths the sandbox may write. |
| `filesystem.deny` | list | `[]` | Paths the sandbox must not access. |
| `commands.allowed` | list | `[]` | Shell commands the sandbox may execute. |
| `commands.denied` | list | `[]` | Shell commands the sandbox must not execute. |

### Example

```yaml
capabilities:
  sandbox:
    type: subprocess
    constraints:
      max_memory_mb: 256
      max_cpu_seconds: 30
    filesystem:
      read:
        - "data/"
      write:
        - "data/output/"
      deny:
        - ".env"
        - "**/*.key"
    commands:
      allowed:
        - "python"
        - "pip"
      denied:
        - "rm"
        - "sudo"
```
