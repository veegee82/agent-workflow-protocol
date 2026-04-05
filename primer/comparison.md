# AWP vs Existing Standards

AWP does not exist in a vacuum. It builds on lessons from existing protocols and frameworks, and in several cases, directly incorporates them. This document provides a detailed comparison to help you understand where AWP fits in the ecosystem.

## Feature Comparison Matrix

| Feature | AWP | MCP | A2A | OpenAPI | LangGraph | CrewAI |
|---------|-----|-----|-----|---------|-----------|--------|
| Agent Identity | Yes | No | Yes | No | No | Partial |
| Tool Protocol | MCP-compatible | Yes | No | No | No | No |
| Orchestration (DAG) | Yes | No | No | No | Yes | Partial |
| Memory Protocol | Yes (4 tiers) | No | No | No | Checkpoints | Partial |
| Communication | Yes (Message Bus) | No | Yes | No | No | No |
| Observability | Yes (OTel) | No | No | No | LangSmith | No |
| State Sharing | Yes (contracts) | No | No | No | Yes | No |
| Output Contract | Yes (JSON Schema) | No | Yes (artifacts) | Yes (schemas) | No | No |
| Packaging | .awp.zip | No | No | No | No | No |
| Autonomy Levels | A0-A4 | No | No | No | No | No |
| Runtime-Agnostic | Yes | Yes | Yes | Yes | No | No |
| Declarative Config | Yes (YAML) | Yes (JSON) | Yes (JSON) | Yes (YAML/JSON) | Partial | Yes (YAML) |
| Versioning | SemVer | No | No | Yes | No | No |
| Validation Rules | 30 rules (R1-R30) | No | No | Yes | No | No |
| Sub-Workflows | Yes | No | No | No | Yes | No |

## Detailed Comparisons

### AWP vs MCP (Model Context Protocol)

**MCP** defines how an LLM accesses external tools: function signatures, parameter schemas, and return formats. It is an excellent protocol for what it does, and AWP adopts it directly for its Layer 2 (Capabilities).

**What MCP does not cover:**
- Who the agent is (no identity, no role, no prompt)
- How multiple agents relate to each other (no graph, no dependencies)
- How agents share state (no state model, no output contracts)
- How to orchestrate execution (no DAG, no execution modes)
- How to persist memory across runs

**AWP's relationship to MCP:** AWP is MCP-compatible at Layer 2. Any MCP tool server works with AWP. AWP extends MCP by wrapping tool access in a complete workflow context.

### AWP vs A2A (Agent-to-Agent Protocol)

**A2A** focuses on inter-agent communication: how agents discover each other, exchange messages, and negotiate tasks. It provides agent cards (identity), task management, and artifact exchange.

**What A2A does not cover:**
- How to define tools and capabilities
- How to orchestrate a multi-step workflow
- How to manage persistent memory
- How to validate workflow structure before execution
- How to package and distribute workflows

**AWP's relationship to A2A:** AWP's Layer 3 (Communication) addresses a similar space as A2A but within the scope of a declared workflow. AWP's message bus could be implemented using A2A as a transport. The two protocols are complementary rather than competing.

### AWP vs OpenAPI

**OpenAPI** describes HTTP APIs: endpoints, request/response schemas, authentication. It is the standard for API documentation and client generation.

**What OpenAPI does not cover:**
- The concept of an autonomous agent
- Execution state that persists across calls
- DAG-based orchestration
- Memory or context that accumulates over time

**AWP's relationship to OpenAPI:** An AWP runtime may expose an OpenAPI-described REST API (and the reference implementation does). But OpenAPI describes the API surface, while AWP describes the workflow semantics behind it.

### AWP vs LangGraph

**LangGraph** provides a state machine abstraction for building agent workflows in Python. It supports conditional edges, loops, and checkpointing. It is powerful and well-integrated with the LangChain ecosystem.

**What LangGraph does not cover:**
- A portable, runtime-agnostic specification format
- Standardized tool definitions (uses LangChain tool wrappers)
- A packaging and distribution format
- Autonomy levels for progressive adoption
- Formal validation before execution

**AWP's relationship to LangGraph:** LangGraph is a runtime; AWP is a specification. An AWP-compatible LangGraph adapter could execute AWP manifests using LangGraph's state machine engine. The workflow definition would live in AWP YAML; the execution would happen in LangGraph.

### AWP vs CrewAI

**CrewAI** uses YAML to define agent roles, goals, and backstories. It provides a simple way to assign tasks to agents with different personas.

**What CrewAI does not cover:**
- Formal DAG orchestration (offers sequential/hierarchical process, but no arbitrary dependency graphs)
- A standardized tool protocol (uses custom tool wrappers, not MCP)
- Tiered memory protocol (has short-term, long-term, and entity memory, but no formal protocol spec)
- Output contracts with schema validation
- Packaging and portability across runtimes

**AWP's relationship to CrewAI:** CrewAI's YAML role definitions are conceptually similar to AWP's Layer 1. An adapter could translate CrewAI YAML to AWP format, gaining orchestration, memory, and validation capabilities.

## AWP Is Complementary

A common misconception is that AWP competes with MCP or A2A. It does not. AWP operates at a different level of abstraction:

- **MCP** answers: "How does an LLM call a tool?"
- **A2A** answers: "How do two agents exchange messages?"
- **AWP** answers: "How do you describe, validate, and execute a complete multi-agent workflow?"

AWP **uses** MCP for tool definitions at Layer 2. An AWP runtime calls MCP tool servers the same way any MCP client would.

AWP **can use** A2A for agent communication at Layer 3. The message bus defined in AWP could be backed by an A2A transport.

AWP **adds** what neither MCP nor A2A provides: the complete workflow context. Agent identity, orchestration graphs, memory protocols, state contracts, observability hooks, validation rules, and packaging -- all in a single, declarative manifest.

Think of it this way:
- MCP is the **tool interface** (like a system call API)
- A2A is the **network protocol** (like TCP/IP for agents)
- AWP is the **application manifest** (like Docker Compose)

They work together. AWP brings them under one roof.

## When to Use What

| Scenario | Recommended Approach |
|----------|---------------------|
| Single agent calling tools | MCP alone is sufficient |
| Two agents exchanging messages | A2A alone is sufficient |
| Multi-agent workflow with orchestration | AWP (uses MCP for tools internally) |
| Describing an API for external consumers | OpenAPI |
| Building a Python-only prototype | LangGraph or CrewAI may be faster |
| Portable, shareable, validated workflows | AWP |
| Production deployment with observability | AWP at A4 autonomy |
