---
name: awp-workflow-builder
description: >
  Generate complete Agent Workflow Protocol (AWP) compliant multi-agent
  workflows from natural language descriptions. Produces workflow.awp.yaml,
  agent configs, prompts, schemas, and optionally custom tools and skills.
version: "1.0.0"
user-invocable: true
allowed-tools: Read Write Edit Bash Glob Grep
---

# AWP Workflow Builder

## AWP 7-Layer Model

The Agent Workflow Protocol defines seven layers, each building on the previous:

| Layer | Name | Purpose |
|-------|------|---------|
| L0 | Orchestration | DAG-based agent graph, execution modes, timeouts, error handling. |
| L1 | State | Persistent state, sharing strategies, required fields, auto-inject. |
| L2 | Communication | Message bus for inter-agent messaging, channels, direct/broadcast. |
| L3 | Memory | Long-term memory (MEMORY.md), daily logs, search, curation. |
| L4 | Observability | Structured logging, distributed tracing, metrics collection. |
| L5 | Governance | Security audit, rate limiting, circuit breakers, access control. |
| L6 | Extension | Custom MCP tools, project-level skills, hooks, preprocessors. |

## Compliance Levels

| Level | Name | Required Layers | Description |
|-------|------|----------------|-------------|
| L0 Core | Core | L0 | Single agent, basic orchestration. Minimum viable workflow. |
| L1 Composable | Composable | L0 + L1 | Multi-agent DAG with state sharing. |
| L2 Communicative | Communicative | L0-L2 | Inter-agent messaging via message bus. |
| L3 Memorable | Memorable | L0-L3 | Memory tiers for cross-session persistence. |
| L4 Observable | Observable | L0-L4 | Full observability: tracing, metrics, structured logs. |
| L5 Enterprise | Enterprise | L0-L6 | All layers, production-grade governance and extensibility. |

## Platform Features

| Feature | Config Location | Description |
|---------|----------------|-------------|
| Agent DAG | `workflow.awp.yaml` graph | Directed acyclic graph of agents with depends_on edges. |
| State Sharing | graph[].share_output | Fields from an agent's output available to dependents. |
| Execution Modes | execution.mode | sequential, parallel, or conditional execution. |
| MCP Tools | agent.awp.yaml tools | Tool calling via the MCP registry (web, file, shell, etc.). |
| Message Bus | communication.bus | In-memory message passing between agents. |
| Memory | memory.tiers | Long-term (MEMORY.md) and working (daily logs) memory. |
| Skills | workflow skills/ | Markdown knowledge injected into agent system prompts. |
| Preprocessor | agent workflow/preprocessor/ | Data extraction and feature engineering before LLM call. |
| Vision | agent.awp.yaml vision | Image processing via base64-encoded data URLs. |


## STRICT RULES

These rules define compliance requirements for AWP workflows. Rules marked **(recommended for Python)** apply to the Python reference implementation but may be adapted for other platforms.

- **R1:** `workflow.name` MUST match the workflow directory name.
- **R2:** All agent IDs MUST be `snake_case` (lowercase letters, digits, underscores).
- **R3 (recommended for Python):** Every `agent.py` SHOULD define a class named `Agent` that extends `AWPAgent` (or a platform-specific base class).
- **R4 (recommended for Python):** The `Agent.name` property MUST return the same string as the agent ID in the graph.
- **R5:** Every agent in the graph MUST have a corresponding directory under `agents/`.
- **R6:** Every agent directory MUST contain `agent.awp.yaml` and `agent.py`.
- **R7:** Every agent MUST have `workflow/instructions/SYSTEM_PROMPT.md`.
- **R8:** Every agent MUST have `workflow/prompt/00_INTRO.md`.
- **R9:** Every agent MUST have `workflow/output_schema/output_schema.json`.
- **R10:** Every agent MUST have `workflow/output_schema_desc/output_schema_desc.json`.
- **R11:** `depends_on` MUST only reference agent names defined in the same graph.
- **R12:** The agent graph MUST be a DAG (no cycles).
- **R13:** `share_output` fields MUST match keys in the agent's output schema.
- **R14:** Tool names in `tools.allowed` MUST reference registered MCP tools.
- **R15:** If `tools.execute` is false, `tools.allowed` MUST be empty or omitted.
- **R16:** `execution.mode` MUST be one of: `sequential`, `parallel`, `conditional`.
- **R17:** All output schemas MUST include a `confidence` field (number, 0.0-1.0).
- **R18:** All `output_schema.json` files MUST be valid JSON Schema draft-07 with `"type": "object"` at the root.


## Workflow Generation Phases

### Phase 0: Planning

Before generating any files, analyze the user's requirements:

1. **Analyze the requirement.** What is the workflow supposed to do? What data flows between agents?
2. **Design the agent graph.** Identify distinct roles, dependencies, and data flow.
3. **Plan state sharing.** Which fields does each agent produce? Which does each consumer need?
4. **Determine compliance level.** What features are needed? Start at L0 and add layers only as required.
5. **Identify tools.** Which MCP tools does each agent need? (web.search, file.read, etc.)
6. **Plan memory.** Does the workflow benefit from cross-session persistence?
7. **Plan communication.** Do agents need to message each other outside the DAG?

### Phase 1: Requirements Gathering

Confirm with the user:

- Workflow name and description.
- Number and roles of agents.
- Data flow between agents.
- Required tools per agent.
- Memory and communication needs.
- Target compliance level.

If the user provides a brief description, infer reasonable defaults. Ask only if critical information is ambiguous.

### Phase 2: Generate the Project

Generate files in this order:

#### Step 1: Workflow Manifest

Create `{workflow_dir}/workflow.awp.yaml` with:
- `project` section (name, version, description).
- `graph` section (all agents with depends_on and share_output).
- `execution` section (mode, timeouts, error handling).
- `state` section (persistence, sharing strategy).
- Additional sections as needed by compliance level: `memory`, `communication`, `observability`, `security`.
- `logging` section.
- `settings` section (LLM models, runtime config).

Use the template at `templates/workflow.awp.yaml` as a starting point.

#### Step 2: Agent Configurations

For each agent, create `{workflow_dir}/agents/{agent_id}/agent.awp.yaml` with:
- `agent` section (name, description).
- `llm` section (model, temperature, reasoning).
- `tools` section (execute flag, max_calls, allowed list).
- `preprocessor`, `vision`, `memory`, `debug` sections as needed.

Use `templates/agent.awp.yaml` (minimal) or `templates/agent-full.awp.yaml` (full-featured).

#### Step 3: Agent Implementations (Platform-Specific)

For each agent, create `{workflow_dir}/agents/{agent_id}/agent.py`.

AWP is platform-agnostic. The `agent.py` file varies by target runtime.
Choose the appropriate **adapter** based on the target platform:

| Platform | Adapter | Import |
|----------|---------|--------|
| **Standalone (awp-protocol)** | `adapters/standalone.md` | `from awp.agent import AWPAgent` |

**Default:** Use `templates/agent.py` which imports from `awp.agent`.

Read the adapter file in `skill/adapters/` for platform-specific instructions,
then generate `agent.py` accordingly. Third-party platforms can provide their
own adapter files following the same pattern.

#### Step 4: System Prompts

For each agent, create `{workflow_dir}/agents/{agent_id}/workflow/instructions/SYSTEM_PROMPT.md`:
- Clear role description.
- List of responsibilities.
- Available tools (if any) with usage instructions.
- Output format instructions referencing the output schema.

Use `templates/SYSTEM_PROMPT.md` as a starting point.

#### Step 5: Intro Prompts

For each agent, create `{workflow_dir}/agents/{agent_id}/workflow/prompt/00_INTRO.md`:
- Brief task introduction.
- Context about what input the agent receives.

Use `templates/00_INTRO.md` as a starting point.

#### Step 6: Output Schemas

For each agent, create:
- `{workflow_dir}/agents/{agent_id}/workflow/output_schema/output_schema.json` -- JSON Schema draft-07.
- `{workflow_dir}/agents/{agent_id}/workflow/output_schema_desc/output_schema_desc.json` -- Human-readable field descriptions.

All schemas MUST have `"type": "object"` at root and include a `confidence` field. Use `templates/output_schema.json` and `templates/output_schema_desc.json`.

#### Step 7: Custom Tools (if needed)

If the workflow needs custom MCP tools, create `{workflow_dir}/mcp/{tool_file}.py` using the FastMCP pattern. See `templates/mcp-tool.py`.

#### Step 8: Project Skills (if needed)

If the workflow needs shared domain knowledge, create `{workflow_dir}/skills/{skill_name}/SKILL.md`. See `templates/project-skill.md`.

### Phase 3: Validation Checklist

After generating all files, verify:

- [ ] R1: workflow.name matches directory name.
- [ ] R2: All agent IDs are snake_case.
- [ ] R3: All agent.py files define class Agent extending AWPAgent (or platform base).
- [ ] R4: Agent.name property returns the correct agent ID.
- [ ] R5: Every graph agent has a directory under agents/.
- [ ] R6: Every agent directory has agent.awp.yaml and agent.py.
- [ ] R7: Every agent has SYSTEM_PROMPT.md.
- [ ] R8: Every agent has 00_INTRO.md.
- [ ] R9: Every agent has output_schema.json.
- [ ] R10: Every agent has output_schema_desc.json.
- [ ] R11: depends_on references only graph-defined agents.
- [ ] R12: No cycles in the agent graph.
- [ ] R13: share_output fields match output schema keys.
- [ ] R14: tools.allowed references valid MCP tools.
- [ ] R15: tools.execute=false implies empty allowed list.
- [ ] R16: execution.mode is sequential, parallel, or conditional.
- [ ] R17: All output schemas include confidence field.
- [ ] R18: All output_schema.json are valid JSON Schema draft-07 with type: object.

### Phase 4: Summary

Present to the user:

- Workflow name and compliance level.
- Agent graph visualization (text-based DAG).
- Files generated (count and list).
- Compliance badge: `AWP L{N} {Level Name} Compliant`.
- Any assumptions made or recommendations for improvement.


## Templates

The `templates/` directory contains starter files for all workflow components:

| Template | Purpose |
|----------|---------|
| `workflow.awp.yaml` | Complete workflow manifest with all sections. |
| `agent.awp.yaml` | Minimal agent configuration. |
| `agent-full.awp.yaml` | Full-featured agent configuration with all options. |
| `agent.py` | Python agent class (platform-specific, see adapters/). |
| `SYSTEM_PROMPT.md` | System prompt with placeholders. |
| `00_INTRO.md` | Intro prompt with placeholders. |
| `output_schema.json` | Output JSON Schema template. |
| `output_schema_desc.json` | Field description template. |
| `mcp-tool.py` | Custom MCP tool template. |
| `project-skill.md` | Project-level skill template. |

## Extensions (Skill Inheritance)

The `extensions/` directory contains domain-specific customizations that
**extend** this base skill -- like subclass inheritance.  An extension can:

- Override defaults (model, compliance level, temperature)
- Add required agents (e.g., `risk_assessor` for financial workflows)
- Add required output fields (e.g., `data_sources` for every agent)
- Add domain-specific rules (F1, F2, ... or D1, D2, ...)
- Inject content into system prompts (prepend/append/replace)
- Include additional project-level skills
- Include additional custom MCP tools
- Set constraints (deny tools, require memory tiers, min compliance)

### How to Use an Extension

When the user requests a domain-specific workflow (e.g., "build a financial
analysis workflow"), load the appropriate extension alongside this base skill:

1. Load this file (`SKILL.md`) -- base rules and generation process
2. Load the adapter (`adapters/*.md`) -- platform-specific agent.py
3. Load the extension (`extensions/examples/*.md`) -- domain overrides
4. Merge: extension rules are **additive**, defaults are **overridden**

### Available Extensions

| Extension | Domain | Key Features |
|-----------|--------|-------------|
| `extensions/examples/financial.md` | Finance | Risk assessor agent, audit trail, compliance controls |
| `extensions/examples/devops.md` | DevOps | Safety checker agent, rollback plans, shell constraints |

See `extensions/README.md` for the full extension format and how to create
custom extensions.


## ClawHub Integration

This skill and all AWP extensions use ClawHub-compatible YAML frontmatter
and can be published directly to the ClawHub registry.

### Publishing this skill

```bash
clawhub publish skill/
```

### Publishing a generated workflow as a ClawHub skill

After generating a workflow, add a `SKILL.md` with ClawHub frontmatter
at the workflow root and publish:

```bash
awp clawhub init my-workflow/    # generates SKILL.md from workflow.awp.yaml
clawhub publish my-workflow/
```

See `adapters/clawhub.md` for the complete ClawHub integration guide including
packaging workflows, publishing extensions, and discovery tag conventions.


## Adapters

| Adapter | Purpose |
|---------|---------|
| `adapters/standalone.md` | Generate agent.py for the AWP standalone runtime |
| `adapters/clawhub.md` | Publish AWP skills and workflows to ClawHub registry |

Third-party platforms can add their own adapters following the same pattern.


## References

The `references/` directory contains condensed documentation for AI context:

| Reference | Purpose |
|-----------|---------|
| `spec-summary.md` | Condensed AWP specification (~2000 words). |
| `compliance-levels.md` | Quick reference for L0-L5 compliance. |
| `validation-rules.md` | R1-R18 checklist format. |
| `tools-reference.md` | Built-in MCP tool catalog. |
| `architecture.md` | Architecture overview. |
