# Tools & Capabilities Reference

## Mental Model

**Layer 2** of AWP — *Capabilities* — defines everything an agent can *do* beyond reasoning over text: which tools it may invoke, which skills are injected into its prompt, which data sources it may read, and which sandbox it may execute code in. Capabilities are the bridge between an LLM's pure-text world and the messy real world of APIs, files, and computation.

AWP treats tools as a **first-class, namespaced registry** rather than ad-hoc function calls. Every tool has a Fully Qualified Name (`namespace.action`), a strict response shape (`{ok, status, data, error, log}`), and an explicit security envelope. This uniformity is what makes tool calls auditable, replayable, and safe to expose to autonomous managers.

Three execution modes coexist for tools, in increasing autonomy:

1. **Classic tool calls** — the LLM invokes one tool at a time, the runtime executes it, returns the result, and the LLM continues. Simple and traceable; high token cost when many tools are involved.
2. **Code mode** (default: enabled) — instead of N round-trips, the LLM writes a single code block against a *typed SDK* that wraps all allowed tools as methods. The code runs in the sandbox; one round-trip replaces many. The output contract (R17 confidence) is unchanged. This is the dominant execution mode for delegation-loop workers.
3. **Runtime tool generation** (default: enabled) — when the existing tool set is insufficient for a task, a worker can author a new MCP tool on the fly. The runtime runs the candidate through a six-phase pipeline before exposing it to the LLM (see below).

### `code.execute` Sandbox Preamble

Every `code.execute` snippet is wrapped by a small deterministic preamble that the runtime prepends before the LLM-written code. It exists to close recurring classes of NameError / TypeError leaks from LLM-generated snippets:

- **Pre-imported standard-library modules**: `json`, `pathlib`, `re`, `math`, `datetime`, plus `os`, `sys`, and `builtins` aliased as `_os`, `_sys`, `_builtins`. Snippets can use these without an explicit `import`.
- **Pre-injected workspace helpers**: `_workspace_dir`, `_output_dir`, `_secrets`, plus helpers `_ensure_dir()`, `_output_file()`, `_input_file()`, `_list_files()`, `_verify_png()`.
- **Safe `open()` wrapper**: writes (`"w"`, `"a"`, `"x"`) auto-create parent directories. Text-mode writes are additionally wrapped in an `_AWPFileProxy` that transparently re-opens the file in binary mode if the caller writes `bytes` / `bytearray` / `memoryview` — preventing the common "write() argument must be str, not bytes" failure mode.
- **Fresh subprocess per call**: each `code.execute` invocation is an isolated Python subprocess (unless a persistent executor is configured). Python-level state (variables, DataFrames, imports done by the snippet) does NOT persist across calls; pass state via files under `_workspace_dir` or via declared `share_output` fields.

Tools are also bounded by an **enforced security envelope** declared in the manifest:

- `shell.execute` and `terminal.execute` are by default in `worker_policy.enforced.forbidden_tools` for the delegation loop. Workers do shell-like work via `code.execute` in the sandbox, or via dynamically generated MCP tools that wrap a narrow capability with proper input validation.
- The sandbox declares hard limits (memory, CPU seconds, network on/off, filesystem read/write/deny) that the manager cannot relax.
- Secrets are injected through a separate `_secrets` channel and are never visible to the LLM.

Capabilities are declared in the `capabilities` section of [agent.awp.yaml](agent.md) (per-agent) and in the `capabilities.custom_tools` section of [workflow.awp.yaml](manifest.md) (workflow-wide custom tools).

> See also: [agent.md](agent.md), [manifest.md](manifest.md), [runtime.md](runtime.md), [runtime-tool-generation.md](runtime-tool-generation.md), [security.md](security.md), [validation.md](validation.md).

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
| `terminal.execute` | Execute a shell command (sudo and privilege escalation forbidden). |
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
| `board.post` | Post a signal to the sibling-coordination blackboard for the current manager run (run-scoped). |
| `board.read` | Read signals from the sibling-coordination blackboard (optional `topic` / `since` filters). |
| `digest.fetch` | Fetch a Hierarchical Context Digest by its SHA from the current manager run's DigestStore. |
| `repo.fact` | Return up to `max_snippets` TF-IDF-ranked text snippets from the run's input workspace (`<workspace>/inputs/`). Pure Python; no network. Cached per-run at `<workspace>/.fact_index.json`. Signature: `repo.fact(query: str, max_snippets: int = 3)`. Opt-in via `tools_allowed` — not registered into default workflows. |

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

## shell.execute vs terminal.execute

Both tools execute shell commands with the same parameters (`command`, `timeout`, `cwd`) and the same 120-second hard cap. The difference is a single security constraint:

| | `shell.execute` | `terminal.execute` |
|---|---|---|
| Full shell access | Yes | Yes |
| `sudo` / `pkexec` / `doas` | Allowed | **Blocked (403)** |
| Security system impact | None | None — uses the same access control, rate limiting, and circuit breaker |

`terminal.execute` rejects commands that invoke `sudo`, `/usr/bin/sudo`, `pkexec`, `doas`, or privilege escalation via `env sudo` / `command sudo`, including chained commands (`echo hi && sudo rm -rf /`).

**When to use which:**
- Use `terminal.execute` for agents that need shell access without privilege escalation (the common case).
- Use `shell.execute` only when an agent genuinely needs elevated privileges.
- In delegation loop workflows, both are typically in `forbidden_tools` — workers use `code.execute` instead.

## Tool Secrets

Tools that need API keys or credentials declare them via the `secrets` parameter in the `@app.tool()` decorator. The AWP runtime injects the values at call time through a `_secrets` dict — the LLM never sees them.

### Declaring Secrets in a Tool

```python
@app.tool("search.query", secrets=["SEARCH_API_KEY"])
def query(*, q: str, _secrets: dict = {}) -> dict:
    """Search using a premium API."""
    api_key = _secrets.get("SEARCH_API_KEY", "")
    # ... use api_key ...
```

- `secrets=["KEY1", "KEY2"]` — declares which keys the tool needs.
- `_secrets: dict = {}` — receives the injected values at runtime. **Must** have a default so the tool works without secrets too.
- The `_secrets` parameter is automatically excluded from the tool definition sent to the LLM.

### Providing Secrets

Create a `secrets.yaml` file at the workflow root (this file is gitignored):

```yaml
secrets:
  SEARCH_API_KEY: "sk-abc123"
  DATABASE_URL: "{{ env.PROD_DATABASE_URL }}"  # reference an env var
```

Resolution priority (later wins): `os.environ` → `.env` file → `secrets.yaml`.

The `{{ env.VAR_NAME }}` template syntax lets you reference environment variables without hardcoding values.

### Declaring Required Secrets in the Manifest

Document required secrets in `workflow.awp.yaml` so users know what to provide:

```yaml
env:
  required:
    - name: SEARCH_API_KEY
      description: "API key for premium search"
      sensitive: true
    - name: AUTH_TOKEN
      description: "Bearer token for external API"
      sensitive: true
```

Variables with `sensitive: true` are never logged.

### Fail-Fast Validation

The runtime validates all secrets at startup before any agent runs. If a tool declares `secrets=["KEY"]` but the key is not found in `secrets.yaml`, `.env`, or `os.environ`:

```
ERROR: Missing secrets for 1 tool(s):
  - search.query: SEARCH_API_KEY

Provide them in secrets.yaml, .env, or as environment variables.
```

### How It Works at Runtime

```
1. load_secrets(workflow_dir)         → merge os.environ + .env + secrets.yaml
2. ToolRegistry(dir, secrets=dict)    → stores secrets
3. Tool registration                  → AST extracts secrets=["KEY"] from decorator
4. validate_secrets()                 → fail-fast check before agents run
5. call("tool.name", {args})          → injects _secrets={KEY: val} for declared keys only
```

The LLM only sees the tool's regular parameters (query, max_results, etc.). The `_secrets` dict is injected by the runtime as a separate channel.

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

## Runtime Tool Generation (B1-B6)

When a delegation-loop worker needs a capability that no existing tool provides, it can **generate a new MCP tool at runtime**. The runtime never trusts the generated code blindly — it runs every candidate through a six-phase pipeline:

| Phase | Name | What happens |
|---|---|---|
| **B1** | Brief | Worker emits a structured *tool brief* (name, purpose, signature, expected I/O). |
| **B2** | Generate | LLM writes the FastMCP tool implementation against the brief. |
| **B3** | Validate | Static checks: FQN format, response shape, parameter annotations, no reserved namespace, no forbidden imports. |
| **B4** | Sandbox | The tool is executed inside the agent sandbox against synthetic / probe inputs. |
| **B5** | Auto-Repair | On failure, the runtime feeds the error back to the LLM for a bounded number of repair attempts. |
| **B6** | Register | On success, the tool is registered into the workflow's tool registry and exposed to the worker (and only that worker, unless promoted). |

This pipeline is **enabled by default** for delegation-loop workers (`codemode.tool_creation: true` in `manager_controlled`). The manager can disable it per-worker via the delegation envelope. Generated tools are persisted to `workspace/runs/{run_id}/artifacts/tools/` for audit and replay.

For the full specification (brief schema, repair strategy, validation rules, examples) see [runtime-tool-generation.md](runtime-tool-generation.md).

## Code Mode — Alternative Tool Execution

Code Mode is an alternative to classic tool-by-tool execution. Instead of the
LLM calling individual tools, it writes code against a **typed SDK** that wraps
all allowed tools as methods. The code runs in a sandbox and returns the result.

### Why Code Mode?

| Aspect | Classic Mode | Code Mode |
|--------|-------------|-----------|
| **Token usage** | High (tool defs × calls) | Low (SDK types once, one code block) |
| **LLM roundtrips** | One per tool call | One total |
| **Debugging** | Step-by-step | Full code trace |
| **Best for** | Few tools, simple flows | Many tools, complex orchestration |

### Configuration

Add `capabilities.codemode` to `agent.awp.yaml`:

```yaml
capabilities:
  tools:
    enabled: true
    allowed: ["web.*", "file.*", "memory.*"]

  sandbox:
    type: isolate                        # or subprocess, docker
    constraints:
      max_memory_mb: 128
      max_cpu_seconds: 30
    network:
      enabled: false

  codemode:
    enabled: true
    language: typescript                 # typescript | python | javascript
    sdk_surface:
      mode: auto                         # all allowed tools → SDK methods
    execution:
      timeout: 30
      max_retries: 1
      capture_console: true
```

### How It Works

1. Runtime generates a typed SDK from `tools.allowed` (e.g., `sdk.web.search()`, `sdk.file.read()`).
2. SDK type definitions replace tool definitions in the system prompt.
3. LLM writes a code block using the SDK.
4. Runtime executes the code in the configured sandbox.
5. SDK method calls are routed to the MCP tool registry internally.
6. The return value is validated against `output_schema.json`.

### SDK Surface Modes

- **`auto`** (default): All tools in `capabilities.tools.allowed` become SDK methods.
- **`explicit`**: Only tools listed in `sdk_surface.include` are available.

Use `sdk_surface.exclude` to remove specific tools from the SDK while keeping them available for classic calls.

### Output Contract

Code Mode does **not** change the output contract. The generated code must
return a JSON object matching `output_schema.json`, including `confidence`.
This means Code Mode agents are fully interchangeable with classic agents in
the DAG.

### Validation Rules

- **R19:** `codemode.enabled: true` requires `tools.enabled: true`
- **R20:** `codemode.enabled: true` requires `sandbox.type` to be set (not `none`)
- **R21:** `codemode.language` must be `typescript`, `python`, or `javascript`
- **R22:** `sdk_surface.mode: explicit` must have at least one tool in `include`
- **R23:** Tools in `sdk_surface.exclude` must exist in `tools.allowed`
- **R24:** `sandbox.type: isolate` requires `sandbox.network` to be defined

For the full specification, see [spec/versions/1.0/layers/02-capabilities.md](../spec/versions/1.0/layers/02-capabilities.md).

---

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
