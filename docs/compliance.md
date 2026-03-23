# Compliance Levels

AWP defines six conformance levels (L0-L5) indicating the breadth of protocol features a workflow implements. Each level builds on the previous. A workflow must satisfy all requirements for its declared level and all levels below it.

## Level Summary

| Level | Name | Key Addition | Min Agents | Requires |
|-------|------|-------------|-----------|----------|
| L0 | AWP/Core | Valid manifest + output contracts | 1 | -- |
| L1 | AWP/Composable | Multi-agent DAG + state sharing | 2 | L0 |
| L2 | AWP/Communicative | Message bus + channels | 2 | L1 |
| L3 | AWP/Memorable | Memory tiers (2+) | 2 | L1 |
| L4 | AWP/Observable | Tracing + metrics + audit | 2 | L1 |
| L5 | AWP/Enterprise | Security (circuit breaker + all below) | 2 | L0-L4 |

## L0 AWP/Core

The minimum viable AWP workflow. A single agent with a valid manifest and output contract.

**Requirements:**

| ID | Requirement |
|----|-------------|
| L0-1 | The workflow must contain a valid `workflow.awp.yaml` with a valid `awp` field (SemVer). |
| L0-2 | The `workflow` section must be present with `name`, `version`, and `description` fields. |
| L0-3 | The `orchestration` section must be present with `engine` and `graph` containing at least 1 agent node. |
| L0-4 | Every agent referenced in the graph must have a valid `agent.awp.yaml` with `awp_agent`, `identity`, `model.name`, `prompt.system`, and `output.format` fields. |
| L0-5 | Every agent must have an `output.contract` defined (inline or file reference). |

**Typical use case:** A single-agent workflow that summarizes text input and produces JSON output.

**Example:**

```yaml
awp: "1.0.0"
workflow:
  name: text-summarizer
  version: "1.0.0"
  description: "Summarizes input text."
orchestration:
  engine: dag
  graph:
    - id: summarizer
      agent: agents/summarizer
      depends_on: []
  execution:
    mode: sequential
    timeout_per_agent: 120
    timeout_total: 300
state:
  persistence:
    enabled: false
  sharing:
    strategy: full
```

## L1 AWP/Composable

A multi-agent workflow with data sharing between agents.

**Requirements:** All L0 requirements, plus:

| ID | Requirement |
|----|-------------|
| L1-1 | The graph must contain 2 or more agent nodes. |
| L1-2 | At least one agent must have a non-empty `depends_on` field. |
| L1-3 | The `state` section must be present in `workflow.awp.yaml`. |
| L1-4 | The `state.sharing` section must be present with a valid `strategy` field. |
| L1-5 | At least one agent should have a non-empty `share_output` field. (SHOULD) |

**Typical use case:** A research-and-write workflow where a researcher agent feeds findings to a writer agent.

**Example graph:**

```yaml
orchestration:
  graph:
    - id: researcher
      agent: agents/researcher
      depends_on: []
      share_output: [findings, summary]
    - id: writer
      agent: agents/writer
      depends_on: [researcher]
      share_output: [article, confidence]
```

## L2 AWP/Communicative

Agents communicate through the message bus beyond DAG data flow.

**Requirements:** All L1 requirements, plus:

| ID | Requirement |
|----|-------------|
| L2-1 | The `communication` section must be present in `workflow.awp.yaml`. |
| L2-2 | The `communication.bus` section must be present with a valid `type` field. |
| L2-3 | The `communication.channels` section must contain at least 1 channel definition. |
| L2-4 | Each channel must have a valid `name` and `type` field. |
| L2-5 | At least one agent should have `agent.send_message` or `agent.list_messages` in its allowed tools. (SHOULD) |

**Typical use case:** A workflow where a research agent broadcasts interim findings to multiple downstream agents via a topic channel.

See [Communication Reference](communication.md) for details.

## L3 AWP/Memorable

Agents maintain persistent memory across executions.

**Requirements:** All L1 requirements, plus:

| ID | Requirement |
|----|-------------|
| L3-1 | The `memory` section must be present in `workflow.awp.yaml`. |
| L3-2 | At least 2 memory tiers must be enabled (e.g., `long_term` and `working`). |
| L3-3 | At least one agent must have `memory.enabled: true` in its `agent.awp.yaml`. |
| L3-4 | The workflow should configure a `workspace_dir` for memory storage. (SHOULD) |
| L3-5 | At least one agent should have memory-related tools in its allowed tools. (SHOULD) |

**Typical use case:** A personal assistant workflow that remembers user preferences across sessions.

See [Memory & State Reference](memory.md) for details.

## L4 AWP/Observable

Full observability with metrics, tracing, and audit.

**Requirements:** All L1 requirements, plus:

| ID | Requirement |
|----|-------------|
| L4-1 | The `observability` section must be present in `workflow.awp.yaml`. |
| L4-2 | `observability.tracing` must be present with `enabled: true`. |
| L4-3 | `observability.metrics` must be present with `enabled: true`. |
| L4-4 | `observability.audit` must be present with `enabled: true`. |
| L4-5 | The audit trail should use `integrity: hash_chain` or `integrity: merkle_tree`. (SHOULD) |
| L4-6 | Logging should include `redaction` configuration for sensitive data. (SHOULD) |

**Typical use case:** A production workflow in a regulated environment requiring full traceability of all agent decisions and tool calls.

See [Observability Reference](observability.md) for details.

## L5 AWP/Enterprise

Full-featured enterprise deployment with all protocol capabilities.

**Requirements:** All L0 through L4 requirements, plus:

| ID | Requirement |
|----|-------------|
| L5-1 | The `security` section must be present in `workflow.awp.yaml`. |
| L5-2 | `security.circuit_breaker` must be present with `enabled: true`. |
| L5-3 | `security.rate_limiting` should be configured. (SHOULD) |
| L5-4 | `security.secrets` should specify a `backend`. (SHOULD) |
| L5-5 | The workflow should define `observability.health.readiness` checks. (SHOULD) |
| L5-6 | The workflow should define `observability.health.liveness` checks. (SHOULD) |

**Typical use case:** A mission-critical enterprise workflow with circuit breakers, rate limiting, secrets management, full observability, and multi-agent communication.

See [Security Reference](security.md) for details.

## Declaring Conformance

A workflow should declare its target conformance level in the manifest:

```yaml
awp: "1.0.0"
workflow:
  name: enterprise-research
  version: "1.0.0"
  description: "Enterprise research workflow with full AWP compliance."
  conformance: L5
```

The `workflow.conformance` field is optional. If omitted, the runtime should infer the level from the configuration.

## Validation

A conformant runtime must provide a validation mechanism that:

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
