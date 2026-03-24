# Layer 2: Capabilities

**AWP Specification v1.0.0 — Layer 2**
**Status:** Draft Standard

---

## 1. Overview

Layer 2 defines the capabilities available to an agent: tools, skills, data sources, and sandboxed execution. Capabilities are declared in the `capabilities` section of `agent.awp.yaml`. The capabilities layer builds on Layer 1 (Agent Identity) and provides the action interface through which agents interact with external systems.

---

## 2. Tools

The `capabilities.tools` section configures MCP tool access for the agent.

### 2.1 Fields

| Field | Type | Status | Default | Description |
|-------|------|--------|---------|-------------|
| `enabled` | boolean | REQUIRED | — | Whether the agent MAY invoke tools. If `false`, the runtime MUST NOT present tool definitions to the LLM. |
| `max_calls` | integer | OPTIONAL | `0` (unlimited) | Maximum total tool calls per agent execution. `0` means unlimited. |
| `max_parallel` | integer | OPTIONAL | `1` | Maximum concurrent tool calls. MUST be >= 1. |
| `timeout_per_call` | integer | OPTIONAL | `30` | Timeout in seconds per tool invocation. |
| `allowed` | list of strings | OPTIONAL | `[]` | Tool names or glob patterns the agent MAY invoke. Empty list with `enabled: true` means all non-denied tools are allowed. |
| `denied` | list of strings | OPTIONAL | `[]` | Tool names or glob patterns the agent MUST NOT invoke. Denied takes precedence over allowed. |
| `overrides` | object | OPTIONAL | — | Per-tool configuration overrides. Keys are tool FQNs, values are objects with `timeout`, `max_calls`, or `rate_limit`. |

### 2.2 Tool Resolution Rules

1. If `enabled` is `false`, no tools are available. The runtime MUST NOT include tool definitions in the LLM request.
2. If `allowed` is non-empty, only tools matching at least one allowed pattern are candidates.
3. If `allowed` is empty and `enabled` is `true`, all registered tools are candidates.
4. From the candidate set, any tool matching a `denied` pattern MUST be removed.
5. Per-tool `overrides` apply to the final resolved set.

### 2.3 Glob Pattern Matching

Tool name patterns MUST support the following glob syntax:

- `*` matches any sequence of characters within a namespace segment.
- `web.*` matches `web.search`, `web.fetch`, etc.
- `*.*` matches all tools.
- Exact names (e.g., `file.read`) match only that tool.

---

## 3. AWP Tool Specification

Each MCP tool in AWP is identified by a Fully Qualified Name (FQN) in the format `namespace.action`.

### 3.1 Tool Definition

A tool definition MUST include:

| Field | Type | Status | Description |
|-------|------|--------|-------------|
| `name` | string | REQUIRED | FQN in `namespace.action` format. |
| `version` | string | REQUIRED | SemVer version of the tool. |
| `description` | string | REQUIRED | Human-readable description of what the tool does. |
| `parameters` | object | REQUIRED | JSON Schema describing the tool's input parameters. |
| `returns` | object | REQUIRED | JSON Schema describing the tool's return value. |
| `meta` | object | OPTIONAL | Metadata about tool behavior. |

### 3.2 Standard Return Format

All AWP tools MUST return a response conforming to the following structure:

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
| `log` | string | OPTIONAL diagnostic message for logging. MUST NOT contain sensitive data. |

### 3.3 Tool Metadata

The `meta` field provides behavioral annotations:

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `side_effects` | boolean | `true` | Whether the tool modifies external state. |
| `idempotent` | boolean | `false` | Whether repeated calls with the same input produce the same result. |
| `deterministic` | boolean | `false` | Whether the output is fully determined by the input. |
| `rate_limit` | object | — | Rate limit configuration: `max_per_minute`, `max_per_hour`. |
| `cost` | string | — | Cost tier: `"free"`, `"low"`, `"medium"`, `"high"`. |
| `latency` | string | — | Expected latency: `"instant"`, `"fast"`, `"medium"`, `"slow"`. |

---

## 4. Custom MCP Tools

Workflows MAY define custom tools in the `mcp/` directory at the workflow root.

### 4.1 Configuration

Custom tools are configured in the `capabilities.custom_tools` section of `workflow.awp.yaml`:

| Field | Type | Status | Default | Description |
|-------|------|--------|---------|-------------|
| `source_dir` | string | OPTIONAL | `"mcp"` | Directory containing custom tool modules relative to workflow root. |
| `declarations` | list | OPTIONAL | `[]` | Explicit tool declarations. Each entry MUST have `module` and `tools` (list of FQNs). |
| `auto_discovery` | boolean | OPTIONAL | `true` | If `true`, the runtime MUST scan `source_dir` for `@app.tool()` decorated functions. |
| `auto_inject` | boolean | OPTIONAL | `true` | If `true`, discovered tools are automatically added to every agent's allowed tools. |

### 4.2 Reserved Namespaces

The following namespaces are reserved for AWP built-in tools. Custom tools MUST NOT use these namespaces:

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

### 4.3 Custom Tool Rules (CT1–CT9)

- **CT1:** Custom tool FQNs MUST use the `namespace.action` format.
- **CT2:** Custom tool namespaces MUST NOT collide with reserved namespaces.
- **CT3:** Custom tools MUST return the standard AWP tool response format (Section 3.2).
- **CT4:** Custom tool modules MUST be valid Python modules (for the Python reference implementation) or equivalent in other runtimes.
- **CT5:** Custom tools MUST declare their parameters using JSON Schema-compatible type annotations.
- **CT6:** Custom tools MUST NOT modify the agent's state directly; they MUST return data that the agent processes.
- **CT7:** Custom tools with `meta.side_effects: true` MUST be idempotent or clearly document non-idempotent behavior.
- **CT8:** Custom tool names MUST be unique within a workflow. Duplicate names MUST cause a validation error.
- **CT9:** Custom tools MUST be unregistered when the workflow is unloaded to prevent namespace pollution.

---

## 5. Skills

Skills are knowledge files (Markdown or `.skill` format) that are injected into an agent's system prompt to provide domain expertise, constraints, or instructions.

### 5.1 Skill Loading Order

Skills are loaded and merged in the following order. Later entries take precedence in case of conflicts:

1. **Foundation skills** (`skills_basis/`) — ALWAYS loaded for every agent. These provide baseline knowledge.
2. **Shared skills** (`{workflow}/skills/`) — Loaded for ALL agents in the workflow. Project-level domain knowledge.
3. **Agent-specific skills** (`{workflow}/agents/{agent_id}/workflow/skills/`) — Loaded only for the specific agent.
4. **External skills** (referenced via `capabilities.skills.external`) — Loaded from global `skills/` directory.

### 5.2 Configuration

| Field | Type | Status | Description |
|-------|------|--------|-------------|
| `capabilities.skills.foundation` | boolean | OPTIONAL | Whether to load foundation skills. Default: `true`. |
| `capabilities.skills.shared` | boolean | OPTIONAL | Whether to load project-level shared skills. Default: `true`. |
| `capabilities.skills.agent_specific` | list | OPTIONAL | List of agent-specific skill files or directories. |
| `capabilities.skills.external` | list | OPTIONAL | List of external skill references with `name` and `version`. |
| `capabilities.skills.load_order` | list | OPTIONAL | Override the default skill loading order. |

### 5.3 Deduplication

When the same skill is present at multiple levels (e.g., foundation and shared), the runtime MUST deduplicate by skill name and use the highest-priority version (agent-specific > shared > foundation > external).

---

## 6. Data Sources

The `capabilities.data_sources` section declares external data sources the agent MAY access.

### 6.1 Data Source Types

| Type | Fields | Description |
|------|--------|-------------|
| `http` | `url`, `method`, `headers`, `auth` | HTTP API endpoint. |
| `filesystem` | `path`, `format`, `watch` | Local file or directory. |
| `database` | `connection_string`, `query`, `driver` | Database connection. `connection_string` MUST NOT appear in logs. |
| `rag` | `index_path`, `embedding_model`, `top_k`, `similarity_threshold` | Vector search / RAG index. |

### 6.2 Common Fields

All data source types share these fields:

| Field | Type | Status | Description |
|-------|------|--------|-------------|
| `name` | string | REQUIRED | Unique identifier for the data source. |
| `type` | string | REQUIRED | One of: `"http"`, `"filesystem"`, `"database"`, `"rag"`. |
| `auth` | object | OPTIONAL | Authentication configuration. MUST be marked sensitive. |
| `rate_limit` | object | OPTIONAL | Rate limiting: `max_per_minute`, `max_per_hour`. |
| `retry` | object | OPTIONAL | Retry configuration: `max_attempts`, `backoff` (linear/exponential), `retryable_errors`. |

---

## 7. Sandbox

The `capabilities.sandbox` section configures sandboxed code execution.

| Field | Type | Status | Default | Description |
|-------|------|--------|---------|-------------|
| `type` | string | OPTIONAL | `"subprocess"` | Sandbox type: `"subprocess"`, `"docker"`, `"wasm"`, `"isolate"`, `"none"`. |
| `constraints` | object | OPTIONAL | — | Resource constraints. |
| `constraints.max_memory_mb` | integer | OPTIONAL | `256` | Maximum memory in megabytes. |
| `constraints.max_cpu_seconds` | integer | OPTIONAL | `30` | Maximum CPU time in seconds. |
| `constraints.max_output_bytes` | integer | OPTIONAL | `1048576` | Maximum output size (1 MB default). |
| `filesystem` | object | OPTIONAL | — | Filesystem access rules. |
| `filesystem.read` | list | OPTIONAL | `[]` | Paths the sandbox MAY read. |
| `filesystem.write` | list | OPTIONAL | `[]` | Paths the sandbox MAY write. |
| `filesystem.deny` | list | OPTIONAL | `[]` | Paths the sandbox MUST NOT access. |
| `commands` | object | OPTIONAL | — | Command execution rules. |
| `commands.allowed` | list | OPTIONAL | `[]` | Shell commands the sandbox MAY execute. |
| `commands.denied` | list | OPTIONAL | `[]` | Shell commands the sandbox MUST NOT execute. |

### 7.1 Sandbox Types

| Type | Startup | Isolation | Network | Use Case |
|------|---------|-----------|---------|----------|
| `subprocess` | ~100ms | Process-level | Host | Python, local development |
| `docker` | ~1-5s | Container | Configurable | Full-stack, heavy workloads |
| `wasm` | ~10ms | WASM sandbox | None | Lightweight, browser |
| `isolate` | ~5ms | V8 Isolate | Configurable | Edge, Cloudflare Workers, Code Mode |
| `none` | 0ms | None | Host | Trusted code only |

### 7.2 Network Isolation

When `type` is `"isolate"`, the `network` field MUST be present:

| Field | Type | Status | Default | Description |
|-------|------|--------|---------|-------------|
| `network.enabled` | boolean | REQUIRED (for `isolate`) | `false` | Whether the sandbox has network access. |
| `network.allowed_hosts` | list | OPTIONAL | `[]` | Host whitelist when `enabled` is `true`. Empty means all hosts allowed. |
| `network.intercept` | boolean | OPTIONAL | `false` | Whether to intercept and log outbound requests. |

---

## 8. Code Mode

Code Mode is an alternative tool execution strategy where the agent writes code
against a typed SDK instead of calling tools individually. This reduces token
usage and LLM roundtrips, especially for agents with large tool surfaces.

Code Mode is OPTIONAL at all compliance levels. Runtimes that do not support
Code Mode MUST fall back to classic tool execution.

### 8.1 Overview

In **classic mode**, an agent calls tools one at a time:

```
Agent → LLM → tool_call("web.search") → result → LLM → tool_call("file.write") → result → LLM
```

In **Code Mode**, the agent writes a code block that chains multiple operations:

```
Agent → LLM → generates code → sandbox executes code → result → LLM
```

The SDK wraps each allowed MCP tool as a typed method. The runtime auto-generates
the SDK interface from `capabilities.tools.allowed`.

### 8.2 Configuration

The `capabilities.codemode` section configures Code Mode:

| Field | Type | Status | Default | Description |
|-------|------|--------|---------|-------------|
| `enabled` | boolean | REQUIRED | `false` | Whether Code Mode is active for this agent. |
| `language` | string | REQUIRED (if enabled) | — | Target language: `"typescript"`, `"python"`, or `"javascript"`. |
| `sdk_surface.mode` | string | OPTIONAL | `"auto"` | `"auto"` maps all allowed tools; `"explicit"` maps only listed tools. |
| `sdk_surface.include` | list | OPTIONAL | `[]` | Tool FQNs to include (only with `mode: "explicit"`). |
| `sdk_surface.exclude` | list | OPTIONAL | `[]` | Tool FQNs to exclude from the SDK. |
| `execution.sandbox_ref` | string | OPTIONAL | `"capabilities.sandbox"` | Reference to the sandbox configuration. |
| `execution.timeout` | integer | OPTIONAL | `30` | Code execution timeout in seconds. |
| `execution.max_retries` | integer | OPTIONAL | `1` | Number of retries on execution failure. |
| `execution.capture_console` | boolean | OPTIONAL | `true` | Whether to capture stdout/stderr. |
| `state.enabled` | boolean | OPTIONAL | `false` | Whether the code has access to persistent state. |
| `state.backend` | string | OPTIONAL | `"memory"` | State backend: `"memory"`, `"filesystem"`, or `"workspace"`. |

### 8.3 SDK Generation

The runtime MUST auto-generate a typed SDK interface from the agent's
`capabilities.tools.allowed` list. Each allowed tool becomes an SDK method,
grouped by namespace:

- Tool `web.search` → `sdk.web.search(query, maxResults)`
- Tool `file.read` → `sdk.file.read(path)`
- Tool `memory.write` → `sdk.memory.write(key, value)`

The SDK interface is injected into the agent's system prompt as type
definitions, replacing the individual tool definitions used in classic mode.

### 8.4 Execution Flow

1. Runtime builds system prompt with SDK type definitions (instead of tool defs).
2. LLM generates a code block using the SDK.
3. Runtime extracts the code block from the LLM response.
4. Runtime executes the code in the configured sandbox (`capabilities.sandbox`).
5. SDK method calls are intercepted and routed to the MCP tool registry.
6. The code's return value is validated against `output_schema.json`.
7. If execution fails and `max_retries > 0`, the error is fed back to the LLM.

### 8.5 Output Contract

Code Mode does NOT change the output contract. The code MUST return a JSON
object matching `output_schema.json`, including the `confidence` field.
This ensures that Code Mode agents are interchangeable with classic agents
in the DAG.

### 8.6 Runtime Implementations

Code Mode is runtime-agnostic. Each runtime implements it using its sandbox:

| Runtime | Sandbox Type | SDK Transport |
|---------|-------------|---------------|
| Python (standalone) | `subprocess` | In-process function calls |
| Cloudflare Workers | `isolate` | RPC stubs via Worker Loader |
| Docker | `docker` | HTTP API on localhost |

### 8.7 Example

```yaml
capabilities:
  tools:
    enabled: true
    allowed: ["web.*", "file.*"]

  sandbox:
    type: isolate
    constraints:
      max_memory_mb: 128
      max_cpu_seconds: 30
    network:
      enabled: false

  codemode:
    enabled: true
    language: typescript
    sdk_surface:
      mode: auto
    execution:
      timeout: 30
      capture_console: true
```

---

## 9. Complete Example

```yaml
awp_agent: "1.0.0"

identity:
  id: research_analyst
  role: researcher
  description: "Performs web research and produces structured summaries."

model:
  name: "anthropic/claude-sonnet-4"
  parameters:
    temperature: 0.0

prompt:
  system: "workflow/instructions/SYSTEM_PROMPT.md"

output:
  format: json
  contract: "workflow/output_schema/output_schema.json"

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

  skills:
    foundation: true
    shared: true
    agent_specific:
      - "workflow/skills/research_methodology.md"
    external:
      - name: academic-search
        version: ">=1.0.0"

  data_sources:
    - name: knowledge_base
      type: rag
      index_path: "data/embeddings/"
      embedding_model: "text-embedding-3-small"
      top_k: 10
      similarity_threshold: 0.7

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
