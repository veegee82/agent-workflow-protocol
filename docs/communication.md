# Communication Reference

Layer 3 defines the communication infrastructure for inter-agent messaging within an AWP workflow. Communication is configured in the `communication` section of [workflow.awp.yaml](manifest.md). This layer enables agents to exchange messages outside the DAG execution flow.

## When to Use Communication vs State Sharing

- **State sharing** (Layer 4) is the primary mechanism for passing data between agents in the DAG. It is implicit -- the orchestrator manages it based on `depends_on` and `share_output`.
- **Communication** (Layer 3) is for messaging outside the DAG: real-time notifications, dynamic routing, request-response patterns between agents that do not have a direct DAG dependency.

Use communication when agents need to collaborate dynamically rather than following a fixed execution order.

## Message Bus

The `communication.bus` section configures the message transport.

### Fields

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `type` | string | Yes | -- | Bus implementation: `"internal"`, `"redis"`, `"nats"`, `"kafka"`, or `"rabbitmq"`. |
| `persistence` | boolean | No | `false` | Whether messages are persisted to durable storage. |
| `max_message_size` | integer | No | `65536` | Maximum message size in bytes. |
| `delivery` | string | No | `"at_least_once"` | Delivery guarantee: `"at_most_once"`, `"at_least_once"`, or `"exactly_once"`. |
| `ordering` | string | No | `"fifo"` | Message ordering: `"fifo"`, `"causal"`, or `"none"`. |
| `connection` | object | No | -- | Connection configuration for external bus implementations. |

### Bus Type: `internal`

The default in-process message bus. All AWP-conformant runtimes must support this type.

- Messages are stored in memory for the duration of the run.
- Delivery guarantee is `at_least_once`.
- Ordering is `fifo` per channel.
- Messages are discarded when the run completes unless `persistence` is `true`.

### External Bus Types

External buses (`redis`, `nats`, `kafka`, `rabbitmq`) require a `connection` object:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `connection.url` | string | Yes | Connection URL or endpoint. |
| `connection.auth` | object | No | Authentication credentials. Must be marked sensitive. |
| `connection.options` | object | No | Provider-specific connection options. |

## Channels

The `communication.channels` section defines named communication channels.

### Channel Definition

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `name` | string | Yes | -- | Unique channel name within the workflow. |
| `type` | string | Yes | -- | `"direct"`, `"broadcast"`, `"topic"`, or `"request_response"`. |
| `participants.publishers` | list | No | `["*"]` | Agent IDs that may publish. `"*"` means all agents. |
| `participants.subscribers` | list | No | `["*"]` | Agent IDs that may subscribe. `"*"` means all agents. |
| `schema` | object | No | -- | JSON Schema for message content validation. |
| `acl` | object | No | -- | Fine-grained access control list. |

### Channel Types

#### `direct`

Point-to-point messaging between two specific agents.

- The sender must specify the recipient agent ID in the `to` field.
- Only the designated recipient receives the message.

#### `broadcast`

One-to-many messaging where all subscribers receive every message.

- The sender publishes to the channel.
- All agents listed in `participants.subscribers` receive the message.

#### `topic`

Topic-based publish-subscribe with filtering.

- Messages include `metadata.tags` for topic matching.
- Subscribers may filter messages based on tags.

#### `request_response`

Synchronous-style request-response communication.

- The sender sends a request and waits for a response.
- The `reply_to` field must be set to a unique correlation address.
- The responder must set `correlation_id` to match the request's `id`.
- The runtime should enforce a timeout for responses.

## Message Envelope

Every message on the bus must conform to the AWP Message Envelope format.

### Envelope Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | string | Yes | Unique message identifier (UUID v7, time-ordered). |
| `timestamp` | string | Yes | ISO 8601 timestamp (UTC). |
| `version` | string | Yes | Envelope schema version. Must be `"1.0"`. |
| `from` | string | Yes | Agent ID of the sender. |
| `to` | string | Yes | Recipient agent ID, channel name, or `"*"` for broadcast. |
| `channel` | string | No | Channel name, if sent via a named channel. |
| `reply_to` | string | No | Address for responses. Required for `request_response`. |
| `type` | string | Yes | `"request"`, `"response"`, `"event"`, `"error"`, or `"ack"`. |
| `correlation_id` | string | No | ID of the message this is responding to. Required for `type: "response"`. |
| `content_type` | string | No | MIME type. Default: `"application/json"`. |
| `content` | any | Yes | The message payload. |
| `metadata` | object | No | Additional metadata. |

### Metadata Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `metadata.priority` | string | `"normal"` | `"low"`, `"normal"`, `"high"`, or `"critical"`. |
| `metadata.ttl` | integer | -- | Time-to-live in seconds. Expired messages should be discarded. |
| `metadata.requires_ack` | boolean | `false` | Whether the sender expects an acknowledgment. |
| `metadata.trace_id` | string | -- | Distributed tracing ID for correlation with [observability](observability.md). |
| `metadata.tags` | list | -- | Topic tags for filtering in `topic` channels. |

### Envelope Example

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

## Communication Patterns

### Request-Response

Synchronous-style interaction between two agents.

<svg viewBox="0 0 420 120" xmlns="http://www.w3.org/2000/svg" font-family="system-ui, -apple-system, sans-serif" font-size="12">
<rect x="30" y="10" width="100" height="36" rx="6" fill="#dce6f7" stroke="#4a6fa5" stroke-width="1.5"/>
  <text x="80" y="33" text-anchor="middle" font-weight="600" fill="#2a3f5f">Agent A</text>
  <rect x="280" y="10" width="100" height="36" rx="6" fill="#d5e8d4" stroke="#5b8c5a" stroke-width="1.5"/>
  <text x="330" y="33" text-anchor="middle" font-weight="600" fill="#2d5a2d">Agent B</text>
  <line x1="80" y1="48" x2="80" y2="110" stroke="#ccc" stroke-width="1" stroke-dasharray="3,3"/>
  <line x1="330" y1="48" x2="330" y2="110" stroke="#ccc" stroke-width="1" stroke-dasharray="3,3"/>
  <line x1="82" y1="60" x2="324.0" y2="60.0" stroke="#4a6fa5" stroke-width="1.5"/>
  <polygon points="326.0,60.0 320.0,63.0 320.0,57.0" fill="#4a6fa5"/>
  <text x="205" y="55" text-anchor="middle" fill="#4a6fa5" font-size="11">request (reply_to=A)</text>
  <line x1="328" y1="90" x2="86.0" y2="90.0" stroke="#27ae60" stroke-width="1.5"/>
  <polygon points="84.0,90.0 90.0,87.0 90.0,93.0" fill="#27ae60"/>
  <text x="205" y="85" text-anchor="middle" fill="#27ae60" font-size="11">response (corr_id=req)</text>
</svg>

- The requester sets `type: "request"` and `reply_to`.
- The responder sets `type: "response"` and `correlation_id` matching the request `id`.
- The runtime should enforce a configurable timeout.

### Publish-Subscribe

One-to-many event distribution.

<svg viewBox="0 0 500 100" xmlns="http://www.w3.org/2000/svg" font-family="system-ui, -apple-system, sans-serif" font-size="12">
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
  <line x1="107" y1="48" x2="161.0" y2="48.0" stroke="#7b4ea3" stroke-width="1.5"/>
  <polygon points="163.0,48.0 157.0,51.0 157.0,45.0" fill="#7b4ea3"/>
  <line x1="307" y1="35" x2="361.1" y2="22.5" stroke="#7b4ea3" stroke-width="1.2"/>
  <polygon points="363.0,22.0 357.8,26.3 356.5,20.4" fill="#7b4ea3"/>
  <line x1="307" y1="48" x2="361.0" y2="48.0" stroke="#7b4ea3" stroke-width="1.2"/>
  <polygon points="363.0,48.0 357.0,51.0 357.0,45.0" fill="#7b4ea3"/>
  <line x1="307" y1="60" x2="361.1" y2="73.5" stroke="#7b4ea3" stroke-width="1.2"/>
  <polygon points="363.0,74.0 356.5,75.5 357.9,69.6" fill="#7b4ea3"/>
</svg>

- The publisher sets `to` to the channel name.
- All subscribers receive the message.
- No response is expected.

### Pipeline

Sequential message passing through a chain of agents.

<svg viewBox="0 0 500 50" xmlns="http://www.w3.org/2000/svg" font-family="system-ui, -apple-system, sans-serif" font-size="12">
<rect x="10" y="10" width="80" height="30" rx="5" fill="#dce6f7" stroke="#4a6fa5" stroke-width="1.2"/>
  <text x="50" y="30" text-anchor="middle" font-weight="600" fill="#2a3f5f" font-size="11">Agent A</text>
  <rect x="130" y="10" width="80" height="30" rx="5" fill="#d5e8d4" stroke="#5b8c5a" stroke-width="1.2"/>
  <text x="170" y="30" text-anchor="middle" font-weight="600" fill="#2d5a2d" font-size="11">Agent B</text>
  <rect x="250" y="10" width="80" height="30" rx="5" fill="#fef3cd" stroke="#d4a017" stroke-width="1.2"/>
  <text x="290" y="30" text-anchor="middle" font-weight="600" fill="#856404" font-size="11">Agent C</text>
  <rect x="370" y="10" width="80" height="30" rx="5" fill="#e8d5f5" stroke="#7b4ea3" stroke-width="1.2"/>
  <text x="410" y="30" text-anchor="middle" font-weight="600" fill="#5a2d82" font-size="11">Agent D</text>
  <line x1="92" y1="25" x2="126.0" y2="25.0" stroke="#4a6fa5" stroke-width="1.5"/>
  <polygon points="128.0,25.0 122.0,28.0 122.0,22.0" fill="#4a6fa5"/>
  <line x1="212" y1="25" x2="246.0" y2="25.0" stroke="#4a6fa5" stroke-width="1.5"/>
  <polygon points="248.0,25.0 242.0,28.0 242.0,22.0" fill="#4a6fa5"/>
  <line x1="332" y1="25" x2="366.0" y2="25.0" stroke="#4a6fa5" stroke-width="1.5"/>
  <polygon points="368.0,25.0 362.0,28.0 362.0,22.0" fill="#4a6fa5"/>
</svg>

Each agent receives output from the previous agent. This pattern is typically implemented via the DAG in [orchestration](orchestration.md) but may also use the message bus for dynamic routing.

### Scatter-Gather

Fan-out a request to multiple agents, then aggregate responses.

<svg viewBox="0 0 480 120" xmlns="http://www.w3.org/2000/svg" font-family="system-ui, -apple-system, sans-serif" font-size="11">
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
  <line x1="92" y1="50" x2="156.2" y2="18.9" stroke="#4a6fa5" stroke-width="1.2"/>
  <polygon points="158.0,18.0 153.9,23.3 151.3,17.9" fill="#4a6fa5"/>
  <line x1="92" y1="55" x2="156.0" y2="55.0" stroke="#4a6fa5" stroke-width="1.2"/>
  <polygon points="158.0,55.0 152.0,58.0 152.0,52.0" fill="#4a6fa5"/>
  <line x1="92" y1="60" x2="156.2" y2="92.1" stroke="#4a6fa5" stroke-width="1.2"/>
  <polygon points="158.0,93.0 151.3,93.0 154.0,87.6" fill="#4a6fa5"/>
  <line x1="242" y1="18" x2="316.2" y2="49.2" stroke="#27ae60" stroke-width="1.2"/>
  <polygon points="318.0,50.0 311.3,50.4 313.6,44.9" fill="#27ae60"/>
  <line x1="242" y1="55" x2="316.0" y2="55.0" stroke="#27ae60" stroke-width="1.2"/>
  <polygon points="318.0,55.0 312.0,58.0 312.0,52.0" fill="#27ae60"/>
  <line x1="242" y1="93" x2="316.2" y2="60.8" stroke="#27ae60" stroke-width="1.2"/>
  <polygon points="318.0,60.0 313.7,65.1 311.3,59.6" fill="#27ae60"/>
</svg>

- The coordinator sends requests to multiple agents.
- Each target responds independently.
- The coordinator collects responses with a configurable timeout.

## Complete Example

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

## Processing Rules

1. A runtime implementing Layer 3 must support the `internal` bus type.
2. External bus types are optional; a runtime may support any subset.
3. The runtime must validate that `from` matches the agent actually sending the message.
4. The runtime must enforce channel ACLs: messages from unauthorized publishers must be rejected.
5. If `schema` is defined on a channel, the runtime must validate `content` against the schema before delivery. See [R15](validation.md).
6. Messages with expired `metadata.ttl` should be discarded rather than delivered.
7. When `metadata.requires_ack` is `true`, the runtime should track acknowledgment and notify the sender on timeout.
