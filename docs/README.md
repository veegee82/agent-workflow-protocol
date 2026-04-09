# AWP Protocol Reference

Complete documentation for the Agent Workflow Protocol (AWP) v1.0.0.

## Mental Model

AWP is a **declarative protocol** for multi-agent systems. A workflow is described in YAML across seven semantic layers, then executed by a runtime that interprets the YAML — never the other way around. The same workflow file can run on any conforming runtime, be packaged into a `.awp.zip`, validated statically (rules R1-R32), and graduated through five **autonomy levels** (A0 prescribed DAG → A4 self-organizing recursive delegation).

The documentation below is grouped by *what question it answers*:

- **Foundations** (1-3, 14-15): What is AWP? Why does it exist? How is it structured on disk and over the wire?
- **Reference per layer** (4-11): Field-by-field description of each YAML section.
- **Autonomy & validation** (12-13): How safety scales with freedom.
- **Runtime & quality** (16-19): How the engines actually execute, and how quality is measured (evaluation) and repaired (critique).
- **Engines, data, UI** (20-23): Concrete pieces — DAG vs. delegation loop, the data importer, Workflow Studio, and OpenClaw integration.

New since 1.0: **complexity-scored auto-promotion** of workers to sub-managers, **A4 sub-run cluster visualization**, **budget reservation with refund** for hard termination guarantees, the **B1-B6 robust tool-generation pipeline with auto-repair**, and the **Experiment paradigm** in Workflow Studio (Sessions are now Experiments with Protocol/Memory tabs). These features are documented in `architecture.md`, `orchestration.md`, `tools.md`, and `ui.md`.

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
| 13 | [validation.md](validation.md) | Validation rules R1 through R32 |
| 14 | [file-structure.md](file-structure.md) | Required directory layout |
| 15 | [packaging.md](packaging.md) | `.awp.zip` format and ClawHub publishing |
| 16 | [runtime.md](runtime.md) | AWPAgent interface, standalone runtime, WorkflowRunner |
| 17 | [skill-system.md](skill-system.md) | Build skill, adapters, extensions, ClawHub |
| 18 | [evaluation.md](evaluation.md) | Quality scoring: metrics, thresholds, retry policy, artifacts |
| 19 | [critique.md](critique.md) | Reflective Critique Loop: defect diagnosis, repair, pattern memory |
| 20 | [ORCHESTRATION_ENGINES.md](ORCHESTRATION_ENGINES.md) | DAG vs. Delegation Loop engine comparison |
| 21 | [data-importer.md](data-importer.md) | Data import and Source resolvers |
| 22 | [ui.md](ui.md) | Workflow Studio (browser UI) |
| 23 | [openclaw_integration.md](openclaw_integration.md) | OpenClaw integration guide |

## Quick Start

If you are new to AWP, start with [overview.md](overview.md) to understand the motivation, then read [layer-model.md](layer-model.md) to see how the protocol is structured.

To build a workflow, you need at minimum:
- A [manifest](manifest.md) (`workflow.awp.yaml`)
- One or more [agent configs](agent.md) (`agent.awp.yaml`)
- An [orchestration graph](orchestration.md)

For the normative specification with RFC 2119 language, see `spec/versions/1.0/`.

For runnable examples, see `examples/`.
