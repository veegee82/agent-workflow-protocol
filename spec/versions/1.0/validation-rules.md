# Validation Rules

**AWP Specification v1.0.0 — Validation Rules R1–R35**
**Status:** Draft Standard

> **See also** — **Parent**: [spec.md](spec.md), [docs/README.md](../../../docs/README.md#concept-map) · **Non-normative explainer**: [docs/validation.md](../../../docs/validation.md) · **Where each rule lands**: per-layer specs in [layers/](layers/) — [manifest](layers/00-manifest.md), [agent-identity](layers/01-agent-identity.md), [capabilities](layers/02-capabilities.md), [communication](layers/03-communication.md), [memory-state](layers/04-memory-state.md), [orchestration](layers/05-orchestration.md), [observability](layers/06-observability.md), [security](layers/security.md) · **Autonomy levels that select rules**: [compliance.md](compliance.md), [docs/compliance.md](../../../docs/compliance.md) · **Runtime-side enforcement**: [docs/runtime.md](../../../docs/runtime.md) (completion gate chain — L0/R34, R35 repair fixpoint), [docs/critique.md](../../../docs/critique.md), [docs/refinement.md](../../../docs/refinement.md) (R36)

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
| R27 | Evaluation | MUST | Evaluation metric `kind` must be valid |
| R28 | Evaluation | MUST | Evaluation thresholds in `[0,1]` and satisfy `accept >= retry >= fail` |
| R29 | Evaluation | MUST | Metric weights non-negative; at least one `> 0` |
| R30 | Evaluation | MUST | `step_scores.hooks` and `retry_policy.actions` must be valid |
| R31 | Orchestration (A4) | MUST | `delegation_loop.budget.max_depth` required and `>= 0` |
| R32 | Orchestration (A4) | MUST | `max_depth` must not exceed the hard ceiling of 10 |
| R33 | Orchestration | MUST | A phase declared `type: deterministic` MUST NOT invoke LLM tools |
| R34 | Observability | SHOULD | Every worker output SHOULD pass the Layer-0 contract chain before the LLM critique runs |
| R35 | Orchestration (repair) | MUST | Two consecutive repair outputs with `simhash` similarity `≥ 0.95` MUST abort the subtask |

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

---

## 6. Evaluation Rules (R27–R30)

### R27: Evaluation Metric Kind Valid

- **Category:** Evaluation
- **Requirement:** When `observability.evaluation.enabled: true`, every metric's `kind` MUST be one of the valid kinds (`llm_rubric`, `deterministic`, `schema`, `budget`, `policy`).
- **Rationale:** Invalid metric kinds would be silently skipped at scoring time, causing misleading pass/fail decisions.

### R28: Evaluation Thresholds Consistent

- **Category:** Evaluation
- **Requirement:** Thresholds `accept`, `retry`, `fail` MUST each lie in `[0.0, 1.0]` and MUST satisfy `accept >= retry >= fail`.
- **Rationale:** Inverted or out-of-range thresholds make the retry/accept decision undefined.

### R29: Evaluation Metric Weights Non-Negative

- **Category:** Evaluation
- **Requirement:** Every metric `weight` MUST be `>= 0` and at least one metric MUST have a strictly positive weight.
- **Rationale:** A weighted aggregation with all-zero weights always produces 0 and is never meaningful.

### R30: Evaluation Hooks and Retry Actions Valid

- **Category:** Evaluation
- **Requirement:** `step_scores.hooks` MUST only contain valid hook names and `retry_policy.actions.below_retry` / `below_fail` MUST reference valid actions.
- **Rationale:** Ensures the evaluation loop can always resolve a concrete action when a threshold is crossed.

---

## 7. A4 Recursive Delegation Rules (R31–R32)

### R31: A4 max_depth Required and Non-Negative

- **Category:** Orchestration (A4)
- **Requirement:** When `orchestration.delegation_loop.budget` is present, `max_depth` MUST be an integer `>= 0`. `max_depth: 0` disables recursive submanager spawning; `>= 1` allows A4 delegation up to that depth.
- **Rationale:** Unbounded recursion has no termination guarantee. Requiring an explicit finite depth makes the worst-case envelope (`max_depth × max_loops_per_level`) provable before execution.

> **Label clarification.** The validator rule `R31` in this document is the *static A4 max_depth gate*. A separate prompt-level label also called "R31" (Plan-Tool-Closure) appears in the manager system prompt at `packages/awp-runtime/src/awp/data/prompts.py` and grades each PLAN subtask's `tool_manifest`. The two rules live in different layers and share the label only by historical accident.

### R32: A4 max_depth Within Safety Ceiling

- **Category:** Orchestration (A4)
- **Requirement:** `delegation_loop.budget.max_depth` MUST NOT exceed the hard ceiling of 10. Values `> 5` emit a warning.
- **Rationale:** Deep recursion makes budget reasoning and debugging intractable. Most A4 workflows complete with depth `<= 3`; the ceiling guarantees the recursion tree always terminates within human-debuggable bounds.

---

## 8. Runtime Completion Gates

These gates govern the delegation-loop runner's acceptance of a manager `COMPLETE` decision. They are runtime checks (filesystem + state access required) and therefore do not carry R-labels, but they are normative for conformant delegation-loop implementations. Every gate rejection MUST:

1. Emit a `gate` event to `events.jsonl` via `trace_gate(gate, triggered=true, reason, …)`.
2. Bump `state["_rejected_completions"]` by 1 (circuit-breaker bookkeeping).
3. Force another manager iteration (do NOT accept the `COMPLETE` decision).

### Deliverable-Presence Gate

- **Category:** Orchestration (delegation_loop)
- **Requirement:** Before accepting `COMPLETE`, the runtime MUST verify that every manager-declared deliverable path exists on disk AND is a non-empty file. Required paths MUST be derived in priority order: (1) `required_outputs: list[str]` on each subtask of the active task plan, (2) path tokens scraped from each subtask's `success_criteria` / `description` via a regex anchored on `_output_dir` or `_workspace_dir`, (3) path tokens scraped from the original task string. When none of the three sources yields any path, the runtime MUST emit a WARNING and the gate MUST become a non-blocking no-op.
- **Event fields:** `missing: list[str]`, `empty: list[str]`, `source: "required_outputs" | "success_criteria"`.
- **Rationale:** Prevents the "manager hallucinated artifacts" pathology where `COMPLETE` is accepted even though the declared output files were never written.

### Completion-Retry Circuit Breaker

- **Category:** Orchestration (delegation_loop)
- **Requirement:** The runtime MUST track a counter `_rejected_completions` that is bumped by every completion-gate rejection and reset on any successful `DELEGATE`. When the counter reaches `budget.max_rejected_completions` (default **2**):
  - If the last gate-rejection payload identifies a concrete defect (missing / empty files, placeholder strings, broken output files, or structural defects), the runtime MUST synthesize a repair subtask (priority `critical`, `required_outputs` populated from the defect) and force the next iteration into `DELEGATE` mode.
  - Otherwise, the runtime MUST terminate the run with status `partial` and reason `max_rejected_completions`.
- **Event fields:** `rejected_completions: int`, `repair_subtask_id: str` (empty on terminate).
- **Rationale:** Bounds the cost of a manager that oscillates between rejected `COMPLETE` decisions without ever actually fixing the defect.

### Plan-Loop Deterministic Transition

- **Category:** Orchestration (delegation_loop)
- **Requirement:** When the manager issues more than `MAX_PRE_PROGRESS_PLANS` (default **2** in strict mode, **3** in relaxed mode) consecutive `PLAN` decisions without any worker progress, the runtime MUST pick one of two deterministic transitions:
  - **`forced_delegate`** — if the active plan has at least one subtask with `status == "pending"`, the runtime MUST inject a textual lock into `state["_plan_locked"]` and continue. The manager MUST issue `DELEGATE` on the next turn.
  - **`forced_terminate`** — if the plan has no pending subtasks, the runtime MUST terminate the run with status `partial` and reason `plan_loop_stall`.
- **Event fields:** `transition: "forced_delegate" | "forced_terminate"`, `pre_progress_plans: int`, `pending_subtasks: int`.
- **Rationale:** Eliminates the ambiguous "plan forever" failure mode by turning the `plan_loop` gate into a deterministic routing decision.

---

## 9. Deterministic Phase Type (R33)

AWP workflows MAY declare orchestration phases as either `type: llm` (default; managed by the manager/worker loop, cost in LLM tokens) or `type: deterministic` (managed by a workflow-supplied Python callable, cost in CPU-seconds). A third value `type: hybrid` is reserved for phases that emit an LLM-generated *spec* which is then executed deterministically; hybrid phases are NOT in scope for v1.0.

### R33: Deterministic Phase Purity

- **Category:** Orchestration
- **Requirement:** A phase declared `type: deterministic` MUST NOT invoke any LLM client (no `chat()`, no `complete()`, no delegation). The runtime MUST reject a `deterministic` phase whose callable imports `awp.runtime.llm` or any symbol that transitively reaches an LLM call site. Workflow authors MAY request LLM output in an earlier `type: llm` phase and pass it by file path or state variable.
- **Event fields:** none (static-analysis gate; emitted once at workflow load).
- **Rationale:** The value proposition of a deterministic phase is bit-exact reproducibility and invariant-check-ability. Admitting hidden LLM calls voids both guarantees and defeats the purpose of the type separation.
- **Implementation status (Phase 2, DAG engine):** The static check is implemented in `packages/awp-core/src/awp/validator/rules.py`; the subprocess runner, secret scrubbing, timeout enforcement, and the 6 normative invariant kinds (`file_exists`, `file_size_range`, `regex_absent`, `regex_present`, `exit_code`, `python_predicate`) are implemented under `packages/awp-runtime/src/awp/runtime/deterministic/`. Phases run in topological order of `depends_on` after all graph nodes complete, with per-phase results persisted at `output/<run_id>/phase_<id>/`. Delegation-loop integration lands in Phase 2.x.

### Schema

A deterministic phase node in `orchestration.phases` SHOULD take the form:

```yaml
- id: assemble_artifact
  type: deterministic
  depends_on: [draft]
  callable: module.path:function_name     # dotted path + colon + attr
  args:                                    # JSON-serialisable dict
    input: "${draft.deliverable}"
  timeout_s: 300                           # hard wall-clock
  invariants:                              # executed after return
    - kind: file_exists
      path: "${output}/final.bin"
    - kind: file_size_range
      path: "${output}/final.bin"
      min_bytes: 1000
      max_bytes: 10000000
    - kind: regex_absent
      path: "${output}/final.bin"
      pattern: 'TODO|XXX'
    - kind: python_predicate
      module: module.path
      function: verify_result
```

### Invariant Kinds (normative minimum set)

A conformant runtime MUST support these invariant kinds:

| Kind | Required Fields | Semantics |
|------|-----------------|-----------|
| `file_exists` | `path` | File at `path` MUST exist and be non-empty |
| `file_size_range` | `path`, `min_bytes`, `max_bytes` | `min_bytes <= size(path) <= max_bytes` |
| `regex_absent` | `path`, `pattern` | `re.search(pattern, content_of(path))` MUST be None |
| `regex_present` | `path`, `pattern` | `re.search(pattern, content_of(path))` MUST NOT be None |
| `exit_code` | `expected` | The callable's returned dict MUST have `exit_code == expected` |
| `python_predicate` | `module`, `function` | Importlib-loaded callable returns truthy |

Runtimes MAY support additional invariant kinds. Unknown kinds MUST cause the phase to fail with reason `unknown_invariant_kind`.

### Sandbox

The runtime MUST execute the callable in an isolated subprocess with:

- Timeout enforcement via `subprocess.run(timeout=...)`;
- Strictly scoped environment variables (no inheritance of `OPENROUTER_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, or any other secret the deterministic phase should not need);
- A working directory derived from the workflow's `_workspace_dir`.

### Terminal Status Contribution

A deterministic phase's outcome maps to the run's terminal status as follows:

- All invariants pass → phase contributes `complete` to the run's aggregate;
- Timeout breach → phase contributes `partial` with reason `deterministic_timeout`;
- Invariant violation → phase contributes `partial` with reason `invariant_<kind>_violated`;
- Callable raises / returns non-zero `exit_code` → phase contributes `failed` with reason `deterministic_failure`.

---

## 10. Layer 0 Output Contract (R34)

Every worker output—whether produced by an LLM worker or by a deterministic phase—SHOULD pass a chain of fast, bit-level checks (the **Layer 0 Contract**) before any LLM-based semantic critique runs. L0 checks are O(n) in output size, domain-agnostic, and carry no LLM cost.

### R34: L0 Contract Precedes Critique

- **Category:** Observability
- **Requirement:** Conformant runtimes SHOULD invoke the L0 contract chain as the first entry of the completion-gate sequence. The chain is defined in `packages/awp-runtime/src/awp/runtime/critique/l0_validator.py` and carries the following default checks (MUST be supported by conformant runtimes):
  - `no_placeholder` — rejects outputs containing `TODO`, `XXX`, `???`, `Lorem ipsum`, `TBD`, `FIXME`, `TITLE GOES HERE`, `Author Name`, `to be filled`;
  - `no_text_loop` — computes `simhash` over paragraphs of `>= 20` words; rejects if the maximum pairwise similarity exceeds `0.85`;
  - `file_size_delta` — compares this repair output's file size with the previous repair attempt; rejects if the growth factor exceeds `2.5`;
  - `no_duplicate_headings` — rejects if any Markdown `^#+ ` or LaTeX `\section{...}` header string appears twice;
  - `balanced_delimiters` — rejects unbalanced `{}` / `[]` / `()` counts (simple tokenizer, no AST);
  - `json_valid_if_claimed` — if the artifact name ends in `.json` or the tool claimed JSON output, the bytes MUST `json.loads` cleanly.
- **Event fields:** `l0_check: str`, `l0_reason: str`, `violating_path: str`.
- **Rationale:** ~90% of runtime defects observed in practice (placeholders in LLM-generated LaTeX, text-loops, repair-induced append leaks, duplicate sections from repeated-plan merges) are detectable in O(n) without any LLM inference. Running L0 before critique cuts tokens, reduces wall time, and provides strictly deterministic repair signals.

### Pluggable Extension

Workflow authors MAY supply additional checks via:

```yaml
observability:
  output_contract:
    checks: [default]
    extra:
      - name: citation_keys_resolve
        implementation: my_workflow.contracts:CitationCheck
```

An extra check MUST implement the `OutputContractCheck` protocol (in `packages/awp-runtime/src/awp/runtime/critique/contracts.py`) and MUST return within 100 ms on a 10 MB output. Extra checks are workflow-specific and MUST NOT live in the AWP core packages.

---

## 11. Repair Fixpoint Detection (R35)

### R35: Consecutive Repair Fixpoint

- **Category:** Orchestration (repair)
- **Requirement:** When a repair worker produces an output `O_n` whose `simhash` similarity to the previous repair output `O_{n-1}` is `>= 0.95`, the runtime MUST treat the subtask as a repair fixpoint and abort further repair attempts. The subtask MUST transition to `status: failed` with reason `repair_fixpoint_detected`, and the parent loop MUST either synthesise a new differently-scoped subtask or contribute the failure to the run's terminal status aggregation.
- **Event fields:** `sim: float`, `attempt: int`, `previous_output_path: str`.
- **Rationale:** A worker that returns a near-identical output across repairs is not making progress; continuing the loop burns budget without information gain. The threshold `0.95` is chosen empirically to tolerate normal LLM paraphrase while still detecting the pathological "produce the same wrong file again" pattern.

## 12. Refinement Mode (R36)

### R36: Refinement Gradient Required

- **Category:** Orchestration (refinement)
- **Requirement:** A refinement iteration SHALL have a non-empty `gradient_input.json` present in its workspace directory before the first manager call. The gradient is non-empty when at least one of the following is true:
  1. `defects` is a non-empty list,
  2. `rejected_gates` is a non-empty list,
  3. `eval_deltas` has at least one entry with a positive gap.
  If the gradient is empty, the refinement loop SHALL abort with a `"nothing to refine"` signal and SHALL NOT dispatch the iteration's agent workflow.
- **Rationale:** Prevents zero-signal reruns — a refinement call against an already-perfect run wastes budget and confuses loss attribution between policy (θ) and output (y) axes.
- **Enforcement:** Runtime: `awp.refinement.loop.RefinementLoop.run` raises `NothingToRefine` before constructing `AgentWorkflow`. `awp refine` CLI prints `"nothing to refine: <reason>"` and exits 0. R36 is a runtime rule; `awp validate` does not evaluate it.

## 13. Continuation Rules

### R37 — Continuation-Task Input Non-Emptiness

- **Category:** Orchestration (experiment hierarchy)
- **Requirement:** A task with `mode == "continuation"` **MUST** have a non-empty `inputs` array, and every entry **MUST** reference a `from_task` that exists in the same experiment and has produced a terminal run recorded in `BEST/manifest.json`. Tasks violating R37 are rejected at task-create time and **MUST NOT** produce a run.
- **Rationale:** Silent "continuation-as-seed" tasks (created with `--continuation` but no inputs, or with a dangling `from_task`) would produce a Manager prompt containing the continuation scaffolding but no actual prior material. R37 makes the invariant load-bearing and refuses the run at creation time rather than at Manager-prompt time.
- **Enforcement:** Pydantic validator on `TaskManifest` (`packages/awp-core/src/awp/models/task.py`) plus the CLI handler in `packages/awp-core/src/awp/experiment/cli_handlers.py`.
