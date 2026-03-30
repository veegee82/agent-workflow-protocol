# How to Give OpenClaw a Real Brain

> **OpenClaw has the best nervous system in open source — 25+ channels, 35+ providers, device integration. But it's missing a brain. AWP is that brain.**

[OpenClaw](https://github.com/openclaw/openclaw) is the most connected AI assistant gateway out there. It reaches users on WhatsApp, Telegram, Slack, Discord, Signal, iMessage, Teams, and 19 more platforms. It manages 35+ LLM providers with failover. It integrates cameras, voice, screens, and location. It is, without question, the best open-source **nervous system** for AI assistants.

But a nervous system without a brain can only do one thing: **relay signals.** Every message goes in, one LLM call happens, one response comes back. That is not thinking. That is a reflex.

AWP gives OpenClaw the ability to actually **think** — to decompose problems, coordinate specialists, validate results, control costs, and iterate until the answer is good enough. Here is why that matters, and what it makes possible.

---

## 1. The Problem: OpenClaw Hits a Ceiling on Complex Tasks

OpenClaw routes each message to one agent. That agent makes one LLM call and returns the result. For simple tasks — answering questions, drafting messages, quick lookups — this is perfect.

But the moment a task gets complex, that single-agent architecture breaks down:

| Task | What It Actually Requires | OpenClaw Alone | OpenClaw + AWP |
|------|--------------------------|----------------|----------------|
| "Analyze our competitors and write a strategy report" | Web research, data analysis, chart generation, report writing — 4 distinct skill sets | One agent attempts all in one LLM call. No specialization, no validation, no budget limits. | Manager decomposes into 4 specialized workers. Each validated. Budget-capped at 500K tokens. |
| "Review this PR for security issues, code quality, and performance" | Security auditing, style analysis, performance profiling — 3 independent evaluations | One agent gives a single-pass review. Misses what a specialist would catch. | DAG fans out to 3 parallel reviewers, fans in with merge strategy. Each produces confidence scores. |
| "Build a daily sales dashboard from our API data" | Data fetching, cleaning, statistical analysis, visualization, summary writing — 5-step pipeline | One agent tries to do everything sequentially in one context window. Context overflows. | DAG pipeline: fetcher → cleaner → analyst → visualizer → writer. Each step's output flows to the next. |
| "Research 20 companies and rank them by growth potential" | 20 parallel research tasks, then aggregation and ranking | One agent researches all 20 sequentially. Takes forever. Forgets early results. | Fan-out to 20 parallel research workers. Fan-in with reduce strategy. Budget prevents runaway costs. |
| "Investigate why our API latency spiked, check logs, metrics, and recent deploys" | Log analysis, metrics correlation, deploy diff review, root cause synthesis | One agent tries to juggle all data sources. No structured handoff between analysis phases. | A4 recursive delegation: manager spawns investigators, investigators spawn sub-investigators for specific services. Budget hierarchy prevents explosion. |

**The pattern is clear**: as task complexity grows, a single-agent architecture hits a wall. It cannot specialize, parallelize, validate, or control costs. AWP's orchestration engines exist specifically to solve this.

---

## 2. The Brain: How AWP Turns Reflexes Into Thinking

### 2.1 The Architecture

Think of it like this: OpenClaw is the **nervous system** — it senses (channels), moves (devices), and communicates (messaging). AWP is the **brain** — it plans (task decomposition), delegates (worker agents), evaluates (validation), and learns when to stop (budget + stall detection).

Simple reflexes still go through OpenClaw directly — no overhead for a weather check. But when a task requires actual thinking, AWP takes over.

<p align="center">
  <img src="diagrams/07-integration-benefits.svg" alt="What AWP Brings to OpenClaw" width="100%"/>
</p>

### 2.2 How the Brain Works — Step by Step

**Step 1: Reflex or Thought?**

When a message arrives, the first decision is: does this need thinking? A lightweight classification checks whether the task requires multiple skills, intermediate artifacts, or parallel execution. "What's the weather?" is a reflex. "Analyze our competitors and write a strategy" requires a brain.

**Step 2: The Brain Plans**

For tasks that require thinking, AWP's manager agent plans the approach — like a prefrontal cortex deciding how to tackle a problem:

- **DAG Engine** for tasks with clear structure: "first research, then analyze, then write" — like following a recipe
- **Delegation Loop** for tasks where the plan itself is unclear: "investigate this problem, see what you find, then dig deeper" — like exploring unknown territory

**Step 3: Specialists Execute**

AWP spawns specialized ephemeral workers — each with its own model, tools, instructions, and output contract. This is the key difference: instead of one generalist agent fumbling through everything, you get a team of specialists.

Every worker result passes through the brain's quality filters:
- Deterministic checks (is it structured? does it have a confidence score?) catch garbage instantly
- LLM semantic checks (does this actually answer the question?) catch subtle failures
- Stall detection (is the worker going in circles?) prevents wasted compute

The 5-dimensional budget system ensures the brain never overthinks — hard limits on tokens, time, workers, loops, and tool calls. OpenClaw has no equivalent.

**Step 4: One Clean Result**

The synthesized result flows back to OpenClaw, which delivers it through the original channel. The user sees one polished reply. They do not know — and do not need to know — that a team of 5 specialists collaborated behind the scenes.

### 2.3 What a Brain Makes Possible — Five Real Scenarios

#### Scenario A: Enterprise Research Pipeline via Slack

A product manager types in Slack: *"Compare our pricing against the top 5 competitors in the European market. Include market share data and a recommendation."*

**Without AWP**: OpenClaw's agent produces a surface-level response from a single LLM call. No real data, no structured comparison, no confidence in the numbers.

**With AWP**: The message flows through OpenClaw to an AWP delegation loop:

1. The **manager** analyzes the request and identifies 3 work streams
2. A **market researcher** worker uses `web.search` to find pricing data for each competitor — producing structured findings with sources and a confidence score of 0.87
3. A **data analyst** worker receives the researcher's findings (via `share_output`), cross-references market share databases, runs statistical comparisons, and produces charts — confidence 0.91
4. A **strategy writer** worker receives both the findings and analysis, synthesizes a recommendation with risk assessment — confidence 0.94
5. The manager validates each output (Tier 1: structured? Tier 2: relevant?), detects that the researcher's initial confidence was low, re-dispatches with refined instructions, gets 0.93 on retry
6. Total cost: 180K tokens (budget was 500K). Wall time: 45 seconds (budget was 300s). 4 workers spawned (budget was 20).

The formatted report arrives in the Slack thread. The product manager has a structured comparison they can take into their next meeting — not a generic LLM ramble.

#### Scenario B: Multi-Stage Code Review via WhatsApp

A developer on the go sends from WhatsApp: *"Review PR #247 — focus on security and performance."*

**Without AWP**: OpenClaw's agent reads the PR diff (if it even has access) and provides a single-pass review. It cannot deeply analyze both security and performance in one context window — one or both will be shallow.

**With AWP**: AWP sets up a parallel DAG:

1. **Code reader** worker fetches the full PR diff and file context
2. Three parallel workers receive the code reader's output:
   - **Security auditor**: checks for injection vulnerabilities, auth bypasses, secret leaks — confidence 0.96
   - **Performance profiler**: identifies N+1 queries, unnecessary allocations, missing caching — confidence 0.89
   - **Architecture reviewer**: checks for design pattern violations, API contract breaks — confidence 0.92
3. **Synthesis writer** receives all three reviews, merges them into a structured report with severity ratings
4. Fan-in strategy: `merge` (combine all findings, deduplicate)

The developer gets a comprehensive review on their phone — three specialist perspectives merged into one actionable document. Each finding has a confidence score so they know what to prioritize.

#### Scenario C: Automated Daily Intelligence Brief via Telegram

An executive's OpenClaw cron job fires every morning at 7:00 AM, triggering an AWP workflow:

1. **News scanner** worker searches for industry news, regulatory changes, and competitor announcements from the last 24 hours
2. **Relevance filter** worker receives all articles and scores each one by relevance to the company's strategic priorities (loaded from long-term memory)
3. **Impact analyst** worker takes the top 10 most relevant items and assesses business impact — categorized as opportunity, threat, or informational
4. **Brief writer** worker synthesizes everything into a 500-word executive summary with action items

Every morning, a crisp intelligence brief appears in the executive's Telegram. The pipeline runs within a budget of 200K tokens and 120 seconds. If the news scanner finds nothing relevant, the workflow short-circuits via conditional execution — no wasted compute.

#### Scenario D: Recursive Investigation via Discord

A DevOps engineer messages Discord: *"Our API latency spiked 3x in the last hour. Figure out why."*

This is an A4 (recursive delegation) task — the investigation itself is unpredictable:

1. **Investigation manager** spawns three parallel investigators:
   - **Log analyst** searches recent application logs for errors and anomalies
   - **Metrics analyst** queries Prometheus/Grafana for correlated metric changes
   - **Deploy analyst** checks recent deployments and config changes
2. The **log analyst** discovers unusual database connection timeouts, but needs more detail. As an A4 worker-turned-sub-manager, it spawns two sub-investigators:
   - **DB connection profiler** analyzes connection pool metrics
   - **Query pattern analyzer** looks for new slow queries
3. The **deploy analyst** finds a config change that reduced the connection pool size — confidence 0.97
4. The investigation manager synthesizes: *"Root cause: connection pool size was reduced from 50 to 10 in deployment #1842 at 14:23 UTC. This caused connection starvation under normal load, resulting in database timeouts that cascaded into API latency."*

Budget hierarchy ensures the recursive investigation stays bounded: the top-level manager has 1M tokens, each investigator gets a fraction, and sub-investigators get a fraction of that. The total cost is predictable even though the investigation depth was emergent.

#### Scenario E: Creative Multi-Media Production via iMessage

A marketing lead sends from iMessage: *"Create social media content about our new product launch — I need copy for Twitter, LinkedIn, and Instagram, plus a blog post."*

**Without AWP**: OpenClaw generates all four pieces of content in one LLM call. They sound similar, lack platform-specific optimization, and nobody reviewed them.

**With AWP**: A delegation loop with platform-specialized workers:

1. **Product researcher** worker reviews the product documentation and extracts key features, differentiators, and target audience segments — shares output with all writers
2. **Twitter copywriter** worker creates 5 tweet variations optimized for engagement (character limits, hashtag strategy, hook patterns) — confidence 0.91
3. **LinkedIn writer** worker produces professional thought-leadership content with industry context — confidence 0.88
4. **Instagram copywriter** worker creates visual-first captions with emoji strategy and CTA optimization — confidence 0.93
5. **Blog writer** worker produces a 1,000-word launch announcement with SEO considerations — confidence 0.90
6. **Editorial reviewer** (Tier 2 validation) checks brand voice consistency across all pieces and flags the LinkedIn post for being too generic — manager re-dispatches with refined instructions
7. Final LinkedIn version: confidence 0.94

Five pieces of content, each optimized for its platform, all brand-consistent, all reviewed. The marketing lead gets them all in one iMessage reply, ready to schedule.

---

## 3. Reflex vs. Brain: The Complexity Gap

| Dimension | Reflex (OpenClaw Alone) | Brain (OpenClaw + AWP) | What Changes |
|-----------|------------------------|----------------------|--------------|
| **Agents per task** | 1 (+ depth-limited subagents) | Unlimited (budget-bounded) | From single-threaded to parallel teams |
| **Task decomposition** | Manual — user must break down tasks | Automatic — manager agent plans it | User describes the goal, not the steps |
| **Specialization** | One agent, one system prompt | N workers, each a domain expert | Specialists instead of a generalist |
| **Quality assurance** | None — output returned as-is | 2-tier validation + stall detection | Failures caught before the user sees them |
| **Cost control** | None — unbounded token consumption | 5D budget system with hard stops | Predictable costs, even for complex tasks |
| **State flow** | Isolated sessions — no sharing | Explicit field-level sharing rules | Pipelines become possible |
| **Execution patterns** | Request → Response | DAG, Delegation Loop, Recursive (A4) | From chat to orchestration |
| **Failure recovery** | Retry the entire task | Re-dispatch individual workers | Surgical recovery, not full restart |
| **Context capacity** | Single context window (overflow → compaction) | Rolling summary + file spillover per worker | Handle tasks larger than any context window |
| **Workflow reuse** | Skills (JSON5 config) | `.awp.zip` bundles — portable, versioned | Complex workflows become shareable artifacts |

---

## 4. Nervous System + Brain: Who Does What

<p align="center">
  <img src="diagrams/05-integration-scenario.svg" alt="Integration Architecture" width="100%"/>
</p>

| Responsibility | Handled By | Why This System |
|---------------|-----------|-----------------|
| User interaction across 25+ channels | OpenClaw | Purpose-built gateway with channel plugins for WhatsApp, Telegram, Slack, Discord, Signal, iMessage, Teams, Matrix, IRC, and more |
| Device integration (voice, camera, screen, location) | OpenClaw | Native mobile node architecture with device-local action execution |
| Model failover with 35+ providers | OpenClaw | Auth profile rotation, cooldown tracking, context overflow detection |
| Browser automation | OpenClaw | CDP-based full browser control with sandbox isolation |
| DM pairing and sender authentication | OpenClaw | Approval flow for unknown senders, per-device pairing |
| Cron scheduling and webhooks | OpenClaw | Built-in job scheduler triggers both simple and complex tasks |
| Multi-agent task decomposition | AWP | Two formal engines: DAG for structured tasks, Delegation Loop for emergent decomposition |
| 5-dimensional budget enforcement | AWP | Hard limits on tokens, time, workers, loops, and tool calls that the manager cannot override |
| 2-tier output validation | AWP | Deterministic structural checks (free) + LLM semantic review (conditional) |
| Stall detection and recovery | AWP | Confidence delta monitoring + output similarity tracking across iterations |
| Cross-agent state sharing | AWP | Explicit `share_output` rules with field-level control and sensitivity annotations |
| Dynamic tool creation at runtime | AWP | A3+ workers generate Python tools on the fly within a safety envelope |
| Workflow portability and versioning | AWP | Declarative YAML manifests packaged as `.awp.zip` bundles |
| Recursive delegation with budget hierarchy | AWP | A4 workers become sub-managers, each inheriting a fraction of the parent budget |
| Hash-chain audit trail | AWP | Tamper-proof event logging with 20+ security event types |

---

## 5. Quick Comparison Table

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

## 6. Summary Assessment

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

**OpenClaw without AWP is an incredibly well-connected assistant that can only do one thing at a time. OpenClaw with AWP is a thinking machine** — it plans, delegates, validates, and iterates, all while staying within budget, all delivered through the channel the user already lives in.

---

# Technical Deep-Dive

*The sections below provide an exhaustive technical comparison for readers interested in the architectural details.*

## Table of Contents (Deep-Dive)

7. [Architectural Overview](#7-architectural-overview)
8. [Autonomy and Orchestration Models](#8-autonomy-and-orchestration-models)
9. [Agent Runtime Comparison](#9-agent-runtime-comparison)
10. [Workflow Definition and Execution](#10-workflow-definition-and-execution)
11. [Memory Systems](#11-memory-systems)
12. [Security Models](#12-security-models)
13. [Tool Systems](#13-tool-systems)
14. [Communication and Routing](#14-communication-and-routing)
15. [Context Management](#15-context-management)
16. [Observability and Debugging](#16-observability-and-debugging)
17. [Multi-Model Support](#17-multi-model-support)

---

## 7. Architectural Overview

### 7.1 AWP: Layered Protocol Architecture

AWP organizes concerns into **7 semantic layers**, each independently composable:


**Two independent PyPI packages:**
- `awp-core`: Protocol layer (models, parser, validator, CLI)
- `awp-runtime`: Execution layer (engines, LLM client, tools, data API)

### 7.2 OpenClaw: Gateway-Centric Architecture

OpenClaw follows a **hub-and-spoke model** with the Gateway as the central control plane:


**Key components:**
- **Gateway daemon**: Long-lived WebSocket server (`ws://127.0.0.1:18789`)
- **Pi agent runtime**: Embedded agent loop (intake → context → inference → tools → reply → persist)
- **Channel plugins**: Platform-specific adapters for 25+ messaging services
- **Context engine**: Pluggable lifecycle (ingest → assemble → compact → after-turn)

### 7.3 Fundamental Architectural Difference

| Aspect | AWP | OpenClaw |
|--------|-----|----------|
| **Deployment** | Any conforming runtime | Single Gateway per host |
| **Agent lifecycle** | Ephemeral (spawned per task) | Persistent (long-running personas) |
| **Coordination** | Explicit DAG or delegation | Routing-based message dispatch |
| **State flow** | Shared dict with explicit `share_output` | Isolated sessions per agent |
| **Wire protocol** | None (runtime-internal) | WebSocket JSON frames (req/res/event) |
| **Packaging** | `.awp.zip` (portable) | Gateway installation |

---

## 8. Autonomy and Orchestration Models

### 8.1 AWP: Formal A0-A4 Autonomy Spectrum

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

### 8.2 OpenClaw: Informal 3-Tier Capability Model

OpenClaw's "autonomy" refers to **permission scope**, not orchestration complexity:

| Tier | Name | Description |
|------|------|-------------|
| **Tier 1** | Read-Only + Draft | Read data, draft messages. Nothing sent without human approval. |
| **Tier 2** | Send on Behalf | Send messages and create events under agent's own identity. |
| **Tier 3** | Proactive | Autonomous cron jobs, standing orders, no per-action approval. |

### 8.3 Autonomy Mapping


**Key insight**: AWP's autonomy spectrum measures **task decomposition complexity** (how sophisticated is the multi-agent coordination?). OpenClaw's tiers measure **permission delegation** (what is the agent allowed to do?). These are orthogonal dimensions.

OpenClaw effectively operates at **AWP A0-A1 level** in orchestration terms: agents receive messages and respond independently, with optional subagent spawning (comparable to simple delegation). There is no DAG-based task decomposition, no multi-agent state sharing, no budget-bounded delegation loops, and no recursive self-organization.

---

## 9. Agent Runtime Comparison

### 9.1 AWP Agent Lifecycle

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

### 9.2 OpenClaw Agent Runtime ("Pi Agent")


**Pi Agent Loop Stages:**

1. **Intake**: Message arrives via channel, routed by binding precedence
2. **Context Assembly**: Context engine selects messages fitting token budget
3. **System Prompt Construction**: Identity + skills + memory + authorized senders + time
4. **Inference**: Streaming model call via configured provider
5. **Tool Execution**: `before-tool-call` hooks → policy check → execute → `after-tool-call` hooks
6. **Reply**: Chunked delivery to source channel
7. **Persist**: `afterTurn()`, JSONL transcript append, auto-compaction trigger

### 9.3 Runtime Feature Matrix

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

## 10. Workflow Definition and Execution

### 10.1 AWP: Declarative YAML Workflows

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

### 10.2 OpenClaw: Imperative JSON5 Configuration

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

### 10.3 Execution Model Comparison


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

## 11. Memory Systems

<p align="center">
  <img src="diagrams/04-memory-comparison.svg" alt="Memory Comparison" width="100%"/>
</p>

### 11.1 AWP: 4-Tier Memory Architecture

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

### 11.2 OpenClaw: File-Based Memory with Semantic Search


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

### 11.3 Memory Comparison

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

## 12. Security Models

<p align="center">
  <img src="diagrams/06-security-comparison.svg" alt="Security Comparison" width="100%"/>
</p>

### 12.1 AWP: Defense-in-Depth with Cross-Cutting Security

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

### 12.2 OpenClaw: Single-Operator Trust Model


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

### 12.3 Security Comparison

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

## 13. Tool Systems

### 13.1 AWP Tool Model

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

### 13.2 OpenClaw Tool Ecosystem

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

### 13.3 Tool System Comparison

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

## 14. Communication and Routing

### 14.1 AWP: Agent Communication

AWP agents communicate through **state sharing** and **message bus**:


**State sharing strategies:**
- `full`: All outputs visible to all downstream agents
- `selective`: Only declared `share_output` fields exposed
- `isolated`: Agents see only their own state + explicit inputs

### 14.2 OpenClaw: Binding-Based Message Routing

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

### 14.3 Communication Comparison

| Feature | AWP | OpenClaw |
|---------|-----|----------|
| **Primary model** | State sharing + message bus | Binding-based routing |
| **Cross-agent data flow** | Explicit `share_output` fields | Isolated (opt-in `sessions_send`) |
| **Routing** | DAG dependency order | 7-level binding precedence |
| **External channels** | None (protocol-level) | 25+ messaging platforms |
| **Threading** | N/A | Native thread binding for subagents |
| **Session model** | Per-workflow run | Per-conversation, DM-scope modes |

---

## 15. Context Management

### 15.1 AWP: Rolling Summary + Context Spillover

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

### 15.2 OpenClaw: Pluggable Context Engine

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

### 15.3 Context Management Comparison

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

## 16. Observability and Debugging

### 16.1 AWP: Layer 6 Observability

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

### 16.2 OpenClaw: Operational Logging

- Structured logging via `createSubsystemLogger()`
- Usage tracking and normalization per model
- Model fallback observation logging
- Session transcript events (JSONL)
- `logs.tail` Gateway method for live tailing
- No formal observability layer or distributed tracing standard

### 16.3 Observability Comparison

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

## 17. Multi-Model Support

### 17.1 AWP: Model-Agnostic per Agent

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

### 17.2 OpenClaw: Sophisticated Model Failover


**35+ LLM providers:** Anthropic (+ Vertex), OpenAI (+ Codex), Google Gemini, DeepSeek, Ollama, Together, Venice, X.AI, Perplexity, HuggingFace, and more.

**Failover features:**
- Candidate chain: primary → fallbacks → allowlist
- Auth profile rotation with cooldown tracking
- Context overflow detection triggers model switch
- Per-session model override via `sessions.patch`
- `FallbackSummaryError` with per-attempt details + `soonestCooldownExpiry`

### 17.3 Model Support Comparison

| Feature | AWP | OpenClaw |
|---------|-----|----------|
| **Provider count** | Runtime-dependent (OpenRouter typical) | 35+ built-in |
| **Failover** | Not in protocol (runtime feature) | Sophisticated chain + cooldown |
| **Per-agent model** | Yes (YAML manifest) | Yes (config + session override) |
| **Auth management** | Environment variables | Multi-profile rotation + cooldown |
| **Context overflow handling** | Context spillover to files | Auto-switch to larger model |

---

*Article generated 2026-03-30. Technical details based on source code analysis of both repositories.*
