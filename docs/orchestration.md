# Orchestration Reference

> **See also** — **Parent**: [layer-model.md](layer-model.md) (this is Layer 5 — Orchestration, the layer that ties every other layer into an executable graph), [docs/README.md](README.md#concept-map) · **Sibling concepts**: [agent.md](agent.md) (nodes of the graph), [memory.md](memory.md) (`share_output` contract), [observability.md](observability.md) (events emitted during orchestration) · **Engines**: [ORCHESTRATION_ENGINES.md](ORCHESTRATION_ENGINES.md) — choose between the `dag` engine (A0–A1) and the `delegation_loop` engine (A2–A4) · **Cross-cutting mechanisms hosted here**: [critique.md](critique.md), [manager-intelligence.md](manager-intelligence.md), [runtime.md](runtime.md) (budget envelope, completion gate chain, R35 repair fixpoint) · **Spec**: [spec/versions/1.0/layers/05-orchestration.md](../spec/versions/1.0/layers/05-orchestration.md) · **Validation**: graph/cycle/output-contract rules in [validation.md](validation.md)

## Mental Model

Orchestration is **Layer 5** of AWP and answers a single question: *In what order, under which conditions, and inside which envelope do agents run?* It is the connective tissue between static agent definitions and a working workflow.

AWP deliberately ships **two orchestration engines** rather than one super-engine, because the two extremes of agent workflows have fundamentally different needs:

- **DAG engine** — a directed acyclic graph of agents with explicit `depends_on` edges. Use it when you can enumerate the steps upfront. It is predictable, cheap to budget (N agents × cost), and easy to audit. This is the right tool for A0-A1 workflows: pipelines, ETL, fan-out/fan-in, conditional branches.
- **Delegation Loop engine** — a manager agent that dynamically spawns ephemeral workers, validates their output, and iterates until the task is complete or the budget is exhausted. Use it when the steps emerge from the task content itself. This is the right tool for A2-A4 workflows: research, open-ended analysis, recursive sub-delegation.

Both engines share the same agent contract (R17 confidence output), the same tool registry, the same memory tiers, and the same observability layer. The difference is *who decides what runs next*: a static graph (DAG) or a manager LLM bounded by a deterministic envelope (Delegation Loop).

The two engines also **compose**: a DAG node may itself be a delegation loop, giving you a predictable outer flow with an adaptive inner step (see [Pattern 4 in ORCHESTRATION_ENGINES.md](ORCHESTRATION_ENGINES.md#pattern-4-dag-with-delegation-loop-inner-step-composed)).

This file is the **DAG engine reference** and the configuration surface for delegation-loop fields that live under `orchestration.delegation_loop`. For the engine comparison, philosophy, and patterns, see [ORCHESTRATION_ENGINES.md](ORCHESTRATION_ENGINES.md). For the critique and evaluation loops, see [critique.md](critique.md) and [evaluation.md](evaluation.md). For the manager's autonomous decision-making, see [manager-intelligence.md](manager-intelligence.md).

  <img src="diagrams/arch-two-engines.svg" alt="DAG vs Delegation Loop" width="100%"/>

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

  <img src="diagrams/inline-orchestration.svg" alt="orchestration diagram" width="100%"/>

## Execution scheduler: `levels` vs. `ready_queue`

The DAG runtime offers two scheduler strategies via `orchestration.execution.scheduler`:

| Value | Behavior |
|-------|----------|
| `levels` (default) | Topological levels with a barrier between levels. All eligible nodes on level *N* are dispatched together; level *N+1* starts only after the last node of level *N* returns. |
| `ready_queue` | A persistent worker pool dispatches nodes as soon as their direct dependencies complete. A fast node on level *N* unblocks its descendants on level *N+1* even while slow siblings on level *N* are still running. |

Both modes use the same pool cap (`min(nodes, 16)`) and share all other semantics: eligibility (`enabled`, `when`, rate-limit, circuit-breaker), retry, loop, fan-out, state persistence, budgets, observability hooks. Only the dispatch strategy changes.

**`when` evaluation timing.** In both modes the `when` expression is evaluated against a state snapshot at the moment the dispatch decision is made. That snapshot differs:

- `levels` — state at the start of the level; all nodes in one level see the same snapshot.
- `ready_queue` — state at the moment the node becomes enqueueable (its direct dependencies completed). Siblings at the same topological depth can see different snapshots because faster upstream branches may have written to the state earlier.

Because agent writers are disjoint under [R17](validation.md) (every agent writes only into `{agent_id: {...}}`), the two snapshots agree on every key that a given `when` expression may read as long as the expression only references true upstream dependencies — the usual case.

**When to pick which.**

- Use `levels` for strictly prescribed, auditable workflows where every level must be a well-defined checkpoint (A0/A1 compliance, evaluation hooks that batch-eval a level, human-in-the-loop inspection between levels).
- Use `ready_queue` when sibling nodes in the same level have heterogeneous runtimes and you want downstream fan-out to proceed as early as correctness allows. Typical gain: the fast-branch tail runs in parallel with the slow-branch body instead of after it.

The default remains `levels` for bit-identical back-compat with existing workflows and tests. Switching to `ready_queue` is a pure local decision — no other AWP contracts change.

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
  enabled: true
  mode: standard
  max_iterations: 5
  until_condition: "state.report_writer.quality_score < 0.9"
  poll_interval: 2.0
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enabled` | boolean | `false` | Must be `true` for the loop to fire. Disabled loops are a no-op. |
| `mode` | string | `"standard"` | `"standard"` or `"interactive"`. |
| `max_iterations` | integer | `5` | Hard cap on iterations. The runtime enforces this limit. |
| `until_condition` | string | `""` | Safe expression evaluated against state **after each iteration**. The loop continues **while the expression is truthy**; it exits when the expression becomes falsy, raises, or `max_iterations` is reached. An empty condition runs the loop exactly `max_iterations` times. |
| `poll_interval` | float | `2.0` | Seconds between iterations in interactive mode. Ignored in standard mode. |

The runtime attaches `_loop_iterations` and `_loop_history` to the agent's
final output so downstream nodes can inspect how many rounds ran.

#### Interactive Loop

Setting `mode: interactive` is reserved for iterations that pause for
external input (human feedback, external events). The current runtime
falls back to standard semantics and logs a warning; full support is
tracked separately.

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
    enabled: true
    source_field: "state.context.topics"
    max_parallel: 5
    aggregation: merge
```

#### Fan-Out Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `fan_out.enabled` | boolean | `false` | Must be `true` for the fan-out to fire. |
| `fan_out.source_field` | string | `""` | State path containing an iterable. Supports a leading `state.` prefix and dotted paths (e.g. `ctx.topics`). If the path is missing, empty, or resolves to a scalar the node emits a zero-count result with `error` set. |
| `fan_out.agent_template` | string | `""` | Reserved for future per-item agent templating. Currently unused — the node's own agent is spawned per item. |
| `fan_out.max_parallel` | integer | `4` | Maximum concurrent instances. Clamped to the number of items. |
| `fan_out.aggregation` | string | `"merge"` | `"merge"` keeps per-item outputs under `items: [...]` with the mean confidence. `"concat"` additionally flattens list-valued fields across items. |

Each per-item invocation receives a shallow-copied state with the reserved
key `fan_out_item` set to the current item and `_fan_out_index` set to its
position. The aggregated result always includes `_fan_out_count`.

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

The delegation loop engine powers A2-A4 workflows. For the complete engine comparison, semantics, budget reservation model, and audit trail layout, see [ORCHESTRATION_ENGINES.md](ORCHESTRATION_ENGINES.md).

A few delegation-loop concepts that materially affect orchestration design:

- **Complexity-scored auto-promotion (A4).** The manager does not decide manually whether a worker becomes a submanager. A deterministic complexity scorer (subtask description length, action keywords like *research*/*validate*/*design*, deliverable count, priority) decides automatically. Subtasks scoring `>= complexity_threshold` are promoted; a hard `max_promotions_per_iteration_fraction` cap prevents a single iteration from blowing the parent budget. Configure under `delegation_loop.auto_promotion`. See [manager-intelligence.md](manager-intelligence.md).
- **Reservation model.** Budget allocation uses pre-charge reservation: when a submanager calls `allocate_child(fraction)`, the parent's pool is immediately debited, so concurrent siblings see a correctly shrinking pool. Unused capacity is refunded via `reclaim_child()` on completion. This is what makes the invariant `sum(children) + self <= allocation` hold even under parallel spawning, and is the source of A4's strong termination guarantees together with `max_depth` and the circuit breaker.
- **Bounded submanager fan-out.** In addition to `max_depth` (default **2**), the budget enforces `max_concurrent_submanagers` (default **3**) and `max_total_submanagers_per_run` (default **6**). Reaching either cap falls back to an ephemeral worker instead of failing the dispatch. Submanager child-budget fraction is computed dynamically as `min(0.3, 0.8 / n)` where *n* is the number of submanagers spawned in the same dispatch, so total submanager spend is bounded at 80% of the parent envelope regardless of sibling count.
- **Submanager output merging.** Each submanager writes its deliverables into its own `output/<sub_run_id>/` sandbox under the parent workflow dir. On completion, the parent runner merges those files back into the parent output dir via `_merge_submanager_outputs`; collisions are renamed `<submanager_name>__<filename>` so nothing is silently lost.
- **Convergence detector.** The manager loop force-completes (`partial: true`, `reason: forced_convergence`) when confidence deltas across the last two iterations are below 0.05 or when three consecutive iterations produce identical `key_findings`. The minimum-iteration floor is `max(5, pending_subtask_count + 3)` — the detector never fires while unstarted subtasks remain in the task plan, because confidence legitimately plateaus between phases of a multi-phase task.
- **Pre-progress planning guard.** The manager is allowed up to 2 consecutive PLAN decisions in strict mode (3 in relaxed mode) before any worker has reported progress. Once any worker reaches `in_progress`, `completed`, or `failed` status, the pre-progress plan counter resets — subsequent PLANs (refinements) are legitimate and do not count against the guard. This prevents endless planning loops while allowing iterative plan refinement and R31-rejected re-plans after initial progress.
- **Redundancy guard + critique gate on DELEGATE.** Every dispatch is signed via a sorted hash of normalized worker instructions. If a new dispatch matches a past signature *and* the last iteration's mean critique score is below `critique.min_score_to_complete` (default **0.6**), the DELEGATE decision is overridden and the manager is forced into DIAGNOSE/REPAIR on the next pass instead of re-issuing the same subtasks.
- **Per-iteration fan-out cap.** `budget.max_workers_per_iteration` (default **6**) is a pre-spawn hard cap on the number of workers the manager is allowed to dispatch in a single DELEGATE decision. When exceeded, the runner trims the dispatch list to the cap, writes the overflow summary into `state["_deferred_workers"]`, and records a `max_workers_per_iteration` trace-gate event. The manager is then forced to merge subtasks or re-dispatch the overflow in a later iteration. This prevents a single DELEGATE turn from blowing the worker budget on a wide fan-out.
- **Deliverable-presence gate.** Before a COMPLETE decision is accepted, every manager-declared deliverable path MUST exist on disk and be non-empty. The gate derives required paths in priority order: (1) `required_outputs: [<relpath>, …]` field on each subtask of the active task plan, (2) path tokens scraped from `success_criteria` / `description` using a regex anchored on the `_output_dir` / `_workspace_dir` placeholders, (3) path tokens from the original task string. When none of the three yield any path, the gate emits a WARNING and becomes a non-blocking no-op. On rejection, it emits a `deliverable_presence` gate event with `missing: [...]`, `empty: [...]`, `source: "required_outputs" | "success_criteria"` and nudges the manager with a textual repair instruction.
- **Completion-retry circuit breaker.** `budget.max_rejected_completions` (default **2**) bounds how many times the manager can have a COMPLETE decision rejected by the completion-gate chain (`deliverable_presence`, `placeholder`, `file`, `structural_integrity`, `critique`, `eval`) before the runner takes over. On the Nth rejection, if the last gate-rejection payload identifies a concrete defect, the runner synthesizes a repair subtask (`id: repair_auto_<iter>`, priority `critical`, `required_outputs` populated from the defect) and force-routes the next iteration into DELEGATE. If no repair can be derived (e.g. a pure evaluation-score miss), the run terminates as `partial` with reason `max_rejected_completions`. The counter resets on any successful DELEGATE, so the breaker only fires on true oscillation.
- **Plan-loop deterministic transition.** When the `plan_loop` gate fires (manager issued >MAX consecutive PLANs without any worker progress), the runner picks one of two transitions deterministically: `forced_delegate` (pending subtasks exist → lock the plan via `state["_plan_locked"]` and force DELEGATE on the next iteration) or `forced_terminate` (no pending subtasks → exit as `partial` with reason `plan_loop_stall`). The gate event records `transition: "forced_delegate" | "forced_terminate"` alongside `pre_progress_plans` and `pending_subtasks`.
- **Terminal status contract.** Every run ends with exactly one of `{complete, partial, failed, aborted}`, mapped from the internal termination reason via the `_finalize_terminal_status(reason)` helper. Cap-forced exits — `defect_category_cap`, `plan_loop`, `max_total_tokens`, `max_total_workers`, `max_wall_time`, `max_loops`, `max_tool_calls`, `forced_convergence`, `stall_detected` — map to **`partial`**, never `complete`. Hard evaluation/execution failures (`eval_fail`, `error: …`) map to **`failed`**. Abrupt process-level exits (SIGTERM/SIGINT, killed process, unhandled exception during teardown) map to **`aborted`** with reason `process_exit_without_terminal_event` or `sigterm`/`sigint`.
- **Finalizer + signal handling.** The delegation-loop runner wraps its main loop in `try/except/finally`, registers `SIGTERM`/`SIGINT` handlers on the root manager (submanagers inherit the parent disposition), and always emits `run_completion.json` + the `run.complete` WebSocket event before returning. The runner_service canonicalizes the status and attaches a `reason` field. On server restart, any runs still flagged `running` without a live PID are marked `aborted` in the SQLite DB so the UI sidebar never shows a permanent "running" indicator for a dead process.
- **Signal watchdog for blocking LLM calls.** The SIGTERM/SIGINT handler also invokes `LLMClient.close_all()`, which reaches into every live httpx client's connection pool and raw-socket-`shutdown()`s each in-flight connection. Without this step, the main thread stays blocked inside the C-level socket `recv()` of a slow `httpx.post()` call, so the Python-level `signal_state["pending"]` flag is never observed and the `finally` block never runs. The raw-socket abort raises `httpx.ReadError` into the blocking thread, which propagates up to the delegation loop's `except Exception` branch, the `finally` emits `run.complete` with `reason="sigterm"`/`"sigint"`, and the DB row transitions `running → aborted` immediately — no SIGKILL needed.
- **Forbidden tools envelope.** `shell.execute` and `terminal.execute` are by default forbidden inside the delegation loop. Workers do shell-like work via `code.execute` in the sandbox or via dynamically generated MCP tools. See [tools.md](tools.md).
- **Code mode + tool creation default to enabled** for delegation-loop workers, because token cost and tool coverage are the dominant constraints in A2-A4. The manager can disable them per-worker via the envelope.
- **Persistent per-worker executor.** Every `code.execute` call inside a single worker targets the same warm Python subprocess — variables, imports, and helper functions defined in one call remain live in the next. Stderr is merged into stdout to avoid pipe deadlock, reads use `select()` with real timeout enforcement, and a bounded history is replayed into a fresh subprocess after a crash. See [ORCHESTRATION_ENGINES.md §Per-worker Executor Lifecycle](ORCHESTRATION_ENGINES.md#per-worker-executor-lifecycle).
- **In-place repair.** When a repair worker (`*_repair`, `*_retry`, `*_vN`, `*_strict`, `*_final`, `*_runN`, `*_subtask_N`) is dispatched, the runtime reuses the prior worker's executor (same warm namespace) and prepends a `REPAIR MODE` block to the worker system prompt so the LLM picks up incrementally rather than re-hydrating state. The manager can force a clean slate via envelope field `fresh_worker: true`. See [ORCHESTRATION_ENGINES.md §Per-worker Executor Lifecycle](ORCHESTRATION_ENGINES.md#per-worker-executor-lifecycle).
- **Auto-emergent tools.** The runtime watches every `code.execute` call and computes an AST-skeleton signature (literals → `<const>`, identifiers → `<vK>`). When the same signature appears from `N=3` distinct worker ids, a generalized tool is synthesized, persisted via `DynamicToolFactory` as `shared/dynamic_tools/dynamic.induced_<hash6>.json`, and exposed to later workers through `tool.list`. No new config flag; `N=3` is a hardcoded constant. See [ORCHESTRATION_ENGINES.md §Auto-Emergent Tools](ORCHESTRATION_ENGINES.md#auto-emergent-tools).
- **Atomicity advisory.** Each pending subtask is scored on a deterministic 0.0-1.0 axis from its description features (atomic/composition keywords, required-output count, numbered-step count, log-length). The score is injected into the manager planning prompt as an advisory hint and MUST NOT block or override any manager decision. See [ORCHESTRATION_ENGINES.md §Atomicity Advisory](ORCHESTRATION_ENGINES.md#atomicity-advisory).

### Critique Configuration

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

### Parallelism toggles (opt-in)

The delegation loop exposes two boolean flags under
`delegation_loop` that trade determinism for wall-clock time. Both
default to `false` so runs stay byte-identical to the sequential code
path; enable only when reproducibility is not a concern.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `pipeline_critique_planning` | bool | `false` | Overlap per-iteration critique with next-iteration manager prompt assembly. See [runtime.md](runtime.md#pipelined-critique--eval-opt-in). |
| `parallel_gate_chain` | bool | `false` | Run independent Phase-A completion gates concurrently. Canonical first-failure-wins rejection order preserved. See [runtime.md](runtime.md#parallel-completion-gate-chain-opt-in). |

## Phase Types (R33) — LLM vs Deterministic

AWP phases are typed. The default `type: llm` places the phase under the
manager/worker delegation loop, paying cost in LLM tokens and accepting
non-deterministic output. A phase may instead be declared
`type: deterministic`, in which case the runtime invokes a
workflow-supplied Python callable inside a subprocess sandbox and
enforces a set of invariants on its output.

**Deterministic phases NEVER invoke LLM clients** — this is enforced as
validation rule R33 (see
[validation-rules.md](../spec/versions/1.0/validation-rules.md#r33-deterministic-phase-purity)).
They exist to give workflow authors a first-class way to:

- Assemble artifacts from LLM drafts (LaTeX, Docker images, Protobuf
  codegen, SQL migrations, …) without paying LLM tokens for mechanical
  string manipulation;
- Guarantee bit-exact, reproducible output;
- Attach hard invariants (`file_exists`, `file_size_range`,
  `regex_absent`, `python_predicate`) that become a *structural* part
  of the terminal-status decision, not an LLM-judge advisory.

### Minimal example

```yaml
orchestration:
  phases:
    - id: draft_report
      type: llm
      deliverable: {id: report_md, kind: file}

    - id: assemble_report
      type: deterministic
      depends_on: [draft_report]
      callable: my_workflow.assembler:build_report
      args:
        input: "${draft_report.deliverable}"
      timeout_s: 300
      invariants:
        - kind: file_exists
          path: "${output}/report.final"
        - kind: regex_absent
          path: "${output}/report.final"
          pattern: 'TODO|XXX'
```

The runner loads the callable via `importlib` (no `eval`, no shell),
strips `*_API_KEY` env vars, runs with the configured timeout, and
then evaluates every invariant. Any failure produces a structured
`partial`/`failed` contribution to the run's terminal status.

Supported invariant kinds (conformant minimum set):

| Kind | Fields | Semantics |
|------|--------|-----------|
| `file_exists` | `path` | Non-empty file at `path` |
| `file_size_range` | `path`, `min_bytes`, `max_bytes` | Size within bounds |
| `regex_absent` | `path`, `pattern` | `re.search` returns None |
| `regex_present` | `path`, `pattern` | `re.search` returns match |
| `exit_code` | `expected` | Callable returned dict with matching `exit_code` |
| `python_predicate` | `module`, `function` | Importlib-loaded callable is truthy |

Unknown invariant kinds cause phase failure with reason
`unknown_invariant_kind`. See the normative semantics in
[validation-rules.md §9](../spec/versions/1.0/validation-rules.md#9-deterministic-phase-type-r33).

### Phase schema reference (all phase types)

| Field | Type | Required | Phase types | Purpose |
|-------|------|----------|-------------|---------|
| `id` | string | yes | all | Unique identifier |
| `type` | enum (`llm`, `deterministic`, `hybrid`) | yes | all | Dispatch target |
| `depends_on` | list[string] | no | all | Topological edges |
| `callable` | `module:function` | yes | `deterministic` | Importable python callable |
| `args` | dict | no | `deterministic` | Positional/keyword args with `${…}` substitution |
| `timeout_s` | int `[1, 3600]` | no (default `300`) | `deterministic` | Legacy deterministic-only timeout |
| `max_wall_time_s` | int `[1, 3600]` | no | all phase types | **Phase 3.2** — generic per-phase wall-time budget. Overrides `timeout_s` when set. On breach the phase returns `partial` with reason `phase_timeout`. |
| `invariants` | list[Invariant] | no | `deterministic` | Post-execution invariant chain |

`max_wall_time_s` is the forward-compatible name to use for new
workflows. `timeout_s` remains a deterministic-only alias for backward
compatibility; when both are set, `max_wall_time_s` wins.

### When to use which phase type

| Situation | Phase type |
|-----------|-----------|
| Creative drafting, analysis, synthesis | `llm` |
| LaTeX/Docker/Proto/SQL/OpenAPI assembly | `deterministic` |
| Fixed-point problems (exact page count, schema validation) | `deterministic` |
| Any task with bit-exact reproducibility requirement | `deterministic` |

The [Compiler Layer](architecture.md#compiler-layer) section of the
architecture document motivates why AWP introduces a deterministic tier
alongside the LLM inner loop and the SGD outer loop.

### Phase 2 scope (implementation status)

Deterministic phases are implemented in the reference runtime as of
Phase 2 of the Compiler-Layer initiative. The current scope is narrow
on purpose: Phase 2 wires the runner into the **DAG engine only**, and
only for a **post-graph** position in the pipeline.

| Capability | Status |
|------------|--------|
| Pydantic models (`DeterministicPhase`, `Invariant`) | **Landed** — `packages/awp-core/src/awp/models/orchestration.py` |
| R33 validator static check (callable format, timeout, import purity, dependency resolution) | **Landed** — `packages/awp-core/src/awp/validator/rules.py` |
| Phase runner (subprocess, secret scrub, timeout, JSON result protocol) | **Landed** — `packages/awp-runtime/src/awp/runtime/deterministic/runner.py` |
| 6 normative invariant kinds (`file_exists`, `file_size_range`, `regex_absent`, `regex_present`, `exit_code`, `python_predicate`) | **Landed** — `packages/awp-runtime/src/awp/runtime/deterministic/invariants.py` |
| DAG-engine integration (phases run in topological order of `depends_on`, after all graph nodes complete) | **Landed** — `packages/awp-runtime/src/awp/runtime/runner.py::_run_deterministic_phases` |
| Delegation-loop-engine integration (phases as a post-loop, pre-critique tier under `engine: delegation_loop`) | **Phase 2.x (planned)** |
| `type: hybrid` semantics (LLM-generated spec, then deterministic execution) | **Reserved** — loader accepts the value; runtime raises `NotImplementedError` |

**DAG-engine integration in practice.** When `orchestration.phases` is
present on a DAG-engine workflow, the runner executes the graph first,
then executes every `type: deterministic` phase in topological order of
its `depends_on` list (dependencies on graph nodes are satisfied by
construction). Each phase's result — stdout, stderr, structured
callable result, and per-invariant check outcome — is persisted under
`output/<run_id>/phase_<phase_id>/result.json` plus `stdout.log` /
`stderr.log`. The aggregate of every phase's status (`complete` >
`partial` > `failed`) is surfaced on the run's state as `_phase_status`
and the per-phase dict list as `_phases`.

**Why post-graph and not interleaved.** In the current scope a
deterministic phase *consumes* LLM-agent output and never *feeds* it —
the LLM agents run first, the deterministic assembler runs after. An
interleaved design (e.g. a deterministic phase in the middle of the
graph, feeding a downstream LLM agent) needs a contract extension: the
DAG runner would have to treat the phase's `callable_result` as a state
fragment with a declared `share_output` set. That is deferred to Phase
2.x along with the delegation-loop integration.

**Phase-only workflows.** A workflow MAY declare `orchestration.phases`
without any `orchestration.graph` entries; in that case the DAG engine
skips the (empty) graph and runs the phases directly. This is a
legitimate use of the engine for pure mechanical-assembly pipelines
that do not need an LLM drafter at all.
