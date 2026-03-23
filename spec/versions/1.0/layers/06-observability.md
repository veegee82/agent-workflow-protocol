# Layer 6: Observability

**AWP Specification v1.0.0 — Layer 6**
**Status:** Draft Standard

---

## 1. Overview

Layer 6 defines the observability requirements for AWP workflows: metrics, distributed tracing, structured logging, audit trails, and health checks. Observability is configured in the `observability` section of `workflow.awp.yaml`. AWP observability is designed to be compatible with OpenTelemetry standards.

---

## 2. Metrics

### 2.1 Configuration

```yaml
observability:
  metrics:
    enabled: true
    exporter: otlp
    endpoint: "http://localhost:4317"
    interval: 30
    custom: []
```

| Field | Type | Status | Default | Description |
|-------|------|--------|---------|-------------|
| `enabled` | boolean | REQUIRED | — | Whether metrics collection is active. |
| `exporter` | string | OPTIONAL | `"otlp"` | Metrics exporter. MUST be one of: `"otlp"`, `"prometheus"`, `"console"`, `"none"`. |
| `endpoint` | string | OPTIONAL | — | Exporter endpoint URL. REQUIRED when exporter is `"otlp"` or `"prometheus"`. |
| `interval` | integer | OPTIONAL | `30` | Export interval in seconds. |
| `custom` | list | OPTIONAL | `[]` | Custom metric definitions. See Section 2.3. |

### 2.2 Built-in Metrics

Conformant runtimes MUST collect the following metrics when `metrics.enabled` is `true`:

| Metric Name | Type | Unit | Description |
|-------------|------|------|-------------|
| `awp.agent.execution_time` | histogram | seconds | Time taken for each agent execution. Labels: `agent_id`, `status`. |
| `awp.agent.token_usage` | counter | tokens | Total tokens consumed per agent. Labels: `agent_id`, `direction` (input/output). |
| `awp.agent.tool_calls` | counter | calls | Number of tool calls per agent. Labels: `agent_id`, `tool_name`, `status`. |
| `awp.agent.errors` | counter | errors | Number of errors per agent. Labels: `agent_id`, `error_type`. |
| `awp.workflow.duration` | histogram | seconds | Total workflow execution duration. Labels: `workflow_name`, `status`. |
| `awp.workflow.agent_count` | gauge | agents | Number of agents in the current execution. Labels: `workflow_name`. |
| `awp.memory.operations` | counter | ops | Memory read/write operations. Labels: `tier`, `operation` (read/write/search). |
| `awp.bus.messages` | counter | messages | Messages sent via the message bus. Labels: `channel`, `type`. |

### 2.3 Custom Metrics

Workflows MAY define custom metrics:

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

| Field | Type | Status | Description |
|-------|------|--------|-------------|
| `name` | string | REQUIRED | Metric name. SHOULD use dot notation. |
| `type` | string | REQUIRED | MUST be one of: `"counter"`, `"gauge"`, `"histogram"`. |
| `description` | string | REQUIRED | Human-readable description. |
| `labels` | list | OPTIONAL | Label keys for the metric. |
| `buckets` | list | OPTIONAL | Histogram bucket boundaries. Only for `"histogram"` type. |

---

## 3. Tracing

### 3.1 Configuration

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

| Field | Type | Status | Default | Description |
|-------|------|--------|---------|-------------|
| `enabled` | boolean | REQUIRED | — | Whether distributed tracing is active. |
| `exporter` | string | OPTIONAL | `"otlp"` | Trace exporter. MUST be one of: `"otlp"`, `"jaeger"`, `"zipkin"`, `"console"`, `"none"`. |
| `endpoint` | string | OPTIONAL | — | Exporter endpoint URL. |
| `propagation` | string | OPTIONAL | `"w3c"` | Context propagation format. MUST be one of: `"w3c"`, `"b3"`, `"jaeger"`. |
| `sampling` | object | OPTIONAL | — | Sampling configuration. |
| `sampling.strategy` | string | OPTIONAL | `"always_on"` | MUST be one of: `"always_on"`, `"always_off"`, `"parent_based"`, `"probability"`. |
| `sampling.rate` | float | OPTIONAL | `1.0` | Sampling rate for `"probability"` strategy. MUST be between 0.0 and 1.0. |

### 3.2 Span Hierarchy

AWP defines a standard span hierarchy that runtimes MUST follow:

```
workflow.run (root span)
├── agent.execute (one per agent)
│   ├── agent.build_context
│   ├── llm.call (one per LLM invocation)
│   │   ├── llm.prompt_construction
│   │   └── llm.inference
│   ├── tool.call (one per tool invocation)
│   │   ├── tool.validate_params
│   │   └── tool.execute
│   ├── memory.read
│   ├── memory.write
│   └── agent.parse_response
├── orchestrator.evaluate_condition
└── orchestrator.fan_out
```

### 3.3 Span Attributes

Each span MUST include:

| Attribute | Type | Description |
|-----------|------|-------------|
| `awp.workflow.name` | string | Workflow name from manifest. |
| `awp.workflow.version` | string | Workflow version. |
| `awp.run.id` | string | Unique run identifier. |

Agent spans MUST additionally include:

| Attribute | Type | Description |
|-----------|------|-------------|
| `awp.agent.id` | string | Agent identity. |
| `awp.agent.role` | string | Agent role. |
| `awp.agent.model` | string | Model name used. |

Tool spans MUST additionally include:

| Attribute | Type | Description |
|-----------|------|-------------|
| `awp.tool.name` | string | Tool FQN. |
| `awp.tool.status` | string | `"ok"` or `"error"`. |

LLM spans MUST additionally include:

| Attribute | Type | Description |
|-----------|------|-------------|
| `awp.llm.model` | string | Model identifier. |
| `awp.llm.tokens.input` | integer | Input token count. |
| `awp.llm.tokens.output` | integer | Output token count. |

### 3.4 W3C TraceContext Propagation

When `propagation` is `"w3c"`, the runtime MUST propagate trace context using the [W3C TraceContext](https://www.w3.org/TR/trace-context/) specification:

- The `traceparent` header MUST be propagated across agent boundaries.
- The `tracestate` header SHOULD be propagated.
- Cross-workflow calls (subworkflows) MUST propagate the trace context.

---

## 4. Logging

### 4.1 Configuration

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

### 4.2 Log Levels

AWP adopts standard log levels:

| Level | Description |
|-------|-------------|
| `DEBUG` | Detailed diagnostic information. |
| `INFO` | General operational messages. |
| `WARNING` | Unexpected but non-fatal conditions. |
| `ERROR` | Errors that prevent an operation from completing. |
| `CRITICAL` | Severe errors that may cause workflow termination. |

### 4.3 Log Formats

| Format | Description |
|--------|-------------|
| `json` | Structured JSON. Each log entry MUST include: `timestamp`, `level`, `message`, `ctx` (trace context). |
| `text` | Human-readable text with timestamp and level prefix. |
| `structured` | Key-value pairs optimized for log aggregation systems. |

### 4.4 Capture Flags

| Flag | Default | Description |
|------|---------|-------------|
| `agent_io` | `true` | Log agent input/output summaries. |
| `state_transitions` | `true` | Log state changes between agents. |
| `llm_prompts` | `true` | Log LLM prompts (SHOULD respect redaction). |
| `llm_responses` | `false` | Log full LLM responses. |
| `tool_calls` | `true` | Log tool invocations and parameters. |
| `tool_results` | `true` | Log tool return values. |

### 4.5 Redaction

The runtime MUST apply redaction rules before writing any log entry:

- `patterns`: Regular expressions matched against all string values. Matches are replaced with `[REDACTED]`.
- `fields`: Field names whose values are always replaced with `[REDACTED]` in log output.

Redaction MUST be applied to:
- Log messages
- Span attributes
- Metric labels
- Audit trail entries

---

## 5. Audit Trail

### 5.1 Configuration

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

| Field | Type | Status | Default | Description |
|-------|------|--------|---------|-------------|
| `enabled` | boolean | REQUIRED | — | Whether audit trail is active. |
| `integrity` | string | OPTIONAL | `"hash_chain"` | Integrity mechanism. MUST be one of: `"hash_chain"`, `"merkle_tree"`, `"none"`. |
| `hash_algorithm` | string | OPTIONAL | `"sha256"` | Hash algorithm. MUST be one of: `"sha256"`, `"sha384"`, `"sha512"`. |
| `storage` | object | REQUIRED | — | Storage configuration. |
| `retention` | object | OPTIONAL | — | Retention policy. |
| `access_control` | object | OPTIONAL | — | Access control for audit data. |

### 5.2 Hash-Chain Integrity

When `integrity` is `"hash_chain"`:

- Each audit entry MUST include a `prev_hash` field containing the hash of the previous entry.
- The first entry MUST have `prev_hash` set to a zero hash (all zeros).
- The runtime MUST compute `hash = H(prev_hash || entry_content)`.
- This provides tamper-evident logging: any modification to a previous entry invalidates all subsequent hashes.

### 5.3 Audit Events

The runtime MUST record the following events:

| Event | Trigger | Required Fields |
|-------|---------|-----------------|
| `workflow.start` | Workflow execution begins. | `run_id`, `workflow_name`, `workflow_version`, `timestamp` |
| `workflow.complete` | Workflow execution ends. | `run_id`, `status`, `duration`, `timestamp` |
| `agent.start` | Agent execution begins. | `run_id`, `agent_id`, `timestamp` |
| `agent.complete` | Agent execution ends. | `run_id`, `agent_id`, `status`, `duration`, `timestamp` |
| `agent.error` | Agent execution fails. | `run_id`, `agent_id`, `error_type`, `error_message`, `timestamp` |
| `tool.call` | Tool is invoked. | `run_id`, `agent_id`, `tool_name`, `timestamp` |
| `tool.result` | Tool returns. | `run_id`, `agent_id`, `tool_name`, `status`, `timestamp` |
| `state.change` | State is modified. | `run_id`, `agent_id`, `fields_changed`, `timestamp` |
| `memory.write` | Memory is modified. | `run_id`, `agent_id`, `tier`, `timestamp` |
| `security.event` | Security-relevant event. | `run_id`, `event_type`, `details`, `timestamp` |

### 5.4 Retention

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `max_age_days` | integer | `90` | Maximum age of audit entries before deletion. |
| `max_size_mb` | float | `100` | Maximum total size of audit storage. Oldest entries are deleted first. |

---

## 6. Health Checks

### 6.1 Readiness (Pre-Start)

Readiness checks verify that all prerequisites are met before workflow execution begins.

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

| Field | Type | Status | Description |
|-------|------|--------|-------------|
| `checks` | list | OPTIONAL | List of readiness checks. |
| `checks[].name` | string | REQUIRED | Check identifier. |
| `checks[].type` | string | REQUIRED | MUST be one of: `"http"`, `"filesystem"`, `"env"`, `"custom"`. |
| `checks[].timeout` | integer | OPTIONAL | Timeout in seconds. Default: 10. |

The runtime MUST execute all readiness checks before starting the workflow. If any check fails, the runtime MUST NOT start the workflow and MUST report which checks failed.

### 6.2 Liveness (Runtime)

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

| Field | Type | Status | Default | Description |
|-------|------|--------|---------|-------------|
| `interval` | integer | OPTIONAL | `30` | Seconds between liveness checks. |
| `timeout` | integer | OPTIONAL | `10` | Seconds before a check is considered failed. |
| `failure_threshold` | integer | OPTIONAL | `3` | Consecutive failures before the workflow is considered unhealthy. |
| `checks` | list | OPTIONAL | — | List of liveness checks. |

When the failure threshold is reached, the runtime SHOULD:
1. Log a CRITICAL-level message.
2. Record a `security.event` in the audit trail.
3. Optionally terminate the workflow based on configuration.

---

## 7. Complete Example

```yaml
observability:
  metrics:
    enabled: true
    exporter: otlp
    endpoint: "http://localhost:4317"
    interval: 30
    custom:
      - name: "research.sources_found"
        type: counter
        description: "Number of research sources discovered."
        labels:
          - agent_id

  tracing:
    enabled: true
    exporter: otlp
    endpoint: "http://localhost:4317"
    propagation: w3c
    sampling:
      strategy: parent_based
      rate: 1.0

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
      fields:
        - api_key
        - secret

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

  health:
    readiness:
      checks:
        - name: llm_provider
          type: http
          endpoint: "https://openrouter.ai/api/v1/models"
          timeout: 10
          expected_status: 200
        - name: env_vars
          type: env
          required:
            - OPENROUTER_API_KEY
    liveness:
      interval: 30
      timeout: 10
      failure_threshold: 3
```

---

## 8. Processing Rules

1. When `metrics.enabled` is `true`, the runtime MUST collect all built-in metrics listed in Section 2.2.
2. When `tracing.enabled` is `true`, the runtime MUST create spans following the hierarchy in Section 3.2.
3. The runtime MUST include all REQUIRED span attributes listed in Section 3.3.
4. Redaction MUST be applied before any log entry is written, exported, or displayed.
5. When `audit.enabled` is `true`, the runtime MUST record all events listed in Section 5.3.
6. When `audit.integrity` is `"hash_chain"`, each audit entry MUST include the hash of the previous entry.
7. Readiness checks MUST complete before workflow execution begins.
8. Liveness check failures MUST be logged at CRITICAL level.
