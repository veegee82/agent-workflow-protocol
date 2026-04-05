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

<svg viewBox="0 0 600 380" xmlns="http://www.w3.org/2000/svg" font-family="system-ui, -apple-system, sans-serif" font-size="11">
  <defs><marker id="da" markerWidth="7" markerHeight="5" refX="7" refY="2.5" orient="auto"><path d="M0,0 L7,2.5 L0,5" fill="#4a6fa5"/></marker></defs>
  <!-- User Task -->
  <rect x="200" y="5" width="160" height="30" rx="6" fill="#e8d5f5" stroke="#7b4ea3" stroke-width="1.5"/>
  <text x="280" y="25" text-anchor="middle" font-weight="600" fill="#5a2d82">User Task</text>
  <!-- Orchestrator -->
  <rect x="170" y="55" width="220" height="30" rx="6" fill="#dce6f7" stroke="#4a6fa5" stroke-width="1.5"/>
  <text x="280" y="75" text-anchor="middle" fill="#2a3f5f">Orchestrator reads workflow.awp.yaml</text>
  <!-- Topo sort -->
  <rect x="170" y="105" width="220" height="30" rx="6" fill="#dce6f7" stroke="#4a6fa5" stroke-width="1.2"/>
  <text x="280" y="125" text-anchor="middle" fill="#2a3f5f">Topological sort of graph</text>
  <!-- Agent.run box -->
  <rect x="80" y="160" width="400" height="160" rx="8" fill="#f0faf0" stroke="#5b8c5a" stroke-width="1.5"/>
  <text x="280" y="178" text-anchor="middle" font-weight="700" fill="#2d5a2d">Agent.run(task, state)</text>
  <text x="100" y="196" fill="#555" font-size="10">1. Load agent.awp.yaml + workflow artifacts</text>
  <text x="100" y="211" fill="#555" font-size="10">2. Run preprocessor (if enabled)</text>
  <text x="100" y="226" fill="#555" font-size="10">3. Inject memory (MEMORY.md) into prompt</text>
  <text x="100" y="241" fill="#555" font-size="10">4. Collect inter-agent messages</text>
  <text x="100" y="256" fill="#555" font-size="10">5. Gather previous agent outputs (via share_input)</text>
  <text x="100" y="271" fill="#555" font-size="10">6. Call LLM with tools</text>
  <text x="100" y="286" fill="#555" font-size="10">7. Parse response against output.contract</text>
  <text x="100" y="301" fill="#555" font-size="10">8. Update state[agent_id] = parsed_result</text>
  <text x="100" y="316" fill="#555" font-size="10">9. Write to daily log (if memory enabled)</text>
  <!-- Final -->
  <rect x="150" y="340" width="260" height="30" rx="6" fill="#d5f5e3" stroke="#27ae60" stroke-width="1.5"/>
  <text x="280" y="360" text-anchor="middle" font-weight="600" fill="#1a6b3c">Final state contains all agent outputs</text>
  <!-- Arrows -->
  <line x1="280" y1="37" x2="280" y2="53" stroke="#4a6fa5" stroke-width="1.5" marker-end="url(#da)"/>
  <line x1="280" y1="87" x2="280" y2="103" stroke="#4a6fa5" stroke-width="1.5" marker-end="url(#da)"/>
  <line x1="280" y1="137" x2="280" y2="158" stroke="#4a6fa5" stroke-width="1.5" marker-end="url(#da)"/>
  <line x1="280" y1="322" x2="280" y2="338" stroke="#4a6fa5" stroke-width="1.5" marker-end="url(#da)"/>
  <!-- Loop arrow -->
  <path d="M482,240 Q520,240 520,150 Q520,137 482,137" fill="none" stroke="#999" stroke-width="1" stroke-dasharray="4,2" marker-end="url(#da)"/>
  <text x="535" y="195" fill="#999" font-size="10" text-anchor="middle">next</text>
  <text x="535" y="207" fill="#999" font-size="10" text-anchor="middle">batch</text>
</svg>

## Data Flow: Delegation Loop Engine

<svg viewBox="0 0 620 370" xmlns="http://www.w3.org/2000/svg" font-family="system-ui, -apple-system, sans-serif" font-size="11">
  <defs><marker id="dl" markerWidth="7" markerHeight="5" refX="7" refY="2.5" orient="auto"><path d="M0,0 L7,2.5 L0,5" fill="#4a6fa5"/></marker>
  <marker id="dg" markerWidth="7" markerHeight="5" refX="7" refY="2.5" orient="auto"><path d="M0,0 L7,2.5 L0,5" fill="#27ae60"/></marker>
  <marker id="dr" markerWidth="7" markerHeight="5" refX="7" refY="2.5" orient="auto"><path d="M0,0 L7,2.5 L0,5" fill="#c0392b"/></marker></defs>
  <!-- Task -->
  <rect x="200" y="5" width="180" height="28" rx="6" fill="#e8d5f5" stroke="#7b4ea3" stroke-width="1.5"/>
  <text x="290" y="24" text-anchor="middle" font-weight="600" fill="#5a2d82">User Task</text>
  <!-- Manager -->
  <rect x="170" y="53" width="240" height="36" rx="6" fill="#dce6f7" stroke="#4a6fa5" stroke-width="1.5"/>
  <text x="290" y="68" text-anchor="middle" font-weight="700" fill="#2a3f5f" font-size="12">Manager Agent</text>
  <text x="290" y="82" text-anchor="middle" fill="#5a7aa5" font-size="10">task + rolling summary + budget status</text>
  <!-- Decision diamond -->
  <polygon points="290,108 340,130 290,152 240,130" fill="#fef3cd" stroke="#d4a017" stroke-width="1.5"/>
  <text x="290" y="134" text-anchor="middle" font-weight="600" fill="#856404" font-size="10">DECISION</text>
  <!-- DELEGATE box -->
  <rect x="60" y="170" width="420" height="140" rx="8" fill="#f0faf0" stroke="#5b8c5a" stroke-width="1.5"/>
  <text x="270" y="188" text-anchor="middle" font-weight="700" fill="#2d5a2d">DELEGATE</text>
  <text x="80" y="206" fill="#555" font-size="10">1. Generate delegation envelopes (instructions, skills, tools)</text>
  <text x="80" y="221" fill="#555" font-size="10">2. Workers execute in parallel (fan-out) in sandboxes</text>
  <text x="80" y="236" fill="#555" font-size="10">3. Critique: analyze worker outputs for defects, trigger repairs</text>
  <text x="80" y="251" fill="#555" font-size="10">4. Two-tier validation (deterministic + LLM semantic)</text>
  <text x="80" y="266" fill="#555" font-size="10">5. Evaluation: score results, threshold-based retry/accept/fail</text>
  <text x="80" y="281" fill="#555" font-size="10">6. Stall detection + budget check</text>
  <text x="80" y="296" fill="#555" font-size="10">7. Update rolling summary → next iteration</text>
  <!-- COMPLETE -->
  <rect x="40" y="330" width="200" height="28" rx="6" fill="#d5f5e3" stroke="#27ae60" stroke-width="1.5"/>
  <text x="140" y="349" text-anchor="middle" font-weight="600" fill="#1a6b3c">COMPLETE: final result</text>
  <!-- FAIL -->
  <rect x="340" y="330" width="220" height="28" rx="6" fill="#fde2e2" stroke="#c0392b" stroke-width="1.5"/>
  <text x="450" y="349" text-anchor="middle" font-weight="600" fill="#922b21">FAIL: error + partial results</text>
  <!-- Arrows -->
  <line x1="290" y1="35" x2="290" y2="51" stroke="#4a6fa5" stroke-width="1.5" marker-end="url(#dl)"/>
  <line x1="290" y1="91" x2="290" y2="106" stroke="#4a6fa5" stroke-width="1.5" marker-end="url(#dl)"/>
  <line x1="290" y1="154" x2="290" y2="168" stroke="#4a6fa5" stroke-width="1.5" marker-end="url(#dl)"/>
  <text x="310" y="164" fill="#856404" font-size="10">delegate</text>
  <line x1="240" y1="140" x2="140" y2="328" stroke="#27ae60" stroke-width="1.2" marker-end="url(#dg)"/>
  <text x="170" y="150" fill="#27ae60" font-size="10">complete</text>
  <line x1="340" y1="140" x2="450" y2="328" stroke="#c0392b" stroke-width="1.2" marker-end="url(#dr)"/>
  <text x="415" y="150" fill="#c0392b" font-size="10">fail</text>
  <!-- Loop back -->
  <path d="M482,240 Q560,240 560,70 Q560,53 412,70" fill="none" stroke="#999" stroke-width="1.2" stroke-dasharray="4,2" marker-end="url(#dl)"/>
  <text x="575" y="160" fill="#999" font-size="10">next iteration</text>
</svg>

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
