# Why AWP Exists

## The Fragmentation Problem

Building multi-agent workflows today means stitching together half a dozen standards, each covering only a fraction of what a complete workflow needs. No single standard describes the full picture -- from agent identity through orchestration to observability.

| Standard | Focus | What's Missing |
|----------|-------|----------------|
| **MCP** (Model Context Protocol) | Tool access for LLMs | No agent identity, no workflow definition, no state management |
| **A2A** (Agent-to-Agent) | Agent communication | No orchestration, no memory protocol, no tool definitions |
| **OpenAPI** | HTTP API description | No agent concept, no execution state, no DAG structure |
| **LangGraph State** | State machine for agents | Proprietary, not portable across runtimes, no tool specs |
| **CrewAI YAML** | Agent role definition | No formal orchestration, no memory protocol, no observability |

Every team building multi-agent systems ends up inventing their own glue: custom YAML formats, ad-hoc state passing, bespoke orchestration logic. The result is workflows that are locked to a single runtime, impossible to share, and difficult to audit.

## What AWP Is

**AWP (Agent Workflow Protocol)** is an open, declarative standard that describes a multi-agent workflow **completely and runtime-agnostically**.

An AWP manifest contains everything needed to:

- **Understand** -- A human-readable description of every component, from agents to tools to data flows
- **Validate** -- Automatic schema checking before a single token is generated
- **Port** -- The same workflow runs on any AWP-compatible runtime without modification
- **Share** -- Export as a `.awp.zip` package, publish to a registry, hand to a colleague
- **Execute** -- Deterministic interpretation by any conforming runtime

### The Docker Compose Analogy

Think of AWP as **Docker Compose for agentic workflows**. Docker Compose does not run containers -- it *describes* how containers relate to each other, what volumes they mount, what networks they share, and in what order they start. The Docker engine interprets the Compose file and does the actual work.

AWP works the same way. A `workflow.awp.yaml` file describes agents, their tools, their communication channels, their orchestration order, and their output contracts. An AWP-compatible runtime -- whether it is a Python framework, a cloud service, or a CLI tool -- reads the manifest and executes it.

The workflow is the artifact. The runtime is interchangeable.

## Design Principles

AWP is built on eight principles that guide every design decision in the specification.

### 1. Declarative Over Imperative

AWP manifests describe *what* the workflow is, not *how* to execute it. Agent graphs, tool bindings, memory tiers, and communication channels are declared as data. The runtime decides execution strategy.

### 2. Runtime-Agnostic

An AWP manifest does not assume Python, JavaScript, or any specific framework. It is a protocol specification that any runtime can implement. The same `workflow.awp.yaml` should produce equivalent behavior whether executed by a local CLI, a cloud orchestrator, or an embedded agent framework.

### 3. Composable

Workflows can include sub-workflows. An agent in one workflow can be an entire workflow in another. This enables building complex systems from well-tested, reusable components -- the same way functions compose into programs.

### 4. Versioned

Every AWP manifest carries a SemVer version (`awp: 1.0.0`). Runtimes can check compatibility before execution. Breaking changes increment the major version. Extensions increment the minor version. Bug fixes increment the patch version.

### 5. Self-Contained

A packaged AWP workflow (`.awp.zip`) contains everything needed to run: manifest, agent definitions, prompt files, schemas, skills, and project-local tools. No external dependencies beyond the runtime itself and configured LLM providers.

### 6. Progressive

AWP follows a "start simple, add complexity" model. The minimal valid workflow is under 10 lines of YAML. Advanced features -- memory, communication, observability -- are optional cross-cutting capabilities available at any autonomy level (A0 through A4). The levels measure how autonomous the workflow is, not what features it has. You adopt only what you need.

### 7. Explicit Over Implicit

Every dependency, every shared field, every tool permission is declared in the manifest. There are no hidden defaults that change behavior. If an agent can access a tool, the manifest says so. If an agent depends on another agent's output, the manifest says so.

### 8. Secure by Default

Agents operate under the principle of least privilege. Tools must be explicitly allowed per agent. Shell execution is disabled unless declared. File access is scoped to the workflow directory. Memory access is per-project. The manifest is both a description and a security boundary.

## What Comes Next

Read [concepts.md](concepts.md) to understand the 7-layer model that structures the AWP specification, then try [quickstart.md](quickstart.md) to build your first workflow in five minutes.
