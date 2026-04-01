# Architecture & Design Decisions

**How AWP differs from every other agent framework — and why it matters.**

---

## The Core Insight

Every multi-agent framework asks the same question: *How do you get multiple AI agents to collaborate?* But most frameworks answer it at the wrong level of abstraction. They give you code primitives — classes, decorators, function calls — and leave the architecture to you. AWP inverts this: **the architecture is the product**. The code is just a runtime that interprets it.

This document traces a single idea — *separation of intent from execution* — from abstract principle to concrete implementation. Along the way, it reveals why this separation unlocks capabilities that code-first frameworks structurally cannot provide.

---

## Table of Contents

1. [The Landscape: Why Another Framework?](#1-the-landscape-why-another-framework)
2. [The Separation Principle](#2-the-separation-principle)
3. [Architectural Comparison](#3-architectural-comparison-awp-vs-the-field)
4. [The Autonomy Spectrum: A Design Innovation](#4-the-autonomy-spectrum-a-design-innovation)
5. [Runtime Capability Genesis](#5-runtime-capability-genesis-tools--skills-from-nothing)
6. [The Problem-Solving Paradigm](#6-the-problem-solving-paradigm)
7. [Solving Complex Problems](#7-solving-complex-problems-the-delegation-architecture)
8. [The Safety Architecture](#8-the-safety-architecture)
9. [What Scientists Can Do Now](#9-what-scientists-can-do-now)
10. [From Abstract Idea to Running System](#10-from-abstract-idea-to-running-system)
11. [Conclusion: The Insight](#11-conclusion-the-insight)

---

## 1. The Landscape: Why Another Framework?

The multi-agent ecosystem in 2024-2026 produced a wave of frameworks, each solving a piece of the puzzle:

| Framework | Core Idea | Strength | Structural Limitation |
|-----------|-----------|----------|----------------------|
| **LangChain/LangGraph** | Chains of LLM calls as graphs | Composability, huge ecosystem | Graph = code. No declarative layer. Migration requires rewriting. |
| **CrewAI** | Role-playing agents with delegation | Intuitive mental model | Flat hierarchy. No budget enforcement. Tools are static. |
| **AutoGen (Microsoft)** | Conversational agent groups | Multi-turn dialogue patterns | Conversation-centric — struggles with non-chat workflows. |
| **Semantic Kernel (Microsoft)** | Plugin-based AI orchestration | Enterprise integration | Plugin model doesn't support dynamic capability creation. |
| **Google A2A** | Agent-to-Agent communication protocol | Interoperability standard, vendor-neutral | Communication only — no orchestration, no workflow definition, no safety envelope. |
| **Google ADK** | Code-first agent development kit | Deep Google Cloud integration, function calling | Code-first. No declarative workflow layer. Tightly coupled to Gemini ecosystem. |
| **OpenAI Agents SDK** | Agent handoffs with guardrails (Swarm successor) | Simple API, built-in tracing, guardrails | No declarative layer. No budget enforcement. No dynamic capability creation. |
| **Amazon Bedrock Agents** | Managed agent service with knowledge bases | Fully managed, enterprise-grade, AWS integration | Vendor-locked. No custom orchestration. Limited autonomy — agents can't create tools or sub-agents. |
| **MetaGPT** | Software-company metaphor (PM, Architect, Engineer) | Strong for code generation | Domain-locked metaphor. Hard to adapt to non-software tasks. |
| **DSPy** | Programmatic prompt optimization | Systematic prompt engineering | Not an orchestration framework. Single-agent focus. |
| **Haystack** | Pipeline-based NLP/RAG | Strong RAG patterns | Pipeline paradigm limits agent autonomy. |

Each framework makes a fundamental trade-off. They either give you **freedom without structure** (LangGraph, Google ADK) or **structure without freedom** (MetaGPT, Bedrock Agents). Some — like Google A2A — solve interoperability at the communication layer but leave orchestration and safety to the developer. AWP's thesis is that you don't have to choose.

<p align="center">
<svg viewBox="0 0 700 480" xmlns="http://www.w3.org/2000/svg" font-family="system-ui, -apple-system, sans-serif" width="700" height="480">
  <defs>
    <marker id="ah1" markerWidth="8" markerHeight="6" refX="8" refY="3" orient="auto"><path d="M0,0 L8,3 L0,6" fill="#64748b"/></marker>
  </defs>
  <rect width="700" height="480" rx="12" fill="#0f172a"/>
  <text x="350" y="36" text-anchor="middle" fill="#94a3b8" font-size="15" font-weight="600">THE FRAMEWORK DESIGN SPACE</text>
  <!-- Axes -->
  <line x1="80" y1="420" x2="650" y2="420" stroke="#334155" stroke-width="1.5" marker-end="url(#ah1)"/>
  <line x1="80" y1="420" x2="80" y2="60" stroke="#334155" stroke-width="1.5" marker-end="url(#ah1)"/>
  <text x="370" y="455" text-anchor="middle" fill="#94a3b8" font-size="13">Structure</text>
  <text x="40" y="240" text-anchor="middle" fill="#94a3b8" font-size="13" transform="rotate(-90,40,240)">Freedom</text>
  <!-- Quadrant labels -->
  <text x="180" y="78" fill="#334155" font-size="9" font-style="italic">code-first / flexible</text>
  <text x="480" y="78" fill="#334155" font-size="9" font-style="italic">structured / flexible</text>
  <text x="180" y="410" fill="#334155" font-size="9" font-style="italic">code-first / constrained</text>
  <text x="480" y="410" fill="#334155" font-size="9" font-style="italic">structured / constrained</text>
  <!-- Framework dots — code-first, high freedom -->
  <circle cx="180" cy="120" r="8" fill="#475569" opacity="0.8"/><text x="180" y="108" text-anchor="middle" fill="#cbd5e1" font-size="11">LangGraph</text>
  <circle cx="190" cy="180" r="8" fill="#475569" opacity="0.8"/><text x="190" y="168" text-anchor="middle" fill="#cbd5e1" font-size="11">AutoGen</text>
  <circle cx="210" cy="240" r="8" fill="#475569" opacity="0.8"/><text x="210" y="228" text-anchor="middle" fill="#cbd5e1" font-size="11">CrewAI</text>
  <!-- New frameworks -->
  <circle cx="270" cy="170" r="8" fill="#475569" opacity="0.8"/><text x="270" y="158" text-anchor="middle" fill="#cbd5e1" font-size="11">Google ADK</text>
  <circle cx="320" cy="190" r="8" fill="#475569" opacity="0.8"/><text x="320" y="178" text-anchor="middle" fill="#cbd5e1" font-size="11">OpenAI Agents SDK</text>
  <circle cx="460" cy="300" r="8" fill="#3b82f6" opacity="0.7"/><text x="460" y="288" text-anchor="middle" fill="#93c5fd" font-size="11">Google A2A</text>
  <text x="460" y="318" text-anchor="middle" fill="#64748b" font-size="8">(protocol, not framework)</text>
  <circle cx="500" cy="350" r="8" fill="#475569" opacity="0.8"/><text x="500" y="340" text-anchor="middle" fill="#cbd5e1" font-size="11">Bedrock Agents</text>
  <!-- Existing frameworks -->
  <circle cx="330" cy="300" r="8" fill="#475569" opacity="0.8"/><text x="330" y="288" text-anchor="middle" fill="#cbd5e1" font-size="11">MetaGPT</text>
  <circle cx="160" cy="350" r="8" fill="#475569" opacity="0.8"/><text x="160" y="338" text-anchor="middle" fill="#cbd5e1" font-size="11">DSPy</text>
  <circle cx="400" cy="340" r="8" fill="#475569" opacity="0.8"/><text x="400" y="360" text-anchor="middle" fill="#cbd5e1" font-size="11">Semantic Kernel</text>
  <circle cx="290" cy="370" r="8" fill="#475569" opacity="0.8"/><text x="290" y="390" text-anchor="middle" fill="#cbd5e1" font-size="11">Haystack</text>
  <!-- AWP star -->
  <polygon points="540,130 546,148 566,148 550,160 556,178 540,166 524,178 530,160 514,148 534,148" fill="#f59e0b"/>
  <text x="540" y="118" text-anchor="middle" fill="#fbbf24" font-size="13" font-weight="700">AWP</text>
  <text x="540" y="198" text-anchor="middle" fill="#fbbf24" font-size="10" font-style="italic">(freedom + structure)</text>
  <!-- Legend hint -->
  <circle cx="100" cy="455" r="5" fill="#3b82f6" opacity="0.7"/><text x="110" y="459" fill="#64748b" font-size="9">= protocol (interop layer)</text>
  <circle cx="250" cy="455" r="5" fill="#475569" opacity="0.8"/><text x="260" y="459" fill="#64748b" font-size="9">= framework (orchestration)</text>
</svg>
</p>

**AWP occupies a unique position**: maximum structural guarantees (formal validation, budget enforcement, safety layers) combined with maximum runtime freedom (agents create their own tools, skills, and sub-agents).

---

## 2. The Separation Principle

The central design decision in AWP is the **separation of workflow definition from workflow execution**.

<p align="center">
<svg viewBox="0 0 700 300" xmlns="http://www.w3.org/2000/svg" font-family="system-ui, -apple-system, sans-serif" width="700" height="300">
  <rect width="700" height="300" rx="12" fill="#0f172a"/>
  <text x="350" y="32" text-anchor="middle" fill="#94a3b8" font-size="15" font-weight="600">THE SEPARATION PRINCIPLE</text>
  <!-- Definition box -->
  <rect x="30" y="55" width="260" height="200" rx="8" fill="#1e293b" stroke="#3b82f6" stroke-width="2"/>
  <text x="160" y="80" text-anchor="middle" fill="#60a5fa" font-size="13" font-weight="600">DEFINITION LAYER</text>
  <text x="50" y="108" fill="#cbd5e1" font-size="11">workflow.awp.yaml</text>
  <text x="50" y="128" fill="#cbd5e1" font-size="11">agent.awp.yaml</text>
  <text x="50" y="148" fill="#cbd5e1" font-size="11">skills/*.md</text>
  <text x="50" y="168" fill="#cbd5e1" font-size="11">mcp/*.py</text>
  <line x1="50" y1="185" x2="270" y2="185" stroke="#334155" stroke-width="1"/>
  <text x="160" y="210" text-anchor="middle" fill="#60a5fa" font-size="12" font-weight="500">WHAT should happen</text>
  <text x="160" y="230" text-anchor="middle" fill="#64748b" font-size="11">(declarative)</text>
  <text x="160" y="270" text-anchor="middle" fill="#475569" font-size="10">awp-core (protocol)</text>
  <!-- Arrow -->
  <line x1="300" y1="155" x2="400" y2="155" stroke="#f59e0b" stroke-width="2.5" marker-end="url(#ah1)"/>
  <text x="350" y="140" text-anchor="middle" fill="#fbbf24" font-size="10">parse</text>
  <text x="350" y="155" text-anchor="middle" fill="#fbbf24" font-size="10">validate</text>
  <text x="350" y="170" text-anchor="middle" fill="#fbbf24" font-size="10">run</text>
  <!-- Execution box -->
  <rect x="410" y="55" width="260" height="200" rx="8" fill="#1e293b" stroke="#10b981" stroke-width="2"/>
  <text x="540" y="80" text-anchor="middle" fill="#34d399" font-size="13" font-weight="600">EXECUTION LAYER</text>
  <text x="430" y="108" fill="#cbd5e1" font-size="11">awp-runtime</text>
  <text x="430" y="138" fill="#cbd5e1" font-size="11">DAG Engine</text>
  <text x="430" y="158" fill="#cbd5e1" font-size="11">Delegation Engine</text>
  <text x="430" y="178" fill="#cbd5e1" font-size="11">Tool Registry</text>
  <line x1="430" y1="195" x2="650" y2="195" stroke="#334155" stroke-width="1"/>
  <text x="540" y="220" text-anchor="middle" fill="#34d399" font-size="12" font-weight="500">HOW it happens</text>
  <text x="540" y="240" text-anchor="middle" fill="#64748b" font-size="11">(imperative)</text>
  <text x="540" y="270" text-anchor="middle" fill="#475569" font-size="10">awp-runtime (execution)</text>
</svg>
</p>

This separation has consequences that ripple through every design decision:

**1. Portability.** A `workflow.awp.yaml` is a contract. Any runtime that speaks AWP can execute it. Today that runtime is Python. Tomorrow it could be Rust, Go, or a cloud service. The workflow doesn't change.

**2. Validation before execution.** Because the intent is declarative, AWP can statically analyze a workflow *before any LLM call is made*. The 24 validation rules (R1-R24) catch structural errors, naming violations, missing dependencies, and unsafe configurations at parse time — not at runtime.

**3. Reproducibility.** The same YAML produces the same execution plan. The LLM outputs vary, but the orchestration topology, budget constraints, and safety boundaries are deterministic.

**4. Governance.** A YAML file can be reviewed, versioned, diffed, and approved — just like infrastructure-as-code. You can't meaningfully review a LangGraph program without running it.

### Why Other Frameworks Don't Separate

| Framework | Definition | Execution | Separation? |
|-----------|-----------|-----------|-------------|
| LangGraph | Python code (StateGraph) | Same Python code | No — code IS the workflow |
| CrewAI | Python classes (Agent, Task, Crew) | Method calls | No — imperative only |
| AutoGen (Microsoft) | Python agent config | Conversation runtime | Partial — config is shallow |
| Semantic Kernel (Microsoft) | Plugin definitions + planners | Kernel execution | Partial — plugins are code, planners are internal |
| Google A2A | JSON Agent Cards + Task protocol | Any compliant runtime | Partial — defines interop, not workflow structure |
| Google ADK | Python agent classes + tools | Google Cloud runtime | No — code-first, agents are classes |
| OpenAI Agents SDK | Python agent definitions | Runner execution | No — imperative, agents defined in code |
| Amazon Bedrock Agents | Console/API config + action groups | Managed AWS runtime | Partial — config is GUI/API, limited expressiveness |
| MetaGPT | Python roles + actions | Subscription bus | No — roles are classes |
| **AWP** | YAML (7-layer model) | Python runtime engines | **Full separation** |

The analogy is **Docker Compose vs. shell scripts**. Both can start containers. But only Compose gives you a declarative specification that tools can parse, validate, visualize, and transform without executing anything.

---

## 3. Architectural Comparison: AWP vs. The Field

### 3.1 The 7-Layer Model vs. Flat Abstractions

Most frameworks organize agents as flat collections of objects. AWP structures the *entire system* into seven semantic layers:

<p align="center">
<svg viewBox="0 0 640 400" xmlns="http://www.w3.org/2000/svg" font-family="system-ui, -apple-system, sans-serif" width="640" height="400">
  <rect width="640" height="400" rx="12" fill="#0f172a"/>
  <!-- Layer stack -->
  <rect x="60" y="40" width="420" height="42" rx="6" fill="#7c3aed" opacity="0.25" stroke="#7c3aed" stroke-width="1.5"/>
  <text x="80" y="66" fill="#a78bfa" font-size="12" font-weight="600">Layer 6: OBSERVABILITY</text>
  <text x="320" y="66" fill="#cbd5e1" font-size="11">Metrics, tracing, audit</text>
  <rect x="60" y="88" width="420" height="42" rx="6" fill="#ec4899" opacity="0.2" stroke="#ec4899" stroke-width="1.5"/>
  <text x="80" y="114" fill="#f472b6" font-size="12" font-weight="600">Layer 5: ORCHESTRATION</text>
  <text x="320" y="114" fill="#cbd5e1" font-size="11">DAG or Delegation Loop</text>
  <rect x="60" y="136" width="420" height="42" rx="6" fill="#f59e0b" opacity="0.2" stroke="#f59e0b" stroke-width="1.5"/>
  <text x="80" y="162" fill="#fbbf24" font-size="12" font-weight="600">Layer 4: MEMORY &amp; STATE</text>
  <text x="320" y="162" fill="#cbd5e1" font-size="11">4-tier memory, state sharing</text>
  <rect x="60" y="184" width="420" height="42" rx="6" fill="#14b8a6" opacity="0.2" stroke="#14b8a6" stroke-width="1.5"/>
  <text x="80" y="210" fill="#2dd4bf" font-size="12" font-weight="600">Layer 3: COMMUNICATION</text>
  <text x="320" y="210" fill="#cbd5e1" font-size="11">Message bus, channels</text>
  <rect x="60" y="232" width="420" height="42" rx="6" fill="#3b82f6" opacity="0.2" stroke="#3b82f6" stroke-width="1.5"/>
  <text x="80" y="258" fill="#60a5fa" font-size="12" font-weight="600">Layer 2: CAPABILITIES</text>
  <text x="320" y="258" fill="#cbd5e1" font-size="11">Tools, skills, sandbox</text>
  <rect x="60" y="280" width="420" height="42" rx="6" fill="#10b981" opacity="0.2" stroke="#10b981" stroke-width="1.5"/>
  <text x="80" y="306" fill="#34d399" font-size="12" font-weight="600">Layer 1: AGENT IDENTITY</text>
  <text x="320" y="306" fill="#cbd5e1" font-size="11">Role, model, prompts</text>
  <rect x="60" y="328" width="420" height="42" rx="6" fill="#64748b" opacity="0.3" stroke="#64748b" stroke-width="1.5"/>
  <text x="80" y="354" fill="#94a3b8" font-size="12" font-weight="600">Layer 0: MANIFEST</text>
  <text x="320" y="354" fill="#cbd5e1" font-size="11">Metadata, dependencies</text>
  <!-- Annotations -->
  <text x="510" y="200" fill="#64748b" font-size="10">Each layer has its own</text>
  <text x="510" y="214" fill="#64748b" font-size="10">YAML section</text>
  <text x="510" y="240" fill="#64748b" font-size="10">Each layer can evolve</text>
  <text x="510" y="254" fill="#64748b" font-size="10">independently</text>
  <text x="510" y="280" fill="#64748b" font-size="10">Each layer maps to a</text>
  <text x="510" y="294" fill="#64748b" font-size="10">Pydantic model</text>
</svg>
</p>

**Why layers matter:**
- **Modularity.** Change your orchestration strategy (Layer 5) without touching agent identity (Layer 1) or tool definitions (Layer 2).
- **Progressive disclosure.** A simple A0 workflow only needs Layer 0, 1, and 5. You add layers as complexity demands.
- **Formal boundaries.** Each layer has its own validation rules. A Layer 2 violation (bad tool namespace) doesn't cascade into Layer 5 failures.

**Comparison:**
- LangGraph: Everything is one graph object. Agent config, tools, state, and orchestration are mixed in a single `StateGraph`.
- CrewAI: Agent and Task are separate, but there's no formal layer for communication, memory, or observability.
- AutoGen: Agents and group chats, but memory, tools, and orchestration are all informal.

### 3.2 Two Engines vs. One Paradigm

Every other framework commits to a single execution paradigm:

| Framework | Paradigm | Limitation |
|-----------|----------|-----------|
| LangGraph | State machine | All workflows must be expressible as state transitions |
| CrewAI | Sequential/hierarchical crew | No true DAG support, limited parallelism |
| AutoGen (Microsoft) | Conversation turns | Non-conversational workflows feel forced |
| Semantic Kernel (Microsoft) | Planner + plugins | Plugins are static; planner is a single-step coordinator, not a multi-agent orchestrator |
| Google ADK | Code-first agent classes | Agents are Python objects — no declarative topology, no formal validation |
| Google A2A | Agent-to-Agent protocol | Defines communication, not orchestration — no workflow engine, no safety envelope |
| OpenAI Agents SDK | Handoff chains | Linear handoff model — no DAG, no budget, no recursive delegation |
| Amazon Bedrock Agents | Managed action groups | Vendor-locked execution — no custom engines, no dynamic capability creation |
| MetaGPT | Pub/sub actions | Overkill for simple sequential workflows |

AWP provides **two engines** optimized for different workflow topologies:

<p align="center">
<svg viewBox="0 0 740 380" xmlns="http://www.w3.org/2000/svg" font-family="system-ui, -apple-system, sans-serif" width="740" height="380">
  <defs>
    <marker id="ah2" markerWidth="8" markerHeight="6" refX="8" refY="3" orient="auto"><path d="M0,0 L8,3 L0,6" fill="#60a5fa"/></marker>
    <marker id="ah3" markerWidth="8" markerHeight="6" refX="8" refY="3" orient="auto"><path d="M0,0 L8,3 L0,6" fill="#f59e0b"/></marker>
  </defs>
  <rect width="740" height="380" rx="12" fill="#0f172a"/>
  <!-- Divider -->
  <line x1="370" y1="20" x2="370" y2="360" stroke="#334155" stroke-width="1" stroke-dasharray="4,4"/>
  <!-- DAG side -->
  <text x="185" y="36" text-anchor="middle" fill="#60a5fa" font-size="14" font-weight="600">engine: dag</text>
  <rect x="100" y="60" width="70" height="34" rx="6" fill="#1e3a5f" stroke="#3b82f6" stroke-width="1.5"/>
  <text x="135" y="82" text-anchor="middle" fill="#93c5fd" font-size="12">A1</text>
  <rect x="210" y="60" width="70" height="34" rx="6" fill="#1e3a5f" stroke="#3b82f6" stroke-width="1.5"/>
  <text x="245" y="82" text-anchor="middle" fill="#93c5fd" font-size="12">A2</text>
  <rect x="210" y="130" width="70" height="34" rx="6" fill="#1e3a5f" stroke="#3b82f6" stroke-width="1.5"/>
  <text x="245" y="152" text-anchor="middle" fill="#93c5fd" font-size="12">A3</text>
  <rect x="290" y="60" width="70" height="34" rx="6" fill="#1e3a5f" stroke="#3b82f6" stroke-width="1.5"/>
  <text x="325" y="82" text-anchor="middle" fill="#93c5fd" font-size="12">A4</text>
  <line x1="170" y1="77" x2="205" y2="77" stroke="#60a5fa" stroke-width="1.5" marker-end="url(#ah2)"/>
  <line x1="280" y1="77" x2="285" y2="77" stroke="#60a5fa" stroke-width="1.5" marker-end="url(#ah2)"/>
  <line x1="245" y1="94" x2="245" y2="125" stroke="#60a5fa" stroke-width="1.5" marker-end="url(#ah2)"/>
  <text x="185" y="200" text-anchor="middle" fill="#64748b" font-size="11">Predetermined topology</text>
  <text x="185" y="216" text-anchor="middle" fill="#64748b" font-size="11">Static agent set</text>
  <text x="185" y="232" text-anchor="middle" fill="#60a5fa" font-size="11" font-weight="500">A0-A1 autonomy</text>
  <!-- Delegation side -->
  <text x="555" y="36" text-anchor="middle" fill="#f59e0b" font-size="14" font-weight="600">engine: delegation_loop</text>
  <!-- Manager 1 -->
  <rect x="510" y="55" width="90" height="34" rx="6" fill="#422006" stroke="#f59e0b" stroke-width="1.5"/>
  <text x="555" y="77" text-anchor="middle" fill="#fbbf24" font-size="12">Manager</text>
  <!-- Workers row 1 -->
  <line x1="530" y1="89" x2="470" y2="115" stroke="#f59e0b" stroke-width="1.2" marker-end="url(#ah3)"/>
  <line x1="555" y1="89" x2="555" y2="115" stroke="#f59e0b" stroke-width="1.2" marker-end="url(#ah3)"/>
  <line x1="580" y1="89" x2="640" y2="115" stroke="#f59e0b" stroke-width="1.2" marker-end="url(#ah3)"/>
  <rect x="440" y="120" width="60" height="30" rx="5" fill="#1e293b" stroke="#64748b" stroke-width="1"/>
  <text x="470" y="140" text-anchor="middle" fill="#cbd5e1" font-size="10">W1</text>
  <rect x="525" y="120" width="60" height="30" rx="5" fill="#1e293b" stroke="#64748b" stroke-width="1"/>
  <text x="555" y="140" text-anchor="middle" fill="#cbd5e1" font-size="10">W2</text>
  <rect x="610" y="120" width="60" height="30" rx="5" fill="#1e293b" stroke="#64748b" stroke-width="1"/>
  <text x="640" y="140" text-anchor="middle" fill="#cbd5e1" font-size="10">W3</text>
  <text x="700" y="140" fill="#64748b" font-size="9" font-style="italic">Ephemeral</text>
  <!-- Loop arrow -->
  <line x1="555" y1="155" x2="555" y2="178" stroke="#f59e0b" stroke-width="1.2" marker-end="url(#ah3)"/>
  <!-- Manager 2 -->
  <rect x="510" y="183" width="90" height="34" rx="6" fill="#422006" stroke="#f59e0b" stroke-width="1.5"/>
  <text x="555" y="205" text-anchor="middle" fill="#fbbf24" font-size="12">Manager</text>
  <text x="620" y="205" fill="#64748b" font-size="9">Loop N+1</text>
  <!-- Workers row 2 -->
  <line x1="535" y1="217" x2="500" y2="243" stroke="#f59e0b" stroke-width="1.2" marker-end="url(#ah3)"/>
  <line x1="575" y1="217" x2="610" y2="243" stroke="#f59e0b" stroke-width="1.2" marker-end="url(#ah3)"/>
  <rect x="470" y="248" width="60" height="30" rx="5" fill="#1e293b" stroke="#64748b" stroke-width="1"/>
  <text x="500" y="268" text-anchor="middle" fill="#cbd5e1" font-size="10">W4</text>
  <rect x="580" y="248" width="60" height="30" rx="5" fill="#1e293b" stroke="#64748b" stroke-width="1"/>
  <text x="610" y="268" text-anchor="middle" fill="#cbd5e1" font-size="10">W5</text>
  <text x="660" y="268" fill="#64748b" font-size="9" font-style="italic">New workers</text>
  <text x="555" y="320" text-anchor="middle" fill="#64748b" font-size="11">Dynamic topology</text>
  <text x="555" y="336" text-anchor="middle" fill="#64748b" font-size="11">Ephemeral agents</text>
  <text x="555" y="352" text-anchor="middle" fill="#f59e0b" font-size="11" font-weight="500">A2-A4 autonomy</text>
</svg>
</p>

**DAG Engine** (A0-A1): Topological execution of a predetermined graph. Agents run in dependency order. State flows along edges. Simple, fast, predictable. Use this when you know the exact workflow at design time.

**Delegation Loop Engine** (A2-A4): A manager agent dynamically spawns ephemeral workers, each configured with custom instructions, tools, and skills. The manager iterates — analyzing results, spawning new workers, refining strategy — until the task is complete or the budget is exhausted. Use this when the workflow must adapt at runtime.

The choice is a single YAML field: `engine: dag` or `engine: delegation_loop`. The rest of the workflow definition is compatible with both.

### 3.3 Feature Matrix

| Capability | AWP | LangGraph | CrewAI | AutoGen | Google ADK | Google A2A | OpenAI Agents SDK | Bedrock Agents | Semantic Kernel | MetaGPT | Haystack |
|-----------|-----|-----------|--------|---------|------------|------------|-------------------|----------------|-----------------|---------|----------|
| Declarative workflow definition | YAML | Code | Code | Code | Code | JSON (Agent Cards) | Code | Console/API | Code | Code | YAML (pipelines) |
| Static validation before execution | 26 rules | No | No | No | No | Schema only | No | Partial | No | No | No |
| DAG orchestration | Yes | Yes | Limited | No | Sequential | N/A | No | No | Planner | No | Yes |
| Dynamic agent spawning | Yes (A2+) | Manual | Limited | Yes | Limited | N/A | Handoffs | No | No | No | No |
| Runtime tool creation | Yes (A3+) | No | No | No | Possible | No | No | No | No | No | No |
| Runtime skill generation | Yes (A3+) | No | No | No | No | No | No | No | No | No | No |
| Budget enforcement | Formal | No | No | No | No | No | No | Partial (timeouts) | No | No | No |
| Recursive delegation | Yes (A4) | Manual | No | Nested | No | N/A | No | No | No | No | No |
| Stall detection | Automatic | No | No | No | No | No | No | No | No | No | No |
| Sandboxed code execution | 5 sandbox types | No | No | Docker | Cloud Run | No | No | Lambda | No | No | No |
| Multi-tier memory | 4 tiers | Custom | Short/Long | Custom | Session-based | No | No | Knowledge bases | Custom | Custom | No |
| Formal observability | OpenTelemetry | LangSmith | No | No | Cloud Trace | No | Built-in tracing | CloudWatch | No | No | No |
| Provider agnostic | Any OpenAI-compat | LangChain | Limited | OpenAI-first | Gemini-first | Vendor-neutral | OpenAI-only | AWS-only | OpenAI/Azure | OpenAI | Any |
| Cross-vendor interop | YAML portable | No | No | No | No | Yes (core purpose) | No | No | No | No | No |
| Autonomy governance | A0-A4 levels | No | No | No | No | No | Guardrails | IAM policies | No | No | No |

---

## 4. The Autonomy Spectrum: A Design Innovation

Most frameworks give you a binary choice: either agents follow instructions, or they don't. AWP introduces a **graduated autonomy model** — five levels where safety requirements scale proportionally with agent freedom.

<p align="center">
<svg viewBox="0 0 760 420" xmlns="http://www.w3.org/2000/svg" font-family="system-ui, -apple-system, sans-serif" width="760" height="420">
  <defs>
    <linearGradient id="autoGrad" x1="0%" y1="0%" x2="100%" y2="0%">
      <stop offset="0%" stop-color="#334155"/><stop offset="100%" stop-color="#f59e0b"/>
    </linearGradient>
    <marker id="ah4" markerWidth="8" markerHeight="6" refX="8" refY="3" orient="auto"><path d="M0,0 L8,3 L0,6" fill="#94a3b8"/></marker>
  </defs>
  <rect width="760" height="420" rx="12" fill="#0f172a"/>
  <text x="380" y="32" text-anchor="middle" fill="#94a3b8" font-size="15" font-weight="600">THE AUTONOMY SPECTRUM</text>
  <!-- Arrow -->
  <line x1="50" y1="55" x2="710" y2="55" stroke="url(#autoGrad)" stroke-width="3" marker-end="url(#ah4)"/>
  <text x="380" y="50" text-anchor="middle" fill="#94a3b8" font-size="10">AUTONOMY</text>
  <!-- A0 -->
  <rect x="60" y="75" width="110" height="130" rx="8" fill="#1e293b" stroke="#475569" stroke-width="1.5"/>
  <text x="115" y="95" text-anchor="middle" fill="#94a3b8" font-size="13" font-weight="700">A0</text>
  <text x="115" y="112" text-anchor="middle" fill="#64748b" font-size="10">Prescribed</text>
  <rect x="82" y="122" width="66" height="60" rx="4" fill="#334155" opacity="0.5"/>
  <text x="115" y="158" text-anchor="middle" fill="#94a3b8" font-size="18">░░</text>
  <text x="115" y="220" text-anchor="middle" fill="#cbd5e1" font-size="9">Fixed DAG</text>
  <text x="115" y="232" text-anchor="middle" fill="#cbd5e1" font-size="9">Fixed tools</text>
  <text x="115" y="244" text-anchor="middle" fill="#64748b" font-size="9">No budget needed</text>
  <!-- A1 -->
  <rect x="190" y="75" width="110" height="130" rx="8" fill="#1e293b" stroke="#3b82f6" stroke-width="1.5"/>
  <text x="245" y="95" text-anchor="middle" fill="#60a5fa" font-size="13" font-weight="700">A1</text>
  <text x="245" y="112" text-anchor="middle" fill="#64748b" font-size="10">Adaptive</text>
  <rect x="212" y="122" width="66" height="60" rx="4" fill="#1e3a5f" opacity="0.6"/>
  <text x="245" y="158" text-anchor="middle" fill="#60a5fa" font-size="18">▓░</text>
  <text x="245" y="220" text-anchor="middle" fill="#cbd5e1" font-size="9">Conditional</text>
  <text x="245" y="232" text-anchor="middle" fill="#cbd5e1" font-size="9">Loops, Fan-out</text>
  <text x="245" y="244" text-anchor="middle" fill="#64748b" font-size="9">No budget needed</text>
  <!-- A2 -->
  <rect x="320" y="75" width="110" height="130" rx="8" fill="#1e293b" stroke="#f59e0b" stroke-width="1.5"/>
  <text x="375" y="95" text-anchor="middle" fill="#fbbf24" font-size="13" font-weight="700">A2</text>
  <text x="375" y="112" text-anchor="middle" fill="#64748b" font-size="10">Delegating</text>
  <rect x="342" y="122" width="66" height="60" rx="4" fill="#422006" opacity="0.6"/>
  <text x="375" y="158" text-anchor="middle" fill="#fbbf24" font-size="18">▓▓</text>
  <text x="375" y="220" text-anchor="middle" fill="#cbd5e1" font-size="9">Dynamic workers</text>
  <text x="375" y="232" text-anchor="middle" fill="#cbd5e1" font-size="9">Budget required</text>
  <text x="375" y="244" text-anchor="middle" fill="#f59e0b" font-size="9">Safety envelope</text>
  <!-- A3 -->
  <rect x="450" y="75" width="110" height="130" rx="8" fill="#1e293b" stroke="#f97316" stroke-width="1.5"/>
  <text x="505" y="95" text-anchor="middle" fill="#fb923c" font-size="13" font-weight="700">A3</text>
  <text x="505" y="112" text-anchor="middle" fill="#64748b" font-size="10">Self-Tooling</text>
  <rect x="472" y="122" width="66" height="60" rx="4" fill="#7c2d12" opacity="0.5"/>
  <text x="505" y="158" text-anchor="middle" fill="#fb923c" font-size="18">██</text>
  <text x="505" y="220" text-anchor="middle" fill="#cbd5e1" font-size="9">Creates tools &amp;</text>
  <text x="505" y="232" text-anchor="middle" fill="#cbd5e1" font-size="9">skills at runtime</text>
  <text x="505" y="244" text-anchor="middle" fill="#f97316" font-size="9">Budget + sandbox</text>
  <!-- A4 -->
  <rect x="580" y="75" width="110" height="130" rx="8" fill="#1e293b" stroke="#ef4444" stroke-width="1.5"/>
  <text x="635" y="95" text-anchor="middle" fill="#f87171" font-size="13" font-weight="700">A4</text>
  <text x="635" y="112" text-anchor="middle" fill="#64748b" font-size="10">Self-Organizing</text>
  <rect x="602" y="122" width="66" height="60" rx="4" fill="#7f1d1d" opacity="0.5"/>
  <text x="635" y="158" text-anchor="middle" fill="#f87171" font-size="18">██</text>
  <text x="635" y="220" text-anchor="middle" fill="#cbd5e1" font-size="9">Recursive</text>
  <text x="635" y="232" text-anchor="middle" fill="#cbd5e1" font-size="9">delegation</text>
  <text x="635" y="244" text-anchor="middle" fill="#ef4444" font-size="9">Budget hierarchy</text>
  <!-- Safety bar -->
  <line x1="60" y1="280" x2="690" y2="280" stroke="#ef4444" stroke-width="1.5" stroke-dasharray="6,3" marker-end="url(#ah4)"/>
  <text x="380" y="300" text-anchor="middle" fill="#f87171" font-size="11" font-weight="500">SAFETY REQUIREMENTS INCREASE</text>
  <!-- Safety details -->
  <text x="115" y="330" text-anchor="middle" fill="#64748b" font-size="9">No budget</text>
  <text x="245" y="330" text-anchor="middle" fill="#64748b" font-size="9">No budget</text>
  <text x="375" y="326" text-anchor="middle" fill="#fbbf24" font-size="9">Budget</text>
  <text x="375" y="340" text-anchor="middle" fill="#fbbf24" font-size="9">required</text>
  <text x="505" y="326" text-anchor="middle" fill="#fb923c" font-size="9">Budget +</text>
  <text x="505" y="340" text-anchor="middle" fill="#fb923c" font-size="9">sandbox required</text>
  <text x="635" y="326" text-anchor="middle" fill="#f87171" font-size="9">Budget + observ.</text>
  <text x="635" y="340" text-anchor="middle" fill="#f87171" font-size="9">+ depth limit</text>
</svg>
</p>

**Why this matters for design:**

**A0-A1 (Prescribed/Adaptive):** The workflow author defines everything. Agents execute a known plan. This is comparable to what LangGraph and CrewAI provide — but expressed declaratively.

**A2 (Delegating):** The manager agent decides *what work to do and who does it*. Workers are ephemeral — they exist only for the task. This is where AWP diverges from every other framework: the manager doesn't call functions, it *generates agent configurations at runtime*.

**A3 (Self-Tooling):** Agents create their own tools and skills during execution. A data scientist agent might create a `dynamic.normalize_timeseries` tool because no built-in tool fits the data shape. This capability doesn't exist in any other framework.

**A4 (Self-Organizing):** Workers can themselves become managers. A CEO agent delegates to department managers, who delegate to specialists. Budget flows hierarchically — each level receives a fraction of the parent's allocation.

### The Governance Gap

No other framework provides formal autonomy governance:

<p align="center">
<svg viewBox="0 0 660 300" xmlns="http://www.w3.org/2000/svg" font-family="system-ui, -apple-system, sans-serif" width="660" height="300">
  <rect width="660" height="300" rx="12" fill="#0f172a"/>
  <text x="330" y="32" text-anchor="middle" fill="#94a3b8" font-size="15" font-weight="600">GOVERNANCE COMPARISON</text>
  <!-- LangGraph -->
  <text x="130" y="72" text-anchor="end" fill="#cbd5e1" font-size="12">LangGraph</text>
  <rect x="140" y="58" width="400" height="22" rx="4" fill="#dc2626" opacity="0.6"/>
  <text x="550" y="74" fill="#fca5a5" font-size="10">Full code access (trust the developer)</text>
  <!-- CrewAI -->
  <text x="130" y="112" text-anchor="end" fill="#cbd5e1" font-size="12">CrewAI</text>
  <rect x="140" y="98" width="400" height="22" rx="4" fill="#dc2626" opacity="0.5"/>
  <text x="550" y="114" fill="#fca5a5" font-size="10">No budget enforcement (hope for best)</text>
  <!-- AutoGen -->
  <text x="130" y="152" text-anchor="end" fill="#cbd5e1" font-size="12">AutoGen</text>
  <rect x="140" y="138" width="400" height="22" rx="4" fill="#dc2626" opacity="0.4"/>
  <text x="550" y="154" fill="#fca5a5" font-size="10">No formal limits (monitor manually)</text>
  <!-- AWP -->
  <text x="130" y="200" text-anchor="end" fill="#fbbf24" font-size="12" font-weight="600">AWP</text>
  <rect x="140" y="186" width="80" height="22" rx="4" fill="#334155"/><text x="180" y="201" text-anchor="middle" fill="#94a3b8" font-size="9">A0</text>
  <rect x="222" y="186" width="80" height="22" rx="4" fill="#3b82f6" opacity="0.5"/><text x="262" y="201" text-anchor="middle" fill="#93c5fd" font-size="9">A1</text>
  <rect x="304" y="186" width="80" height="22" rx="4" fill="#f59e0b" opacity="0.5"/><text x="344" y="201" text-anchor="middle" fill="#fbbf24" font-size="9">A2</text>
  <rect x="386" y="186" width="80" height="22" rx="4" fill="#f97316" opacity="0.5"/><text x="426" y="201" text-anchor="middle" fill="#fb923c" font-size="9">A3</text>
  <rect x="468" y="186" width="72" height="22" rx="4" fill="#ef4444" opacity="0.5"/><text x="504" y="201" text-anchor="middle" fill="#f87171" font-size="9">A4</text>
  <text x="400" y="228" text-anchor="middle" fill="#34d399" font-size="10">Graduated autonomy (formal safety at each level)</text>
  <!-- Safety annotations -->
  <line x1="304" y1="240" x2="540" y2="240" stroke="#f59e0b" stroke-width="1" stroke-dasharray="3,2"/>
  <text x="420" y="254" text-anchor="middle" fill="#fbbf24" font-size="9">Budget required</text>
  <line x1="386" y1="262" x2="540" y2="262" stroke="#f97316" stroke-width="1" stroke-dasharray="3,2"/>
  <text x="463" y="276" text-anchor="middle" fill="#fb923c" font-size="9">Sandbox enforced</text>
</svg>
</p>

---

## 5. Runtime Capability Genesis: Tools & Skills from Nothing

This is AWP's most radical departure from the field. At A3 and above, agents don't just *use* tools — they *create* them.

### 5.1 The Problem

Traditional agent frameworks provide a fixed toolbox:

```python
# LangGraph / CrewAI / AutoGen pattern:
tools = [search_tool, calculator_tool, file_tool]
agent = Agent(tools=tools)  # Tools fixed at instantiation
```

This creates the **competence dilemma**: you either give agents too many tools (wasting context, increasing hallucination risk) or too few (limiting their problem-solving ability). Neither option is good.

### 5.2 AWP's Solution: Code Mode + Dynamic Tool Factory

AWP solves this with two mechanisms that work together:

<p align="center">
<svg viewBox="0 0 720 560" xmlns="http://www.w3.org/2000/svg" font-family="system-ui, -apple-system, sans-serif" width="720" height="560">
  <defs>
    <marker id="ah5" markerWidth="8" markerHeight="6" refX="8" refY="3" orient="auto"><path d="M0,0 L8,3 L0,6" fill="#f59e0b"/></marker>
    <marker id="ah5g" markerWidth="8" markerHeight="6" refX="8" refY="3" orient="auto"><path d="M0,0 L8,3 L0,6" fill="#34d399"/></marker>
  </defs>
  <rect width="720" height="560" rx="12" fill="#0f172a"/>
  <text x="360" y="30" text-anchor="middle" fill="#94a3b8" font-size="15" font-weight="600">RUNTIME CAPABILITY GENESIS</text>
  <!-- Step 1 -->
  <circle cx="50" cy="65" r="14" fill="#422006" stroke="#f59e0b" stroke-width="1.5"/><text x="50" y="70" text-anchor="middle" fill="#fbbf24" font-size="12" font-weight="700">1</text>
  <text x="75" y="62" fill="#fbbf24" font-size="12" font-weight="600">MANAGER ANALYZES TASK</text>
  <text x="75" y="80" fill="#94a3b8" font-size="10">"I need to normalize 47 different time series formats. No built-in tool handles this."</text>
  <!-- Step 2 -->
  <circle cx="50" cy="125" r="14" fill="#422006" stroke="#f59e0b" stroke-width="1.5"/><text x="50" y="130" text-anchor="middle" fill="#fbbf24" font-size="12" font-weight="700">2</text>
  <text x="75" y="122" fill="#fbbf24" font-size="12" font-weight="600">MANAGER CREATES WORKER WITH CODE MODE</text>
  <rect x="90" y="138" width="300" height="100" rx="6" fill="#1e293b" stroke="#475569" stroke-width="1"/>
  <text x="105" y="158" fill="#64748b" font-size="10">DelegationEnvelope:</text>
  <text x="115" y="174" fill="#cbd5e1" font-size="10">instructions: "Build a normalization tool"</text>
  <text x="115" y="190" fill="#34d399" font-size="10">codemode: enabled: true</text>
  <text x="115" y="206" fill="#34d399" font-size="10">tool_creation: true</text>
  <text x="115" y="222" fill="#cbd5e1" font-size="10">sandbox: subprocess</text>
  <!-- Arrow -->
  <line x1="240" y1="242" x2="240" y2="268" stroke="#f59e0b" stroke-width="1.5" marker-end="url(#ah5)"/>
  <!-- Step 3 -->
  <circle cx="50" cy="290" r="14" fill="#422006" stroke="#f59e0b" stroke-width="1.5"/><text x="50" y="295" text-anchor="middle" fill="#fbbf24" font-size="12" font-weight="700">3</text>
  <text x="75" y="288" fill="#fbbf24" font-size="12" font-weight="600">WORKER WRITES + REGISTERS TOOL</text>
  <rect x="90" y="302" width="300" height="60" rx="6" fill="#022c22" stroke="#10b981" stroke-width="1"/>
  <text x="105" y="320" fill="#34d399" font-size="10" font-family="monospace">@tool("dynamic.normalize_ts")</text>
  <text x="105" y="336" fill="#34d399" font-size="10" font-family="monospace">def normalize_ts(data, method):</text>
  <text x="105" y="352" fill="#64748b" font-size="10" font-family="monospace">    # 50 lines of Python ...</text>
  <!-- Validation pipeline -->
  <line x1="400" y1="315" x2="430" y2="315" stroke="#34d399" stroke-width="1.5" marker-end="url(#ah5g)"/>
  <rect x="435" y="298" width="200" height="78" rx="6" fill="#1e293b" stroke="#475569" stroke-width="1"/>
  <text x="535" y="316" text-anchor="middle" fill="#34d399" font-size="10">AST validation</text>
  <text x="535" y="332" text-anchor="middle" fill="#34d399" font-size="10">Import policy check (NC1-NC3)</text>
  <text x="535" y="348" text-anchor="middle" fill="#34d399" font-size="10">Sandbox wrapping</text>
  <text x="535" y="364" text-anchor="middle" fill="#34d399" font-size="10">Registration in ToolRegistry</text>
  <!-- Arrow -->
  <line x1="240" y1="366" x2="240" y2="398" stroke="#f59e0b" stroke-width="1.5" marker-end="url(#ah5)"/>
  <!-- Step 4 -->
  <circle cx="50" cy="420" r="14" fill="#422006" stroke="#f59e0b" stroke-width="1.5"/><text x="50" y="425" text-anchor="middle" fill="#fbbf24" font-size="12" font-weight="700">4</text>
  <text x="75" y="418" fill="#fbbf24" font-size="12" font-weight="600">ALL SUBSEQUENT WORKERS CAN USE THE TOOL</text>
  <text x="90" y="440" fill="#cbd5e1" font-size="10">Worker-3: calls dynamic.normalize_ts(data, "z-score")</text>
  <text x="90" y="456" fill="#cbd5e1" font-size="10">Worker-5: calls dynamic.normalize_ts(data, "min-max")</text>
  <!-- Step 5 -->
  <circle cx="50" cy="500" r="14" fill="#1e293b" stroke="#475569" stroke-width="1.5"/><text x="50" y="505" text-anchor="middle" fill="#94a3b8" font-size="12" font-weight="700">5</text>
  <text x="75" y="498" fill="#94a3b8" font-size="12">OPTIONAL: PERSIST FOR FUTURE RUNS</text>
  <text x="90" y="518" fill="#64748b" font-size="10" font-family="monospace">workspace/runs/&lt;id&gt;/artifacts/tools/normalize_ts.py</text>
</svg>
</p>

**Code Mode** is the paradigm shift. Instead of agents making dozens of individual tool calls (search, extract, transform, analyze — one LLM round-trip each), an agent writes a **complete Python program** and executes it in a single round-trip. For data-heavy tasks, this reduces LLM calls from 50+ to 3-5.

**Dynamic Tool Factory** validates and sandboxes agent-created tools:
- **AST analysis** ensures no forbidden imports (`os`, `subprocess`, `sys`, `ctypes`)
- **Capability gating** (NC1-NC3) controls what each namespace can access
- **Sandbox wrapping** ensures tools run within resource limits
- **Registry integration** makes tools available to all agents in the workflow

### 5.3 Skill Generation

Tools handle computation. Skills handle *knowledge*. An agent can generate a Markdown skill at runtime that captures domain expertise:

<p align="center">
<svg viewBox="0 0 620 400" xmlns="http://www.w3.org/2000/svg" font-family="system-ui, -apple-system, sans-serif" width="620" height="400">
  <defs>
    <marker id="ah6" markerWidth="8" markerHeight="6" refX="8" refY="3" orient="auto"><path d="M0,0 L8,3 L0,6" fill="#a78bfa"/></marker>
  </defs>
  <rect width="620" height="400" rx="12" fill="#0f172a"/>
  <text x="310" y="28" text-anchor="middle" fill="#94a3b8" font-size="15" font-weight="600">SKILL GENERATION FLOW</text>
  <!-- Worker 1 -->
  <rect x="40" y="45" width="540" height="75" rx="8" fill="#1e293b" stroke="#a78bfa" stroke-width="1.5"/>
  <text x="60" y="66" fill="#a78bfa" font-size="12" font-weight="600">Worker-1 (Domain Research)</text>
  <text x="60" y="86" fill="#cbd5e1" font-size="10">Discovers: "ARIMA requires stationary data. ADF test p-value &lt; 0.05 means stationary.</text>
  <text x="60" y="102" fill="#cbd5e1" font-size="10">If non-stationary, difference d times."</text>
  <!-- Arrow -->
  <line x1="310" y1="120" x2="310" y2="148" stroke="#a78bfa" stroke-width="1.5" marker-end="url(#ah6)"/>
  <!-- Skill doc -->
  <rect x="100" y="152" width="420" height="100" rx="8" fill="#1a1035" stroke="#7c3aed" stroke-width="1.5"/>
  <text x="120" y="174" fill="#a78bfa" font-size="12" font-weight="600">Generates: skills/timeseries_stationarity.md</text>
  <line x1="120" y1="182" x2="500" y2="182" stroke="#334155" stroke-width="0.5"/>
  <text x="130" y="200" fill="#cbd5e1" font-size="10" font-family="monospace"># Stationarity Testing for Time Series</text>
  <text x="130" y="216" fill="#cbd5e1" font-size="10" font-family="monospace">1. Run ADF test on raw series</text>
  <text x="130" y="232" fill="#cbd5e1" font-size="10" font-family="monospace">2. If p &gt; 0.05: apply differencing (d=1)</text>
  <text x="130" y="248" fill="#cbd5e1" font-size="10" font-family="monospace">3. Re-test until stationary</text>
  <!-- Arrow -->
  <line x1="310" y1="255" x2="310" y2="278" stroke="#a78bfa" stroke-width="1.5" marker-end="url(#ah6)"/>
  <!-- Injection -->
  <rect x="100" y="282" width="420" height="36" rx="6" fill="#1e293b" stroke="#f59e0b" stroke-width="1"/>
  <text x="310" y="305" text-anchor="middle" fill="#fbbf24" font-size="11">Manager injects skill into Worker-3's system prompt</text>
  <!-- Arrow -->
  <line x1="310" y1="320" x2="310" y2="343" stroke="#a78bfa" stroke-width="1.5" marker-end="url(#ah6)"/>
  <!-- Worker 3 -->
  <rect x="100" y="347" width="420" height="42" rx="8" fill="#1e293b" stroke="#10b981" stroke-width="1.5"/>
  <text x="120" y="366" fill="#34d399" font-size="12" font-weight="600">Worker-3 (Time Series Analysis)</text>
  <text x="120" y="382" fill="#cbd5e1" font-size="10">Now has domain knowledge WITHOUT fine-tuning</text>
</svg>
</p>

**No other framework supports runtime skill/knowledge generation.** CrewAI has "memory" but it's conversation history, not structured domain knowledge. LangGraph has no equivalent concept.

### 5.4 Why This Changes Everything

The combination of runtime tool creation and skill generation means AWP workflows are **self-improving within a single run**:

1. **Iteration 1:** Manager discovers the problem space
2. **Iteration 2:** Workers create specialized tools for the domain
3. **Iteration 3:** Workers create skills capturing discovered knowledge
4. **Iteration 4+:** Workers use both tools and skills to solve the actual problem — with capabilities that didn't exist 30 seconds ago

This is emergent specialization. The workflow adapts its own toolkit to the problem, rather than hoping the pre-defined tools are sufficient.

---

## 6. The Problem-Solving Paradigm

Most agent frameworks answer the question: *"How do I solve this problem?"* AWP asks a deeper question: *"What capability am I missing — and how do I build it?"*

This distinction defines three fundamentally different paradigms for AI problem-solving.

### 6.1 Three Paradigms of Agent Problem-Solving

<p align="center">
<svg viewBox="0 0 760 480" xmlns="http://www.w3.org/2000/svg" font-family="system-ui, -apple-system, sans-serif" width="760" height="480">
  <defs>
    <marker id="pah1" markerWidth="7" markerHeight="5" refX="7" refY="2.5" orient="auto"><path d="M0,0 L7,2.5 L0,5" fill="#64748b"/></marker>
    <marker id="pah2" markerWidth="7" markerHeight="5" refX="7" refY="2.5" orient="auto"><path d="M0,0 L7,2.5 L0,5" fill="#f59e0b"/></marker>
    <marker id="pah3" markerWidth="7" markerHeight="5" refX="7" refY="2.5" orient="auto"><path d="M0,0 L7,2.5 L0,5" fill="#34d399"/></marker>
  </defs>
  <rect width="760" height="480" rx="12" fill="#0f172a"/>
  <text x="380" y="28" text-anchor="middle" fill="#94a3b8" font-size="15" font-weight="600">THREE PARADIGMS OF AGENT PROBLEM-SOLVING</text>
  <!-- Paradigm 1: Agent-first -->
  <rect x="20" y="46" width="230" height="420" rx="8" fill="#1e293b" stroke="#ef4444" stroke-width="1.5"/>
  <text x="135" y="70" text-anchor="middle" fill="#f87171" font-size="13" font-weight="700">AGENT-FIRST</text>
  <text x="135" y="88" text-anchor="middle" fill="#64748b" font-size="10">"The LLM thinks"</text>
  <text x="135" y="104" text-anchor="middle" fill="#475569" font-size="9">CrewAI, AutoGen, Swarm</text>
  <!-- Flow -->
  <rect x="55" y="120" width="160" height="26" rx="4" fill="#450a0a" stroke="#7f1d1d" stroke-width="1"/><text x="135" y="138" text-anchor="middle" fill="#fca5a5" font-size="10">Problem</text>
  <line x1="135" y1="146" x2="135" y2="162" stroke="#64748b" stroke-width="1" marker-end="url(#pah1)"/>
  <rect x="55" y="166" width="160" height="26" rx="4" fill="#450a0a" stroke="#7f1d1d" stroke-width="1"/><text x="135" y="184" text-anchor="middle" fill="#fca5a5" font-size="10">LLM reasons</text>
  <line x1="135" y1="192" x2="135" y2="208" stroke="#64748b" stroke-width="1" marker-end="url(#pah1)"/>
  <rect x="55" y="212" width="160" height="26" rx="4" fill="#450a0a" stroke="#7f1d1d" stroke-width="1"/><text x="135" y="230" text-anchor="middle" fill="#fca5a5" font-size="10">Try solution</text>
  <line x1="135" y1="238" x2="135" y2="254" stroke="#64748b" stroke-width="1" marker-end="url(#pah1)"/>
  <rect x="55" y="258" width="160" height="26" rx="4" fill="#450a0a" stroke="#7f1d1d" stroke-width="1"/><text x="135" y="276" text-anchor="middle" fill="#fca5a5" font-size="10">Adjust &amp; retry</text>
  <!-- Verdict -->
  <line x1="40" y1="310" x2="230" y2="310" stroke="#334155" stroke-width="0.5"/>
  <text x="40" y="330" fill="#f87171" font-size="9">Tools: fixed at instantiation</text>
  <text x="40" y="346" fill="#f87171" font-size="9">Skills: none or static</text>
  <text x="40" y="362" fill="#f87171" font-size="9">Control: minimal</text>
  <text x="40" y="378" fill="#f87171" font-size="9">Reproducibility: low</text>
  <text x="40" y="400" fill="#64748b" font-size="9">System stays the same.</text>
  <text x="40" y="416" fill="#64748b" font-size="9">Only outputs change.</text>
  <text x="135" y="450" text-anchor="middle" fill="#f87171" font-size="10" font-weight="600">Improvisation</text>
  <!-- Paradigm 2: Orchestration-first -->
  <rect x="265" y="46" width="230" height="420" rx="8" fill="#1e293b" stroke="#f59e0b" stroke-width="1.5"/>
  <text x="380" y="70" text-anchor="middle" fill="#fbbf24" font-size="13" font-weight="700">ORCHESTRATION-FIRST</text>
  <text x="380" y="88" text-anchor="middle" fill="#64748b" font-size="10">"The framework steers"</text>
  <text x="380" y="104" text-anchor="middle" fill="#475569" font-size="9">LangGraph, Haystack, Google ADK, Semantic Kernel</text>
  <!-- Flow -->
  <rect x="300" y="120" width="160" height="26" rx="4" fill="#422006" stroke="#92400e" stroke-width="1"/><text x="380" y="138" text-anchor="middle" fill="#fcd34d" font-size="10">Problem</text>
  <line x1="380" y1="146" x2="380" y2="162" stroke="#f59e0b" stroke-width="1" marker-end="url(#pah2)"/>
  <rect x="300" y="166" width="160" height="26" rx="4" fill="#422006" stroke="#92400e" stroke-width="1"/><text x="380" y="184" text-anchor="middle" fill="#fcd34d" font-size="10">Workflow routes</text>
  <line x1="380" y1="192" x2="380" y2="208" stroke="#f59e0b" stroke-width="1" marker-end="url(#pah2)"/>
  <rect x="300" y="212" width="160" height="26" rx="4" fill="#422006" stroke="#92400e" stroke-width="1"/><text x="380" y="230" text-anchor="middle" fill="#fcd34d" font-size="10">Use existing tools</text>
  <line x1="380" y1="238" x2="380" y2="254" stroke="#f59e0b" stroke-width="1" marker-end="url(#pah2)"/>
  <rect x="300" y="258" width="160" height="26" rx="4" fill="#422006" stroke="#92400e" stroke-width="1"/><text x="380" y="276" text-anchor="middle" fill="#fcd34d" font-size="10">Branch / loop</text>
  <!-- Verdict -->
  <line x1="285" y1="310" x2="475" y2="310" stroke="#334155" stroke-width="0.5"/>
  <text x="285" y="330" fill="#fbbf24" font-size="9">Tools: configurable, mostly static</text>
  <text x="285" y="346" fill="#fbbf24" font-size="9">Skills: optional, not generated</text>
  <text x="285" y="362" fill="#fbbf24" font-size="9">Control: good</text>
  <text x="285" y="378" fill="#fbbf24" font-size="9">Reproducibility: medium</text>
  <text x="285" y="400" fill="#64748b" font-size="9">Better execution.</text>
  <text x="285" y="416" fill="#64748b" font-size="9">But same capabilities.</text>
  <text x="380" y="450" text-anchor="middle" fill="#fbbf24" font-size="10" font-weight="600">Execution</text>
  <!-- Paradigm 3: Spec-first (AWP) -->
  <rect x="510" y="46" width="230" height="420" rx="8" fill="#1e293b" stroke="#10b981" stroke-width="2"/>
  <text x="625" y="70" text-anchor="middle" fill="#34d399" font-size="13" font-weight="700">SPEC-FIRST (AWP)</text>
  <text x="625" y="88" text-anchor="middle" fill="#64748b" font-size="10">"The system evolves"</text>
  <text x="625" y="104" text-anchor="middle" fill="#475569" font-size="9">Agent Workflow Protocol</text>
  <!-- Flow -->
  <rect x="545" y="120" width="160" height="26" rx="4" fill="#022c22" stroke="#065f46" stroke-width="1"/><text x="625" y="138" text-anchor="middle" fill="#6ee7b7" font-size="10">Problem</text>
  <line x1="625" y1="146" x2="625" y2="162" stroke="#34d399" stroke-width="1" marker-end="url(#pah3)"/>
  <rect x="545" y="166" width="160" height="26" rx="4" fill="#022c22" stroke="#065f46" stroke-width="1"/><text x="625" y="184" text-anchor="middle" fill="#6ee7b7" font-size="10">Diagnose gap</text>
  <line x1="625" y1="192" x2="625" y2="208" stroke="#34d399" stroke-width="1" marker-end="url(#pah3)"/>
  <rect x="545" y="212" width="160" height="26" rx="4" fill="#022c22" stroke="#065f46" stroke-width="1"/><text x="625" y="230" text-anchor="middle" fill="#6ee7b7" font-size="10">Build capability</text>
  <line x1="625" y1="238" x2="625" y2="254" stroke="#34d399" stroke-width="1" marker-end="url(#pah3)"/>
  <rect x="545" y="258" width="160" height="26" rx="4" fill="#022c22" stroke="#065f46" stroke-width="1"/><text x="625" y="276" text-anchor="middle" fill="#6ee7b7" font-size="10">Validate &amp; integrate</text>
  <!-- Verdict -->
  <line x1="530" y1="310" x2="720" y2="310" stroke="#334155" stroke-width="0.5"/>
  <text x="530" y="330" fill="#34d399" font-size="9">Tools: created at runtime</text>
  <text x="530" y="346" fill="#34d399" font-size="9">Skills: generated &amp; validated</text>
  <text x="530" y="362" fill="#34d399" font-size="9">Control: formal governance</text>
  <text x="530" y="378" fill="#34d399" font-size="9">Reproducibility: high</text>
  <text x="530" y="400" fill="#34d399" font-size="9">System improves itself.</text>
  <text x="530" y="416" fill="#34d399" font-size="9">Capabilities grow.</text>
  <text x="625" y="450" text-anchor="middle" fill="#34d399" font-size="10" font-weight="600">Evolution</text>
</svg>
</p>

The difference is fundamental:
- **Agent-first** systems optimize *outputs*. The system stays the same; only the answers change.
- **Orchestration-first** systems optimize *execution*. The workflow is better, but the capabilities are static.
- **AWP** optimizes *the system itself*. Capabilities grow. Each run leaves the system more capable than before.

### 6.2 The Capability Evolution Loop

When AWP encounters a problem it cannot solve with existing tools, it doesn't just retry harder. It identifies what's missing, builds it, validates it, and integrates it — under strict governance.

<p align="center">
<svg viewBox="0 0 740 580" xmlns="http://www.w3.org/2000/svg" font-family="system-ui, -apple-system, sans-serif" width="740" height="580">
  <defs>
    <marker id="cel1" markerWidth="7" markerHeight="5" refX="7" refY="2.5" orient="auto"><path d="M0,0 L7,2.5 L0,5" fill="#34d399"/></marker>
    <marker id="cel2" markerWidth="7" markerHeight="5" refX="7" refY="2.5" orient="auto"><path d="M0,0 L7,2.5 L0,5" fill="#f87171"/></marker>
    <marker id="cel3" markerWidth="7" markerHeight="5" refX="7" refY="2.5" orient="auto"><path d="M0,0 L7,2.5 L0,5" fill="#fbbf24"/></marker>
  </defs>
  <rect width="740" height="580" rx="12" fill="#0f172a"/>
  <text x="370" y="28" text-anchor="middle" fill="#94a3b8" font-size="15" font-weight="600">THE CAPABILITY EVOLUTION LOOP</text>
  <!-- Phase 1: Execute -->
  <rect x="250" y="44" width="240" height="48" rx="8" fill="#1e293b" stroke="#3b82f6" stroke-width="2"/>
  <circle cx="280" cy="68" r="12" fill="#1e3a5f" stroke="#3b82f6" stroke-width="1"/><text x="280" y="72" text-anchor="middle" fill="#60a5fa" font-size="10" font-weight="700">1</text>
  <text x="300" y="64" fill="#60a5fa" font-size="11" font-weight="600">EXECUTE PIPELINE</text>
  <text x="300" y="80" fill="#94a3b8" font-size="9">Run current workflow with existing capabilities</text>
  <line x1="370" y1="92" x2="370" y2="112" stroke="#34d399" stroke-width="1.5" marker-end="url(#cel1)"/>
  <!-- Phase 2: Evaluate -->
  <rect x="250" y="116" width="240" height="48" rx="8" fill="#1e293b" stroke="#f59e0b" stroke-width="2"/>
  <circle cx="280" cy="140" r="12" fill="#422006" stroke="#f59e0b" stroke-width="1"/><text x="280" y="144" text-anchor="middle" fill="#fbbf24" font-size="10" font-weight="700">2</text>
  <text x="300" y="136" fill="#fbbf24" font-size="11" font-weight="600">EVALUATE RESULTS</text>
  <text x="300" y="152" fill="#94a3b8" font-size="9">Check confidence, metrics, error signals</text>
  <!-- Branch -->
  <line x1="370" y1="164" x2="370" y2="186" stroke="#34d399" stroke-width="1.5" marker-end="url(#cel1)"/>
  <!-- Decision diamond (simplified as rect) -->
  <rect x="250" y="190" width="240" height="52" rx="8" fill="#422006" stroke="#f59e0b" stroke-width="2"/>
  <text x="370" y="212" text-anchor="middle" fill="#fbbf24" font-size="11" font-weight="600">CAPABILITY GAP DETECTED?</text>
  <text x="370" y="230" text-anchor="middle" fill="#94a3b8" font-size="9">performance &lt; threshold AND no improvement in N iters</text>
  <!-- No branch (right) -->
  <line x1="490" y1="216" x2="560" y2="216" stroke="#34d399" stroke-width="1.5" marker-end="url(#cel1)"/>
  <rect x="565" y="200" width="130" height="32" rx="6" fill="#022c22" stroke="#10b981" stroke-width="1.5"/>
  <text x="630" y="220" text-anchor="middle" fill="#34d399" font-size="10" font-weight="600">DONE (success)</text>
  <!-- Yes branch (down) -->
  <line x1="370" y1="242" x2="370" y2="264" stroke="#fbbf24" stroke-width="1.5" marker-end="url(#cel3)"/>
  <text x="390" y="258" fill="#fbbf24" font-size="9">YES</text>
  <text x="510" y="216" fill="#34d399" font-size="9">NO</text>
  <!-- Phase 3: Classify -->
  <rect x="250" y="268" width="240" height="62" rx="8" fill="#1e293b" stroke="#a78bfa" stroke-width="2"/>
  <circle cx="280" cy="292" r="12" fill="#1a1035" stroke="#a78bfa" stroke-width="1"/><text x="280" y="296" text-anchor="middle" fill="#a78bfa" font-size="10" font-weight="700">3</text>
  <text x="300" y="288" fill="#a78bfa" font-size="11" font-weight="600">CLASSIFY GAP</text>
  <text x="300" y="304" fill="#94a3b8" font-size="9">What capability is missing?</text>
  <text x="300" y="318" fill="#64748b" font-size="8">feature_engineering | model_complexity | data_processing | evaluation</text>
  <line x1="370" y1="330" x2="370" y2="350" stroke="#34d399" stroke-width="1.5" marker-end="url(#cel1)"/>
  <!-- Phase 4: Generate -->
  <rect x="250" y="354" width="240" height="48" rx="8" fill="#1e293b" stroke="#10b981" stroke-width="2"/>
  <circle cx="280" cy="378" r="12" fill="#022c22" stroke="#10b981" stroke-width="1"/><text x="280" y="382" text-anchor="middle" fill="#34d399" font-size="10" font-weight="700">4</text>
  <text x="300" y="374" fill="#34d399" font-size="11" font-weight="600">GENERATE SKILL / TOOL</text>
  <text x="300" y="390" fill="#94a3b8" font-size="9">One capability per iteration. Versioned. Sandboxed.</text>
  <line x1="370" y1="402" x2="370" y2="422" stroke="#34d399" stroke-width="1.5" marker-end="url(#cel1)"/>
  <!-- Phase 5: Validate -->
  <rect x="250" y="426" width="240" height="48" rx="8" fill="#1e293b" stroke="#ef4444" stroke-width="2"/>
  <circle cx="280" cy="450" r="12" fill="#450a0a" stroke="#ef4444" stroke-width="1"/><text x="280" y="454" text-anchor="middle" fill="#f87171" font-size="10" font-weight="700">5</text>
  <text x="300" y="446" fill="#f87171" font-size="11" font-weight="600">VALIDATE</text>
  <text x="300" y="462" fill="#94a3b8" font-size="9">Syntax + functional + performance check</text>
  <!-- Reject branch -->
  <line x1="490" y1="450" x2="560" y2="450" stroke="#f87171" stroke-width="1.5" marker-end="url(#cel2)"/>
  <rect x="565" y="434" width="130" height="32" rx="6" fill="#450a0a" stroke="#ef4444" stroke-width="1"/>
  <text x="630" y="454" text-anchor="middle" fill="#f87171" font-size="10">REJECT &amp; log</text>
  <text x="510" y="445" fill="#f87171" font-size="9">FAIL</text>
  <!-- Pass branch -->
  <line x1="370" y1="474" x2="370" y2="494" stroke="#34d399" stroke-width="1.5" marker-end="url(#cel1)"/>
  <text x="390" y="490" fill="#34d399" font-size="9">PASS</text>
  <!-- Phase 6: Integrate -->
  <rect x="250" y="498" width="240" height="48" rx="8" fill="#1e293b" stroke="#3b82f6" stroke-width="2"/>
  <circle cx="280" cy="522" r="12" fill="#1e3a5f" stroke="#3b82f6" stroke-width="1"/><text x="280" y="526" text-anchor="middle" fill="#60a5fa" font-size="10" font-weight="700">6</text>
  <text x="300" y="518" fill="#60a5fa" font-size="11" font-weight="600">INTEGRATE &amp; RERUN</text>
  <text x="300" y="534" fill="#94a3b8" font-size="9">New capability available to all agents. Loop to step 1.</text>
  <!-- Loop-back arrow -->
  <line x1="250" y1="522" x2="100" y2="522" stroke="#475569" stroke-width="1" stroke-dasharray="4,3"/>
  <line x1="100" y1="522" x2="100" y2="68" stroke="#475569" stroke-width="1" stroke-dasharray="4,3"/>
  <line x1="100" y1="68" x2="244" y2="68" stroke="#475569" stroke-width="1" stroke-dasharray="4,3" marker-end="url(#cel1)"/>
  <text x="80" y="300" fill="#475569" font-size="9" transform="rotate(-90,80,300)">iterate until success or limits</text>
  <!-- Limits box -->
  <rect x="40" y="440" width="180" height="80" rx="6" fill="#1e293b" stroke="#334155" stroke-width="1"/>
  <text x="130" y="458" text-anchor="middle" fill="#94a3b8" font-size="10" font-weight="500">HARD LIMITS</text>
  <text x="55" y="476" fill="#f87171" font-size="9">max_new_skills_per_run: 3</text>
  <text x="55" y="492" fill="#f87171" font-size="9">max_total_generated: 10</text>
  <text x="55" y="508" fill="#f87171" font-size="9">stop after 2 without gain</text>
</svg>
</p>

This is not a theoretical pattern. It's how AWP's delegation loop actually operates at A3+:

1. **Execute** — the manager runs workers against the current task
2. **Evaluate** — confidence scores and result quality are checked
3. **Detect gap** — if confidence stalls and no progress in N iterations, the system identifies a missing capability
4. **Classify** — is this a data processing gap? A feature engineering gap? A model complexity gap? An evaluation gap?
5. **Generate** — a worker creates exactly one new tool or skill, versioned and sandboxed
6. **Validate** — syntax check, functional test, performance comparison against baseline
7. **Integrate** — the new capability enters the ToolRegistry; all subsequent workers can use it
8. **Rerun** — the pipeline executes again, now with an expanded capability set

**Governance rules prevent runaway complexity:**
- Maximum 3 new skills per run (configurable)
- Stop generation after 2 consecutive skills with no metric improvement
- No overwriting existing skills — versioned only
- No duplicate functionality (similarity detection)
- All generated code must pass AST validation and sandbox wrapping

### 6.3 Why This Is a Paradigm Shift

The capability evolution loop creates a fundamentally different relationship between the system and the problem:

<p align="center">
<svg viewBox="0 0 720 300" xmlns="http://www.w3.org/2000/svg" font-family="system-ui, -apple-system, sans-serif" width="720" height="300">
  <rect width="720" height="300" rx="12" fill="#0f172a"/>
  <text x="360" y="28" text-anchor="middle" fill="#94a3b8" font-size="14" font-weight="600">WHAT IMPROVES ACROSS ITERATIONS?</text>
  <!-- Traditional -->
  <rect x="30" y="50" width="310" height="230" rx="8" fill="#1e293b" stroke="#ef4444" stroke-width="1.5"/>
  <text x="185" y="74" text-anchor="middle" fill="#f87171" font-size="12" font-weight="600">Traditional Agents</text>
  <text x="185" y="92" text-anchor="middle" fill="#64748b" font-size="10">(CrewAI, AutoGen, LangGraph)</text>
  <!-- Iteration bars -->
  <text x="50" y="124" fill="#94a3b8" font-size="9">Iter 1:</text><rect x="100" y="112" width="120" height="16" rx="3" fill="#ef4444" opacity="0.3"/><text x="230" y="124" fill="#64748b" font-size="9">tools: 5 | output: 0.62</text>
  <text x="50" y="150" fill="#94a3b8" font-size="9">Iter 2:</text><rect x="100" y="138" width="120" height="16" rx="3" fill="#ef4444" opacity="0.4"/><text x="230" y="150" fill="#64748b" font-size="9">tools: 5 | output: 0.68</text>
  <text x="50" y="176" fill="#94a3b8" font-size="9">Iter 3:</text><rect x="100" y="164" width="120" height="16" rx="3" fill="#ef4444" opacity="0.5"/><text x="230" y="176" fill="#64748b" font-size="9">tools: 5 | output: 0.71</text>
  <text x="50" y="202" fill="#94a3b8" font-size="9">Iter 4:</text><rect x="100" y="190" width="120" height="16" rx="3" fill="#ef4444" opacity="0.5"/><text x="230" y="202" fill="#64748b" font-size="9">tools: 5 | output: 0.72</text>
  <text x="50" y="228" fill="#94a3b8" font-size="9">Iter 5:</text><rect x="100" y="216" width="120" height="16" rx="3" fill="#ef4444" opacity="0.5"/><text x="230" y="228" fill="#64748b" font-size="9">tools: 5 | output: 0.72</text>
  <text x="185" y="260" text-anchor="middle" fill="#f87171" font-size="10">Same tools. Diminishing returns.</text>
  <!-- AWP -->
  <rect x="380" y="50" width="310" height="230" rx="8" fill="#1e293b" stroke="#10b981" stroke-width="2"/>
  <text x="535" y="74" text-anchor="middle" fill="#34d399" font-size="12" font-weight="600">AWP (Capability Evolution)</text>
  <text x="535" y="92" text-anchor="middle" fill="#64748b" font-size="10">A3+ with tool_creation: true</text>
  <!-- Iteration bars -->
  <text x="400" y="124" fill="#94a3b8" font-size="9">Iter 1:</text><rect x="450" y="112" width="120" height="16" rx="3" fill="#10b981" opacity="0.3"/><text x="580" y="124" fill="#64748b" font-size="9">tools: 5 | output: 0.62</text>
  <text x="400" y="150" fill="#94a3b8" font-size="9">Iter 2:</text><rect x="450" y="138" width="140" height="16" rx="3" fill="#10b981" opacity="0.4"/><text x="600" y="150" fill="#34d399" font-size="9">tools: 6 | output: 0.74</text>
  <text x="400" y="176" fill="#94a3b8" font-size="9">Iter 3:</text><rect x="450" y="164" width="160" height="16" rx="3" fill="#10b981" opacity="0.5"/><text x="620" y="176" fill="#34d399" font-size="9">tools: 7 | output: 0.83</text>
  <text x="400" y="202" fill="#94a3b8" font-size="9">Iter 4:</text><rect x="450" y="190" width="180" height="16" rx="3" fill="#10b981" opacity="0.6"/><text x="640" y="202" fill="#34d399" font-size="9">tools: 8 | output: 0.89</text>
  <text x="400" y="228" fill="#94a3b8" font-size="9">Iter 5:</text><rect x="450" y="216" width="190" height="16" rx="3" fill="#10b981" opacity="0.7"/><text x="650" y="228" fill="#34d399" font-size="9">tools: 8 | output: 0.91</text>
  <text x="535" y="260" text-anchor="middle" fill="#34d399" font-size="10">Growing toolkit. Compounding gains.</text>
</svg>
</p>

Traditional agents hit a ceiling because their capabilities are fixed. They can retry with different prompts, temperatures, or strategies — but the underlying toolkit doesn't change. When the problem requires a capability the agent doesn't have, it's stuck.

AWP breaks through that ceiling because each iteration can *expand what the system is capable of*. A generated tool persists. A generated skill compounds. The next iteration starts with a strictly larger capability set than the previous one.

**In one sentence:** Other frameworks optimize outputs. AWP optimizes the system that produces outputs.

### 6.4 Framework Comparison: Problem-Solving & Capability Evolution

| Capability | AWP | LangGraph | CrewAI | AutoGen | Google ADK | Google A2A | OpenAI Agents SDK | Bedrock Agents | Semantic Kernel | MetaGPT | Haystack |
|-----------|-----|-----------|--------|---------|------------|------------|-------------------|----------------|-----------------|---------|----------|
| **Structured problem decomposition** | Formal (delegation envelope) | Graph states | Role-based | Conversation | Code-first | N/A (protocol) | Handoff-based | Action groups | Planner-based | SOPs | Pipeline |
| **Deterministic decision flow** | Yes (rules + budget) | Partial (edges) | No | No | Partial | No | No | Partial | Partial | Partial | Yes |
| **Root cause analysis** | Gap classification (data/feature/model/eval) | No | No | No | No | No | No | No | No | No | No |
| **Runtime tool creation** | Yes (Dynamic Tool Factory + AST validation) | No | No (code only) | Emergent (code exec) | Possible | No | No | No | No | Artifacts | No |
| **Runtime skill generation** | Yes (Markdown skills + injection) | No | No | No | No | No | No | No | No | No | No |
| **Skill/tool validation** | 3-tier (syntax + functional + performance) | No | No | No | No | No | No | No | No | No | No |
| **Skill/tool governance** | Versioned, limits, duplicate detection | No | No | No | No | No | No | No | No | No | No |
| **Cumulative capability growth** | Yes (ToolRegistry persists across iterations) | No | No | No | No | No | No | No | No | No | No |
| **Controlled self-extension** | Budget + max_skills + stall detection | N/A | N/A | N/A | N/A | N/A | N/A | N/A | N/A | N/A | N/A |
| **Cross-vendor interop** | Protocol-level (YAML portable) | No | No | No | Gemini-centric | Yes (core purpose) | No | AWS-only | Microsoft-centric | No | No |
| **Reproducibility** | High (declarative + audit trail) | Medium | Low | Low | Medium | N/A | Low | Medium | Medium | Medium | High |

### 6.5 The External Skill Pattern

In AWP, the capability gap detection itself is implemented as a manager skill — not hardcoded into the orchestration engine. The manager receives a skill like `detect_capability_gap_and_propose_extension.md` that teaches it *when* and *how* to identify missing capabilities:

```yaml
# In the manager's delegation loop config:
worker_policy:
  manager_controlled:
    - instructions       # Manager decides what each worker does
    - skills             # Manager selectively forwards skills
    - tools_allowed      # Manager configures worker tools
    - codemode.enabled   # Manager enables code execution
    - codemode.tool_creation  # Manager enables tool creation
```

The manager doesn't contain hardcoded capability-detection logic. Instead:
1. The **skill** teaches the manager to recognize capability gaps
2. The **delegation loop** provides the iteration mechanism
3. The **budget system** enforces limits on self-extension
4. The **validation pipeline** ensures generated capabilities are safe

This keeps the manager slim, deterministic, and replaceable — while the complex gap-analysis logic lives in a modular, swappable skill file.

---

## 7. Solving Complex Problems: The Delegation Architecture

### 6.1 The Problem with Flat Orchestration

Most frameworks orchestrate agents in a flat structure:

<p align="center">
<svg viewBox="0 0 600 200" xmlns="http://www.w3.org/2000/svg" font-family="system-ui, -apple-system, sans-serif" width="600" height="200">
  <defs>
    <marker id="ah7" markerWidth="8" markerHeight="6" refX="8" refY="3" orient="auto"><path d="M0,0 L8,3 L0,6" fill="#64748b"/></marker>
  </defs>
  <rect width="600" height="200" rx="12" fill="#0f172a"/>
  <text x="300" y="26" text-anchor="middle" fill="#94a3b8" font-size="13">Traditional (CrewAI, AutoGen)</text>
  <!-- Planner -->
  <rect x="245" y="38" width="110" height="32" rx="6" fill="#1e293b" stroke="#64748b" stroke-width="1.5"/>
  <text x="300" y="59" text-anchor="middle" fill="#94a3b8" font-size="11">Planner</text>
  <line x1="300" y1="70" x2="300" y2="88" stroke="#64748b" stroke-width="1.2" marker-end="url(#ah7)"/>
  <!-- Chain -->
  <rect x="50" y="92" width="110" height="32" rx="6" fill="#1e293b" stroke="#64748b" stroke-width="1.5"/>
  <text x="105" y="113" text-anchor="middle" fill="#94a3b8" font-size="11">Researcher</text>
  <rect x="245" y="92" width="110" height="32" rx="6" fill="#1e293b" stroke="#64748b" stroke-width="1.5"/>
  <text x="300" y="113" text-anchor="middle" fill="#94a3b8" font-size="11">Writer</text>
  <rect x="440" y="92" width="110" height="32" rx="6" fill="#1e293b" stroke="#64748b" stroke-width="1.5"/>
  <text x="495" y="113" text-anchor="middle" fill="#94a3b8" font-size="11">Reviewer</text>
  <line x1="160" y1="108" x2="240" y2="108" stroke="#64748b" stroke-width="1.2" marker-end="url(#ah7)"/>
  <line x1="355" y1="108" x2="435" y2="108" stroke="#64748b" stroke-width="1.2" marker-end="url(#ah7)"/>
  <!-- Problems -->
  <text x="40" y="152" fill="#f87171" font-size="10">What if the research requires 12 sub-tasks?</text>
  <text x="40" y="168" fill="#f87171" font-size="10">What if the writer needs a tool that doesn't exist?</text>
  <text x="40" y="184" fill="#f87171" font-size="10">What if the whole approach is wrong after step 2?</text>
</svg>
</p>

Flat orchestration breaks down when:
- The problem decomposes into an unknown number of sub-tasks
- Agents need capabilities that weren't anticipated
- The approach itself needs to change mid-execution
- Resource consumption must be bounded

### 6.2 AWP's Delegation Loop: Adaptive Problem-Solving

The delegation loop is a **feedback-driven orchestration pattern** that mirrors how expert teams actually work:

<p align="center">
<svg viewBox="0 0 740 520" xmlns="http://www.w3.org/2000/svg" font-family="system-ui, -apple-system, sans-serif" width="740" height="520">
  <defs>
    <marker id="ah8" markerWidth="8" markerHeight="6" refX="8" refY="3" orient="auto"><path d="M0,0 L8,3 L0,6" fill="#f59e0b"/></marker>
    <marker id="ah8b" markerWidth="8" markerHeight="6" refX="8" refY="3" orient="auto"><path d="M0,0 L8,3 L0,6" fill="#64748b"/></marker>
  </defs>
  <rect width="740" height="520" rx="12" fill="#0f172a"/>
  <text x="370" y="28" text-anchor="middle" fill="#94a3b8" font-size="15" font-weight="600">THE DELEGATION LOOP</text>
  <!-- Manager -->
  <rect x="120" y="42" width="500" height="60" rx="8" fill="#422006" stroke="#f59e0b" stroke-width="2"/>
  <text x="370" y="64" text-anchor="middle" fill="#fbbf24" font-size="14" font-weight="600">MANAGER</text>
  <text x="370" y="82" text-anchor="middle" fill="#fcd34d" font-size="10">Sees: task + history + budget + previous results. Decides: what workers to spawn.</text>
  <!-- Fan-out arrows -->
  <line x1="250" y1="102" x2="150" y2="135" stroke="#f59e0b" stroke-width="1.5" marker-end="url(#ah8)"/>
  <line x1="370" y1="102" x2="370" y2="135" stroke="#f59e0b" stroke-width="1.5" marker-end="url(#ah8)"/>
  <line x1="490" y1="102" x2="590" y2="135" stroke="#f59e0b" stroke-width="1.5" marker-end="url(#ah8)"/>
  <!-- Workers -->
  <rect x="60" y="140" width="180" height="105" rx="6" fill="#1e293b" stroke="#475569" stroke-width="1.5"/>
  <text x="150" y="160" text-anchor="middle" fill="#cbd5e1" font-size="12" font-weight="500">Worker 1</text>
  <text x="80" y="178" fill="#64748b" font-size="9">instructions</text>
  <text x="80" y="192" fill="#64748b" font-size="9">skills</text>
  <text x="80" y="206" fill="#64748b" font-size="9">tools</text>
  <text x="80" y="220" fill="#64748b" font-size="9">sandbox</text>
  <text x="80" y="234" fill="#64748b" font-size="9">temperature</text>
  <rect x="280" y="140" width="180" height="105" rx="6" fill="#1e293b" stroke="#475569" stroke-width="1.5"/>
  <text x="370" y="160" text-anchor="middle" fill="#cbd5e1" font-size="12" font-weight="500">Worker 2</text>
  <text x="300" y="178" fill="#64748b" font-size="9">instructions</text>
  <text x="300" y="192" fill="#64748b" font-size="9">skills</text>
  <text x="300" y="206" fill="#64748b" font-size="9">tools</text>
  <text x="300" y="220" fill="#64748b" font-size="9">sandbox</text>
  <text x="300" y="234" fill="#64748b" font-size="9">output_schema</text>
  <rect x="500" y="140" width="180" height="105" rx="6" fill="#1e293b" stroke="#475569" stroke-width="1.5"/>
  <text x="590" y="160" text-anchor="middle" fill="#cbd5e1" font-size="12" font-weight="500">Worker 3</text>
  <text x="520" y="178" fill="#34d399" font-size="9">code_mode</text>
  <text x="520" y="192" fill="#34d399" font-size="9">tool_creation</text>
  <text x="520" y="206" fill="#64748b" font-size="9">tools</text>
  <text x="520" y="220" fill="#64748b" font-size="9">sandbox</text>
  <text x="520" y="234" fill="#64748b" font-size="9">output_schema</text>
  <text x="700" y="190" fill="#475569" font-size="9" font-style="italic">Each</text>
  <text x="700" y="204" fill="#475569" font-size="9" font-style="italic">configured</text>
  <text x="700" y="218" fill="#475569" font-size="9" font-style="italic">differently</text>
  <!-- Converge arrows -->
  <line x1="150" y1="245" x2="310" y2="278" stroke="#64748b" stroke-width="1" marker-end="url(#ah8b)"/>
  <line x1="370" y1="245" x2="370" y2="278" stroke="#64748b" stroke-width="1" marker-end="url(#ah8b)"/>
  <line x1="590" y1="245" x2="430" y2="278" stroke="#64748b" stroke-width="1" marker-end="url(#ah8b)"/>
  <!-- Validation -->
  <rect x="170" y="282" width="400" height="52" rx="6" fill="#1e293b" stroke="#3b82f6" stroke-width="1.5"/>
  <text x="370" y="302" text-anchor="middle" fill="#60a5fa" font-size="12" font-weight="600">VALIDATION (Two-Tier)</text>
  <text x="370" y="320" text-anchor="middle" fill="#93c5fd" font-size="10">Tier 1: Schema + fields + confidence (fast) | Tier 2: LLM semantic check (optional)</text>
  <!-- Arrow to decision -->
  <line x1="370" y1="334" x2="370" y2="360" stroke="#64748b" stroke-width="1.5" marker-end="url(#ah8b)"/>
  <!-- Decision -->
  <rect x="170" y="364" width="400" height="90" rx="6" fill="#1e293b" stroke="#f59e0b" stroke-width="1.5"/>
  <text x="370" y="386" text-anchor="middle" fill="#fbbf24" font-size="12" font-weight="600">DECISION POINT</text>
  <text x="200" y="408" fill="#f87171" font-size="10">Budget exhausted?</text><text x="410" y="408" fill="#f87171" font-size="10">STOP</text>
  <text x="200" y="424" fill="#fb923c" font-size="10">Stall detected?</text><text x="410" y="424" fill="#fb923c" font-size="10">WARN then STOP</text>
  <text x="200" y="440" fill="#34d399" font-size="10">Confidence high?</text><text x="410" y="440" fill="#34d399" font-size="10">STOP (success)</text>
  <!-- Budget bar -->
  <rect x="60" y="478" width="620" height="28" rx="6" fill="#1e293b" stroke="#334155" stroke-width="1"/>
  <text x="370" y="497" text-anchor="middle" fill="#94a3b8" font-size="11">Budget tracker: loops 3/20 | workers 7/30 | tokens 45K/1M</text>
</svg>
</p>

**Key differences from other frameworks:**

1. **Workers are ephemeral.** They don't persist between iterations. The manager creates fresh workers with new configurations each loop. This prevents accumulated context pollution.

2. **The manager generates configurations, not code.** The `DelegationEnvelope` is a structured specification — instructions, skills, tools, temperature, output schema — not a function call. This is why the declarative separation matters at execution time too.

3. **Two-tier validation catches both structural and semantic errors.** Deterministic checks (fast, free) catch malformed output. LLM validation (slow, costs tokens) catches *wrong* output. The system adaptively skips LLM validation when confidence is high or budget is low.

4. **Stall detection prevents infinite loops.** If the last N iterations show no confidence improvement above a threshold, the system warns and stops. No other framework has automatic stall detection.

5. **Budget is a first-class architectural concept.** Not an afterthought. Not a configuration option you might set. A *required* structural element at A2+.

### 6.3 Recursive Delegation (A4): Hierarchical Problem Decomposition

At A4, the architecture goes fractal. Workers can themselves become managers:

<p align="center">
<svg viewBox="0 0 660 340" xmlns="http://www.w3.org/2000/svg" font-family="system-ui, -apple-system, sans-serif" width="660" height="340">
  <defs>
    <marker id="ah9" markerWidth="8" markerHeight="6" refX="8" refY="3" orient="auto"><path d="M0,0 L8,3 L0,6" fill="#f59e0b"/></marker>
    <marker id="ah9r" markerWidth="8" markerHeight="6" refX="8" refY="3" orient="auto"><path d="M0,0 L8,3 L0,6" fill="#f87171"/></marker>
  </defs>
  <rect width="660" height="340" rx="12" fill="#0f172a"/>
  <text x="330" y="28" text-anchor="middle" fill="#94a3b8" font-size="15" font-weight="600">RECURSIVE DELEGATION (A4)</text>
  <!-- Depth labels -->
  <text x="30" y="72" fill="#475569" font-size="10">depth=0</text>
  <text x="30" y="162" fill="#475569" font-size="10">depth=1</text>
  <text x="30" y="252" fill="#475569" font-size="10">depth=2</text>
  <!-- Budget labels -->
  <text x="590" y="72" fill="#fbbf24" font-size="10">budget: 100%</text>
  <text x="590" y="162" fill="#fb923c" font-size="10">budget: ~30%</text>
  <text x="590" y="252" fill="#f87171" font-size="10">budget: ~10%</text>
  <!-- CEO -->
  <rect x="255" y="48" width="150" height="36" rx="6" fill="#422006" stroke="#f59e0b" stroke-width="2"/>
  <text x="330" y="72" text-anchor="middle" fill="#fbbf24" font-size="12" font-weight="600">CEO Manager</text>
  <!-- Lines to depth 1 -->
  <line x1="290" y1="84" x2="170" y2="130" stroke="#f59e0b" stroke-width="1.5" marker-end="url(#ah9)"/>
  <line x1="330" y1="84" x2="330" y2="130" stroke="#f59e0b" stroke-width="1.5" marker-end="url(#ah9)"/>
  <line x1="370" y1="84" x2="490" y2="130" stroke="#f59e0b" stroke-width="1.5" marker-end="url(#ah9)"/>
  <!-- Depth 1 managers -->
  <rect x="100" y="135" width="140" height="36" rx="6" fill="#422006" stroke="#fb923c" stroke-width="1.5"/>
  <text x="170" y="158" text-anchor="middle" fill="#fb923c" font-size="11" font-weight="500">R&amp;D Manager</text>
  <rect x="260" y="135" width="140" height="36" rx="6" fill="#422006" stroke="#fb923c" stroke-width="1.5"/>
  <text x="330" y="158" text-anchor="middle" fill="#fb923c" font-size="11" font-weight="500">Ops Manager</text>
  <rect x="420" y="135" width="140" height="36" rx="6" fill="#422006" stroke="#fb923c" stroke-width="1.5"/>
  <text x="490" y="158" text-anchor="middle" fill="#fb923c" font-size="11" font-weight="500">Sales Manager</text>
  <text x="580" y="158" fill="#64748b" font-size="9" font-style="italic">Also managers</text>
  <!-- Lines to depth 2 -->
  <line x1="150" y1="171" x2="115" y2="218" stroke="#f87171" stroke-width="1.2" marker-end="url(#ah9r)"/>
  <line x1="190" y1="171" x2="225" y2="218" stroke="#f87171" stroke-width="1.2" marker-end="url(#ah9r)"/>
  <line x1="310" y1="171" x2="310" y2="218" stroke="#f87171" stroke-width="1.2" marker-end="url(#ah9r)"/>
  <line x1="350" y1="171" x2="385" y2="218" stroke="#f87171" stroke-width="1.2" marker-end="url(#ah9r)"/>
  <line x1="470" y1="171" x2="470" y2="218" stroke="#f87171" stroke-width="1.2" marker-end="url(#ah9r)"/>
  <line x1="510" y1="171" x2="555" y2="218" stroke="#f87171" stroke-width="1.2" marker-end="url(#ah9r)"/>
  <!-- Depth 2 workers -->
  <rect x="85" y="222" width="60" height="28" rx="5" fill="#1e293b" stroke="#64748b" stroke-width="1"/><text x="115" y="241" text-anchor="middle" fill="#94a3b8" font-size="10">W1</text>
  <rect x="195" y="222" width="60" height="28" rx="5" fill="#1e293b" stroke="#64748b" stroke-width="1"/><text x="225" y="241" text-anchor="middle" fill="#94a3b8" font-size="10">W2</text>
  <rect x="280" y="222" width="60" height="28" rx="5" fill="#1e293b" stroke="#64748b" stroke-width="1"/><text x="310" y="241" text-anchor="middle" fill="#94a3b8" font-size="10">W3</text>
  <rect x="355" y="222" width="60" height="28" rx="5" fill="#1e293b" stroke="#64748b" stroke-width="1"/><text x="385" y="241" text-anchor="middle" fill="#94a3b8" font-size="10">W4</text>
  <rect x="440" y="222" width="60" height="28" rx="5" fill="#1e293b" stroke="#64748b" stroke-width="1"/><text x="470" y="241" text-anchor="middle" fill="#94a3b8" font-size="10">W5</text>
  <rect x="525" y="222" width="60" height="28" rx="5" fill="#1e293b" stroke="#64748b" stroke-width="1"/><text x="555" y="241" text-anchor="middle" fill="#94a3b8" font-size="10">W6</text>
  <text x="600" y="241" fill="#64748b" font-size="9" font-style="italic">Leaf workers</text>
  <!-- Footer -->
  <rect x="100" y="280" width="460" height="44" rx="6" fill="#1e293b" stroke="#334155" stroke-width="1"/>
  <text x="330" y="300" text-anchor="middle" fill="#94a3b8" font-size="11">Total budget consumed &le; 100% (enforced by budget hierarchy)</text>
  <text x="330" y="316" text-anchor="middle" fill="#f87171" font-size="11">max_depth: 3 (prevents unbounded recursion)</text>
</svg>
</p>

**Budget flows down, results flow up.** Each level receives a subset of the parent's budget. A department manager cannot spend more than the CEO allocated. This hierarchical budget enforcement is unique to AWP.

---

## 7. The Safety Architecture

Safety in AWP is not a feature — it's a structural property. Every design decision supports the principle: **safety scales with autonomy**.

### 7.1 Defense in Depth

<p align="center">
<svg viewBox="0 0 640 420" xmlns="http://www.w3.org/2000/svg" font-family="system-ui, -apple-system, sans-serif" width="640" height="420">
  <rect width="640" height="420" rx="12" fill="#0f172a"/>
  <text x="320" y="28" text-anchor="middle" fill="#94a3b8" font-size="15" font-weight="600">SAFETY LAYERS (Defense in Depth)</text>
  <!-- Layer 1 -->
  <rect x="40" y="44" width="560" height="52" rx="6" fill="#1e293b" stroke="#3b82f6" stroke-width="1.5"/>
  <circle cx="65" cy="70" r="12" fill="#1e3a5f" stroke="#3b82f6" stroke-width="1"/><text x="65" y="74" text-anchor="middle" fill="#60a5fa" font-size="10" font-weight="700">1</text>
  <text x="90" y="64" fill="#60a5fa" font-size="11" font-weight="600">STATIC VALIDATION (before any execution)</text>
  <text x="90" y="80" fill="#94a3b8" font-size="10">26 rules check structure, naming, types, references. Zero cost — no LLM calls needed.</text>
  <!-- Layer 2 -->
  <rect x="40" y="104" width="560" height="52" rx="6" fill="#1e293b" stroke="#10b981" stroke-width="1.5"/>
  <circle cx="65" cy="130" r="12" fill="#022c22" stroke="#10b981" stroke-width="1"/><text x="65" y="134" text-anchor="middle" fill="#34d399" font-size="10" font-weight="700">2</text>
  <text x="90" y="124" fill="#34d399" font-size="11" font-weight="600">BUDGET ENFORCEMENT (during execution)</text>
  <text x="90" y="140" fill="#94a3b8" font-size="10">max_loops, max_workers, max_tokens, max_wall_time. Hard limits agents CANNOT override.</text>
  <!-- Layer 3 -->
  <rect x="40" y="164" width="560" height="52" rx="6" fill="#1e293b" stroke="#f59e0b" stroke-width="1.5"/>
  <circle cx="65" cy="190" r="12" fill="#422006" stroke="#f59e0b" stroke-width="1"/><text x="65" y="194" text-anchor="middle" fill="#fbbf24" font-size="10" font-weight="700">3</text>
  <text x="90" y="184" fill="#fbbf24" font-size="11" font-weight="600">IMMUTABLE WORKER POLICY (A2+)</text>
  <text x="90" y="200" fill="#94a3b8" font-size="10">Sandbox type, forbidden tools, rate limits. The manager CANNOT override these constraints.</text>
  <!-- Layer 4 -->
  <rect x="40" y="224" width="560" height="52" rx="6" fill="#1e293b" stroke="#f97316" stroke-width="1.5"/>
  <circle cx="65" cy="250" r="12" fill="#431407" stroke="#f97316" stroke-width="1"/><text x="65" y="254" text-anchor="middle" fill="#fb923c" font-size="10" font-weight="700">4</text>
  <text x="90" y="244" fill="#fb923c" font-size="11" font-weight="600">SANDBOX ISOLATION (code execution)</text>
  <text x="90" y="260" fill="#94a3b8" font-size="10">subprocess | venv | docker | wasm | isolate. ALWAYS_DENIED: os, subprocess, sys, ctypes.</text>
  <!-- Layer 5 -->
  <rect x="40" y="284" width="560" height="52" rx="6" fill="#1e293b" stroke="#ef4444" stroke-width="1.5"/>
  <circle cx="65" cy="310" r="12" fill="#450a0a" stroke="#ef4444" stroke-width="1"/><text x="65" y="314" text-anchor="middle" fill="#f87171" font-size="10" font-weight="700">5</text>
  <text x="90" y="304" fill="#f87171" font-size="11" font-weight="600">STALL DETECTION (automatic termination)</text>
  <text x="90" y="320" fill="#94a3b8" font-size="10">Confidence delta tracking over sliding window. Prevents infinite loops and resource waste.</text>
  <!-- Layer 6 -->
  <rect x="40" y="344" width="560" height="52" rx="6" fill="#1e293b" stroke="#a78bfa" stroke-width="1.5"/>
  <circle cx="65" cy="370" r="12" fill="#1a1035" stroke="#a78bfa" stroke-width="1"/><text x="65" y="374" text-anchor="middle" fill="#a78bfa" font-size="10" font-weight="700">6</text>
  <text x="90" y="364" fill="#a78bfa" font-size="11" font-weight="600">OBSERVABILITY (full audit trail)</text>
  <text x="90" y="380" fill="#94a3b8" font-size="10">Hash-chained audit log (tamper-evident). OpenTelemetry. Every tool call and decision recorded.</text>
</svg>
</p>

### 7.2 The Immutable Envelope

At A2+, the workflow author declares a **safety envelope** that the manager cannot modify:

```yaml
worker_policy:
  enforced:                          # IMMUTABLE — manager cannot override
    sandbox:
      type: subprocess
      max_memory_mb: 512
      network: false
    forbidden_tools:
      - shell.execute
      - file.write_outside_workspace
    rate_limiting:
      max_llm_calls_per_minute: 30

  manager_controlled:                # Manager CAN vary these per worker
    - instructions
    - skills
    - tools_allowed
    - temperature
    - output_contract
```

**Why this matters:** In frameworks like CrewAI or AutoGen, if an agent "goes rogue" (hallucinated tool calls, infinite loops, excessive API usage), there's no structural barrier. AWP's immutable policy means the *workflow definition* — not the runtime agent — sets the safety boundaries.

### 7.3 The Output Contract: Confidence as Universal Signal

Every agent in AWP must return a confidence score (0.0-1.0). This is not optional — it's validation rule R17:

<p align="center">
<svg viewBox="0 0 620 260" xmlns="http://www.w3.org/2000/svg" font-family="system-ui, -apple-system, sans-serif" width="620" height="260">
  <defs>
    <marker id="ah10" markerWidth="8" markerHeight="6" refX="8" refY="3" orient="auto"><path d="M0,0 L8,3 L0,6" fill="#f59e0b"/></marker>
  </defs>
  <rect width="620" height="260" rx="12" fill="#0f172a"/>
  <text x="310" y="28" text-anchor="middle" fill="#94a3b8" font-size="15" font-weight="600">CONFIDENCE DRIVES EVERYTHING</text>
  <!-- Agent output -->
  <rect x="90" y="42" width="440" height="30" rx="6" fill="#1e293b" stroke="#475569" stroke-width="1"/>
  <text x="310" y="62" text-anchor="middle" fill="#cbd5e1" font-size="10" font-family="monospace">Agent returns: { "agent_name": { "confidence": 0.82, ... } }</text>
  <!-- Confidence line -->
  <line x1="310" y1="72" x2="310" y2="95" stroke="#f59e0b" stroke-width="2"/>
  <text x="310" y="90" text-anchor="middle" fill="#fbbf24" font-size="11" font-weight="600">confidence</text>
  <!-- Branch lines -->
  <line x1="310" y1="100" x2="140" y2="130" stroke="#f59e0b" stroke-width="1.5" marker-end="url(#ah10)"/>
  <line x1="310" y1="100" x2="310" y2="130" stroke="#f59e0b" stroke-width="1.5" marker-end="url(#ah10)"/>
  <line x1="310" y1="100" x2="480" y2="130" stroke="#f59e0b" stroke-width="1.5" marker-end="url(#ah10)"/>
  <!-- Three boxes -->
  <rect x="60" y="135" width="160" height="65" rx="6" fill="#1e293b" stroke="#ef4444" stroke-width="1.5"/>
  <text x="140" y="155" text-anchor="middle" fill="#f87171" font-size="11" font-weight="600">Stall Detection</text>
  <text x="140" y="172" text-anchor="middle" fill="#94a3b8" font-size="9">"Is the system</text>
  <text x="140" y="185" text-anchor="middle" fill="#94a3b8" font-size="9">making progress?"</text>
  <rect x="230" y="135" width="160" height="65" rx="6" fill="#1e293b" stroke="#3b82f6" stroke-width="1.5"/>
  <text x="310" y="155" text-anchor="middle" fill="#60a5fa" font-size="11" font-weight="600">LLM Validation</text>
  <text x="310" y="172" text-anchor="middle" fill="#94a3b8" font-size="9">Skip if</text>
  <text x="310" y="185" text-anchor="middle" fill="#94a3b8" font-size="9">conf &gt; 0.95</text>
  <rect x="400" y="135" width="160" height="65" rx="6" fill="#1e293b" stroke="#10b981" stroke-width="1.5"/>
  <text x="480" y="155" text-anchor="middle" fill="#34d399" font-size="11" font-weight="600">Manager Decision</text>
  <text x="480" y="172" text-anchor="middle" fill="#94a3b8" font-size="9">"Should I iterate</text>
  <text x="480" y="185" text-anchor="middle" fill="#94a3b8" font-size="9">or stop?"</text>
  <!-- Footer -->
  <rect x="90" y="218" width="440" height="30" rx="6" fill="#422006" stroke="#f59e0b" stroke-width="1"/>
  <text x="310" y="238" text-anchor="middle" fill="#fbbf24" font-size="10">The confidence field is the nervous system of the protocol — connecting validation, termination, and decisions.</text>
</svg>
</p>

---

## 8. What Scientists Can Do Now

AWP was designed with a specific user in mind: the domain expert who needs multi-agent AI but shouldn't need to be a software engineer to use it. Here's what's now possible.

### 8.1 Three Lines to Multi-Agent Analysis

```python
from awp.data import AgentWorkflow
import pandas as pd

result = AgentWorkflow(
    inputs={"data": pd.read_csv("experiment_results.csv")},
    task="Identify statistically significant patterns and generate publication-ready visualizations",
    model="openrouter/anthropic/claude-sonnet-4",
).run()
```

Behind these three lines, the system:
1. Creates a delegation loop with a manager agent
2. The manager analyzes the data shape and creates specialized workers
3. Workers run statistical tests, create visualizations, write interpretations
4. Results are validated, aggregated, and returned

**No YAML. No agent configuration. No tool setup.** The `AgentWorkflow` API is a zero-configuration entry point that creates an A4 delegation loop internally.

### 8.2 Research Workflows That Were Previously Impossible

<p align="center">
<svg viewBox="0 0 720 560" xmlns="http://www.w3.org/2000/svg" font-family="system-ui, -apple-system, sans-serif" width="720" height="560">
  <rect width="720" height="560" rx="12" fill="#0f172a"/>
  <text x="360" y="28" text-anchor="middle" fill="#94a3b8" font-size="15" font-weight="600">SCIENTIFIC WORKFLOWS ENABLED BY AWP</text>
  <!-- Card 1: Multi-modal -->
  <rect x="20" y="44" width="335" height="228" rx="8" fill="#1e293b" stroke="#3b82f6" stroke-width="1.5"/>
  <text x="40" y="68" fill="#60a5fa" font-size="12" font-weight="700">MULTI-MODAL DATA ANALYSIS</text>
  <text x="40" y="90" fill="#64748b" font-size="9" font-family="monospace">inputs: { genomic_data, expression,</text>
  <text x="40" y="104" fill="#64748b" font-size="9" font-family="monospace">  microscopy, clinical }</text>
  <text x="40" y="122" fill="#94a3b8" font-size="9">task: "Correlate gene expression with</text>
  <text x="40" y="136" fill="#94a3b8" font-size="9">cell morphology and clinical outcomes"</text>
  <line x1="40" y1="148" x2="335" y2="148" stroke="#334155" stroke-width="0.5"/>
  <text x="40" y="168" fill="#cbd5e1" font-size="9">Manager creates genomics worker (BioPython)</text>
  <text x="40" y="184" fill="#cbd5e1" font-size="9">Manager creates imaging worker (scikit-image)</text>
  <text x="40" y="200" fill="#cbd5e1" font-size="9">Manager creates statistics worker (scipy)</text>
  <text x="40" y="216" fill="#34d399" font-size="9">Workers CREATE custom domain-specific tools</text>
  <text x="40" y="232" fill="#cbd5e1" font-size="9">Manager synthesizes cross-modal findings</text>
  <text x="40" y="260" fill="#fbbf24" font-size="9">Autonomy: A3 (Self-Tooling)</text>
  <!-- Card 2: Literature review -->
  <rect x="365" y="44" width="335" height="228" rx="8" fill="#1e293b" stroke="#10b981" stroke-width="1.5"/>
  <text x="385" y="68" fill="#34d399" font-size="12" font-weight="700">LITERATURE REVIEW + META-ANALYSIS</text>
  <text x="385" y="90" fill="#64748b" font-size="9" font-family="monospace">inputs: { papers: "papers/*.pdf" }</text>
  <text x="385" y="112" fill="#94a3b8" font-size="9">task: "Extract effect sizes, assess bias,</text>
  <text x="385" y="126" fill="#94a3b8" font-size="9">run random-effects meta-analysis"</text>
  <line x1="385" y1="140" x2="680" y2="140" stroke="#334155" stroke-width="0.5"/>
  <text x="385" y="160" fill="#cbd5e1" font-size="9">Worker-1 extracts structured data from PDFs</text>
  <text x="385" y="176" fill="#34d399" font-size="9">Worker-2 creates meta-analysis tool (statsmodels)</text>
  <text x="385" y="192" fill="#cbd5e1" font-size="9">Worker-3 runs analysis + generates forest plot</text>
  <text x="385" y="208" fill="#cbd5e1" font-size="9">Worker-4 writes interpretation with citations</text>
  <text x="385" y="260" fill="#fbbf24" font-size="9">Autonomy: A3 (Self-Tooling)</text>
  <!-- Card 3: Reproducible -->
  <rect x="20" y="282" width="335" height="250" rx="8" fill="#1e293b" stroke="#f59e0b" stroke-width="1.5"/>
  <text x="40" y="306" fill="#fbbf24" font-size="12" font-weight="700">REPRODUCIBLE EXPERIMENTS</text>
  <text x="40" y="328" fill="#64748b" font-size="9" font-family="monospace">inputs: { config: "experiment.yaml",</text>
  <text x="40" y="342" fill="#64748b" font-size="9" font-family="monospace">  data: "raw/*.csv" }</text>
  <text x="40" y="364" fill="#94a3b8" font-size="9">task: "Run parameter sweep, identify optimal</text>
  <text x="40" y="378" fill="#94a3b8" font-size="9">config, generate reproducibility report"</text>
  <line x1="40" y1="390" x2="335" y2="390" stroke="#334155" stroke-width="0.5"/>
  <text x="40" y="410" fill="#cbd5e1" font-size="9">Workers fan out across parameter space</text>
  <text x="40" y="426" fill="#cbd5e1" font-size="9">Each worker runs in isolated sandbox</text>
  <text x="40" y="442" fill="#cbd5e1" font-size="9">Manager aggregates, identifies convergence</text>
  <text x="40" y="458" fill="#cbd5e1" font-size="9">Final worker generates LaTeX-ready report</text>
  <text x="40" y="474" fill="#a78bfa" font-size="9">Full audit trail ensures reproducibility</text>
  <text x="40" y="520" fill="#fbbf24" font-size="9">Autonomy: A2 (Delegating) + Observability</text>
  <!-- Card 4: Hypothesis -->
  <rect x="365" y="282" width="335" height="250" rx="8" fill="#1e293b" stroke="#a78bfa" stroke-width="1.5"/>
  <text x="385" y="306" fill="#a78bfa" font-size="12" font-weight="700">AUTOMATED HYPOTHESIS GENERATION</text>
  <text x="385" y="328" fill="#64748b" font-size="9" font-family="monospace">inputs: { dataset: df,</text>
  <text x="385" y="342" fill="#64748b" font-size="9" font-family="monospace">  domain_papers: "refs/*.pdf" }</text>
  <text x="385" y="364" fill="#94a3b8" font-size="9">task: "Generate 5 testable hypotheses</text>
  <text x="385" y="378" fill="#94a3b8" font-size="9">ranked by expected impact"</text>
  <line x1="385" y1="390" x2="680" y2="390" stroke="#334155" stroke-width="0.5"/>
  <text x="385" y="410" fill="#cbd5e1" font-size="9">Worker-1 profiles data (distributions, corr.)</text>
  <text x="385" y="426" fill="#cbd5e1" font-size="9">Worker-2 extracts known findings from literature</text>
  <text x="385" y="442" fill="#cbd5e1" font-size="9">Worker-3 identifies gaps (data vs. literature)</text>
  <text x="385" y="458" fill="#cbd5e1" font-size="9">Manager ranks by novelty + testability</text>
  <text x="385" y="474" fill="#cbd5e1" font-size="9">Each hypothesis includes test methodology</text>
  <text x="385" y="520" fill="#fbbf24" font-size="9">Autonomy: A4 (Self-Organizing)</text>
</svg>
</p>

### 8.3 The Jupyter Integration

AWP's `AgentWorkflow` API is designed for notebook-first workflows:

```python
# Cell 1: Load data
import pandas as pd
df = pd.read_csv("measurements.csv")
df.head()

# Cell 2: Run multi-agent analysis
from awp.data import AgentWorkflow

result = AgentWorkflow(
    inputs={"measurements": df, "sensor_layout": "layout.png"},
    task="Detect anomalies in sensor readings, correlate with spatial layout, suggest root causes",
    max_loops=10,
    max_total_tokens=500_000,
    code_mode=True,
    tool_creation=True,
    verbose=True,      # Stream progress to notebook
).run()

# Cell 3: Inspect results
print(result["final_answer"])

# Cell 4: Use generated artifacts
# AWP saves all generated code, tools, and visualizations to workspace/
!ls workspace/outputs/
```

**Key insight:** The `code_mode=True` + `tool_creation=True` flags enable the full self-tooling capability. Without YAML, without configuration, a scientist in a Jupyter notebook gets the same A3+ capabilities that the full protocol provides.

---

## 9. From Abstract Idea to Running System

Let's trace the journey of a single idea — "analyze this data" — from abstract intention through every architectural layer to concrete execution.

### 9.1 The Full Stack: Idea to Execution

<p align="center">
<svg viewBox="0 0 720 680" xmlns="http://www.w3.org/2000/svg" font-family="system-ui, -apple-system, sans-serif" width="720" height="680">
  <defs>
    <marker id="ah11" markerWidth="7" markerHeight="5" refX="7" refY="2.5" orient="auto"><path d="M0,0 L7,2.5 L0,5" fill="#475569"/></marker>
  </defs>
  <rect width="720" height="680" rx="12" fill="#0f172a"/>
  <text x="360" y="26" text-anchor="middle" fill="#94a3b8" font-size="14" font-weight="600">FROM IDEA TO EXECUTION: THE FULL STACK</text>
  <!-- Row 1: User Intent -->
  <rect x="40" y="40" width="300" height="36" rx="6" fill="#422006" stroke="#f59e0b" stroke-width="1.5"/>
  <text x="190" y="63" text-anchor="middle" fill="#fbbf24" font-size="11" font-weight="600">User Intent: "Analyze this dataset"</text>
  <text x="390" y="63" fill="#64748b" font-size="10">Python / Jupyter</text>
  <line x1="190" y1="76" x2="190" y2="92" stroke="#475569" stroke-width="1.5" marker-end="url(#ah11)"/>
  <!-- Row 2: AgentWorkflow -->
  <rect x="40" y="96" width="300" height="50" rx="6" fill="#1e293b" stroke="#10b981" stroke-width="1.5"/>
  <text x="60" y="116" fill="#34d399" font-size="11" font-weight="600">AgentWorkflow</text>
  <text x="60" y="134" fill="#94a3b8" font-size="9">Auto-generates manifest, delegation loop, budget</text>
  <text x="390" y="124" fill="#64748b" font-size="10">awp.data.workflow</text>
  <line x1="190" y1="146" x2="190" y2="162" stroke="#475569" stroke-width="1.5" marker-end="url(#ah11)"/>
  <!-- Row 3: Validation -->
  <rect x="40" y="166" width="300" height="40" rx="6" fill="#1e293b" stroke="#3b82f6" stroke-width="1.5"/>
  <text x="60" y="186" fill="#60a5fa" font-size="11" font-weight="600">Validation</text>
  <text x="175" y="186" fill="#94a3b8" font-size="9">26 rules checked, R17: confidence required</text>
  <text x="390" y="190" fill="#64748b" font-size="10">awp.validator.rules</text>
  <line x1="190" y1="206" x2="190" y2="222" stroke="#475569" stroke-width="1.5" marker-end="url(#ah11)"/>
  <!-- Row 4: Orchestration -->
  <rect x="40" y="226" width="300" height="40" rx="6" fill="#1e293b" stroke="#ec4899" stroke-width="1.5"/>
  <text x="60" y="246" fill="#f472b6" font-size="11" font-weight="600">Layer 5: Orchestration</text>
  <text x="230" y="246" fill="#94a3b8" font-size="9">DelegationLoopRunner init</text>
  <text x="390" y="250" fill="#64748b" font-size="10">awp.runtime.delegation_loop_runner</text>
  <line x1="190" y1="266" x2="190" y2="282" stroke="#475569" stroke-width="1.5" marker-end="url(#ah11)"/>
  <!-- Row 5: Agent Identity -->
  <rect x="40" y="286" width="300" height="40" rx="6" fill="#1e293b" stroke="#10b981" stroke-width="1.5"/>
  <text x="60" y="306" fill="#34d399" font-size="11" font-weight="600">Layer 1: Agent Identity</text>
  <text x="230" y="306" fill="#94a3b8" font-size="9">Manager agent loads</text>
  <text x="390" y="310" fill="#64748b" font-size="10">awp.runtime.agent</text>
  <line x1="190" y1="326" x2="190" y2="342" stroke="#475569" stroke-width="1.5" marker-end="url(#ah11)"/>
  <!-- Row 6: LLM -->
  <rect x="40" y="346" width="300" height="40" rx="6" fill="#1e293b" stroke="#f59e0b" stroke-width="1.5"/>
  <text x="60" y="366" fill="#fbbf24" font-size="11" font-weight="600">LLM Client</text>
  <text x="155" y="366" fill="#94a3b8" font-size="9">"How should I decompose this task?"</text>
  <text x="390" y="370" fill="#64748b" font-size="10">awp.runtime.llm</text>
  <line x1="190" y1="386" x2="190" y2="402" stroke="#475569" stroke-width="1.5" marker-end="url(#ah11)"/>
  <!-- Row 7: Fan-out -->
  <rect x="40" y="406" width="300" height="40" rx="6" fill="#1e293b" stroke="#3b82f6" stroke-width="1.5"/>
  <text x="60" y="426" fill="#60a5fa" font-size="11" font-weight="600">Layer 2: Capabilities</text>
  <text x="220" y="426" fill="#94a3b8" font-size="9">DelegationEnvelopes generated</text>
  <line x1="190" y1="446" x2="190" y2="462" stroke="#475569" stroke-width="1.5" marker-end="url(#ah11)"/>
  <!-- Row 8: Workers -->
  <rect x="40" y="466" width="90" height="46" rx="5" fill="#1e293b" stroke="#64748b" stroke-width="1"/>
  <text x="85" y="486" text-anchor="middle" fill="#cbd5e1" font-size="9">Worker-1</text>
  <text x="85" y="500" text-anchor="middle" fill="#64748b" font-size="8">Data profiling</text>
  <rect x="145" y="466" width="90" height="46" rx="5" fill="#1e293b" stroke="#64748b" stroke-width="1"/>
  <text x="190" y="486" text-anchor="middle" fill="#cbd5e1" font-size="9">Worker-2</text>
  <text x="190" y="500" text-anchor="middle" fill="#34d399" font-size="8">Statistical + tools</text>
  <rect x="250" y="466" width="90" height="46" rx="5" fill="#1e293b" stroke="#64748b" stroke-width="1"/>
  <text x="295" y="486" text-anchor="middle" fill="#cbd5e1" font-size="9">Worker-3</text>
  <text x="295" y="500" text-anchor="middle" fill="#64748b" font-size="8">Visualization</text>
  <text x="390" y="490" fill="#64748b" font-size="10">awp.runtime (parallel)</text>
  <line x1="190" y1="512" x2="190" y2="528" stroke="#475569" stroke-width="1.5" marker-end="url(#ah11)"/>
  <!-- Row 9: State + Validation -->
  <rect x="40" y="532" width="145" height="40" rx="6" fill="#1e293b" stroke="#f59e0b" stroke-width="1.5"/>
  <text x="112" y="552" text-anchor="middle" fill="#fbbf24" font-size="10" font-weight="500">Layer 4: State</text>
  <text x="112" y="564" text-anchor="middle" fill="#64748b" font-size="8">results + spillover</text>
  <rect x="195" y="532" width="145" height="40" rx="6" fill="#1e293b" stroke="#3b82f6" stroke-width="1.5"/>
  <text x="267" y="552" text-anchor="middle" fill="#60a5fa" font-size="10" font-weight="500">Two-Tier Validation</text>
  <text x="267" y="564" text-anchor="middle" fill="#64748b" font-size="8">schema + LLM semantic</text>
  <line x1="190" y1="572" x2="190" y2="588" stroke="#475569" stroke-width="1.5" marker-end="url(#ah11)"/>
  <!-- Row 10: Decision -->
  <rect x="40" y="592" width="300" height="30" rx="6" fill="#1e293b" stroke="#ec4899" stroke-width="1"/>
  <text x="190" y="612" text-anchor="middle" fill="#f472b6" font-size="10">Decision: Budget OK? Progress? Loop or Stop</text>
  <line x1="190" y1="622" x2="190" y2="638" stroke="#475569" stroke-width="1.5" marker-end="url(#ah11)"/>
  <!-- Row 11: Result -->
  <rect x="40" y="642" width="300" height="30" rx="6" fill="#022c22" stroke="#10b981" stroke-width="2"/>
  <text x="190" y="662" text-anchor="middle" fill="#34d399" font-size="11" font-weight="600">Result: { "final_answer": "...", "artifacts": [...] }</text>
</svg>
</p>

### 9.2 Concrete Example: Financial Time Series

Let's follow a real workflow through the system:

**Input:**
```python
result = AgentWorkflow(
    inputs={"prices": pd.read_csv("stock_prices.csv")},
    task="Identify regime changes, compute risk metrics, forecast next 30 days",
    max_loops=8,
    code_mode=True,
    tool_creation=True,
).run()
```

**Iteration 1 — Manager analyzes:**
```
Manager sees: DataFrame with columns [date, open, high, low, close, volume]
Manager decides: Need 3 workers
  Worker-1: "Profile the data — distributions, stationarity, seasonality"
  Worker-2: "Detect structural breaks using CUSUM or Bai-Perron"
  Worker-3: "Compute VaR, CVaR, Sharpe, max drawdown"
```

**Iteration 2 — Workers execute:**
```
Worker-1: Runs ADF test → non-stationary. Computes returns → stationary.
          Creates skill: "Use log returns, not raw prices, for all analysis"
          confidence: 0.91

Worker-2: Needs Bai-Perron test → no built-in tool.
          Creates tool: dynamic.structural_breaks(series, max_breaks=5)
          Finds 3 regime changes at dates [2024-03, 2024-08, 2025-01]
          confidence: 0.85

Worker-3: Computes VaR(95%)=-2.3%, CVaR=-3.1%, Sharpe=1.4
          confidence: 0.93
```

**Iteration 3 — Manager synthesizes:**
```
Manager sees: All results, confidence > 0.85
Manager decides: Need forecast worker using regime-aware model
  Worker-4: "Forecast using regime-switching model. Use the structural
             breaks from Worker-2. Use log returns per Worker-1's skill."
  Worker-4 receives: Worker-1's skill + Worker-2's tool + all results
```

**Iteration 4 — Final worker:**
```
Worker-4: Uses dynamic.structural_breaks tool (created by Worker-2!)
          Applies regime-switching ARIMA
          Generates forecast plot → workspace/outputs/forecast.png
          confidence: 0.88

Manager: All tasks complete. Aggregate confidence: 0.89. STOP.
```

**Total: 4 iterations, 7 workers, ~180K tokens. Budget: well within limits.**

### 9.3 The Architecture Map

Here is how the packages, layers, and runtime components relate:

<p align="center">
<svg viewBox="0 0 740 440" xmlns="http://www.w3.org/2000/svg" font-family="system-ui, -apple-system, sans-serif" width="740" height="440">
  <defs>
    <marker id="ah12" markerWidth="7" markerHeight="5" refX="7" refY="2.5" orient="auto"><path d="M0,0 L7,2.5 L0,5" fill="#60a5fa"/></marker>
  </defs>
  <rect width="740" height="440" rx="12" fill="#0f172a"/>
  <text x="370" y="26" text-anchor="middle" fill="#94a3b8" font-size="15" font-weight="600">AWP ARCHITECTURE MAP</text>
  <!-- awp-core -->
  <rect x="20" y="42" width="340" height="290" rx="8" fill="#1e293b" stroke="#3b82f6" stroke-width="2"/>
  <text x="190" y="64" text-anchor="middle" fill="#60a5fa" font-size="13" font-weight="700">awp-core (Protocol)</text>
  <!-- models -->
  <rect x="35" y="76" width="200" height="160" rx="5" fill="#0f172a" stroke="#334155" stroke-width="1"/>
  <text x="45" y="94" fill="#60a5fa" font-size="10" font-weight="600">models/</text>
  <text x="55" y="112" fill="#94a3b8" font-size="9">manifest.py</text><text x="160" y="112" fill="#475569" font-size="8">L0</text>
  <text x="55" y="126" fill="#94a3b8" font-size="9">agent.py</text><text x="160" y="126" fill="#475569" font-size="8">L1</text>
  <text x="55" y="140" fill="#94a3b8" font-size="9">capabilities.py</text><text x="160" y="140" fill="#475569" font-size="8">L2</text>
  <text x="55" y="154" fill="#94a3b8" font-size="9">communication.py</text><text x="160" y="154" fill="#475569" font-size="8">L3</text>
  <text x="55" y="168" fill="#94a3b8" font-size="9">memory.py / state.py</text><text x="160" y="168" fill="#475569" font-size="8">L4</text>
  <text x="55" y="182" fill="#94a3b8" font-size="9">orchestration.py</text><text x="160" y="182" fill="#475569" font-size="8">L5</text>
  <text x="55" y="196" fill="#94a3b8" font-size="9">observability.py</text><text x="160" y="196" fill="#475569" font-size="8">L6</text>
  <text x="55" y="210" fill="#94a3b8" font-size="9">security.py</text>
  <text x="55" y="228" fill="#94a3b8" font-size="9">+6 more model files</text>
  <!-- parser -->
  <rect x="35" y="242" width="142" height="30" rx="5" fill="#0f172a" stroke="#334155" stroke-width="1"/>
  <text x="106" y="262" text-anchor="middle" fill="#60a5fa" font-size="10">parser/ YAML Models</text>
  <!-- validator -->
  <rect x="185" y="242" width="142" height="30" rx="5" fill="#0f172a" stroke="#334155" stroke-width="1"/>
  <text x="256" y="262" text-anchor="middle" fill="#60a5fa" font-size="10">validator/ R1-R26</text>
  <!-- agent.py -->
  <rect x="35" y="278" width="310" height="26" rx="5" fill="#0f172a" stroke="#334155" stroke-width="1"/>
  <text x="190" y="296" text-anchor="middle" fill="#60a5fa" font-size="10">agent.py (AWPAgent abstract interface)</text>
  <!-- Arrow core -> runtime -->
  <line x1="242" y1="154" x2="388" y2="154" stroke="#60a5fa" stroke-width="1.5" stroke-dasharray="4,3" marker-end="url(#ah12)"/>
  <!-- awp-runtime -->
  <rect x="380" y="42" width="340" height="290" rx="8" fill="#1e293b" stroke="#10b981" stroke-width="2"/>
  <text x="550" y="64" text-anchor="middle" fill="#34d399" font-size="13" font-weight="700">awp-runtime (Execution)</text>
  <!-- runtime module -->
  <rect x="395" y="76" width="200" height="200" rx="5" fill="#0f172a" stroke="#334155" stroke-width="1"/>
  <text x="405" y="94" fill="#34d399" font-size="10" font-weight="600">runtime/</text>
  <text x="415" y="112" fill="#94a3b8" font-size="9">runner.py</text><text x="560" y="112" fill="#475569" font-size="8">DAG</text>
  <text x="415" y="126" fill="#94a3b8" font-size="9">delegation_loop_runner.py</text>
  <text x="415" y="140" fill="#94a3b8" font-size="9">agent.py</text><text x="560" y="140" fill="#475569" font-size="8">Standalone</text>
  <text x="415" y="154" fill="#94a3b8" font-size="9">llm.py</text><text x="560" y="154" fill="#475569" font-size="8">LLM Client</text>
  <text x="415" y="168" fill="#94a3b8" font-size="9">tools.py</text><text x="560" y="168" fill="#475569" font-size="8">Registry</text>
  <text x="415" y="182" fill="#34d399" font-size="9">dynamic_tool_factory.py</text>
  <text x="415" y="196" fill="#34d399" font-size="9">skill_loader.py</text>
  <text x="415" y="210" fill="#94a3b8" font-size="9">code_executor.py</text>
  <text x="415" y="224" fill="#94a3b8" font-size="9">context_sharing.py</text>
  <text x="415" y="238" fill="#94a3b8" font-size="9">message_bus.py</text>
  <text x="415" y="252" fill="#94a3b8" font-size="9">observability.py</text>
  <text x="415" y="266" fill="#94a3b8" font-size="9">+4 more modules</text>
  <!-- data module -->
  <rect x="395" y="284" width="200" height="38" rx="5" fill="#0f172a" stroke="#334155" stroke-width="1"/>
  <text x="495" y="300" text-anchor="middle" fill="#34d399" font-size="10">data/ Zero-config API</text>
  <text x="495" y="314" text-anchor="middle" fill="#64748b" font-size="9">workflow.py + inputs.py</text>
  <!-- Bottom boxes -->
  <rect x="20" y="360" width="340" height="60" rx="8" fill="#1e293b" stroke="#64748b" stroke-width="1"/>
  <text x="190" y="382" text-anchor="middle" fill="#94a3b8" font-size="11" font-weight="500">spec/</text>
  <text x="190" y="400" text-anchor="middle" fill="#64748b" font-size="9">Normative specification (RFC 2119)</text>
  <text x="190" y="414" text-anchor="middle" fill="#64748b" font-size="9">Layer definitions</text>
  <rect x="380" y="360" width="340" height="60" rx="8" fill="#1e293b" stroke="#64748b" stroke-width="1"/>
  <text x="550" y="382" text-anchor="middle" fill="#94a3b8" font-size="11" font-weight="500">awp-ui (optional)</text>
  <text x="550" y="400" text-anchor="middle" fill="#64748b" font-size="9">Workflow Studio</text>
  <text x="550" y="414" text-anchor="middle" fill="#64748b" font-size="9">Visual graph editor + real-time viewer</text>
</svg>
</p>

---

## 10. Conclusion: The Insight

The journey through AWP's architecture reveals a single organizing principle:

**Declare what you want. Let the system figure out how.**

This is not a new idea — it's the principle behind SQL, Kubernetes, Terraform, and every successful declarative system. But it hadn't been applied to multi-agent AI orchestration until AWP.

The consequences compound:

1. **Because** the workflow is declarative, it can be validated before execution → 26 rules catch errors for free.
2. **Because** validation exists, the runtime can trust the structure → it can safely grant agents more autonomy.
3. **Because** agents have more autonomy, they can create tools and skills → emergent capability genesis.
4. **Because** capability genesis exists, workflows solve problems their authors didn't anticipate → true adaptivity.
5. **Because** adaptivity is powerful, it must be bounded → formal budget and safety architecture.
6. **Because** safety is structural (not optional), the system scales → from 3-line scripts to recursive delegation hierarchies.

Each step enables the next. Remove any one, and the chain breaks.

This is the insight: **the right constraints create freedom.** A budget isn't a limitation — it's what makes autonomous delegation safe enough to deploy. A validation rule isn't bureaucracy — it's what lets you trust agent output enough to feed it to other agents. A sandbox isn't restriction — it's what makes runtime tool creation possible.

Other frameworks give you either safety or freedom. AWP gives you both — because it understands they're the same thing.

---

<p align="center">
  <a href="overview.md">Overview</a> &middot;
  <a href="layer-model.md">7-Layer Model</a> &middot;
  <a href="orchestration.md">Orchestration</a> &middot;
  <a href="tools.md">Tools</a> &middot;
  <a href="../README.md">Back to README</a>
</p>
