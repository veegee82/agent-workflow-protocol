# Integrationsplan: Cloudflare Dynamic Workers + Code Mode als AWP-Native

**Status:** Finaler Plan
**Datum:** 2026-03-24
**Branch:** `claude/dynamic-workers-integration-Rw1NX`

---

## 1. Ziel

Zwei Dinge nativ in AWP integrieren:

1. **Cloudflare Dynamic Workers** als Runtime-Adapter — der Skill generiert
   deploybaren Cloudflare-Code.
2. **Code Mode (CLI-Konzept)** als protokoll-natives Feature in Layer 2
   (Capabilities) — Agents können Code gegen ein typed SDK schreiben statt
   Tools einzeln aufzurufen. Dieses Konzept ist **runtime-agnostisch** und
   nicht an Cloudflare gebunden.

---

## 2. Entscheidungen

| Frage | Entscheidung | Begründung |
|-------|-------------|------------|
| Scope | Skill-Adapter zuerst | Niedrig-Risiko, Dynamic Workers ist brandneu (März 2026), APIs können sich ändern |
| Agent-Isolierung | 1 Agent = 1 Isolate | Natürliches AWP-Mapping, echte Isolation, Kosten vernachlässigbar ($0.002/Worker/Tag) |
| Code Mode | Natives Protokoll-Feature in Layer 2 | Nicht nur Runtime-Hint — vollständige Spezifikation als `capabilities.codemode` |
| Memory-Mapping | 2-Tier (InMemory + Workspace) | Working → Isolate-Memory, Short-term → SQLite, Long-term → R2 |
| LLM Backend | Flexibel (OpenAI-kompatibel) | Workers AI als Option, nicht als Pflicht — Protokoll-Gedanke bleibt |
| Deployment | Generieren + `wrangler deploy` | AWP ist Protokoll, kein Deploy-Tool; wrangler ist CF-Standard |
| CLI-Konzept | Nativ im Protokoll (Layer 2) | Runtime-agnostisch: CF nutzt Isolates, Python nutzt subprocess, Docker nutzt Container |
| Priorität | Phase 1 → Phase 2 → Phase 3 | Adapter → Protokoll-Erweiterung (Code Mode) → TS-Runtime |

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

## 4. Code Mode — Natives Protokoll-Konzept (CLI → MCP → Skill)

### 4.0 Das Problem

Im klassischen AWP-Flow ruft ein Agent MCP-Tools **einzeln** auf:

```
Agent → LLM → Tool-Call "web.search" → Ergebnis → LLM → Tool-Call "file.write" → Ergebnis → LLM → ...
```

**Jeder Tool-Call** = 1 LLM-Roundtrip + Token-Overhead für Tool-Definitionen.

Bei 15 Tools × 200 Tokens pro Definition = **3.000 Tokens** nur für Tool-Beschreibungen
im System Prompt — bei jedem einzelnen LLM-Aufruf.

### 4.1 Die Lösung: Code Mode

Statt einzelne Tools aufzurufen, **schreibt der Agent Code** gegen ein typed SDK:

```
Agent → LLM → generiert Code-Block → Sandbox führt Code aus → Ergebnis → LLM
```

**Ein Roundtrip** statt vieler. Das SDK fasst alle erlaubten Tools als Methoden zusammen.

### 4.2 Warum nativ im Protokoll?

Code Mode ist **nicht Cloudflare-spezifisch**. Es ist ein fundamentales Muster:

| Runtime | Code Mode Sandbox | SDK Surface |
|---------|-------------------|-------------|
| **Cloudflare** | V8 Isolate (Dynamic Worker) | `@cloudflare/codemode` |
| **Python (standalone)** | subprocess / Docker | Python SDK mit `awp.tools.*` |
| **WASM** | WASM Sandbox | Beliebige Sprache |
| **Docker** | Container | Beliebige Sprache |

Das Protokoll definiert das **WAS** (welche Tools als SDK verfügbar sind, welche
Constraints gelten). Die Runtime bestimmt das **WIE** (Isolate, subprocess, Container).

### 4.3 Einordnung in die AWP-Architektur

Code Mode erweitert **Layer 2 (Capabilities)** — es ist eine alternative
Tool-Execution-Strategie, kein neuer Layer:

```
Layer 2: Capabilities
├── tools              (bestehend)  → Einzelne MCP Tool-Calls
├── skills             (bestehend)  → Wissens-Injection in Prompts
├── data_sources       (bestehend)  → Externe Datenquellen
├── sandbox            (bestehend)  → Code-Execution Sandbox
└── codemode           (NEU)        → Agent schreibt Code gegen Tool-SDK
    ├── enabled                     → Feature-Toggle
    ├── sdk_surface                 → Welche Tools als SDK-Methoden
    ├── language                    → Zielsprache des generierten Codes
    ├── sandbox_ref                 → Referenz auf capabilities.sandbox
    ├── state                       → State-Backend (filesystem, memory)
    └── constraints                 → Limits (timeout, output_size, network)
```

### 4.4 Spezifikation: `capabilities.codemode` in `agent.awp.yaml`

```yaml
capabilities:
  # --- Bestehende Sections (unverändert) ---
  tools:
    enabled: true
    allowed: ["web.*", "file.*", "memory.*"]
    denied: ["shell.*"]

  sandbox:
    type: isolate                           # NEU: "isolate" als Typ
    constraints:
      max_memory_mb: 128
      max_cpu_seconds: 30
      max_output_bytes: 1048576
    network:
      enabled: false                        # globalOutbound: null
      allowed_hosts: []                     # Whitelist wenn enabled: true
    filesystem:
      read: ["data/"]
      write: ["data/output/"]
      deny: [".env", "**/*.key"]

  # --- NEU: Code Mode ---
  codemode:
    enabled: true
    description: >
      Agent schreibt Code gegen ein typed SDK statt einzelne Tool-Calls.
      Reduziert Token-Verbrauch und LLM-Roundtrips bei großer Tool-Surface.

    # Welche Sprache generiert der Agent?
    language: typescript                    # typescript | python | javascript

    # Welche Tools sind als SDK-Methoden verfügbar?
    # Referenziert capabilities.tools.allowed — nur erlaubte Tools werden
    # in das SDK aufgenommen.
    sdk_surface:
      mode: auto                            # auto | explicit
      # auto: Alle allowed tools werden SDK-Methoden
      # explicit: Nur die unten gelisteten
      include: []                           # Nur bei mode: explicit
      exclude: []                           # Tools die NICHT im SDK sein sollen

    # Wie wird der generierte Code ausgeführt?
    # Referenziert capabilities.sandbox — gleiche Sandbox-Config
    execution:
      sandbox_ref: capabilities.sandbox     # Nutzt die Sandbox-Config oben
      timeout: 30                           # Überschreibt sandbox.constraints wenn nötig
      max_retries: 1                        # Code-Execution Retries
      capture_console: true                 # stdout/stderr capturen und zurückgeben

    # State-Backend für den Code (optional)
    state:
      enabled: false
      backend: memory                       # memory | filesystem | workspace
      # memory: In-Memory, stirbt nach Execution
      # filesystem: Persistiert in sandbox.filesystem.write Pfaden
      # workspace: Nutzt Memory-Layer (L4) — SQLite + Object Storage
```

### 4.5 Wie Runtimes Code Mode implementieren

#### 4.5.1 Python Runtime (standalone)

```python
# Das SDK wird aus den erlaubten Tools generiert:
class AWPToolSDK:
    """Auto-generated from capabilities.tools.allowed"""

    async def web_search(self, query: str, max_results: int = 5) -> dict:
        """Search the web."""
        return await self._call_tool("web.search", {"query": query, "max_results": max_results})

    async def file_read(self, path: str) -> dict:
        """Read a file."""
        return await self._call_tool("file.read", {"path": path})

    # ... Auto-generiert aus Tool-Definitionen

# Agent generiert Code:
generated_code = """
results = await sdk.web_search("AWP protocol")
summary = results["data"]["results"][0]["snippet"]
await sdk.file_write("output/summary.txt", summary)
return {"summary": summary, "source_count": len(results["data"]["results"])}
"""

# Runtime führt Code in Sandbox aus:
result = sandbox.execute(generated_code, sdk=sdk, timeout=30)
```

#### 4.5.2 Cloudflare Runtime (Dynamic Workers)

```typescript
// SDK wird als TypeScript-Interface für den Isolate gebaut:
interface AWPToolSDK {
  web: {
    search(query: string, maxResults?: number): Promise<ToolResult>;
  };
  file: {
    read(path: string): Promise<ToolResult>;
    write(path: string, content: string): Promise<ToolResult>;
  };
  memory: {
    read(key: string): Promise<ToolResult>;
    write(key: string, value: string): Promise<ToolResult>;
  };
}

// Agent generiert Code, der im Isolate läuft:
const result = await env.LOADER.get("agent-code-123", {
  modules: [{ name: "agent.ts", content: generatedCode }],
  env: { sdk: toolSDKProxy },           // RPC-Stubs für Tools
  globalOutbound: null,                   // Netzwerk blockiert
});
```

#### 4.5.3 Docker Runtime

```python
# SDK wird als REST-API im Container bereitgestellt:
# Container startet → HTTP-Server auf localhost:8080
# Agent-Code ruft sdk.web_search() → HTTP POST localhost:8080/tools/web.search
# Container hat kein Netzwerk außer localhost
```

### 4.6 Zusammenspiel: Code Mode × MCP Tools × Skills

```
┌─────────────────────────────────────────────────────────┐
│                    Agent Execution                       │
│                                                         │
│  System Prompt:                                         │
│  ┌─────────────────────────────────────────────────┐    │
│  │ SYSTEM_PROMPT.md (Rolle, Regeln)                │    │
│  │ + Skills (Domain-Wissen)                        │    │
│  │ + MEMORY.md (Long-term Memory)                  │    │
│  │ + SDK Type Definitions (wenn codemode: true)    │ ◄──── NEU
│  │   statt einzelner Tool-Definitionen             │    │
│  └─────────────────────────────────────────────────┘    │
│                                                         │
│  LLM Response:                                          │
│  ┌─────────────────────────────────────────────────┐    │
│  │ Classic Mode:  tool_call("web.search", {q: ..}) │    │
│  │                tool_call("file.write", {..})     │    │
│  │                                                  │    │
│  │ Code Mode:     ```typescript                     │ ◄──── NEU
│  │                const r = await sdk.web.search(q) │    │
│  │                await sdk.file.write(path, data)  │    │
│  │                return { summary, confidence }    │    │
│  │                ```                               │    │
│  └─────────────────────────────────────────────────┘    │
│                                                         │
│  Execution:                                             │
│  ┌─────────────────────────────────────────────────┐    │
│  │ Classic: Runtime ruft Tools einzeln auf          │    │
│  │ Code Mode: Runtime führt Code in Sandbox aus     │ ◄──── NEU
│  │            SDK-Methoden → MCP Tool-Calls intern  │    │
│  └─────────────────────────────────────────────────┘    │
│                                                         │
│  Output: JSON gemäß output_schema.json (unverändert)    │
└─────────────────────────────────────────────────────────┘
```

**Wichtig:** Der Output-Contract bleibt identisch. Egal ob Classic oder Code Mode —
das Ergebnis MUSS dem `output_schema.json` entsprechen. Code Mode ändert nur
**wie** der Agent zu seinem Ergebnis kommt, nicht **was** er zurückgibt.

### 4.7 Neuer Sandbox-Typ: `isolate`

Die bestehende `capabilities.sandbox` Section bekommt einen neuen Typ:

```yaml
capabilities:
  sandbox:
    type: isolate                           # NEU (neben subprocess, docker, wasm, none)
    constraints:
      max_memory_mb: 128
      max_cpu_seconds: 30
      max_output_bytes: 1048576
    network:                                # NEU: Netzwerk-Isolation
      enabled: false                        # Default: kein Netzwerk
      allowed_hosts: []                     # Whitelist für erlaubte Hosts
      intercept: false                      # Requests abfangen und loggen
    filesystem:
      read: ["data/"]
      write: ["data/output/"]
      deny: [".env"]
```

| Sandbox-Typ | Startup | Isolation | Netzwerk | Dateisystem | Use Case |
|-------------|---------|-----------|----------|-------------|----------|
| `subprocess` | ~100ms | Prozess-Level | Host | Host FS (eingeschränkt) | Python, lokale Entwicklung |
| `docker` | ~1-5s | Container | Konfigurierbar | Container FS | Full-Stack, Heavy Workloads |
| `wasm` | ~10ms | WASM-Sandbox | Keins | Keins | Leichtgewichtig, Browser |
| `isolate` | **~5ms** | **V8 Isolate** | **Konfigurierbar** | **Virtual FS** | **CF Workers, Edge, Code Mode** |
| `none` | 0ms | Keine | Host | Host | Nur vertrauenswürdiger Code |

### 4.8 Skill-Integration: Code-Mode-Skill

Ein neuer Projekt-Skill wird automatisch generiert wenn `codemode.enabled: true`:

```markdown
# Skill: Code Mode Execution

Du hast Zugriff auf ein typed SDK statt einzelner Tool-Calls.
Schreibe Code der das SDK nutzt, um deine Aufgabe zu lösen.

## SDK API

{{AUTO_GENERATED_FROM_ALLOWED_TOOLS}}

## Regeln

1. Schreibe IMMER eine einzelne async Funktion die das Ergebnis zurückgibt.
2. Das Ergebnis MUSS dem Output-Schema entsprechen.
3. Nutze KEINE globalen Variablen oder Imports außer dem SDK.
4. Fange Fehler ab und gib sie im error-Feld zurück.
5. Das SDK ist das EINZIGE Interface zur Außenwelt.
   Direkte fetch()-Aufrufe oder Dateisystem-Zugriffe sind blockiert.

## Beispiel

```typescript
async function execute(sdk: AWPToolSDK): Promise<Output> {
  const results = await sdk.web.search("{{EXAMPLE_QUERY}}");
  const topResult = results.data.results[0];

  return {
    result: topResult.snippet,
    confidence: 0.85
  };
}
```
```

Dieser Skill wird vom AWP-Skill-Generator automatisch aus den `capabilities.tools.allowed`
und dem `output_schema.json` des Agents erstellt. Er ersetzt die üblichen
Tool-Definitionen im System Prompt.

### 4.9 Neue Validierungsregeln

| Regel | Beschreibung |
|-------|-------------|
| **R19** | Wenn `codemode.enabled: true`, MUSS `capabilities.tools.enabled: true` sein |
| **R20** | Wenn `codemode.enabled: true`, MUSS `capabilities.sandbox.type` gesetzt sein (nicht `none`) |
| **R21** | `codemode.language` MUSS einer der unterstützten Werte sein: `typescript`, `python`, `javascript` |
| **R22** | `codemode.sdk_surface.mode: explicit` MUSS mindestens ein Tool in `include` haben |
| **R23** | Tools in `codemode.sdk_surface.exclude` MÜSSEN in `capabilities.tools.allowed` existieren |
| **R24** | Wenn `sandbox.type: isolate`, MUSS `sandbox.network` definiert sein |
| **CT10** | Custom Tools die `codemode`-kompatibel sind, MÜSSEN async/Promise-basiert sein |

### 4.10 Compliance-Level Zuordnung

Code Mode ist **optional ab L0** — es hat kein eigenes Compliance-Level,
sondern ist ein Capability-Feature das jeder Agent nutzen kann:

| Level | Code Mode Verhalten |
|-------|-------------------|
| **L0-L1** | `codemode` optional, `sandbox.type: subprocess` oder `isolate` |
| **L2+** | `codemode` kann `agent.send_message` über SDK aufrufen |
| **L3+** | `codemode.state.backend: workspace` nutzt Memory-Layer |
| **L4+** | Code-Execution wird getraced (Observability) |
| **L5** | Rate-Limits und Circuit-Breaker gelten auch für SDK-Calls |

---

## 5. Phasen

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

### Phase 2: Protokoll-Erweiterung — Code Mode nativ (nach Phase 1)

**Ziel:** Code Mode als natives Feature in Layer 2 spezifizieren. Siehe Abschnitt 4
für die vollständige Spezifikation.

#### 5.2.1 Spec-Änderungen

| Datei | Änderung |
|-------|---------|
| `spec/versions/1.0/layers/02-capabilities.md` | Neuer Abschnitt "8. Code Mode" mit vollständiger Spezifikation |
| `spec/versions/1.0/validation-rules.md` | Regeln R19-R24 und CT10 hinzufügen |
| `schemas/v1.0/agent.awp.schema.json` | `capabilities.codemode` Schema hinzufügen |
| `schemas/v1.0/agent.awp.schema.json` | `sandbox.type: "isolate"` + `sandbox.network` hinzufügen |

#### 5.2.2 Dokumentations-Änderungen

| Datei | Änderung |
|-------|---------|
| `docs/tools.md` | Neuer Abschnitt "Code Mode — Alternative Tool Execution" |
| `docs/skill-system.md` | Code-Mode-Skill Auto-Generation dokumentieren |
| `docs/runtime.md` | Runtime-Implementierung für Code Mode je Plattform |

#### 5.2.3 Template-Änderungen

| Datei | Änderung |
|-------|---------|
| `skill/templates/agent-full.awp.yaml` | `capabilities.codemode` Section hinzufügen |
| `skill/templates/codemode-skill.md` | **Neu:** Template für auto-generiertes Code-Mode-Skill |
| `skill/templates/codemode-sdk.ts.tmpl` | **Neu:** TypeScript SDK-Interface Template |
| `skill/templates/codemode-sdk.py.tmpl` | **Neu:** Python SDK-Class Template |

#### 5.2.4 Referenz-Implementierung (Python)

| Datei | Änderung |
|-------|---------|
| `reference/python/src/awp/runtime/codemode.py` | **Neu:** CodeModeExecutor Klasse |
| `reference/python/src/awp/runtime/sdk_generator.py` | **Neu:** Generiert SDK aus Tool-Registry |
| `reference/python/src/awp/runtime/runner.py` | Code Mode Support im WorkflowRunner |
| `reference/python/src/awp/validator/rules.py` | R19-R24 Validierung |

#### 5.2.5 Beispiel-Workflow

| Datei | Beschreibung |
|-------|-------------|
| `examples/06-codemode/` | **Neu:** Beispiel das Code Mode mit subprocess-Sandbox zeigt |

#### 5.2.6 SKILL.md Änderungen

Der Haupt-Skill (`skill/SKILL.md`) wird erweitert um:
- Phase 1 (Questionnaire): Frage "Soll der Agent Code Mode nutzen?"
- Phase 2 (Plan): Code Mode Section im Workflow-Plan
- Phase 3 (Generation): Auto-Generierung des Code-Mode-Skills + SDK-Types

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

## 6. Dateien-Übersicht (alle Phasen)

### Phase 1: Cloudflare Adapter (11 Dateien)

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

### Phase 2: Code Mode Protokoll-Integration (~20 Dateien)

| Datei | Typ | Beschreibung |
|-------|-----|-------------|
| `spec/versions/1.0/layers/02-capabilities.md` | **Änderung** | Code Mode Spezifikation (Abschnitt 8) |
| `spec/versions/1.0/validation-rules.md` | **Änderung** | R19-R24, CT10 |
| `schemas/v1.0/agent.awp.schema.json` | **Änderung** | codemode + isolate Schema |
| `docs/tools.md` | **Änderung** | Code Mode Dokumentation |
| `docs/skill-system.md` | **Änderung** | Code-Mode-Skill Generierung |
| `docs/runtime.md` | **Änderung** | Code Mode Runtime-Guide |
| `skill/SKILL.md` | **Änderung** | Code Mode in Generierungs-Phasen |
| `skill/templates/agent-full.awp.yaml` | **Änderung** | codemode Section |
| `skill/templates/codemode-skill.md` | **Neu** | Auto-generiertes Skill Template |
| `skill/templates/codemode-sdk.ts.tmpl` | **Neu** | TypeScript SDK Template |
| `skill/templates/codemode-sdk.py.tmpl` | **Neu** | Python SDK Template |
| `reference/python/src/awp/runtime/codemode.py` | **Neu** | CodeModeExecutor |
| `reference/python/src/awp/runtime/sdk_generator.py` | **Neu** | SDK aus Tool-Registry |
| `reference/python/src/awp/runtime/runner.py` | **Änderung** | Code Mode Support |
| `reference/python/src/awp/validator/rules.py` | **Änderung** | R19-R24 Validierung |
| `examples/06-codemode/` | **Neu** | Beispiel-Workflow mit Code Mode |

### Phase 3: TypeScript-Runtime (langfristig)

| Datei | Typ | Beschreibung |
|-------|-----|-------------|
| `reference/cloudflare/` | **Neu** | Vollständiges npm-Package `awp-cloudflare` |
| `reference/cloudflare/src/runtime/codemode.ts` | **Neu** | CF-native CodeModeExecutor mit Isolates |
| `reference/cloudflare/src/runtime/shell.ts` | **Neu** | `@cloudflare/shell` Integration |

---

## 7. Abgrenzung: Was Phase 1 NICHT enthält

- Keine Spec-Änderungen (→ Phase 2)
- Kein Code Mode im Protokoll (→ Phase 2)
- Keine Python CodeModeExecutor (→ Phase 2)
- Keine vollständige TypeScript-Runtime (→ Phase 3)
- Keine `@cloudflare/codemode` Integration (→ Phase 3)
- Keine `@cloudflare/shell` Integration (→ Phase 3)
- Kein Durable Objects Message Bus (→ Phase 3)
- Kein ClawHub One-Click Deploy (→ separat)
- Keine Conformance Tests für Cloudflare (→ Phase 3)

---

## 8. Risiken & Mitigationen

| Risiko | Wahrscheinlichkeit | Mitigation |
|--------|-------------------|------------|
| Dynamic Workers API ändert sich | Hoch (brandneu) | Adapter ist Markdown — leicht anpassbar |
| Worker Loader Pricing ändert sich | Mittel | Kosten-Abschnitt im Adapter versioniert |
| D1/R2 Limits für große Workflows | Niedrig | Adapter dokumentiert Limits, Fallback auf KV |
| LLM-Aufrufe aus Workers haben Latenz-Limits | Mittel | Timeout-Config in wrangler.toml anpassbar |
| LLM generiert fehlerhaften Code im Code Mode | Hoch | `max_retries` + `capture_console` für Debugging; Fallback auf Classic Mode |
| Code Mode SDK-Oberfläche zu groß | Niedrig | `sdk_surface.mode: explicit` erlaubt manuelle Auswahl |
| Security: Code Injection über LLM-Output | Mittel | Sandbox-Isolation ist Pflicht (R20); Netzwerk default blockiert |

---

## 9. Erfolgs-Kriterien

### Phase 1 gilt als abgeschlossen wenn:

1. `skill/adapters/cloudflare-dynamic-workers.md` existiert und dem Adapter-Format folgt
2. Alle Templates in `skill/templates/adapters/cloudflare/` sind vollständig
3. Der Skill kann bei "Build me a workflow for Cloudflare" den richtigen Adapter laden
4. Ein generierter Hello-World-Workflow lässt sich mit `wrangler deploy` deployen
5. Dokumentation in `docs/runtime.md` ist aktualisiert

### Phase 2 gilt als abgeschlossen wenn:

6. `capabilities.codemode` ist in der Spec (Layer 2) vollständig dokumentiert
7. `sandbox.type: isolate` + `sandbox.network` sind im Schema definiert
8. Validierungsregeln R19-R24 und CT10 sind implementiert
9. `skill/templates/agent-full.awp.yaml` enthält die `codemode` Section
10. SDK-Templates (TypeScript + Python) existieren
11. Python `CodeModeExecutor` + `SDKGenerator` sind implementiert
12. `examples/06-codemode/` ist lauffähig mit `awp run`
13. `skill/SKILL.md` fragt in Phase 1 nach Code Mode und generiert es in Phase 3
14. Code-Mode-Skill wird automatisch aus `tools.allowed` generiert

### Phase 3 gilt als abgeschlossen wenn:

15. `awp-cloudflare` npm-Package ist publishbar
16. CF-native `CodeModeExecutor` nutzt Dynamic Worker Isolates
17. `@cloudflare/shell` Integration für Workspace-State
18. Alle 5+ Beispiel-Workflows laufen auf Cloudflare
19. Conformance Tests L0-L3 bestehen auf CF-Runtime
