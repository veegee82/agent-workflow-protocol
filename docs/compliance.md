# Autonomy Levels

> **See also** — **Parent**: [overview.md](overview.md), [docs/README.md](README.md#concept-map) · **Sibling concepts**: [layer-model.md](layer-model.md) (which layers each level requires), [validation.md](validation.md) (rules that scale with autonomy), [architecture.md](architecture.md) (why the spectrum exists) · **Per-level runtime**: A0–A1 → `dag` engine in [ORCHESTRATION_ENGINES.md](ORCHESTRATION_ENGINES.md); A2–A4 → `delegation_loop` engine + [manager-intelligence.md](manager-intelligence.md) + [critique.md](critique.md); A3+ → [runtime-tool-generation.md](runtime-tool-generation.md); A5 (experimental, outside the 7 layers) → [outer-loop.md](outer-loop.md), [refinement.md](refinement.md) · **Budget envelope** (mandatory from A2 onward): [runtime.md](runtime.md), [orchestration.md](orchestration.md) · **Spec**: [spec/versions/1.0/compliance.md](../spec/versions/1.0/compliance.md)

## Mental Model: The Autonomy Spectrum

AWP's autonomy levels (A0–A4) form a **spectrum of control transfer from human to system**. At A0 a human spells out every step; at A4 the workflow recursively decomposes itself, spawns its own sub-workflows, and even creates the tools it needs along the way. Each level adds *one* fundamental capability and, in exchange, requires *one* additional safety mechanism. The deal is non-negotiable: you cannot adopt the capability without adopting its safety counterpart.

| Level | New capability | New safety requirement |
|-------|----------------|------------------------|
| A0 | Static DAG, fixed agents and tools | Schema validation (R1–R32) |
| A1 | Multi-agent DAG, branching, state sharing | `state.sharing` strategy |
| A2 | **Delegation loop**: manager spawns workers dynamically | **Budgets** (`max_loops`, `max_total_workers`, `max_total_tokens`, `max_wall_time`) |
| A3 | **Self-tooling**: agents create tools at runtime | **Safety envelope** + sandbox + B1–B6 tool auto-repair validation |
| A4 | **Recursive delegation**: submanagers spawn sub-workflows | **Budget reservation model**, `max_depth`, mandatory observability |

The single most important property of this spectrum is that **the safety envelope is monotone**: a child can never have a *larger* envelope than its parent. The runtime enforces this via the **reservation model** (introduced in commit `7803188`) — when a manager dispatches a worker or promotes one to a submanager, a portion of the parent's remaining budget is *reserved* for the sub-tree before it starts. The submanager inherits a strictly smaller envelope, and the runtime refuses to spawn beyond `budget.max_depth`. **The manager has no API to override the safety envelope.** Together, reservation + depth limit + wall-time + token cap give A4 workflows a **provable termination guarantee**: even an adversarial or buggy manager cannot recurse forever.

The autonomy of *deciding* is also bounded but in a softer way. From A2 onward, the manager is expected to make non-trivial choices: planning, hypothesis-diagnosis, strategy switching, and — new in recent versions — **complexity-scored auto-promotion**. When a worker faces a task whose estimated complexity exceeds a threshold, the manager autonomously promotes that worker to a submanager (A4) rather than executing it inline. This makes the A2-vs-A4 boundary a runtime decision rather than a static design choice. Every such decision is recorded in the [Decision Journal](manager-intelligence.md) and surfaced in the [observability](observability.md) trace.

Communication, memory, and observability are **cross-cutting features** available at any autonomy level — they are not levels themselves. Security and observability are cross-cutting concerns that apply to all levels (mandatory at A4).

## Level Summary

| Level | Name | Key Addition | Min Agents | Requires |
|-------|------|-------------|-----------|----------|
| A0 | AWP/Prescribed | Valid manifest + static DAG + fixed tools | 1 | -- |
| A1 | AWP/Adaptive | Conditional execution, loops, fan-out, multi-agent DAG | 2 | A0 |
| A2 | AWP/Delegating | Manager spawns workers dynamically (delegation loop) | 2 | A1 |
| A3 | AWP/Self-Tooling | Agents create tools and skills at runtime | 2 | A2 |
| A4 | AWP/Self-Organizing | Recursive delegation, budget distribution | 2 | A3 |

**Cross-cutting concerns (all levels):** Security + Observability

**Safety requirements:** A2+ requires budget controls, A3+ requires safety envelope, A4+ requires observability enabled.

## A0 AWP/Prescribed

The minimum viable AWP workflow. A static DAG with predefined agents and fixed tools.

**Requirements:**

| ID | Requirement |
|----|-------------|
| A0-1 | The workflow must contain a valid `workflow.awp.yaml` with a valid `awp` field (SemVer). |
| A0-2 | The `workflow` section must be present with `name`, `version`, and `description` fields. |
| A0-3 | The `orchestration` section must be present with `engine` and `graph` containing at least 1 agent node. |
| A0-4 | Every agent referenced in the graph must have a valid `agent.awp.yaml` with `awp_agent`, `identity`, `model.name`, `prompt.system`, and `output.format` fields. |
| A0-5 | Every agent must have an `output.contract` defined (inline or file reference). |

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

## A1 AWP/Adaptive

A multi-agent workflow with conditional execution, loops, fan-out, and data sharing between agents.

**Requirements:** All A0 requirements, plus:

| ID | Requirement |
|----|-------------|
| A1-1 | The graph must contain 2 or more agent nodes. |
| A1-2 | At least one agent must have a non-empty `depends_on` field. |
| A1-3 | The `state` section must be present in `workflow.awp.yaml`. |
| A1-4 | The `state.sharing` section must be present with a valid `strategy` field. |
| A1-5 | At least one agent should have a non-empty `share_output` field. (SHOULD) |

**Typical use case:** A research-and-write workflow where a researcher agent feeds findings to a writer agent, with conditional branching based on confidence scores.

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

## A2 AWP/Delegating

A manager agent dynamically spawns worker agents. The manager decides at runtime which workers to invoke and how to distribute tasks (delegation loop).

**Requirements:** All A1 requirements, plus:

| ID | Requirement |
|----|-------------|
| A2-1 | At least one agent must be configured as a manager with `delegation.enabled: true`. |
| A2-2 | The manager must have access to `agent.spawn` or equivalent delegation tools. |
| A2-3 | A `budget` section must be present in `workflow.awp.yaml` to constrain delegation. |
| A2-4 | The budget must specify at least `max_agents` and `max_llm_calls`. |
| A2-5 | Worker agents spawned by the manager must conform to the same output contract requirements as static agents. |

**Safety:** Budget controls are required at this level to prevent unbounded agent spawning.

**Manager intelligence at A2+:** From A2 onward the manager makes runtime decisions that the static DAG cannot express — initial planning, hypothesis-diagnosis after a worker failure, strategy switching, and **complexity-scored auto-promotion** (a worker whose task complexity exceeds a threshold is autonomously promoted to a submanager, escalating an A2 dispatch into an A4 sub-run). Every such decision is captured in the Decision Journal — see [manager-intelligence.md](manager-intelligence.md) and [observability.md](observability.md).

**Typical use case:** A project manager agent that breaks a task into subtasks and delegates each to a dynamically created specialist agent.

**Delegation loop example:**

```yaml
orchestration:
  engine: delegation_loop
  delegation_loop:
    manager: agents/project_manager
    budget:
      max_loops: 10
      max_total_workers: 15
      max_total_tokens: 500000
      max_wall_time: 300
    worker_policy:
      enforced:
        sandbox: { type: subprocess, max_memory_mb: 512 }
        forbidden_tools: ["shell.execute"]
      manager_controlled:
        - instructions
        - skills
        - tools_allowed
        - output_contract
    termination:
      enabled: true
      window: 3
      min_confidence_delta: 0.05
      action: warn_then_stop
```

## A3 AWP/Self-Tooling

Agents create new tools and skills at runtime. The workflow can extend its own capabilities dynamically.

**Requirements:** All A2 requirements, plus:

| ID | Requirement |
|----|-------------|
| A3-1 | At least one agent must have `capabilities.tool_creation.enabled: true`. |
| A3-2 | A `safety_envelope` section must be present defining allowed tool namespaces and resource limits. |
| A3-3 | Runtime-created tools must be registered in the tool registry and validated before use. |
| A3-4 | The safety envelope must specify `allowed_namespaces`, `denied_operations`, and `max_tool_count`. |
| A3-5 | All runtime-created tools must be logged in the audit trail. |

**Safety:** A safety envelope is required to constrain what tools agents can create and what operations those tools can perform.

**Typical use case:** An agent that encounters an unfamiliar API, writes an MCP tool wrapper for it, and uses the new tool to complete its task.

**Tool creation via delegation envelope:**

In the delegation loop, the manager enables tool creation per worker by setting `codemode` in the delegation envelope:

```json
{
  "worker_id": "api_integrator",
  "instructions": "Create an MCP tool for the target API and use it.",
  "codemode": { "enabled": true, "tool_creation": true },
  "tools_allowed": ["web.search", "file.read", "file.write"],
  "output_contract": {
    "required_fields": ["tool_name", "result", "confidence"]
  }
}
```

The `worker_policy.enforced.codemode.max_tools_per_worker` limit is enforced by the runtime and cannot be overridden by the manager.

## A4 AWP/Self-Organizing

Full recursive delegation with budget distribution. Agents can spawn sub-workflows that themselves spawn sub-workflows, with budget flowing down the hierarchy.

**Requirements:** All A3 requirements, plus:

| ID | Requirement |
|----|-------------|
| A4-1 | The workflow must support recursive delegation (agents spawning sub-workflows that contain managers). |
| A4-2 | Budget must be distributable: a parent agent allocates portions of its budget to child workflows. |
| A4-3 | `observability.tracing` must be enabled with `enabled: true` to track the full delegation tree. |
| A4-4 | The workflow must define a `budget.distribution` strategy (e.g., `equal`, `weighted`, `dynamic`). |
| A4-5 | Circuit breaker or equivalent safety mechanism must be enabled to prevent runaway recursion. |
| A4-6 | The delegation depth must be bounded by `budget.max_depth`. |

**Safety:** Observability is required at this level. Budget distribution, depth limits, and circuit breakers prevent runaway recursive delegation.

### A4 Termination Guarantees (Reservation Model)

A4 is the only level that needs a *formal* argument for termination, because recursive delegation could in principle run forever. AWP rules out infinite recursion through three composing constraints:

1. **Budget reservation before dispatch.** When a manager spawns a worker or promotes one to a submanager, the runtime atomically reserves a portion of the parent's remaining budget for the sub-tree. The reservation is recorded as a `budget_reserve` entry in the [Decision Journal](manager-intelligence.md) with `parent_remaining`, `child_reserved`, and `depth`.
2. **Strictly decreasing envelope.** A child's reserved envelope is always strictly smaller than its parent's remaining budget along *every* dimension (`max_loops`, `max_total_workers`, `max_total_tokens`, `max_wall_time`). The manager has no override.
3. **Hard depth cap.** `budget.max_depth` is checked before any spawn. Reaching the cap immediately fails the spawn with a `depth_exceeded` audit event.

Because each recursive step strictly reduces the available budget, and the budget is bounded above, the recursion must terminate in a finite number of steps. This is the **A4 termination guarantee**.

### A4 Sub-Run Cluster Visualization

For tracing and debugging, every submanager creates a **sub-run cluster** in the trace tree — a clustered subgraph rooted at the spawning manager span. AWP Studio renders the full delegation forest as nested clusters in the graph view ([ui.md](ui.md)), with each cluster annotated by its reserved budget envelope and its termination cause. This is the primary post-mortem tool for A4 workflows.

**Typical use case:** A mission-critical enterprise workflow where a top-level coordinator delegates to team leads, who in turn delegate to specialists, with budget and oversight flowing through the hierarchy.

## Cross-Cutting Features (Available at Any Level)

The following capabilities are not tied to any specific autonomy level. They can be used with any A0-A4 workflow:

### Communication

Agents can communicate through a message bus beyond DAG data flow. Configure the `communication` section in `workflow.awp.yaml` with bus type and channels.

See [Communication Reference](communication.md) for details.

### Memory

Agents can maintain persistent memory across executions. Configure the `memory` section in `workflow.awp.yaml` with memory tiers.

See [Memory & State Reference](memory.md) for details.

### Observability

Full observability with metrics, tracing, and audit. Configure the `observability` section in `workflow.awp.yaml`. While optional at A0-A3, observability is **required** at A4.

See [Observability Reference](observability.md) for details.

### Security

Security controls including circuit breakers, rate limiting, and access control. Configure the `security` section in `workflow.awp.yaml`.

See [Security Reference](security.md) for details.

## Declaring Autonomy Level

A workflow should declare its target autonomy level in the manifest:

```yaml
awp: "1.0.0"
workflow:
  name: enterprise-research
  version: "1.0.0"
  description: "Enterprise research workflow with full AWP autonomy."
  autonomy: A4
```

The `workflow.autonomy` field is optional. If omitted, the runtime should infer the level from the configuration.

## Validation

A conformant runtime must provide a validation mechanism that:

1. Parses the workflow manifest and all agent configurations.
2. Checks all MUST-level requirements for the declared (or inferred) autonomy level.
3. Reports SHOULD-level requirements as warnings.
4. Returns a clear pass/fail result with details of any violations.

Example validation output:

```
AWP Autonomy Validation: enterprise-research v1.0.0
Target Level: A4 AWP/Self-Organizing

A0 AWP/Prescribed ........... PASS
  [PASS] A0-1: Valid awp field
  [PASS] A0-2: Workflow section complete
  [PASS] A0-3: Orchestration with graph
  [PASS] A0-4: All agents have valid configs
  [PASS] A0-5: All agents have output contracts

A1 AWP/Adaptive ............. PASS
  [PASS] A1-1: 2+ agents in graph
  [PASS] A1-2: DAG with depends_on
  [PASS] A1-3: State section present
  [PASS] A1-4: Sharing strategy defined
  [WARN] A1-5: No share_output defined (SHOULD)

A2 AWP/Delegating ........... PASS
A3 AWP/Self-Tooling ......... PASS
A4 AWP/Self-Organizing ...... PASS

Result: PASS (A4 AWP/Self-Organizing)
Warnings: 1
```
