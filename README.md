<p align="center">
  <img src="assets/awp_logo.png" alt="AWP Logo" width="200" />
</p>

<h1 align="center">AWP - Agent Workflow Protocol</h1>

<p align="center">
  <strong>An open standard for describing multi-agent workflows.</strong><br/>
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
solutions -- uses its own format for defining agents, tools,
orchestration, and memory. Moving a workflow from one platform to another
means rewriting everything.

Existing standards each solve a piece of the puzzle but none cover the
full picture:

| Standard | What it covers | What it misses |
|----------|---------------|----------------|
| MCP | Tool access for LLMs | No agents, no orchestration, no state |
| A2A | Agent communication | No orchestration, no memory, no tools |
| OpenAPI | HTTP API description | No agent concept, no DAG structure |

**AWP fills this gap.** It describes a **complete** multi-agent workflow in a
single, portable format that any runtime can execute.

## The Core Idea

AWP is to agentic workflows what **Docker Compose** is to container stacks:

- A **declarative YAML** describes the entire system
- Services (= Agents) are defined with their dependencies
- Volumes (= Memory), Networks (= Communication), Health-Checks (= Observability)
- Portable across different container runtimes (= agent platforms)

**One manifest. Any runtime. Full workflow.**

But AWP goes further. It doesn't just describe workflows -- it provides a
complete **capability stack** that turns any LLM agent into a powerful,
autonomous system:

```
  ┌──────────────────────────────────────────────────────────────┐
  │                    AWP Capability Stack                       │
  │                                                              │
  │  ┌─────────────┐  ┌─────────────┐  ┌──────────────────────┐ │
  │  │  Generated   │  │    MCP      │  │     Code Mode        │ │
  │  │   Skills     │  │   Tools     │  │  (SDK + Sandbox)     │ │
  │  │             │  │             │  │                      │ │
  │  │ Domain know- │  │ Dynamic     │  │ Write code against   │ │
  │  │ ledge as     │  │ actions:    │  │ a typed SDK instead  │ │
  │  │ Markdown,    │  │ web.search  │  │ of calling tools     │ │
  │  │ injected     │  │ file.write  │  │ one by one.          │ │
  │  │ into the     │  │ memory.*    │  │                      │ │
  │  │ agent's      │  │ shell.exec  │  │ 10 tool calls in     │ │
  │  │ system       │  │ custom.*    │  │ one LLM roundtrip.   │ │
  │  │ prompt.      │  │             │  │                      │ │
  │  └─────────────┘  └─────────────┘  └──────────────────────┘ │
  │                                                              │
  │  ┌─────────────────────────────────────────────────────────┐ │
  │  │                    CLI Runtime                           │ │
  │  │  awp run / awp validate / awp pack / awp visualize      │ │
  │  └─────────────────────────────────────────────────────────┘ │
  └──────────────────────────────────────────────────────────────┘
```

### What This Combination Makes Possible

The real power of AWP lies in the synergy of its four pillars:

**1. Generated Skills** -- Domain expertise on demand.
Tell the AI *"build a compliance workflow for cloud security"* and it generates
`skills/cloud-security/SKILL.md` with CIS benchmarks, NIST controls, and
severity classifications. The skill is injected into the agent's system prompt
at runtime, giving the LLM deep domain knowledge without manual prompt engineering.

**2. MCP Tools** -- The agent's hands.
Every agent can call tools: search the web, read/write files, query APIs, run
shell commands, access memory. Tools are declared in YAML and resolved at
runtime. Need a custom tool? Drop a Python file into `mcp/` -- auto-discovered,
auto-registered. Need to override a built-in? Use the same FQN.

**3. Code Mode** -- 10x efficiency for complex tasks.
Instead of calling tools one-at-a-time (one LLM roundtrip per tool), Code Mode
lets the agent write a complete program against a typed SDK. One roundtrip,
ten tool calls. The code runs in a sandboxed environment (subprocess, Docker,
or V8 isolate). Same output contract, dramatically fewer tokens.

**4. CLI Runtime** -- From YAML to results in one command.
`awp run my-workflow/ --task "..."` validates the workflow, resolves tools,
builds prompts with skills, orchestrates the agent DAG, and collects results.
No framework lock-in. No boilerplate. Just run it.

**Together, these four pillars let you build workflows that:**
- Understand their domain deeply (Skills)
- Act on that understanding (MCP Tools)
- Do it efficiently (Code Mode)
- Run anywhere (CLI + portable YAML)

Example: A security audit workflow where the analyst agent *knows* CIS benchmarks
(Skill), *queries* cloud resources for violations (MCP Tool), and *generates*
a complete remediation script in one shot (Code Mode) -- all described in
declarative YAML that runs on any AWP-compatible runtime.

### LLM-Planned Workflows: Everything is Generated

The most powerful aspect of AWP is not any single capability -- it's that **the
entire capability stack is generated by the LLM itself**. Skills, MCP tools, and
agent code with Code Mode are not hand-authored by developers -- they are
produced by the same AI that plans the workflow. This fundamentally changes what
is possible.

#### What Gets Generated

When an LLM plans an AWP workflow, it doesn't just produce YAML config files.
It generates the **complete operational infrastructure**:

```
  LLM receives: "Build a compliance audit workflow for AWS infrastructure"

  LLM generates:
  ┌──────────────────────────────────────────────────────────────────┐
  │                                                                  │
  │  Skills (Domain Knowledge)                                       │
  │  ├── skills/aws-compliance/SKILL.md                              │
  │  │   └── CIS Benchmarks, NIST 800-53 controls, severity         │
  │  │       classifications, remediation patterns                   │
  │  ├── skills/report-writing/SKILL.md                              │
  │  │   └── Executive summary format, risk matrix template,         │
  │  │       compliance scoring methodology                          │
  │  │                                                               │
  │  MCP Tools (Custom Capabilities)                                 │
  │  ├── mcp/aws_scanner.py                                          │
  │  │   └── aws.scan_security_groups, aws.check_iam_policies,       │
  │  │       aws.list_public_buckets                                 │
  │  ├── mcp/compliance_db.py                                        │
  │  │   └── compliance.lookup_control, compliance.score_finding      │
  │  │                                                               │
  │  Agent Code (Code Mode)                                          │
  │  ├── agents/scanner/agent.py                                     │
  │  │   └── Code Mode enabled -- writes scanning logic against      │
  │  │       typed SDK: sdk.aws.scan_security_groups(),               │
  │  │       sdk.aws.check_iam_policies() -- 12 tool calls           │
  │  │       in one LLM roundtrip                                    │
  │  ├── agents/analyzer/agent.py                                    │
  │  │   └── Code Mode enabled -- correlates findings, computes      │
  │  │       risk scores, generates remediation plan                 │
  │  ├── agents/reporter/agent.py                                    │
  │  │   └── Classic mode -- uses skills for formatting,             │
  │  │       produces executive summary                              │
  │  │                                                               │
  │  Workflow Orchestration                                           │
  │  └── workflow.awp.yaml                                           │
  │      └── DAG: scanner → analyzer → reporter                     │
  │          State sharing, memory config, output contracts           │
  └──────────────────────────────────────────────────────────────────┘
```

The LLM decides **which** skills to write and **what** domain knowledge to
include. It decides **which** custom MCP tools are needed and **generates their
implementations**. It decides **which** agents benefit from Code Mode and writes
the SDK-based code those agents will execute. Every piece fits together because
**one intelligence planned the entire system**.

#### Why This Changes Everything

Traditional agent development is a manual assembly process. A developer writes
prompts, integrates tools, configures orchestration, and hopes everything fits.
With AWP, the LLM handles this end-to-end:

**1. Skills are generated with perfect context.**
The LLM doesn't search for a generic "compliance" skill -- it generates one
tailored to the exact use case. A cloud security audit gets CIS benchmarks
and AWS-specific controls. A financial compliance workflow gets SOX procedures
and GAAP rules. The domain knowledge is precise because the LLM understands
the requirements before it writes the skill.

**2. MCP tools are generated to fill capability gaps.**
The LLM knows what built-in tools exist (`web.search`, `file.write`, `memory.*`)
and identifies what's missing. Need to query AWS APIs? It generates
`mcp/aws_scanner.py`. Need to score compliance findings? It generates
`mcp/compliance_db.py`. Each tool follows the standard MCP interface, is
auto-discovered at runtime, and slots seamlessly into the agent's tool registry.

**3. Code Mode enables complex logic in a single step.**
When the LLM plans an agent that needs to call 10+ tools in sequence -- scan
resources, filter results, cross-reference compliance rules, compute scores --
it enables Code Mode for that agent. Instead of 10 LLM roundtrips with 10 tool
calls, the agent writes one code block against the typed SDK. The LLM generates
this code at runtime, using the skills it wrote for domain knowledge and the
MCP tools it created for capability. Everything is self-consistent.

**4. The workflow graph emerges from the task, not from templates.**
The LLM determines how many agents are needed, what each one does, how data
flows between them, and what compliance level is required. A simple task gets
a single agent (L0). A complex enterprise task gets a multi-agent DAG with
memory, communication, and observability (L4/L5). The architecture adapts to
the problem.

#### The Feedback Loop: Skills Inform Tools Inform Code

The generated components form a coherent system because they're planned together:

```
  Skills define what the agent knows
       ↓
  MCP Tools give the agent capabilities that match its knowledge
       ↓
  Code Mode lets the agent combine knowledge + tools efficiently
       ↓
  Output contracts ensure each agent's results feed the next
       ↓
  The workflow DAG ties everything into an execution plan
```

A manually assembled system would require a developer to ensure these layers
align. In an LLM-planned workflow, alignment is inherent -- the same model that
wrote the compliance skill also wrote the scanning tool and the code that uses
both. There is no integration gap.

#### What This Enables in Practice

| Scenario | What the LLM Plans |
|----------|-------------------|
| *"Build a deep-research pipeline for market analysis"* | Generates skills for financial analysis and source evaluation. Creates custom MCP tools for SEC EDGAR queries and earnings data. Enables Code Mode on the researcher agent to parallelize 15 data source queries in one roundtrip. |
| *"Build a code review workflow for our Python monorepo"* | Generates skills with the team's coding standards and architecture patterns. Creates MCP tools for static analysis and test coverage. Uses Code Mode to run linters, parse ASTs, and correlate findings across files. |
| *"Build a customer support triage system with memory"* | Generates skills for product knowledge and escalation rules. Creates MCP tools for ticketing system integration. Configures L3 memory so agents recall past interactions. Classic mode for the response agent (few tools, high quality). |

In each case, the human describes the **goal**. The LLM determines the
**architecture**, generates the **capabilities** (skills, tools, code), and
produces a **validated, runnable workflow**. The entire path from idea to
execution is LLM-planned -- and every generated artifact follows the AWP
specification, making it portable, shareable, and reproducible.

This is what AWP makes possible: **not just an agent that follows instructions,
but an agent that builds other agents -- complete with the domain knowledge,
tools, and code they need to operate autonomously.**

## The 7-Layer Model

AWP organizes a workflow into seven layers. Each layer answers one question:

```
 Layer 6  OBSERVABILITY     How do I monitor this workflow?
 Layer 5  ORCHESTRATION     In what order and under what conditions?
 Layer 4  MEMORY & STATE    What does the workflow remember?
 Layer 3  COMMUNICATION     How do agents talk to each other?
 Layer 2  CAPABILITIES      What can an agent do? (tools, skills, code mode)
 Layer 1  AGENT IDENTITY    Who is this agent?
 Layer 0  MANIFEST          What is this workflow?
```

You start at the bottom. Layer 0 (manifest) and Layer 1 (agent identity)
are always required. Everything above is opt-in -- add layers only when
you need them. A simple single-agent workflow uses two layers. A
production enterprise system uses all seven.

## Installation

### Quick Install (Linux / macOS)

```bash
curl -fsSL https://raw.githubusercontent.com/veegee82/agent-workflow-protocol/main/install.sh | bash
```

Or clone and run locally:

```bash
git clone https://github.com/veegee82/agent-workflow-protocol.git
cd agent-workflow-protocol
./install.sh
```

The installer:
1. Checks for Python >= 3.10, pip, and git
2. Creates `~/.awp/` with an isolated Python virtual environment
3. Installs the `awp-protocol` package
4. Creates the `awp` CLI wrapper in `~/.awp/bin/`
5. Adds `~/.awp/bin` to your PATH (`.bashrc`, `.zshrc`, or `.profile`)
6. Runs an interactive **LLM Configuration Wizard** that sets up your preferred provider (OpenRouter, Ollama, OpenAI, Groq, Together, or custom)

After installation, restart your shell or run:

```bash
source ~/.bashrc   # or ~/.zshrc
awp --help
```

### Quick Install (Windows)

```powershell
# PowerShell (Administrator)
irm https://raw.githubusercontent.com/veegee82/agent-workflow-protocol/main/install.ps1 | iex
```

Or run `install.bat` from the cloned repository.

### Manual Install (pip)

If you prefer a manual setup:

```bash
pip install awp-protocol

# Set LLM credentials
export LLM_API_KEY=sk-...
export LLM_MODEL=anthropic/claude-sonnet-4-20250514
export LLM_BASE_URL=https://openrouter.ai/api/v1    # optional
```

### Verify Installation

```bash
awp --help                       # Show available commands
awp validate examples/01-hello-world/   # Validate an example workflow
awp run examples/01-hello-world/ --task "Say hello to the world"
```

## From Idea to Workflow -- The Red Thread

AWP follows a deliberate path from abstract idea to running code:

```
 Idea → Requirements → Plan → Code → Run → Share
  abstract ─────────────────────────────── concrete
```

### Step 0: Install the AWP Skill in Claude

Before you can describe your idea, Claude needs the AWP skill -- the domain
knowledge that tells it how to plan and generate complete AWP workflows.

**Option A: Add the skill file directly (Claude Code / Claude Desktop)**

The AWP skill is a single Markdown file (`skill/SKILL.md`) that contains the
complete AWP specification, all 24 validation rules, the 5-phase generation
process, and the file templates. You add it to Claude's context so it becomes
part of the conversation:

```
# Claude Code -- add as project skill
# Copy skill/SKILL.md into your project, then reference it:
/add-skill skill/SKILL.md

# Or simply paste the content of SKILL.md at the start of the conversation.
```

For **Claude Desktop**, add the skill as a Project Knowledge file:
1. Create a new Project (or open an existing one)
2. Go to Project Knowledge → Add Content
3. Upload `skill/SKILL.md` (or paste its contents)
4. Every conversation in this project now has AWP generation capability

For **Claude Code (CLI)**, the skill can be loaded in multiple ways:
```bash
# Option 1: Reference in CLAUDE.md (auto-loaded for every conversation)
echo "Read and follow the instructions in skill/SKILL.md" >> CLAUDE.md

# Option 2: Install via ClawHub (if available)
clawhub install awp-workflow-builder

# Option 3: Use the packaged skill.zip
unzip skill.zip -d ~/.claude/skills/awp/
```

**Option B: Use the portable `skill.zip`**

The repository includes a pre-packaged `skill.zip` that bundles the base skill
with all adapters (Standalone, Cloudflare Workers, ClawHub) and extensions
(Financial, DevOps). Extract and add it to your AI assistant's context.

**What the skill gives Claude:**

Once loaded, Claude gains:
- The complete AWP 7-layer model and compliance levels (L0-L5)
- The 5-phase generation process (Requirements → Plan → Generate → Validate → Summary)
- All 24 validation rules (R1-R24) for structural correctness
- File templates for every artifact (YAML configs, schemas, prompts, agent code)
- Platform adapters for choosing the right deployment target
- The interactive questionnaire and validation menu

Without the skill, Claude is a general-purpose assistant. **With the skill,
Claude becomes an AWP workflow architect** -- it knows how to ask the right
questions, plan the agent graph, generate every file, and validate the result
against the specification. The skill is the bridge between your idea and a
running multi-agent system.

Now you're ready to describe your idea.

### Step 1: You have an idea

> "I need a research pipeline that plans, investigates, and writes articles."

### Step 2: You clarify requirements

Tell Claude:

> "Build an AWP research pipeline with three agents: planner, researcher, writer."

The AI presents a structured questionnaire -- agent roles, tools, data flow,
compliance level, memory, output format. You answer (or accept defaults), and
the AI has everything it needs to plan your workflow.

### Step 3: The AI builds a Workflow Plan

Before writing a single file, the AI creates a **Workflow Plan** -- a structured
document that transitions step by step from the abstract goal to the concrete
implementation:

1. **Goal Statement** -- What does the workflow do? What goes in, what comes out?
2. **Agent Roles** -- Each agent's responsibility in plain language.
3. **Data Flow & Contracts** -- What data moves between agents, with types and fields.
4. **Tool & Capability Mapping** -- Which tools, memory tiers, and skills each agent needs.
5. **File Manifest** -- Every file that will be generated, listed and explained.
6. **Validation Preview** -- Which rules apply, what compliance level is targeted.
7. **Validation Menu** -- Multiple-choice questions to confirm or correct each
   design decision (agents, data flow, tools, compliance level, memory).

You validate the plan point by point. The AI pre-selects its recommendations --
you confirm, adjust, or override. Only when you approve does code generation start.

### Step 4: The AWP Skill generates your workflow

With the approved plan, the AI generates all files:

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
        output_schema_desc/output_schema_desc.json
    researcher/
      ...
    writer/
      ...
```

Every file follows the AWP spec. Every rule is validated. The workflow is
ready to run.

### Step 5: Run it

```bash
awp run research-pipeline/ --task "Research quantum computing trends in 2026"
```

Or via the Python API:

```python
from awp.runtime import WorkflowRunner

runner = WorkflowRunner("research-pipeline")
result = runner.run("Research quantum computing trends in 2026")
print(result["writer"]["article"])
```

### Step 6: Share it

```bash
# Pack as portable archive
awp pack research-pipeline/
# → Creates research-pipeline.awp.zip

# Or publish to ClawHub
clawhub publish research-pipeline/

# Anyone can install and run it
clawhub install research-pipeline
awp run research-pipeline/ --task "Research AI safety"
```

## Platform Independence

AWP separates **what** a workflow does from **how** it runs.

The YAML configs, prompts, and schemas are the same everywhere.
Only `agent.py` varies by platform -- and even that follows the
`AWPAgent` interface:

```python
from awp.agent import AWPAgent

class Agent(AWPAgent):
    @property
    def name(self) -> str:
        return "researcher"

    def run(self, task: str, state: dict) -> dict:
        # Platform handles LLM calls, tools, memory
        return {self.name: {"findings": "...", "confidence": 0.85}}
```

### Available Runtimes

| Runtime | Language | Deployment | Best for |
|---------|----------|-----------|----------|
| **Standalone** (`awp-protocol`) | Python | Local / Server | Development, prototyping, self-hosted |
| **Cloudflare Workers** | TypeScript | Edge (serverless) | Production, global scale, low latency |

Third-party platforms can provide their own adapters. Each adapter
translates the AWP interface to the platform's native agent system.

## Enterprise Integration -- Bring Your Own Infrastructure

Most companies already have production systems for memory, RAG, tools, and
observability. AWP doesn't replace them -- it **plugs into them**. The protocol
defines clear interfaces at every layer, so you swap implementations without
touching the workflow definition.

### The Principle: Interfaces, Not Implementations

AWP workflows describe **what** an agent needs (`memory.search`, `web.search`,
a skill with domain knowledge). They never describe **how** those capabilities
are implemented. This separation is the key to enterprise adoption:

```
  AWP Workflow (portable)          Your Infrastructure (custom)
  ─────────────────────           ──────────────────────────────
  memory.write  ──────────────→   Pinecone / Weaviate / pgvector / Redis
  memory.search ──────────────→   Your RAG pipeline (embeddings + reranker)
  web.search    ──────────────→   Internal search API / Elasticsearch
  shell.execute ──────────────→   Your sandboxed execution environment
  custom.erp    ──────────────→   SAP / Salesforce / internal APIs
  Skills (.md)  ──────────────→   Your knowledge base / Confluence export
  Tracing       ──────────────→   Datadog / Grafana / your OTEL collector
```

### How It Works in Practice

**1. Replace the Memory Backend**

AWP defines a standard memory interface (`memory.read`, `memory.write`,
`memory.search`). The standalone runtime uses file-based storage. Your company
replaces it with a single MCP tool file:

```python
# mcp/memory_search.py -- overrides the built-in memory.search
from mcp.server.fastmcp import FastMCP
import your_vector_db  # Pinecone, Weaviate, Qdrant, pgvector, ...

app = FastMCP("memory")

@app.tool("memory.search")
def search(*, query: str, top_k: int = 5, namespace: str = "default") -> dict:
    """Semantic search across company knowledge base."""
    results = your_vector_db.query(
        embedding=embed(query),
        top_k=top_k,
        namespace=namespace
    )
    return {"ok": True, "status": 200, "data": {"results": results}, "error": None}
```

Drop this file into `mcp/` and every agent in the workflow that calls
`memory.search` now queries your vector database. No YAML changes. No
agent code changes. The workflow is identical -- only the backend differs.

**2. Plug In Your RAG Pipeline**

If your company has a sophisticated RAG system (chunking, embeddings, reranking,
hybrid search), expose it as a custom MCP tool:

```python
# mcp/knowledge_base.py
@app.tool("kb.query")
def query(*, question: str, sources: list[str] = [], rerank: bool = True) -> dict:
    """Query the company knowledge base with RAG."""
    chunks = your_rag_pipeline.retrieve(question, sources=sources)
    if rerank:
        chunks = your_reranker.rerank(question, chunks)
    return {"ok": True, "status": 200, "data": {"chunks": chunks}, "error": None}
```

Agents declare `kb.query` in their `tools.allowed` list, and the existing
RAG infrastructure is available to every workflow -- without rebuilding anything.

**3. Connect Your Internal Tool Ecosystem**

Most enterprises have internal APIs, ERPs, ticketing systems, and databases.
Each becomes an MCP tool:

```python
# mcp/erp_connector.py     → erp.query_orders, erp.update_status
# mcp/jira_ops.py           → jira.create_ticket, jira.search
# mcp/salesforce.py          → crm.get_account, crm.update_opportunity
# mcp/internal_auth.py       → auth.validate_token, auth.get_permissions
```

These tools live in a shared `mcp/` library that all workflows can reference.
API keys are managed via `secrets.yaml` -- the LLM never sees credentials.

**4. Inject Company Knowledge via Skills**

Your compliance rules, coding standards, product documentation, or domain
expertise become Skills -- Markdown files injected into the agent's context:

```
my-workflow/
  skills/
    company-policies/
      SKILL.md              ← exported from Confluence / Notion
    product-catalog/
      SKILL.md              ← generated from your PIM system
    coding-standards/
      SKILL.md              ← your internal style guide
```

Skills can be generated from existing documentation, exported from wikis,
or maintained as living documents. They give every agent in the workflow
access to institutional knowledge without fine-tuning.

**5. Route Observability to Your Stack**

AWP's observability layer (L4) emits OpenTelemetry-compatible traces and
metrics. Point them at your existing collector:

```yaml
# workflow.awp.yaml
observability:
  tracing:
    enabled: true
    exporter: otlp
    endpoint: "https://otel-collector.internal:4317"
  metrics:
    enabled: true
    exporter: prometheus
    endpoint: "https://prometheus.internal:9090"
```

Every agent execution, tool call, and state transition shows up in your
Datadog, Grafana, or Splunk dashboards -- the same monitoring your team
already uses.

### Enterprise Integration Summary

| Your System | AWP Integration Point | How |
|-------------|----------------------|-----|
| Vector DB (Pinecone, Weaviate, ...) | `memory.*` tools | Override in `mcp/` |
| RAG Pipeline | Custom MCP tool (`kb.query`) | Add to `mcp/` |
| Internal APIs / ERP / CRM | Custom MCP tools | Add to `mcp/` |
| Knowledge Base / Wiki | Skills (`.md` files) | Export to `skills/` |
| Auth / SSO | Secrets + custom tools | `secrets.yaml` + `mcp/` |
| Observability (Datadog, Grafana) | OTEL exporter config | `workflow.awp.yaml` |
| Sandboxing / Security | Custom sandbox config | `agent.awp.yaml` |
| LLM Provider (Azure OpenAI, Bedrock) | Runtime config | `.env` or `secrets.yaml` |

**The bottom line:** AWP workflows are portable descriptions of *what* agents
should do. Your infrastructure decides *how* they do it. Teams write workflows
once and run them against dev, staging, and production backends by swapping
only the `mcp/` implementations and environment config -- the YAML never changes.

## MCP Tools -- Generate, Register, Use

AWP agents interact with the outside world through **MCP tools** -- functions
identified by a Fully Qualified Name (`namespace.action`) that return a standard
result format. Tools are declared per agent in `agent.awp.yaml` and resolved at
runtime by the `ToolRegistry`.

### Built-in Tools

The AWP runtime ships with these tools out of the box:

| Tool | Description |
|------|-------------|
| `web.search` | Web search via DuckDuckGo (no API key needed) |
| `http.request` | Arbitrary HTTP requests (GET, POST, ...) |
| `file.read` / `file.write` / `file.list` | File system operations |
| `shell.execute` | Sandboxed shell commands |
| `memory.read` / `memory.write` / `memory.search` | Persistent memory |
| `arithmetic.add` / `subtract` / `multiply` / `divide` | Basic math |

### Declaring Tools for an Agent

```yaml
# In agent.awp.yaml
tools:
  execute: true
  max_calls: 15
  allowed:
    - web.search
    - http.request
    - memory.*        # glob patterns work
```

### Custom MCP Tools

For domain-specific functionality, create custom tools in the `mcp/` directory:

```python
# mcp/legal_search.py
from mcp.server.fastmcp import FastMCP

app = FastMCP("legal")

@app.tool("legal.search_cases")
def search_cases(*, query: str, court: str = "BGH", max_results: int = 10) -> dict:
    """Search court decisions by keyword."""
    try:
        # ... implementation ...
        return {"ok": True, "status": 200, "data": {"cases": [...]}, "error": None}
    except Exception as e:
        return {"ok": False, "status": 500, "data": {}, "error": str(e)}
```

Custom tools are auto-discovered from `mcp/` at runtime. They can override
built-in tools by using the same FQN.

### Tool Secrets -- API Keys Without Exposing Them to the LLM

Tools that need API keys declare them in the decorator. The runtime injects them
via a `_secrets` channel that the LLM never sees:

```python
@app.tool("search.query", secrets=["SEARCH_API_KEY"])
def query(*, q: str, max_results: int = 10, _secrets: dict = {}) -> dict:
    api_key = _secrets["SEARCH_API_KEY"]    # injected by runtime
    # ...
```

Provide values in `secrets.yaml` (gitignored):

```yaml
secrets:
  SEARCH_API_KEY: "sk-abc123"
  AUTH_TOKEN: "{{ env.PROD_AUTH_TOKEN }}"   # reference env var
```

Resolution priority: `secrets.yaml` > `.env` > `os.environ`.

## Skills -- Domain Knowledge for Agents

Skills are **Markdown files** that get injected into an agent's system prompt at
runtime. They provide domain expertise, rules, and reference data that the LLM
needs to do its job well.

```
                      System Prompt Assembly
                      ─────────────────────
                      ┌─────────────────────────────┐
                      │ 1. SYSTEM_PROMPT.md (base)   │  ← agent role & instructions
                      │ 2. Skills (injected)         │  ← domain knowledge
                      │ 3. MEMORY.md (if enabled)    │  ← long-term memory
                      └─────────────────────────────┘
```

### Skill Locations

1. **Project-level** -- `{workflow}/skills/{skill_name}/SKILL.md` (all agents)
2. **Agent-level** -- `{agent}/workflow/skills/*.md` (single agent)

### Generating Skills

When the AI generates a workflow, it asks whether domain knowledge is needed.
If yes, it generates a `SKILL.md` with relevant domain expertise:

> "Build a deep-research workflow for cloud security audits, with domain knowledge."

The AI generates `skills/cloud-security/SKILL.md` containing relevant frameworks,
compliance controls, and remediation patterns.

### Skills via Extensions

AWP supports **extensions** -- domain-specific overlays that inject skills, tools,
and rules into generated workflows:

| Extension | Domain | Injected Skills |
|-----------|--------|----------------|
| `financial.md` | Finance | `financial_regulations`, `disclaimer` |
| `devops.md` | DevOps/Infra | Safety procedures, rollback policies |

Tell the AI: *"Build a portfolio workflow using the financial extension"* -- and
the extension's skills, tools, and rules are automatically merged.

## Code Mode -- Write Code, Not Tool Calls

When an agent needs many tools, the classic one-tool-at-a-time approach burns
tokens and LLM roundtrips. **Code Mode** is the alternative: the agent writes
code against a typed SDK that wraps all allowed tools as methods.

```
Classic:  Agent → LLM → tool("web.search") → result → LLM → tool("file.write") → result → LLM
Code:     Agent → LLM → generates code block → sandbox executes → result → LLM
```

### Configuration

```yaml
# In agent.awp.yaml
capabilities:
  codemode:
    enabled: true
    language: typescript      # typescript | python | javascript
    sdk_surface:
      mode: auto              # all allowed tools → SDK methods
    execution:
      timeout: 30
      capture_console: true
  sandbox:
    type: isolate             # or subprocess, docker
    constraints:
      max_memory_mb: 128
      max_cpu_seconds: 30
```

### Why Code Mode?

| | Classic Mode | Code Mode |
|---|-------------|-----------|
| **Token usage** | ~200 tokens/tool x N tools | SDK types once (~500 tokens total) |
| **LLM roundtrips** | 1 per tool call | 1 total |
| **Best for** | Simple flows, few tools | Complex orchestration, many tools |

Code Mode is a **protocol feature**. Each runtime implements it with its own sandbox:

| Runtime | Sandbox | SDK Transport |
|---------|---------|---------------|
| Python (standalone) | `subprocess` | In-process calls |
| Cloudflare Workers | `isolate` (V8) | RPC stubs |
| Docker | `docker` | HTTP on localhost |

## Three Ways to Build Workflows

### 1. AI-Generated (Skill)

Tell any AI assistant with the AWP skill installed:

> "Build a customer support workflow with triage, research, and response agents.
>  Use memory for case history. Compliance level L3."

The AI gathers requirements, builds a plan, waits for your approval, generates
all files, validates against 24 rules (R1-R24), and reports the compliance level.

### 2. Manual (YAML)

Create the files yourself following the spec:

```yaml
# workflow.awp.yaml
awp: "1.0.0"
workflow:
  name: my-workflow
  version: "1.0.0"
  description: "My custom workflow"
orchestration:
  engine: dag
  graph:
    - id: my_agent
      agent: my_agent
      depends_on: []
  execution:
    mode: sequential
    timeout:
      per_agent: 120
      total: 300
state:
  persistence:
    enabled: false
  sharing:
    strategy: full
```

Validate with: `awp validate my-workflow/`

### 3. ClawHub (Community)

```bash
clawhub search awp                    # Find AWP workflows
clawhub install research-pipeline     # Install one
awp run research-pipeline/            # Run it
clawhub publish my-workflow/          # Share your own
```

## Compliance Levels

Workflows declare what they need. Runtimes declare what they support.

| Level | Name | What it adds |
|-------|------|-------------|
| **L0** | Core | Manifest + 1 agent + output contract |
| **L1** | Composable | Multi-agent DAG + state sharing |
| **L2** | Communicative | Message bus for agent-to-agent messaging |
| **L3** | Memorable | Multi-tier memory (long-term + daily logs) |
| **L4** | Observable | Tracing + metrics + audit trail |
| **L5** | Enterprise | All above + security + circuit breaker |

Start at L0. Add layers as your workflow grows.

## What AWP Unifies

| Concern | Without AWP | With AWP |
|---------|------------|----------|
| Agent definition | Framework-specific classes | `agent.awp.yaml` -- portable YAML |
| Orchestration | Hardcoded in Python | `orchestration.graph` -- declarative DAG |
| Tool access | Framework-specific wrappers | MCP-compatible tool protocol |
| State sharing | Ad-hoc dict passing | Output contracts with `shareable` fields |
| Memory | Custom per-project | 4-tier standard (long-term, daily, episodic, semantic) |
| Communication | Not standardized | Message bus with typed channels |
| Observability | Manual logging | OpenTelemetry-compatible tracing + metrics |
| Validation | None (runtime errors) | 24 rules checked before execution (R1-R24) |
| Portability | Zero | `.awp.zip` + ClawHub registry |

## Repository Structure

```
agent-workflow-protocol/
  install.sh                  Linux/macOS installer with LLM config wizard
  install.ps1                 Windows PowerShell installer
  install.bat                 Windows batch installer
  skill.zip                   Packaged AWP skill (portable)
  docs/                       Complete protocol reference
  primer/                     Introduction and tutorials
  spec/                       Normative specification (RFC 2119)
  schemas/                    JSON Schemas for validation
  examples/                   Runnable example workflows (L0-L5)
  skill/                      Build skill for AI assistants
    adapters/                 Platform adapters (standalone, Cloudflare, ClawHub)
    extensions/               Domain extensions (financial, devops)
    templates/                File templates for generation
    references/               Condensed docs for AI context
  reference/                  Python reference implementation
    python/                   awp-protocol package (parser, validator, runtime)
  conformance/                Conformance test suite
  assets/                     Logo and media
```

## CLI Reference

```bash
awp run <workflow-dir> --task "..."      # Run a workflow
awp validate <workflow-dir>              # Validate structure and rules (R1-R24)
awp compliance <workflow-dir> --level L3 # Check compliance level
awp visualize <workflow-dir> --format mermaid  # Visualize the agent DAG
awp pack <workflow-dir>                  # Pack as .awp.zip for sharing
awp identity-card <agent.awp.yaml>      # Show agent capabilities
```

## Quick Links

| Resource | Start here if you... |
|----------|---------------------|
| [Docs](docs/) | Want the complete protocol reference |
| [Primer](primer/) | Are new to AWP and want to understand the concepts |
| [Quickstart](primer/quickstart.md) | Want to build your first workflow in 5 minutes |
| [Specification](spec/versions/1.0/spec.md) | Need the normative technical specification |
| [Examples](examples/) | Want to see complete, runnable workflows |
| [Skill](skill/SKILL.md) | Want AI to generate workflows for you |
| [Cloudflare Adapter](skill/adapters/cloudflare-dynamic-workers.md) | Want to deploy on Cloudflare Workers |
| [ClawHub Adapter](skill/adapters/clawhub.md) | Want to publish workflows to ClawHub |
| [FAQ](primer/faq.md) | Have questions |

## License

MIT License. See [LICENSE](LICENSE).
