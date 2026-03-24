# Enterprise Feature Test Workflow

> **AWP L5 Enterprise Compliant** | Version 1.0.0 | Test-Workflow

Fiktiver Enterprise-Workflow zum **Testen aller AWP-Protocol-Features**.
Jeder Agent deckt spezifische Feature-Layer ab, sodass bei einem Durchlauf
alle Capabilities des Protocols validiert werden können.

---

## Workflow-Diagramm

```
                         ┌──────────────────────┐
                         │     User Input        │
                         │  "Analyse BTCUSD"     │
                         └──────────┬───────────┘
                                    │
                                    ▼
                   ┌──────────────────────────────────┐
                   │  data_collector (Daten-Sammler)   │
                   │  Tools: web.search, http.request, │
                   │         custom.fetch_market_data   │
                   │  Vision: ✓  Memory: ✓             │
                   │  Output: raw_data, data_sources,  │
                   │          screenshot_summary        │
                   └──────────────┬───────────────────┘
                                  │ shares: raw_data, data_sources,
                                  │         screenshot_summary
                        ┌─────────┴─────────┐
                        ▼                   ▼
     ┌─────────────────────────┐  ┌────────────────────────────┐
     │  code_executor           │  │  analyst (Markt-Analyst)    │
     │  (Code-Ausführer)        │  │  Tools: memory.*, arithmetic│
     │  Code Mode: TypeScript   │  │  Preprocessor: ✓            │
     │  Sandbox: isolate        │  │  Skills: market_analysis,   │
     │  SDK: web, http, file,   │  │    compliance_rules,        │
     │       memory.read,       │  │    analysis_methodology     │
     │       arithmetic         │  │  Reasoning: high            │
     │  Output: computed_metrics│  │  Output: analysis_summary,  │
     │          execution_log   │  │    risk_score, recommendations│
     └───────────┬─────────────┘  └─────────────┬──────────────┘
                 │                               │
                 │ shares: computed_metrics,      │ shares: analysis_summary,
                 │         execution_log          │   risk_score, recommendations
                 └──────────┬────────────────────┘
                            ▼
              ┌──────────────────────────────────┐
              │  communicator (Kommunikator)      │
              │  Tools: agent.send_message,       │
              │         agent.list_messages,      │
              │         memory.read/write         │
              │  Channels: default, alerts,       │
              │            metrics                │
              │  Output: consolidated_report,     │
              │          broadcast_status         │
              └──────────────┬───────────────────┘
                             │ shares: consolidated_report,
                             │         broadcast_status
                             ▼
                    ┌─── CONDITIONAL ───┐
                    │ risk_score > 0.3? │
                    └────────┬──────────┘
                             │ yes
                             ▼
              ┌──────────────────────────────────┐
              │  report_writer (Report-Schreiber) │
              │  Tools: file.write, file.read,   │
              │         memory.write             │
              │  Blocked: shell.execute          │
              │  (Governance Access Control)      │
              │  Secrets: REPORT_SIGNING_KEY     │
              │  Output: final_report_path,      │
              │          report_hash             │
              └──────────────┬───────────────────┘
                             │
                             ▼
                   ┌─────────────────────┐
                   │    Final Output      │
                   │  data/output/report  │
                   │  + signed hash       │
                   └─────────────────────┘
```

---

## Feature-Coverage-Matrix

| AWP Feature | Layer | Agent(s) | Status |
|-------------|-------|----------|--------|
| **F0: DAG Orchestration** | L0 | Alle | ✅ 5-Agent DAG mit depends_on |
| **F0: Sequential Execution** | L0 | — | ✅ data_collector → ... → report_writer |
| **F0: Parallel Execution** | L0 | code_executor ∥ analyst | ✅ Parallele Branches |
| **F0: Conditional Execution** | L0 | report_writer | ✅ `when: risk_score > 0.3` |
| **F0: Timeout & Error Handling** | L0 | Alle | ✅ per_agent: 180s, retry |
| **F1: State Sharing** | L1 | Alle | ✅ share_output/share_input |
| **F1: State Persistence** | L1 | Alle | ✅ data/state (JSON) |
| **F1: Auto-Inject** | L1 | Alle | ✅ run_id, timestamp |
| **F2: Message Bus (direct)** | L2 | communicator | ✅ default, metrics channels |
| **F2: Message Bus (broadcast)** | L2 | communicator | ✅ alerts channel |
| **F2: Inter-Agent Messaging** | L2 | communicator | ✅ agent.send_message/list_messages |
| **F3: Long-Term Memory** | L3 | analyst, communicator | ✅ MEMORY.md injection |
| **F3: Daily Logs** | L3 | Alle | ✅ auto_write enabled |
| **F3: Memory Search** | L3 | analyst | ✅ memory.search |
| **F3: Memory Curation** | L3 | analyst | ✅ memory.curate (after_run) |
| **F4: Distributed Tracing** | L4 | Alle | ✅ W3C Trace Context |
| **F4: Metrics Collection** | L4 | Alle | ✅ token_usage, tool_duration, confidence |
| **F4: Audit Log (Hash Chain)** | L4 | Alle | ✅ Tamper-proof audit |
| **F4: Structured Logging** | L4 | Alle | ✅ JSON on stdout |
| **F5: Circuit Breaker** | L5 | Alle | ✅ threshold=3, reset=30s |
| **F5: Rate Limiting** | L5 | Alle | ✅ 120 calls/min per agent |
| **F5: Access Control** | L5 | report_writer | ✅ shell.execute denied |
| **F5: Secrets Management** | L5 | data_collector, report_writer | ✅ secrets.yaml injection |
| **F6: Custom MCP Tool** | L5 | data_collector | ✅ custom.fetch_market_data |
| **F6: Built-in Tool Impl.** | L5 | Alle | ✅ 8 MCP files in mcp/ |
| **F6: Code Mode (TypeScript)** | L5 | code_executor | ✅ SDK + Sandbox |
| **F6: Sandbox (isolate)** | L5 | code_executor | ✅ Memory/CPU/FS constraints |
| **F6: SDK Surface Control** | L5 | code_executor | ✅ exclude: memory.write |
| **F6: Vision** | L5 | data_collector | ✅ PNG/JPG/WebP support |
| **F6: Preprocessor** | L5 | analyst | ✅ normalize.py + features.py |
| **F6: Project Skills** | L5 | analyst, report_writer | ✅ market_analysis, compliance_rules |
| **F6: Agent Skills** | L5 | code_executor, analyst | ✅ codemode.md, analysis_methodology |
| **Reasoning (Extended)** | — | Alle (außer communicator) | ✅ effort: high |
| **Prompt Variables** | — | data_collector, analyst, communicator | ✅ {{variable}} injection |

**Coverage: 35/35 Features** — Alle AWP-Protocol-Features werden getestet.

---

## CLI-Befehle

### Installation

```bash
cd enterprise_feature_test/
pip install -r requirements.txt
```

### Workflow validieren

```bash
awp validate enterprise_feature_test/
```

### Workflow ausführen

```bash
# Secrets konfigurieren
cp secrets.yaml.example secrets.yaml
# → Secrets eintragen

# Standard-Ausführung
awp run enterprise_feature_test/ --task "Analysiere den aktuellen BTCUSD-Markt"

# Mit explizitem Modell
LLM_MODEL=anthropic/claude-sonnet-4-20250514 awp run enterprise_feature_test/ \
  --task "Analysiere den aktuellen BTCUSD-Markt" \
  --secrets secrets.yaml
```

### Python-Ausführung

```python
from awp.runtime import WorkflowRunner

runner = WorkflowRunner("enterprise_feature_test")
result = runner.run("Analysiere den aktuellen BTCUSD-Markt")

# Einzelne Agent-Ergebnisse
print(result["data_collector"])     # Rohdaten
print(result["code_executor"])      # Berechnete Metriken
print(result["analyst"])            # Analyse + Risk Score
print(result["communicator"])       # Konsolidierter Bericht
print(result["report_writer"])      # Finaler Report + Hash
```

### Anpassungen

- Prompts: `agents/{agent_id}/workflow/instructions/SYSTEM_PROMPT.md`
- Schemas: `agents/{agent_id}/workflow/output_schema/`
- Tools: `agents/{agent_id}/agent.awp.yaml` → `tools.allowed`
- Skills: `skills/{skill_name}/SKILL.md`
- MCP Tools: `mcp/{tool_file}.py`

---

## Compliance-Validierung (R1–R24)

| Regel | Beschreibung | Status |
|-------|-------------|--------|
| R1 | workflow.name == directory name | ✅ `enterprise_feature_test` |
| R2 | Agent IDs are snake_case | ✅ Alle 5 Agents |
| R3 | agent.py defines class Agent(AWPAgent) | ✅ Alle 5 Agents |
| R4 | Agent.name returns agent ID | ✅ Alle 5 Agents |
| R5 | Every graph agent has directory | ✅ agents/{id}/ |
| R6 | Every agent has agent.awp.yaml + agent.py | ✅ 10 Dateien |
| R7 | Every agent has SYSTEM_PROMPT.md | ✅ 5 Dateien |
| R8 | Every agent has 00_INTRO.md | ✅ 5 Dateien |
| R9 | Every agent has output_schema.json | ✅ 5 Dateien |
| R10 | Every agent has output_schema_desc.json | ✅ 5 Dateien |
| R11 | depends_on references valid agents | ✅ Geprüft |
| R12 | Graph is a DAG (no cycles) | ✅ Keine Zyklen |
| R13 | share_output matches schema keys | ✅ Geprüft |
| R14 | tools.allowed references registered tools | ✅ MCP-Implementierungen in mcp/ |
| R15 | tools.execute=false → empty allowed | ✅ N/A (alle execute=true) |
| R16 | execution.mode is valid | ✅ conditional |
| R17 | All schemas have confidence | ✅ Alle 5 Schemas |
| R18 | All schemas are JSON Schema draft-07 | ✅ type: object |
| R19 | codemode.enabled → tools.enabled | ✅ code_executor |
| R20 | codemode.enabled → sandbox.type ≠ none | ✅ isolate |
| R21 | codemode.language is valid | ✅ typescript |
| R22 | sdk_surface explicit → include non-empty | ✅ N/A (mode: auto) |
| R23 | sdk_surface.exclude matches tools.allowed | ✅ memory.write ∈ allowed |
| R24 | sandbox.type isolate → network defined | ✅ network.enabled: false |

---

## Dateistruktur

```
enterprise_feature_test/                        # Workflow Root
├── workflow.awp.yaml                           # L5 Enterprise Manifest
├── requirements.txt                            # Python Dependencies
├── secrets.yaml.example                        # Secrets Template
├── README.md                                   # Diese Datei
│
├── agents/
│   ├── data_collector/                         # Agent 1: Daten-Sammler
│   │   ├── agent.awp.yaml                      #   Config (Vision, Custom MCP)
│   │   ├── agent.py                            #   Python Class
│   │   └── workflow/
│   │       ├── instructions/SYSTEM_PROMPT.md   #   System Prompt
│   │       ├── prompt/00_INTRO.md              #   Intro Prompt
│   │       ├── output_schema/output_schema.json
│   │       ├── output_schema_desc/output_schema_desc.json
│   │       └── skills/                         #   (keine Agent-Skills)
│   │
│   ├── code_executor/                          # Agent 2: Code-Ausführer
│   │   ├── agent.awp.yaml                      #   Config (Code Mode, Sandbox)
│   │   ├── agent.py
│   │   └── workflow/
│   │       ├── instructions/SYSTEM_PROMPT.md
│   │       ├── prompt/00_INTRO.md
│   │       ├── output_schema/output_schema.json
│   │       ├── output_schema_desc/output_schema_desc.json
│   │       └── skills/
│   │           └── codemode.md                 #   Code Mode SDK Skill
│   │
│   ├── analyst/                                # Agent 3: Markt-Analyst
│   │   ├── agent.awp.yaml                      #   Config (Memory, Preprocessor)
│   │   ├── agent.py
│   │   └── workflow/
│   │       ├── instructions/SYSTEM_PROMPT.md
│   │       ├── prompt/00_INTRO.md
│   │       ├── output_schema/output_schema.json
│   │       ├── output_schema_desc/output_schema_desc.json
│   │       ├── skills/
│   │       │   └── analysis_methodology.md     #   Agent-Level Skill
│   │       └── preprocessor/
│   │           ├── normalize.py                #   Step 1: ATR, Z-Scores
│   │           └── features.py                 #   Step 2: Trend, Volatility
│   │
│   ├── communicator/                           # Agent 4: Kommunikator
│   │   ├── agent.awp.yaml                      #   Config (Message Bus)
│   │   ├── agent.py
│   │   └── workflow/
│   │       ├── instructions/SYSTEM_PROMPT.md
│   │       ├── prompt/00_INTRO.md
│   │       ├── output_schema/output_schema.json
│   │       ├── output_schema_desc/output_schema_desc.json
│   │       └── skills/
│   │
│   └── report_writer/                          # Agent 5: Report-Schreiber
│       ├── agent.awp.yaml                      #   Config (Governance, Secrets)
│       ├── agent.py
│       └── workflow/
│           ├── instructions/SYSTEM_PROMPT.md
│           ├── prompt/00_INTRO.md
│           ├── output_schema/output_schema.json
│           ├── output_schema_desc/output_schema_desc.json
│           └── skills/
│
├── mcp/                                        # MCP Tool Implementations
│   ├── custom_fetch_market_data.py             #   Custom: Market Data API (F6)
│   ├── web_search.py                           #   Built-in: web.search
│   ├── http_request.py                         #   Built-in: http.request
│   ├── file_ops.py                             #   Built-in: file.read/write/list
│   ├── shell_execute.py                        #   Built-in: shell.execute
│   ├── memory_ops.py                           #   Built-in: memory.*
│   ├── agent_messaging.py                      #   Built-in: agent.send/list_messages
│   └── arithmetic_ops.py                       #   Built-in: arithmetic.*
│
├── skills/                                     # Project-Level Skills
│   ├── market_analysis/SKILL.md                #   Marktanalyse-Methodik
│   └── compliance_rules/SKILL.md               #   Governance & Compliance
│
└── data/
    └── state/                                  #   State Persistence Directory
```

**Gesamt: 42 Dateien** | **Compliance: L5 Enterprise** | **Agents: 5** | **MCP Tools: 8**
