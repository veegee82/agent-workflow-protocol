# Validation Rules R1-R24

AWP runtimes must enforce these validation rules when loading a workflow. Each rule has a unique identifier, category, and description. Rules marked RECOMMENDED apply primarily to the Python reference implementation; other runtimes may adapt them.

## Rule Summary

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
| R20 | Capabilities | MUST | Code Mode requires sandbox |
| R21 | Capabilities | MUST | Code Mode language is valid |
| R22 | Capabilities | MUST | Explicit SDK surface has tools |
| R23 | Capabilities | MUST | SDK excludes reference valid tools |
| R24 | Capabilities | MUST | Isolate sandbox requires network config |

## R1: Valid AWP Version

- **Category:** Manifest
- **Level:** MUST
- **Description:** The `awp` field in `workflow.awp.yaml` must be a valid Semantic Versioning 2.0.0 string.

**Valid:**
```yaml
awp: "1.0.0"
```

**Invalid:**
```yaml
awp: "1.0"      # Missing patch version
awp: "v1.0.0"   # Prefix not allowed
awp: 1           # Not a string
```

## R2: Workflow Name Format

- **Category:** Manifest
- **Level:** MUST
- **Description:** The `workflow.name` field must match `^[a-z][a-z0-9_-]{0,62}[a-z0-9]$` (kebab-case, 2-64 characters).

**Valid:**
```yaml
workflow:
  name: research-and-write
  name: my_workflow_v2
```

**Invalid:**
```yaml
workflow:
  name: Research-And-Write   # Uppercase
  name: a                    # Too short
  name: my-workflow-          # Trailing hyphen
```

## R3: Agent Class Name Convention

- **Category:** Agent Identity
- **Level:** RECOMMENDED (Python convention)
- **Description:** Python implementations should use a class named `Agent` (specified in `runtime.class_name`). Non-Python runtimes may use any class name.

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

## R4: Agent Identity Consistency

- **Category:** Agent Identity
- **Level:** RECOMMENDED (Python convention)
- **Description:** In Python implementations, the `self.name` property should return the same string as `identity.id`. Non-Python runtimes may use any mechanism to associate the agent instance with its declared identity.

**Valid (Python):**
```python
class Agent(AWPAgent):
    @property
    def name(self):
        return "research_analyst"  # Matches identity.id
```

## R5: Agent ID Uniqueness

- **Category:** Orchestration
- **Level:** MUST
- **Description:** Every `id` in `orchestration.graph` must be unique within the workflow.

**Valid:**
```yaml
orchestration:
  graph:
    - id: researcher
    - id: writer
```

**Invalid:**
```yaml
orchestration:
  graph:
    - id: researcher
    - id: researcher    # Duplicate
```

## R6: DAG Acyclicity

- **Category:** Orchestration
- **Level:** MUST
- **Description:** The `orchestration.graph` must form a Directed Acyclic Graph. Cycles must cause a validation error.

**Valid:**
```yaml
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
graph:
  - id: a
    depends_on: [c]
  - id: b
    depends_on: [a]
  - id: c
    depends_on: [b]    # Cycle: a -> c -> b -> a
```

## R7: Dependency Resolution

- **Category:** Orchestration
- **Level:** MUST
- **Description:** Every entry in `depends_on` must reference a valid `id` in the graph.

**Invalid:**
```yaml
graph:
  - id: writer
    depends_on: [nonexistent_agent]
```

## R8: Agent Configuration File Existence

- **Category:** File Structure
- **Level:** MUST
- **Description:** Every agent referenced in the graph must have a corresponding `agent.awp.yaml` file at `agents/{agent_id}/agent.awp.yaml`.

## R9: Output Contract Presence

- **Category:** Agent Identity
- **Level:** MUST
- **Description:** Every agent must have an `output.contract` defined. When `output.format` is `"json"`, the contract must be a valid JSON Schema.

**Valid:**
```yaml
output:
  format: json
  contract:
    type: object
    required: [decision, summary, confidence]
    properties:
      decision:
        type: string
      summary:
        type: string
      confidence:
        type: number
```

**Invalid:**
```yaml
output:
  format: json
  # No contract defined
```

## R10: Tool Namespace Reservation

- **Category:** Capabilities
- **Level:** MUST
- **Description:** Custom tools must not use reserved namespaces: `web`, `http`, `file`, `shell`, `agent`, `memory`, `arithmetic`, `numpy`, `matplot`, `pandas`, `doc`, `sklearn`.

**Valid:**
```python
@app.tool("myns.custom_action")
```

**Invalid:**
```python
@app.tool("web.custom_search")    # "web" is reserved
```

## R11: Tool Name Uniqueness

- **Category:** Capabilities
- **Level:** MUST
- **Description:** All tool FQNs within a workflow must be unique. Duplicate tool names must cause a validation error.

## R12: Agent ID Format

- **Category:** Agent Identity
- **Level:** MUST
- **Description:** The `identity.id` field must match `^[a-z][a-z0-9_]{0,46}[a-z0-9]$` (snake_case, 2-48 characters).

**Valid:**
```yaml
identity:
  id: research_analyst
  id: a1
```

**Invalid:**
```yaml
identity:
  id: Research_Analyst    # Uppercase
  id: r                   # Too short
  id: research-analyst    # Hyphens not allowed
```

## R13: State Reserved Keys

- **Category:** Memory & State
- **Level:** MUST
- **Description:** Agents must not write to reserved state keys: `_meta`, `_errors`, `_trace`, `_workflow`.

**Valid:**
```python
state["research_analyst"] = {"findings": [...]}
```

**Invalid:**
```python
state["_meta"] = {"custom": "data"}
```

## R14: Sensitive Field Redaction

- **Category:** Security
- **Level:** MUST
- **Description:** Fields listed in `state.sharing.sensitive_fields` and environment variables with `sensitive: true` must not appear in any log output, metric label, span attribute, or audit entry.

See [Security Reference](security.md) for details.

## R15: Channel Schema Validation

- **Category:** Communication
- **Level:** MUST
- **Description:** When a channel defines a `schema`, the runtime must validate message `content` against the schema before delivery. Messages that fail validation must be rejected.

See [Communication Reference](communication.md) for details.

## R16: Sharing Strategy Enforcement

- **Category:** Memory & State
- **Level:** MUST
- **Description:** The runtime must enforce the declared `state.sharing.strategy`. Under `selective`, agents must not access fields not listed in `share_output` or sharing rules. Under `isolated`, agents must not access other agents' state.

See [Memory & State Reference](memory.md) for details.

## R17: Timeout Enforcement

- **Category:** Orchestration
- **Level:** MUST
- **Description:** The runtime must enforce `timeout_per_agent` and `timeout_total` limits. When a timeout expires, the runtime must terminate the agent's execution and apply the configured `on_failure` strategy.

See [Orchestration Reference](orchestration.md) for details.

## R18: Audit Hash Chain Integrity

- **Category:** Observability
- **Level:** MUST
- **Description:** When `audit.integrity` is `"hash_chain"`, each audit entry must include a `prev_hash` field containing the hash of the previous entry. The first entry must have `prev_hash` set to a zero hash.

**Valid:**
```json
[
  {"id": 1, "event": "workflow.start", "prev_hash": "000...000", "hash": "a1b2c3..."},
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

See [Observability Reference](observability.md) for details.

## R19: Code Mode Requires Tools Enabled

- **Category:** Capabilities
- **Level:** MUST
- **Description:** If `capabilities.codemode.enabled` is `true`, then `capabilities.tools.enabled` MUST be `true`. Code Mode generates an SDK from the allowed tools.

## R20: Code Mode Requires Sandbox

- **Category:** Capabilities
- **Level:** MUST
- **Description:** If `capabilities.codemode.enabled` is `true`, then `capabilities.sandbox.type` MUST be set and MUST NOT be `"none"`.

## R21: Code Mode Language Validation

- **Category:** Capabilities
- **Level:** MUST
- **Description:** `capabilities.codemode.language` MUST be one of: `"typescript"`, `"python"`, `"javascript"`.

## R22: Explicit SDK Surface Must Have Tools

- **Category:** Capabilities
- **Level:** MUST
- **Description:** If `capabilities.codemode.sdk_surface.mode` is `"explicit"`, then `capabilities.codemode.sdk_surface.include` MUST contain at least one tool FQN.

## R23: SDK Excludes Must Reference Valid Tools

- **Category:** Capabilities
- **Level:** MUST
- **Description:** Every entry in `capabilities.codemode.sdk_surface.exclude` MUST match at least one tool in `capabilities.tools.allowed`.

## R24: Isolate Sandbox Requires Network Config

- **Category:** Capabilities
- **Level:** MUST
- **Description:** If `capabilities.sandbox.type` is `"isolate"`, the `capabilities.sandbox.network` section MUST be present with at least `network.enabled` defined.
