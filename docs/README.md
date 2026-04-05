# AWP Protocol Reference

Complete documentation for the Agent Workflow Protocol (AWP) v1.0.0.

## Reading Order

| # | Document | Description |
|---|----------|-------------|
| 1 | [overview.md](overview.md) | What AWP is, why it exists, and its design principles |
| 2 | [architecture.md](architecture.md) | Architecture, design decisions, and framework comparison |
| 3 | [layer-model.md](layer-model.md) | The 7-layer architecture and how layers relate |
| 4 | [manifest.md](manifest.md) | `workflow.awp.yaml` field reference |
| 5 | [agent.md](agent.md) | `agent.awp.yaml` field reference |
| 6 | [orchestration.md](orchestration.md) | DAG engine, execution modes, loops, error handling |
| 7 | [tools.md](tools.md) | MCP tools, custom tools, tool result format |
| 8 | [communication.md](communication.md) | Message bus, channels, messaging patterns |
| 9 | [memory.md](memory.md) | 4-tier memory system and state sharing |
| 10 | [observability.md](observability.md) | Metrics, tracing, audit trails, health checks |
| 11 | [security.md](security.md) | Circuit breaker, rate limiting, access control |
| 12 | [compliance.md](compliance.md) | Autonomy levels A0 through A4 |
| 13 | [validation.md](validation.md) | Validation rules R1 through R30 |
| 14 | [file-structure.md](file-structure.md) | Required directory layout |
| 15 | [packaging.md](packaging.md) | `.awp.zip` format and ClawHub publishing |
| 16 | [runtime.md](runtime.md) | AWPAgent interface, standalone runtime, WorkflowRunner |
| 17 | [skill-system.md](skill-system.md) | Build skill, adapters, extensions, ClawHub |
| 18 | [evaluation.md](evaluation.md) | Quality scoring: metrics, thresholds, retry policy, artifacts |
| 19 | [critique.md](critique.md) | Reflective Critique Loop: defect diagnosis, repair, pattern memory |

## Quick Start

If you are new to AWP, start with [overview.md](overview.md) to understand the motivation, then read [layer-model.md](layer-model.md) to see how the protocol is structured.

To build a workflow, you need at minimum:
- A [manifest](manifest.md) (`workflow.awp.yaml`)
- One or more [agent configs](agent.md) (`agent.awp.yaml`)
- An [orchestration graph](orchestration.md)

For the normative specification with RFC 2119 language, see `spec/versions/1.0/`.

For runnable examples, see `examples/`.
