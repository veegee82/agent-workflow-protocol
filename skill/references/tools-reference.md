# AWP Built-in Tools Reference

AWP-compliant runtimes SHOULD provide the following built-in tools. All tools use the `namespace.action` naming convention and return the standard AWP tool result format.

## Standard Tool Result Format

Every tool MUST return:

```json
{
  "ok": true,
  "status": 200,
  "data": { ... },
  "error": null,
  "log": null
}
```

| Field | Type | Description |
|-------|------|-------------|
| `ok` | boolean | Whether the call succeeded |
| `status` | integer | HTTP-like status code (200, 400, 404, 500) |
| `data` | any | Result payload (tool-specific) |
| `error` | string or null | Error message if `ok` is false |
| `log` | string or null | Execution log for debugging |

---

## Web Tools

### `web.search`

Search the web for information.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `query` | string | Yes | -- | Search query (1-500 chars) |
| `max_results` | integer | No | 10 | Maximum results (1-100) |
| `language` | string | No | "en" | Language filter (ISO 639-1) |

### `http.request`

Make an arbitrary HTTP request.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `url` | string | Yes | -- | Target URL |
| `method` | string | No | "GET" | HTTP method |
| `headers` | object | No | {} | HTTP headers |
| `body` | string | No | null | Request body |
| `timeout` | integer | No | 30 | Timeout in seconds |

---

## File Tools

### `file.read`

Read file contents from disk.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `path` | string | Yes | -- | File path |
| `encoding` | string | No | "utf-8" | File encoding |

### `file.write`

Write content to a file.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `path` | string | Yes | -- | File path |
| `content` | string | Yes | -- | Content to write |
| `mode` | string | No | "overwrite" | "overwrite" or "append" |

### `file.list`

List files in a directory.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `path` | string | Yes | -- | Directory path |
| `pattern` | string | No | "*" | Glob pattern |
| `recursive` | boolean | No | false | Include subdirectories |

---

## Shell Tools

### `shell.execute`

Execute a shell command in a sandboxed environment.

> **Restricted.** `shell.execute` is in the delegation loop's default `forbidden_tools` list. Workers MUST NOT receive it via `tools_allowed`; it will be silently removed by the runtime. Use `code.execute` for Python execution or `terminal.execute` for sudo-free shell access.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `command` | string | Yes | -- | Command to execute |
| `timeout` | integer | No | 30 | Timeout in seconds |
| `cwd` | string | No | null | Working directory |

### `terminal.execute`

Sudo-free shell execution. Rejects any command containing `sudo`, `pkexec`, or `doas`. Use instead of `shell.execute` when an agent needs terminal access without privilege escalation.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `command` | string | Yes | -- | Command (no sudo/pkexec/doas) |
| `timeout` | integer | No | 30 | Timeout in seconds |
| `cwd` | string | No | null | Working directory |

### `code.execute`

Execute a Python snippet in a sandbox subprocess with an auto-injected preamble (`json`, `pathlib`, `re`, `math`, `datetime` pre-imported; `_workspace_dir`, `_output_dir`, `_secrets`, `_ensure_dir()`, `_output_file()`, `_input_file()`, `_list_files()`, `_verify_png()` pre-bound). Each call is a fresh subprocess — pass state via files under `_workspace_dir`. This is the default code execution tool for delegation-loop workers and replaces `shell.execute`.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `code` | string | Yes | -- | Python snippet (no `import os`, `subprocess`, `sys`, `ctypes`, `importlib`, `signal`, `multiprocessing`) |
| `timeout` | integer | No | 60 | Timeout in seconds |

---

## Agent Communication Tools

### `agent.send_message`

Send a message to another agent via the message bus.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `to` | string | Yes | -- | Target agent ID or "*" for broadcast |
| `content` | any | Yes | -- | Message content |
| `channel` | string | No | "direct" | Channel name |
| `type` | string | No | "event" | Message type (request/response/event) |

### `agent.list_messages`

List messages received from other agents.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `from_agent` | string | No | null | Filter by sender |
| `channel` | string | No | null | Filter by channel |
| `limit` | integer | No | 50 | Maximum messages to return |

---

## Memory Tools

### `memory.write`

Write to daily log or long-term memory (MEMORY.md).

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `content` | string | Yes | -- | Content to write |
| `target` | string | No | "daily" | "daily" or "long_term" |

### `memory.search`

Keyword search across all memory files.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `query` | string | Yes | -- | Search query |
| `max_results` | integer | No | 10 | Maximum results |
| `date_range` | string | No | null | Date filter (e.g., "2026-03-01:2026-03-23") |

### `memory.read`

Read MEMORY.md, daily log, or list available dates.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `target` | string | No | "long_term" | "long_term", "daily", or "dates" |
| `date` | string | No | null | Specific date for daily log (YYYY-MM-DD) |

### `memory.curate`

Trigger LLM-based curation: extract stable facts from daily logs into MEMORY.md.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `days` | integer | No | 7 | Number of recent days to curate |
| `model` | string | No | null | Override curation model |

---

## Delegation Loop Runtime Tools (auto-injected, A2+)

These tools are automatically injected into every worker's tool surface by the delegation-loop runner when the corresponding feature flag is enabled. Workers do NOT need to list them in `tools_allowed`.

### `board.post` — sibling blackboard append (auto-injected when `delegation_loop.blackboard_enabled: true`, default `true`)

Append an entry to the run-scoped append-only JSONL blackboard at `<workspace>/blackboard/<manager_run_id>.jsonl`. Siblings in the SAME manager run see each other's signals.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `topic` | string | Yes | -- | Topic identifier (e.g., "dead_end", "finding") |
| `payload` | object | Yes | -- | JSON-serialisable payload |

### `board.read` — sibling blackboard read (auto-injected)

Read entries from the same run-scoped blackboard.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `topic` | string | No | null | Filter by topic |
| `since` | integer | No | null | Return only entries after this sequence number |

### `digest.fetch` — hierarchical context digest lookup (auto-injected when `delegation_loop.digest_enabled: true`, default `true`)

Fetch a per-level digest record by SHA from the current manager run's `DigestStore`. Used by workers to access digest layers deeper than `digest_max_depth` that are not inlined in the prompt. Cross-run access is refused.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `sha` | string | Yes | -- | Content-addressed digest SHA |

---

## Dynamic Tool Creation Meta-Tool (A3)

### `dynamic.create_tool`

Create a new MCP tool at runtime. Requires `capabilities.codemode.tool_creation: true` on the calling agent AND `dynamic_tools.enabled: true` in `workflow.awp.yaml` (R26). The `name` MUST use an approved `allowed_namespaces` prefix (R25).

Preferred modes — `reuse_or_generate`:
- `reuse` — bind to an existing `pattern_id` from the seeded pattern table.
- `synthesize` — deterministic archetype instantiation. Set `archetype_id` ∈ {`compute`, `fetch`, `parse`, `transform`, `render`, `probe`} and `recipe_params`. Recipes that succeed are auto-captured under `~/.awp/recipes/` (Quarantined → Probationary → Trusted).
- `generate` — last-resort free-form codegen. Requires an `assumptions` list.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `name` | string | Yes | `<namespace>.<action>`, namespace MUST be in `dynamic_tools.allowed_namespaces` |
| `description` | string | Yes | One-line purpose |
| `parameters` | object | Yes | JSON Schema object for inputs |
| `code` | string | Conditional | Required for `generate`; optional for `synthesize` when the archetype skeleton is complete |
| `archetype_id` | string | Conditional | Required for `synthesize` |
| `recipe_params` | object | Conditional | Required for `synthesize` |
| `pattern_id` | string | Conditional | Required for `reuse` |
| `required_secrets` | array | No | Secret keys injected as `_secrets` dict in the sandbox |

---

## Arithmetic Tools

### `arithmetic.add` / `arithmetic.subtract` / `arithmetic.multiply` / `arithmetic.divide`

Basic arithmetic operations.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `a` | number | Yes | First operand |
| `b` | number | Yes | Second operand |

---

## Reserved Namespaces

The following namespaces are reserved for built-in tools. Custom tools and dynamically-created tools MUST NOT use these namespaces (R25):

`web`, `http`, `file`, `shell`, `terminal`, `code`, `agent`, `memory`, `arithmetic`, `numpy`, `matplot`, `pandas`, `doc`, `sklearn`, `board`, `digest`, `dynamic`
