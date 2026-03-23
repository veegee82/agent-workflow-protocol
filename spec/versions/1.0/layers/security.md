# Security (Cross-Cutting Concern)

**AWP Specification v1.0.0 — Security**
**Status:** Draft Standard

---

## 1. Overview

Security is a cross-cutting concern that applies across all AWP layers. This document defines circuit breaker patterns, rate limiting, access control, secrets management, and security audit requirements. Security is configured in the `security` section of `workflow.awp.yaml`.

---

## 2. Circuit Breaker

The circuit breaker pattern prevents cascading failures by temporarily disabling agents or tools that are repeatedly failing.

### 2.1 Configuration

```yaml
security:
  circuit_breaker:
    enabled: true
    failure_threshold: 5
    reset_timeout: 60
    half_open_max: 2
    monitored_exceptions:
      - timeout
      - rate_limit
      - server_error
      - connection_error
```

### 2.2 Fields

| Field | Type | Status | Default | Description |
|-------|------|--------|---------|-------------|
| `enabled` | boolean | REQUIRED | — | Whether circuit breaker is active. |
| `failure_threshold` | integer | OPTIONAL | `5` | Number of consecutive failures before the circuit opens. |
| `reset_timeout` | integer | OPTIONAL | `60` | Seconds before the circuit transitions from open to half-open. |
| `half_open_max` | integer | OPTIONAL | `2` | Number of test requests allowed in half-open state. |
| `monitored_exceptions` | list | OPTIONAL | `["timeout", "server_error"]` | Exception types that count toward the failure threshold. |

### 2.3 State Machine

```
     success          failure_threshold reached
  ┌───────────┐      ┌───────────────────────┐
  │           ▼      ▼                       │
  │        CLOSED ──────────▶ OPEN           │
  │           ▲                 │             │
  │           │                 │ reset_timeout
  │           │                 ▼             │
  │           └──── HALF-OPEN ───────────────┘
  │                success       failure
  └────────────────────┘
```

- **CLOSED:** Normal operation. Failures are counted.
- **OPEN:** All requests are immediately rejected. No execution occurs.
- **HALF-OPEN:** A limited number of requests (`half_open_max`) are allowed through. If they succeed, the circuit closes. If any fail, the circuit reopens.

### 2.4 Scope

Circuit breakers MAY be applied at two levels:

- **Per-agent:** Monitors individual agent failures.
- **Per-tool:** Monitors individual tool call failures.

```yaml
security:
  circuit_breaker:
    enabled: true
    failure_threshold: 5
    per_tool:
      web.search:
        failure_threshold: 3
        reset_timeout: 120
```

---

## 3. Rate Limiting

Rate limiting prevents excessive resource consumption by agents and tools.

### 3.1 Configuration

```yaml
security:
  rate_limiting:
    per_agent:
      max_calls_per_minute: 60
      max_tokens_per_minute: 100000
    per_tool:
      max_calls_per_minute: 30
      overrides:
        web.search:
          max_calls_per_minute: 10
        shell.execute:
          max_calls_per_minute: 5
```

### 3.2 Per-Agent Rate Limits

| Field | Type | Status | Default | Description |
|-------|------|--------|---------|-------------|
| `max_calls_per_minute` | integer | OPTIONAL | `60` | Maximum LLM calls per agent per minute. |
| `max_tokens_per_minute` | integer | OPTIONAL | `100000` | Maximum tokens (input + output) per agent per minute. |

When a rate limit is exceeded, the runtime MUST:

1. Queue the request (if a queue is configured).
2. Or reject the request with a `rate_limit` error.
3. Record the event in the audit trail.

### 3.3 Per-Tool Rate Limits

| Field | Type | Status | Default | Description |
|-------|------|--------|---------|-------------|
| `max_calls_per_minute` | integer | OPTIONAL | `30` | Maximum tool calls per minute across all agents. |
| `overrides` | object | OPTIONAL | — | Per-tool overrides. Keys are tool FQNs. |

---

## 4. Access Control

### 4.1 Tool Permissions

Per-agent tool access is defined in Layer 2 (`capabilities.tools.allowed` and `capabilities.tools.denied`). The security layer adds enforcement requirements:

- The runtime MUST enforce tool ACLs before executing any tool call.
- A tool call from an agent not in the allowed list MUST be rejected.
- Rejected tool calls MUST be logged as `security.event` in the audit trail.

### 4.2 Channel ACL

Per-channel access is defined in Layer 3 (`communication.channels[].participants`). The security layer adds:

- The runtime MUST enforce channel ACLs before delivering any message.
- A message from an agent not in `participants.publishers` MUST be rejected.
- A subscription from an agent not in `participants.subscribers` MUST be rejected.
- ACL violations MUST be logged as `security.event` in the audit trail.

### 4.3 Sandbox Restrictions

Sandbox access is defined in Layer 2 (`capabilities.sandbox`). The security layer adds:

- The runtime MUST enforce filesystem and command restrictions within the sandbox.
- Any attempt to access a denied path or execute a denied command MUST be blocked.
- Sandbox violations MUST be logged as `security.event` in the audit trail.

### 4.4 Memory Access Control

Memory access is defined in Layer 4 (`memory.access_control`). The security layer adds:

- The runtime MUST enforce memory tier permissions before any read or write.
- An agent attempting to write to a tier where it has `read` or `none` access MUST be rejected.
- Memory access violations MUST be logged as `security.event` in the audit trail.

---

## 5. Secrets Management

### 5.1 Configuration

```yaml
security:
  secrets:
    backend: env
    options: {}
    never_log:
      - OPENROUTER_API_KEY
      - DATABASE_PASSWORD
      - AWS_SECRET_ACCESS_KEY
```

### 5.2 Fields

| Field | Type | Status | Default | Description |
|-------|------|--------|---------|-------------|
| `backend` | string | OPTIONAL | `"env"` | Secrets backend. MUST be one of: `"env"`, `"vault"`, `"aws_secrets"`. |
| `options` | object | OPTIONAL | `{}` | Backend-specific configuration. |
| `never_log` | list | OPTIONAL | `[]` | Environment variable names that MUST NOT appear in any log output. |

### 5.3 Backend: `env`

Secrets are read from environment variables.

- The runtime MUST read secrets from the process environment.
- Variables listed in `workflow.env` with `sensitive: true` are automatically added to `never_log`.

### 5.4 Backend: `vault`

Secrets are read from HashiCorp Vault.

```yaml
security:
  secrets:
    backend: vault
    options:
      address: "https://vault.example.com"
      auth_method: token
      secret_path: "secret/data/awp"
```

### 5.5 Backend: `aws_secrets`

Secrets are read from AWS Secrets Manager.

```yaml
security:
  secrets:
    backend: aws_secrets
    options:
      region: "us-east-1"
      secret_name: "awp/production"
```

### 5.6 Logging Rules

The runtime MUST enforce the following rules for sensitive data:

1. Values of variables listed in `never_log` MUST NOT appear in any log output, metric label, span attribute, or audit entry.
2. Fields listed in `state.sharing.sensitive_fields` (Layer 4) MUST be redacted in all observability output.
3. The `workflow.env` entries with `sensitive: true` MUST be treated identically to `never_log` entries.
4. Redaction MUST occur before the log entry is written, not after.

---

## 6. Security Audit

Security events MUST always be logged to the audit trail (Layer 6) regardless of the audit trail's `enabled` setting. If the audit trail is disabled, security events MUST still be logged to the application log at WARNING level or higher.

### 6.1 Security Event Types

| Event Type | Trigger | Severity |
|------------|---------|----------|
| `acl.tool.denied` | Agent attempted to call a denied tool. | WARNING |
| `acl.channel.denied` | Agent attempted to publish/subscribe to a denied channel. | WARNING |
| `acl.memory.denied` | Agent attempted to access a denied memory tier. | WARNING |
| `acl.sandbox.denied` | Sandbox attempted to access a denied path or command. | WARNING |
| `rate_limit.exceeded` | Agent or tool exceeded rate limit. | WARNING |
| `circuit_breaker.opened` | Circuit breaker transitioned to OPEN state. | WARNING |
| `circuit_breaker.half_open` | Circuit breaker transitioned to HALF-OPEN state. | INFO |
| `circuit_breaker.closed` | Circuit breaker transitioned to CLOSED state. | INFO |
| `secret.access` | A secret was accessed. | INFO |
| `secret.leak_prevented` | A secret value was redacted from output. | WARNING |
| `auth.failure` | Authentication to an external service failed. | ERROR |
| `integrity.violation` | Audit trail hash chain integrity check failed. | CRITICAL |

### 6.2 Security Event Format

```json
{
  "timestamp": "2026-03-23T14:30:00.000Z",
  "event_type": "acl.tool.denied",
  "severity": "WARNING",
  "run_id": "abc12345",
  "agent_id": "research_analyst",
  "details": {
    "tool": "shell.execute",
    "reason": "Tool not in agent's allowed list."
  }
}
```

---

## 7. Complete Example

```yaml
security:
  circuit_breaker:
    enabled: true
    failure_threshold: 5
    reset_timeout: 60
    half_open_max: 2
    monitored_exceptions:
      - timeout
      - rate_limit
      - server_error
    per_tool:
      web.search:
        failure_threshold: 3
        reset_timeout: 120

  rate_limiting:
    per_agent:
      max_calls_per_minute: 60
      max_tokens_per_minute: 100000
    per_tool:
      max_calls_per_minute: 30
      overrides:
        web.search:
          max_calls_per_minute: 10
        shell.execute:
          max_calls_per_minute: 5

  secrets:
    backend: env
    never_log:
      - OPENROUTER_API_KEY
      - DATABASE_PASSWORD

  audit:
    security_events_always_logged: true
```

---

## 8. Processing Rules

1. When `circuit_breaker.enabled` is `true`, the runtime MUST implement the circuit breaker state machine for all agents and tools.
2. Rate limits MUST be enforced before the request is executed, not after.
3. When a rate limit is exceeded, the runtime MUST return a `rate_limit` error and MUST NOT execute the request.
4. Tool ACL violations MUST be rejected and logged before the tool is invoked.
5. Secrets MUST be resolved at runtime and MUST NOT be stored in the workflow YAML files.
6. The `never_log` list MUST be enforced across all logging, tracing, metrics, and audit output.
7. Security events MUST be logged even when the general audit trail is disabled.
8. The circuit breaker MUST track failures independently per agent and per tool when `per_tool` overrides are configured.
