# Integrationsplan: Cloudflare Dynamic Workers als AWP-Runtime

**Status:** Finaler Plan
**Datum:** 2026-03-24
**Branch:** `claude/dynamic-workers-integration-Rw1NX`

---

## 1. Ziel

Cloudflare Dynamic Workers als vollwertigen Runtime-Adapter in AWP integrieren,
sodass der Skill Cloudflare-kompatiblen TypeScript-Code generieren kann. Jeder
AWP-Agent läuft als eigener V8-Isolate mit voller Sandbox-Isolation.

---

## 2. Entscheidungen

| Frage | Entscheidung | Begründung |
|-------|-------------|------------|
| Scope | Skill-Adapter zuerst | Niedrig-Risiko, Dynamic Workers ist brandneu (März 2026), APIs können sich ändern |
| Agent-Isolierung | 1 Agent = 1 Isolate | Natürliches AWP-Mapping, echte Isolation, Kosten vernachlässigbar ($0.002/Worker/Tag) |
| Code Mode | Optional via `execution_mode` | Protokoll-kompatibler Runtime-Hint, Fallback auf `classic` |
| Memory-Mapping | 2-Tier (InMemory + Workspace) | Working → Isolate-Memory, Short-term → SQLite, Long-term → R2 |
| LLM Backend | Flexibel (OpenAI-kompatibel) | Workers AI als Option, nicht als Pflicht — Protokoll-Gedanke bleibt |
| Deployment | Generieren + `wrangler deploy` | AWP ist Protokoll, kein Deploy-Tool; wrangler ist CF-Standard |
| Priorität | Phase 1 → Phase 2 → Phase 3 | Adapter → Spec-Erweiterung → TS-Runtime |

---

## 3. Architektur

```
┌─────────────────────────────────────────────────────┐
│            Dispatch Worker (Orchestrator)            │
│                                                     │
│  - Liest workflow.awp.yaml (eingebettet als JSON)   │
│  - Steuert DAG-Ausführung (sequentiell/parallel)    │
│  - Lädt Agent-Isolates via Worker Loader API        │
│  - Sammelt Ergebnisse, verwaltet State              │
│                                                     │
│  Bindings:                                          │
│    LOADER  → Worker Loader (Agent-Isolates)         │
│    STATE   → KV Namespace (Workflow State)          │
│    MEMORY  → R2 Bucket (Long-term Memory)           │
│    DB      → D1 Database (Short-term/Daily Log)     │
│    AI      → Workers AI (optional LLM Backend)      │
│    BUS     → Durable Object (Message Bus, L2+)      │
├──────────┬──────────┬──────────┬────────────────────┤
│ Agent A  │ Agent B  │ Agent C  │  ... Agent N       │
│ (Isolate)│ (Isolate)│ (Isolate)│  (Isolate)         │
│          │          │          │                    │
│ Erhält:  │ Erhält:  │ Erhält:  │                    │
│ - task   │ - task   │ - task   │                    │
│ - state  │ - state  │ - state  │                    │
│ - tools  │ - tools  │ - tools  │                    │
│   (RPC)  │   (RPC)  │   (RPC)  │                    │
│          │          │          │                    │
│ Rückgabe:│ Rückgabe:│ Rückgabe:│                    │
│ JSON per │ JSON per │ JSON per │                    │
│ contract │ contract │ contract │                    │
├──────────┴──────────┴──────────┴────────────────────┤
│              Shared Infrastructure                   │
│                                                     │
│  KV Namespace     → Agent Configs (agent.awp.yaml)  │
│  D1 (SQLite)      → Short-term Memory, Daily Logs   │
│  R2 Bucket        → Long-term Memory (MEMORY.md)    │
│  Durable Objects  → Message Bus (L2+), Locks        │
│  Workers AI       → LLM Inference (optional)        │
│  External API     → OpenAI/Anthropic/OpenRouter     │
└─────────────────────────────────────────────────────┘
```

### Datenfluss einer Agent-Ausführung

```
1. Dispatch Worker empfängt Request (HTTP oder Cron)
2. Liest DAG aus eingebettetem workflow.awp.yaml
3. Bestimmt nächsten Agent(s) basierend auf depends_on + Bedingungen
4. Für jeden Agent:
   a. Lädt Agent-Config aus KV
   b. Baut System Prompt: SYSTEM_PROMPT.md + Skills + MEMORY.md
   c. Baut User Prompt: 00_INTRO.md + State von Vorgänger-Agents
   d. Ruft LLM auf (Workers AI oder externe API)
   e. Parst JSON-Response gegen output_schema.json
   f. Speichert Ergebnis in State (KV)
   g. Optional: Schreibt Daily Log (D1), Updated MEMORY.md (R2)
5. Nächster Agent im DAG, bis alle fertig
6. Gibt finales Ergebnis zurück
```

### Warum kein Agent-Code im Isolate?

Anders als beim Python-Adapter braucht der Cloudflare-Adapter **keinen
agent.ts-Code im Isolate**. Der Dispatch Worker übernimmt die gesamte
Orchestrierung. Die Agent-Isolates werden nur gebraucht wenn:

- **Code Mode** aktiv ist (Agent generiert + führt Code aus)
- **Custom Tools** als Isolate-Sandboxes laufen müssen
- **Untrusted Code** aus dem LLM-Output ausgeführt werden soll

Für den Standard-Flow (Prompt → LLM → JSON) reicht der Dispatch Worker allein.

---

## 4. Phasen

### Phase 1: Skill-Adapter (Hauptarbeit)

**Ziel:** Der AWP-Skill kann Cloudflare-kompatiblen Code generieren.

#### 4.1.1 Neue Dateien

```
skill/
  adapters/
    cloudflare-dynamic-workers.md    ← Adapter-Dokument (Hauptdatei)
  templates/
    adapters/
      cloudflare/
        wrangler.toml                ← Wrangler-Config Template
        src/
          index.ts                   ← Dispatch Worker (Orchestrator)
          types.ts                   ← Shared TypeScript Types
          llm.ts                     ← LLM Client (OpenAI-kompatibel)
          memory.ts                  ← Memory Manager (KV + D1 + R2)
        package.json                 ← Dependencies Template
        tsconfig.json                ← TypeScript Config
        README.md                    ← Deploy-Anleitung
```

#### 4.1.2 Adapter-Dokument: `cloudflare-dynamic-workers.md`

Struktur (analog zu `standalone.md`):

```markdown
# AWP Platform Adapter: Cloudflare Dynamic Workers

## When to Use
- Serverless, edge-deployed Multi-Agent Workflows
- Maximale Isolation zwischen Agents (V8 Isolates)
- Globale Verfügbarkeit (300+ Cloudflare-Standorte)
- Skalierung ohne Limits auf gleichzeitige Agents

## Architektur
- Dispatch Worker als zentraler Orchestrator
- Jeder Agent = potentieller Dynamic Worker Isolate
- Standard-Flow läuft komplett im Dispatch Worker
- Isolates nur für Code Mode / Custom Tool Sandboxing

## Generierte Dateien
[Liste aller generierten Dateien mit Erklärung]

## Templates
[Dispatch Worker, LLM Client, Memory Manager Templates]

## Deployment
[Schritt-für-Schritt wrangler deploy Anleitung]

## Kosten-Übersicht
[Workers Pricing Breakdown]
```

#### 4.1.3 Template-Details

**`wrangler.toml`:**
```toml
name = "{{WORKFLOW_NAME}}"
main = "src/index.ts"
compatibility_date = "2026-03-24"

[observability]
enabled = true

# Agent Configs & State
[[kv_namespaces]]
binding = "STATE"
id = "{{KV_NAMESPACE_ID}}"

# Long-term Memory
[[r2_buckets]]
binding = "MEMORY"
bucket_name = "{{WORKFLOW_NAME}}-memory"

# Short-term Memory / Daily Logs
[[d1_databases]]
binding = "DB"
database_name = "{{WORKFLOW_NAME}}-db"
database_id = "{{D1_DATABASE_ID}}"

# Optional: Workers AI
[ai]
binding = "AI"

# Optional: Dynamic Worker Loader (für Code Mode)
# [[worker_loaders]]
# binding = "LOADER"
```

**`src/index.ts` (Dispatch Worker):**
```typescript
// Liest eingebettetes workflow.awp.yaml
// Steuert DAG-Ausführung
// Ruft LLM für jeden Agent auf
// Validiert Output gegen Schema
// Verwaltet State zwischen Agents

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const runner = new WorkflowRunner(env);
    const task = await extractTask(request);
    const result = await runner.execute(task);
    return Response.json(result);
  },

  async scheduled(event: ScheduledEvent, env: Env): Promise<void> {
    // Cron-basierte Workflow-Ausführung
  }
};
```

#### 4.1.4 Memory-Mapping Implementation

| AWP Tier | CF Service | Lifecycle | Zugriff |
|----------|-----------|-----------|---------|
| Working Memory | JavaScript Variables im Dispatch Worker | Request-Scope | Direkt |
| Short-term (Daily Log) | D1 (SQLite) | Persistiert, querybar | `env.DB.prepare()` |
| Long-term (MEMORY.md) | R2 (Object Storage) | Unbegrenzt | `env.MEMORY.get/put()` |

#### 4.1.5 LLM-Integration

```typescript
// llm.ts - Flexibler LLM Client
interface LLMConfig {
  provider: "workers-ai" | "openai-compatible";
  model: string;
  apiKey?: string;
  baseUrl?: string;
  parameters: { temperature: number; max_tokens?: number };
}

// Workers AI:
const response = await env.AI.run(config.model, { messages });

// OpenAI-kompatibel (Anthropic, OpenRouter, etc.):
const response = await fetch(config.baseUrl + "/chat/completions", {
  headers: { Authorization: `Bearer ${config.apiKey}` },
  body: JSON.stringify({ model: config.model, messages }),
});
```

---

### Phase 2: Spec-Erweiterung (nach Phase 1)

**Ziel:** Code Mode und Runtime-Hints im Protokoll formalisieren.

#### 4.2.1 Neue Felder in `agent.awp.yaml`

```yaml
# Neues optionales Feld unter 'tools'
tools:
  execute: true
  execution_mode: classic          # classic | codemode
  # codemode: Agent schreibt Code gegen typed SDK statt einzelne Tool-Calls
  # Runtimes die codemode nicht unterstützen fallen auf classic zurück

# Neues optionales Feld unter 'runtime'
runtime:
  class_name: Agent
  strategy_folder: workflow
  target: standalone               # standalone | cloudflare | custom
  # Runtime-Hint für Adapter-Auswahl bei Code-Generierung
```

#### 4.2.2 Schema-Erweiterung

- `schemas/v1.0/agent.awp.schema.json` — `execution_mode` enum hinzufügen
- `spec/versions/1.0/layers/02-capabilities.md` — Code Mode dokumentieren
- `docs/tools.md` — Code Mode Abschnitt ergänzen

#### 4.2.3 Neue Validierungsregel

- **R19:** Wenn `execution_mode: codemode`, MUSS `tools.execute: true` sein
- **R20:** Wenn `runtime.target` gesetzt, MUSS ein passender Adapter existieren

---

### Phase 3: TypeScript-Referenz-Runtime (langfristig)

**Ziel:** Vollständiges `awp-cloudflare` npm-Package.

#### 4.3.1 Package-Struktur

```
reference/cloudflare/
  package.json                     # awp-cloudflare
  tsconfig.json
  src/
    index.ts                       # Exports
    runner.ts                      # WorkflowRunner (CF-native)
    agent.ts                       # AWPAgent Interface (TS)
    parser/
      manifest.ts                  # workflow.awp.yaml Parser
      agent.ts                     # agent.awp.yaml Parser
    runtime/
      dispatch.ts                  # Dispatch Worker Logic
      llm.ts                      # LLM Client
      tools.ts                    # Tool Registry (MCP)
      memory.ts                   # Memory Manager
      codemode.ts                 # @cloudflare/codemode Integration
    validator/
      schema.ts                   # JSON Schema Validation
      graph.ts                    # DAG Validation
```

#### 4.3.2 Voraussetzungen

- Phase 1 und 2 abgeschlossen
- Dynamic Workers API stabil (mind. 3 Monate nach Launch)
- Mindestens 2 Beispiel-Workflows erfolgreich auf CF deployed

---

## 5. Dateien-Übersicht (Phase 1)

| Datei | Typ | Beschreibung |
|-------|-----|-------------|
| `skill/adapters/cloudflare-dynamic-workers.md` | **Neu** | Adapter-Dokument für den Skill |
| `skill/templates/adapters/cloudflare/wrangler.toml` | **Neu** | Wrangler Config Template |
| `skill/templates/adapters/cloudflare/package.json` | **Neu** | npm Dependencies |
| `skill/templates/adapters/cloudflare/tsconfig.json` | **Neu** | TypeScript Config |
| `skill/templates/adapters/cloudflare/src/index.ts` | **Neu** | Dispatch Worker Template |
| `skill/templates/adapters/cloudflare/src/types.ts` | **Neu** | Shared Types |
| `skill/templates/adapters/cloudflare/src/llm.ts` | **Neu** | LLM Client Template |
| `skill/templates/adapters/cloudflare/src/memory.ts` | **Neu** | Memory Manager Template |
| `skill/templates/adapters/cloudflare/README.md` | **Neu** | Deploy-Anleitung |
| `skill/SKILL.md` | **Änderung** | Adapter-Referenz hinzufügen |
| `docs/runtime.md` | **Änderung** | Cloudflare-Abschnitt ergänzen |

---

## 6. Abgrenzung: Was Phase 1 NICHT enthält

- Keine vollständige TypeScript-Runtime (→ Phase 3)
- Keine Spec-Änderungen an JSON Schemas (→ Phase 2)
- Keine `@cloudflare/codemode` Integration (→ Phase 2/3)
- Keine `@cloudflare/shell` Integration (→ Phase 3)
- Kein Durable Objects Message Bus (→ Phase 3)
- Kein ClawHub One-Click Deploy (→ separat)
- Keine Conformance Tests für Cloudflare (→ Phase 3)

---

## 7. Risiken & Mitigationen

| Risiko | Wahrscheinlichkeit | Mitigation |
|--------|-------------------|------------|
| Dynamic Workers API ändert sich | Hoch (brandneu) | Adapter ist Markdown — leicht anpassbar |
| Worker Loader Pricing ändert sich | Mittel | Kosten-Abschnitt im Adapter versioniert |
| D1/R2 Limits für große Workflows | Niedrig | Adapter dokumentiert Limits, Fallback auf KV |
| LLM-Aufrufe aus Workers haben Latenz-Limits | Mittel | Timeout-Config in wrangler.toml anpassbar |

---

## 8. Erfolgs-Kriterien

### Phase 1 gilt als abgeschlossen wenn:

1. `skill/adapters/cloudflare-dynamic-workers.md` existiert und dem Adapter-Format folgt
2. Alle Templates in `skill/templates/adapters/cloudflare/` sind vollständig
3. Der Skill kann bei "Build me a workflow for Cloudflare" den richtigen Adapter laden
4. Ein generierter Hello-World-Workflow lässt sich mit `wrangler deploy` deployen
5. Dokumentation in `docs/runtime.md` ist aktualisiert

### Phase 2 gilt als abgeschlossen wenn:

6. `execution_mode` und `runtime.target` sind in Schema und Spec dokumentiert
7. Validierungsregeln R19/R20 sind implementiert
8. Mindestens 1 Beispiel-Workflow nutzt Code Mode

### Phase 3 gilt als abgeschlossen wenn:

9. `awp-cloudflare` npm-Package ist publishbar
10. Alle 5 Beispiel-Workflows laufen auf Cloudflare
11. Conformance Tests L0-L3 bestehen auf CF-Runtime
