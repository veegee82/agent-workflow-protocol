# Docker Compose for AI Agents: How We Built an Open Standard for Multi-Agent Workflows

*Why every team building multi-agent systems keeps reinventing the same glue — and how AWP fixes it.*

---

## The Problem Nobody Talks About

You've built your first multi-agent system. A planner breaks down tasks, a researcher gathers data, a writer produces the report. It works beautifully — on your laptop, in your framework, with your custom YAML format.

Now try handing it to someone else.

They use a different orchestration framework. Different state management. Different tool integration. Your workflow is dead on arrival. You've just experienced what we call **the fragmentation problem**.

Today's AI ecosystem has no shortage of standards — but each one covers only a sliver of what a complete multi-agent workflow actually needs:

| Standard | What It Covers | What's Missing |
|----------|---------------|----------------|
| **MCP** | Tool access for LLMs | No agents, no orchestration, no state |
| **A2A** | Agent-to-agent communication | No orchestration, no memory, no tools |
| **OpenAPI** | HTTP API descriptions | No agent concept, no DAG structure |
| **LangGraph** | State machines for agents | Proprietary, not portable |
| **CrewAI** | Agent role definitions | No formal orchestration, no observability |

Every team ends up inventing their own glue. The result? Workflows locked to a single runtime, impossible to share, and difficult to audit.

We decided to fix this.

---

## The "Aha" Moment: Docker Compose for Agents

The breakthrough came from an analogy that now seems obvious.

**Docker Compose** doesn't run containers. It *describes* how containers relate — what volumes they mount, what networks they share, what order they start in. The Docker engine reads the Compose file and does the actual work. The description is the artifact. The runtime is interchangeable.

What if we could do the same for multi-agent workflows?

A single YAML file that describes **everything**: agents, their tools, how they communicate, how state flows between them, how they're orchestrated, and how you observe them running. Any compliant runtime reads the file and executes it. Switch from Python to TypeScript, from local to cloud — the workflow stays the same.

That's AWP: the **Agent Workflow Protocol**.

---

## Designing the Architecture: Seven Layers

We structured AWP as a 7-layer model. Each layer builds on the one below, but none depends on layers above. You adopt only what you need.

```
┌─────────────────────────────────────────┐
│  Layer 6: OBSERVABILITY                 │  Metrics, tracing, audit logs
├─────────────────────────────────────────┤
│  Layer 5: ORCHESTRATION                 │  DAG or delegation loop
├─────────────────────────────────────────┤
│  Layer 4: MEMORY & STATE                │  State model, persistence
├─────────────────────────────────────────┤
│  Layer 3: COMMUNICATION                 │  Message bus, typed channels
├─────────────────────────────────────────┤
│  Layer 2: CAPABILITIES                  │  Tools (MCP), skills, sandbox
├─────────────────────────────────────────┤
│  Layer 1: AGENT IDENTITY                │  Name, role, LLM config, prompt
├─────────────────────────────────────────┤
│  Layer 0: MANIFEST                      │  Workflow metadata, version
└─────────────────────────────────────────┘
```

**Layers 0 and 1 are required.** Everything else is optional. A "hello world" workflow is under 10 lines of YAML. A production enterprise workflow with security, observability, and dynamic delegation uses all seven layers — but the format is the same.

---

## Autonomy as a Spectrum

One of AWP's most important design decisions: **autonomy is not binary**. We defined five levels:

| Level | Name | What It Means | Example |
|-------|------|--------------|---------|
| **A0** | Prescribed | Fixed agents, fixed graph, fixed tools | `planner → researcher → writer` |
| **A1** | Adaptive | Conditional branching, loops, fan-out | Same pipeline, but skip writer if score < 0.7 |
| **A2** | Delegating | Manager dynamically spawns workers | Manager decides at runtime what workers to create |
| **A3** | Self-Tooling | Agents create new tools at runtime | A tool-builder agent generates scoring functions |
| **A4** | Self-Organizing | Recursive delegation with budget control | Managers delegate to sub-managers, budgets split recursively |

The key insight: **communication, memory, and observability are orthogonal to autonomy**. A simple A0 pipeline can have full observability. A complex A4 system *must* have it.

---

## Show Me the Code

### A Minimal Workflow (A0)

```yaml
awp: "1.0.0"

workflow:
  name: hello-world
  version: "1.0.0"
  description: "Simple greeting workflow"

orchestration:
  graph:
    - id: greeter
      agent: greeter
      depends_on: []
      share_output:
        - greeting
        - tone

state:
  model: shared_dict
  sharing:
    strategy: full
```

That's it. One agent, one node in the graph, shared state. Under 20 lines.

### A Research Pipeline (A1)

```yaml
awp: "1.0.0"

workflow:
  name: research-pipeline
  version: "1.0.0"
  description: "Multi-agent research pipeline with state sharing"

orchestration:
  graph:
    - id: planner
      agent: planner
      depends_on: []
      share_output: [research_questions, search_strategy]

    - id: researcher
      agent: researcher
      depends_on: ["planner"]
      share_output: [findings, sources]

    - id: writer
      agent: writer
      depends_on: ["researcher"]
      share_output: [report]

state:
  model: shared_dict
  sharing:
    strategy: selective
```

Three agents. A DAG: planner → researcher → writer. The researcher gets the planner's output automatically. The writer gets the researcher's findings. No custom glue code.

### Dynamic Delegation (A2)

```yaml
awp: "1.0.0"

workflow:
  name: delegation-loop-research
  version: "1.0.0"

orchestration:
  engine: delegation_loop

  delegation_loop:
    manager: agents/manager

    worker_policy:
      enforced:
        sandbox:
          type: subprocess
          max_memory_mb: 512
          network: false
        rate_limiting:
          max_llm_calls_per_minute: 30

    budget:
      max_loops: 5
      max_total_workers: 10
      max_total_tokens: 500000
      max_wall_time: 300
```

Now the manager agent **dynamically decides** what workers to spawn, what instructions to give them, and what tools they can use — all within hard budget constraints. No static graph. The manager orchestrates at runtime.

---

## Two Orchestration Engines

AWP provides two fundamentally different execution models:

### 1. DAG Engine (A0–A1)
- Static graph defined in YAML
- Topological execution order
- Predictable, auditable, reproducible
- Perfect for pipelines with known steps

```
┌──────────┐     ┌────────────┐     ┌────────┐
│ Planner  │────▶│ Researcher │────▶│ Writer │
└──────────┘     └────────────┘     └────────┘
```

### 2. Delegation Loop Engine (A2–A4)
- Manager spawns workers dynamically
- Workers are ephemeral — no static YAML definition
- Hard budget system prevents runaway costs
- Supports recursive sub-delegation (A4)

```
         ┌──────────┐
         │ Manager  │
         └────┬─────┘
        ┌─────┼─────┐
        ▼     ▼     ▼
   ┌────┴┐ ┌─┴───┐ ┌┴────┐
   │ W1  │ │ W2  │ │ W3  │
   └─────┘ └─────┘ └──┬──┘
                   ┌───┼───┐
                   ▼   ▼   ▼
                  W3a W3b W3c
```

---

## Building the Reference Implementation

The spec is nothing without a runtime. We built a reference implementation in Python that covers the full protocol.

### The Stack

```
CLI (awp validate | run | pack | visualize)
    │
    ├── Parser (YAML → Pydantic models)
    ├── Validator (24 pre-execution rules)
    ├── Runtime
    │   ├── DAG Runner (topological execution)
    │   ├── Delegation Loop Runner (manager-worker)
    │   ├── LLM Client (OpenRouter, OpenAI, Ollama)
    │   ├── Message Bus (inter-agent communication)
    │   ├── Code Executor (sandboxed Python)
    │   └── Dynamic Tool Factory (A3 runtime tools)
    ├── Packager (.awp.zip archives)
    └── Visualizer (Mermaid / ASCII DAG rendering)
```

### Validation: 24 Rules, Zero Ambiguity

Before a single token is generated, AWP validates the workflow against 24 deterministic rules (R1–R24):

- **R1–R5**: Manifest structure and version compatibility
- **R6–R10**: Agent identity and prompt file existence
- **R11–R15**: Graph connectivity, cycle detection, dependency resolution
- **R16–R20**: Tool permissions, output contracts, state sharing
- **R21–R24**: Security boundaries, budget constraints, compliance levels

If validation fails, execution doesn't start. No surprises at runtime.

---

## Testing: From Unit to End-to-End

We built a comprehensive test suite with 15 test modules:

```python
# End-to-end test: parse → validate → visualize → pack → unpack
def test_full_pipeline_hello_world(self):
    wf_dir = EXAMPLES / "01-hello-world"

    # 1. Parse manifest
    manifest = parse_manifest(wf_dir / "workflow.awp.yaml")
    assert manifest.workflow.name == "hello-world"

    # 2. Parse all agents
    agents = {}
    for ad in sorted((wf_dir / "agents").iterdir()):
        awp = ad / "agent.awp.yaml"
        if awp.exists():
            agents[ad.name] = parse_agent(awp)

    # 3. Validate graph
    graph_result = validate_graph(manifest.orchestration)
    assert graph_result.valid

    # 4. Validate contracts
    contract_result = validate_contracts(agents, manifest.orchestration)
    assert contract_result.valid

    # 5. Check autonomy level
    compliance = check_compliance(
        manifest, agents, wf_dir, ComplianceLevel.A0_PRESCRIBED
    )
    assert compliance.level >= ComplianceLevel.A0_PRESCRIBED
```

The test suite covers:

- **Parser tests**: YAML parsing correctness for all 7 layers
- **Validator tests**: All 24 validation rules (valid and invalid fixtures)
- **Runtime tests**: DAG execution, delegation loops, state sharing
- **E2E tests**: All 12 example workflows parsed, validated, and executed
- **Security tests**: Circuit breaker, rate limiting, access control
- **Message bus tests**: Inter-agent communication integrity
- **Conformance tests**: A standardized suite ensuring any runtime implementation behaves identically

---

## What We Learned

### 1. Declarative beats imperative — until it doesn't

YAML descriptions work brilliantly for A0–A1 workflows. But at A2+, agents need to make runtime decisions. The delegation loop engine was our answer: the *structure* is still declarative (budgets, policies, constraints), but the *behavior* is dynamic.

### 2. Budget systems are non-negotiable

Self-organizing agents without hard budget limits are a recipe for disaster. AWP enforces `max_loops`, `max_total_tokens`, `max_wall_time`, and `max_tool_calls` at the protocol level. Not optional. Not configurable away.

### 3. Observability isn't a feature — it's a requirement

At A4 (self-organizing), you *must* have observability. When agents spawn sub-agents that spawn sub-sub-agents, you need tracing, metrics, and audit logs to understand what happened and why. We made this a compliance requirement, not an optional add-on.

### 4. Portability requires discipline

Every time we added a "convenient" runtime-specific feature, we had to ask: "Can a TypeScript runtime implement this identically?" If not, it didn't belong in the spec. The protocol must remain runtime-agnostic.

---

## Try It Yourself

```bash
# Install
pip install awp-protocol

# Validate a workflow
awp validate examples/02-research-pipeline/

# Visualize the DAG
awp visualize examples/02-research-pipeline/ --format mermaid

# Pack for distribution
awp pack examples/02-research-pipeline/ -o research.awp.zip

# Run a workflow
awp run examples/02-research-pipeline/ --task "Research quantum computing"
```

AWP is open source under MIT. The spec, reference implementation, 12 example workflows, and conformance test suite are all on GitHub.

---

## What's Next

AWP 1.0 is the foundation. On the roadmap:

- **TypeScript reference implementation** for Node.js and edge runtimes
- **Workflow registry** for publishing and discovering `.awp.zip` packages
- **Visual workflow builder** for designing AWP workflows graphically
- **Cross-runtime benchmarking** using identical AWP workflows to compare infrastructure components

The multi-agent future needs a common language. AWP is our proposal for what that language should look like.

---

*AWP is an open-source project. Star the repo, try the examples, file issues. The spec belongs to the community.*

*[GitHub: veegee82/agent-workflow-protocol]*
