# Memory & State Reference

## Mental Model

Layer 4 answers two distinct but related questions: **"What does this run know right now?"** (state) and **"What does this workflow remember from past runs?"** (memory). Keeping the two separate is essential — conflating them is the most common modeling mistake in multi-agent systems.

**State** is the ephemeral, per-run scratchpad that agents read from and write to as the DAG executes. It is filtered by a `sharing.strategy` (`full`, `selective`, or `isolated`) so that downstream agents only see what they are explicitly allowed to see. State dies when the run ends (unless persisted for resume/replay).

**Memory** is the durable knowledge store that survives across runs. AWP defines a deliberate **4-tier hierarchy** modeled on cognitive science: long-term (curated facts in `MEMORY.md`), working (append-only daily logs), episodic (per-agent run history), and semantic (vector index). Memory promotes information *upward* over time: today's working-memory observations get curated into tomorrow's long-term knowledge via the `memory.curate` tool. In the [Experiment paradigm](ui.md), memory is **scoped per Experiment** — each Experiment has its own Protocol/Memory tab, so two parallel experiments do not pollute each other's long-term store.

State sharing rules are enforced by the runtime as **rule R16** ([validation.md](validation.md)) and integrate with [security](security.md): `sensitive_fields` and `never_share` are redacted before any [observability](observability.md) sink sees them. Memory access is gated by per-agent `access_control` and audited as `memory.write` events.

State is configured under `state` in [workflow.awp.yaml](manifest.md); memory under `memory`.

### Ephemeral Run-Scoped Tiers (Delegation Loop)

Delegation loops add two ephemeral, run-scoped memory channels that
sit **below** the four durable tiers — they live only for the
duration of a single manager run and are discarded at the end:

- **Blackboard** — append-only JSONL sibling-coordination channel
  (`board.post` / `board.read`). One per manager run, isolated per
  depth. See [runtime.md](runtime.md#blackboard-channel-sibling-coordination).
- **Hierarchical Context Digest (HCD)** — content-addressed, per-level
  compact summary (`digest.fetch`) that compresses each manager
  iteration into a deterministic goal / key_facts / open_questions /
  confidence_trend record, with child digest SHAs linking the
  hierarchy together. See
  [runtime.md](runtime.md#hierarchical-context-digest) and
  [manager-intelligence.md](manager-intelligence.md#hierarchical-context-digest-hcd).

Both tiers are run-scoped via `ContextVar` bindings so parallel
delegation runs never cross-contaminate. At run end, the
**Auto-Curation** layer deterministically promotes selected
knowledge from the digest hierarchy, the dynamic-tools registry,
and the runner's failed-signature log into the durable long-term
tier (see next section). Everything not curated is discarded with
the run.

### Auto-Curation (Baustein 4)

When `delegation_loop.auto_curation_enabled` is `true` (the default),
a deterministic :class:`Curator` runs after the root manager's
delegation loop terminates. It writes reusable knowledge into
`<workflow_dir>/memory/`:

- `memory/tools/<recipe>.md` — tool recipes for every tool present
  in the dynamic-tool registry at run end. Dedupe key is
  `name + content_hash(spec)`. Same name + new hash appends a
  `## v{n}` section; same name + same hash is a no-op.
- `memory/facts/YYYY-MM-DD.md` — cross-confirmed facts. The curator
  walks the digest hierarchy rooted at `runner._current_digest_sha`,
  counts each distinct `key_facts` entry across digests, and emits
  those appearing in **>=2** digests. Daily file is append-only and
  dedupes by exact line match.
- `memory/antipatterns/<sha>.md` — failed delegation signatures
  collected by the runner during the loop: redundant re-dispatch,
  worker error, or worker confidence `<0.3`. Content-addressed by
  `sha256(signature)[:16]`, so re-running curate on the same run is
  idempotent.

The curator is pure-deterministic in v1 — no LLM calls — and is
wrapped in a try/except so a curator failure NEVER fails a run.
It runs **only on root managers** (submanagers share the parent's
workflow_dir; restricting to root keeps `run_id` attribution clean).

**Priming the next run.** On the first iteration of the root
manager, `Curator.read_prior_memory(workflow_dir)` reads these
three directories and renders a compact `## PRIOR RUN MEMORY`
block (capped at ~3000 chars) which `_build_manager_task` injects
into the manager prompt. Submanagers never see this block — they
inherit priors through the digest tree from their parent instead.

This closes the loop: runs learn from prior runs without any human
curation step. With `auto_curation_enabled: false`, both the
writeback and the priming are skipped and behavior reverts to
S3's "forget on run end" semantics.

## State Model

The `state` section of [workflow.awp.yaml](manifest.md) configures execution state management.

### State Model Types

#### `shared_dict` (Default)

State is a flat dictionary shared among all agents.

- Each agent writes to `state[agent_id]` after execution.
- All agents may read any key in the state (subject to sharing rules).
- The runtime must ensure atomic updates.

#### `event_sourced`

State is derived from an append-only event log.

- Each agent emits events rather than directly mutating state.
- Current state is computed by replaying events.
- Events must include: `event_id`, `timestamp`, `agent_id`, `type`, `payload`.

#### `cqrs`

Command Query Responsibility Segregation.

- Write operations (commands) and read operations (queries) use separate models.
- Agents issue commands processed by the runtime.
- Queries read from a projection of the event stream.

### State Configuration Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `model` | string | `"shared_dict"` | `"shared_dict"`, `"event_sourced"`, or `"cqrs"`. |
| `initial` | object | `{}` | Initial state values injected before the first agent executes. |
| `required_fields` | list | `[]` | Fields that must be present in initial state or via `auto_inject`. |
| `auto_inject` | object | `{}` | Key-value pairs injected into state at run start. |

### Reserved State Keys

Agents must not write to these keys (see [R13](validation.md)):

| Key | Description |
|-----|-------------|
| `_meta` | Runtime metadata (run_id, timestamps, status). |
| `_errors` | Error accumulator for the current run. |
| `_trace` | Trace context for distributed tracing. |
| `_workflow` | Workflow-level metadata (name, version). |

### State Persistence

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `persistence.enabled` | boolean | `true` | Whether state is persisted to disk. |
| `persistence.path` | string | `"data/state"` | Directory for state files. |
| `persistence.format` | string | `"json"` | `"json"` or `"msgpack"`. |
| `persistence.interval` | string | `"per_agent"` | When to persist: `"per_agent"`, `"per_run"`, or `"manual"`. |

### State Limits

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `limits.max_state_size_mb` | float | `10.0` | Maximum total state size in megabytes. |
| `limits.max_field_size_mb` | float | `1.0` | Maximum size of any single state field. |
| `limits.max_fields` | integer | `1000` | Maximum number of top-level state keys. |

## State Sharing

The `state.sharing` section controls how agent outputs flow to downstream agents.

### Sharing Strategies

#### `full`

All agent outputs are visible to all downstream agents.

- Every agent may read `state[other_agent_id]` for any completed agent.
- No filtering is applied.

#### `selective`

Only explicitly shared fields are visible to downstream agents.

- The `share_output` field on each graph node (in [orchestration](orchestration.md)) lists exposed fields.
- Downstream agents may only read the listed fields.
- The runtime must filter state to exclude non-shared fields.

#### `isolated`

Each agent sees only its own state and explicitly passed inputs.

- Agents must not read other agents' state entries.
- Data transfer between agents must be explicit via `share_input`.

### Sharing Configuration

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `strategy` | string | -- | Required. `"full"`, `"selective"`, or `"isolated"`. |
| `rules` | list | `[]` | Fine-grained sharing rules for `selective` strategy. |
| `never_share` | list | `[]` | Fields that must not be shared regardless of strategy. |
| `sensitive_fields` | list | `[]` | Fields redacted in logs and observability. See [R14](validation.md). |

### Sharing Rules

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

### Output Contracts and State Sharing

Each agent's output contract (defined in [agent.awp.yaml](agent.md)) declares which fields the agent produces. The `share_output` list in the orchestration graph determines which of those fields are visible downstream. Fields annotated with `x-awp-shareable: false` in the contract are never shared, regardless of the `share_output` list.

## The 4-Tier Memory Architecture

AWP defines four memory tiers. Memory operates at the workflow level and persists across runs.

### Tier 1: Long-Term Memory

- **File:** `workspace/MEMORY.md`
- **Type:** Curated knowledge store.
- **Contents:** Stable facts, preferences, policies, and learned patterns.
- **Injection:** Content is injected into agent prompts under a "Long-term Memory" section when `memory.long_term_inject` is `true`.
- **Size limit:** Injection is truncated to `memory.long_term_max_tokens` characters.
- **Writing:** Agents may write via `memory.write` tool with `target: "long_term"`. The `memory.curate` tool uses an LLM to extract stable facts from daily logs into MEMORY.md.

### Tier 2: Working Memory (Daily Logs)

- **Files:** `workspace/memory/YYYY-MM-DD.md`
- **Type:** Append-only daily logs.
- **Contents:** One file per calendar day. The orchestrator auto-logs each agent's result after execution.
- **Writing:** Agents may write via `memory.write` tool with `target: "daily"`.
- **Retention:** Daily logs should be retained for at least 30 days. Older logs may be archived or deleted.

### Tier 3: Episodic Memory (Agent Outputs)

- **Storage:** State persistence files and run artifacts.
- **Type:** Per-agent execution history.
- **Access:** Agents may query previous run outputs for context. Read-only from the agent's perspective.

### Tier 4: Semantic Memory (Vector Search)

- **Storage:** Vector index (e.g., FAISS, Chroma, Qdrant).
- **Type:** Embedding-based semantic search.
- **Status:** Optional. Runtimes may implement this tier.
- **Access:** Agents search via the `memory.search` tool with semantic queries.

### Memory Configuration in workflow.awp.yaml

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

### Memory Configuration in agent.awp.yaml

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

## Memory Access Control

Memory access may be restricted per agent per tier.

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

### Permission Levels

| Level | Description |
|-------|-------------|
| `none` | Agent must not access this tier. |
| `read` | Agent may read but must not write. |
| `read_write` | Agent may read and write. |

If access control is not configured, the default is `read_write` for all enabled tiers.

## Memory Search

The `memory.search` tool provides search across memory tiers.

### Search Modes

| Mode | Description | Applicable Tiers |
|------|-------------|-----------------|
| `keyword` | Exact or fuzzy keyword matching. | long_term, working |
| `semantic` | Embedding-based similarity search. | semantic |
| `date_range` | Filter working memory by date range. | working |
| `agent_filter` | Filter episodic memory by agent ID. | episodic |

### Search Request Example

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

### Search Response Example

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

## Memory Curation

The `memory.curate` tool uses an LLM to extract stable facts from daily logs into MEMORY.md. This is the bridge between Tier 2 (working) and Tier 1 (long-term) memory. Curation should be run periodically (e.g., at the end of each day or workflow run) to promote recurring patterns and important findings to long-term memory.

## Complete Example

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

## Processing Rules

1. The runtime must initialize state with `initial` values and `auto_inject` values before the first agent executes.
2. The runtime must validate that all `required_fields` are present before starting execution.
3. The runtime must enforce the `sharing.strategy` and filter state access accordingly. See [R16](validation.md).
4. Fields in `never_share` must not be visible to any agent other than the producer.
5. Fields in `sensitive_fields` must be redacted in all log and observability output. See [R14](validation.md).
6. Agents must not write to reserved state keys. See [R13](validation.md).
7. The runtime must enforce `limits.max_state_size_mb` and reject writes exceeding the limit.
8. Memory tier access must be enforced per the `access_control` configuration.
9. Long-term memory injection must be truncated to `long_term_max_tokens` characters.
10. Daily log auto-write should include the agent ID, timestamp, and a summary of the agent's output.
