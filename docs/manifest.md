# workflow.awp.yaml Reference

The manifest is the root document of every AWP workflow. It declares the workflow's identity, version, dependencies, environment requirements, and default settings. Every AWP workflow must contain exactly one `workflow.awp.yaml` file at the root of the workflow directory.

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

### `workflow.conformance`

- **Type:** string
- **Description:** Target [compliance level](compliance.md) (e.g., `L0`, `L1`, `L2`, `L3`, `L4`, `L5`). If omitted, the runtime should infer the level from the configuration.

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
| `workflow.conformance` | string | No | L0-L5 |
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
  license: "Apache-2.0"
  tags:
    - research
    - writing
    - web-search
  homepage: "https://example.com/research-and-write"
  repository: "https://github.com/example/research-and-write"
  conformance: L1

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
      max_tokens: 4096
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
