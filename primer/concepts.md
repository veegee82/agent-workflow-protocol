# Core Concepts

AWP organizes the concerns of a multi-agent workflow into seven layers. Each layer answers a specific question, builds on the layers below it, and can be adopted independently. Autonomy levels (A0-A4) measure how autonomous the workflow is, while features like communication, memory, and observability are cross-cutting concerns available at any level.

## The 7-Layer Model

```
Layer 6: OBSERVABILITY     -- Metrics, traces, health-checks, audit logs
Layer 5: ORCHESTRATION     -- DAG topology, execution modes, loops, conditions
Layer 4: MEMORY & STATE    -- State model, persistence, memory tiers, output contracts
Layer 3: COMMUNICATION     -- Message Bus, channels, message envelope, patterns
Layer 2: CAPABILITIES      -- Tools (MCP), skills, data sources, sandbox
Layer 1: AGENT IDENTITY    -- Name, role, LLM config, prompt, output schema
Layer 0: MANIFEST          -- Workflow metadata, version, dependencies, runtime
```

## Layer Descriptions

### Layer 0: Manifest

**Question: What is this workflow, and what does it need?**

The manifest is the root document. It declares the workflow's name, version, AWP specification version, description, and any external dependencies or runtime requirements. Every AWP workflow begins here. Without a valid manifest, nothing else can be interpreted.

### Layer 1: Agent Identity

**Question: Who are the agents, and what are they configured to do?**

Each agent in the workflow has a unique name, a role description, an LLM configuration (model, temperature, reasoning settings), a system prompt, and an output schema. Layer 1 establishes the agents as named, configured entities that the rest of the protocol can reference.

### Layer 2: Capabilities

**Question: What can the agents do beyond generating text?**

Capabilities extend agents with tools (following the MCP tool protocol), skills (injected knowledge), data sources (external inputs), and sandboxed execution environments. An agent with no capabilities can only produce text; an agent with capabilities can search the web, read files, execute code, and more.

### Layer 3: Communication

**Question: How do agents talk to each other outside the execution graph?**

The communication layer defines a message bus with named channels, a standard message envelope (sender, receiver, content, timestamp), and communication patterns (request-reply, broadcast, pub-sub). This enables agent-to-agent messaging that is independent of the DAG execution order.

### Layer 4: Memory and State

**Question: What do agents remember, and how do they share results?**

This layer defines the state model (a shared dictionary keyed by agent name), persistence rules, memory tiers (working memory, short-term daily logs, long-term curated memory, shared workspace), and output contracts. Output contracts specify which fields an agent produces and which downstream agents can consume.

### Layer 5: Orchestration

**Question: In what order do agents run, and under what conditions?**

The orchestration layer describes the agent graph as a DAG (directed acyclic graph), execution modes (sequential, parallel, conditional), timeouts, error handling strategies, retry policies, and loop constructs. It uses agent IDs from Layer 1 and state from Layer 4 to determine execution flow.

### Layer 6: Observability

**Question: How do we monitor, debug, and audit the workflow?**

The observability layer defines metrics collection, distributed tracing (OpenTelemetry-compatible), health checks, structured logging, and audit logs. It is the only fully optional layer -- a workflow can run without it -- but production deployments rely on it for monitoring and compliance.

## Layer Dependencies

The layers form a dependency graph, not a strict stack. Each layer declares what it needs from below:

```
Layer 6 (Observability) -- optional, can instrument any layer below
  |
Layer 5 (Orchestration) -- needs Layer 1 (agent IDs) + Layer 4 (state)
  |
Layer 4 (Memory & State) -- needs Layer 1 (agent IDs for output contracts)
  |
Layer 3 (Communication) -- needs Layer 1 (agent IDs as sender/receiver)
  |
Layer 2 (Capabilities) -- independent, extends Layer 1 agents with tools
  |
Layer 1 (Agent Identity) -- needs Layer 0 (workflow context)
  |
Layer 0 (Manifest) -- independent, root document
```

Key observations:

- **Layer 0** is always required. It is the entry point for any AWP document.
- **Layer 1** is required for any workflow that contains agents (which is nearly all of them).
- **Layers 2-4** are independent of each other. You can have tools without communication, or memory without tools.
- **Layer 5** ties agents and state together into an executable graph.
- **Layer 6** is purely additive. Removing it changes nothing about execution semantics.

## A Minimal Example

The simplest possible AWP workflow defines a manifest and a single agent:

```yaml
awp: 1.0.0
workflow:
  name: hello-world
  version: 1.0.0
  description: A single agent that greets the user

agents:
  - name: greeter
    role: Greets the user with a friendly message
    llm:
      model: openai/gpt-4o-mini
```

This 10-line file is a valid A0 AWP workflow. It declares the protocol version, workflow metadata, and one agent with a name, role, and model. A conforming runtime can execute this by sending the role as a system prompt and returning the agent's response.

## Autonomy Levels

AWP defines five autonomy levels. Each level measures how autonomous the workflow is -- not what features it has. Communication, memory, observability, and security are cross-cutting features available at any level.

| Level | Name | What It Measures |
|-------|------|-----------------|
| **A0** | Prescribed | Static DAG, predefined agents, fixed tools. The simplest workflow. |
| **A1** | Adaptive | Conditional execution, loops, fan-out. The workflow can adapt its execution path. |
| **A2** | Delegating | Manager spawns workers dynamically. Budget controls required. |
| **A3** | Self-Tooling | Agents create tools and skills at runtime. Safety envelope required. |
| **A4** | Self-Organizing | Recursive delegation with budget distribution. Observability required. |

A runtime advertises the highest autonomy level it supports. A workflow declares the minimum level it requires. If the runtime's level meets or exceeds the workflow's requirement, execution can proceed.

## What Comes Next

Now that you understand the conceptual model, try building a workflow hands-on in [quickstart.md](quickstart.md). For the normative specification of each layer, see the `spec/` directory.
