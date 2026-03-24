# Protocol Overview

## What AWP Is

The Agent Workflow Protocol (AWP) is an open standard for describing, packaging, and executing multi-agent AI workflows. A single set of YAML documents fully specifies agent identities, capabilities, communication patterns, state management, orchestration logic, and observability requirements. Any conforming runtime can execute these documents without modification.

## The Problem AWP Solves

Building multi-agent systems today means choosing a framework and being locked into it. Every platform -- LangGraph, CrewAI, AutoGen, custom solutions -- uses its own format for defining agents, tools, orchestration, and memory. Moving a workflow from one platform to another means rewriting everything.

Existing standards each solve a piece of the puzzle but none cover the full picture:

| Standard | What It Covers | What It Misses |
|----------|---------------|----------------|
| MCP | Tool access for LLMs | No agents, no orchestration, no state |
| A2A | Agent communication | No orchestration, no memory, no tools |
| OpenAPI | HTTP API description | No agent concept, no DAG structure |
| LangGraph State | State machine for agents | Proprietary, not portable |
| CrewAI YAML | Agent role definition | No formal orchestration, no memory protocol |

AWP fills this gap. It describes a complete multi-agent workflow in a single, portable format.

## The Docker Compose Analogy

AWP is to agentic workflows what Docker Compose is to container stacks:

- A declarative YAML describes the entire system
- Services (= Agents) are defined with their dependencies
- Volumes (= Memory), Networks (= Communication), Health-Checks (= Observability)
- Portable across different container runtimes (= agent platforms)

One manifest. Any runtime. Full workflow.

## Design Principles

AWP is built on eight principles:

### 1. Declarative Over Imperative

AWP manifests describe *what* the workflow is, not *how* to execute it. Agent graphs, tool bindings, memory tiers, and communication channels are declared as data. The runtime decides execution strategy.

### 2. Runtime-Agnostic

An AWP manifest does not assume Python, JavaScript, or any specific framework. The same `workflow.awp.yaml` should produce equivalent behavior whether executed by a local CLI, a cloud orchestrator, or an embedded agent framework.

### 3. Composable

Workflows can include sub-workflows. An agent in one workflow can be an entire workflow in another. This enables building complex systems from well-tested, reusable components.

### 4. Versioned

Every AWP manifest carries a SemVer version (`awp: "1.0.0"`). Runtimes check compatibility before execution. Breaking changes increment the major version. Extensions increment the minor version.

### 5. Self-Contained

A packaged AWP workflow (`.awp.zip`) contains everything needed to run: manifest, agent definitions, prompt files, schemas, skills, and project-local tools. No external dependencies beyond the runtime and configured LLM providers.

### 6. Progressive

AWP follows a "start simple, add complexity" model. The minimal valid workflow is under 10 lines of YAML. Advanced features -- memory, communication, observability -- are optional extensions activated through [compliance levels](compliance.md) (L0 through L5).

### 7. Explicit Over Implicit

Every dependency, every shared field, every tool permission is declared in the manifest. There are no hidden defaults that change behavior.

### 8. Secure by Default

Agents operate under the principle of least privilege. Tools must be explicitly allowed per agent. Shell execution is disabled unless declared. File access is scoped to the workflow directory. Memory access is per-project.

## What AWP Is Not

- **Not a runtime.** AWP describes workflows; it does not execute them. Any platform that implements the AWPAgent interface can run AWP workflows. A reference runtime (`awp-protocol`) is provided for convenience.
- **Not a framework.** AWP does not impose application structure, dependency injection, or programming patterns. It is a protocol specification.
- **Not an LLM.** AWP is model-agnostic. Any LLM provider (OpenRouter, OpenAI, Anthropic, Ollama, etc.) can be used.

## Relationship to Other Standards

| Standard | Relationship |
|----------|-------------|
| **MCP** | AWP uses MCP for tool definitions and calling. MCP tools are first-class citizens in AWP. |
| **A2A** | AWP and A2A are complementary. AWP covers full workflow definition; A2A focuses on agent-to-agent communication. AWP's message bus (Layer 3) addresses the same domain within a workflow context. |
| **OpenTelemetry** | AWP's observability layer (Layer 6) is designed to be OpenTelemetry-compatible. |

## What AWP Unifies

| Concern | Without AWP | With AWP |
|---------|------------|----------|
| Agent definition | Framework-specific classes | `agent.awp.yaml` -- portable YAML |
| Orchestration | Hardcoded in Python | `orchestration.graph` -- declarative DAG |
| Tool access | Framework-specific wrappers | MCP-compatible tool protocol |
| State sharing | Ad-hoc dict passing | Output contracts with `shareable` fields |
| Memory | Custom per-project | 4-tier standard (long-term, daily, episodic, semantic) |
| Communication | Not standardized | Message bus with typed channels |
| Observability | Manual logging | OpenTelemetry-compatible tracing and metrics |
| Validation | None (runtime errors) | 24 rules checked before execution (R1-R24) |
| Portability | Zero | `.awp.zip` and ClawHub registry |

## Next Steps

- [Layer Model](layer-model.md) -- Understand the 7-layer architecture
- [Manifest Reference](manifest.md) -- Start building a workflow
- [Compliance Levels](compliance.md) -- Choose your feature level
