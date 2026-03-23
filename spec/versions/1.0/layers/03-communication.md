# Layer 3: Communication

**AWP Specification v1.0.0 — Layer 3**
**Status:** Draft Standard

---

## 1. Overview

Layer 3 defines the communication infrastructure for inter-agent messaging within an AWP workflow. Communication is configured in the `communication` section of `workflow.awp.yaml`. This layer enables agents to exchange messages outside the DAG execution flow, supporting patterns such as request-response, publish-subscribe, and pipeline processing.

---

## 2. Message Bus

The `communication.bus` section configures the message transport layer.

### 2.1 Fields

| Field | Type | Status | Default | Description |
|-------|------|--------|---------|-------------|
| `type` | string | REQUIRED | — | Bus implementation. MUST be one of: `"internal"`, `"redis"`, `"nats"`, `"kafka"`, `"rabbitmq"`. |
| `persistence` | boolean | OPTIONAL | `false` | Whether messages are persisted to durable storage. |
| `max_message_size` | integer | OPTIONAL | `65536` | Maximum message size in bytes. Runtime MUST reject messages exceeding this limit. |
| `delivery` | string | OPTIONAL | `"at_least_once"` | Delivery guarantee. MUST be one of: `"at_most_once"`, `"at_least_once"`, `"exactly_once"`. |
| `ordering` | string | OPTIONAL | `"fifo"` | Message ordering guarantee. MUST be one of: `"fifo"`, `"causal"`, `"none"`. |
| `connection` | object | OPTIONAL | — | Connection configuration for external bus implementations. |

### 2.2 Bus Type: `internal`

The `internal` bus type is the default in-process message bus. It MUST be supported by all AWP-conformant runtimes.

- Messages are stored in memory for the duration of the run.
- Delivery guarantee is `at_least_once`.
- Ordering is `fifo` per channel.
- Messages are discarded when the run completes unless `persistence` is `true`.

### 2.3 Bus Type: External (`redis`, `nats`, `kafka`, `rabbitmq`)

External bus types require a `connection` object:

| Field | Type | Status | Description |
|-------|------|--------|-------------|
| `connection.url` | string | REQUIRED | Connection URL or endpoint. |
| `connection.auth` | object | OPTIONAL | Authentication credentials. MUST be marked sensitive. |
| `connection.options` | object | OPTIONAL | Provider-specific connection options. |

---

## 3. Channels

The `communication.channels` section defines named communication channels.

### 3.1 Channel Definition

Each channel MUST have:

| Field | Type | Status | Default | Description |
|-------|------|--------|---------|-------------|
| `name` | string | REQUIRED | — | Unique channel name within the workflow. |
| `type` | string | REQUIRED | — | MUST be one of: `"direct"`, `"broadcast"`, `"topic"`, `"request_response"`. |
| `participants` | object | OPTIONAL | — | Access control for the channel. |
| `participants.publishers` | list | OPTIONAL | `["*"]` | Agent IDs that MAY publish to this channel. `"*"` means all agents. |
| `participants.subscribers` | list | OPTIONAL | `["*"]` | Agent IDs that MAY subscribe to this channel. `"*"` means all agents. |
| `schema` | object | OPTIONAL | — | JSON Schema for message content validation. If present, the runtime MUST validate messages against this schema. |
| `acl` | object | OPTIONAL | — | Fine-grained access control list. |

### 3.2 Channel Types

#### 3.2.1 `direct`

Point-to-point messaging between two specific agents.

- The sender MUST specify the recipient agent ID in the `to` field.
- Only the designated recipient MAY receive the message.
- The runtime MUST reject messages where `to` does not match a valid agent ID.

#### 3.2.2 `broadcast`

One-to-many messaging where all subscribers receive every message.

- The sender publishes to the channel.
- All agents listed in `participants.subscribers` MUST receive the message.
- The `to` field in the envelope SHOULD be set to the channel name.

#### 3.2.3 `topic`

Topic-based publish-subscribe with filtering.

- Messages include a `metadata.tags` field for topic matching.
- Subscribers MAY filter messages based on tags.
- The runtime MUST deliver messages only to subscribers whose filters match.

#### 3.2.4 `request_response`

Synchronous-style request-response communication.

- The sender sends a request and waits for a response.
- The `reply_to` field in the envelope MUST be set to a unique correlation address.
- The responder MUST set `correlation_id` to match the request's `id`.
- The runtime SHOULD enforce a timeout for responses.

---

## 4. Message Envelope

Every message on the bus MUST conform to the AWP Message Envelope format.

### 4.1 Envelope Fields

| Field | Type | Status | Description |
|-------|------|--------|-------------|
| `id` | string | REQUIRED | Unique message identifier. MUST be a UUID v7 (time-ordered). |
| `timestamp` | string | REQUIRED | ISO 8601 timestamp with timezone. MUST be UTC. |
| `version` | string | REQUIRED | Envelope schema version. MUST be `"1.0"`. |
| `from` | string | REQUIRED | Agent ID of the sender. |
| `to` | string | REQUIRED | Agent ID of the recipient, channel name, or `"*"` for broadcast. |
| `channel` | string | OPTIONAL | Channel name, if the message is sent via a named channel. |
| `reply_to` | string | OPTIONAL | Address for responses. REQUIRED for `request_response` type. |
| `type` | string | REQUIRED | MUST be one of: `"request"`, `"response"`, `"event"`, `"error"`, `"ack"`. |
| `correlation_id` | string | OPTIONAL | ID of the message this is responding to. REQUIRED for `type: "response"`. |
| `content_type` | string | OPTIONAL | MIME type of the content. Default: `"application/json"`. |
| `content` | any | REQUIRED | The message payload. Type determined by `content_type`. |
| `metadata` | object | OPTIONAL | Additional metadata. |

### 4.2 Metadata Fields

| Field | Type | Status | Description |
|-------|------|--------|-------------|
| `metadata.priority` | string | OPTIONAL | Priority level: `"low"`, `"normal"`, `"high"`, `"critical"`. Default: `"normal"`. |
| `metadata.ttl` | integer | OPTIONAL | Time-to-live in seconds. Messages older than TTL SHOULD be discarded. |
| `metadata.requires_ack` | boolean | OPTIONAL | Whether the sender expects an acknowledgment. Default: `false`. |
| `metadata.trace_id` | string | OPTIONAL | Distributed tracing ID for correlation with observability. |
| `metadata.tags` | list | OPTIONAL | Topic tags for filtering in `topic` channels. |

### 4.3 Envelope Example

```json
{
  "id": "01912f3e-7b6c-7def-8abc-1234567890ab",
  "timestamp": "2026-03-23T14:30:00.000Z",
  "version": "1.0",
  "from": "research_analyst",
  "to": "report_writer",
  "channel": "research_results",
  "type": "event",
  "content_type": "application/json",
  "content": {
    "topic": "quantum computing",
    "findings": [
      {"title": "Recent advances", "summary": "...", "confidence": 0.92}
    ]
  },
  "metadata": {
    "priority": "normal",
    "ttl": 3600,
    "requires_ack": false,
    "trace_id": "abc123def456",
    "tags": ["research", "quantum"]
  }
}
```

---

## 5. Messaging Patterns

### 5.1 Request-Response

Synchronous-style interaction between two agents.

```
Agent A                          Agent B
   │                                │
   │──── request (reply_to=A) ────▶│
   │                                │
   │◀─── response (corr_id=req) ───│
   │                                │
```

- The requesting agent MUST set `type: "request"` and `reply_to`.
- The responding agent MUST set `type: "response"` and `correlation_id` matching the request `id`.
- The runtime SHOULD enforce a configurable timeout. If the timeout expires, the runtime MUST deliver a timeout error to the requester.

### 5.2 Publish-Subscribe

One-to-many event distribution.

```
Agent A                   Channel "events"              Agent B, C, D
   │                          │                             │
   │──── event ─────────────▶ │ ─── deliver ──────────────▶ │
   │                          │                             │
```

- The publisher sets `to` to the channel name.
- All subscribers receive the message.
- No response is expected.

### 5.3 Pipeline

Sequential message passing through a chain of agents.

```
Agent A ──▶ Agent B ──▶ Agent C ──▶ Agent D
```

- Each agent in the pipeline receives output from the previous agent.
- Messages flow through named channels or direct addressing.
- The pipeline pattern is typically implemented via the DAG in Layer 5, but MAY also be implemented via the message bus for dynamic routing.

### 5.4 Scatter-Gather

Fan-out a request to multiple agents, then aggregate responses.

```
                    ┌──▶ Agent B ──┐
Agent A ────────────┼──▶ Agent C ──┼──▶ Agent A (aggregate)
                    └──▶ Agent D ──┘
```

- The coordinator sends requests to multiple agents using `type: "request"`.
- Each target responds independently.
- The coordinator collects responses, applying a configurable timeout.
- The runtime SHOULD support a `min_responses` configuration to proceed with partial results.

---

## 6. Complete Example

```yaml
communication:
  bus:
    type: internal
    persistence: true
    max_message_size: 131072
    delivery: at_least_once
    ordering: fifo

  channels:
    - name: research_results
      type: direct
      participants:
        publishers:
          - research_analyst
        subscribers:
          - report_writer
      schema:
        type: object
        required:
          - topic
          - findings
        properties:
          topic:
            type: string
          findings:
            type: array
            items:
              type: object

    - name: status_updates
      type: broadcast
      participants:
        publishers:
          - "*"
        subscribers:
          - "*"

    - name: review_requests
      type: request_response
      participants:
        publishers:
          - report_writer
        subscribers:
          - quality_reviewer

    - name: domain_events
      type: topic
      participants:
        publishers:
          - "*"
        subscribers:
          - research_analyst
          - report_writer
```

---

## 7. Processing Rules

1. A runtime implementing Layer 3 MUST support the `internal` bus type.
2. External bus types (redis, nats, kafka, rabbitmq) are OPTIONAL; a runtime MAY support any subset.
3. The runtime MUST validate that `from` matches the agent actually sending the message.
4. The runtime MUST enforce channel ACLs: a message from an agent not in `participants.publishers` MUST be rejected.
5. If `schema` is defined on a channel, the runtime MUST validate `content` against the schema before delivery.
6. Messages with `metadata.ttl` that have expired SHOULD be discarded rather than delivered.
7. When `metadata.requires_ack` is `true`, the runtime SHOULD track acknowledgment and notify the sender on timeout.
