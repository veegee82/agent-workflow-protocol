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
