# AWP Architecture Overview

## Protocol Structure

AWP workflows are defined by two YAML documents and supporting files:

```
workflow.awp.yaml          -- Manifest (Layer 0) + global config
agents/{id}/agent.awp.yaml -- Agent Identity (Layer 1) + capabilities
```

## 7-Layer Model

```
Layer 6: OBSERVABILITY     -- Metrics, traces, health-checks, audit logs
Layer 5: ORCHESTRATION     -- DAG topology, execution modes, loops, conditions
Layer 4: MEMORY & STATE    -- State model, persistence, memory tiers, output contracts
Layer 3: COMMUNICATION     -- Message Bus, channels, message envelope, patterns
Layer 2: CAPABILITIES      -- Tools (MCP), skills, data sources, sandbox
Layer 1: AGENT IDENTITY    -- Name, role, LLM config, prompt, output schema
Layer 0: MANIFEST          -- Workflow metadata, version, dependencies, runtime
```

## Orchestration Engines

AWP supports two orchestration engines at Layer 5:

| Engine | Philosophy | Agent Definition | Best For |
|--------|-----------|-----------------|----------|
| **DAG** | Static graph, defined before run | All agents defined in `agent.awp.yaml` | Predictable pipelines with known steps |
| **Delegation Loop** | Dynamic, decided at runtime by LLM | Manager: static, Workers: ephemeral | Open-ended tasks where steps emerge during execution |

The two engines can be composed: a DAG node can contain a delegation loop as an inner step.

## Data Flow: DAG Engine

```
User Task
    |
    v
Orchestrator reads workflow.awp.yaml
    |
    v
Topological sort of orchestration.graph
    |
    v
For each execution batch (parallel where possible):
    |
    +---> Agent.run(task, state)
    |       1. Load agent.awp.yaml + workflow artifacts
    |       2. Run preprocessor (if enabled)
    |       3. Inject memory (MEMORY.md) into prompt
    |       4. Collect inter-agent messages
    |       5. Gather previous agent outputs (via share_input)
    |       6. Call LLM with tools
    |       7. Parse response against output.contract
    |       8. Update state[agent_id] = parsed_result
    |       9. Write to daily log (if memory enabled)
    |
    v
Next batch (agents whose dependencies are satisfied)
    |
    v
Final state contains all agent outputs
```

## Data Flow: Delegation Loop Engine

```
User Task
    |
    v
Orchestrator reads workflow.awp.yaml (engine: delegation_loop)
    |
    v
Manager agent receives task + rolling summary
    |
    v
Manager decides: DELEGATE | COMPLETE | FAIL
    |
    +---> DELEGATE: Manager generates delegation envelopes
    |       1. Create ephemeral workers with instructions, skills, tools
    |       2. Workers execute in parallel (fan-out)
    |       3. Two-tier validation (deterministic + LLM semantic)
    |       4. Stall detection (confidence delta over window)
    |       5. Update rolling summary
    |       6. Check budget limits
    |       7. Next iteration -> back to Manager
    |
    +---> COMPLETE: Return final aggregated result
    |
    +---> FAIL: Return error with partial results
```

## Budget System (A2+)

The delegation loop uses a budget system to bound resource consumption:

```yaml
budget:
  max_loops: 20              # Maximum manager iterations
  max_total_workers: 30      # Total workers across all iterations
  max_total_tokens: 1000000  # LLM token limit
  max_wall_time: 600         # Wall clock seconds
  max_tool_calls: 200        # Total tool invocations
  max_depth: 5               # Recursive sub-delegation depth limit
```

For recursive delegation (A4), the invariant `sum(children) + self <= allocation` is enforced deterministically by the runtime, not by the LLM.

## Dual Logging Structure

The delegation loop produces both JSON (machine-readable) and Markdown (human-readable) artifacts:

```
workspace/runs/{run_id}/
├── RUN_SUMMARY.md                 # Human-readable overview
├── run_manifest.json              # Machine-readable config
├── iterations/
│   └── 001/
│       ├── ITERATION_SUMMARY.md   # What happened (Markdown)
│       ├── manager_decision.json  # Manager output (JSON)
│       ├── budget_snapshot.json   # Budget state (JSON)
│       └── delegations/
│           └── worker_a/
│               ├── envelope.json  # Worker input
│               ├── result.json    # Worker output
│               └── RESULT.md      # Human-readable result
├── history/
│   ├── ROLLING_SUMMARY.md         # Rolling summary (Markdown)
│   └── rolling_summary.json       # Rolling summary (JSON)
└── artifacts/
    ├── skills/                    # Generated skills
    └── tools/                     # Generated tools (A3+)
```

Configure via `logging.format: dual | json | md`.

## File Structure

```
{workflow-name}/
├── workflow.awp.yaml               -- Manifest
├── agents/
│   └── {agent_id}/
│       ├── agent.awp.yaml          -- Agent config
│       ├── agent.py                -- Agent class (Python ref impl)
│       └── workflow/
│           ├── instructions/
│           │   └── SYSTEM_PROMPT.md
│           ├── prompt/
│           │   └── 00_INTRO.md
│           ├── output_schema/
│           │   └── output_schema.json
│           ├── output_schema_desc/
│           │   └── output_schema_desc.json
│           ├── skills/             -- Agent-specific skills (optional)
│           └── preprocessor/       -- Data preprocessing (optional)
├── mcp/                            -- Custom MCP tools (optional)
├── skills/                         -- Project-level skills (optional)
├── workspace/                      -- Memory (created at runtime)
│   ├── MEMORY.md                   -- Long-term memory
│   └── memory/                     -- Daily logs
└── data/                           -- Input/output/state (optional)
```

## Key Concepts

### Output Contract

The `output.contract` in `agent.awp.yaml` is the single source of truth for what an agent produces. From it:

- `output_schema.json` is generated (JSON Schema draft-07)
- `output_schema_desc.json` is generated (field descriptions)
- `share_input` references are validated (R8)
- The `confidence` field is mandatory (R17)

### State Sharing

Agents share data through the state dictionary:

1. Agent A declares fields with `shareable: true` in its output.contract
2. Agent B lists `share_input: {agent_a: [field1, field2]}` in the graph
3. At runtime, Agent B receives Agent A's shareable outputs in its context

### Tool Calling

AWP uses MCP-compatible tool calling:

1. Agent's LLM returns tool call requests
2. Runtime executes tools via the tool registry
3. Tool results (standard format: `{ok, status, data, error, log}`) are fed back
4. LLM continues with tool results in context
5. This loops until the LLM produces a final response

### Memory Tiers

| Tier | Storage | Purpose | Persistence |
|------|---------|---------|-------------|
| Long-term | MEMORY.md | Curated facts, preferences | Permanent |
| Working | memory/YYYY-MM-DD.md | Daily agent logs | 30-90 days |
| Episodic | agent_outputs/*.json | Agent output history | 30 days |
| Semantic | Vector DB | Embedding-based search | Configurable |

### Autonomy Levels

| Level | Name | Core Requirement |
|-------|------|-----------------|
| A0 | AWP/Prescribed | Static DAG + Predefined Agents + Fixed Tools |
| A1 | AWP/Adaptive | A0 + Conditional Execution + Loops + Fan-out |
| A2 | AWP/Delegating | A1 + Dynamic Worker Spawning + Budget |
| A3 | AWP/Self-Tooling | A2 + Runtime Tool Creation + Safety Envelope |
| A4 | AWP/Self-Organizing | A3 + Recursive Delegation + Budget Distribution + Observability |

Cross-cutting (all levels): Communication, Memory, Observability, Security
