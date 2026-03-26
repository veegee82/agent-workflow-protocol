<p align="center">
  <img src="assets/awp_logo.png" alt="AWP Logo" width="200" />
</p>

<h1 align="center">AWP - Agent Workflow Protocol</h1>

<p align="center">
  <strong>An open standard for multi-agent workflows -- from scripted pipelines to self-organizing teams.</strong><br/>
  Declarative. Runtime-agnostic. Portable.
</p>

<p align="center">
  <a href="docs/">Docs</a> &middot;
  <a href="primer/quickstart.md">Quickstart</a> &middot;
  <a href="examples/">Examples</a> &middot;
  <a href="spec/versions/1.0/spec.md">Specification</a> &middot;
  <a href="skill/SKILL.md">AWP Skill</a> &middot;
  <a href="https://clawhub.ai/veegee82/awp-workflow-builder">ClawHub</a>
</p>

---

## The Problem

Building multi-agent systems today means choosing a framework and being
locked into it. Every platform -- LangGraph, CrewAI, AutoGen, custom
solutions -- uses its own format. Moving a workflow means rewriting everything.

Existing standards each solve a piece:

| Standard | Covers | Misses |
|----------|--------|--------|
| MCP | Tool access for LLMs | No agents, no orchestration, no state |
| A2A | Agent communication | No orchestration, no memory, no tools |
| OpenAPI | HTTP API description | No agent concept, no DAG structure |

**AWP fills the gap.** One portable format that describes the complete
multi-agent system -- and lets you choose how autonomous that system should be.

---

## The Big Idea: Autonomy as a Spectrum

Most agent frameworks force a choice: either you hardcode every step (safe but
rigid), or you give agents full freedom (powerful but unpredictable). AWP
rejects this binary. Instead, it treats **autonomy as a spectrum** -- and lets
you dial it to exactly the level your task requires.

```
  A0 Prescribed ──── A1 Adaptive ──── A2 Delegating ──── A3 Self-Tooling ──── A4 Self-Organizing
  │                  │                │                  │                    │
  │ You define       │ Agents react   │ A manager agent  │ Agents create      │ Agents organize
  │ every step.      │ to results:    │ decides what     │ their own tools    │ sub-teams, split
  │ Fixed graph,     │ skip, repeat,  │ workers to       │ and domain         │ budgets, delegate
  │ fixed agents,    │ branch based   │ spawn, what      │ knowledge at       │ recursively.
  │ fixed tools.     │ on conditions. │ instructions     │ runtime.           │ Full autonomy
  │                  │                │ to give them.    │                    │ within bounds.
  "Do exactly this"  "React to this"  "Figure this out"  "Build what          "Run the team"
                                                          you need"
```

**The key insight:** Features like memory, communication, observability, and
security are not levels -- they are capabilities available at every autonomy
level. A simple A0 pipeline can have full observability. A complex A4
self-organizing system must have it.

### What Each Level Means

**A0 Prescribed** -- You define a DAG of agents with explicit dependencies.
The runtime executes them in topological order. Predictable, auditable,
easy to debug. This is where most workflows start.

```yaml
orchestration:
  engine: dag
  graph:
    - id: planner
      agent: planner
    - id: researcher
      agent: researcher
      depends_on: [planner]
    - id: writer
      agent: writer
      depends_on: [researcher]
```

**A1 Adaptive** -- The graph reacts to intermediate results. Conditional
execution (`when` expressions), loops, fan-out. Agents still exist in YAML,
but the path through the graph depends on what they find.

```yaml
- id: deep_analysis
  agent: deep_analyzer
  depends_on: [initial_scan]
  when: "state.initial_scan.risk_score > 0.7"   # only if risk is high
```

**A2 Delegating** -- A manager agent receives the task and **dynamically
decides** what workers to spawn. Workers don't exist as static YAML files --
the manager generates their instructions, skills, and tool configurations
at runtime. This is the delegation loop engine.

```yaml
orchestration:
  engine: delegation_loop
  delegation_loop:
    manager: agents/manager
    budget:
      max_loops: 10
      max_total_workers: 20
      max_wall_time: 300
```

The manager generates **delegation envelopes** for each worker:
```
Manager: "I need market research and competitive analysis."
  → Worker A: instructions="Research EV market size", skills=["## Market Analysis\n..."]
  → Worker B: instructions="Analyze top 5 competitors", skills=["## Competitive Intel\n..."]
Workers execute in parallel, report back.
Manager evaluates: "Need deeper data on pricing." → spawns Worker C
Manager evaluates: "Complete." → returns final result
```

**A3 Self-Tooling** -- Agents don't just use tools -- they **create** them.
Via Code Mode's `sdk.tools.create()`, an agent reads a configuration, API spec,
or data schema and generates specialized MCP tools on the fly. Downstream
agents use these tools immediately. The toolchain evolves with the workflow.

```python
# Agent reads scoring config and creates tools dynamically
for criterion in config["criteria"]:
    await sdk.tools.create(
        name=f"scoring.{criterion['name']}",
        description=f"Score: {criterion['name']}",
        parameters={"type": "object", "properties": {"value": {"type": "number"}}},
        code=f"def handler(*, value): return {{'ok': True, 'data': {{'score': value * {criterion['weight']}}}}}"
    )
```

**A4 Self-Organizing** -- Workers can become managers themselves. They split
their allocated budget and delegate to sub-workers. The execution tree grows
organically, bounded by a **budget system** that guarantees termination and
cost control.

```
Manager (budget: 20 workers, 500k tokens)
├── Worker A → becomes sub-manager (budget: 8 workers, 150k tokens)
│   ├── Sub-Worker A1
│   └── Sub-Worker A2
├── Worker B (budget: 4 workers, 100k tokens)
└── Worker C → becomes sub-manager (budget: 6 workers, 120k tokens)
    └── Sub-Worker C1
```

### Safety Scales with Autonomy

More autonomy demands more guardrails:

| Level | Required Safety |
|-------|----------------|
| A0-A1 | Security + observability recommended |
| A2 | **Budget system required** -- hard limits on loops, workers, tokens, wall time |
| A3 | **Safety envelope required** -- manager cannot disable sandbox, override models, or remove tool restrictions |
| A4 | **Observability required** -- full audit trail mandatory for self-organizing systems |

This is enforced by the runtime, not by convention. A manager agent at A2+
literally cannot spawn workers without a budget. A worker at A3+ literally
cannot escape its sandbox.

```bash
awp compliance my-workflow/ --level A2   # Check if workflow achieves A2
```

### Cross-Cutting: Features Available at Every Level

Memory, communication, observability, and security are **not** gated behind
autonomy levels. They are capabilities you add when your workflow needs them:

| Capability | What it does | Available at |
|------------|-------------|-------------|
| Memory | Long-term, daily log, episodic, semantic | Any level |
| Communication | Message bus with typed channels | Any level |
| Observability | Tracing, metrics, audit trail | Any level (required at A4) |
| Security | Circuit breaker, rate limiting, access control | Any level (required at A3+) |

A single-agent A0 workflow with full observability is perfectly valid.
A complex A4 workflow without memory is also fine -- if the task doesn't need it.

---

## How AWP Works: The 7-Layer Model

AWP organizes a workflow into seven layers plus security as a cross-cutting concern:

```
 Layer 6  OBSERVABILITY     How do I monitor this?          (cross-cutting)
 Layer 5  ORCHESTRATION     How do agents coordinate?       (DAG or Delegation Loop)
 Layer 4  MEMORY & STATE    What does the workflow remember?
 Layer 3  COMMUNICATION     How do agents talk?
 Layer 2  CAPABILITIES      What can an agent do?           (tools, skills, code mode)
 Layer 1  AGENT IDENTITY    Who is this agent?
 Layer 0  MANIFEST          What is this workflow?
```

Start at the bottom. Layer 0 and 1 are always required. Everything above is opt-in.

---

## The Capability Stack

AWP provides five pillars that enable agents at every autonomy level:

### 1. Generated Skills -- Domain Knowledge on Demand

Skills are Markdown files injected into the agent's system prompt. They provide
domain expertise without manual prompt engineering:

```
skills/cloud-security/SKILL.md
  → CIS Benchmarks, NIST 800-53 controls, severity classifications
```

At A2+ (delegation loop), the **manager generates skills dynamically** for each
worker -- tailored to the specific subtask. No static skill files needed.

### 2. MCP Tools -- The Agent's Hands

Every agent can call tools: search the web, read/write files, query APIs,
access memory. Tools are declared in YAML and resolved at runtime:

```yaml
capabilities:
  tools:
    enabled: true
    allowed: [web.search, file.read, memory.*]
```

Custom tools go into `mcp/` -- auto-discovered, auto-registered. Need to
override a built-in? Use the same FQN.

### 3. Code Mode -- Write Code, Not Tool Calls

Instead of calling tools one-at-a-time (one LLM roundtrip per tool), Code Mode
lets the agent write a program against a typed SDK. One roundtrip, ten tool calls:

```
Classic:  Agent → LLM → tool → result → LLM → tool → result → LLM     (3 roundtrips)
Code:     Agent → LLM → code block → sandbox executes all → result     (1 roundtrip)
```

### 4. Dynamic Tool Creation -- Agents That Build Tools

The most powerful capability: agents with Code Mode can **create new MCP tools
at runtime** via `sdk.tools.create()`. A tool-builder agent reads a config and
generates specialized tools. Downstream agents use them immediately.

This is what enables **A3 Self-Tooling**: the toolchain itself becomes a
runtime artifact, not a static dependency.

### 5. Two Orchestration Engines

| Engine | Autonomy | How it works |
|--------|----------|-------------|
| **DAG** | A0-A1 | Static graph of agents, topological execution |
| **Delegation Loop** | A2-A4 | Manager-worker loop with dynamic orchestration |

The engines compose: a DAG node can **be** a delegation loop. This gives
predictable outer flow with adaptive inner steps.

```bash
# DAG workflow
awp run my-pipeline/ --task "Process quarterly report"

# Delegation loop with separate models for manager and workers
awp run my-research/ --task "Analyze market trends" \
  --manager-model openrouter/anthropic/claude-opus-4 \
  --worker-model openrouter/anthropic/claude-sonnet-4
```

See [docs/ORCHESTRATION_ENGINES.md](docs/ORCHESTRATION_ENGINES.md) for the
complete reference.

---

## Design Patterns

AWP workflows follow common patterns. Choose the right one for your task:

**Pipeline** (A0-A1) -- Linear chain, each agent feeds the next.
```
planner → researcher → writer
```

**Fan-Out / Fan-In** (A1) -- Split, process in parallel, aggregate.
```
splitter → [worker_1, worker_2, worker_3] → aggregator
```

**Conditional Branching** (A1) -- Route based on intermediate results.
```
analyzer → (risk > 0.7) → deep_analysis
         → (risk ≤ 0.7) → summary
```

**Manager-Worker** (A2) -- Manager delegates, evaluates, iterates.
```
manager → [worker_a, worker_b] → validate → manager → complete
```

**Tool Builder** (A3) -- Phase 1 creates tools, Phase 2 uses them.
```
Iter 1: manager → tool_builder (creates scoring.*)
Iter 2: manager → [analyst_1, analyst_2] (uses scoring.*)
Iter 3: manager → complete
```

**Self-Organizing Team** (A4) -- Manager delegates to sub-managers.
```
manager (budget: 20 workers)
├── sub_mgr_a (budget: 8) → [worker_a1, worker_a2]
├── worker_b
└── sub_mgr_c (budget: 6) → [worker_c1]
```

---

## The Delegation Loop in Detail

The delegation loop is the engine that powers A2-A4. Here's how it works:

```
┌─────────────────────────────────────────────────────────────┐
│                     DELEGATION LOOP                          │
│                                                              │
│   ┌──────────────┐                                           │
│   │   MANAGER     │ ← Task + Rolling Summary + Budget Status │
│   │   (strong     │                                          │
│   │    model)     │ → Decision: DELEGATE / COMPLETE / FAIL   │
│   └──────┬───────┘                                           │
│          │ DELEGATE                                          │
│    ┌─────┴─────┬──────────┐   Fan-Out                        │
│    ▼           ▼          ▼                                   │
│  Worker A   Worker B   Worker C   ← Ephemeral, dynamic       │
│  (sonnet)   (sonnet)   (sonnet)     instructions + skills     │
│    │           │          │                                   │
│    └─────┬─────┴──────────┘                                  │
│          ▼                                                   │
│   ┌──────────────┐                                           │
│   │  VALIDATION   │  Tier 1: Deterministic (schema, budget)  │
│   │  (2-tier)     │  Tier 2: LLM semantic (does it make      │
│   └──────┬───────┘          sense?)                          │
│          ▼                                                   │
│   Stall detection → Budget check → Next iteration            │
└─────────────────────────────────────────────────────────────┘
```

### Budget System

Every delegation loop has a hard budget. No exceptions.

```yaml
budget:
  max_loops: 20              # Manager iterations
  max_total_workers: 30      # Total workers spawned
  max_total_tokens: 1000000  # LLM token cap
  max_wall_time: 600         # Wall clock seconds
  max_depth: 5               # Recursive delegation depth
```

When workers sub-delegate (A4), they split their budget. The invariant
`sum(children) + self <= allocation` is enforced deterministically.

### Run Budget Limits -- Global Limits for Any Workflow

Independent of the delegation loop budget, AWP supports **global run budget
limits** that apply to **any workflow type** (DAG or delegation loop). These
limits cap total resource consumption across the entire run.

```yaml
orchestration:
  engine: dag                    # Works with both dag and delegation_loop
  run_budget:
    max_wall_time: 300           # 5 minutes total
    max_total_tokens: 500000     # LLM token cap
    max_tool_calls: 100          # Total tool invocations
    max_agent_runs: 50           # Total agent executions
    max_cost_usd: 5.0            # Estimated cost cap in USD
    enabled_limits:              # Choose which limits are active
      - max_wall_time
      - max_total_tokens
      - max_cost_usd
```

**Selectable limits:** The `enabled_limits` field lets you activate only the
limits you care about. During `awp run`, the **Limits Wizard** lets you
interactively toggle each limit on/off and adjust its value:

```
============================================================
  Run Budget Limits
============================================================

  1) [ON ] Max Wall Time          300 s    (total execution time)
  2) [ON ] Max Tokens          500000      (LLM token cap)
  3) [OFF] Max Tool Calls         100      (total tool invocations)
  4) [OFF] Max Agent Runs          50      (total agent executions)
  5) [ON ] Max Cost              5.0 USD   (estimated cost cap)

============================================================

  Toggle or adjust limits? Enter numbers (e.g. 1,3) or [N]:
```

When a limit is hit, the workflow stops gracefully and reports which limit
was exceeded in the final state under `_run_budget.exceeded`.

### Safety Envelope

The manager controls what workers do -- but cannot override security:

```yaml
worker_policy:
  enforced:                         # Manager CANNOT change
    sandbox: {type: subprocess, max_memory_mb: 512}
    rate_limiting: {max_llm_calls_per_minute: 30}
    forbidden_tools: [shell.execute]
  manager_controlled:               # Manager CAN set
    - instructions
    - skills
    - tools_allowed
    - output_contract
    - codemode.enabled
```

The user controls the models (`--manager-model`, `--worker-model`). The
manager cannot upgrade workers to expensive models.

### Logging -- Everything on Disk

Every run produces a full audit trail:

```
workspace/runs/{run_id}/
├── RUN_SUMMARY.md                 # Human-readable overview
├── run_manifest.json              # Machine-readable config
├── iterations/
│   ├── 001/
│   │   ├── ITERATION_SUMMARY.md   # What happened
│   │   ├── manager_decision.json  # Manager's raw output
│   │   ├── budget_snapshot.json   # Budget after this iteration
│   │   └── delegations/
│   │       └── worker_a/
│   │           ├── envelope.json  # What the worker received
│   │           ├── result.json    # What the worker returned
│   │           └── RESULT.md      # Human-readable result
├── history/
│   ├── ROLLING_SUMMARY.md         # Keeps context window manageable
│   └── rolling_summary.json
└── artifacts/
    ├── skills/                    # All generated skills
    └── tools/                     # All generated tools
```

Both JSON (machines) and Markdown (humans). The rolling summary prevents
context overflow: recent iterations in full, older ones summarized.

---

## From Idea to Workflow -- The Red Thread

AWP follows a deliberate path from abstract idea to running code:

```
 Idea → Requirements → Plan → Code → Run → Share
  abstract ─────────────────────────────── concrete
```

### Step 0: Install AWP

```bash
curl -fsSL https://raw.githubusercontent.com/veegee82/agent-workflow-protocol/main/install.sh | bash
```

Or: `pip install awp-protocol`

### Step 1: Install the AWP Skill in Claude

The AWP skill is a Markdown file (`skill/SKILL.md`) that turns Claude into an
AWP workflow architect. Add it to Claude Code or Claude Desktop:

```bash
# Claude Code
echo "Read and follow the instructions in skill/SKILL.md" >> CLAUDE.md

# Or install via ClawHub
clawhub install awp-workflow-builder
```

### Step 2: Describe your idea

> "I need a research pipeline that plans, investigates, and writes articles."

The AI asks structured questions: agent roles, tools, data flow, autonomy level,
memory needs. You answer or accept defaults.

### Step 3: The AI builds a plan

Before writing code, the AI creates a **Workflow Plan**: goal statement, agent
roles, data flow, tool mapping, file manifest, validation preview. You confirm
or adjust.

### Step 4: The AI generates all files

```
research-pipeline/
  workflow.awp.yaml            Manifest: 3 agents, DAG, state sharing
  agents/
    planner/
      agent.awp.yaml           Agent config: model, prompt, output contract
      agent.py                 Agent class (platform-agnostic)
      workflow/
        instructions/SYSTEM_PROMPT.md
        prompt/00_INTRO.md
        output_schema/output_schema.json
```

Every file follows the AWP spec. Every rule is validated.

### Step 5: Run it

```bash
awp run research-pipeline/ --task "Research quantum computing trends"
```

Or via Python:

```python
from awp.runtime import WorkflowRunner

runner = WorkflowRunner("research-pipeline")
result = runner.run("Research quantum computing trends")
```

### Step 6: Share it

```bash
awp pack research-pipeline/              # Creates .awp.zip
clawhub publish research-pipeline/       # Or publish to ClawHub
```

---

## LLM-Planned Workflows: Everything is Generated

The most powerful aspect of AWP: **the entire capability stack is generated by
the LLM itself**. Skills, tools, agent code -- all produced by the same AI that
plans the workflow.

```
  LLM receives: "Build a compliance audit for AWS"

  LLM generates:
  ┌──────────────────────────────────────────────────────────────┐
  │  Skills → skills/aws-compliance/SKILL.md                     │
  │           CIS Benchmarks, NIST controls, remediation         │
  │                                                              │
  │  Tools  → mcp/aws_scanner.py                                 │
  │           aws.scan_security_groups, aws.check_iam_policies   │
  │                                                              │
  │  Agents → agents/scanner/ (Code Mode, uses dynamic tools)    │
  │           agents/analyzer/ (correlates findings)              │
  │           agents/reporter/ (produces executive summary)       │
  │                                                              │
  │  Orchestration → workflow.awp.yaml                           │
  │                  DAG or delegation loop, based on complexity  │
  └──────────────────────────────────────────────────────────────┘
```

The LLM decides the **architecture** (A0 pipeline or A2 delegation loop),
generates the **capabilities** (skills, tools, code), and produces a
**validated, runnable workflow**. One intelligence plans the entire system --
there is no integration gap.

---

## Platform Independence

AWP separates **what** a workflow does from **how** it runs:

```python
from awp.agent import AWPAgent

class Agent(AWPAgent):
    @property
    def name(self) -> str:
        return "researcher"

    def run(self, task: str, state: dict) -> dict:
        return {self.name: {"findings": "...", "confidence": 0.85}}
```

| Runtime | Language | Deployment | Best for |
|---------|----------|-----------|----------|
| **Standalone** (`awp-protocol`) | Python | Local / Server | Development, prototyping |
| **Cloudflare Workers** | TypeScript | Edge (serverless) | Production, global scale |

Third-party platforms provide their own adapters.

---

## Enterprise Integration

AWP doesn't replace your infrastructure -- it **plugs into it**:

```
  AWP Workflow (portable)          Your Infrastructure (custom)
  ─────────────────────           ──────────────────────────────
  memory.write  ──────────────→   Pinecone / Weaviate / pgvector
  web.search    ──────────────→   Internal search API
  custom.erp    ──────────────→   SAP / Salesforce
  Skills (.md)  ──────────────→   Confluence export
  Tracing       ──────────────→   Datadog / Grafana
```

Override any built-in tool by dropping a Python file into `mcp/`. Inject
company knowledge via `skills/`. Route observability to your OTEL collector.
Manage secrets via `secrets.yaml`. The YAML never changes -- only the backend.

### Competitive Benchmarking: Same Workflow, Different Backends

Because AWP separates the workflow definition from the infrastructure, companies
can **benchmark their technologies against each other using identical agentic
workflows**.

A memory vendor builds a better vector search? Swap the `memory.search` MCP
tool and run the same workflow. An observability platform claims lower overhead?
Plug it in and compare. A new LLM provider is faster? Change the model and
measure.

```
  Same workflow.awp.yaml                Different backends
  ─────────────────────                 ──────────────────────
                                        Run A: Pinecone + GPT-4o
  research-pipeline/                →   Run B: Weaviate + Claude Sonnet
    planner → researcher → writer       Run C: pgvector + Llama 3
                                        Run D: Qdrant + Gemini Pro
```

This creates a **shared evaluation framework** for the entire AI infrastructure
ecosystem:

| What you're building | How AWP helps |
|---------------------|---------------|
| **Memory / RAG** | Benchmark your vector DB against competitors using real multi-agent workflows, not synthetic queries |
| **LLM Providers** | Compare model quality, speed, and cost on identical agent tasks with identical prompts |
| **Observability** | Prove your tracing adds less overhead by running the same workflow with different collectors |
| **Orchestration** | Show your runtime is faster/cheaper by executing the same AWP workflow on your platform |
| **Tool Platforms** | Demonstrate your MCP tool implementations outperform alternatives on the same agent graph |
| **Security** | Validate your sandbox/rate-limiter catches more edge cases using standardized A3/A4 workflows |

The key insight: **the workflow is the benchmark**. When everyone uses the same
portable format, the competition shifts from "who has the best framework" to
"who has the best infrastructure" -- which is where the real value lies.

Companies can publish their AWP-compatible implementations, and the community
can run standardized benchmark suites to compare them objectively. No vendor
lock-in, no synthetic benchmarks, no framework-specific bias. Just the same
agents, the same tasks, the same output contracts -- different backends.

---

## Repository Structure

```
agent-workflow-protocol/
  install.sh                  Linux/macOS installer
  docs/                       Complete protocol reference
  spec/                       Normative specification
  schemas/                    JSON Schemas for validation
  examples/                   Runnable workflows (A0-A4)
    01-hello-world/           A0 Prescribed: single agent greeting
    02-research-pipeline/     A1 Adaptive: 3-agent DAG (planner→researcher→writer)
    03-chat-team/             A1 + Communication: message bus between agents
    04-memory-workflow/        A1 + Memory: long-term memory persistence
    05-observable-analytics/   A1 + Observability: tracing, metrics, audit
    06-enterprise/             A1 + All Features: security, skills, code mode
    07-dynamic-tools/          A3 Self-Tooling: dynamic tool creation via DAG
    08-delegation-loop/        A2 Delegating: manager-worker delegation loop
    09-recursive-delegation/   A4 Self-Organizing: recursive delegation + budget
    10-skill-and-tool-gen/     A3 Self-Tooling: skill generation in delegation loop
    11-tool-creation-loop/     A3 Self-Tooling: scoring tool creation + usage
    12-full-autonomy-test/     A4 Full Test: tools + skills + multi-iteration + budget
  skill/                      AWP Skill for AI assistants
  reference/python/           Python reference implementation
  conformance/                Conformance test suite
```

## CLI Reference

```bash
awp run <dir> --task "..."                          # Run workflow (DAG or delegation loop)
awp run <dir> --task "..." --manager-model opus     # Delegation loop with model split
awp validate <dir>                                  # Validate structure (R1-R26)
awp compliance <dir> --level A2                     # Check autonomy level
awp visualize <dir> --format mermaid                # Visualize agent graph
awp pack <dir>                                      # Pack as .awp.zip
awp identity-card <agent.awp.yaml>                  # Show agent capabilities
```

## Quick Links

| Resource | Start here if you... |
|----------|---------------------|
| [Docs](docs/) | Want the complete protocol reference |
| [Quickstart](primer/quickstart.md) | Want to build your first workflow in 5 minutes |
| [Orchestration Engines](docs/ORCHESTRATION_ENGINES.md) | Want to understand DAG vs Delegation Loop |
| [Specification](spec/versions/1.0/spec.md) | Need the normative technical specification |
| [Examples](examples/) | Want to see complete, runnable workflows |
| [Skill](skill/SKILL.md) | Want AI to generate workflows for you |
| [FAQ](primer/faq.md) | Have questions |

## License

MIT License. See [LICENSE](LICENSE).
