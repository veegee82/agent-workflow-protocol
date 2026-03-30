# OpenClaw + AWP: Better Together

> **What if your personal AI assistant could orchestrate entire multi-agent workflows — safely, within budget, with validated results — triggered from any messaging platform?**

[OpenClaw](https://github.com/openclaw/openclaw) is a self-hosted AI assistant gateway connecting 25+ messaging platforms. [AWP (Agent Workflow Protocol)](https://github.com/agent-workflow-protocol) is a declarative multi-agent orchestration standard. They solve orthogonal problems — and together, they unlock capabilities neither can achieve alone.

---

## 1. Why Integrate AWP into OpenClaw?

<p align="center">
  <img src="diagrams/07-integration-benefits.svg" alt="What AWP Brings to OpenClaw" width="100%"/>
</p>

OpenClaw excels at **reaching users** — WhatsApp, Telegram, Slack, Discord, Signal, iMessage, Teams, and 19 more channels. But when a user sends a complex multi-step request, OpenClaw routes it to a single agent that handles everything in one LLM call. There is no task decomposition, no budget control, and no quality validation.

AWP fills exactly this gap. Here is what becomes possible when AWP serves as OpenClaw's orchestration backend:

### 1.1 Multi-Agent Task Decomposition

**Without AWP**: User asks "analyze our competitors and write a report" in Slack. OpenClaw's agent tries to do everything in one shot — research, analysis, and writing — in a single context window.

**With AWP**: OpenClaw classifies the task as complex and dispatches it to an AWP delegation loop. AWP's manager agent decomposes it into specialized workers:

```
User (Slack) → OpenClaw Gateway → AWP Runtime
                                    ├── Worker 1: Web Researcher (web.search, confidence: 0.92)
                                    ├── Worker 2: Data Analyst (code.execute, confidence: 0.88)
                                    └── Worker 3: Report Writer (file.write, confidence: 0.95)
                                  → Synthesized report → OpenClaw → Slack thread
```

Each worker uses the right model for the job (cheap/fast for data collection, expensive/capable for analysis), and the manager only accepts results above confidence thresholds.

### 1.2 Budget Enforcement — No More Runaway Costs

OpenClaw has **no budget system**. A complex task could consume unlimited tokens, run forever, or spawn unbounded subagents. AWP adds 5-dimensional hard limits:

| Budget Dimension | What It Prevents | Example Limit |
|-----------------|------------------|---------------|
| `max_total_tokens` | Unbounded LLM costs | 500,000 tokens |
| `max_wall_time` | Tasks that never finish | 300 seconds |
| `max_total_workers` | Subagent explosion | 20 workers |
| `max_loops` | Infinite delegation cycles | 15 iterations |
| `max_tool_calls` | Runaway tool usage | 200 calls |

The workflow **hard-stops** when any dimension is exhausted. The manager cannot override these limits. This is critical for a personal assistant where unexpected costs hit the user's wallet.

### 1.3 Quality Validation and Stall Detection

OpenClaw returns LLM output as-is. AWP adds two layers of quality control:

- **Tier 1 (Free)**: Every worker result must be a dict with a `confidence` float in [0,1]. Malformed outputs are rejected instantly.
- **Tier 2 (LLM Semantic)**: A validation LLM checks whether the result actually addresses the task. Skipped when confidence is high (>= 0.95) or budget is low (<= 10%) to save tokens.

**Stall detection** monitors confidence deltas and output similarity across iterations. If a worker keeps producing similar low-confidence results, AWP warns once, then stops — preventing wasted compute on tasks that are going nowhere.

### 1.4 Portable Workflows as OpenClaw Skills

AWP workflows are declarative YAML manifests, packaged as `.awp.zip` bundles. This means:

- **Shareable**: A "competitive analysis" workflow can be shared as a file, not code
- **Versioned**: Workflows declare `awp: "1.0"` and can be validated against the spec
- **Runtime-agnostic**: The same `.awp.zip` runs on any conforming AWP runtime
- **Publishable to ClawHub**: AWP workflows can be published as OpenClaw skills via the [ClawHub adapter](../skill/adapters/clawhub.md)

### 1.5 Cross-Agent State Sharing

OpenClaw agents work in isolated sessions — they cannot share intermediate results. AWP provides explicit, field-level state sharing:

```yaml
state:
  sharing:
    strategy: selective
    rules:
      - from: researcher
        to: analyst
        fields: [findings, raw_data]
      - from: analyst
        to: writer
        fields: [charts, summary]
    never_share: [api_keys, raw_api_responses]
```

This enables multi-step pipelines where each agent builds on the previous agent's work — something impossible with OpenClaw's isolated session model.

---

## 2. Integration Architecture

<p align="center">
  <img src="diagrams/05-integration-scenario.svg" alt="Integration Scenario" width="100%"/>
</p>

### 2.1 How It Works

1. **User sends message** via WhatsApp / Telegram / Slack / any channel
2. **OpenClaw Gateway** routes the message to the appropriate agent persona
3. **Routing agent classifies** the task complexity:
   - **Simple query** (weather, quick lookup) → Direct LLM response via OpenClaw's Pi agent
   - **Complex multi-step task** (research, analysis, code review) → Dispatch to AWP runtime
4. **AWP decomposes** the task into a DAG or delegation loop with specialized workers
5. **Workers execute** with budget enforcement, validation, and stall detection
6. **Synthesized result** flows back to the OpenClaw agent
7. **Reply delivered** via the original messaging channel

### 2.2 Each System Plays to Its Strengths

| Responsibility | Handled By | Why |
|---------------|-----------|-----|
| User interface (25+ channels) | OpenClaw | Purpose-built for multi-platform messaging |
| Device integration (voice, camera, location) | OpenClaw | Native mobile node support |
| Model failover and auth rotation | OpenClaw | 35+ providers with cooldown tracking |
| Browser automation | OpenClaw | CDP-based, full browser control |
| Task decomposition | AWP | Formal DAG + delegation loop engines |
| Budget enforcement | AWP | 5D hard limits the manager cannot override |
| Quality validation | AWP | 2-tier (deterministic + LLM semantic) |
| Stall detection | AWP | Confidence delta + output similarity |
| Cross-agent state sharing | AWP | Explicit `share_output` with field-level control |
| Workflow portability | AWP | Declarative YAML, `.awp.zip` bundles |

### 2.3 Concrete Use Cases

**Research Pipeline via Slack**: "Analyze our Q4 competitors" triggers an AWP delegation loop — web researcher, data analyst, report writer — each validated, budget-bounded. The synthesized report arrives back in the Slack thread.

**Code Review via WhatsApp**: "Review PR #42" from your phone triggers an AWP DAG — code reader, security auditor, style checker — each producing confidence scores. The merged review is delivered to WhatsApp.

**Scheduled Data Pipeline via Telegram**: OpenClaw's cron system triggers a daily AWP workflow — data fetcher → analyst → chart generator → summary writer. Results are posted to a Telegram channel every morning.

**Dynamic Tool Creation via Discord**: A user asks for a custom analysis. AWP's A3+ agents create Python tools at runtime, use them for the analysis, and return validated results — all within the safety envelope.

---

## 3. Quick Comparison

| Dimension | **AWP** | **OpenClaw** |
|-----------|---------|--------------|
| **Core paradigm** | Declarative workflow orchestration protocol | Personal AI assistant gateway |
| **Primary question** | *How do I coordinate multiple agents for complex tasks?* | *How do I reach my AI assistant from any messaging platform?* |
| **Language** | Python 3.10+ | TypeScript/ESM (Node 22+) |
| **Architecture** | Two orchestration engines (DAG + Delegation Loop) | WebSocket Gateway daemon + embedded Pi agent |
| **Agent model** | Ephemeral workers spawned by managers | Persistent agent personas with isolated workspaces |
| **Workflow format** | Declarative YAML manifests | Imperative JSON5 configuration |
| **Autonomy model** | Formal 5-tier spectrum (A0-A4) | Informal 3-tier capability model |
| **Packaging** | Self-contained `.awp.zip` bundles | Gateway daemon + client apps |
| **Channel support** | None (runtime-agnostic) | 25+ messaging platforms |
| **Stars** | Growing | ~340k |

<p align="center">
  <img src="diagrams/01-architecture-overview.svg" alt="Architecture Overview" width="100%"/>
</p>

---

## 4. Summary Assessment

| Dimension | Winner | Margin |
|-----------|--------|--------|
| **Multi-agent orchestration** | AWP | Large — fundamentally different capability |
| **Messaging integration** | OpenClaw | Large — AWP has none |
| **Budget/safety controls** | AWP | Large — 5D enforcement vs. none |
| **Model management** | OpenClaw | Medium — 35+ providers with failover |
| **Memory system** | Tie | Different strengths (sharing vs. search) |
| **Security model** | Tie | Different threat models |
| **Developer experience** | OpenClaw | Medium — production-ready daily driver |
| **Protocol formalism** | AWP | Large — versioned spec with 26 rules |
| **Portability** | AWP | Large — `.awp.zip` vs. single runtime |
| **Device/hardware** | OpenClaw | Large — AWP has no device concept |
| **Context management** | Tie | Different approaches, both effective |

**The most interesting question is not "which is better?" but "how do they compose?"** — a Gateway that knows how to reach users on every platform, backed by an orchestration engine that can decompose any task into coordinated, budget-bounded, validated agent workflows.

---

# Technical Deep-Dive

*The sections below provide an exhaustive technical comparison for readers interested in the architectural details.*

## Table of Contents

5. [Architectural Overview](#5-architectural-overview)
6. [Autonomy and Orchestration Models](#6-autonomy-and-orchestration-models)
7. [Agent Runtime Comparison](#7-agent-runtime-comparison)
8. [Workflow Definition and Execution](#8-workflow-definition-and-execution)
9. [Memory Systems](#9-memory-systems)
10. [Security Models](#10-security-models)
11. [Tool Systems](#11-tool-systems)
12. [Communication and Routing](#12-communication-and-routing)
13. [Context Management](#13-context-management)
14. [Observability and Debugging](#14-observability-and-debugging)
15. [Multi-Model Support](#15-multi-model-support)

---

## 5. Architectural Overview

### 5.1 AWP: Layered Protocol Architecture

AWP organizes concerns into **7 semantic layers**, each independently composable:


**Two independent PyPI packages:**
- `awp-core`: Protocol layer (models, parser, validator, CLI)
- `awp-runtime`: Execution layer (engines, LLM client, tools, data API)

### 5.2 OpenClaw: Gateway-Centric Architecture

OpenClaw follows a **hub-and-spoke model** with the Gateway as the central control plane:


**Key components:**
- **Gateway daemon**: Long-lived WebSocket server (`ws://127.0.0.1:18789`)
- **Pi agent runtime**: Embedded agent loop (intake → context → inference → tools → reply → persist)
- **Channel plugins**: Platform-specific adapters for 25+ messaging services
- **Context engine**: Pluggable lifecycle (ingest → assemble → compact → after-turn)

### 5.3 Fundamental Architectural Difference

| Aspect | AWP | OpenClaw |
|--------|-----|----------|
| **Deployment** | Any conforming runtime | Single Gateway per host |
| **Agent lifecycle** | Ephemeral (spawned per task) | Persistent (long-running personas) |
| **Coordination** | Explicit DAG or delegation | Routing-based message dispatch |
| **State flow** | Shared dict with explicit `share_output` | Isolated sessions per agent |
| **Wire protocol** | None (runtime-internal) | WebSocket JSON frames (req/res/event) |
| **Packaging** | `.awp.zip` (portable) | Gateway installation |

---

## 6. Autonomy and Orchestration Models

### 6.1 AWP: Formal A0-A4 Autonomy Spectrum

AWP defines five progressive autonomy levels with strict safety requirements at each tier:

<p align="center">
  <img src="diagrams/02-autonomy-spectrum.svg" alt="Autonomy Spectrum" width="100%"/>
</p>

| Level | Agents | Coordination | Tools | Safety Requirement |
|-------|--------|-------------|-------|--------------------|
| **A0** | 1 | Static DAG | Fixed | Valid manifest |
| **A1** | N | DAG with conditionals, fan-out/in | Fixed | Graph acyclicity |
| **A2** | Dynamic | Manager → workers (delegation loop) | Fixed | **Budget enforcement** |
| **A3** | Dynamic | Delegation + tool creation | Dynamic | **Safety envelope** |
| **A4** | Recursive | Workers become sub-managers | Dynamic | **Observability required** |

**Budget enforcement at A2+** (5 independent dimensions):

```
max_loops:          20       # Manager iterations
max_total_workers:  30       # Ephemeral workers spawned
max_total_tokens:   1,000,000  # LLM token consumption
max_wall_time:      600s     # Elapsed seconds
max_tool_calls:     200      # Tool invocations
max_depth:          5        # Recursive delegation depth
```

The `budget_fraction_remaining` metric tracks the minimum remaining fraction across all dimensions — the workflow stops when **any** resource is exhausted.

### 6.2 OpenClaw: Informal 3-Tier Capability Model

OpenClaw's "autonomy" refers to **permission scope**, not orchestration complexity:

| Tier | Name | Description |
|------|------|-------------|
| **Tier 1** | Read-Only + Draft | Read data, draft messages. Nothing sent without human approval. |
| **Tier 2** | Send on Behalf | Send messages and create events under agent's own identity. |
| **Tier 3** | Proactive | Autonomous cron jobs, standing orders, no per-action approval. |

### 6.3 Autonomy Mapping


**Key insight**: AWP's autonomy spectrum measures **task decomposition complexity** (how sophisticated is the multi-agent coordination?). OpenClaw's tiers measure **permission delegation** (what is the agent allowed to do?). These are orthogonal dimensions.

OpenClaw effectively operates at **AWP A0-A1 level** in orchestration terms: agents receive messages and respond independently, with optional subagent spawning (comparable to simple delegation). There is no DAG-based task decomposition, no multi-agent state sharing, no budget-bounded delegation loops, and no recursive self-organization.

---

## 7. Agent Runtime Comparison

### 7.1 AWP Agent Lifecycle

<p align="center">
  <img src="diagrams/03-delegation-loop.svg" alt="Delegation Loop" width="100%"/>
</p>

**Delegation Envelope** (manager → worker):
```json
{
  "worker_id": "data_analyst_01",
  "instructions": "Analyze Q4 revenue trends...",
  "skills": ["Financial analysis domain knowledge..."],
  "tools_allowed": ["web.search", "code.execute"],
  "output_contract": {
    "required_fields": ["findings", "confidence"],
    "description": "Structured analysis results"
  },
  "codemode": {
    "enabled": true,
    "tool_creation": false
  },
  "temperature": 0.2
}
```

**Two-tier validation after each worker result:**

| Tier | Cost | Checks | Skip Condition |
|------|------|--------|----------------|
| **Tier 1** (Deterministic) | Free | Is dict? Has confidence? In [0,1]? Not pure error? | Never skipped |
| **Tier 2** (LLM Semantic) | Tokens | Does result address the task? Confidence accurate? | confidence >= 0.95 OR budget <= 10% |

**Stall Detection** (two independent channels):

```python
# Channel 1: Confidence delta
delta = confidence_history[-1] - confidence_history[-window]
confidence_stalled = abs(delta) < 0.05

# Channel 2: Output similarity (difflib.SequenceMatcher)
output_stalled = similarity(old_output, new_output) > 0.85

# Decision: 1st warning → "warn", 2nd warning → "stop"
```

### 7.2 OpenClaw Agent Runtime ("Pi Agent")


**Pi Agent Loop Stages:**

1. **Intake**: Message arrives via channel, routed by binding precedence
2. **Context Assembly**: Context engine selects messages fitting token budget
3. **System Prompt Construction**: Identity + skills + memory + authorized senders + time
4. **Inference**: Streaming model call via configured provider
5. **Tool Execution**: `before-tool-call` hooks → policy check → execute → `after-tool-call` hooks
6. **Reply**: Chunked delivery to source channel
7. **Persist**: `afterTurn()`, JSONL transcript append, auto-compaction trigger

### 7.3 Runtime Feature Matrix

| Feature | AWP | OpenClaw |
|---------|-----|----------|
| **Agent spawning** | Dynamic (manager spawns workers at runtime) | Subagent spawn with depth limits |
| **Agent lifespan** | Ephemeral (per-task) | Persistent (long-running) |
| **Budget tracking** | 5-dimensional (tokens, time, workers, loops, tools) | None |
| **Validation** | 2-tier (deterministic + LLM) | None (no output validation) |
| **Stall detection** | Confidence delta + output similarity | None |
| **Output contract** | Required fields + confidence [0,1] | Free-form text |
| **Streaming** | Not primary focus | Native block streaming |
| **Tool call hooks** | Policy-based enforcement | before/after hooks with gating |
| **Context compaction** | Rolling summary + spillover | LLM-based summarization |
| **Device integration** | None | Camera, screen, location, voice |

---

## 8. Workflow Definition and Execution

### 8.1 AWP: Declarative YAML Workflows

AWP workflows are defined as portable YAML manifests:

```yaml
# workflow.awp.yaml
awp: "1.0"
name: market-research-pipeline
version: "1.0.0"
autonomy_level: A2

agents:
  - id: research_analyst
    model: openai/gpt-4o
    system_prompt: "You are a senior market research analyst..."
    output_contract:
      required_fields: [findings, confidence]
  - id: report_writer
    model: openai/gpt-4o
    depends_on: [research_analyst]
    system_prompt: "You are a technical writer..."

orchestration:
  mode: delegation_loop
  delegation:
    budget:
      max_loops: 15
      max_total_workers: 20
      max_total_tokens: 500000
      max_wall_time: 300
    stall_detection:
      enabled: true
      window: 3
      min_confidence_delta: 0.05

state:
  sharing:
    strategy: selective
    rules:
      - from: research_analyst
        to: report_writer
        fields: [findings, summary]
```

**Advanced DAG features:**
- **Fan-out**: `source: "state.context.topics"` splits into parallel agents
- **Fan-in**: `strategy: merge | reduce | first | majority`
- **Conditional execution**: `expr: "state.analyst.decision == 'proceed'"`
- **Subworkflows**: DAG node references an entire sub-workflow

### 8.2 OpenClaw: Imperative JSON5 Configuration

OpenClaw uses JSON5 config files for agent setup and routing (not workflow definition):

```json5
{
  agents: {
    defaults: {
      model: "anthropic/claude-sonnet-4-20250514",
      systemPrompt: "full"
    },
    list: [
      {
        id: "main",
        displayName: "Assistant",
        workspace: "~/workspace"
      },
      {
        id: "code-reviewer",
        displayName: "Code Reviewer",
        workspace: "~/projects"
      }
    ]
  },
  bindings: [
    {
      match: { channel: "slack", accountId: "*" },
      agentId: "main"
    },
    {
      match: { channel: "telegram", peer: { kind: "direct", id: "12345" } },
      agentId: "code-reviewer"
    }
  ]
}
```

**No workflow graphs**: OpenClaw does not define task pipelines. Each agent operates independently in response to routed messages.

### 8.3 Execution Model Comparison


| Capability | AWP | OpenClaw |
|-----------|-----|----------|
| **Task decomposition** | Native (manager → workers) | Manual (subagent spawn) |
| **Pipeline execution** | DAG with topological sort | Not supported |
| **Dynamic worker creation** | Budget-bounded delegation loop | Depth-limited subagent spawn |
| **State passing between agents** | `share_output` + state dict | None (isolated sessions) |
| **Conditional branching** | DAG expressions | Not supported |
| **Fan-out/fan-in** | Native with merge strategies | Not supported |
| **Recursive delegation** | A4 with budget cascade | Max spawn depth limit |
| **Workflow portability** | `.awp.zip` runs anywhere | Tied to OpenClaw Gateway |

---

## 9. Memory Systems

<p align="center">
  <img src="diagrams/04-memory-comparison.svg" alt="Memory Comparison" width="100%"/>
</p>

### 9.1 AWP: 4-Tier Memory Architecture

**Access control per agent per tier:**
```yaml
memory.access_control:
  research_analyst:
    long_term: read_write
    working: read_write
    episodic: read
  report_writer:
    long_term: read
    working: read_write
```

**State sharing** (explicit field declarations):
```yaml
state:
  sharing:
    strategy: selective
    rules:
      - from: research_analyst
        to: report_writer
        fields: [findings, summary]
    never_share: [raw_api_responses]
    sensitive_fields: [api_keys]
  limits:
    max_state_size_mb: 10.0
    max_field_size_mb: 1.0
    max_fields: 1000
```

### 9.2 OpenClaw: File-Based Memory with Semantic Search


**Search configuration:**
- Hybrid search: vector weight 0.7, text weight 0.3
- Chunking: 400 tokens/chunk, 80 token overlap
- Max results: 6, min score: 0.35
- Temporal decay: optional (half-life 30 days)
- MMR (Maximal Marginal Relevance): optional

**Sync policies:**
- `onSessionStart`, `onSearch`, `watch` (filesystem)
- Delta triggers: 100KB or 50 messages
- Force sync post-compaction

### 9.3 Memory Comparison

| Feature | AWP | OpenClaw |
|---------|-----|----------|
| **Architecture** | 4-tier (long-term → semantic) | File-based + SQLite search |
| **Cross-agent sharing** | Explicit `share_output` rules | None (agent-isolated) |
| **Access control** | Per-agent per-tier permissions | Per-agent workspace isolation |
| **Persistence** | JSON/msgpack checkpoints | JSONL transcripts + Markdown |
| **Semantic search** | Optional vector index | Hybrid (vector + FTS) |
| **Curation** | LLM-based promotion to long-term | Manual Markdown editing |
| **State limits** | 10MB total, 1MB/field, 1000 fields | No formal limits |
| **Inter-agent state** | Shared dict with field-level control | Not supported |

---

## 10. Security Models

<p align="center">
  <img src="diagrams/06-security-comparison.svg" alt="Security Comparison" width="100%"/>
</p>

### 10.1 AWP: Defense-in-Depth with Cross-Cutting Security

**Circuit breaker state machine:**
```yaml
security.circuit_breaker:
  failure_threshold: 5      # Failures before OPEN
  reset_timeout: 60         # Seconds in OPEN before HALF_OPEN
  half_open_max: 2          # Test requests in HALF_OPEN
  monitored_exceptions: [timeout, rate_limit, server_error]
```

**Worker policy enforcement** (manager CANNOT override):
- `sandbox.type`, `sandbox.max_memory_mb`, `sandbox.max_cpu_seconds`
- `rate_limiting.max_llm_calls_per_minute`
- `forbidden_tools` list
- `codemode.max_tools_per_worker`

### 10.2 OpenClaw: Single-Operator Trust Model


**Sandbox modes:**
- `"off"`: No sandboxing (default)
- `"non-main"`: Sandbox non-main sessions only
- `"all"`: Sandbox everything

**Sandbox backends:** Docker, SSH, remote shell

**Tool policy pipeline** (5 layers, evaluated in order):
1. Global `tools.allow/deny`
2. Provider-specific overrides
3. Agent-specific overrides
4. Sandbox policy
5. Subagent depth-based denials

### 10.3 Security Comparison

| Feature | AWP | OpenClaw |
|---------|-----|----------|
| **Trust model** | Least privilege, explicit permissions | Single trusted operator |
| **Agent trust** | Untrusted (output validated) | Untrusted (prompt injection assumed) |
| **Tool control** | `allowed`/`denied` per agent + `forbidden_tools` | 5-layer allow/deny pipeline |
| **Sandboxing** | Docker/venv per execution | Docker/SSH per session or agent |
| **Budget limits** | 5-dimensional hard enforcement | None |
| **Circuit breaker** | Native (failure threshold + recovery) | Not present |
| **Rate limiting** | Per-agent + per-tool | Not present |
| **Secrets** | `security.secrets` with redaction | `secrets.resolve` + credential store |
| **Audit trail** | Hash-chain integrity, 20+ event types | Session transcripts + logs |
| **Multi-tenant** | Runtime-dependent | Explicitly single-tenant |
| **DM/pairing security** | N/A | DM pairing with approval flow |
| **Device auth** | N/A | Token + device pairing + challenge |

---

## 11. Tool Systems

### 11.1 AWP Tool Model

AWP uses **MCP (Model Context Protocol)** for tool definition with namespace enforcement:

```yaml
capabilities:
  tools:
    allowed:
      - web.search
      - file.read
      - code.execute
    denied:
      - shell.execute
    mcp_servers:
      - url: "http://localhost:3000/mcp"
        namespace: "data"
```

**Dynamic tool creation** (A3+):
- Workers generate Python tools at runtime
- Stored in `codemode.tools_created` with full specs
- Secrets injected via `_secrets` dict (not in function signature)
- Pre-defined variables: `_workspace_dir`, `_output_dir`
- Namespace isolation for generated tools

### 11.2 OpenClaw Tool Ecosystem

OpenClaw ships with 30+ built-in tools:

| Category | Tools |
|----------|-------|
| **Execution** | bash (host/Docker/PTY), background processes, script preflight |
| **File system** | read, write, edit, apply_patch (workspace-only guards) |
| **Browser** | CDP-based control, snapshots, profiles |
| **Canvas** | A2UI push/reset, eval, snapshot |
| **Sessions** | spawn, send, list, history |
| **Messaging** | Cross-channel send, polls, reactions, inline buttons |
| **Media** | Camera snap/clip, screen recording, image generation |
| **Search** | Memory search, web search |
| **Device** | Location, voice/TTS |
| **Admin** | Cron, gateway control, PDF reading |

**MCP integration** via mcporter bridge (external, decoupled from core).

### 11.3 Tool System Comparison

| Feature | AWP | OpenClaw |
|---------|-----|----------|
| **Tool standard** | MCP-native | Custom + MCP bridge |
| **Built-in tools** | code.execute, web.search, file.* | 30+ categories |
| **Dynamic creation** | A3+ agents create tools at runtime | Not supported |
| **Namespace isolation** | Per-agent namespaces | Global with allow/deny |
| **Approval flow** | Policy-based (enforced/selectable) | Interactive exec approval |
| **Browser automation** | Not built-in | CDP-based, full browser control |
| **Device tools** | None | Camera, screen, location, voice |

---

## 12. Communication and Routing

### 12.1 AWP: Agent Communication

AWP agents communicate through **state sharing** and **message bus**:


**State sharing strategies:**
- `full`: All outputs visible to all downstream agents
- `selective`: Only declared `share_output` fields exposed
- `isolated`: Agents see only their own state + explicit inputs

### 12.2 OpenClaw: Binding-Based Message Routing

OpenClaw routes messages through a **precedence hierarchy**:


**7-level binding precedence** (most specific wins):
1. Direct peer match
2. Thread parent peer
3. Guild + member roles (Discord)
4. Guild (Discord)
5. Team (Microsoft Teams)
6. Account-specific
7. Channel-wide
8. Default fallback

**Inter-agent communication:**
- `sessions_send`: Message another session (opt-in)
- `agentToAgent` tool: Direct agent-to-agent (default off)
- Subagent announce: Push-based completion events

### 12.3 Communication Comparison

| Feature | AWP | OpenClaw |
|---------|-----|----------|
| **Primary model** | State sharing + message bus | Binding-based routing |
| **Cross-agent data flow** | Explicit `share_output` fields | Isolated (opt-in `sessions_send`) |
| **Routing** | DAG dependency order | 7-level binding precedence |
| **External channels** | None (protocol-level) | 25+ messaging platforms |
| **Threading** | N/A | Native thread binding for subagents |
| **Session model** | Per-workflow run | Per-conversation, DM-scope modes |

---

## 13. Context Management

### 13.1 AWP: Rolling Summary + Context Spillover

AWP manages context growth through two mechanisms:

**Rolling Summary:**
- Recent N iterations (default 3): full results preserved
- Older iterations: summarized as confidence + key findings only
- Stored in `ROLLING_SUMMARY.md` + `rolling_summary.json`
- Injected into manager prompt each iteration

**Context Spillover:**
```
If serialized_length <= per_entry_budget:
    → Inline as JSON in worker prompt

If serialized_length > per_entry_budget:
    → Write to workspace/context/{key}.json
    → Show preview (2,000 chars) + file path in prompt
    → Worker reads full file via _workspace_dir
```

Budget allocation: `total_chars / num_entries` (minimum 4,000 chars per entry).

### 13.2 OpenClaw: Pluggable Context Engine

OpenClaw's context engine has 6 lifecycle methods:


**Compaction details:**
- Multi-part chunked summarization
- Safety margin: 1.2x (20% buffer for token estimation)
- Base chunk ratio: 0.4, minimum: 0.15
- Identifier preservation: `strict` | `custom` | `off`
- Preserves: active tasks, batch progress, last user request, decisions/rationale

**Subagent context management:**
- `prepareSubagentSpawn()`: Prepare context for child agent
- `onSubagentEnded()`: Cleanup child context
- Rollback handles for failed spawns

### 13.3 Context Management Comparison

| Feature | AWP | OpenClaw |
|---------|-----|----------|
| **Strategy** | Rolling summary + file spillover | Pluggable context engine |
| **Compaction** | Windowed summary (recent vs. old) | LLM-based chunked summarization |
| **Large results** | Spill to file, show preview + path | Token budget assembly |
| **Budget tracking** | Per-entry allocation from total | Model-specific token counting |
| **Subagent context** | Delegation envelope (fresh context) | `prepareSubagentSpawn()` lifecycle |
| **Plugin support** | Fixed implementation | Fully pluggable interface |
| **Transcript rewriting** | Not supported | `rewriteTranscriptEntries()` |

---

## 14. Observability and Debugging

### 14.1 AWP: Layer 6 Observability

AWP treats observability as a first-class protocol layer:

```yaml
observability:
  metrics:
    enabled: true
    exporters: [prometheus, otlp]
  tracing:
    enabled: true
    exporter: otlp
    sampling_rate: 1.0
  logging:
    level: INFO
    structured: true
  audit:
    enabled: true
    hash_chain: true
    retention:
      max_age_days: 90
      max_size_mb: 100
```

**Security events** (20+ types): `acl.tool.denied`, `rate_limit.exceeded`, `circuit_breaker.opened`, `secret.leak_prevented`, etc.

**Hash-chain audit trail**: Each entry includes `prev_hash` for tamper detection.

**Budget snapshots**: Real-time visibility into all 5 resource dimensions.

### 14.2 OpenClaw: Operational Logging

- Structured logging via `createSubsystemLogger()`
- Usage tracking and normalization per model
- Model fallback observation logging
- Session transcript events (JSONL)
- `logs.tail` Gateway method for live tailing
- No formal observability layer or distributed tracing standard

### 14.3 Observability Comparison

| Feature | AWP | OpenClaw |
|---------|-----|----------|
| **Formalization** | Dedicated protocol layer (L6) | Operational logging |
| **Distributed tracing** | OpenTelemetry-compatible | Not supported |
| **Metrics export** | Prometheus, OTLP | Usage tracking only |
| **Audit trail** | Hash-chain integrity | Session transcripts |
| **Budget visibility** | Real-time 5D snapshots | None |
| **Security events** | 20+ typed events | Log messages |
| **Live debugging** | Structured logging | `logs.tail` method |

---

## 15. Multi-Model Support

### 15.1 AWP: Model-Agnostic per Agent

```yaml
agents:
  - id: manager
    model: anthropic/claude-sonnet-4-20250514    # Expensive, capable
  - id: worker
    model: openai/gpt-4o-mini              # Cheap, fast
```

- Model specified per agent in YAML manifest
- Tier 2 validation runs on `worker_model` (cheaper) to save budget
- Temperature control per worker via delegation envelope
- No built-in failover (runtime-dependent)

### 15.2 OpenClaw: Sophisticated Model Failover


**35+ LLM providers:** Anthropic (+ Vertex), OpenAI (+ Codex), Google Gemini, DeepSeek, Ollama, Together, Venice, X.AI, Perplexity, HuggingFace, and more.

**Failover features:**
- Candidate chain: primary → fallbacks → allowlist
- Auth profile rotation with cooldown tracking
- Context overflow detection triggers model switch
- Per-session model override via `sessions.patch`
- `FallbackSummaryError` with per-attempt details + `soonestCooldownExpiry`

### 15.3 Model Support Comparison

| Feature | AWP | OpenClaw |
|---------|-----|----------|
| **Provider count** | Runtime-dependent (OpenRouter typical) | 35+ built-in |
| **Failover** | Not in protocol (runtime feature) | Sophisticated chain + cooldown |
| **Per-agent model** | Yes (YAML manifest) | Yes (config + session override) |
| **Auth management** | Environment variables | Multi-profile rotation + cooldown |
| **Context overflow handling** | Context spillover to files | Auto-switch to larger model |

---

*Article generated 2026-03-30. Technical details based on source code analysis of both repositories.*
