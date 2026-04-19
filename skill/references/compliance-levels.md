# AWP Autonomy Levels -- Quick Reference

## A0 Prescribed

**What it measures:** Static workflow with predefined agents and fixed tools.
**Minimum requirements:**
- `workflow.awp.yaml` with project, graph, execution, state, logging, settings sections.
- At least one agent in the graph.
- Each agent has: agent.awp.yaml, agent.py, SYSTEM_PROMPT.md, 00_INTRO.md, output_schema.json, output_schema_desc.json.
- Output schema includes confidence field.
- No delegation, dynamic tools, or self-organization required.

**Use when:** You need a simple single-agent or basic multi-agent workflow with a fixed DAG.

---

## A1 Adaptive

**What it measures:** Workflow can branch, loop, fan-out, and adapt execution at runtime.
**Additional requirements beyond A0:**
- Multiple agents with `depends_on` edges forming a DAG.
- `share_output` fields defined and matching output schema properties.
- `state.persist: true` with a persist path.
- `state.sharing_strategy` explicitly set (full, selective, or isolated).
- Conditional execution, loops, or fan-out patterns.

**Use when:** You need a multi-step pipeline where agents build on each other's output with dynamic control flow.

---

## A2 Delegating

**What it measures:** Manager agents can spawn workers dynamically via the delegation loop engine.
**Additional requirements beyond A1:**
- At least one manager agent with delegation enabled.
- Budget section with `max_loops`, `max_total_workers`, `max_total_tokens`, `max_wall_time` (and optionally `max_tool_calls`, `max_workers_per_iteration` default `6`, `max_rejected_completions` default `2`).
- Spawned workers must conform to output contracts.
- Delegation loop configuration with budget and worker policy.

**Safety:** Budget controls required to prevent unbounded spawning.

**Use when:** A manager agent needs to dynamically decide what workers to create based on the task.

**Delegation loop config example:**

```yaml
orchestration:
  engine: delegation_loop
  delegation_loop:
    manager: agents/manager
    budget:
      max_loops: 10
      max_total_workers: 15
      max_total_tokens: 500000
      max_wall_time: 300
    worker_policy:
      enforced:
        sandbox:
          type: subprocess
          max_memory_mb: 512
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

---

## A3 Self-Tooling

**What it measures:** Agents can create tools and skills at runtime via CodeMode.
**Additional requirements beyond A2:**
- At least one agent with tool creation capabilities (`codemode.enabled: true`).
- Safety envelope defining allowed namespaces and resource limits.
- Runtime-created tools must be validated and logged.
- In delegation loop: manager can enable `codemode.tool_creation` per worker via the delegation envelope.

**Safety:** Safety envelope required to constrain tool creation. The `worker_policy.enforced.codemode.max_tools_per_worker` limit cannot be overridden by the manager.

**Use when:** Agents need to adapt their capabilities by creating new tools to handle unfamiliar situations.

**Delegation envelope with tool creation:**

```json
{
  "worker_id": "api_integrator",
  "instructions": "Create an MCP tool for the target API and use it.",
  "tools_allowed": ["web.search", "file.read", "file.write"],
  "codemode": {
    "enabled": true,
    "tool_creation": true
  },
  "output_contract": {
    "required_fields": ["tool_name", "result", "confidence"]
  }
}
```

---

## A4 Self-Organizing

**What it measures:** Recursive delegation with budget distribution across a delegation tree.
**Additional requirements beyond A3:**
- Recursive delegation support (workers acting as sub-managers spawning their own workers).
- Budget distribution strategy (equal, weighted, dynamic) with invariant: `sum(children) + self <= allocation`.
- Observability tracing required to track the full delegation tree.
- Circuit breaker or equivalent safety mechanism.
- Bounded delegation depth via `budget.max_depth`.

**Safety:** Observability required. Budget distribution, depth limits, and circuit breakers prevent runaway recursion.

**Use when:** Mission-critical enterprise workflows requiring hierarchical delegation with oversight.

**Full delegation loop config for A4:**

```yaml
orchestration:
  engine: delegation_loop
  delegation_loop:
    manager: agents/manager
    budget:
      max_loops: 20
      max_total_workers: 30
      max_total_tokens: 1000000
      max_wall_time: 600
      max_tool_calls: 200
      max_depth: 5                    # Bounds recursive sub-delegation
    worker_policy:
      enforced:
        sandbox:
          type: subprocess
          max_memory_mb: 512
          max_cpu_seconds: 30
          network: false
        codemode:
          max_tools_per_worker: 10
        rate_limiting:
          max_llm_calls_per_minute: 30
        forbidden_tools: ["shell.execute"]
      manager_controlled:
        - instructions
        - skills
        - tools_allowed
        - output_contract
        - codemode.enabled
        - codemode.tool_creation
    termination:
      enabled: true
      window: 3
      min_confidence_delta: 0.05
      action: warn_then_stop
    validation:
      deterministic:
        always: true
        checks: [schema, required_fields, confidence, budget]
      llm:
        enabled: true
        skip_when_confidence_above: 0.95
        skip_when_budget_remaining_below: 0.1
    history:
      rolling_summary: true
      full_results_window: 3
      persist_to_disk: true
    logging:
      format: dual                    # dual | json | md
      persist_artifacts: true

# Observability is REQUIRED at A4
observability:
  tracing:
    enabled: true
    exporter: internal
  metrics:
    enabled: true

# Circuit breaker is REQUIRED at A4
security:
  circuit_breaker:
    enabled: true
    failure_threshold: 5
    reset_timeout: 60
```

---

## Cross-Cutting Features (Available at Any Level)

These features are not tied to a specific autonomy level. Use them with any A0-A4 workflow:

| Feature | Description |
|---------|-------------|
| Communication | Message bus for agent-to-agent messaging outside the DAG. |
| Memory | Long-term memory (MEMORY.md), daily logs, search, curation. |
| Observability | Structured logging, distributed tracing, metrics collection. Required at A4. |
| Security | Circuit breaker, rate limiting, access control, audit trail. |

---

## Autonomy Level Determination

A workflow's autonomy level is the highest level for which ALL requirements are met. Partial implementation of a higher level does not count. For example, a workflow with delegation but no safety envelope is A1 Adaptive, not A3 Self-Tooling, because A2 budget requirements must also be met.

Cross-cutting features (communication, memory, observability, security) can be added at any level and do not affect the autonomy level classification. A simple A0 workflow can have full observability; a complex A4 workflow must have it.
