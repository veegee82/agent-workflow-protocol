# Layer 1: Agent Identity

**AWP Specification v1.0.0 — Layer 1**
**Status:** Draft Standard

---

## 1. Overview

Layer 1 defines the identity, model configuration, prompt structure, and output contract for each agent in an AWP workflow. Every agent MUST have an `agent.awp.yaml` file located at `agents/{agent_id}/agent.awp.yaml` within the workflow directory.

---

## 2. File Name and Location

- The file MUST be named `agent.awp.yaml`.
- The file MUST be located at `agents/{agent_id}/agent.awp.yaml` where `{agent_id}` matches the `identity.id` field within the file.

---

## 3. Top-Level Field

### 3.1 `awp_agent` — Agent Schema Version

- **Type:** string (SemVer)
- **Status:** REQUIRED
- **Description:** The AWP agent schema version this file conforms to.

```yaml
awp_agent: "1.0.0"
```

---

## 4. Identity Section

The `identity` section MUST be present and declares the agent's unique identity within the workflow.

### 4.1 `identity.id`

- **Type:** string
- **Status:** REQUIRED
- **Constraints:**
  - MUST be snake_case.
  - MUST be between 2 and 48 characters.
  - MUST match the regex: `^[a-z][a-z0-9_]{0,46}[a-z0-9]$`
  - MUST be unique within the workflow.

### 4.2 `identity.role`

- **Type:** string
- **Status:** REQUIRED
- **Description:** A short human-readable label for the agent's role (e.g., "researcher", "code reviewer", "summarizer").

### 4.3 `identity.description`

- **Type:** string
- **Status:** REQUIRED
- **Description:** A detailed description of what this agent does and its purpose in the workflow.

---

## 5. Runtime Section

The `runtime` section provides implementation hints for agent instantiation.

> **Note:** These fields are implementation hints. Non-Python runtimes MAY ignore them entirely. Python implementations SHOULD use them to locate and instantiate the agent class.

### 5.1 `runtime.class_name`

- **Type:** string
- **Status:** RECOMMENDED (Python implementations)
- **Default:** `"Agent"`
- **Description:** The Python class name to import from the agent's module. Non-Python runtimes MAY ignore this field.

### 5.2 `runtime.strategy_folder`

- **Type:** string
- **Status:** RECOMMENDED (Python implementations)
- **Default:** `"workflow"`
- **Description:** The folder name within the agent directory containing workflow artifacts (prompts, schemas, preprocessors). Non-Python runtimes MAY ignore this field.

---

## 6. Model Section

The `model` section configures the LLM used by the agent.

### 6.1 `model.provider`

- **Type:** string
- **Status:** OPTIONAL
- **Description:** The LLM provider to use. If omitted, the runtime MUST use the workflow-level default provider.
- **Examples:** `"openrouter"`, `"ollama"`, `"openai"`, `"anthropic"`

### 6.2 `model.name`

- **Type:** string
- **Status:** REQUIRED
- **Description:** The model identifier. Format is provider-specific.
- **Example:** `"anthropic/claude-sonnet-4"`

### 6.3 `model.fallback`

- **Type:** list of strings
- **Status:** OPTIONAL
- **Description:** Ordered list of fallback model identifiers. If the primary model fails, the runtime SHOULD attempt each fallback in order.

### 6.4 `model.parameters`

- **Type:** object
- **Status:** OPTIONAL
- **Description:** Model inference parameters.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `temperature` | float | `0.0` | Sampling temperature. MUST be between 0.0 and 2.0. |
| `max_tokens` | integer | `4096` | Maximum tokens in the response. |
| `top_p` | float | `1.0` | Nucleus sampling threshold. MUST be between 0.0 and 1.0. |

### 6.5 `model.reasoning`

- **Type:** object
- **Status:** OPTIONAL
- **Description:** Reasoning/chain-of-thought configuration.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enabled` | boolean | `false` | Whether to enable extended reasoning. |
| `effort` | string | `"medium"` | Reasoning effort level. MUST be one of: `"low"`, `"medium"`, `"high"`. |
| `force` | boolean | `false` | If `true`, the runtime MUST request reasoning even if the model does not natively support it. |

---

## 7. Prompt Section

The `prompt` section defines how the agent's LLM prompt is constructed.

### 7.1 `prompt.system`

- **Type:** string or file reference
- **Status:** REQUIRED
- **Description:** The system prompt. MAY be an inline string or a file path relative to the agent directory (e.g., `"workflow/instructions/SYSTEM_PROMPT.md"`).

### 7.2 `prompt.user_template`

- **Type:** string or file reference
- **Status:** OPTIONAL
- **Description:** A template for the user message. Supports variable interpolation using `{{variable_name}}` syntax.

### 7.3 `prompt.additional`

- **Type:** list of strings or file references
- **Status:** OPTIONAL
- **Description:** Additional prompt fragments appended to the system prompt in order.

### 7.4 `prompt.variables`

- **Type:** object
- **Status:** OPTIONAL
- **Description:** Key-value pairs for template variable interpolation. Values MAY reference state fields using `${state.field_name}` syntax.

### 7.5 `prompt.injection_order`

- **Type:** list of strings
- **Status:** OPTIONAL
- **Default:** `["system", "skills", "memory", "messages", "context", "additional"]`
- **Description:** Defines the order in which prompt components are assembled. Each entry MUST be one of the recognized component names.

---

## 8. Output Section

The `output` section defines the expected output format and contract for the agent.

### 8.1 `output.format`

- **Type:** string
- **Status:** REQUIRED
- **Description:** The output format. MUST be one of: `"json"`, `"text"`, `"markdown"`.

### 8.2 `output.contract`

- **Type:** object or file reference
- **Status:** REQUIRED when `output.format` is `"json"`, OPTIONAL otherwise
- **Description:** A JSON Schema defining the structure of the agent's output. MAY be an inline schema or a file path to a `.json` file.

When `output.format` is `"json"`:
- The agent's output MUST validate against the contract schema.
- The runtime MUST reject outputs that fail validation.

### 8.3 `output.validation`

- **Type:** object
- **Status:** OPTIONAL
- **Description:** Additional validation rules.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `strict` | boolean | `true` | If `true`, output MUST exactly match the contract. If `false`, additional fields are permitted. |
| `max_retries` | integer | `3` | Number of times the runtime SHOULD re-prompt the LLM on validation failure. |
| `on_failure` | string | `"error"` | Action on persistent validation failure. MUST be one of: `"error"`, `"warn"`, `"passthrough"`. |

---

## 9. Vision Section

The `vision` section configures multi-modal image input capabilities.

| Field | Type | Status | Default | Description |
|-------|------|--------|---------|-------------|
| `enabled` | boolean | OPTIONAL | `false` | Whether the agent accepts image inputs. |
| `model` | string | OPTIONAL | — | Vision-specific model override. If omitted, uses `model.name`. |
| `supported_formats` | list | OPTIONAL | `["png", "jpg", "jpeg", "webp", "gif"]` | Accepted image formats. |
| `max_images` | integer | OPTIONAL | `5` | Maximum number of images per request. |
| `max_size_mb` | float | OPTIONAL | `10.0` | Maximum size per image in megabytes. |

---

## 10. Agent Identity Card (AIC)

The Agent Identity Card is an auto-generated summary of an agent's capabilities, derived from the `agent.awp.yaml` file. Runtimes SHOULD generate the AIC at load time and make it available for introspection.

The AIC MUST include:

| Field | Source |
|-------|--------|
| `id` | `identity.id` |
| `role` | `identity.role` |
| `model` | `model.name` |
| `output_format` | `output.format` |
| `tools_enabled` | `capabilities.tools.enabled` (from Layer 2) |
| `tool_count` | Count of allowed tools |
| `vision_enabled` | `vision.enabled` |
| `memory_enabled` | Derived from Layer 4 memory configuration |
| `skills_count` | Count of loaded skills |

The AIC is informational and MUST NOT affect agent execution behavior.

---

## 11. Field Reference Table

| Field Path | Type | Status | Constraints |
|------------|------|--------|-------------|
| `awp_agent` | string | REQUIRED | Valid SemVer |
| `identity.id` | string | REQUIRED | snake_case, 2–48 chars, `^[a-z][a-z0-9_]{0,46}[a-z0-9]$` |
| `identity.role` | string | REQUIRED | — |
| `identity.description` | string | REQUIRED | — |
| `runtime.class_name` | string | RECOMMENDED | Default: `"Agent"` |
| `runtime.strategy_folder` | string | RECOMMENDED | Default: `"workflow"` |
| `model.provider` | string | OPTIONAL | — |
| `model.name` | string | REQUIRED | Provider-specific format |
| `model.fallback` | list | OPTIONAL | — |
| `model.parameters.temperature` | float | OPTIONAL | 0.0–2.0, default: 0.0 |
| `model.parameters.max_tokens` | integer | OPTIONAL | Default: 32768 |
| `model.parameters.top_p` | float | OPTIONAL | 0.0–1.0, default: 1.0 |
| `model.reasoning.enabled` | boolean | OPTIONAL | Default: `false` |
| `model.reasoning.effort` | string | OPTIONAL | `"low"`, `"medium"`, `"high"` |
| `model.reasoning.force` | boolean | OPTIONAL | Default: `false` |
| `prompt.system` | string | REQUIRED | Inline or file reference |
| `prompt.user_template` | string | OPTIONAL | Supports `{{var}}` interpolation |
| `prompt.additional` | list | OPTIONAL | — |
| `prompt.variables` | object | OPTIONAL | — |
| `prompt.injection_order` | list | OPTIONAL | Recognized component names |
| `output.format` | string | REQUIRED | `"json"`, `"text"`, `"markdown"` |
| `output.contract` | object/string | REQUIRED (json) | JSON Schema or file path |
| `output.validation.strict` | boolean | OPTIONAL | Default: `true` |
| `output.validation.max_retries` | integer | OPTIONAL | Default: 3 |
| `output.validation.on_failure` | string | OPTIONAL | `"error"`, `"warn"`, `"passthrough"` |
| `vision.enabled` | boolean | OPTIONAL | Default: `false` |
| `vision.model` | string | OPTIONAL | — |
| `vision.supported_formats` | list | OPTIONAL | Default: common image formats |
| `vision.max_images` | integer | OPTIONAL | Default: 5 |
| `vision.max_size_mb` | float | OPTIONAL | Default: 10.0 |

---

## 12. Complete Example

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
    force: false

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
```
