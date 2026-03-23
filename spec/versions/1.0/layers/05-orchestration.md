# Layer 5: Orchestration

**AWP Specification v1.0.0 — Layer 5**
**Status:** Draft Standard

---

## 1. Overview

Layer 5 defines the orchestration engine, execution graph, execution modes, control flow, error handling, and retry strategies for AWP workflows. Orchestration is configured in the `orchestration` section of `workflow.awp.yaml`.

---

## 2. Engine

### 2.1 `orchestration.engine`

- **Type:** string
- **Status:** REQUIRED
- **Description:** The orchestration engine type.
- **Allowed values:** `"dag"`

Currently, `dag` (Directed Acyclic Graph) is the only defined engine. Future AWP versions MAY introduce additional engine types.

```yaml
orchestration:
  engine: dag
```

---

## 3. Graph Nodes

The `orchestration.graph` section defines the agent execution graph as a list of node definitions.

### 3.1 Node Fields

| Field | Type | Status | Default | Description |
|-------|------|--------|---------|-------------|
| `id` | string | REQUIRED | — | Unique node identifier. MUST match an agent's `identity.id` (AgentId format). |
| `agent` | string | REQUIRED | — | Path to the agent directory relative to the workflow root. |
| `enabled` | boolean | OPTIONAL | `true` | Whether this node is active. Disabled nodes are skipped. |
| `depends_on` | list | OPTIONAL | `[]` | Dependencies. See Section 3.2. |
| `share_input` | list | OPTIONAL | `[]` | State fields to inject from the workflow context into this agent's input. |
| `share_output` | list | OPTIONAL | `[]` | Output fields this agent exposes to downstream agents. |
| `description` | string | OPTIONAL | — | Human-readable description of this node's role in the graph. |
| `on_failure` | string | OPTIONAL | `"stop"` | Action on agent failure. MUST be one of: `"stop"`, `"continue"`, `"retry"`, `"skip"`. |
| `loop` | object | OPTIONAL | — | Loop configuration. See Section 6.2. |
| `fan_out` | object | OPTIONAL | — | Fan-out configuration. See Section 6.3. |
| `timeout` | integer | OPTIONAL | — | Per-node timeout in seconds. Overrides the execution-level `timeout_per_agent`. |
| `retry` | object | OPTIONAL | — | Per-node retry configuration. Overrides execution-level retry. |

### 3.2 Dependencies

The `depends_on` field defines execution ordering. It accepts two forms:

#### Simple Dependencies

A list of agent IDs. The node MUST NOT execute until all listed agents have completed successfully.

```yaml
depends_on:
  - research_analyst
  - data_collector
```

#### Conditional Dependencies

A list of objects with an `id` and `expr` (expression) field. The node executes only if the expression evaluates to `true`.

```yaml
depends_on:
  - id: research_analyst
    expr: "state.research_analyst.decision == 'proceed'"
  - id: data_collector
    expr: "state.data_collector.status == 'complete'"
```

- Expressions MUST reference state fields using `state.{agent_id}.{field}` syntax.
- The runtime MUST evaluate expressions after the dependency agent completes.
- If any conditional dependency evaluates to `false`, the node MUST be skipped.

### 3.3 Graph Validation

The runtime MUST validate the graph at load time:

1. The graph MUST contain at least one node.
2. The graph MUST be a valid DAG (no cycles).
3. Every `depends_on` reference MUST resolve to a valid node `id`.
4. Every node `id` MUST be unique within the graph.
5. Every node `id` MUST match an `identity.id` in the corresponding `agent.awp.yaml`.

---

## 4. Execution Modes

The `orchestration.execution` section configures how the graph is traversed.

### 4.1 Fields

| Field | Type | Status | Default | Description |
|-------|------|--------|---------|-------------|
| `mode` | string | REQUIRED | — | MUST be one of: `"sequential"`, `"parallel"`, `"conditional"`, `"adaptive"`. |
| `timeout_per_agent` | integer | OPTIONAL | `120` | Default timeout per agent in seconds. |
| `timeout_total` | integer | OPTIONAL | `300` | Total workflow timeout in seconds. |
| `timeout_idle` | integer | OPTIONAL | `60` | Maximum idle time (no agent progress) before the workflow is terminated. |
| `on_error` | string | OPTIONAL | `"stop"` | Default error handling. MUST be one of: `"stop"`, `"continue"`, `"retry"`. |

### 4.2 Mode: `sequential`

Agents execute one at a time in topological order.

- The runtime MUST sort agents topologically based on `depends_on`.
- Each agent MUST complete before the next begins.
- If two agents have no dependency relationship, their relative order is implementation-defined.

### 4.3 Mode: `parallel`

Independent agents execute concurrently.

- Agents with no mutual dependency MAY execute in parallel.
- Agents with dependencies MUST wait for all dependencies to complete.
- The runtime SHOULD limit concurrency to available resources.

### 4.4 Mode: `conditional`

Execution follows the DAG with conditional branching.

- Conditional expressions on `depends_on` determine which branches execute.
- Skipped branches do not produce output.
- Downstream agents of skipped branches are also skipped unless they have alternative satisfied dependencies.

### 4.5 Mode: `adaptive`

The runtime dynamically determines execution order based on state.

- An adaptive orchestrator MAY reorder, skip, or repeat agents based on runtime conditions.
- The DAG serves as a constraint (no cycles, dependency ordering) but not a strict schedule.
- The runtime MUST still respect `depends_on` constraints.

---

## 5. Timeouts and Retry

### 5.1 Timeout Hierarchy

Timeouts are resolved in order of specificity:

1. Node-level `timeout` (highest priority)
2. Execution-level `timeout_per_agent`
3. Runtime default (120 seconds)

When a timeout expires:

- The runtime MUST terminate the agent's execution.
- The runtime MUST set the agent's state to indicate a timeout error.
- The `on_failure` strategy for the node determines subsequent behavior.

### 5.2 Retry Configuration

| Field | Type | Status | Default | Description |
|-------|------|--------|---------|-------------|
| `retry.max_attempts` | integer | OPTIONAL | `1` | Maximum number of execution attempts (1 = no retry). |
| `retry.backoff` | string | OPTIONAL | `"exponential"` | Backoff strategy. MUST be one of: `"none"`, `"linear"`, `"exponential"`. |
| `retry.backoff_base` | float | OPTIONAL | `2.0` | Base for exponential backoff in seconds. |
| `retry.backoff_max` | float | OPTIONAL | `60.0` | Maximum backoff delay in seconds. |
| `retry.retryable_errors` | list | OPTIONAL | `["timeout", "rate_limit", "server_error"]` | Error types that trigger a retry. |
| `retry.non_retryable_errors` | list | OPTIONAL | `["validation_error", "auth_error"]` | Error types that MUST NOT be retried. |

### 5.3 Backoff Calculation

- **none:** No delay between retries.
- **linear:** Delay = `backoff_base * attempt_number` seconds.
- **exponential:** Delay = `min(backoff_base ^ attempt_number, backoff_max)` seconds.

---

## 6. Control Flow

### 6.1 Conditions

Conditional execution is expressed via `depends_on` expressions (Section 3.2) and node-level `enabled` flags.

The `enabled` field MAY be a boolean or a string expression:

```yaml
- id: fallback_researcher
  agent: agents/fallback_researcher
  enabled: "state.research_analyst.decision == 'retry_with_fallback'"
  depends_on:
    - research_analyst
```

When `enabled` is a string, the runtime MUST evaluate it as a boolean expression against the current state.

### 6.2 Loops

The `loop` field on a graph node enables iterative execution.

#### Standard Loop

```yaml
loop:
  type: standard
  max_iterations: 5
  condition: "state.{agent_id}.quality_score < 0.9"
```

| Field | Type | Status | Description |
|-------|------|--------|-------------|
| `type` | string | REQUIRED | MUST be `"standard"` or `"interactive"`. |
| `max_iterations` | integer | REQUIRED | Maximum loop iterations. Runtime MUST enforce this limit. |
| `condition` | string | REQUIRED | Expression evaluated after each iteration. Loop continues while `true`. |

#### Interactive Loop

```yaml
loop:
  type: interactive
  max_iterations: 10
  prompt_field: "state.{agent_id}.needs_input"
  input_channel: "user_feedback"
```

Interactive loops pause execution to await external input (e.g., human feedback) before continuing.

| Field | Type | Status | Description |
|-------|------|--------|-------------|
| `prompt_field` | string | REQUIRED | State field that indicates input is needed. |
| `input_channel` | string | REQUIRED | Channel or endpoint for receiving input. |

### 6.3 Subworkflows

A graph node MAY reference a subworkflow instead of a single agent:

```yaml
- id: deep_analysis
  subworkflow: "workflows/deep-analysis"
  depends_on:
    - research_analyst
  share_input:
    - findings
  share_output:
    - detailed_report
```

- The subworkflow MUST be a valid AWP workflow with its own `workflow.awp.yaml`.
- State is passed to the subworkflow via `share_input` and returned via `share_output`.
- The subworkflow executes as a single unit from the parent graph's perspective.

### 6.4 Fan-Out / Fan-In

Fan-out distributes work across multiple parallel instances of an agent:

```yaml
- id: parallel_researcher
  agent: agents/researcher
  fan_out:
    source: "state.context.topics"
    variable: "topic"
    max_parallel: 5
  fan_in:
    strategy: merge
    target_field: all_findings
```

#### Fan-Out Fields

| Field | Type | Status | Description |
|-------|------|--------|-------------|
| `fan_out.source` | string | REQUIRED | State field containing an iterable to distribute. |
| `fan_out.variable` | string | REQUIRED | Variable name injected into each instance's state. |
| `fan_out.max_parallel` | integer | OPTIONAL | Maximum concurrent instances. Default: unbounded. |

#### Fan-In Fields

| Field | Type | Status | Description |
|-------|------|--------|-------------|
| `fan_in.strategy` | string | REQUIRED | MUST be one of: `"merge"`, `"reduce"`, `"first"`, `"majority"`. |
| `fan_in.target_field` | string | REQUIRED | State field where aggregated results are stored. |

Fan-in strategies:

- **merge:** Collect all outputs into a list.
- **reduce:** Apply a reduction function to combine outputs.
- **first:** Use the first completed output and cancel remaining instances.
- **majority:** Use the most common output (requires comparable outputs).

---

## 7. Error Handling

### 7.1 Default Strategy

The `orchestration.execution.on_error` field sets the default error handling strategy:

| Strategy | Behavior |
|----------|----------|
| `stop` | Halt the entire workflow immediately. |
| `continue` | Skip the failed agent and continue with agents that do not depend on it. |
| `retry` | Retry the failed agent according to the retry configuration. |

### 7.2 Per-Node Override

Each graph node MAY override the default strategy via `on_failure`:

| Strategy | Behavior |
|----------|----------|
| `stop` | Halt the entire workflow. |
| `continue` | Skip this node and continue. Downstream nodes that depend on this node are also skipped. |
| `retry` | Retry using the node's or execution-level retry configuration. |
| `skip` | Mark the node as skipped (not failed) and continue. Downstream nodes receive empty state for this node. |

### 7.3 Circuit Breaker

When enabled (see [security.md](security.md)), the circuit breaker monitors agent failures:

- After `failure_threshold` consecutive failures, the circuit opens.
- While open, the agent is automatically skipped.
- After `reset_timeout`, the circuit enters half-open state and allows `half_open_max` test executions.
- If test executions succeed, the circuit closes. If they fail, the circuit reopens.

### 7.4 Graceful Degradation

A workflow MAY define degradation rules:

```yaml
orchestration:
  degradation:
    - agent: research_analyst
      fallback: cached_results
      max_staleness: 3600
    - agent: quality_reviewer
      fallback: skip
```

| Field | Type | Description |
|-------|------|-------------|
| `agent` | string | Agent ID that MAY degrade. |
| `fallback` | string | Fallback behavior: agent ID, `"cached_results"`, or `"skip"`. |
| `max_staleness` | integer | Maximum age in seconds for cached results. |

---

## 8. Complete Example

```yaml
orchestration:
  engine: dag

  execution:
    mode: conditional
    timeout_per_agent: 120
    timeout_total: 600
    timeout_idle: 60
    on_error: continue

  graph:
    - id: research_analyst
      agent: agents/research_analyst
      enabled: true
      depends_on: []
      share_output:
        - findings
        - summary
        - confidence_score
      description: "Researches the topic using web search."
      on_failure: retry
      timeout: 180
      retry:
        max_attempts: 3
        backoff: exponential
        backoff_base: 2.0
        retryable_errors:
          - timeout
          - rate_limit

    - id: data_collector
      agent: agents/data_collector
      depends_on: []
      share_output:
        - raw_data
        - statistics
      on_failure: continue

    - id: report_writer
      agent: agents/report_writer
      depends_on:
        - id: research_analyst
          expr: "state.research_analyst.confidence_score >= 0.7"
        - data_collector
      share_output:
        - draft
        - metadata
      loop:
        type: standard
        max_iterations: 3
        condition: "state.report_writer.quality_score < 0.9"

    - id: quality_reviewer
      agent: agents/quality_reviewer
      depends_on:
        - report_writer
      share_output:
        - review
        - approved
      on_failure: skip

  degradation:
    - agent: research_analyst
      fallback: cached_results
      max_staleness: 3600
    - agent: quality_reviewer
      fallback: skip
```

---

## 9. Processing Rules

1. The runtime MUST validate the graph is a valid DAG at load time.
2. The runtime MUST execute agents in topological order, respecting all `depends_on` constraints.
3. The runtime MUST skip disabled nodes and nodes whose conditional dependencies evaluate to `false`.
4. The runtime MUST enforce `timeout_per_agent` and `timeout_total` limits.
5. The runtime MUST apply the retry strategy before applying the `on_failure` strategy.
6. When `on_failure` is `continue`, the runtime MUST skip all transitive dependents of the failed node.
7. When `on_failure` is `skip`, the runtime MUST provide empty state for the skipped node to downstream dependents.
8. Fan-out instances MUST be isolated: each instance receives its own copy of the relevant state.
9. Fan-in MUST NOT proceed until all fan-out instances have completed (or timed out).
10. Subworkflow execution MUST be atomic: either all agents in the subworkflow succeed, or the subworkflow fails as a unit.
