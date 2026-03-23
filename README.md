# AWP -- Agent Workflow Protocol

An open standard for describing multi-agent workflows.
Declarative. Runtime-agnostic. Portable.

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

AWP fills this gap. It describes a **complete** multi-agent workflow in a
single, portable format that any runtime can execute.

## The Idea

AWP is to agentic workflows what **Docker Compose** is to container stacks:

- A declarative YAML describes the entire system
- Services (= Agents) are defined with their dependencies
- Volumes (= Memory), Networks (= Communication), Health-Checks (= Observability)
- Portable across different container runtimes (= agent platforms)

One manifest. Any runtime. Full workflow.

## The 7-Layer Model

AWP organizes a workflow into seven layers. Each layer answers one question:

```
 Layer 6  OBSERVABILITY     How do I monitor this workflow?
 Layer 5  ORCHESTRATION     In what order and under what conditions?
 Layer 4  MEMORY & STATE    What does the workflow remember?
 Layer 3  COMMUNICATION     How do agents talk to each other?
 Layer 2  CAPABILITIES      What can an agent do? (tools, skills)
 Layer 1  AGENT IDENTITY    Who is this agent?
 Layer 0  MANIFEST          What is this workflow?
```

You start at the bottom. Layer 0 (manifest) and Layer 1 (agent identity)
are always required. Everything above is opt-in -- add layers only when
you need them. A simple single-agent workflow uses two layers. A
production enterprise system uses all seven.

## From Idea to Workflow -- The Red Thread

### Step 1: You have an idea

> "I need a research pipeline that plans, investigates, and writes articles."

### Step 2: The AWP Skill generates your workflow

AWP includes a **build skill** -- a set of instructions that any AI assistant
(Claude, GPT, Clawdbot, etc.) can use to generate a complete AWP workflow
from your description.

Tell your AI:

> "Build an AWP research pipeline with three agents: planner, researcher, writer."

The AI reads the AWP skill and produces:

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

### Step 3: Run it

With the standalone AWP runtime:

```python
from awp.runtime import WorkflowRunner

runner = WorkflowRunner("research-pipeline")
result = runner.run("Research quantum computing trends in 2026")
print(result["writer"]["article"])
```

Or via CLI:

```bash
pip install awp-protocol
awp run research-pipeline/ --task "Research quantum computing"
```

### Step 4: Share it

Pack your workflow as a portable archive:

```bash
awp pack research-pipeline/
# Creates research-pipeline.awp.zip
```

Or publish to ClawHub (the open skill registry):

```bash
clawhub publish research-pipeline/
```

Anyone can install and run it:

```bash
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

Any platform that implements the `AWPAgent` interface can run AWP
workflows. The standalone runtime included in `awp-protocol` proves
this works without any external framework.

Third-party platforms provide their own adapters. Each adapter
translates the AWP interface to the platform's native agent system.

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

These are registered automatically when the runtime starts. No extra files needed.

### Declaring Tools for an Agent

In `agent.awp.yaml`, list which tools an agent may use:

```yaml
tools:
  execute: true
  max_calls: 15
  allowed:
    - web.search
    - http.request
    - memory.*        # glob patterns work
```

If `allowed` is empty and `execute` is `true`, the agent can use all registered tools.

### Custom MCP Tools

For domain-specific functionality, create custom tools in the `mcp/` directory
at the workflow root. Use the **FastMCP decorator pattern**:

```
my-workflow/
  mcp/
    legal_search.py     ← custom tool
    pdf_extract.py      ← custom tool
  agents/
    ...
```

```python
# mcp/legal_search.py
from mcp.server.fastmcp import FastMCP

app = FastMCP("legal")

@app.tool("legal.search_cases")
def search_cases(*, query: str, court: str = "BGH", max_results: int = 10) -> dict:
    """Search court decisions by keyword.

    Args:
        query: Search query.
        court: Court filter (BGH, OLG, AG).
        max_results: Maximum results to return.
    """
    try:
        # ... implementation ...
        return {"ok": True, "status": 200, "data": {"cases": [...]}, "error": None}
    except Exception as e:
        return {"ok": False, "status": 500, "data": {}, "error": str(e)}
```

**Rules for custom tools:**
- FQN must follow `namespace.action` format
- Custom namespaces must NOT collide with reserved ones (`web`, `http`, `file`,
  `shell`, `agent`, `memory`, `arithmetic`)
- Return the standard `{"ok", "status", "data", "error"}` format
- Filenames must not start with `_`

### Auto-Discovery at Runtime

The `ToolRegistry` automatically discovers and registers tools:

```
1. _register_builtins()              → web.search, file.read, memory.*, ...
2. _discover_custom_tools(mcp/)      → scans @app.tool() decorators
3. get_definitions(agent.allowed)    → filters to agent's allowed list
```

Custom tools in `mcp/` can **override** built-in tools by using the same FQN.
For example, a `mcp/web_search.py` with `@app.tool("web.search")` replaces the
default DuckDuckGo implementation with your own.

### Tool Implementation Mode (Standalone Workflows)

When generating a workflow with the AWP Skill, you can enable **tool implementation
mode**. This generates working MCP implementations for every referenced built-in
tool, making the workflow fully self-contained:

```
my-workflow/
  mcp/
    web_search.py         ← generated: DuckDuckGo search
    http_request.py       ← generated: HTTP client
    memory_write.py       ← generated: file-based memory
    memory_search.py      ← generated: keyword search
  agents/
    ...
```

This is useful when you don't want to depend on the AWP runtime's built-in tools
or need to customize the implementation (e.g., use a different search API).

To enable, tell the AI skill: *"generate tool implementations"* or *"standalone tools"*.

### End-to-End Example

```python
from awp.runtime.tools import ToolRegistry

# 1. Create registry (discovers mcp/ tools automatically)
registry = ToolRegistry(workflow_dir=Path("my-workflow"))

# 2. See what's available
print(registry.tool_names)
# ['arithmetic.add', ..., 'legal.search_cases', ..., 'web.search']

# 3. Call a tool directly
result = registry.call("web.search", {"query": "quantum error correction 2026"})
print(result)
# {"ok": True, "status": 200, "data": {"results": [...], "count": 5}, "error": None}

# 4. Get OpenAI function-calling definitions for an agent
defs = registry.get_definitions(["web.search", "legal.*"])
# Pass these to the LLM as tool definitions
```

For the full tool reference, see [docs/tools.md](docs/tools.md).

## Skills -- Domain Knowledge for Agents

Skills are **Markdown files** that get injected into an agent's system prompt at
runtime. They provide domain expertise, rules, terminology, or reference data
that the LLM needs to do its job well -- without cramming everything into the
system prompt itself.

### How Skills Work

```
                      System Prompt Assembly
                      ─────────────────────
                      ┌─────────────────────────────┐
                      │ 1. SYSTEM_PROMPT.md (base)   │  ← agent role & instructions
                      │ 2. Skills (injected)         │  ← domain knowledge
                      │ 3. MEMORY.md (if enabled)    │  ← long-term memory
                      └─────────────────────────────┘
```

At runtime, `StandaloneAgent._build_system_prompt()` loads skills from two locations:

1. **Project-level skills** -- `{workflow}/skills/{skill_name}/SKILL.md`
   Shared by all agents in the workflow.
2. **Agent-level skills** -- `{agent}/workflow/skills/*.md`
   Only available to that specific agent.

### Skill File Structure

A skill is a plain Markdown file. Use the template at `skill/templates/project-skill.md`:

```markdown
# Cloud Security Best Practices

## Purpose
Domain knowledge for cloud infrastructure security analysis agents.

## Domain Knowledge
### Core Frameworks
- CIS Benchmarks for AWS, Azure, GCP
- NIST 800-53 security controls
- SOC 2 Type II compliance requirements
...

## Rules
- Always reference the specific CIS control ID when citing a benchmark
- Distinguish between "must" (compliance requirement) and "should" (best practice)
- Flag any publicly accessible storage buckets as critical severity
```

### Project Layout

```
my-workflow/
  skills/
    cloud-security/
      SKILL.md              ← project-level skill (all agents see this)
    compliance-frameworks/
      SKILL.md
  agents/
    researcher/
      workflow/
        skills/
          search-strategy.md  ← agent-level skill (only researcher sees this)
    analyst/
      ...
```

### Generating Skills with the AWP Skill

When the AI generates a workflow via the AWP build skill, it asks whether
domain knowledge is needed (Phase 1, question 7). If yes, it generates a
`SKILL.md` with relevant domain knowledge during Phase 2, Step 8.

Example prompt:

> "Build a deep-research workflow for cloud security audits, with domain knowledge."

The AI generates `skills/cloud-security/SKILL.md` containing relevant frameworks,
compliance controls, severity classifications, and remediation patterns.

### Skills + MCP Tools -- The Combination

Skills and MCP tools serve complementary roles:

| | Skills | MCP Tools |
|---|--------|-----------|
| **What** | Static knowledge (Markdown) | Dynamic actions (Python functions) |
| **When** | Injected into prompt before LLM call | Called by the LLM during execution |
| **Where** | `skills/` directory | `mcp/` directory |
| **Example** | "CIS 2.1.1 requires S3 bucket encryption" | `web.search("AWS S3 encryption best practices")` |

The real power comes from **combining both**. A skill tells the agent *what it
should know*; a tool lets the agent *act on that knowledge*:

```
skills/cloud-security/SKILL.md
  → Agent knows: "CIS 2.1.1 requires encryption at rest for all S3 buckets"

mcp/web_search.py (web.search tool)
  → Agent can: search for the latest AWS security advisories online

mcp/cloud_audit.py (cloud.check_compliance tool)
  → Agent can: query cloud resources against CIS benchmark controls
```

When tool implementation mode is enabled, the AI generates both the skill files
*and* the MCP tool implementations -- a fully self-contained, domain-aware
workflow.

### Skills via Extensions

For reusable domain knowledge, AWP supports **extensions** -- domain-specific
overlays that automatically inject skills, tools, and rules into generated
workflows. Extensions work like class inheritance on top of the base build skill:

```
skill/SKILL.md (base)
  └── extensions/examples/financial.md
        ├── Required agent: risk_assessor
        ├── Additional rules: F1–F7
        ├── Additional skills: financial_regulations, disclaimer
        └── Additional tools: finance.market_data, finance.risk_calc
```

Tell the AI: *"Build a portfolio analysis workflow using the financial extension"*
-- and the extension's skills, tools, and rules are automatically merged.

Available extensions:

| Extension | Domain | Injected Skills |
|-----------|--------|----------------|
| `financial.md` | Finance | `financial_regulations`, `disclaimer` |
| `devops.md` | DevOps/Infra | Safety procedures, rollback policies |

Create your own: copy an existing extension from `skill/extensions/examples/`
and adjust it to your domain.

For the full skill system reference, see [docs/skill-system.md](docs/skill-system.md).

## Three Ways to Build Workflows

### 1. AI-Generated (Skill)

Tell any AI assistant with the AWP skill installed:

> "Build a customer support workflow with triage, research, and response agents.
>  Use memory for case history. Compliance level L3."

The AI generates all files, validates against 18 rules, and reports the
compliance level. This is the fastest path from idea to working workflow.

### 2. Standalone (Manual)

Create the YAML files yourself following the spec:

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

Browse and install pre-built workflows from the ClawHub registry:

```bash
clawhub search awp                    # Find AWP workflows
clawhub install research-pipeline     # Install one
awp run research-pipeline/            # Run it
```

Publish your own workflows for others to use:

```bash
clawhub publish my-workflow/          # Share with the community
```

## Compliance Levels

Workflows declare what they need. Runtimes declare what they support.
If the runtime meets the requirement, execution proceeds.

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
| Validation | None (runtime errors) | 18 rules checked before execution |
| Portability | Zero | `.awp.zip` + ClawHub registry |
| Documentation | Scattered | Self-describing YAML with field descriptions |

## Repository Structure

```
agent-workflow-protocol/
  docs/                     Complete protocol reference
  primer/                   Introduction and tutorials
  spec/                     Normative specification (RFC 2119)
  schemas/                  JSON Schemas for validation
  examples/                 5 runnable example workflows (L0-L5)
  skill/                    Build skill for AI assistants
    adapters/               Platform adapters (standalone, ClawHub)
    extensions/             Domain extensions (financial, devops)
    templates/              File templates for generation
    references/             Condensed docs for AI context
  reference/                Python reference implementation
    python/                 awp-protocol package (parser, validator, runtime)
  conformance/              Conformance test suite
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
| [ClawHub Adapter](skill/adapters/clawhub.md) | Want to publish workflows to ClawHub |
| [FAQ](primer/faq.md) | Have questions |

## Install

```bash
pip install awp-protocol
```

## License

MIT License. See [LICENSE](LICENSE).
