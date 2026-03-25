# The 7-Layer Architecture

AWP organizes workflow concerns into seven layers. Each layer answers one question and builds on the layers below it.

## Layer Diagram

```
+---------------------------------------------+
|  Layer 6: OBSERVABILITY                     |  How do I monitor this workflow?
|  metrics, tracing, logging, audit           |
+---------------------------------------------+
|  Layer 5: ORCHESTRATION                     |  In what order and under what conditions?
|  DAG, execution modes, control flow         |
+---------------------------------------------+
|  Layer 4: MEMORY & STATE                    |  What does the workflow remember?
|  state model, memory tiers, sharing         |
+---------------------------------------------+
|  Layer 3: COMMUNICATION                     |  How do agents talk to each other?
|  message bus, channels, envelopes           |
+---------------------------------------------+
|  Layer 2: CAPABILITIES                      |  What can an agent do?
|  tools, skills, data sources, sandbox       |
+---------------------------------------------+
|  Layer 1: AGENT IDENTITY                    |  Who is this agent?
|  identity, model, prompt, output            |
+---------------------------------------------+
|  Layer 0: MANIFEST                          |  What is this workflow?
|  workflow metadata, dependencies, env       |
+---------------------------------------------+

Cross-cutting: SECURITY (circuit breaker, rate limiting, access control, secrets, audit)
```

## Layer Dependency Diagram

Layers form a dependency graph, not a strict stack. Each layer depends only on the layers it needs:

```
Layer 6 (Observability) ----depends----> Layer 5 (Orchestration)
Layer 5 (Orchestration) ----depends----> Layer 1 (Agent Identity)
Layer 4 (Memory & State) ---depends----> Layer 1 (Agent Identity)
Layer 3 (Communication) ----depends----> Layer 1 (Agent Identity)
Layer 2 (Capabilities) -----depends----> Layer 1 (Agent Identity)
Layer 1 (Agent Identity) ---depends----> Layer 0 (Manifest)
Security -------------------cross-cuts-> All Layers
```

Key observations:

- **Layer 0** is always required. It is the entry point for any AWP document.
- **Layer 1** is required for any workflow that contains agents (which is all of them).
- **Layers 2, 3, and 4** are independent of each other. You can have tools without communication, or memory without tools.
- **Layer 5** ties agents and state together into an executable graph.
- **Layer 6** is purely additive. Removing it changes nothing about execution semantics.

## You Always Need Layer 0 + Layer 1

The minimum viable AWP workflow requires Layer 0 (manifest) and Layer 1 (agent identity). Everything above is opt-in. A simple single-agent workflow uses only these two layers. A production enterprise system uses all seven plus the cross-cutting security layer.

## Autonomy Level to Layer Mapping

Each [autonomy level](compliance.md) uses specific layers:

| Level | Name | Required Layers | Description |
|-------|------|----------------|-------------|
| A0 | Prescribed | 0, 1, 5 (minimal) | Static DAG, predefined agents, fixed tools |
| A1 | Adaptive | 0, 1, 4, 5 | Conditional execution, loops, fan-out, multi-agent DAG |
| A2 | Delegating | 0, 1, 4, 5 | Manager spawns workers dynamically (delegation loop) |
| A3 | Self-Tooling | 0, 1, 2, 4, 5 | Agents create tools and skills at runtime |
| A4 | Self-Organizing | All (0-6 + Security) | Recursive delegation, budget distribution |

Communication (Layer 3), Memory (Layer 4), Observability (Layer 6), and Security are cross-cutting features available at any autonomy level.

## How Layers Map to YAML Sections

### In `workflow.awp.yaml`

| Layer | YAML Section(s) |
|-------|-----------------|
| Layer 0 | `awp`, `workflow` (name, version, description, runtime, dependencies, env, settings) |
| Layer 2 | `capabilities.custom_tools` (workflow-level custom tools) |
| Layer 3 | `communication` (bus, channels) |
| Layer 4 | `state`, `memory` |
| Layer 5 | `orchestration` (engine, graph, execution) |
| Layer 6 | `observability` (metrics, tracing, logging, audit, health) |
| Security | `security` (circuit_breaker, rate_limiting, secrets) |

### In `agent.awp.yaml`

| Layer | YAML Section(s) |
|-------|-----------------|
| Layer 1 | `awp_agent`, `identity`, `runtime`, `model`, `prompt`, `output`, `vision` |
| Layer 2 | `capabilities` (tools, skills, data_sources, sandbox) |
| Layer 4 | `memory` (agent-level memory configuration) |

## Layer Details

For the complete reference of each layer, see:

- Layer 0: [Manifest Reference](manifest.md)
- Layer 1: [Agent Reference](agent.md)
- Layer 2: [Tools & Capabilities Reference](tools.md)
- Layer 3: [Communication Reference](communication.md)
- Layer 4: [Memory & State Reference](memory.md)
- Layer 5: [Orchestration Reference](orchestration.md)
- Layer 6: [Observability Reference](observability.md)
- Security: [Security Reference](security.md)
