# agent.awp.yaml Reference

> **See also** — **Parent**: [layer-model.md](layer-model.md) (this is Layer 1 — Agent Identity), [docs/README.md](README.md#concept-map) · **Sibling concepts**: [manifest.md](manifest.md) (Layer 0), [tools.md](tools.md) (Layer 2 — capabilities an agent may use), [orchestration.md](orchestration.md) (Layer 5 — how agents are wired into a graph) · **Contract**: the agent output contract **R17** lives in [runtime.md](runtime.md) and is validated per [validation.md](validation.md) · **Deeper**: [runtime-tool-generation.md](runtime-tool-generation.md) (A3+ tool factory an agent can invoke) · **Spec**: [spec/versions/1.0/layers/01-agent-identity.md](../spec/versions/1.0/layers/01-agent-identity.md)

## Mental Model

An **agent** in AWP is the smallest unit of reasoning: an identity, a model, a system prompt, and a strict output contract. Every agent lives in `agents/{agent_id}/agent.awp.yaml` and is referenced from the workflow manifest. Agents are intentionally small and self-describing — the goal is that you can read a single `agent.awp.yaml` and know exactly *who* this agent is, *which model* it runs on, *what* it must produce, and *which tools* it may touch.

Two contracts make agents composable across runtimes:

1. **The output contract (R17).** Every agent's `run()` must return `{self.name: {"confidence": 0.0-1.0, ...}}`. The `confidence` field is mandatory for JSON outputs and is what downstream agents, validators, evaluation gates, and the delegation loop use to make decisions. Without it the runtime will reject the result.
2. **The identity contract.** `identity.id` must match both the agent's directory name and the node `id` used in `orchestration.graph`. This three-way symmetry is what lets the runtime resolve graph nodes deterministically.

Agents come in two flavors:

- **Static agents** — defined as `agent.awp.yaml` files on disk and referenced from the DAG. These are the agents you author.
- **Ephemeral workers** — generated at runtime by a manager in the delegation loop engine. They never exist as files; the manager produces a *Delegation Envelope* (instructions + skills + allowed tools + output contract) per worker. The same `AWPAgent` interface and the same R17 contract apply. See [ORCHESTRATION_ENGINES.md](ORCHESTRATION_ENGINES.md).

Two cross-cutting features modify how an agent executes — both **default to enabled** in modern AWP runtimes:

- **Code mode** (`capabilities.codemode`) lets the agent emit a single code block against a typed SDK instead of issuing many tool calls. This collapses N LLM round-trips into one and dramatically reduces token cost. The output contract is unchanged. See [tools.md](tools.md#code-mode--alternative-tool-execution).
- **Tool creation** lets a worker generate new MCP tools at runtime when the existing toolset is insufficient. The runtime validates, sandboxes, and auto-repairs generated tools through a six-phase pipeline (B1-B6). See [runtime-tool-generation.md](runtime-tool-generation.md) and [tools.md](tools.md#runtime-tool-generation-b1-b6).

> See also: [orchestration.md](orchestration.md), [tools.md](tools.md), [runtime.md](runtime.md), [memory.md](memory.md), [validation.md](validation.md), [critique.md](critique.md).

## Top-Level Field

### `awp_agent` -- Agent Schema Version

- **Type:** string (SemVer)
- **Required:** Yes
- **Description:** The AWP agent schema version this file conforms to.

```yaml
awp_agent: "1.0.0"
```

## Identity Section

The `identity` section must be present.

### `identity.id`

- **Type:** string
- **Required:** Yes
- **Constraints:** snake_case, 2-48 characters. Must match `^[a-z][a-z0-9_]{0,46}[a-z0-9]$`
- **Description:** Unique identifier for the agent within the workflow. Must match the agent's directory name.

### `identity.role`

- **Type:** string
- **Required:** Yes
- **Description:** Short human-readable label for the agent's role (e.g., "researcher", "code reviewer", "summarizer").

### `identity.description`

- **Type:** string
- **Required:** Yes
- **Description:** Detailed description of what this agent does and its purpose in the workflow.

### `identity.version`

- **Type:** string (SemVer)
- **Required:** No
- **Description:** Agent-specific version, independent of the workflow version.

### `identity.tags`

- **Type:** list of strings
- **Required:** No
- **Description:** Tags for categorization.

## Runtime Section

The `runtime` section provides implementation hints for agent instantiation. Non-Python runtimes may ignore these fields entirely.

### `runtime.class_name`

- **Type:** string
- **Required:** No (Recommended for Python)
- **Default:** `"Agent"`
- **Description:** Python class name to import from the agent's module.

### `runtime.strategy_folder`

- **Type:** string
- **Required:** No (Recommended for Python)
- **Default:** `"workflow"`
- **Description:** Folder name within the agent directory containing workflow artifacts (prompts, schemas, preprocessors).

## Model Section

### `model.provider`

- **Type:** string
- **Required:** No
- **Description:** LLM provider to use (e.g., `"openrouter"`, `"ollama"`, `"openai"`, `"anthropic"`). If omitted, the runtime uses the workflow-level default.

### `model.name`

- **Type:** string
- **Required:** Yes
- **Description:** Model identifier. Format is provider-specific (e.g., `"anthropic/claude-sonnet-4"`).

### `model.fallback`

- **Type:** list of strings
- **Required:** No
- **Description:** Ordered list of fallback model identifiers. If the primary model fails, the runtime should attempt each fallback in order.

### `model.parameters`

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `temperature` | float | `0.0` | Sampling temperature. Must be between 0.0 and 2.0. |
| `max_tokens` | integer | `4096` | Maximum tokens in the response. |
| `top_p` | float | `1.0` | Nucleus sampling threshold. Must be between 0.0 and 1.0. |

### `model.reasoning`

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enabled` | boolean | `false` | Whether to enable extended reasoning / chain-of-thought. |
| `effort` | string | `"medium"` | Reasoning effort level: `"low"`, `"medium"`, or `"high"`. |
| `force` | boolean | `false` | If `true`, the runtime must request reasoning even if the model does not natively support it. |

## Prompt Section

### `prompt.system`

- **Type:** string or file reference
- **Required:** Yes
- **Description:** The system prompt. May be an inline string or a file path relative to the agent directory (e.g., `"workflow/instructions/SYSTEM_PROMPT.md"`).

### `prompt.user_template`

- **Type:** string or file reference
- **Required:** No
- **Description:** Template for the user message. Supports variable interpolation using `{{variable_name}}` syntax.

### `prompt.additional`

- **Type:** list of strings or file references
- **Required:** No
- **Description:** Additional prompt fragments appended to the system prompt in order.

### `prompt.variables`

- **Type:** object
- **Required:** No
- **Description:** Key-value pairs for template variable interpolation. Values may reference state fields using `${state.field_name}` syntax.

### `prompt.injection_order`

- **Type:** list of strings
- **Required:** No
- **Default:** `["system", "skills", "memory", "messages", "context", "additional"]`
- **Description:** Defines the order in which prompt components are assembled.

## Output Section

### `output.format`

- **Type:** string
- **Required:** Yes
- **Allowed values:** `"json"`, `"text"`, `"markdown"`

### `output.contract`

- **Type:** object or file reference
- **Required:** Yes when `output.format` is `"json"`, optional otherwise
- **Description:** JSON Schema defining the structure of the agent's output. May be inline or a file path to a `.json` file.

When `output.format` is `"json"`, the agent's output must validate against the contract schema.

#### Output Contract Field Annotations

Fields within the output contract JSON Schema may include AWP-specific annotations:

| Annotation | Type | Default | Description |
|------------|------|---------|-------------|
| `x-awp-shareable` | boolean | `true` | Whether this field may be shared with downstream agents. |
| `x-awp-sensitive` | boolean | `false` | Whether this field contains sensitive data. |
| `x-awp-required` | boolean | per JSON Schema `required` | Whether this field must be present in the output. |
| `x-awp-description` | string | -- | Human-readable description for documentation and AIC generation. |

Example output contract:

```json
{
  "type": "object",
  "required": ["decision", "summary", "confidence"],
  "properties": {
    "decision": {
      "type": "string",
      "enum": ["proceed", "revise", "reject"],
      "x-awp-shareable": true,
      "x-awp-description": "The agent's decision on how to proceed."
    },
    "summary": {
      "type": "string",
      "x-awp-shareable": true
    },
    "confidence": {
      "type": "number",
      "minimum": 0.0,
      "maximum": 1.0,
      "x-awp-shareable": true,
      "x-awp-description": "Confidence score for this output."
    },
    "raw_data": {
      "type": "object",
      "x-awp-shareable": false
    }
  }
}
```

**The `confidence` field:** Per [validation rule R17](validation.md), all output schemas with `format: json` must include a `confidence` field (number, 0.0-1.0). This provides a standardized signal of output quality for downstream agents and orchestration decisions.

### `output.validation`

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `strict` | boolean | `true` | If `true`, output must exactly match the contract. If `false`, additional fields are permitted. |
| `max_retries` | integer | `3` | Number of times the runtime should re-prompt the LLM on validation failure. |
| `on_failure` | string | `"error"` | Action on persistent validation failure: `"error"`, `"warn"`, or `"passthrough"`. |

## Vision Section

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `vision.enabled` | boolean | `false` | Whether the agent accepts image inputs. |
| `vision.model` | string | -- | Vision-specific model override. If omitted, uses `model.name`. |
| `vision.supported_formats` | list | `["png", "jpg", "jpeg", "webp", "gif"]` | Accepted image formats. |
| `vision.max_images` | integer | `5` | Maximum number of images per request. |
| `vision.max_size_mb` | float | `10.0` | Maximum size per image in megabytes. |

## Preprocessor Section

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `preprocessor.enabled` | boolean | `false` | Whether data preprocessing runs before the agent. |
| `preprocessor.pipeline` | string | `"default"` | Pipeline identifier or module path. |

## Capabilities Section

The `capabilities` section configures tools, skills, data sources, and sandbox. See [Tools & Capabilities Reference](tools.md) for the full specification.

## Memory Section (Agent-Level)

Agent-level memory configuration overrides or supplements the workflow-level memory settings. See [Memory & State Reference](memory.md).

```yaml
memory:
  enabled: true
  long_term_inject: true
  long_term_max_tokens: 2000
  daily_log_enabled: true
  daily_log_auto_write: true
  search_enabled: true
```

## Agent Identity Card (AIC)

The AIC is an auto-generated summary derived from the `agent.awp.yaml` file. Runtimes should generate the AIC at load time and make it available for introspection. The AIC is informational and must not affect agent execution.

| AIC Field | Source |
|-----------|--------|
| `id` | `identity.id` |
| `role` | `identity.role` |
| `model` | `model.name` |
| `output_format` | `output.format` |
| `tools_enabled` | `capabilities.tools.enabled` |
| `tool_count` | Count of allowed tools |
| `vision_enabled` | `vision.enabled` |
| `memory_enabled` | Memory configuration |
| `skills_count` | Count of loaded skills |

## Field Reference Table

| Field Path | Type | Required | Constraints |
|------------|------|----------|-------------|
| `awp_agent` | string | Yes | Valid SemVer |
| `identity.id` | string | Yes | snake_case, 2-48 chars, `^[a-z][a-z0-9_]{0,46}[a-z0-9]$` |
| `identity.role` | string | Yes | -- |
| `identity.description` | string | Yes | -- |
| `runtime.class_name` | string | Recommended | Default: `"Agent"` |
| `runtime.strategy_folder` | string | Recommended | Default: `"workflow"` |
| `model.provider` | string | No | -- |
| `model.name` | string | Yes | Provider-specific format |
| `model.fallback` | list | No | -- |
| `model.parameters.temperature` | float | No | 0.0-2.0, default: 0.0 |
| `model.parameters.max_tokens` | integer | No | Default: 32768 |
| `model.parameters.top_p` | float | No | 0.0-1.0, default: 1.0 |
| `model.reasoning.enabled` | boolean | No | Default: `false` |
| `model.reasoning.effort` | string | No | `"low"`, `"medium"`, `"high"` |
| `model.reasoning.force` | boolean | No | Default: `false` |
| `prompt.system` | string | Yes | Inline or file reference |
| `prompt.user_template` | string | No | Supports `{{var}}` interpolation |
| `prompt.additional` | list | No | -- |
| `prompt.variables` | object | No | -- |
| `prompt.injection_order` | list | No | Recognized component names |
| `output.format` | string | Yes | `"json"`, `"text"`, `"markdown"` |
| `output.contract` | object/string | Yes (json) | JSON Schema or file path |
| `output.validation.strict` | boolean | No | Default: `true` |
| `output.validation.max_retries` | integer | No | Default: 3 |
| `output.validation.on_failure` | string | No | `"error"`, `"warn"`, `"passthrough"` |
| `vision.enabled` | boolean | No | Default: `false` |
| `vision.model` | string | No | -- |
| `vision.supported_formats` | list | No | Default: common formats |
| `vision.max_images` | integer | No | Default: 5 |
| `vision.max_size_mb` | float | No | Default: 10.0 |

## Complete Example

```yaml
awp_agent: "1.0.0"

identity:
  id: research_analyst
  role: researcher
  description: >
    Performs deep research on a given topic using web search tools,
    synthesizes findings, and produces a structured summary with
    citations and confidence scores.

runtime:
  class_name: Agent
  strategy_folder: workflow

model:
  provider: openrouter
  name: "anthropic/claude-sonnet-4"
  fallback:
    - "google/gemini-2.5-pro"
    - "qwen/qwen3-235b-a22b:free"
  parameters:
    temperature: 0.0
    max_tokens: 32768
    top_p: 1.0
  reasoning:
    enabled: true
    effort: high

prompt:
  system: "workflow/instructions/SYSTEM_PROMPT.md"
  user_template: >
    Research the following topic: {{topic}}
    Focus areas: {{focus_areas}}
  additional:
    - "workflow/prompt/00_INTRO.md"
  variables:
    topic: "${state.context.topic}"
    focus_areas: "${state.context.focus_areas}"
  injection_order:
    - system
    - skills
    - memory
    - messages
    - context
    - additional

output:
  format: json
  contract: "workflow/output_schema/output_schema.json"
  validation:
    strict: true
    max_retries: 3
    on_failure: error

vision:
  enabled: false

capabilities:
  tools:
    enabled: true
    max_calls: 20
    allowed:
      - "web.*"
      - "file.read"
      - "memory.*"
    denied:
      - "shell.*"

memory:
  enabled: true
  long_term_inject: true
  long_term_max_tokens: 2000
  daily_log_enabled: true
  daily_log_auto_write: true
  search_enabled: true
```
