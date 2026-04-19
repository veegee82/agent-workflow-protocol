# AWP Protocol Reference

Complete documentation for the Agent Workflow Protocol (AWP) v1.0.0.

## Mental Model

AWP is a **declarative protocol** for multi-agent systems. A workflow is described in YAML across seven semantic layers, then executed by a runtime that interprets the YAML — never the other way around. The same workflow file can run on any conforming runtime, be packaged into a `.awp.zip`, validated statically (rules R1-R32), and graduated through five **autonomy levels** (A0 prescribed DAG → A4 self-organizing recursive delegation).

The documentation below is grouped by *what question it answers*:

- **Foundations** (1-3, 14-15): What is AWP? Why does it exist? How is it structured on disk and over the wire?
- **Reference per layer** (4-11): Field-by-field description of each YAML section.
- **Autonomy & validation** (12-13): How safety scales with freedom.
- **Runtime & quality** (16-20): How the engines actually execute, how quality is measured (evaluation) and repaired (critique), and how iterative optimization works.
- **Engines, data, UI** (21-24): Concrete pieces — DAG vs. delegation loop, the data importer, Workflow Studio, and OpenClaw integration.

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
| 20 | [iterative-optimization.md](iterative-optimization.md) | Iterative optimization: feedback loop, capability accumulation, stall detection, budgets |
| 21 | [ORCHESTRATION_ENGINES.md](ORCHESTRATION_ENGINES.md) | DAG vs. Delegation Loop engine comparison |
| 22 | [data-importer.md](data-importer.md) | Data import and Source resolvers |
| 23 | [ui.md](ui.md) | Workflow Studio (browser UI) |
| 24 | [openclaw_integration.md](openclaw_integration.md) | OpenClaw integration guide |

## Concept Map

AWP has a small vocabulary of concepts that reference each other. Use this as a "where does concept X live?" lookup — every architectural document should be one hop away from its neighbors via this map.

### Structural concepts (where things live)

| Concept | Lives in | Authoritative doc | Referenced by |
|---|---|---|---|
| **7 semantic layers** (Manifest → Identity → Capabilities → Communication → Memory → Orchestration → Observability) | The stack itself | [layer-model.md](layer-model.md) | Every per-layer doc below; `spec/versions/1.0/layers/` |
| **Autonomy spectrum** (A0 prescribed → A4 self-organizing) | Cross-cutting classification | [compliance.md](compliance.md) | [overview.md](overview.md), [layer-model.md](layer-model.md), [architecture.md](architecture.md) |
| **Two engines** (DAG, delegation loop) | Layer 5 (Orchestration) | [ORCHESTRATION_ENGINES.md](ORCHESTRATION_ENGINES.md) | [orchestration.md](orchestration.md), [runtime.md](runtime.md) |
| **Agent contract (R17)** | Layer 1 ↔ Layer 5 boundary | [runtime.md](runtime.md), [validation.md](validation.md) | [agent.md](agent.md), every delegation-loop concept |
| **Cross-cutting mechanisms** (critique, evaluation, manager intelligence, dynamic tools) | Plug into existing layers, **not new layers** | [layer-model.md](layer-model.md#cross-cutting-mechanisms-not-new-layers) | [critique.md](critique.md), [evaluation.md](evaluation.md), [manager-intelligence.md](manager-intelligence.md), [runtime-tool-generation.md](runtime-tool-generation.md) |

### Dynamic concepts (what happens at runtime)

| Concept | Enforced by | Authoritative doc | Related |
|---|---|---|---|
| **Budget envelope** (max_loops, tokens, workers, wall-time, depth) | Deterministic check in delegation loop engine | [orchestration.md](orchestration.md), [runtime.md](runtime.md) | [compliance.md](compliance.md), [manager-intelligence.md](manager-intelligence.md) |
| **Completion gate chain** (L0 → critique → deliverable_presence → placeholder → file → deliverable → structural_integrity → eval) | Runtime between manager COMPLETE and run end | [critique.md](critique.md), [runtime.md](runtime.md) | [validation.md](validation.md), [evaluation.md](evaluation.md) |
| **Validation rules R1-R32** (+R33 deterministic purity, R34 L0 output contract, R35 repair fixpoint, R36 empty-gradient guard) | `awp validate` + parse-time + runtime gates | [validation.md](validation.md) | Every layer doc; [compliance.md](compliance.md), [refinement.md](refinement.md) |
| **Delegation loop** (manager ↔ ephemeral workers, PLAN/DELEGATE/COMPLETE) | Delegation-loop engine at A2+ | [ORCHESTRATION_ENGINES.md](ORCHESTRATION_ENGINES.md), [manager-intelligence.md](manager-intelligence.md) | [critique.md](critique.md), [runtime.md](runtime.md) |
| **Dynamic tool factory** (B1-B6 pipeline + β auto-emergent induction) | Runtime at A3+ | [runtime-tool-generation.md](runtime-tool-generation.md), [tools.md](tools.md) | [runtime.md](runtime.md) §Framework-Fixes |
| **Outer loop (A5)** — SGD over prompt artifacts with TextGrad | `awp optimize`, never `awp run` | [outer-loop.md](outer-loop.md), [iterative-optimization.md](iterative-optimization.md) | [refinement.md](refinement.md) contrasts y-axis |
| **Refinement mode** — y-axis iteration over a seed deliverable | `awp refine`, never inside `awp run` | [refinement.md](refinement.md) | [outer-loop.md](outer-loop.md) (θ-axis), [critique.md](critique.md) (gradient source) |

### Reading a concept off this map

If a doc names concept X, you should be able to (a) find X's authoritative doc in one of the tables above, (b) name the layer/contract/gate/engine/rule X belongs to, and (c) reach X's neighbors in one click. If any of those fails, the doc carries a linked-mental-model gap — see `CLAUDE.md` §2.

## Quick Start

If you are new to AWP, start with [overview.md](overview.md) to understand the motivation, then read [layer-model.md](layer-model.md) to see how the protocol is structured.

To build a workflow, you need at minimum:
- A [manifest](manifest.md) (`workflow.awp.yaml`) — Layer 0
- One or more [agent configs](agent.md) (`agent.awp.yaml`) — Layer 1
- An [orchestration graph](orchestration.md) — Layer 5
- Optionally: [tools](tools.md) (Layer 2), [memory](memory.md) (Layer 4), [observability](observability.md) (Layer 6), [security](security.md) (cross-cutting)

For the normative specification with RFC 2119 language, see [`spec/versions/1.0/`](../spec/versions/1.0/spec.md) — the [validation rules](validation.md) cross-reference `spec/versions/1.0/validation-rules.md` field-by-field.

For runnable examples, see [`examples/`](../examples/README.md). For the governance/sync contract that keeps all of this coherent with the code, see `CLAUDE.md` §2.
