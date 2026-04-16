# Validation Rules R1-R32

## Mental Model: Four Tiers of Validation

AWP uses **four complementary tiers** of validation, each operating at a different point in the workflow lifecycle and answering a different question. They are not redundant — they catch different classes of problems and you almost always want all four enabled in production.

| Tier | When | Cost | Catches | Configured under |
|------|------|------|---------|------------------|
| **1. Deterministic schema/rule validation (R1–R32)** | Load time, before any agent runs | Free, instant | Structural bugs: missing fields, cycles, ID collisions, reserved-namespace abuse, missing output contracts, broken sandbox/codemode config, A4 max_depth termination | Built into runtime; this document |
| **2. LLM semantic validation** | Per-agent, after output is produced | 1 LLM call per agent (skippable if confidence is high) | Output that *parses* correctly but is *semantically* wrong (hallucinated facts, ignored instructions) | Implicit in delegation loop; gated by `confidence` threshold |
| **3. Critique loop** | Per-worker inside delegation loop, after a defect is suspected | LLM calls for diagnose + repair | Defects in worker output, with **targeted repair** rather than full retry; learns cross-worker patterns into a defect memory | `delegation_loop.critique` — see [critique.md](critique.md) |
| **4. Evaluation layer** | Workflow level, after the run (or step-scored during) | Multiple LLM calls + deterministic tests | Quality scoring against rubrics, deterministic assertions, budget utility, policy checks. Can trigger retry/repair across the whole workflow | `observability.evaluation` — see [evaluation.md](evaluation.md) |

**Rule of thumb:** R1–R32 reject *invalid* workflows; LLM/critique/evaluation reject *bad outputs*. The four tiers compose — a workflow that passes all R-rules can still fail evaluation, and a worker that passes critique can still produce a low evaluation score.

A separate, security-flavored validation runs whenever a worker creates a new tool at runtime: the **B1–B6 sandbox auto-repair pipeline** ([runtime-tool-generation.md](runtime-tool-generation.md)). It is not a workflow validator but a *tool* validator, and it sits between Tier 1 and Tier 2 conceptually.

This document specifies the deterministic Tier 1 rules. AWP runtimes must enforce these when loading a workflow. Each rule has a unique identifier, category, and description. Rules marked RECOMMENDED apply primarily to the Python reference implementation; other runtimes may adapt them.

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
| R25 | Capabilities | MUST | Dynamic tool namespace compliance |
| R26 | Capabilities | MUST | Dynamic tool creation requires Code Mode and workflow-level flag |
| R27 | Evaluation | MUST | Evaluation metric IDs unique and well-formed |
| R28 | Evaluation | MUST | Evaluation weights normalized and metric kinds valid |
| R29 | Evaluation | MUST | Thresholds consistent (e.g. `warn <= fail`) |
| R30 | Evaluation | MUST | `step_scores.hooks` use valid hooks; `retry_policy.actions` valid |
| R31 | Orchestration (A4) | MUST | `delegation_loop.budget.max_depth` present and >= 0 for A4 workflows |
| R32 | Orchestration (A4) | MUST | `max_depth` must not exceed the hard ceiling that guarantees termination |

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

## R25: Dynamic Tool Namespace Compliance

- **Category:** Capabilities
- **Level:** MUST
- **Description:** When an agent has `capabilities.codemode.tool_creation: true`, its `tool_creation_namespace` MUST NOT match any reserved namespace, and it MUST be listed in the workflow-level `dynamic_tools.allowed_namespaces`. Default namespace is `"dynamic"`. Prevents runtime-generated tools from shadowing built-ins or using undeclared namespaces.

## R26: Dynamic Tool Creation Requires Code Mode and Workflow Flag

- **Category:** Capabilities
- **Level:** MUST
- **Description:** When `capabilities.codemode.tool_creation: true`, both `capabilities.codemode.enabled` and workflow-level `dynamic_tools.enabled` MUST be `true`. Tool creation operates through the Code Mode SDK and requires an active `DynamicToolFactory` on the runtime.

## R27: Evaluation Metric Kind Valid

- **Category:** Evaluation
- **Level:** MUST
- **Description:** When `observability.evaluation.enabled: true`, every metric's `kind` MUST be one of the valid metric kinds (`llm_rubric`, `deterministic`, `schema`, `budget`, `policy`). Invalid kinds are rejected at load time so misconfigured evaluators cannot silently skip scoring.

## R28: Evaluation Thresholds Consistent

- **Category:** Evaluation
- **Level:** MUST
- **Description:** Evaluation thresholds (`accept`, `retry`, `fail`) MUST each lie in `[0.0, 1.0]` and MUST satisfy `accept >= retry >= fail`. Inverted or out-of-range thresholds are rejected so retry/accept decisions remain well-defined.

## R29: Evaluation Metric Weights Non-Negative

- **Category:** Evaluation
- **Level:** MUST
- **Description:** Every evaluation metric's `weight` MUST be `>= 0`, and at least one metric MUST have a strictly positive weight. Prevents degenerate aggregations where the weighted score is always zero.

## R30: Evaluation Hooks and Retry Actions Valid

- **Category:** Evaluation
- **Level:** MUST
- **Description:** `step_scores.hooks` MUST only contain valid hook names and `retry_policy.actions.below_retry` / `below_fail` MUST reference valid actions. Ensures the evaluation loop can always resolve a concrete action when a threshold is crossed.

## R31: A4 max_depth Required and Non-Negative

- **Category:** Orchestration (A4)
- **Level:** MUST
- **Description:** When `orchestration.delegation_loop.budget` is present, `max_depth` MUST be set to an integer `>= 0`. Use `max_depth: 0` to disable recursive submanager spawning, or `>= 1` to allow A4 delegation. Missing or negative values are rejected so recursion always has a finite ceiling.

> **Note on the R31 label.** The validator rule `R31` above is the *A4 max_depth gate*. A different label also called "R31" appears inside the manager prompt in `packages/awp-runtime/src/awp/data/prompts.py` as "R31 Plan-Tool-Closure" — that is an unrelated prompt-level plan validator applied to each PLAN subtask's `tool_manifest`. The two live in different layers (static YAML validation vs. runtime plan grading) and share the label only by historical accident; do not conflate them.

## R32: A4 max_depth Within Safety Ceiling

- **Category:** Orchestration (A4)
- **Level:** MUST
- **Description:** `delegation_loop.budget.max_depth` MUST NOT exceed the hard ceiling of `10`. Values `> 5` emit a warning ("most A4 workflows complete with depth <= 3"). Deep recursion makes budget reasoning and debugging intractable; a flatter decomposition is always preferred.

## Runtime Completion Gates (Tier 1.5)

In addition to the static R-rules above, the delegation-loop runner enforces a deterministic **completion-gate chain** on every manager COMPLETE decision. These gates are runtime checks (they require filesystem and result-state access) and therefore do not carry an R-label, but they are normative for conformant delegation-loop implementations. A rejection by any gate bumps the `_rejected_completions` counter (see **Completion-Retry Circuit Breaker** below) and forces another manager iteration.

| Gate | MUST/SHOULD | Description |
|------|-------------|-------------|
| `critique` | MUST | Mean critique score across the latest iteration's worker critiques MUST be `>= critique.min_score_to_complete` when the critique engine is enabled and at least one critique score exists. |
| `deliverable_presence` | MUST | Every manager-declared deliverable path (from subtask `required_outputs`, or regex-scraped from `success_criteria` / `description` anchored on `_output_dir` / `_workspace_dir`) MUST exist on disk AND be a non-empty file. On rejection, emit a `deliverable_presence` gate event with `missing: [...]`, `empty: [...]`, `source: "required_outputs" | "success_criteria"`. When no paths can be derived, the gate SHOULD emit a WARNING and skip (non-blocking fallback). |
| `placeholder` | MUST | Declared output files and the `final_result` dict MUST NOT contain placeholder strings (`TODO`, `XX%`, `???`, `your_value`, `FIXME`, etc.). Code-comment exemptions apply (e.g. `# TODO:` on a line that looks like a code comment). |
| `file` | MUST | Declared output files MUST NOT be broken placeholders (1×1 PNGs, zero-length PDFs, truncated CSVs without headers). |
| `deliverable` | SHOULD | Legacy keyword-based check: if the task text implies a file deliverable (via hint keywords like `image`, `report`, `chart`, `dataset`) and the run's `_output_dir` contains no file `>= 512` bytes, reject. Complementary to `deliverable_presence`. |
| `structural_integrity` | SHOULD | Markdown deliverables MUST pass deterministic structural checks: anchor adjacency, reference-format consistency, paragraph-duplication ratio, figure inline-ref presence. |
| `eval` | MUST when enabled | When `observability.evaluation.enabled: true`, the aggregated evaluation score MUST be `>= thresholds.retry`. Below `retry` → `retry_with_repair`; below `fail` → hard failure. |

## Plan-Loop Deterministic Transition

When the manager issues `pre_progress_plans > MAX_PRE_PROGRESS_PLANS` consecutive PLAN decisions without any worker progress (the `plan_loop` gate), the runtime MUST pick one of the following deterministic transitions:

1. **`forced_delegate`** — if the active task plan has at least one subtask with `status == "pending"`, the runner sets `state["_plan_locked"]` to a textual nudge and continues the loop. The manager MUST issue DELEGATE on the next turn.
2. **`forced_terminate`** — if the plan has no pending subtasks (all completed, failed, or skipped), the runtime MUST terminate the run with status `partial` and reason `plan_loop_stall`.

The gate event MUST record `transition: "forced_delegate" | "forced_terminate"`, `pre_progress_plans`, and `pending_subtasks` so the decision can be audited after the fact.

## Completion-Retry Circuit Breaker

The runtime MUST track a monotonically-increasing `_rejected_completions` counter. Every rejection by the completion-gate chain (`critique`, `deliverable_presence`, `placeholder`, `file`, `deliverable`, `structural_integrity`, `eval`) MUST bump the counter by 1. Any successful DELEGATE decision MUST reset the counter to 0.

When the counter reaches `budget.max_rejected_completions` (default **2**):

* If the last gate-rejection payload describes a concrete defect, the runtime MUST synthesize a repair subtask (priority `critical`, `required_outputs` derived from the defect) and force the next iteration into DELEGATE mode. The counter is reset after repair synthesis.
* If no repair can be derived, the runtime MUST terminate the run with status `partial` and reason `max_rejected_completions`.

Both paths MUST emit a `completion_circuit_breaker` gate event with the counter value and — when applicable — the synthesized `repair_subtask_id`.
