# AWP Protocol Reference

Complete documentation for the Agent Workflow Protocol (AWP) v1.0.0.

## Reading Order

| # | Document | Description |
|---|----------|-------------|
| 1 | [overview.md](overview.md) | What AWP is, why it exists, and its design principles |
| 2 | [layer-model.md](layer-model.md) | The 7-layer architecture and how layers relate |
| 3 | [manifest.md](manifest.md) | `workflow.awp.yaml` field reference |
| 4 | [agent.md](agent.md) | `agent.awp.yaml` field reference |
| 5 | [orchestration.md](orchestration.md) | DAG engine, execution modes, loops, error handling |
| 6 | [tools.md](tools.md) | MCP tools, custom tools, tool result format |
| 7 | [communication.md](communication.md) | Message bus, channels, messaging patterns |
| 8 | [memory.md](memory.md) | 4-tier memory system and state sharing |
| 9 | [observability.md](observability.md) | Metrics, tracing, audit trails, health checks |
| 10 | [security.md](security.md) | Circuit breaker, rate limiting, access control |
| 11 | [compliance.md](compliance.md) | Autonomy levels A0 through A4 |
| 12 | [validation.md](validation.md) | Validation rules R1 through R18 |
| 13 | [file-structure.md](file-structure.md) | Required directory layout |
| 14 | [packaging.md](packaging.md) | `.awp.zip` format and ClawHub publishing |
| 15 | [runtime.md](runtime.md) | AWPAgent interface, standalone runtime, WorkflowRunner |
| 16 | [skill-system.md](skill-system.md) | Build skill, adapters, extensions, ClawHub |

## Quick Start

If you are new to AWP, start with [overview.md](overview.md) to understand the motivation, then read [layer-model.md](layer-model.md) to see how the protocol is structured.

To build a workflow, you need at minimum:
- A [manifest](manifest.md) (`workflow.awp.yaml`)
- One or more [agent configs](agent.md) (`agent.awp.yaml`)
- An [orchestration graph](orchestration.md)

For the normative specification with RFC 2119 language, see `spec/versions/1.0/`.

For runnable examples, see `examples/`.
