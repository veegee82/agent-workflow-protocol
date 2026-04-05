# The 7-Layer Architecture

AWP organizes workflow concerns into seven layers. Each layer answers one question and builds on the layers below it.

## Layer Diagram

<svg viewBox="0 0 700 340" xmlns="http://www.w3.org/2000/svg" font-family="system-ui, -apple-system, sans-serif" font-size="13">
  <defs>
    <filter id="shadow" x="-2%" y="-2%" width="104%" height="108%">
      <feDropShadow dx="0" dy="1" stdDeviation="1.5" flood-opacity="0.08"/>
    </filter>
  </defs>
  <rect x="20" y="5" width="660" height="40" rx="6" fill="#dce6f7" stroke="#4a6fa5" stroke-width="1.5" filter="url(#shadow)"/>
  <text x="32" y="22" font-weight="700" fill="#2a3f5f" font-size="11">Layer 6</text>
  <text x="100" y="22" font-weight="600" fill="#2a3f5f">OBSERVABILITY</text>
  <text x="32" y="37" fill="#5a7aa5" font-size="11">metrics, tracing, logging, audit, evaluation</text>
  <text x="670" y="30" text-anchor="end" fill="#888" font-size="11" font-style="italic">How do I monitor?</text>

  <rect x="20" y="50" width="660" height="40" rx="6" fill="#d5e8d4" stroke="#5b8c5a" stroke-width="1.5" filter="url(#shadow)"/>
  <text x="32" y="67" font-weight="700" fill="#2d5a2d" font-size="11">Layer 5</text>
  <text x="100" y="67" font-weight="600" fill="#2d5a2d">ORCHESTRATION</text>
  <text x="32" y="82" fill="#5a8c5a" font-size="11">DAG engine, delegation loop, critique, control flow</text>
  <text x="670" y="75" text-anchor="end" fill="#888" font-size="11" font-style="italic">In what order?</text>

  <rect x="20" y="95" width="660" height="40" rx="6" fill="#fef3cd" stroke="#d4a017" stroke-width="1.5" filter="url(#shadow)"/>
  <text x="32" y="112" font-weight="700" fill="#856404" font-size="11">Layer 4</text>
  <text x="100" y="112" font-weight="600" fill="#856404">MEMORY &amp; STATE</text>
  <text x="32" y="127" fill="#a88a04" font-size="11">state model, memory tiers, sharing</text>
  <text x="670" y="120" text-anchor="end" fill="#888" font-size="11" font-style="italic">What does it remember?</text>

  <rect x="20" y="140" width="660" height="40" rx="6" fill="#e8d5f5" stroke="#7b4ea3" stroke-width="1.5" filter="url(#shadow)"/>
  <text x="32" y="157" font-weight="700" fill="#5a2d82" font-size="11">Layer 3</text>
  <text x="100" y="157" font-weight="600" fill="#5a2d82">COMMUNICATION</text>
  <text x="32" y="172" fill="#7b4ea3" font-size="11">message bus, channels, envelopes</text>
  <text x="670" y="165" text-anchor="end" fill="#888" font-size="11" font-style="italic">How do agents talk?</text>

  <rect x="20" y="185" width="660" height="40" rx="6" fill="#fde2e2" stroke="#c0392b" stroke-width="1.5" filter="url(#shadow)"/>
  <text x="32" y="202" font-weight="700" fill="#922b21" font-size="11">Layer 2</text>
  <text x="100" y="202" font-weight="600" fill="#922b21">CAPABILITIES</text>
  <text x="32" y="217" fill="#c0392b" font-size="11">tools, skills, data sources, sandbox</text>
  <text x="670" y="210" text-anchor="end" fill="#888" font-size="11" font-style="italic">What can it do?</text>

  <rect x="20" y="230" width="660" height="40" rx="6" fill="#d5f5e3" stroke="#27ae60" stroke-width="1.5" filter="url(#shadow)"/>
  <text x="32" y="247" font-weight="700" fill="#1a6b3c" font-size="11">Layer 1</text>
  <text x="100" y="247" font-weight="600" fill="#1a6b3c">AGENT IDENTITY</text>
  <text x="32" y="262" fill="#27ae60" font-size="11">identity, model, prompt, output</text>
  <text x="670" y="255" text-anchor="end" fill="#888" font-size="11" font-style="italic">Who is this agent?</text>

  <rect x="20" y="275" width="660" height="40" rx="6" fill="#f0f0f0" stroke="#888" stroke-width="1.5" filter="url(#shadow)"/>
  <text x="32" y="292" font-weight="700" fill="#333" font-size="11">Layer 0</text>
  <text x="100" y="292" font-weight="600" fill="#333">MANIFEST</text>
  <text x="32" y="307" fill="#666" font-size="11">workflow metadata, dependencies, env</text>
  <text x="670" y="300" text-anchor="end" fill="#888" font-size="11" font-style="italic">What is this workflow?</text>

  <rect x="20" y="322" width="660" height="16" rx="3" fill="#fff3e0" stroke="#e65100" stroke-width="1" stroke-dasharray="4,2"/>
  <text x="350" y="334" text-anchor="middle" fill="#e65100" font-size="10" font-weight="600">SECURITY — cross-cutting: circuit breaker, rate limiting, access control, secrets, audit</text>
</svg>

## Layer Dependency Diagram

Layers form a dependency graph, not a strict stack. Each layer depends only on the layers it needs:

<svg viewBox="0 0 600 260" xmlns="http://www.w3.org/2000/svg" font-family="system-ui, -apple-system, sans-serif" font-size="12">
  <defs>
    <marker id="arr" markerWidth="8" markerHeight="6" refX="8" refY="3" orient="auto"><path d="M0,0 L8,3 L0,6" fill="#666"/></marker>
  </defs>
  <!-- Nodes -->
  <rect x="10" y="10" width="140" height="30" rx="5" fill="#dce6f7" stroke="#4a6fa5" stroke-width="1.2"/>
  <text x="80" y="30" text-anchor="middle" fill="#2a3f5f" font-weight="600" font-size="11">L6 Observability</text>

  <rect x="230" y="10" width="140" height="30" rx="5" fill="#d5e8d4" stroke="#5b8c5a" stroke-width="1.2"/>
  <text x="300" y="30" text-anchor="middle" fill="#2d5a2d" font-weight="600" font-size="11">L5 Orchestration</text>

  <rect x="10" y="80" width="120" height="30" rx="5" fill="#fef3cd" stroke="#d4a017" stroke-width="1.2"/>
  <text x="70" y="100" text-anchor="middle" fill="#856404" font-weight="600" font-size="11">L4 Memory</text>

  <rect x="150" y="80" width="120" height="30" rx="5" fill="#e8d5f5" stroke="#7b4ea3" stroke-width="1.2"/>
  <text x="210" y="100" text-anchor="middle" fill="#5a2d82" font-weight="600" font-size="11">L3 Communication</text>

  <rect x="290" y="80" width="120" height="30" rx="5" fill="#fde2e2" stroke="#c0392b" stroke-width="1.2"/>
  <text x="350" y="100" text-anchor="middle" fill="#922b21" font-weight="600" font-size="11">L2 Capabilities</text>

  <rect x="150" y="150" width="140" height="30" rx="5" fill="#d5f5e3" stroke="#27ae60" stroke-width="1.2"/>
  <text x="220" y="170" text-anchor="middle" fill="#1a6b3c" font-weight="600" font-size="11">L1 Agent Identity</text>

  <rect x="150" y="210" width="140" height="30" rx="5" fill="#f0f0f0" stroke="#888" stroke-width="1.2"/>
  <text x="220" y="230" text-anchor="middle" fill="#333" font-weight="600" font-size="11">L0 Manifest</text>

  <!-- Security -->
  <rect x="440" y="70" width="140" height="30" rx="5" fill="#fff3e0" stroke="#e65100" stroke-width="1.2" stroke-dasharray="4,2"/>
  <text x="510" y="90" text-anchor="middle" fill="#e65100" font-weight="600" font-size="11">Security</text>
  <text x="510" y="118" text-anchor="middle" fill="#999" font-size="10" font-style="italic">cross-cuts all layers</text>

  <!-- Edges -->
  <line x1="150" y1="25" x2="228" y2="25" stroke="#666" stroke-width="1.2" marker-end="url(#arr)"/>
  <line x1="300" y1="42" x2="230" y2="148" stroke="#666" stroke-width="1.2" marker-end="url(#arr)"/>
  <line x1="70" y1="112" x2="185" y2="148" stroke="#666" stroke-width="1.2" marker-end="url(#arr)"/>
  <line x1="210" y1="112" x2="215" y2="148" stroke="#666" stroke-width="1.2" marker-end="url(#arr)"/>
  <line x1="350" y1="112" x2="255" y2="148" stroke="#666" stroke-width="1.2" marker-end="url(#arr)"/>
  <line x1="220" y1="182" x2="220" y2="208" stroke="#666" stroke-width="1.2" marker-end="url(#arr)"/>
</svg>

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
