# Layer 4: Memory & State

**AWP Specification v1.0.0 — Layer 4**
**Status:** Draft Standard

> **See also** — **Parent**: [spec.md](../spec.md), [docs/layer-model.md](../../../../docs/layer-model.md) · **Non-normative explainer**: [docs/memory.md](../../../../docs/memory.md) · **Push-based alternative**: [03-communication.md](03-communication.md) · **Consumer layer**: [05-orchestration.md](05-orchestration.md) (nodes read/write state via `share_output`) · **Agent-level memory config**: [01-agent-identity.md](01-agent-identity.md) · **Agent output contract R17 (normative)**: [../validation-rules.md](../validation-rules.md)

---

## 1. Overview

Layer 4 defines the state model, state sharing strategy, output contracts, and memory architecture for AWP workflows. State is the primary mechanism through which agents share data within a workflow execution. Memory provides persistent knowledge across executions.

---

## 2. State Model

The `state` section of `workflow.awp.yaml` configures how execution state is managed.

### 2.1 Fields

| Field | Type | Status | Default | Description |
|-------|------|--------|---------|-------------|
| `model` | string | OPTIONAL | `"shared_dict"` | State model type. MUST be one of: `"shared_dict"`, `"event_sourced"`, `"cqrs"`. |
| `initial` | object | OPTIONAL | `{}` | Initial state values injected before the first agent executes. |
| `required_fields` | list | OPTIONAL | `[]` | Fields that MUST be present in the initial state or injected via `auto_inject`. |
| `auto_inject` | object | OPTIONAL | `{}` | Key-value pairs automatically injected into the state at run start. |
| `reserved_keys` | list | — | See below | Keys reserved by the runtime. Agents MUST NOT write to these keys. |
| `persistence` | object | OPTIONAL | — | State persistence configuration. |
| `limits` | object | OPTIONAL | — | State size limits. |

### 2.2 State Model Types

#### 2.2.1 `shared_dict`

The default state model. State is a flat dictionary shared among all agents.

- Each agent writes to `state[agent_id]` after execution.
- All agents MAY read any key in the state (subject to sharing rules).
- The runtime MUST ensure atomic updates to the state dictionary.

#### 2.2.2 `event_sourced`

State is derived from an append-only event log.

- Each agent emits events rather than directly mutating state.
- The current state is computed by replaying events.
- Events MUST include: `event_id`, `timestamp`, `agent_id`, `type`, `payload`.
- The runtime MUST maintain the event log for the duration of the run.

#### 2.2.3 `cqrs`

Command Query Responsibility Segregation.

- Write operations (commands) and read operations (queries) use separate models.
- Agents issue commands that are processed by the runtime.
- Queries read from a projection of the event stream.
- The runtime MUST maintain consistency between the command and query models.

### 2.3 Reserved Keys

The following state keys are reserved by the runtime. Agents MUST NOT write to these keys directly:

| Key | Description |
|-----|-------------|
| `_meta` | Runtime metadata (run_id, timestamps, status). |
| `_errors` | Error accumulator for the current run. |
| `_trace` | Trace context for distributed tracing. |
| `_workflow` | Workflow-level metadata (name, version). |

### 2.4 Persistence

| Field | Type | Status | Default | Description |
|-------|------|--------|---------|-------------|
| `persistence.enabled` | boolean | OPTIONAL | `true` | Whether state is persisted to disk. |
| `persistence.path` | string | OPTIONAL | `"data/state"` | Directory for state files, relative to workflow root. |
| `persistence.format` | string | OPTIONAL | `"json"` | Serialization format. MUST be one of: `"json"`, `"msgpack"`. |
| `persistence.interval` | string | OPTIONAL | `"per_agent"` | When to persist. MUST be one of: `"per_agent"`, `"per_run"`, `"manual"`. |

### 2.5 Limits

| Field | Type | Status | Default | Description |
|-------|------|--------|---------|-------------|
| `limits.max_state_size_mb` | float | OPTIONAL | `10.0` | Maximum total state size in megabytes. |
| `limits.max_field_size_mb` | float | OPTIONAL | `1.0` | Maximum size of any single state field. |
| `limits.max_fields` | integer | OPTIONAL | `1000` | Maximum number of top-level state keys. |

---

## 3. State Sharing

The `state.sharing` section controls how agent outputs are shared with downstream agents.

### 3.1 Fields

| Field | Type | Status | Default | Description |
|-------|------|--------|---------|-------------|
| `strategy` | string | REQUIRED | — | MUST be one of: `"full"`, `"selective"`, `"isolated"`. |
| `rules` | list | OPTIONAL | `[]` | Sharing rules for `selective` strategy. |
| `never_share` | list | OPTIONAL | `[]` | Fields that MUST NOT be shared regardless of strategy. |
| `sensitive_fields` | list | OPTIONAL | `[]` | Fields that MUST be redacted in logs and observability output. |

### 3.2 Sharing Strategies

#### 3.2.1 `full`

All agent outputs are visible to all downstream agents.

- Every agent MAY read `state[other_agent_id]` for any agent that has already executed.
- No filtering is applied.

#### 3.2.2 `selective`

Only explicitly shared fields are visible to downstream agents.

- The `share_output` field on each graph node (Layer 5) lists the fields that agent exposes.
- Downstream agents MAY only read the listed fields from upstream agents.
- The runtime MUST filter the state to exclude non-shared fields.

#### 3.2.3 `isolated`

Each agent sees only its own state and explicitly passed inputs.

- Agents MUST NOT read other agents' state entries.
- Data transfer between agents MUST be explicit via `share_input` in the graph node (Layer 5).

### 3.3 Sharing Rules

For the `selective` strategy, rules provide fine-grained control:

```yaml
state:
  sharing:
    strategy: selective
    rules:
      - from: research_analyst
        to: report_writer
        fields:
          - findings
          - summary
          - confidence_scores
      - from: research_analyst
        to: quality_reviewer
        fields:
          - findings
    never_share:
      - raw_api_responses
      - internal_reasoning
    sensitive_fields:
      - api_keys
      - user_credentials
```

---

## 4. Output Contract

Each agent's output contract is defined in `agent.awp.yaml` under `output.contract` (see Layer 1, Section 8.2). This section specifies how the contract integrates with state sharing.

### 4.1 Contract Field Annotations

When the output contract is a JSON Schema, fields MAY include AWP-specific annotations:

| Annotation | Type | Description |
|------------|------|-------------|
| `x-awp-shareable` | boolean | Whether this field MAY be shared with downstream agents. Default: `true`. |
| `x-awp-sensitive` | boolean | Whether this field contains sensitive data. Default: `false`. |
| `x-awp-required` | boolean | Whether this field MUST be present in the output. Default: per JSON Schema `required`. |
| `x-awp-description` | string | Human-readable description for documentation and AIC generation. |

### 4.2 Example Output Contract

```json
{
  "type": "object",
  "required": ["decision", "summary"],
  "properties": {
    "decision": {
      "type": "string",
      "enum": ["proceed", "revise", "reject"],
      "x-awp-shareable": true,
      "x-awp-description": "The agent's decision on how to proceed."
    },
    "summary": {
      "type": "string",
      "x-awp-shareable": true,
      "x-awp-description": "A brief summary of the analysis."
    },
    "raw_data": {
      "type": "object",
      "x-awp-shareable": false,
      "x-awp-description": "Raw data used for analysis. Not shared downstream."
    },
    "api_token": {
      "type": "string",
      "x-awp-sensitive": true,
      "x-awp-shareable": false,
      "x-awp-description": "Temporary API token. Sensitive."
    }
  }
}
```

---

## 5. Memory Architecture

AWP defines a four-tier memory architecture. Memory operates at the workflow level and is shared across runs.

### 5.1 Tier 1: Long-Term Memory

- **File:** `workspace/MEMORY.md`
- **Type:** Curated knowledge store.
- **Behavior:**
  - Contains stable facts, preferences, policies, and learned patterns.
  - Content is injected into agent prompts under a "Long-term Memory" section.
  - Content is curated by the `memory.curate` tool, which uses an LLM to extract stable facts from daily logs.
  - Agents MAY write to long-term memory via `memory.write` with `target: "long_term"`.
- **Injection:** The runtime MUST inject MEMORY.md content into the agent's prompt if `memory.long_term_inject` is `true` in the agent's configuration.
- **Size Limit:** Injection MUST be truncated to `memory.long_term_max_tokens` characters.

### 5.2 Tier 2: Working Memory (Daily Logs)

- **Files:** `workspace/memory/YYYY-MM-DD.md`
- **Type:** Append-only daily logs.
- **Behavior:**
  - One file per calendar day.
  - The orchestrator SHOULD auto-log each agent's result after execution.
  - Agents MAY write to the daily log via `memory.write` with `target: "daily"`.
  - Daily logs are the source material for long-term memory curation.
- **Retention:** Daily logs SHOULD be retained for at least 30 days. Older logs MAY be archived or deleted.

### 5.3 Tier 3: Episodic Memory (Agent Outputs)

- **Storage:** State persistence files and run artifacts.
- **Type:** Per-agent execution history.
- **Behavior:**
  - Each agent's output from each run is stored as part of the run state.
  - Agents MAY query previous run outputs for context.
  - Episodic memory is read-only from the agent's perspective; it is written by the runtime.

### 5.4 Tier 4: Semantic Memory (Vector Search)

- **Storage:** Vector index (e.g., FAISS, Chroma, Qdrant).
- **Type:** Embedding-based semantic search.
- **Status:** OPTIONAL. Runtimes MAY implement this tier.
- **Behavior:**
  - Documents and agent outputs are embedded and indexed.
  - Agents MAY search via the `memory.search` tool with semantic queries.
  - The runtime MUST declare the embedding model and similarity metric.

### 5.5 Memory Configuration

In `agent.awp.yaml`:

```yaml
memory:
  enabled: true
  long_term_inject: true
  long_term_max_tokens: 2000
  daily_log_enabled: true
  daily_log_auto_write: true
  search_enabled: true
  tiers:
    - long_term
    - working
    - episodic
```

In `workflow.awp.yaml`:

```yaml
memory:
  enabled: true
  workspace_dir: "workspace"
  tiers:
    long_term:
      enabled: true
      file: "MEMORY.md"
      max_size_kb: 100
    working:
      enabled: true
      directory: "memory"
      retention_days: 30
    episodic:
      enabled: true
    semantic:
      enabled: false
      index_path: "data/embeddings"
      embedding_model: "text-embedding-3-small"
      similarity_metric: cosine
```

---

## 6. Access Control

Memory access MAY be restricted per agent per tier.

### 6.1 Configuration

```yaml
memory:
  access_control:
    research_analyst:
      long_term: read_write
      working: read_write
      episodic: read
      semantic: read
    report_writer:
      long_term: read
      working: read_write
      episodic: read
      semantic: read
```

### 6.2 Permission Levels

| Level | Description |
|-------|-------------|
| `none` | Agent MUST NOT access this tier. |
| `read` | Agent MAY read from this tier but MUST NOT write. |
| `read_write` | Agent MAY read from and write to this tier. |

If access control is not configured, the default is `read_write` for all tiers that the agent has enabled.

---

## 7. Search

The `memory.search` tool provides search across memory tiers.

### 7.1 Search Modes

| Mode | Description | Applicable Tiers |
|------|-------------|-----------------|
| `keyword` | Exact or fuzzy keyword matching across memory files. | long_term, working |
| `semantic` | Embedding-based similarity search. | semantic |
| `date_range` | Filter working memory by date range. | working |
| `agent_filter` | Filter episodic memory by agent ID. | episodic |

### 7.2 Search Request

```json
{
  "query": "search terms",
  "mode": "keyword",
  "tiers": ["long_term", "working"],
  "date_range": {
    "start": "2026-03-01",
    "end": "2026-03-23"
  },
  "agent_filter": ["research_analyst"],
  "max_results": 10
}
```

### 7.3 Search Response

```json
{
  "ok": true,
  "status": 200,
  "data": {
    "results": [
      {
        "tier": "working",
        "source": "workspace/memory/2026-03-23.md",
        "content": "Matched text snippet...",
        "score": 0.95,
        "timestamp": "2026-03-23T10:00:00Z"
      }
    ],
    "total": 1
  }
}
```

---

## 8. Complete Example

```yaml
state:
  model: shared_dict
  initial:
    context:
      topic: "quantum computing"
  required_fields:
    - context
  auto_inject:
    workflow_name: research-and-write
    run_timestamp: "${now}"
  persistence:
    enabled: true
    path: "data/state"
    format: json
    interval: per_agent
  limits:
    max_state_size_mb: 10.0
    max_field_size_mb: 1.0
    max_fields: 1000
  sharing:
    strategy: selective
    rules:
      - from: research_analyst
        to: report_writer
        fields:
          - findings
          - summary
      - from: report_writer
        to: quality_reviewer
        fields:
          - draft
          - metadata
    never_share:
      - raw_api_responses
    sensitive_fields:
      - api_credentials

memory:
  enabled: true
  workspace_dir: "workspace"
  tiers:
    long_term:
      enabled: true
      file: "MEMORY.md"
      max_size_kb: 100
    working:
      enabled: true
      directory: "memory"
      retention_days: 30
    episodic:
      enabled: true
    semantic:
      enabled: false
  access_control:
    research_analyst:
      long_term: read_write
      working: read_write
      episodic: read
    report_writer:
      long_term: read
      working: read_write
      episodic: read
```

---

## 9. Processing Rules

1. The runtime MUST initialize the state with `initial` values and `auto_inject` values before the first agent executes.
2. The runtime MUST validate that all `required_fields` are present in the state before starting execution.
3. The runtime MUST enforce the `sharing.strategy` and filter state access accordingly.
4. Fields listed in `never_share` MUST NOT be visible to any agent other than the agent that produced them.
5. Fields listed in `sensitive_fields` MUST be redacted in all log output and observability data.
6. Agents MUST NOT write to reserved state keys (`_meta`, `_errors`, `_trace`, `_workflow`).
7. The runtime MUST enforce `limits.max_state_size_mb` and reject writes that would exceed the limit.
8. Memory tier access MUST be enforced per the `access_control` configuration.
9. Long-term memory injection MUST be truncated to `long_term_max_tokens` characters.
10. Daily log auto-write SHOULD include the agent ID, timestamp, and a summary of the agent's output.
