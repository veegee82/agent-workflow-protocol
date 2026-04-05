# Orchestration Reference

Orchestration defines the execution graph, modes, control flow, error handling, and retry strategies. It is configured in the `orchestration` section of `workflow.awp.yaml`.

## Engine

### `orchestration.engine`

- **Type:** string
- **Required:** Yes
- **Allowed values:** `"dag"`

Two engines are available:

- `dag` — Directed Acyclic Graph for A0-A1 workflows (described below)
- `delegation_loop` — Manager-worker loop for A2-A4 workflows (see [ORCHESTRATION_ENGINES.md](ORCHESTRATION_ENGINES.md))

```yaml
orchestration:
  engine: dag
```

## Graph Nodes

The `orchestration.graph` section defines the agent execution graph as a list of node definitions.

### Node Fields

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `id` | string | Yes | -- | Unique node identifier. Must match an agent's `identity.id`. |
| `agent` | string | Yes | -- | Path to the agent directory relative to the workflow root. |
| `enabled` | boolean | No | `true` | Whether this node is active. Disabled nodes are skipped. |
| `depends_on` | list | No | `[]` | Dependencies. See below. |
| `share_input` | list | No | `[]` | State fields to inject from workflow context into this agent's input. |
| `share_output` | list | No | `[]` | Output fields this agent exposes to downstream agents. |
| `description` | string | No | -- | Human-readable description of this node's role. |
| `on_failure` | string | No | `"stop"` | Action on failure: `"stop"`, `"continue"`, `"retry"`, or `"skip"`. |
| `loop` | object | No | -- | Loop configuration. |
| `fan_out` | object | No | -- | Fan-out configuration. |
| `timeout` | integer | No | -- | Per-node timeout in seconds. Overrides `execution.timeout_per_agent`. |
| `retry` | object | No | -- | Per-node retry configuration. |

### Dependencies

The `depends_on` field defines execution ordering. It accepts two forms.

#### Simple Dependencies

A list of agent IDs. The node must not execute until all listed agents have completed successfully.

```yaml
depends_on:
  - research_analyst
  - data_collector
```

#### Conditional Dependencies

A list of objects with an `id` and `expr` field. The node executes only if all expressions evaluate to `true`.

```yaml
depends_on:
  - id: research_analyst
    expr: "state.research_analyst.decision == 'proceed'"
  - id: data_collector
    expr: "state.data_collector.status == 'complete'"
```

- Expressions must reference state fields using `state.{agent_id}.{field}` syntax.
- The runtime evaluates expressions after the dependency agent completes.
- If any conditional dependency evaluates to `false`, the node is skipped.

### Graph Validation

The runtime must validate the graph at load time:

1. The graph must contain at least one node.
2. The graph must be a valid DAG (no cycles). See [R6](validation.md).
3. Every `depends_on` reference must resolve to a valid node `id`. See [R7](validation.md).
4. Every node `id` must be unique. See [R5](validation.md).
5. Every node `id` must match an `identity.id` in the corresponding `agent.awp.yaml`.

## Execution Modes

### `orchestration.execution`

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `mode` | string | Yes | -- | `"sequential"`, `"parallel"`, `"conditional"`, or `"adaptive"`. |
| `timeout_per_agent` | integer | No | `120` | Default timeout per agent in seconds. |
| `timeout_total` | integer | No | `300` | Total workflow timeout in seconds. |
| `timeout_idle` | integer | No | `60` | Maximum idle time before the workflow is terminated. |
| `on_error` | string | No | `"stop"` | Default error handling: `"stop"`, `"continue"`, or `"retry"`. |

### `sequential`

Agents execute one at a time in topological order. Each agent must complete before the next begins. If two agents have no dependency relationship, their relative order is implementation-defined.

### `parallel`

Independent agents execute concurrently. Agents with no mutual dependency may run in parallel. Agents with dependencies must wait for all dependencies to complete.

### `conditional`

Execution follows the DAG with conditional branching. Conditional expressions on `depends_on` determine which branches execute. Skipped branches do not produce output. Downstream agents of skipped branches are also skipped unless they have alternative satisfied dependencies.

### `adaptive`

The runtime dynamically determines execution order based on state. The DAG serves as a constraint (no cycles, dependency ordering) but not a strict schedule. The runtime must still respect `depends_on` constraints.

## Execution Order Visualization

The runtime sorts agents topologically into batches. Agents within the same batch have no mutual dependencies and may execute in parallel (in `parallel` or `conditional` mode).

```
Batch 0:  [research_analyst, data_collector]    -- no dependencies
Batch 1:  [report_writer]                       -- depends on batch 0
Batch 2:  [quality_reviewer]                    -- depends on batch 1
```

## Timeouts

Timeouts are resolved in order of specificity:

1. Node-level `timeout` (highest priority)
2. Execution-level `timeout_per_agent`
3. Runtime default (120 seconds)

When a timeout expires:
- The runtime must terminate the agent's execution.
- The runtime must set the agent's state to indicate a timeout error.
- The `on_failure` strategy for the node determines subsequent behavior.

## Retry Configuration

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `retry.max_attempts` | integer | `1` | Maximum execution attempts (1 = no retry). |
| `retry.backoff` | string | `"exponential"` | Backoff strategy: `"none"`, `"linear"`, or `"exponential"`. |
| `retry.backoff_base` | float | `2.0` | Base for backoff calculation in seconds. |
| `retry.backoff_max` | float | `60.0` | Maximum backoff delay in seconds. |
| `retry.retryable_errors` | list | `["timeout", "rate_limit", "server_error"]` | Error types that trigger a retry. |
| `retry.non_retryable_errors` | list | `["validation_error", "auth_error"]` | Error types that must not be retried. |

### Backoff Calculation

- **none:** No delay between retries.
- **linear:** Delay = `backoff_base * attempt_number` seconds.
- **exponential:** Delay = `min(backoff_base ^ attempt_number, backoff_max)` seconds.

## Control Flow

### Conditional Execution

The `enabled` field on a graph node may be a boolean or a string expression:

```yaml
- id: fallback_researcher
  agent: agents/fallback_researcher
  enabled: "state.research_analyst.decision == 'retry_with_fallback'"
  depends_on:
    - research_analyst
```

When `enabled` is a string, the runtime evaluates it as a boolean expression against the current state.

### Loops

The `loop` field on a graph node enables iterative execution.

#### Standard Loop

```yaml
loop:
  type: standard
  max_iterations: 5
  condition: "state.report_writer.quality_score < 0.9"
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `type` | string | Yes | `"standard"` or `"interactive"`. |
| `max_iterations` | integer | Yes | Maximum loop iterations. The runtime must enforce this limit. |
| `condition` | string | Yes | Expression evaluated after each iteration. Loop continues while `true`. |

#### Interactive Loop

```yaml
loop:
  type: interactive
  max_iterations: 10
  prompt_field: "state.report_writer.needs_input"
  input_channel: "user_feedback"
```

Interactive loops pause execution to await external input (e.g., human feedback) before continuing.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `prompt_field` | string | Yes | State field that indicates input is needed. |
| `input_channel` | string | Yes | Channel or endpoint for receiving input. |

### Subworkflows

A graph node may reference a subworkflow instead of a single agent:

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

- The subworkflow must be a valid AWP workflow with its own `workflow.awp.yaml`.
- State is passed via `share_input` and returned via `share_output`.
- The subworkflow executes as a single unit from the parent graph's perspective.

### Fan-Out / Fan-In

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

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `fan_out.source` | string | Yes | State field containing an iterable to distribute. |
| `fan_out.variable` | string | Yes | Variable name injected into each instance's state. |
| `fan_out.max_parallel` | integer | No | Maximum concurrent instances. Default: unbounded. |

#### Fan-In Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `fan_in.strategy` | string | Yes | `"merge"`, `"reduce"`, `"first"`, or `"majority"`. |
| `fan_in.target_field` | string | Yes | State field where aggregated results are stored. |

Fan-in strategies:
- **merge:** Collect all outputs into a list.
- **reduce:** Apply a reduction function to combine outputs.
- **first:** Use the first completed output and cancel remaining instances.
- **majority:** Use the most common output (requires comparable outputs).

## Error Handling

### Default Strategy

The `orchestration.execution.on_error` field sets the default:

| Strategy | Behavior |
|----------|----------|
| `stop` | Halt the entire workflow immediately. |
| `continue` | Skip the failed agent and continue with agents that do not depend on it. |
| `retry` | Retry the failed agent according to the retry configuration. |

### Per-Node Override

Each graph node may override the default via `on_failure`:

| Strategy | Behavior |
|----------|----------|
| `stop` | Halt the entire workflow. |
| `continue` | Skip this node and continue. Downstream dependents are also skipped. |
| `retry` | Retry using node-level or execution-level retry configuration. |
| `skip` | Mark the node as skipped (not failed). Downstream nodes receive empty state. |

### Circuit Breaker Integration

When enabled (see [Security Reference](security.md)), the circuit breaker monitors agent failures. After consecutive failures exceed the threshold, the agent is automatically skipped until the circuit resets.

### Graceful Degradation

A workflow may define degradation rules:

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
| `agent` | string | Agent ID that may degrade. |
| `fallback` | string | Fallback behavior: agent ID, `"cached_results"`, or `"skip"`. |
| `max_staleness` | integer | Maximum age in seconds for cached results. |

## Complete Example

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

## Delegation Loop Engine

The delegation loop engine powers A2-A4 workflows. For the complete engine comparison, see [ORCHESTRATION_ENGINES.md](ORCHESTRATION_ENGINES.md).

### Critique Configuration

The delegation loop supports an optional **Reflective Critique Loop** that analyzes worker outputs for defects and triggers targeted repairs. See [critique.md](critique.md) for the full reference.

```yaml
orchestration:
  engine: delegation_loop
  delegation_loop:
    critique:
      enabled: true
      mode: inline
      max_repair_attempts: 2
      repair_budget_fraction: 0.15
      pattern_memory: true
      defect_categories:
        - missing_data
        - wrong_format
        - incomplete
        - hallucinated
        - policy_violation
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `critique.enabled` | bool | `false` | Enable reflective critique loop |
| `critique.mode` | string | `"inline"` | `"inline"` (worker model) or `"dedicated"` (separate critic) |
| `critique.model` | string | `null` | LLM for critic. `null` = inherit worker model |
| `critique.max_repair_attempts` | int | `2` | Max repair cycles per worker |
| `critique.repair_budget_fraction` | float | `0.15` | Max budget fraction for repairs |
| `critique.pattern_memory` | bool | `true` | Accumulate cross-worker failure patterns |
| `critique.defect_categories` | list | 6 defaults | Defect types to diagnose |
