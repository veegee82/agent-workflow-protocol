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

<svg viewBox="0 0 700 340" xmlns="http://www.w3.org/2000/svg" font-family="sans-serif" font-size="14">
<!-- Layer 6 -->
  <rect x="20" y="10" width="660" height="38" rx="4" fill="#dce6f7" stroke="#4a6fa5" stroke-width="1.5"/>
  <text x="30" y="34" font-weight="bold" fill="#2a3f5f">Layer 6: Observability</text>
  <text x="680" y="34" text-anchor="end" fill="#666">metrics, tracing, logging, audit</text>
  <!-- Layer 5 -->
  <rect x="20" y="52" width="660" height="38" rx="4" fill="#d5e8d4" stroke="#5b8c5a" stroke-width="1.5"/>
  <text x="30" y="76" font-weight="bold" fill="#2d5a2d">Layer 5: Orchestration</text>
  <text x="680" y="76" text-anchor="end" fill="#666">DAG, execution modes, control flow</text>
  <!-- Layer 4 -->
  <rect x="20" y="94" width="660" height="38" rx="4" fill="#fef3cd" stroke="#d4a017" stroke-width="1.5"/>
  <text x="30" y="118" font-weight="bold" fill="#856404">Layer 4: Memory &amp; State</text>
  <text x="680" y="118" text-anchor="end" fill="#666">state model, memory tiers, sharing</text>
  <!-- Layer 3 -->
  <rect x="20" y="136" width="660" height="38" rx="4" fill="#e8d5f5" stroke="#7b4ea3" stroke-width="1.5"/>
  <text x="30" y="160" font-weight="bold" fill="#5a2d82">Layer 3: Communication</text>
  <text x="680" y="160" text-anchor="end" fill="#666">message bus, channels, envelopes</text>
  <!-- Layer 2 -->
  <rect x="20" y="178" width="660" height="38" rx="4" fill="#fde2e2" stroke="#c0392b" stroke-width="1.5"/>
  <text x="30" y="202" font-weight="bold" fill="#922b21">Layer 2: Capabilities</text>
  <text x="680" y="202" text-anchor="end" fill="#666">tools, skills, data sources, sandbox</text>
  <!-- Layer 1 -->
  <rect x="20" y="220" width="660" height="38" rx="4" fill="#d5f5e3" stroke="#27ae60" stroke-width="1.5"/>
  <text x="30" y="244" font-weight="bold" fill="#1a6b3c">Layer 1: Agent Identity</text>
  <text x="680" y="244" text-anchor="end" fill="#666">identity, model, prompt, output</text>
  <!-- Layer 0 -->
  <rect x="20" y="262" width="660" height="38" rx="4" fill="#f0f0f0" stroke="#888" stroke-width="1.5"/>
  <text x="30" y="286" font-weight="bold" fill="#333">Layer 0: Manifest</text>
  <text x="680" y="286" text-anchor="end" fill="#666">workflow metadata, dependencies, env</text>
  <!-- Cross-cutting -->
  <rect x="20" y="310" width="660" height="24" rx="12" fill="#4a6fa5" stroke="none"/>
  <text x="350" y="327" text-anchor="middle" fill="#fff" font-size="12" font-weight="bold">Cross-cutting: Security (circuit breaker, rate limiting, access control, secrets, audit)</text>
</svg>

### Dependency Diagram

<svg viewBox="0 0 600 280" xmlns="http://www.w3.org/2000/svg" font-family="sans-serif" font-size="13">
<!-- Nodes -->
  <rect x="180" y="5" width="180" height="28" rx="14" fill="#dce6f7" stroke="#4a6fa5" stroke-width="1.5"/>
  <text x="270" y="24" text-anchor="middle" fill="#2a3f5f" font-weight="bold">Layer 6: Observability</text>
  <rect x="180" y="50" width="180" height="28" rx="14" fill="#d5e8d4" stroke="#5b8c5a" stroke-width="1.5"/>
  <text x="270" y="69" text-anchor="middle" fill="#2d5a2d" font-weight="bold">Layer 5: Orchestration</text>
  <rect x="10" y="110" width="170" height="28" rx="14" fill="#fef3cd" stroke="#d4a017" stroke-width="1.5"/>
  <text x="95" y="129" text-anchor="middle" fill="#856404" font-weight="bold">Layer 4: Memory</text>
  <rect x="190" y="110" width="170" height="28" rx="14" fill="#e8d5f5" stroke="#7b4ea3" stroke-width="1.5"/>
  <text x="275" y="129" text-anchor="middle" fill="#5a2d82" font-weight="bold">Layer 3: Comm</text>
  <rect x="370" y="110" width="170" height="28" rx="14" fill="#fde2e2" stroke="#c0392b" stroke-width="1.5"/>
  <text x="455" y="129" text-anchor="middle" fill="#922b21" font-weight="bold">Layer 2: Capabilities</text>
  <rect x="180" y="165" width="180" height="28" rx="14" fill="#d5f5e3" stroke="#27ae60" stroke-width="1.5"/>
  <text x="270" y="184" text-anchor="middle" fill="#1a6b3c" font-weight="bold">Layer 1: Agent Identity</text>
  <rect x="180" y="215" width="180" height="28" rx="14" fill="#f0f0f0" stroke="#888" stroke-width="1.5"/>
  <text x="270" y="234" text-anchor="middle" fill="#333" font-weight="bold">Layer 0: Manifest</text>
  <!-- Dependency arrows -->
  <line x1="270" y1="33" x2="270.0" y2="48.0" stroke="#4a6fa5" stroke-width="1.5"/>
  <polygon points="270.0,50.0 267.0,44.0 273.0,44.0" fill="#4a6fa5"/>
  <line x1="270" y1="78" x2="270.0" y2="163.0" stroke="#4a6fa5" stroke-width="1.5"/>
  <polygon points="270.0,165.0 267.0,159.0 273.0,159.0" fill="#4a6fa5"/>
  <line x1="95" y1="138" x2="218.0" y2="164.6" stroke="#4a6fa5" stroke-width="1.5"/>
  <polygon points="220.0,165.0 213.5,166.7 214.8,160.8" fill="#4a6fa5"/>
  <line x1="275" y1="138" x2="270.4" y2="163.0" stroke="#4a6fa5" stroke-width="1.5"/>
  <polygon points="270.0,165.0 268.1,158.6 274.0,159.6" fill="#4a6fa5"/>
  <line x1="455" y1="138" x2="322.0" y2="164.6" stroke="#4a6fa5" stroke-width="1.5"/>
  <polygon points="320.0,165.0 325.3,160.9 326.5,166.8" fill="#4a6fa5"/>
  <line x1="270" y1="193" x2="270.0" y2="213.0" stroke="#4a6fa5" stroke-width="1.5"/>
  <polygon points="270.0,215.0 267.0,209.0 273.0,209.0" fill="#4a6fa5"/>
  <!-- Security cross-cut -->
  <rect x="170" y="258" width="200" height="22" rx="11" fill="#c0392b" stroke="none"/>
  <text x="270" y="274" text-anchor="middle" fill="#fff" font-size="11" font-weight="bold">Security — cross-cuts all layers</text>
</svg>

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
| [validation-rules.md](validation-rules.md) | Validation rules R1–R36 |
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
