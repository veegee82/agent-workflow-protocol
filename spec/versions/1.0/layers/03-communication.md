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

<svg viewBox="0 0 420 120" xmlns="http://www.w3.org/2000/svg" font-family="system-ui, -apple-system, sans-serif" font-size="12">
  <defs><marker id="s1" markerWidth="8" markerHeight="6" refX="8" refY="3" orient="auto"><path d="M0,0 L8,3 L0,6" fill="#4a6fa5"/></marker><marker id="s2" markerWidth="8" markerHeight="6" refX="8" refY="3" orient="auto"><path d="M0,0 L8,3 L0,6" fill="#27ae60"/></marker></defs>
  <rect x="30" y="10" width="100" height="36" rx="6" fill="#dce6f7" stroke="#4a6fa5" stroke-width="1.5"/>
  <text x="80" y="33" text-anchor="middle" font-weight="600" fill="#2a3f5f">Agent A</text>
  <rect x="280" y="10" width="100" height="36" rx="6" fill="#d5e8d4" stroke="#5b8c5a" stroke-width="1.5"/>
  <text x="330" y="33" text-anchor="middle" font-weight="600" fill="#2d5a2d">Agent B</text>
  <line x1="80" y1="48" x2="80" y2="110" stroke="#ccc" stroke-width="1" stroke-dasharray="3,3"/>
  <line x1="330" y1="48" x2="330" y2="110" stroke="#ccc" stroke-width="1" stroke-dasharray="3,3"/>
  <line x1="82" y1="65" x2="326" y2="65" stroke="#4a6fa5" stroke-width="1.5" marker-end="url(#s1)"/>
  <text x="205" y="60" text-anchor="middle" fill="#4a6fa5" font-size="11">request (reply_to=A)</text>
  <line x1="328" y1="90" x2="84" y2="90" stroke="#27ae60" stroke-width="1.5" marker-end="url(#s2)"/>
  <text x="205" y="85" text-anchor="middle" fill="#27ae60" font-size="11">response (corr_id=req)</text>
</svg>

- The requesting agent MUST set `type: "request"` and `reply_to`.
- The responding agent MUST set `type: "response"` and `correlation_id` matching the request `id`.
- The runtime SHOULD enforce a configurable timeout. If the timeout expires, the runtime MUST deliver a timeout error to the requester.

### 5.2 Publish-Subscribe

One-to-many event distribution.

<svg viewBox="0 0 500 100" xmlns="http://www.w3.org/2000/svg" font-family="system-ui, -apple-system, sans-serif" font-size="12">
  <defs><marker id="s3" markerWidth="8" markerHeight="6" refX="8" refY="3" orient="auto"><path d="M0,0 L8,3 L0,6" fill="#7b4ea3"/></marker></defs>
  <rect x="15" y="30" width="90" height="36" rx="6" fill="#dce6f7" stroke="#4a6fa5" stroke-width="1.5"/>
  <text x="60" y="53" text-anchor="middle" font-weight="600" fill="#2a3f5f">Agent A</text>
  <rect x="165" y="20" width="140" height="56" rx="8" fill="#e8d5f5" stroke="#7b4ea3" stroke-width="1.5"/>
  <text x="235" y="45" text-anchor="middle" font-weight="600" fill="#5a2d82">Channel</text>
  <text x="235" y="62" text-anchor="middle" fill="#7b4ea3" font-size="11">"events"</text>
  <rect x="365" y="12" width="110" height="20" rx="4" fill="#d5e8d4" stroke="#5b8c5a" stroke-width="1"/>
  <text x="420" y="26" text-anchor="middle" fill="#2d5a2d" font-size="11">Agent B</text>
  <rect x="365" y="38" width="110" height="20" rx="4" fill="#d5e8d4" stroke="#5b8c5a" stroke-width="1"/>
  <text x="420" y="52" text-anchor="middle" fill="#2d5a2d" font-size="11">Agent C</text>
  <rect x="365" y="64" width="110" height="20" rx="4" fill="#d5e8d4" stroke="#5b8c5a" stroke-width="1"/>
  <text x="420" y="78" text-anchor="middle" fill="#2d5a2d" font-size="11">Agent D</text>
  <line x1="107" y1="48" x2="163" y2="48" stroke="#7b4ea3" stroke-width="1.5" marker-end="url(#s3)"/>
  <line x1="307" y1="35" x2="363" y2="22" stroke="#7b4ea3" stroke-width="1.2" marker-end="url(#s3)"/>
  <line x1="307" y1="48" x2="363" y2="48" stroke="#7b4ea3" stroke-width="1.2" marker-end="url(#s3)"/>
  <line x1="307" y1="60" x2="363" y2="74" stroke="#7b4ea3" stroke-width="1.2" marker-end="url(#s3)"/>
</svg>

- The publisher sets `to` to the channel name.
- All subscribers receive the message.
- No response is expected.

### 5.3 Pipeline

Sequential message passing through a chain of agents.

<svg viewBox="0 0 500 50" xmlns="http://www.w3.org/2000/svg" font-family="system-ui, -apple-system, sans-serif" font-size="12">
  <defs><marker id="s4" markerWidth="8" markerHeight="6" refX="8" refY="3" orient="auto"><path d="M0,0 L8,3 L0,6" fill="#4a6fa5"/></marker></defs>
  <rect x="10" y="10" width="80" height="30" rx="5" fill="#dce6f7" stroke="#4a6fa5" stroke-width="1.2"/>
  <text x="50" y="30" text-anchor="middle" font-weight="600" fill="#2a3f5f" font-size="11">Agent A</text>
  <rect x="130" y="10" width="80" height="30" rx="5" fill="#d5e8d4" stroke="#5b8c5a" stroke-width="1.2"/>
  <text x="170" y="30" text-anchor="middle" font-weight="600" fill="#2d5a2d" font-size="11">Agent B</text>
  <rect x="250" y="10" width="80" height="30" rx="5" fill="#fef3cd" stroke="#d4a017" stroke-width="1.2"/>
  <text x="290" y="30" text-anchor="middle" font-weight="600" fill="#856404" font-size="11">Agent C</text>
  <rect x="370" y="10" width="80" height="30" rx="5" fill="#e8d5f5" stroke="#7b4ea3" stroke-width="1.2"/>
  <text x="410" y="30" text-anchor="middle" font-weight="600" fill="#5a2d82" font-size="11">Agent D</text>
  <line x1="92" y1="25" x2="128" y2="25" stroke="#4a6fa5" stroke-width="1.5" marker-end="url(#s4)"/>
  <line x1="212" y1="25" x2="248" y2="25" stroke="#4a6fa5" stroke-width="1.5" marker-end="url(#s4)"/>
  <line x1="332" y1="25" x2="368" y2="25" stroke="#4a6fa5" stroke-width="1.5" marker-end="url(#s4)"/>
</svg>

- Each agent in the pipeline receives output from the previous agent.
- Messages flow through named channels or direct addressing.
- The pipeline pattern is typically implemented via the DAG in Layer 5, but MAY also be implemented via the message bus for dynamic routing.

### 5.4 Scatter-Gather

Fan-out a request to multiple agents, then aggregate responses.

<svg viewBox="0 0 480 120" xmlns="http://www.w3.org/2000/svg" font-family="system-ui, -apple-system, sans-serif" font-size="11">
  <defs><marker id="s5" markerWidth="7" markerHeight="5" refX="7" refY="2.5" orient="auto"><path d="M0,0 L7,2.5 L0,5" fill="#4a6fa5"/></marker></defs>
  <rect x="10" y="40" width="80" height="30" rx="5" fill="#dce6f7" stroke="#4a6fa5" stroke-width="1.2"/>
  <text x="50" y="60" text-anchor="middle" font-weight="600" fill="#2a3f5f">Agent A</text>
  <rect x="160" y="5" width="80" height="26" rx="5" fill="#d5e8d4" stroke="#5b8c5a" stroke-width="1"/>
  <text x="200" y="22" text-anchor="middle" fill="#2d5a2d">Agent B</text>
  <rect x="160" y="42" width="80" height="26" rx="5" fill="#d5e8d4" stroke="#5b8c5a" stroke-width="1"/>
  <text x="200" y="59" text-anchor="middle" fill="#2d5a2d">Agent C</text>
  <rect x="160" y="80" width="80" height="26" rx="5" fill="#d5e8d4" stroke="#5b8c5a" stroke-width="1"/>
  <text x="200" y="97" text-anchor="middle" fill="#2d5a2d">Agent D</text>
  <rect x="320" y="40" width="130" height="30" rx="5" fill="#fef3cd" stroke="#d4a017" stroke-width="1.2"/>
  <text x="385" y="60" text-anchor="middle" font-weight="600" fill="#856404">A (aggregate)</text>
  <line x1="92" y1="50" x2="158" y2="18" stroke="#4a6fa5" stroke-width="1.2" marker-end="url(#s5)"/>
  <line x1="92" y1="55" x2="158" y2="55" stroke="#4a6fa5" stroke-width="1.2" marker-end="url(#s5)"/>
  <line x1="92" y1="60" x2="158" y2="93" stroke="#4a6fa5" stroke-width="1.2" marker-end="url(#s5)"/>
  <line x1="242" y1="18" x2="318" y2="50" stroke="#27ae60" stroke-width="1.2" marker-end="url(#s5)"/>
  <line x1="242" y1="55" x2="318" y2="55" stroke="#27ae60" stroke-width="1.2" marker-end="url(#s5)"/>
  <line x1="242" y1="93" x2="318" y2="60" stroke="#27ae60" stroke-width="1.2" marker-end="url(#s5)"/>
</svg>

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
