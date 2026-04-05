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

<svg viewBox="0 0 580 310" xmlns="http://www.w3.org/2000/svg" font-family="system-ui, -apple-system, sans-serif" font-size="11">
<rect x="10" y="5" width="560" height="30" rx="5" fill="#dce6f7" stroke="#4a6fa5" stroke-width="1.2"/>
  <text x="20" y="24" font-weight="600" fill="#2a3f5f">L6 Observability</text>
  <text x="560" y="24" text-anchor="end" fill="#888" font-size="10">optional, instruments any layer</text>
  <rect x="10" y="45" width="560" height="30" rx="5" fill="#d5e8d4" stroke="#5b8c5a" stroke-width="1.2"/>
  <text x="20" y="64" font-weight="600" fill="#2d5a2d">L5 Orchestration</text>
  <text x="560" y="64" text-anchor="end" fill="#888" font-size="10">needs L1 (agent IDs) + L4 (state)</text>
  <rect x="10" y="85" width="560" height="30" rx="5" fill="#fef3cd" stroke="#d4a017" stroke-width="1.2"/>
  <text x="20" y="104" font-weight="600" fill="#856404">L4 Memory &amp; State</text>
  <text x="560" y="104" text-anchor="end" fill="#888" font-size="10">needs L1 (output contracts)</text>
  <rect x="10" y="125" width="560" height="30" rx="5" fill="#e8d5f5" stroke="#7b4ea3" stroke-width="1.2"/>
  <text x="20" y="144" font-weight="600" fill="#5a2d82">L3 Communication</text>
  <text x="560" y="144" text-anchor="end" fill="#888" font-size="10">needs L1 (sender/receiver)</text>
  <rect x="10" y="165" width="560" height="30" rx="5" fill="#fde2e2" stroke="#c0392b" stroke-width="1.2"/>
  <text x="20" y="184" font-weight="600" fill="#922b21">L2 Capabilities</text>
  <text x="560" y="184" text-anchor="end" fill="#888" font-size="10">extends L1 with tools</text>
  <rect x="10" y="205" width="560" height="30" rx="5" fill="#d5f5e3" stroke="#27ae60" stroke-width="1.2"/>
  <text x="20" y="224" font-weight="600" fill="#1a6b3c">L1 Agent Identity</text>
  <text x="560" y="224" text-anchor="end" fill="#888" font-size="10">needs L0 (workflow context)</text>
  <rect x="10" y="245" width="560" height="30" rx="5" fill="#f0f0f0" stroke="#888" stroke-width="1.2"/>
  <text x="20" y="264" font-weight="600" fill="#333">L0 Manifest</text>
  <text x="560" y="264" text-anchor="end" fill="#888" font-size="10">independent, root document</text>
  <line x1="290" y1="37" x2="290.0" y2="41.0" stroke="#888" stroke-width="1"/>
  <polygon points="290.0,43.0 287.0,37.0 293.0,37.0" fill="#888"/>
  <line x1="290" y1="77" x2="290.0" y2="81.0" stroke="#888" stroke-width="1"/>
  <polygon points="290.0,83.0 287.0,77.0 293.0,77.0" fill="#888"/>
  <line x1="290" y1="117" x2="290.0" y2="121.0" stroke="#888" stroke-width="1"/>
  <polygon points="290.0,123.0 287.0,117.0 293.0,117.0" fill="#888"/>
  <line x1="290" y1="157" x2="290.0" y2="161.0" stroke="#888" stroke-width="1"/>
  <polygon points="290.0,163.0 287.0,157.0 293.0,157.0" fill="#888"/>
  <line x1="290" y1="197" x2="290.0" y2="201.0" stroke="#888" stroke-width="1"/>
  <polygon points="290.0,203.0 287.0,197.0 293.0,197.0" fill="#888"/>
  <line x1="290" y1="237" x2="290.0" y2="241.0" stroke="#888" stroke-width="1"/>
  <polygon points="290.0,243.0 287.0,237.0 293.0,237.0" fill="#888"/>
</svg>

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
