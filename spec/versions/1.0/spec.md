# AWP — Agent Workflow Protocol Specification v1.0.0

**Status:** Draft Standard
**Version:** 1.0.0
**Date:** 2026-03-23
**License:** MIT

---

## Abstract

The Agent Workflow Protocol (AWP) is an open specification for defining, packaging, and executing multi-agent AI workflows. AWP provides a layered architecture that enables interoperability between agent runtimes, tool registries, memory systems, and orchestration engines. A conforming AWP workflow is described by a set of YAML documents that fully specify agent identities, capabilities, communication patterns, state management, orchestration logic, and observability requirements. AWP is runtime-agnostic: while a Python reference implementation exists, any language or platform MAY implement the protocol.

---

## 1. Terminology

The key words "MUST", "MUST NOT", "REQUIRED", "SHALL", "SHALL NOT", "SHOULD", "SHOULD NOT", "RECOMMENDED", "NOT RECOMMENDED", "MAY", and "OPTIONAL" in this document are to be interpreted as described in [RFC 2119](https://www.rfc-editor.org/rfc/rfc2119) and [RFC 8174](https://www.rfc-editor.org/rfc/rfc8174).

| Term | Definition |
|------|------------|
| **Workflow** | A complete AWP package: manifest, agents, orchestration graph, and supporting files. |
| **Agent** | An autonomous unit of work within a workflow, identified by a unique `agent_id`. |
| **Manifest** | The root document (`workflow.awp.yaml`) that declares the workflow and its configuration. |
| **Agent Identity Card (AIC)** | An auto-generated summary of an agent's capabilities derived from its configuration. |
| **MCP Tool** | A callable function exposed via the Model Context Protocol tool interface. |
| **DAG** | Directed Acyclic Graph defining execution order and data flow between agents. |
| **Layer** | A logical grouping of related protocol concerns (e.g., identity, capabilities, orchestration). |
| **Autonomy Level** | A tiered autonomy designation (A0–A4) indicating the degree of autonomous behavior a workflow exhibits. |

---

## 2. Protocol Versioning

AWP uses [Semantic Versioning 2.0.0](https://semver.org/) for the protocol version, expressed in the `awp` field of the manifest document.

- **MAJOR** version changes indicate breaking changes to the protocol.
- **MINOR** version changes add new features in a backward-compatible manner.
- **PATCH** version changes address errata or clarifications without behavioral changes.

A conforming runtime MUST reject a manifest whose MAJOR version it does not support. A runtime SHOULD accept any manifest whose MAJOR version matches and whose MINOR version is less than or equal to the runtime's supported MINOR version.

```yaml
awp: "1.0.0"
```

---

## 3. Layer Model

AWP is organized into seven layers, each addressing a distinct concern. Layers are additive: higher layers depend on lower layers but not vice versa.

```
┌─────────────────────────────────────────────┐
│  Layer 6: Observability                     │  metrics, tracing, logging, audit
├─────────────────────────────────────────────┤
│  Layer 5: Orchestration                     │  DAG, execution modes, control flow
├─────────────────────────────────────────────┤
│  Layer 4: Memory & State                    │  state model, memory tiers, sharing
├─────────────────────────────────────────────┤
│  Layer 3: Communication                     │  message bus, channels, envelopes
├─────────────────────────────────────────────┤
│  Layer 2: Capabilities                      │  tools, skills, data sources, sandbox
├─────────────────────────────────────────────┤
│  Layer 1: Agent Identity                    │  identity, model, prompt, output
├─────────────────────────────────────────────┤
│  Layer 0: Manifest                          │  workflow metadata, dependencies, env
└─────────────────────────────────────────────┘

Cross-cutting: Security (circuit breaker, rate limiting, access control, secrets, audit)
```

### Dependency Diagram

```
Layer 6 (Observability) ──depends──▶ Layer 5 (Orchestration)
Layer 5 (Orchestration) ──depends──▶ Layer 1 (Agent Identity)
Layer 4 (Memory & State) ──depends──▶ Layer 1 (Agent Identity)
Layer 3 (Communication) ──depends──▶ Layer 1 (Agent Identity)
Layer 2 (Capabilities)  ──depends──▶ Layer 1 (Agent Identity)
Layer 1 (Agent Identity) ──depends──▶ Layer 0 (Manifest)
Security ──cross-cuts──▶ All Layers
```

---

## 4. Layer Documents

| Layer | Document | Description |
|-------|----------|-------------|
| 0 | [00-manifest.md](layers/00-manifest.md) | Workflow manifest and metadata |
| 1 | [01-agent-identity.md](layers/01-agent-identity.md) | Agent identity, model, prompt, and output configuration |
| 2 | [02-capabilities.md](layers/02-capabilities.md) | Tools, skills, data sources, and sandbox |
| 3 | [03-communication.md](layers/03-communication.md) | Message bus, channels, and messaging patterns |
| 4 | [04-memory-state.md](layers/04-memory-state.md) | State model, memory tiers, and access control |
| 5 | [05-orchestration.md](layers/05-orchestration.md) | DAG engine, execution modes, and control flow |
| 6 | [06-observability.md](layers/06-observability.md) | Metrics, tracing, logging, and audit |
| — | [security.md](layers/security.md) | Cross-cutting security concerns |

### Supporting Documents

| Document | Description |
|----------|-------------|
| [compliance.md](compliance.md) | Autonomy levels A0–A4 |
| [validation-rules.md](validation-rules.md) | Validation rules R1–R24 |
| [file-structure.md](file-structure.md) | Required directory layout |
| [packaging.md](packaging.md) | `.awp.zip` exchange format |

---

## 5. Conformance Statement

A workflow is **AWP-conformant** if and only if:

1. It includes a valid `workflow.awp.yaml` manifest with a supported `awp` version string.
2. It satisfies all MUST-level requirements defined in [validation-rules.md](validation-rules.md).
3. It declares an autonomy level (A0–A4) and satisfies all requirements for that level as defined in [compliance.md](compliance.md).

A runtime is **AWP-conformant** if and only if:

1. It can parse and validate a `workflow.awp.yaml` manifest.
2. It enforces all MUST-level validation rules for the declared autonomy level.
3. It executes agents according to the orchestration graph semantics defined in Layer 5.
4. It implements the state sharing semantics defined in Layer 4.

Partial conformance is permitted: a runtime MAY implement a subset of layers and MUST declare which layers it supports. A runtime that supports Layer N MUST also support all layers that Layer N depends on.
