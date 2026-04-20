# AWP Specification Summary

> **See also** — **Parent**: [skill/SKILL.md](../SKILL.md) · **Authoritative normative spec**: [spec/versions/1.0/spec.md](../../spec/versions/1.0/spec.md) (this file is a condensed mirror) · **Per-layer normative refs**: [spec/versions/1.0/layers/](../../spec/versions/1.0/layers/) · **Non-normative explainers (by layer)**: [manifest](../../docs/manifest.md), [agent](../../docs/agent.md), [tools](../../docs/tools.md), [communication](../../docs/communication.md), [memory](../../docs/memory.md), [orchestration](../../docs/orchestration.md), [observability](../../docs/observability.md), [security](../../docs/security.md) · **Sibling skill references**: [architecture.md](architecture.md), [compliance-levels.md](compliance-levels.md), [validation-rules.md](validation-rules.md), [tools-reference.md](tools-reference.md)

This document provides a condensed overview of the Agent Workflow Protocol (AWP) for use as AI context. It covers all seven layers of the protocol.

## What is AWP?

AWP is a specification for building multi-agent AI workflows. It defines how agents are orchestrated -- either as directed acyclic graphs (DAGs) or via a delegation loop where a manager agent dynamically spawns workers at runtime. AWP covers how agents share state, communicate, remember information across sessions, and operate under governance controls. AWP is platform-agnostic in its design, with a Python reference implementation built on FastAPI.

## Core Concepts

**Workflow:** A self-contained project consisting of a manifest file (`workflow.awp.yaml`), one or more agents, and supporting artifacts (prompts, schemas, tools, skills).

**Agent:** An autonomous unit that receives a task and state, calls an LLM with tools and context, and produces structured JSON output. Each agent has its own configuration, system prompt, output schema, and optional tools.

**Graph (DAG engine):** Agents are organized in a DAG via `depends_on` edges. The orchestrator executes them in topological order. An agent can only run after all its dependencies have completed. Shared output fields flow downstream through the state dictionary.

**Delegation Loop (delegation_loop engine):** A manager agent receives the task and dynamically decides to DELEGATE (spawn ephemeral workers), COMPLETE (return result), or FAIL. Workers are created at runtime via delegation envelopes containing instructions, skills, tools, and output contracts. A budget system bounds resource consumption. The two engines can be composed: a DAG node can contain a delegation loop.

**State:** A Python dictionary (`Dict[str, Any]`) that accumulates agent outputs. Each agent writes to `state[agent_name]`. Downstream agents read from their dependencies' state entries. State can be persisted to disk between runs.

## The 7-Layer Model

### Layer 0: Orchestration

The foundation. Defines how agents are orchestrated. Every AWP workflow must implement this layer.

AWP supports two orchestration engines:

- **DAG engine** (`engine: dag`) -- Static graph of agents with `depends_on` edges. Agents run in topological order. Best for predictable pipelines with known steps.
- **Delegation Loop engine** (`engine: delegation_loop`) -- A manager agent dynamically spawns ephemeral workers at runtime. Workers are defined by delegation envelopes, not static config files. Best for open-ended tasks where steps emerge during execution. Requires a budget system (A2+).

Key manifest sections: `project`, `graph` (DAG) or `delegation_loop` (loop), `execution`.

DAG execution modes:
- **sequential** -- agents run one at a time in topological order.
- **parallel** -- independent agents (no mutual dependencies) run concurrently.
- **conditional** -- agents run based on runtime conditions evaluated from state.

Delegation loop decisions:
- **DELEGATE** -- Manager generates delegation envelopes for ephemeral workers.
- **COMPLETE** -- Task is done; return the final result.
- **FAIL** -- Task cannot be completed; return error with partial results.

Error handling options: `stop` (halt on first error), `continue` (skip failed agent), `retry` (retry with backoff).

### Layer 1: State

Manages how data flows between agents and persists across runs. The `state` section controls persistence, sharing strategy (full, selective, isolated), required fields, and auto-injected values.

State sharing works through `share_output` in the graph definition. When agent A lists `[summary, findings]` in share_output, and agent B has `depends_on: [A]`, agent B receives those fields in its context.

### Layer 2: Communication

Adds a message bus for agent-to-agent messaging outside the DAG flow. Agents use `agent.send_message` and `agent.list_messages` MCP tools to exchange messages.

The `communication` section defines the bus type and channels. Channels can be `direct` (point-to-point) or `broadcast` (one-to-many). Messages are stored per-run and cleared on completion.

### Layer 3: Memory

Provides cross-session persistence through two tiers:

- **Long-term memory (MEMORY.md):** Curated facts, preferences, and policies injected into every agent's prompt. Updated via `memory.write` (target: long_term) or `memory.curate` (LLM-based curation from daily logs).
- **Working memory (daily logs):** Append-only daily notes in `workspace/memory/YYYY-MM-DD.md`. Written automatically after each agent run or manually via `memory.write` (target: daily).

Memory tools: `memory.read`, `memory.write`, `memory.search`, `memory.curate`.

### Layer 4: Observability

Structured logging, distributed tracing, and metrics collection.

- **Tracing:** Every log entry includes trace context (`run_id`, `project`, `agent`). Exported as JSONL.
- **Metrics:** Performance data collected at configurable intervals.
- **Logging:** JSON-structured logs with rotation. Separate files for app logs, exceptions, state events, tool calls.

### Layer 5: Governance

Security and operational controls for production deployments.

- **Audit:** Logs tool calls, state mutations, and optionally LLM prompts.
- **Rate limiting:** Caps tool calls and LLM calls per minute per agent.
- **Circuit breaker:** Trips after N consecutive failures, enters recovery mode with limited calls, then resets.

### Layer 6: Extension

Custom capabilities added to a workflow:

- **Custom MCP tools:** Python files in `{workflow_dir}/mcp/` using FastMCP decorators. Auto-discovered and registered.
- **Project-level skills:** Markdown files in `{workflow_dir}/skills/` injected into all agents' system prompts.
- **Preprocessors:** Data extraction logic in `workflow/preprocessor/preprocessor.py`.
- **Hooks:** Pre/post-execution callbacks defined in the manifest.

## Agent Anatomy

Each agent lives in `{workflow_dir}/agents/{agent_id}/` and contains:

| File | Required | Purpose |
|------|----------|---------|
| `agent.awp.yaml` | Yes | Agent configuration (LLM, tools, memory, etc.) |
| `agent.py` | Yes | Agent class implementation |
| `workflow/instructions/SYSTEM_PROMPT.md` | Yes | LLM system prompt |
| `workflow/prompt/00_INTRO.md` | Yes | Task introduction prompt |
| `workflow/output_schema/output_schema.json` | Yes | JSON Schema for output validation |
| `workflow/output_schema_desc/output_schema_desc.json` | Yes | Human-readable field descriptions |
| `workflow/preprocessor/preprocessor.py` | No | Data preprocessing logic |
| `workflow/skills/` | No | Agent-specific skill files |

## Agent Execution Flow

1. Load configuration from `agent.awp.yaml`.
2. Load workflow artifacts (prompts, schemas, skills) via the loader.
3. Check if the agent should skip (no new data since last run).
4. Build context: preprocessed data + memory + inter-agent messages + upstream outputs.
5. Gather images for vision (if enabled).
6. Call the LLM with messages, tool definitions, and images.
7. If LLM returns tool calls, execute them via the MCP registry and feed results back.
8. Parse the JSON response and validate against the output schema.
9. Update `state[agent_name]` with the result.

## MCP Tool System

Tools are registered in a global registry and exposed to agents based on their `tools.allowed` configuration. Each tool follows a standard interface:

- **Input:** Named parameters defined in the tool's schema.
- **Output:** `{ok: bool, status: int, data: dict, error: str, log: str}`.

Built-in tool namespaces: `web`, `http`, `file`, `shell`, `agent`, `memory`, `arithmetic`.

Custom tools are defined using FastMCP decorators (`@app.tool("namespace.action")`) and placed in `{workflow_dir}/mcp/`. They are auto-discovered at project load time.

## Output Schema Contract

Every agent must produce JSON output conforming to its `output_schema.json`. Key requirements:

- Must be valid JSON Schema draft-07.
- Root type must be `"object"`.
- Must include a `confidence` field (number, 0.0 to 1.0).
- Fields listed in `share_output` must be present as properties in the schema.
- A companion `output_schema_desc.json` provides human-readable descriptions for each field.

## Autonomy Levels

Autonomy levels measure HOW AUTONOMOUS the workflow is. Communication, memory, and observability are cross-cutting features available at any level.

| Level | Name | Key Features |
|-------|------|--------------|
| A0 | Prescribed | Static DAG, predefined agents, fixed tools. |
| A1 | Adaptive | Conditional execution, loops, fan-out, multi-agent DAG. |
| A2 | Delegating | Manager spawns workers dynamically. Budget required. |
| A3 | Self-Tooling | Agents create tools and skills at runtime. Safety envelope required. |
| A4 | Self-Organizing | Recursive delegation, budget distribution. Observability required. |

Cross-cutting (all levels): Communication, Memory, Observability, Security.
