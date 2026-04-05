# Observability Reference

Layer 6 defines the observability requirements for AWP workflows: metrics, distributed tracing, structured logging, audit trails, and health checks. Observability is configured in the `observability` section of [workflow.awp.yaml](manifest.md). AWP observability is designed to be compatible with OpenTelemetry standards.

## Metrics

### Configuration

```yaml
observability:
  metrics:
    enabled: true
    exporter: otlp
    endpoint: "http://localhost:4317"
    interval: 30
    custom: []
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enabled` | boolean | -- | Required. Whether metrics collection is active. |
| `exporter` | string | `"otlp"` | `"otlp"`, `"prometheus"`, `"console"`, or `"none"`. |
| `endpoint` | string | -- | Exporter endpoint URL. Required for `"otlp"` and `"prometheus"`. |
| `interval` | integer | `30` | Export interval in seconds. |
| `custom` | list | `[]` | Custom metric definitions. |

### Built-In Metrics

Conformant runtimes must collect these metrics when `metrics.enabled` is `true`:

| Metric Name | Type | Unit | Labels | Description |
|-------------|------|------|--------|-------------|
| `awp.agent.execution_time` | histogram | seconds | `agent_id`, `status` | Time per agent execution. |
| `awp.agent.token_usage` | counter | tokens | `agent_id`, `direction` | Tokens consumed per agent. |
| `awp.agent.tool_calls` | counter | calls | `agent_id`, `tool_name`, `status` | Tool calls per agent. |
| `awp.agent.errors` | counter | errors | `agent_id`, `error_type` | Errors per agent. |
| `awp.workflow.duration` | histogram | seconds | `workflow_name`, `status` | Total workflow duration. |
| `awp.workflow.agent_count` | gauge | agents | `workflow_name` | Number of agents in current execution. |
| `awp.memory.operations` | counter | ops | `tier`, `operation` | Memory read/write/search operations. |
| `awp.bus.messages` | counter | messages | `channel`, `type` | Messages on the message bus. |

### Custom Metrics

Workflows may define additional metrics:

```yaml
observability:
  metrics:
    custom:
      - name: "research.sources_found"
        type: counter
        description: "Number of research sources found."
        labels:
          - agent_id
          - source_type
      - name: "report.quality_score"
        type: gauge
        description: "Quality score of the generated report."
        labels:
          - agent_id
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | Yes | Metric name. Should use dot notation. |
| `type` | string | Yes | `"counter"`, `"gauge"`, or `"histogram"`. |
| `description` | string | Yes | Human-readable description. |
| `labels` | list | No | Label keys for the metric. |
| `buckets` | list | No | Histogram bucket boundaries (for `"histogram"` type only). |

## Tracing

### Configuration

```yaml
observability:
  tracing:
    enabled: true
    exporter: otlp
    endpoint: "http://localhost:4317"
    propagation: w3c
    sampling:
      strategy: parent_based
      rate: 1.0
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enabled` | boolean | -- | Required. Whether distributed tracing is active. |
| `exporter` | string | `"otlp"` | `"otlp"`, `"jaeger"`, `"zipkin"`, `"console"`, or `"none"`. |
| `endpoint` | string | -- | Exporter endpoint URL. |
| `propagation` | string | `"w3c"` | Context propagation format: `"w3c"`, `"b3"`, or `"jaeger"`. |
| `sampling.strategy` | string | `"always_on"` | `"always_on"`, `"always_off"`, `"parent_based"`, or `"probability"`. |
| `sampling.rate` | float | `1.0` | Sampling rate for `"probability"` strategy. 0.0-1.0. |

### Span Hierarchy

AWP defines a standard span hierarchy:

```
workflow.run (root span)
+-- agent.execute (one per agent)
|   +-- agent.build_context
|   +-- llm.call (one per LLM invocation)
|   |   +-- llm.prompt_construction
|   |   +-- llm.inference
|   +-- tool.call (one per tool invocation)
|   |   +-- tool.validate_params
|   |   +-- tool.execute
|   +-- memory.read
|   +-- memory.write
|   +-- agent.parse_response
+-- orchestrator.evaluate_condition
+-- orchestrator.fan_out
```

### Span Attributes

All spans must include:

| Attribute | Type | Description |
|-----------|------|-------------|
| `awp.workflow.name` | string | Workflow name from manifest. |
| `awp.workflow.version` | string | Workflow version. |
| `awp.run.id` | string | Unique run identifier. |

Agent spans must additionally include:

| Attribute | Type | Description |
|-----------|------|-------------|
| `awp.agent.id` | string | Agent identity. |
| `awp.agent.role` | string | Agent role. |
| `awp.agent.model` | string | Model name used. |

Tool spans must additionally include:

| Attribute | Type | Description |
|-----------|------|-------------|
| `awp.tool.name` | string | Tool FQN. |
| `awp.tool.status` | string | `"ok"` or `"error"`. |

LLM spans must additionally include:

| Attribute | Type | Description |
|-----------|------|-------------|
| `awp.llm.model` | string | Model identifier. |
| `awp.llm.tokens.input` | integer | Input token count. |
| `awp.llm.tokens.output` | integer | Output token count. |

### W3C TraceContext Propagation

When `propagation` is `"w3c"`, the runtime must propagate trace context using the W3C TraceContext specification:

- The `traceparent` header must be propagated across agent boundaries.
- The `tracestate` header should be propagated.
- Cross-workflow calls (subworkflows) must propagate the trace context.

## Logging

### Configuration

```yaml
observability:
  logging:
    level: INFO
    format: json
    outputs:
      - type: file
        path: "logs/app.log"
        rotation:
          max_size_mb: 10
          max_files: 5
      - type: console
        format: text
      - type: otlp
        endpoint: "http://localhost:4317"
    capture:
      agent_io: true
      state_transitions: true
      llm_prompts: true
      llm_responses: false
      tool_calls: true
      tool_results: true
    redaction:
      patterns:
        - "sk-[a-zA-Z0-9]{20,}"
        - "password\\s*[:=]\\s*\\S+"
      fields:
        - api_key
        - secret
        - token
```

### Log Levels

| Level | Description |
|-------|-------------|
| `DEBUG` | Detailed diagnostic information. |
| `INFO` | General operational messages. |
| `WARNING` | Unexpected but non-fatal conditions. |
| `ERROR` | Errors that prevent an operation from completing. |
| `CRITICAL` | Severe errors that may cause workflow termination. |

### Log Formats

| Format | Description |
|--------|-------------|
| `json` | Structured JSON. Each entry must include `timestamp`, `level`, `message`, `ctx` (trace context). |
| `text` | Human-readable text with timestamp and level prefix. |
| `structured` | Key-value pairs optimized for log aggregation systems. |

### Capture Flags

| Flag | Default | Description |
|------|---------|-------------|
| `agent_io` | `true` | Log agent input/output summaries. |
| `state_transitions` | `true` | Log state changes between agents. |
| `llm_prompts` | `true` | Log LLM prompts (should respect redaction). |
| `llm_responses` | `false` | Log full LLM responses. |
| `tool_calls` | `true` | Log tool invocations and parameters. |
| `tool_results` | `true` | Log tool return values. |

### Redaction

The runtime must apply redaction rules before writing any log entry:

- `patterns`: Regular expressions matched against all string values. Matches are replaced with `[REDACTED]`.
- `fields`: Field names whose values are always replaced with `[REDACTED]`.

Redaction must be applied to: log messages, span attributes, metric labels, and audit trail entries.

## Audit Trail

### Configuration

```yaml
observability:
  audit:
    enabled: true
    integrity: hash_chain
    hash_algorithm: sha256
    storage:
      type: file
      path: "logs/audit.jsonl"
    retention:
      max_age_days: 90
      max_size_mb: 100
    access_control:
      read:
        - admin
        - auditor
      write:
        - system
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enabled` | boolean | -- | Required. Whether audit trail is active. |
| `integrity` | string | `"hash_chain"` | `"hash_chain"`, `"merkle_tree"`, or `"none"`. |
| `hash_algorithm` | string | `"sha256"` | `"sha256"`, `"sha384"`, or `"sha512"`. |
| `storage` | object | -- | Required. Storage configuration. |
| `retention.max_age_days` | integer | `90` | Maximum age before deletion. |
| `retention.max_size_mb` | float | `100` | Maximum storage size. Oldest entries deleted first. |
| `access_control` | object | -- | Access control for audit data. |

### Hash-Chain Integrity

When `integrity` is `"hash_chain"` (see [R18](validation.md)):

- Each audit entry must include a `prev_hash` field containing the hash of the previous entry.
- The first entry must have `prev_hash` set to a zero hash (all zeros).
- The runtime must compute `hash = H(prev_hash || entry_content)`.
- This provides tamper-evident logging.

### Audit Events

The runtime must record these events:

| Event | Trigger | Required Fields |
|-------|---------|-----------------|
| `workflow.start` | Workflow begins | `run_id`, `workflow_name`, `workflow_version`, `timestamp` |
| `workflow.complete` | Workflow ends | `run_id`, `status`, `duration`, `timestamp` |
| `agent.start` | Agent begins | `run_id`, `agent_id`, `timestamp` |
| `agent.complete` | Agent ends | `run_id`, `agent_id`, `status`, `duration`, `timestamp` |
| `agent.error` | Agent fails | `run_id`, `agent_id`, `error_type`, `error_message`, `timestamp` |
| `tool.call` | Tool invoked | `run_id`, `agent_id`, `tool_name`, `timestamp` |
| `tool.result` | Tool returns | `run_id`, `agent_id`, `tool_name`, `status`, `timestamp` |
| `state.change` | State modified | `run_id`, `agent_id`, `fields_changed`, `timestamp` |
| `memory.write` | Memory modified | `run_id`, `agent_id`, `tier`, `timestamp` |
| `security.event` | Security event | `run_id`, `event_type`, `details`, `timestamp` |

## Health Checks

### Readiness (Pre-Start)

Readiness checks verify prerequisites before workflow execution begins.

```yaml
observability:
  health:
    readiness:
      checks:
        - name: llm_provider
          type: http
          endpoint: "https://openrouter.ai/api/v1/models"
          timeout: 10
          expected_status: 200
        - name: memory_dir
          type: filesystem
          path: "workspace/"
          check: exists
        - name: env_vars
          type: env
          required:
            - OPENROUTER_API_KEY
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `checks[].name` | string | Yes | Check identifier. |
| `checks[].type` | string | Yes | `"http"`, `"filesystem"`, `"env"`, or `"custom"`. |
| `checks[].timeout` | integer | No | Timeout in seconds. Default: 10. |

The runtime must execute all readiness checks before starting the workflow. If any check fails, the workflow must not start.

### Liveness (Runtime)

Liveness checks verify that the workflow is still making progress.

```yaml
observability:
  health:
    liveness:
      interval: 30
      timeout: 10
      failure_threshold: 3
      checks:
        - name: agent_progress
          type: custom
          condition: "time_since_last_agent_completion < 300"
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `interval` | integer | `30` | Seconds between checks. |
| `timeout` | integer | `10` | Seconds before a check is considered failed. |
| `failure_threshold` | integer | `3` | Consecutive failures before the workflow is unhealthy. |

When the failure threshold is reached, the runtime should log a CRITICAL-level message, record a `security.event` in the audit trail, and optionally terminate the workflow.

## Evaluation

The evaluation subsystem provides **quality scoring** for workflow results. It is configured under `observability.evaluation` and is fully optional (disabled by default). For the complete reference, see [evaluation.md](evaluation.md).

### Quick Reference

```yaml
observability:
  evaluation:
    enabled: true
    metrics:
      - name: correctness
        kind: deterministic_test
        weight: 2.0
        params:
          expr: "result.confidence > 0.7"
      - name: quality
        kind: rubric_judge
        weight: 1.0
      - name: efficiency
        kind: budget_utility
        weight: 0.5
    thresholds:
      accept: 0.85
      retry: 0.65
      fail: 0.40
    retry_policy:
      enabled: true
      max_repairs: 2
```

### Metric Kinds

| Kind | Description | Returns |
|------|-------------|---------|
| `deterministic_test` | Evaluate a single safe expression | 1.0 (truthy) or 0.0 (falsy) |
| `deterministic_assertion` | Evaluate a list of assertions | Fraction passing |
| `rubric_judge` | LLM-as-judge with rubric prompt | 0.0-1.0 from LLM |
| `budget_utility` | Score based on resource utilization | 1.0 - avg_utilization |
| `policy_score` | Check policy/governance assertions | Fraction passing |

### Validation Rules

Evaluation adds rules R27-R30 to the validator:

- **R27**: `metrics[].kind` must be a valid metric kind
- **R28**: Thresholds must satisfy `accept >= retry >= fail`, all in [0, 1]
- **R29**: Metric weights must be >= 0; at least one metric must have weight > 0
- **R30**: `step_scores.hooks` must use valid hooks; retry actions must be valid
