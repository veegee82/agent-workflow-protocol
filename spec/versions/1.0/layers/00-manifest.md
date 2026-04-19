# Layer 0: Manifest

**AWP Specification v1.0.0 — Layer 0**
**Status:** Draft Standard

> **See also** — **Parent**: [spec.md](../spec.md), [docs/layer-model.md](../../../../docs/layer-model.md) · **Non-normative explainer**: [docs/manifest.md](../../../../docs/manifest.md) · **Sibling layers**: [01-agent-identity.md](01-agent-identity.md), [02-capabilities.md](02-capabilities.md), [03-communication.md](03-communication.md), [04-memory-state.md](04-memory-state.md), [05-orchestration.md](05-orchestration.md), [06-observability.md](06-observability.md), [security.md](security.md) · **Validation rules for this layer**: [../validation-rules.md](../validation-rules.md)

---

## 1. Overview

The manifest is the root document of every AWP workflow. It is a YAML file named `workflow.awp.yaml` located at the root of the workflow directory. The manifest declares the workflow's identity, version, dependencies, environment requirements, and default settings.

Every AWP workflow MUST contain exactly one `workflow.awp.yaml` file at the root of the workflow directory.

---

## 2. File Name

The manifest file MUST be named `workflow.awp.yaml`. Runtimes MUST NOT accept alternative file names for the manifest.

---

## 3. Required Fields

### 3.1 `awp` — Protocol Version

- **Type:** string (SemVer)
- **Status:** REQUIRED
- **Description:** The AWP protocol version this workflow conforms to.
- **Constraints:** MUST be a valid Semantic Versioning 2.0.0 string.

```yaml
awp: "1.0.0"
```

### 3.2 `workflow` — Workflow Metadata

The `workflow` section MUST be present and MUST contain the following fields:

#### 3.2.1 `workflow.name`

- **Type:** string
- **Status:** REQUIRED
- **Constraints:**
  - MUST be kebab-case.
  - MUST be between 2 and 64 characters.
  - MUST match the regex: `^[a-z][a-z0-9_-]{0,62}[a-z0-9]$`
- **Rationale:** The name serves as the primary identifier for the workflow across registries, file systems, and APIs.

#### 3.2.2 `workflow.version`

- **Type:** string (SemVer)
- **Status:** REQUIRED
- **Constraints:** MUST be a valid Semantic Versioning 2.0.0 string.

#### 3.2.3 `workflow.description`

- **Type:** string
- **Status:** REQUIRED
- **Constraints:** MUST NOT exceed 500 characters.

---

## 4. Optional Fields

### 4.1 `workflow.author`

- **Type:** string
- **Status:** OPTIONAL
- **Description:** The author or organization responsible for the workflow.

### 4.2 `workflow.license`

- **Type:** string (SPDX identifier)
- **Status:** OPTIONAL
- **Description:** The license under which the workflow is distributed. SHOULD be a valid [SPDX license identifier](https://spdx.org/licenses/).

### 4.3 `workflow.tags`

- **Type:** list of strings
- **Status:** OPTIONAL
- **Description:** Tags for categorization and discovery.

### 4.4 `workflow.homepage`

- **Type:** string (URL)
- **Status:** OPTIONAL
- **Description:** URL of the workflow's homepage or documentation.

### 4.5 `workflow.repository`

- **Type:** string (URL)
- **Status:** OPTIONAL
- **Description:** URL of the workflow's source code repository.

### 4.6 `workflow.runtime`

- **Type:** object
- **Status:** OPTIONAL
- **Description:** Runtime requirements and constraints.

| Field | Type | Description |
|-------|------|-------------|
| `min_awp_version` | string (SemVer) | Minimum AWP version required. Runtime MUST reject if unsupported. |
| `python` | string | Python version constraint (e.g., `">=3.10"`). OPTIONAL; applies only to Python runtimes. |
| `required_providers` | list of strings | LLM providers the workflow requires (e.g., `["openrouter"]`). |
| `required_capabilities` | list of strings | Runtime capabilities required (e.g., `["tool_calling", "vision"]`). |

### 4.7 `workflow.dependencies`

- **Type:** object
- **Status:** OPTIONAL
- **Description:** External dependencies the workflow requires.

| Field | Type | Description |
|-------|------|-------------|
| `tools` | list of objects | External MCP tool packages. Each object MUST have `name` and `version`. |
| `workflows` | list of objects | Sub-workflows referenced by this workflow. Each object MUST have `name` and `version`. |
| `skills` | list of objects | External skill packages. Each object MUST have `name` and `version`. |
| `python` | list of strings | Python package requirements (pip format, e.g., `"numpy>=1.24"`). |

### 4.8 `workflow.env`

- **Type:** list of objects
- **Status:** OPTIONAL
- **Description:** Environment variables the workflow expects.

Each entry MUST have:

| Field | Type | Status | Description |
|-------|------|--------|-------------|
| `name` | string | REQUIRED | Environment variable name. |
| `description` | string | OPTIONAL | Human-readable description. |
| `required` | boolean | OPTIONAL | Whether the variable MUST be set. Default: `false`. |
| `sensitive` | boolean | OPTIONAL | If `true`, the value MUST NOT appear in logs or output. Default: `false`. |
| `default` | string | OPTIONAL | Default value if not set in the environment. |

### 4.9 `workflow.settings`

- **Type:** object
- **Status:** OPTIONAL
- **Description:** Default settings for the workflow.

| Field | Type | Description |
|-------|------|-------------|
| `llm` | object | Default LLM settings. MAY include `default_provider`, `default_model`, `temperature`, `max_tokens`. |
| `custom` | object | Arbitrary key-value pairs. Runtimes MUST pass these through to agents without modification. |

---

## 5. Field Reference Table

| Field Path | Type | Status | Constraints |
|------------|------|--------|-------------|
| `awp` | string | REQUIRED | Valid SemVer |
| `workflow.name` | string | REQUIRED | kebab-case, 2–64 chars, `^[a-z][a-z0-9_-]{0,62}[a-z0-9]$` |
| `workflow.version` | string | REQUIRED | Valid SemVer |
| `workflow.description` | string | REQUIRED | Max 500 chars |
| `workflow.author` | string | OPTIONAL | — |
| `workflow.license` | string | OPTIONAL | SPDX identifier |
| `workflow.tags` | list | OPTIONAL | — |
| `workflow.homepage` | string | OPTIONAL | Valid URL |
| `workflow.repository` | string | OPTIONAL | Valid URL |
| `workflow.runtime` | object | OPTIONAL | See Section 4.6 |
| `workflow.runtime.min_awp_version` | string | OPTIONAL | Valid SemVer |
| `workflow.runtime.python` | string | OPTIONAL | Version constraint |
| `workflow.runtime.required_providers` | list | OPTIONAL | — |
| `workflow.runtime.required_capabilities` | list | OPTIONAL | — |
| `workflow.dependencies` | object | OPTIONAL | See Section 4.7 |
| `workflow.dependencies.tools` | list | OPTIONAL | Objects with `name`, `version` |
| `workflow.dependencies.workflows` | list | OPTIONAL | Objects with `name`, `version` |
| `workflow.dependencies.skills` | list | OPTIONAL | Objects with `name`, `version` |
| `workflow.dependencies.python` | list | OPTIONAL | pip format strings |
| `workflow.env` | list | OPTIONAL | See Section 4.8 |
| `workflow.settings` | object | OPTIONAL | See Section 4.9 |
| `workflow.settings.llm` | object | OPTIONAL | — |
| `workflow.settings.custom` | object | OPTIONAL | Arbitrary key-value |

---

## 6. Complete Example

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
```

---

## 7. Processing Rules

1. A runtime MUST parse the `awp` field first and reject the manifest if the MAJOR version is unsupported.
2. A runtime MUST validate all REQUIRED fields are present before proceeding.
3. A runtime MUST validate the `workflow.name` field against the specified regex.
4. A runtime MUST NOT start workflow execution if any `workflow.env` entry with `required: true` is missing from the environment and has no `default` value.
5. A runtime MUST NOT log or output any environment variable marked `sensitive: true`.
6. Unknown fields at any level SHOULD be ignored by the runtime to allow forward compatibility.
