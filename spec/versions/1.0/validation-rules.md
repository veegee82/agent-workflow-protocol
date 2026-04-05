# Validation Rules

**AWP Specification v1.0.0 — Validation Rules R1–R30**
**Status:** Draft Standard

---

## 1. Overview

This document defines the validation rules that AWP runtimes MUST enforce when loading a workflow. Each rule has a unique identifier, category, description using RFC 2119 language, rationale, and examples.

---

## 2. Rules

### R1: Valid AWP Version

- **Category:** Manifest
- **Requirement:** The `awp` field in `workflow.awp.yaml` MUST be a valid Semantic Versioning 2.0.0 string.
- **Rationale:** The protocol version is essential for compatibility checking and forward/backward compatibility.

**Valid:**
```yaml
awp: "1.0.0"
```

**Invalid:**
```yaml
awp: "1.0"
```
```yaml
awp: "v1.0.0"
```
```yaml
awp: 1
```

---

### R2: Workflow Name Format

- **Category:** Manifest
- **Requirement:** The `workflow.name` field MUST match the regex `^[a-z][a-z0-9_-]{0,62}[a-z0-9]$` (kebab-case, 2–64 characters).
- **Rationale:** Consistent naming enables reliable file system paths, API endpoints, and registry lookups.

**Valid:**
```yaml
workflow:
  name: research-and-write
```
```yaml
workflow:
  name: my_workflow_v2
```

**Invalid:**
```yaml
workflow:
  name: Research-And-Write
```
```yaml
workflow:
  name: a
```
```yaml
workflow:
  name: my-workflow-
```

---

### R3: Agent Class Name Convention

- **Category:** Agent Identity
- **Requirement:** Python implementations SHOULD use a class named `Agent` (specified in `runtime.class_name`). Non-Python runtimes MAY use any class name.
- **Status:** RECOMMENDED (Python reference convention), not REQUIRED.
- **Rationale:** A consistent class name simplifies dynamic loading in the Python reference implementation, but imposing this on all runtimes would be unnecessarily restrictive.

**Valid (Python):**
```yaml
runtime:
  class_name: Agent
```

**Valid (non-Python or custom):**
```yaml
runtime:
  class_name: CustomResearchAgent
```

---

### R4: Agent Identity Consistency

- **Category:** Agent Identity
- **Requirement:** In Python implementations, the `self.name` property SHOULD return the same string as `identity.id`. Non-Python runtimes MAY use any mechanism to associate the agent instance with its declared identity.
- **Status:** RECOMMENDED (Python reference convention), not REQUIRED.
- **Rationale:** Consistency between the configuration and the runtime instance prevents identity mismatches in state and logging, but the enforcement mechanism is implementation-specific.

**Valid (Python):**
```python
class Agent(BaseAgent):
    @property
    def name(self):
        return "research_analyst"  # Matches identity.id
```

**Valid (any runtime):**
```yaml
identity:
  id: research_analyst
```
The runtime ensures the agent instance is associated with `research_analyst` through its own mechanism.

---

### R5: Agent ID Uniqueness

- **Category:** Orchestration
- **Requirement:** Every `id` in the `orchestration.graph` MUST be unique within the workflow.
- **Rationale:** Duplicate agent IDs cause ambiguous state references and unpredictable execution.

**Valid:**
```yaml
orchestration:
  graph:
    - id: researcher
      agent: agents/researcher
    - id: writer
      agent: agents/writer
```

**Invalid:**
```yaml
orchestration:
  graph:
    - id: researcher
      agent: agents/researcher
    - id: researcher
      agent: agents/another_researcher
```

---

### R6: DAG Acyclicity

- **Category:** Orchestration
- **Requirement:** The `orchestration.graph` MUST form a Directed Acyclic Graph. Cycles MUST cause a validation error.
- **Rationale:** Cycles in the execution graph cause infinite loops and prevent topological sorting.

**Valid:**
```yaml
orchestration:
  graph:
    - id: a
      depends_on: []
    - id: b
      depends_on: [a]
    - id: c
      depends_on: [b]
```

**Invalid:**
```yaml
orchestration:
  graph:
    - id: a
      depends_on: [c]
    - id: b
      depends_on: [a]
    - id: c
      depends_on: [b]
```

---

### R7: Dependency Resolution

- **Category:** Orchestration
- **Requirement:** Every entry in an agent's `depends_on` list MUST reference a valid `id` in the `orchestration.graph`.
- **Rationale:** Unresolvable dependencies prevent the graph from being executed.

**Valid:**
```yaml
orchestration:
  graph:
    - id: researcher
      depends_on: []
    - id: writer
      depends_on: [researcher]
```

**Invalid:**
```yaml
orchestration:
  graph:
    - id: writer
      depends_on: [nonexistent_agent]
```

---

### R8: Agent Configuration File Existence

- **Category:** File Structure
- **Requirement:** Every agent referenced in the `orchestration.graph` MUST have a corresponding `agent.awp.yaml` file at `agents/{agent_id}/agent.awp.yaml`.
- **Rationale:** Without a configuration file, the runtime cannot instantiate the agent.

**Valid:**
```
my-workflow/
├── workflow.awp.yaml          # graph references "researcher"
└── agents/
    └── researcher/
        └── agent.awp.yaml     # exists
```

**Invalid:**
```
my-workflow/
├── workflow.awp.yaml          # graph references "researcher"
└── agents/                    # no researcher directory
```

---

### R9: Output Contract Presence

- **Category:** Agent Identity
- **Requirement:** Every agent MUST have an `output.contract` defined. When `output.format` is `"json"`, the contract MUST be a valid JSON Schema.
- **Rationale:** Output contracts enable state sharing validation and downstream agent type safety.

**Valid:**
```yaml
output:
  format: json
  contract:
    type: object
    required: [decision, summary]
    properties:
      decision:
        type: string
      summary:
        type: string
```

**Invalid:**
```yaml
output:
  format: json
  # no contract defined
```

---

### R10: Tool Namespace Reservation

- **Category:** Capabilities
- **Requirement:** Custom tools MUST NOT use reserved namespaces (web, http, file, shell, agent, memory, arithmetic, numpy, matplot, pandas, doc, sklearn).
- **Rationale:** Reserved namespaces prevent collisions with built-in tools and ensure consistent tool identity.

**Valid:**
```python
@app.tool("myns.custom_action")
def custom_action():
    pass
```

**Invalid:**
```python
@app.tool("web.custom_search")
def custom_search():
    pass
```

---

### R11: Tool Name Uniqueness

- **Category:** Capabilities
- **Requirement:** All tool FQNs within a workflow MUST be unique. Duplicate tool names MUST cause a validation error.
- **Rationale:** Duplicate names cause ambiguous tool resolution.

**Valid:**
```yaml
# Two distinct tools
myns.action_a
myns.action_b
```

**Invalid:**
```yaml
# Same FQN registered twice
myns.action_a  (from module_1.py)
myns.action_a  (from module_2.py)
```

---

### R12: Agent ID Format

- **Category:** Agent Identity
- **Requirement:** The `identity.id` field MUST match the regex `^[a-z][a-z0-9_]{0,46}[a-z0-9]$` (snake_case, 2–48 characters).
- **Rationale:** Consistent agent IDs enable reliable state key references and file system paths.

**Valid:**
```yaml
identity:
  id: research_analyst
```
```yaml
identity:
  id: a1
```

**Invalid:**
```yaml
identity:
  id: Research_Analyst
```
```yaml
identity:
  id: r
```
```yaml
identity:
  id: research-analyst
```

---

### R13: State Reserved Keys

- **Category:** Memory & State
- **Requirement:** Agents MUST NOT write to reserved state keys: `_meta`, `_errors`, `_trace`, `_workflow`.
- **Rationale:** Reserved keys are managed by the runtime for internal bookkeeping.

**Valid:**
```python
state["research_analyst"] = {"findings": [...]}
```

**Invalid:**
```python
state["_meta"] = {"custom": "data"}
```

---

### R14: Sensitive Field Redaction

- **Category:** Security
- **Requirement:** Fields listed in `state.sharing.sensitive_fields` and environment variables with `sensitive: true` MUST NOT appear in any log output, metric label, span attribute, or audit entry.
- **Rationale:** Preventing sensitive data leakage is a fundamental security requirement.

**Valid:**
```yaml
state:
  sharing:
    sensitive_fields:
      - api_credentials
# Runtime redacts "api_credentials" from all output
```

**Invalid:**
```
# Log entry contains: api_credentials=sk-abc123...
```

---

### R15: Channel Schema Validation

- **Category:** Communication
- **Requirement:** When a channel defines a `schema`, the runtime MUST validate message `content` against the schema before delivery. Messages that fail validation MUST be rejected.
- **Rationale:** Schema validation prevents malformed messages from corrupting downstream agent state.

**Valid:**
```json
{
  "content": {"topic": "quantum computing", "findings": []}
}
```
(Matches the channel schema requiring `topic` and `findings`.)

**Invalid:**
```json
{
  "content": {"unrelated_field": 42}
}
```
(Missing required fields per channel schema.)

---

### R16: Sharing Strategy Enforcement

- **Category:** Memory & State
- **Requirement:** The runtime MUST enforce the declared `state.sharing.strategy`. Under `selective`, agents MUST NOT access fields not listed in `share_output` or sharing rules. Under `isolated`, agents MUST NOT access other agents' state.
- **Rationale:** State isolation prevents unintended data dependencies and ensures predictable agent behavior.

**Valid (selective):**
```yaml
# Agent "writer" can access researcher's "findings" and "summary"
state:
  sharing:
    strategy: selective
orchestration:
  graph:
    - id: researcher
      share_output: [findings, summary]
```

**Invalid (selective):**
```python
# Agent "writer" reads researcher's "raw_data" which is not in share_output
data = state["researcher"]["raw_data"]
```

---

### R17: Timeout Enforcement

- **Category:** Orchestration
- **Requirement:** The runtime MUST enforce `timeout_per_agent` and `timeout_total` limits. When a timeout expires, the runtime MUST terminate the agent's execution and apply the configured `on_failure` strategy.
- **Rationale:** Unbounded execution prevents workflow completion and wastes resources.

**Valid:**
```yaml
orchestration:
  execution:
    timeout_per_agent: 120
    timeout_total: 600
```

**Invalid (runtime behavior):**
```
# Agent runs for 300 seconds despite timeout_per_agent: 120
# Runtime does not terminate the agent
```

---

### R18: Audit Hash Chain Integrity

- **Category:** Observability
- **Requirement:** When `audit.integrity` is `"hash_chain"`, each audit entry MUST include a `prev_hash` field containing the hash of the previous entry. The first entry MUST have `prev_hash` set to a zero hash.
- **Rationale:** Hash-chain integrity provides tamper-evident logging for compliance and forensic analysis.

**Valid:**
```json
[
  {"id": 1, "event": "workflow.start", "prev_hash": "0000000000000000000000000000000000000000000000000000000000000000", "hash": "a1b2c3..."},
  {"id": 2, "event": "agent.start", "prev_hash": "a1b2c3...", "hash": "d4e5f6..."}
]
```

**Invalid:**
```json
[
  {"id": 1, "event": "workflow.start", "hash": "a1b2c3..."},
  {"id": 2, "event": "agent.start", "hash": "d4e5f6..."}
]
```
(Missing `prev_hash` field.)

---

## 3. Rule Summary

| Rule | Category | Level | Summary |
|------|----------|-------|---------|
| R1 | Manifest | MUST | Valid SemVer in `awp` field |
| R2 | Manifest | MUST | Workflow name matches regex |
| R3 | Agent Identity | RECOMMENDED | Python class named `Agent` |
| R4 | Agent Identity | RECOMMENDED | `self.name` matches `identity.id` (Python) |
| R5 | Orchestration | MUST | Unique agent IDs |
| R6 | Orchestration | MUST | DAG has no cycles |
| R7 | Orchestration | MUST | All dependencies resolve |
| R8 | File Structure | MUST | Agent config files exist |
| R9 | Agent Identity | MUST | Output contract present |
| R10 | Capabilities | MUST | No reserved namespace collisions |
| R11 | Capabilities | MUST | Unique tool FQNs |
| R12 | Agent Identity | MUST | Agent ID matches regex |
| R13 | Memory & State | MUST | No writes to reserved keys |
| R14 | Security | MUST | Sensitive fields redacted |
| R15 | Communication | MUST | Channel schema validated |
| R16 | Memory & State | MUST | Sharing strategy enforced |
| R17 | Orchestration | MUST | Timeouts enforced |
| R18 | Observability | MUST | Audit hash chain integrity |
| R19 | Capabilities | MUST | Code Mode requires tools enabled |
| R20 | Capabilities | MUST | Code Mode requires sandbox (not `none`) |
| R21 | Capabilities | MUST | Code Mode language is valid |
| R22 | Capabilities | MUST | Explicit SDK surface has tools |
| R23 | Capabilities | MUST | SDK excludes reference valid tools |
| R24 | Capabilities | MUST | Isolate sandbox requires network config |
| CT10 | Custom Tools | MUST | Code Mode tools must be async |
| R25 | Capabilities | MUST | Dynamic tool namespace not reserved and in allowed list |
| R26 | Capabilities | MUST | Dynamic tool creation requires Code Mode and workflow flag |

---

## 4. Code Mode & Sandbox Rules (R19–R24, CT10)

### R19: Code Mode Requires Tools Enabled

- **Category:** Capabilities
- **Requirement:** If `capabilities.codemode.enabled` is `true`, then `capabilities.tools.enabled` MUST be `true`.
- **Rationale:** Code Mode generates an SDK from the allowed tools. Without tools enabled, the SDK would be empty.

### R20: Code Mode Requires Sandbox

- **Category:** Capabilities
- **Requirement:** If `capabilities.codemode.enabled` is `true`, then `capabilities.sandbox.type` MUST be set and MUST NOT be `"none"`.
- **Rationale:** Agent-generated code MUST run in a sandbox for security. Executing untrusted LLM-generated code without isolation is unsafe.

### R21: Code Mode Language Validation

- **Category:** Capabilities
- **Requirement:** `capabilities.codemode.language` MUST be one of: `"typescript"`, `"python"`, `"javascript"`.
- **Rationale:** The runtime must know which language the generated SDK and agent code use.

### R22: Explicit SDK Surface Must Have Tools

- **Category:** Capabilities
- **Requirement:** If `capabilities.codemode.sdk_surface.mode` is `"explicit"`, then `capabilities.codemode.sdk_surface.include` MUST contain at least one tool FQN.
- **Rationale:** An explicit SDK surface with zero tools would generate an empty SDK.

### R23: SDK Excludes Must Reference Valid Tools

- **Category:** Capabilities
- **Requirement:** Every entry in `capabilities.codemode.sdk_surface.exclude` MUST match at least one tool in `capabilities.tools.allowed`.
- **Rationale:** Excluding a tool that is not allowed is a configuration error.

### R24: Isolate Sandbox Requires Network Config

- **Category:** Capabilities
- **Requirement:** If `capabilities.sandbox.type` is `"isolate"`, the `capabilities.sandbox.network` section MUST be present with at least `network.enabled` defined.
- **Rationale:** V8 isolates have configurable network access. The default for isolates SHOULD be `enabled: false` (no network) for security.

### CT10: Code Mode Custom Tools Must Be Async

- **Category:** Custom Tools
- **Requirement:** Custom tools used with Code Mode (`codemode.enabled: true`) MUST be async/Promise-based (or use `async def` in Python).
- **Rationale:** The Code Mode SDK exposes all tools as async methods. Synchronous tools would break the async execution model.

---

## 5. Dynamic Tool Creation Rules (R25–R26)

### R25: Dynamic Tool Namespace Compliance

- **Category:** Capabilities
- **Requirement:** If `capabilities.codemode.tool_creation` is `true`, the `tool_creation_namespace` MUST NOT match any reserved namespace (web, http, file, shell, agent, memory, arithmetic, numpy, matplot, pandas, doc, sklearn). The `tool_creation_namespace` MUST also be listed in the workflow's `dynamic_tools.allowed_namespaces`. The runtime MUST validate this at configuration parse time.
- **Rationale:** Dynamic tool namespaces must not collide with built-in tools and must be explicitly approved at the workflow level.

**Valid:**
```yaml
# workflow.awp.yaml
dynamic_tools:
  enabled: true
  allowed_namespaces: ["scoring", "transform"]

# agent.awp.yaml
capabilities:
  codemode:
    tool_creation: true
    tool_creation_namespace: "scoring"  # In allowed_namespaces, not reserved
```

**Invalid:**
```yaml
# agent.awp.yaml
capabilities:
  codemode:
    tool_creation: true
    tool_creation_namespace: "web"  # Reserved namespace
```
```yaml
# tool_creation_namespace: "custom" but workflow allows only ["scoring"]
```

### R26: Dynamic Tool Creation Requires Code Mode

- **Category:** Capabilities
- **Requirement:** If `capabilities.codemode.tool_creation` is `true`, then `capabilities.codemode.enabled` MUST also be `true`. Additionally, `dynamic_tools.enabled` MUST be `true` in `workflow.awp.yaml`.
- **Rationale:** Dynamic tool creation operates through the Code Mode SDK. Without Code Mode enabled, the `sdk.tools.create()` method is unavailable. Without the workflow-level flag, the runtime has no `DynamicToolFactory` instance.

**Valid:**
```yaml
# workflow.awp.yaml
dynamic_tools:
  enabled: true

# agent.awp.yaml
capabilities:
  codemode:
    enabled: true
    tool_creation: true
```

**Invalid:**
```yaml
capabilities:
  codemode:
    enabled: false
    tool_creation: true  # Code Mode is disabled
```
```yaml
# workflow.awp.yaml has no dynamic_tools section or dynamic_tools.enabled: false
# agent.awp.yaml has tool_creation: true
```
