# Autonomy Levels

**AWP Specification v1.0.0 — Autonomy Levels**
**Status:** Draft Standard

> **See also** — **Parent**: [spec.md](spec.md), [docs/README.md](../../../docs/README.md#concept-map) · **Non-normative explainer**: [docs/compliance.md](../../../docs/compliance.md) · **Required layers per level**: [docs/layer-model.md](../../../docs/layer-model.md) and [layers/](layers/) · **Runtime enforcement**: [docs/runtime.md](../../../docs/runtime.md) (budget envelope, completion gate chain), [docs/ORCHESTRATION_ENGINES.md](../../../docs/ORCHESTRATION_ENGINES.md) (A0–A1 → DAG engine; A2–A4 → delegation loop) · **Validation rules that scale with autonomy**: [validation-rules.md](validation-rules.md), [docs/validation.md](../../../docs/validation.md)

---

## 1. Overview

AWP defines five autonomy levels (A0–A4) that indicate the degree of autonomous behavior a workflow exhibits. Each level builds on the previous, adding requirements for additional capabilities. A workflow MUST declare its target autonomy level and MUST satisfy all requirements for that level and all levels below it.

Communication (message bus) and Memory are cross-cutting **features** available at any autonomy level; they are not level requirements.

Security and Observability are **recommended for all workflows** as cross-cutting concerns. Safety requirements scale with autonomy: A2+ requires budget controls, A3+ requires a safety envelope, and A4+ requires observability.

A conformant runtime MUST be able to validate a workflow's autonomy level by checking the requirements listed below.

> **Backward compatibility note:** The previous L0–L5 compliance level system has been replaced by A0–A4 autonomy levels. L0 Core maps to A0 Prescribed, L1 Composable maps to A1 Adaptive, and L5 Enterprise maps to A4 Self-Organizing. L2 Communicative, L3 Memorable, and L4 Observable are now cross-cutting features and concerns rather than distinct levels.

---

## 2. Level Definitions

### 2.1 A0 AWP/Prescribed

**Description:** Static DAG with predefined agents and fixed tools. The minimum viable AWP workflow.

**Requirements:**

| ID | Requirement |
|----|-------------|
| A0-1 | The workflow MUST contain a valid `workflow.awp.yaml` with a valid `awp` field (SemVer). |
| A0-2 | The `workflow` section MUST be present with `name`, `version`, and `description` fields. |
| A0-3 | The `orchestration` section MUST be present with `engine` and `graph` containing at least 1 agent node. |
| A0-4 | Every agent referenced in the graph MUST have a valid `agent.awp.yaml` with `awp_agent`, `identity`, `model.name`, `prompt.system`, and `output.format` fields. |
| A0-5 | Every agent MUST have an `output.contract` defined (either inline or as a file reference). |
| A0-6 | The graph MUST be a static DAG — all nodes and edges are predefined at design time. |

**Example use case:** A single-agent workflow that summarizes text input and produces a JSON output.

---

### 2.2 A1 AWP/Adaptive

**Description:** Conditional execution, loops, fan-out, and multi-agent DAG with state sharing. The workflow can adapt its execution path based on runtime conditions but cannot create new agents or tools.

**Requirements:** All A0 requirements, plus:

| ID | Requirement |
|----|-------------|
| A1-1 | The graph MUST contain 2 or more agent nodes. |
| A1-2 | At least one agent MUST have a non-empty `depends_on` field, establishing a DAG relationship. |
| A1-3 | The `state` section MUST be present in `workflow.awp.yaml`. |
| A1-4 | The `state.sharing` section MUST be present with a valid `strategy` field. |
| A1-5 | At least one agent SHOULD have a non-empty `share_output` field. |
| A1-6 | The workflow MAY include conditional execution, loops, or fan-out in the orchestration graph. |

**Example use case:** A research-and-write workflow where a researcher agent feeds findings to a writer agent, with conditional paths based on research quality.

---

### 2.3 A2 AWP/Delegating

**Description:** A manager agent can spawn worker agents dynamically at runtime (delegation loop). Workers are drawn from a predefined pool but instantiated on demand.

**Requirements:** All A1 requirements, plus:

| ID | Requirement |
|----|-------------|
| A2-1 | The workflow MUST define a `delegation` section or equivalent mechanism for dynamic agent spawning. |
| A2-2 | At least one agent MUST be designated as a manager capable of delegating tasks to workers. |
| A2-3 | The workflow MUST define a `budget` section with resource limits (e.g., max tokens, max time, max cost). |
| A2-4 | Delegated tasks MUST inherit or subset the manager's budget constraints. |
| A2-5 | The workflow SHOULD define a worker pool or agent template for dynamically spawned agents. |

**Example use case:** A project manager agent that breaks down a complex task and spawns specialized worker agents to handle each subtask, with budget controls.

---

### 2.4 A3 AWP/Self-Tooling

**Description:** Agents can create new tools and skills at runtime. The workflow can extend its own capabilities dynamically.

**Requirements:** All A2 requirements, plus:

| ID | Requirement |
|----|-------------|
| A3-1 | At least one agent MUST be capable of defining new tools or skills at runtime. |
| A3-2 | The workflow MUST define a `safety_envelope` section constraining what tools can be created. |
| A3-3 | Dynamically created tools MUST be validated against the safety envelope before use. |
| A3-4 | The workflow MUST log all dynamically created tools in the audit trail. |
| A3-5 | The safety envelope MUST define allowed namespaces, resource limits, and sandboxing requirements for generated tools. |

**Example use case:** A data analysis workflow where an agent discovers it needs a custom data transformation and generates a sandboxed tool to perform it.

---

### 2.5 A4 AWP/Self-Organizing

**Description:** Recursive delegation with budget distribution. Agents can spawn sub-workflows, delegate recursively, and organize themselves to accomplish goals.

**Requirements:** All A3 requirements, plus:

| ID | Requirement |
|----|-------------|
| A4-1 | The workflow MUST support recursive delegation — delegated agents MAY themselves delegate further. |
| A4-2 | Budget distribution MUST be hierarchical: each level MUST receive a subset of its parent's budget. |
| A4-3 | The workflow MUST define a maximum delegation depth. |
| A4-4 | `observability` MUST be enabled with tracing, metrics, and audit at all delegation levels. |
| A4-5 | The workflow MUST implement convergence criteria — conditions under which recursive delegation terminates. |
| A4-6 | The workflow SHOULD define `observability.health.readiness` and `observability.health.liveness` checks. |

**Example use case:** A mission-critical enterprise workflow where a top-level planner recursively delegates to specialized teams, each with their own budget, tools, and observability, terminating when quality thresholds are met.

---

## 3. Cross-Cutting Features

The following are **features** that may be used at any autonomy level. They are not requirements for any specific level but are recommended best practices.

### 3.1 Communication (Message Bus)

Available at any level. Enables agents to communicate through a message bus beyond DAG data flow.

| ID | Recommendation |
|----|----------------|
| CC-1 | The `communication` section MAY be present in `workflow.awp.yaml`. |
| CC-2 | If present, the `communication.bus` section MUST have a valid `type` field. |
| CC-3 | If present, `communication.channels` MUST contain at least 1 channel definition. |
| CC-4 | Each channel MUST have a valid `name` and `type` field. |

### 3.2 Memory

Available at any level. Enables agents to maintain persistent memory across executions.

| ID | Recommendation |
|----|----------------|
| CC-5 | The `memory` section MAY be present in `workflow.awp.yaml`. |
| CC-6 | If present, at least 1 memory tier MUST be enabled. |
| CC-7 | Agents using memory MUST have `memory.enabled: true` in their `agent.awp.yaml`. |

### 3.3 Observability

Recommended for all levels; **required** for A4.

| ID | Recommendation |
|----|----------------|
| CC-8 | The `observability` section SHOULD be present for all production workflows. |
| CC-9 | `observability.tracing` SHOULD be enabled with `enabled: true`. |
| CC-10 | `observability.metrics` SHOULD be enabled with `enabled: true`. |
| CC-11 | `observability.audit` SHOULD be enabled with `enabled: true`. |
| CC-12 | The audit trail SHOULD use `integrity: hash_chain` or `integrity: merkle_tree`. |

### 3.4 Security

Recommended for all levels; safety requirements **scale with autonomy**.

| ID | Recommendation |
|----|----------------|
| CC-13 | The `security` section SHOULD be present for all production workflows. |
| CC-14 | `security.circuit_breaker` SHOULD be configured for resilient workflows. |
| CC-15 | `security.rate_limiting` SHOULD be configured for external-facing workflows. |
| CC-16 | `security.secrets` SHOULD specify a `backend` for credential management. |

---

## 4. Autonomy Level Summary

| Level | Name | Key Capability | Min Agents | Requires | Safety |
|-------|------|---------------|-----------|----------|--------|
| A0 | AWP/Prescribed | Static DAG, fixed tools | 1 | — | — |
| A1 | AWP/Adaptive | Conditional execution, loops, fan-out, state sharing | 2 | A0 | — |
| A2 | AWP/Delegating | Manager spawns workers dynamically | 2 | A1 | Budget |
| A3 | AWP/Self-Tooling | Agents create tools/skills at runtime | 2 | A2 | Safety envelope |
| A4 | AWP/Self-Organizing | Recursive delegation, budget distribution | 2 | A3 | Observability required |

Cross-cutting features (available at all levels): Communication, Memory, Observability, Security.

---

## 5. Declaring Autonomy Level

A workflow SHOULD declare its target autonomy level in the manifest:

```yaml
awp: "1.0.0"

workflow:
  name: enterprise-research
  version: "1.0.0"
  description: "Enterprise research workflow with full AWP capabilities."
  autonomy: A4
```

The `workflow.autonomy` field is OPTIONAL. If omitted, the runtime SHOULD infer the autonomy level from the workflow's configuration.

> **Backward compatibility note:** The `workflow.conformance` field (e.g., `conformance: L5`) is deprecated but MAY be accepted by runtimes for backward compatibility. Runtimes SHOULD map legacy values as follows: L0 to A0, L1 to A1, L5 to A4.

---

## 6. Validation

A conformant runtime MUST provide a validation mechanism that:

1. Parses the workflow manifest and all agent configurations.
2. Checks all MUST-level requirements for the declared (or inferred) autonomy level.
3. Reports SHOULD-level requirements as warnings.
4. Returns a clear pass/fail result with details of any violations.

Example validation output:

```
AWP Autonomy Level Validation: enterprise-research v1.0.0
Target Level: A4 AWP/Self-Organizing

A0 AWP/Prescribed ......... PASS
  [PASS] A0-1: Valid awp field
  [PASS] A0-2: Workflow section complete
  [PASS] A0-3: Orchestration with graph
  [PASS] A0-4: All agents have valid configs
  [PASS] A0-5: All agents have output contracts
  [PASS] A0-6: Static DAG defined

A1 AWP/Adaptive ........... PASS
  [PASS] A1-1: 2+ agents in graph
  [PASS] A1-2: DAG with depends_on
  [PASS] A1-3: State section present
  [PASS] A1-4: Sharing strategy defined
  [WARN] A1-5: No share_output defined (SHOULD)

A2 AWP/Delegating ......... PASS
A3 AWP/Self-Tooling ....... PASS
A4 AWP/Self-Organizing .... PASS

Cross-cutting:
  [PASS] Communication: Message bus configured
  [PASS] Memory: 2 tiers enabled
  [PASS] Observability: Tracing + metrics + audit
  [PASS] Security: Circuit breaker + rate limiting

Result: PASS (A4 AWP/Self-Organizing)
Warnings: 1
```
