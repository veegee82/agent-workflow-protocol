# workflow.awp.yaml Reference

## Mental Model

`workflow.awp.yaml` is the **root document** of every AWP workflow — the single anchor file that ties together identity, dependencies, the orchestration graph, security, memory, and observability. If you only read one file to understand a workflow, read this one. Everything else (`agent.awp.yaml`, custom MCP tools, skills) is referenced from here.

The manifest exists to **separate workflow definition from implementation**. The YAML declares *what* should happen — which agents, in what order, with which budgets, and under which security envelope — while the Python (or other language) implementation declares *how*. This separation is what makes AWP workflows portable across runtimes (standalone Python, Cloudflare Workers, custom adapters) and auditable without reading any code.

A manifest plays three roles at once:

1. **Identity & contract** — name, version, autonomy level, required runtime capabilities, and required environment variables. The runtime uses these for fail-fast validation before any agent runs.
2. **Composition root** — the manifest references all other layers via top-level sections (`orchestration`, `state`, `memory`, `communication`, `observability`, `security`, `capabilities.custom_tools`). See the cross-reference table below.
3. **Safety envelope** — for A2-A4 workflows, the manifest declares the **`delegation_loop`** section with budgets, forbidden tools, sandbox limits, and the manager's auto-promotion thresholds. The runtime enforces these envelope fields deterministically; even a hallucinating manager cannot escape them.

> See also: [orchestration.md](orchestration.md), [ORCHESTRATION_ENGINES.md](ORCHESTRATION_ENGINES.md), [tools.md](tools.md), [runtime.md](runtime.md), [compliance.md](compliance.md), [manager-intelligence.md](manager-intelligence.md).

## Required Fields

### `awp` -- Protocol Version

- **Type:** string (SemVer)
- **Required:** Yes
- **Description:** The AWP protocol version this workflow conforms to.

```yaml
awp: "1.0.0"
```

The runtime must reject a manifest whose major version it does not support.

### `workflow` -- Workflow Metadata

The `workflow` section must be present with the following required fields:

#### `workflow.name`

- **Type:** string
- **Required:** Yes
- **Constraints:** Kebab-case, 2-64 characters. Must match `^[a-z][a-z0-9_-]{0,62}[a-z0-9]$`
- **Description:** Primary identifier for the workflow across registries, file systems, and APIs.

```yaml
workflow:
  name: research-and-write
```

#### `workflow.version`

- **Type:** string (SemVer)
- **Required:** Yes

```yaml
workflow:
  version: "1.0.0"
```

#### `workflow.description`

- **Type:** string
- **Required:** Yes
- **Constraints:** Maximum 500 characters.

## Optional Workflow Fields

### `workflow.author`

- **Type:** string
- **Description:** Author or organization responsible for the workflow.

### `workflow.license`

- **Type:** string (SPDX identifier)
- **Description:** License under which the workflow is distributed. Should be a valid SPDX license identifier.

### `workflow.tags`

- **Type:** list of strings
- **Description:** Tags for categorization and discovery.

### `workflow.homepage`

- **Type:** string (URL)
- **Description:** URL of the workflow's homepage or documentation.

### `workflow.repository`

- **Type:** string (URL)
- **Description:** URL of the workflow's source code repository.

### `workflow.autonomy`

- **Type:** string
- **Description:** Target [autonomy level](compliance.md) (e.g., `A0`, `A1`, `A2`, `A3`, `A4`). If omitted, the runtime should infer the level from the configuration.

### `workflow.runtime`

Runtime requirements and constraints.

| Field | Type | Description |
|-------|------|-------------|
| `min_awp_version` | string (SemVer) | Minimum AWP version required. Runtime must reject if unsupported. |
| `python` | string | Python version constraint (e.g., `">=3.10"`). Applies only to Python runtimes. |
| `required_providers` | list of strings | LLM providers the workflow requires (e.g., `["openrouter"]`). |
| `required_capabilities` | list of strings | Runtime capabilities required (e.g., `["tool_calling", "vision"]`). |

### `workflow.dependencies`

External dependencies the workflow requires.

| Field | Type | Description |
|-------|------|-------------|
| `tools` | list of objects | External MCP tool packages. Each must have `name` and `version`. |
| `workflows` | list of objects | Sub-workflows. Each must have `name` and `version`. |
| `skills` | list of objects | External skill packages. Each must have `name` and `version`. |
| `python` | list of strings | Python package requirements in pip format (e.g., `"numpy>=1.24"`). |

### `workflow.env`

Environment variables the workflow expects. Each entry has:

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `name` | string | Yes | -- | Environment variable name. |
| `description` | string | No | -- | Human-readable description. |
| `required` | boolean | No | `false` | Whether the variable must be set. |
| `sensitive` | boolean | No | `false` | If `true`, the value must not appear in logs or output. |
| `default` | string | No | -- | Default value if not set in the environment. |

### `workflow.settings`

Default settings for the workflow.

| Field | Type | Description |
|-------|------|-------------|
| `llm` | object | Default LLM settings: `default_provider`, `default_model`, `temperature`, `max_tokens`. |
| `custom` | object | Arbitrary key-value pairs passed through to agents without modification. |

## Manager Envelope (A2-A4 Workflows)

Workflows that use the **delegation loop** engine declare a `delegation_loop` block under `orchestration`. The most safety-critical fields — budgets, forbidden tools, sandbox limits, auto-promotion thresholds, and the worker policy split — live in the manifest because they form the **enforced envelope** that the manager cannot override at runtime.

```yaml
orchestration:
  engine: delegation_loop
  delegation_loop:
    manager: agents/manager

    models:
      manager: nvidia/nemotron-3-super-120b-a12b   # default manager model
      worker:  openai/gpt-5-mini                   # default worker model

    worker_policy:
      enforced:
        sandbox:
          type: subprocess
          max_memory_mb: 512
          max_cpu_seconds: 30
          network: false
        forbidden_tools:
          - "shell.execute"        # forbidden in delegation loop by default
          - "terminal.execute"
        codemode:
          max_tools_per_worker: 10
        rate_limiting:
          max_llm_calls_per_minute: 30
      manager_controlled:
        - instructions
        - skills
        - tools_allowed
        - output_contract
        - codemode.enabled         # default: enabled
        - codemode.tool_creation   # default: enabled
        - temperature

    auto_promotion:                # complexity-scored submanager promotion
      enabled: true
      complexity_threshold: 3
      max_promotions_per_iteration_fraction: 0.5

    budget:
      max_loops: 20
      max_total_workers: 30
      max_total_tokens: 1000000
      max_wall_time: 600
      max_depth: 5
```

Key envelope fields:

| Field | Purpose |
|---|---|
| `worker_policy.enforced.forbidden_tools` | Tools the manager **may not** grant to workers. `shell.execute` and `terminal.execute` are forbidden by default in delegation loops — workers use `code.execute` instead. See [tools.md](tools.md). |
| `worker_policy.enforced.sandbox` | Hard limits for the worker sandbox. Manager cannot relax. |
| `worker_policy.manager_controlled` | The whitelist of fields the manager *can* set per worker (instructions, skills, tool list, output contract, codemode toggles, temperature). |
| `auto_promotion.complexity_threshold` | Minimum complexity score for a worker subtask to be promoted to a submanager (A4). See [manager-intelligence.md](manager-intelligence.md). |
| `budget.*` | Hard envelope: loops, workers, tokens, wall time, depth. Reservation model guarantees `sum(children) + self <= allocation`. |
| `models.manager` / `models.worker` | Default routing per role. Provider auto-detected from the model string (`provider/model` → OpenRouter, `gpt-*`/`o3*` → OpenAI direct, `claude-*` → Anthropic, `ollama/*` → local). See [runtime.md](runtime.md). |

For the full delegation-loop reference (engine semantics, validation tiers, critique loop, history & spillover) see [ORCHESTRATION_ENGINES.md](ORCHESTRATION_ENGINES.md) and [orchestration.md](orchestration.md).

## How the Manifest References Other Sections

The manifest is the anchor document. It contains or references the following top-level sections (each documented in its own reference page):

| Section | Reference |
|---------|-----------|
| `orchestration` | [Orchestration Reference](orchestration.md) |
| `state` | [Memory & State Reference](memory.md) |
| `memory` | [Memory & State Reference](memory.md) |
| `communication` | [Communication Reference](communication.md) |
| `observability` | [Observability Reference](observability.md) |
| `security` | [Security Reference](security.md) |
| `capabilities.custom_tools` | [Tools Reference](tools.md) |

## Field Reference Table

| Field Path | Type | Required | Constraints |
|------------|------|----------|-------------|
| `awp` | string | Yes | Valid SemVer |
| `workflow.name` | string | Yes | kebab-case, 2-64 chars, `^[a-z][a-z0-9_-]{0,62}[a-z0-9]$` |
| `workflow.version` | string | Yes | Valid SemVer |
| `workflow.description` | string | Yes | Max 500 chars |
| `workflow.author` | string | No | -- |
| `workflow.license` | string | No | SPDX identifier |
| `workflow.tags` | list | No | -- |
| `workflow.homepage` | string | No | Valid URL |
| `workflow.repository` | string | No | Valid URL |
| `workflow.autonomy` | string | No | A0-A4 |
| `workflow.runtime` | object | No | See above |
| `workflow.runtime.min_awp_version` | string | No | Valid SemVer |
| `workflow.runtime.python` | string | No | Version constraint |
| `workflow.runtime.required_providers` | list | No | -- |
| `workflow.runtime.required_capabilities` | list | No | -- |
| `workflow.dependencies` | object | No | See above |
| `workflow.dependencies.tools` | list | No | Objects with `name`, `version` |
| `workflow.dependencies.workflows` | list | No | Objects with `name`, `version` |
| `workflow.dependencies.skills` | list | No | Objects with `name`, `version` |
| `workflow.dependencies.python` | list | No | pip format strings |
| `workflow.env` | list | No | See above |
| `workflow.settings` | object | No | See above |
| `workflow.settings.llm` | object | No | -- |
| `workflow.settings.custom` | object | No | Arbitrary key-value |

## Complete Example

```yaml
awp: "1.0.0"

workflow:
  name: research-and-write
  version: "1.0.0"
  description: >
    A two-agent workflow that researches a topic using web search
    and produces a structured written report.
  author: "AWP Contributors"
  license: "MIT"
  tags:
    - research
    - writing
    - web-search
  homepage: "https://example.com/research-and-write"
  repository: "https://github.com/example/research-and-write"
  autonomy: A1

  runtime:
    min_awp_version: "1.0.0"
    python: ">=3.10"
    required_providers:
      - openrouter
    required_capabilities:
      - tool_calling

  dependencies:
    tools:
      - name: web-search
        version: ">=1.0.0"
    python:
      - "beautifulsoup4>=4.12"
      - "httpx>=0.25"

  env:
    - name: OPENROUTER_API_KEY
      description: "API key for OpenRouter LLM provider"
      required: true
      sensitive: true
    - name: MAX_SEARCH_RESULTS
      description: "Maximum number of search results to return"
      required: false
      default: "10"

  settings:
    llm:
      default_provider: openrouter
      default_model: "anthropic/claude-sonnet-4"
      temperature: 0.0
      max_tokens: 32768
    custom:
      output_format: markdown
      max_report_length: 5000

orchestration:
  engine: dag
  graph:
    - id: research_analyst
      agent: agents/research_analyst
      depends_on: []
      share_output: [findings, summary]
    - id: report_writer
      agent: agents/report_writer
      depends_on: [research_analyst]
      share_output: [draft, final_output]
  execution:
    mode: sequential
    timeout_per_agent: 120
    timeout_total: 300

state:
  persistence:
    enabled: true
    path: "data/state"
  sharing:
    strategy: selective
```

## Processing Rules

1. The runtime must parse the `awp` field first and reject the manifest if the major version is unsupported.
2. The runtime must validate all required fields are present before proceeding.
3. The runtime must validate the `workflow.name` field against the specified regex.
4. The runtime must not start workflow execution if any `workflow.env` entry with `required: true` is missing from the environment and has no `default` value.
5. The runtime must not log or output any environment variable marked `sensitive: true`.
6. Unknown fields at any level should be ignored by the runtime to allow forward compatibility.
