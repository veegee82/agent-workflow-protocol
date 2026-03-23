# Compliance Levels

**AWP Specification v1.0.0 — Compliance**
**Status:** Draft Standard

---

## 1. Overview

AWP defines six conformance levels (L0–L5) that indicate the breadth of protocol features a workflow implements. Each level builds on the previous, adding requirements for additional capabilities. A workflow MUST declare its target conformance level and MUST satisfy all requirements for that level and all levels below it.

A conformant runtime MUST be able to validate a workflow's conformance level by checking the requirements listed below.

---

## 2. Level Definitions

### 2.1 L0 AWP/Core

**Description:** The minimum viable AWP workflow. A single agent with a valid manifest and output contract.

**Requirements:**

| ID | Requirement |
|----|-------------|
| L0-1 | The workflow MUST contain a valid `workflow.awp.yaml` with a valid `awp` field (SemVer). |
| L0-2 | The `workflow` section MUST be present with `name`, `version`, and `description` fields. |
| L0-3 | The `orchestration` section MUST be present with `engine` and `graph` containing at least 1 agent node. |
| L0-4 | Every agent referenced in the graph MUST have a valid `agent.awp.yaml` with `awp_agent`, `identity`, `model.name`, `prompt.system`, and `output.format` fields. |
| L0-5 | Every agent MUST have an `output.contract` defined (either inline or as a file reference). |

**Example use case:** A single-agent workflow that summarizes text input and produces a JSON output.

---

### 2.2 L1 AWP/Composable

**Description:** A multi-agent workflow with data sharing between agents.

**Requirements:** All L0 requirements, plus:

| ID | Requirement |
|----|-------------|
| L1-1 | The graph MUST contain 2 or more agent nodes. |
| L1-2 | At least one agent MUST have a non-empty `depends_on` field, establishing a DAG relationship. |
| L1-3 | The `state` section MUST be present in `workflow.awp.yaml`. |
| L1-4 | The `state.sharing` section MUST be present with a valid `strategy` field. |
| L1-5 | At least one agent SHOULD have a non-empty `share_output` field. |

**Example use case:** A research-and-write workflow where a researcher agent feeds findings to a writer agent.

---

### 2.3 L2 AWP/Communicative

**Description:** Agents communicate through the message bus beyond DAG data flow.

**Requirements:** All L1 requirements, plus:

| ID | Requirement |
|----|-------------|
| L2-1 | The `communication` section MUST be present in `workflow.awp.yaml`. |
| L2-2 | The `communication.bus` section MUST be present with a valid `type` field. |
| L2-3 | The `communication.channels` section MUST contain at least 1 channel definition. |
| L2-4 | Each channel MUST have a valid `name` and `type` field. |
| L2-5 | At least one agent SHOULD have `agent.send_message` or `agent.list_messages` in its allowed tools. |

**Example use case:** A workflow where a research agent broadcasts interim findings to multiple downstream agents via a topic channel, enabling dynamic collaboration.

---

### 2.4 L3 AWP/Memorable

**Description:** Agents maintain persistent memory across executions.

**Requirements:** All L1 requirements, plus:

| ID | Requirement |
|----|-------------|
| L3-1 | The `memory` section MUST be present in `workflow.awp.yaml`. |
| L3-2 | At least 2 memory tiers MUST be enabled (e.g., `long_term` and `working`). |
| L3-3 | At least one agent MUST have `memory.enabled: true` in its `agent.awp.yaml`. |
| L3-4 | The workflow SHOULD configure a `workspace_dir` for memory storage. |
| L3-5 | At least one agent SHOULD have memory-related tools (`memory.read`, `memory.write`, `memory.search`) in its allowed tools. |

**Example use case:** A personal assistant workflow that remembers user preferences and past interactions across sessions.

---

### 2.5 L4 AWP/Observable

**Description:** Full observability with metrics, tracing, and audit.

**Requirements:** All L1 requirements, plus:

| ID | Requirement |
|----|-------------|
| L4-1 | The `observability` section MUST be present in `workflow.awp.yaml`. |
| L4-2 | `observability.tracing` MUST be present with `enabled: true`. |
| L4-3 | `observability.metrics` MUST be present with `enabled: true`. |
| L4-4 | `observability.audit` MUST be present with `enabled: true`. |
| L4-5 | The audit trail SHOULD use `integrity: hash_chain` or `integrity: merkle_tree`. |
| L4-6 | Logging SHOULD include `redaction` configuration for sensitive data. |

**Example use case:** A production workflow in a regulated environment requiring full traceability of all agent decisions and tool calls.

---

### 2.6 L5 AWP/Enterprise

**Description:** Full-featured enterprise deployment with all protocol capabilities.

**Requirements:** All L0 through L4 requirements, plus:

| ID | Requirement |
|----|-------------|
| L5-1 | The `security` section MUST be present in `workflow.awp.yaml`. |
| L5-2 | `security.circuit_breaker` MUST be present with `enabled: true`. |
| L5-3 | `security.rate_limiting` SHOULD be configured. |
| L5-4 | `security.secrets` SHOULD specify a `backend`. |
| L5-5 | The workflow SHOULD define `observability.health.readiness` checks. |
| L5-6 | The workflow SHOULD define `observability.health.liveness` checks. |

**Example use case:** A mission-critical enterprise workflow with circuit breakers, rate limiting, secrets management, full observability, and multi-agent communication.

---

## 3. Conformance Level Summary

| Level | Name | Key Addition | Min Agents | Requires |
|-------|------|-------------|-----------|----------|
| L0 | AWP/Core | Valid manifest + output contracts | 1 | — |
| L1 | AWP/Composable | Multi-agent DAG + state sharing | 2 | L0 |
| L2 | AWP/Communicative | Message bus + channels | 2 | L1 |
| L3 | AWP/Memorable | Memory tiers (2+) | 2 | L1 |
| L4 | AWP/Observable | Tracing + metrics + audit | 2 | L1 |
| L5 | AWP/Enterprise | Security (circuit breaker + all below) | 2 | L0–L4 |

---

## 4. Declaring Conformance

A workflow SHOULD declare its target conformance level in the manifest:

```yaml
awp: "1.0.0"

workflow:
  name: enterprise-research
  version: "1.0.0"
  description: "Enterprise research workflow with full AWP compliance."
  conformance: L5
```

The `workflow.conformance` field is OPTIONAL. If omitted, the runtime SHOULD infer the conformance level from the workflow's configuration.

---

## 5. Validation

A conformant runtime MUST provide a validation mechanism that:

1. Parses the workflow manifest and all agent configurations.
2. Checks all MUST-level requirements for the declared (or inferred) conformance level.
3. Reports SHOULD-level requirements as warnings.
4. Returns a clear pass/fail result with details of any violations.

Example validation output:

```
AWP Conformance Validation: enterprise-research v1.0.0
Target Level: L5 AWP/Enterprise

L0 AWP/Core .............. PASS
  [PASS] L0-1: Valid awp field
  [PASS] L0-2: Workflow section complete
  [PASS] L0-3: Orchestration with graph
  [PASS] L0-4: All agents have valid configs
  [PASS] L0-5: All agents have output contracts

L1 AWP/Composable ........ PASS
  [PASS] L1-1: 2+ agents in graph
  [PASS] L1-2: DAG with depends_on
  [PASS] L1-3: State section present
  [PASS] L1-4: Sharing strategy defined
  [WARN] L1-5: No share_output defined (SHOULD)

L2 AWP/Communicative ..... PASS
L3 AWP/Memorable ......... PASS
L4 AWP/Observable ........ PASS
L5 AWP/Enterprise ........ PASS

Result: PASS (L5 AWP/Enterprise)
Warnings: 1
```
