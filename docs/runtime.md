# Runtime & Platform Integration

## Mental Model

AWP is intentionally **runtime-agnostic**. The protocol (YAML manifests, agent contracts, validation rules) is normative; the runtime that *executes* a workflow is pluggable. This separation is what lets the same `workflow.awp.yaml` run unchanged on the standalone Python runtime, on Cloudflare Workers, inside Jupyter, or on a custom adapter for LangGraph / CrewAI.

A runtime, regardless of platform, has four responsibilities:

1. **Parse and validate** the manifest and all agent files (rules R1-R32, see [validation.md](validation.md)).
2. **Resolve providers and credentials** for the LLMs each agent declares (see "Provider Routing" below).
3. **Execute the orchestration engine** — DAG or delegation loop — while honoring the safety envelope (budgets, sandbox, forbidden tools).
4. **Enforce the agent output contract (R17)**: every `AWPAgent.run()` must return `{self.name: {"confidence": 0.0-1.0, ...}}`. Without it, the runtime rejects the result.

The reference Python runtime adds two cross-cutting features that are **enabled by default** in modern versions, because they are essential for A2-A4 workloads:

- **Code mode** — workers emit a single code block against a typed SDK instead of issuing many tool calls. Collapses N round-trips into one. See [tools.md](tools.md#code-mode--alternative-tool-execution).
- **Runtime tool generation (B1-B6)** — workers can generate new MCP tools at runtime when the existing tools are insufficient. The runtime runs them through a six-phase pipeline (Brief → Generate → Validate → Sandbox → Auto-Repair → Register) before exposing them to the LLM. See [runtime-tool-generation.md](runtime-tool-generation.md).

This file documents the abstract `AWPAgent` interface, the standalone reference runtime, environment variables, the Cloudflare Workers adapter, and how to build a new platform adapter. For execution semantics see [orchestration.md](orchestration.md) and [ORCHESTRATION_ENGINES.md](ORCHESTRATION_ENGINES.md).

### Delegation Loop Termination Envelope

The delegation loop runner is **bounded on every axis** — this is what makes an A2-A4 run provably terminating regardless of LLM behaviour:

- **Hard budget** — `max_loops`, `max_total_workers`, `max_total_tokens`, `max_wall_time`, `max_depth`. The manager cannot override any of them.
- **LLM call tracing** — optional (`trace_enabled: false` by default). When enabled, every LLM API call is persisted as `llm_trace/call_NNN.json` with full messages, response, token usage, and latency. See [observability.md](observability.md#llm-call-tracing).
- **Submanager caps** — `max_concurrent_submanagers` (default 3) and `max_total_submanagers_per_run` (default 6); each submanager's child budget is `min(0.3, 0.8 / n)` of the parent's remaining envelope, where *n* is the number of submanagers spawned in the same dispatch.
- **Convergence detector** — the loop force-completes with `partial: true, reason: forced_convergence` when confidence deltas across the last two iterations drop below 0.05 or three consecutive iterations emit identical `key_findings`. The minimum-iteration floor is `max(5, pending_subtask_count + 3)` so the detector never fires while unstarted subtasks remain in the task plan.
- **Redundancy guard** — every dispatch is fingerprinted by a sorted hash of normalised worker instructions **combined with a stable canonical JSON of the context the envelope references** (`context`, `input_context`, or the set of `inherited_state_keys`). This content-aware signature stops flagging identical instructions over different inputs as redundant; envelopes that reference no context hash identically to the legacy instructions-only signature (backward compatible). If a new dispatch matches an earlier signature and the mean critique score is below `critique.min_score_to_complete`, the manager is forced into DIAGNOSE instead of re-issuing the same subtasks.
- **Submanager state inheritance** — children inherit the parent's full state by default (no more "born blind" submanagers). An explicit `inherited_state_keys` whitelist on the envelope still wins (legacy behaviour), and a `forbidden_inheritance_keys` blacklist — per-envelope or at `delegation_loop.forbidden_inheritance_keys` in config — strips sensitive or oversized keys from the default inherit-all slice.
- **Submanager output merging** — each submanager writes into its own `output/<sub_run_id>/` sandbox; on completion the parent runner's `_merge_submanager_outputs` copies those files back into the parent's `_output_dir`, prefixing colliding names with `<submanager_name>__` so nothing is silently overwritten. The merged filenames are attached to the sub-result as `_merged_files` so the manager can see what the child produced.
- **Completion gates** — placeholder scanner, file-validator gate, deliverable-presence gate, and critique-score gate must all pass before a `COMPLETE` decision is accepted (see [critique.md](critique.md)).

## Provider Routing

Models are declared as plain strings; the runtime auto-detects the provider from the prefix:

| Model string pattern | Routed to | Required env var |
|---|---|---|
| `provider/model-name` (e.g. `openai/gpt-5-mini`, `anthropic/claude-sonnet-4`) | **OpenRouter** | `OPENROUTER_API_KEY` |
| `gpt-*`, `o1-*`, `o3*` | **OpenAI direct** | `OPENAI_API_KEY` |
| `claude-*` | **Anthropic direct** | `ANTHROPIC_API_KEY` |
| `ollama/*` | **Ollama (local)** | none |

Defaults for the delegation loop engine:

- **Manager model**: `nvidia/nemotron-3-super-120b-a12b` (strong reasoning for decomposition and validation)
- **Worker model**: `openai/gpt-5-mini` (fast and cheap for ephemeral workers)

The manager **cannot** override the worker model at runtime — that decision belongs to the user via the manifest or the CLI flags `--manager-model` / `--worker-model`. This prevents a hallucinating manager from upgrading workers to expensive models.

## AWPAgent Abstract Interface

Every AWP-compliant platform must provide an agent class that implements this interface:

```python
from abc import ABC, abstractmethod
from typing import Any, Dict


class AWPAgent(ABC):
    """Minimal AWP agent contract."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique agent identifier in the workflow DAG.

        Must match the identity.id field in agent.awp.yaml.
        """

    @abstractmethod
    def run(self, task: str, state: Dict[str, Any]) -> Dict[str, Any]:
        """Execute the agent.

        Args:
            task: Human-readable task description.
            state: Shared workflow state dictionary containing outputs
                   from previously executed agents (keyed by agent name)
                   and auto-injected fields from the manifest.

        Returns:
            A dict with at minimum {self.name: result_dict}.
            result_dict must include a 'confidence' field (float, 0.0-1.0)
            per validation rule R17.
        """
```

### Contract Requirements

1. The `name` property must return a string matching `identity.id` in `agent.awp.yaml`.
2. The `run` method receives the current task and shared state.
3. The return value must be a dict with at least one key equal to `self.name`.
4. The result dict under `self.name` must include a `confidence` field (number, 0.0-1.0).
5. Additional top-level keys may be included for metadata or logging.

### Example Implementation

```python
from awp.agent import AWPAgent


class Agent(AWPAgent):
    @property
    def name(self) -> str:
        return "researcher"

    def run(self, task: str, state: dict) -> dict:
        # Your agent logic here
        findings = do_research(task)
        return {
            self.name: {
                "findings": findings,
                "summary": summarize(findings),
                "confidence": 0.85,
            }
        }
```

## Standalone Runtime

The `awp-agents` package includes a minimal standalone runtime for executing AWP workflows without any external framework.

### Installation

```bash
pip install awp-agents
```

### Components

#### StandaloneAgent

A concrete AWPAgent implementation that:
1. Reads `agent.awp.yaml` for configuration.
2. Loads system prompt from `workflow/instructions/SYSTEM_PROMPT.md`.
3. Loads user prompt from `workflow/prompt/00_INTRO.md`.
4. Builds context from previous agent outputs in state.
5. Calls the LLM via an OpenAI-compatible API.
6. Parses the response as JSON matching `output_schema.json`.
7. Returns `{agent_id: parsed_result}`.

```python
from awp.runtime.agent import StandaloneAgent
from pathlib import Path

agent = StandaloneAgent(
    agent_dir=Path("my-workflow/agents/researcher"),
    workflow_dir=Path("my-workflow"),
)
result = agent.run("Research quantum computing", state={})
# result == {"researcher": {"summary": "...", "confidence": 0.85}}
```

#### WorkflowRunner

A minimal DAG executor that reads `workflow.awp.yaml`, topologically sorts the agent graph, and executes agents in order.

```python
from awp.runtime import WorkflowRunner

runner = WorkflowRunner("path/to/my-workflow")
result = runner.run("Analyze the latest quarterly report")
print(result)
```

**Supported features:**
- Sequential and parallel execution modes
- DAG-based topological ordering
- State sharing between agents
- Basic error handling (continue / skip / abort)
- Auto-inject fields from the manifest

**Not supported (use a full runtime):**
- Loops and interactive agents
- Fan-out / Fan-in
- Subworkflows
- Message bus communication
- Memory curation
- Observability export

#### LLMClient

A minimal OpenAI-compatible chat completion client.

```python
from awp.runtime.llm import LLMClient

client = LLMClient(
    api_key="sk-...",
    base_url="https://openrouter.ai/api/v1",
    model="anthropic/claude-sonnet-4",
)

# Text response
text = client.chat_text([
    {"role": "system", "content": "You are a helpful assistant."},
    {"role": "user", "content": "Hello!"},
])

# JSON response
data = client.chat_json([
    {"role": "system", "content": "Respond in JSON."},
    {"role": "user", "content": "List three colors."},
])
```

### Running via CLI

```bash
awp run path/to/my-workflow --task "Research quantum computing"
```

### Running via Python API

```python
from awp.runtime import WorkflowRunner

runner = WorkflowRunner("research-pipeline")
result = runner.run("Research quantum computing trends in 2026")
print(result["writer"]["article"])
```

## Environment Variables

The standalone runtime reads these environment variables:

| Variable | Description | Default |
|----------|-------------|---------|
| `LLM_API_KEY` | API key for the LLM provider. Falls back to `OPENROUTER_API_KEY`. | -- |
| `LLM_MODEL` | Model identifier (e.g., `"anthropic/claude-sonnet-4"`). | -- |
| `LLM_BASE_URL` | API base URL. | `https://openrouter.ai/api/v1` |

## Cloudflare Workers Runtime

AWP workflows can run on **Cloudflare Workers** using the Dynamic Workers adapter.
Each workflow deploys as a single Dispatch Worker that orchestrates the agent DAG.

### Architecture

- **Dispatch Worker** — Central orchestrator that reads the DAG, calls LLMs, validates outputs
- **KV Namespace** — Workflow state between agents
- **D1 (SQLite)** — Short-term memory and daily logs (when memory feature is enabled)
- **R2 Bucket** — Long-term memory / MEMORY.md (when memory feature is enabled)
- **Workers AI** — Optional LLM backend (alternative to external APIs)

### Installation & Deployment

```bash
# Install Wrangler CLI
npm install -g wrangler
wrangler login

# Generate workflow with Cloudflare adapter
# (tell the AWP skill: "use the Cloudflare adapter")

# Setup and deploy
cd my-workflow/
npm install
wrangler kv namespace create STATE
# → copy id into wrangler.toml
wrangler secret put LLM_API_KEY
wrangler deploy
```

### Running

```bash
# HTTP invocation
curl -X POST https://my-workflow.account.workers.dev \
  -H "Content-Type: application/json" \
  -d '{"task": "Research quantum computing trends"}'

# Local development
wrangler dev
curl http://localhost:8787 -d '{"task": "..."}'

# Health check
curl https://my-workflow.account.workers.dev/health
```

### LLM Configuration

The Cloudflare adapter supports two LLM backends:

```yaml
# External (OpenAI-compatible) — default
model:
  name: "anthropic/claude-sonnet-4-20250514"

# Cloudflare Workers AI
model:
  provider: workers-ai
  name: "@cf/meta/llama-3.1-70b-instruct"
```

### Memory Mapping

| AWP Tier | Cloudflare Service | Lifecycle |
|----------|-------------------|-----------|
| Working | JS variables | Request-scoped |
| Short-term | D1 (SQLite) | Persistent, queryable |
| Long-term | R2 (Object Storage) | Unlimited |

For the full adapter reference, see [skill/adapters/cloudflare-dynamic-workers.md](../skill/adapters/cloudflare-dynamic-workers.md).

---

## Building a Platform Adapter

To run AWP workflows on a different platform (e.g., LangGraph, CrewAI, a custom framework), you need to:

1. **Parse the YAML.** Read `workflow.awp.yaml` and all `agent.awp.yaml` files. The `awp-agents` package provides parsers you can reuse:

   ```python
   from awp.parser import parse_manifest, parse_agent

   manifest = parse_manifest("workflow.awp.yaml")
   agent_config = parse_agent("agents/researcher/agent.awp.yaml")
   ```

2. **Map to platform concepts.** Translate AWP graph nodes to your platform's agent system, AWP state sharing to your platform's state mechanism, and AWP tool definitions to your platform's tool interface.

3. **Implement `agent.py`.** Each agent's `agent.py` should extend your platform's base class while also conforming to the AWPAgent interface:

   ```python
   from awp.agent import AWPAgent
   from your_platform import PlatformAgent

   class Agent(AWPAgent, PlatformAgent):
       @property
       def name(self) -> str:
           return "researcher"

       def run(self, task: str, state: dict) -> dict:
           # Use platform-specific features
           result = self.platform_execute(task, state)
           return {self.name: result}
   ```

4. **Validate.** Use the AWP validator to check your workflow before execution:

   ```python
   from awp.validator import validate_workflow

   result = validate_workflow("path/to/workflow")
   if not result.passed:
       for error in result.errors:
           print(error)
   ```

5. **Write an adapter document.** Create a markdown file following the pattern in `skill/adapters/standalone.md` that describes how `agent.py` should be generated for your platform. This allows the AWP build skill to generate platform-specific code.

### Adapter Document Structure

Place your adapter in `skill/adapters/{platform}.md`:

```markdown
# AWP Platform Adapter: {Platform Name}

## When to Use
{When this adapter is appropriate.}

## agent.py Template
{The agent.py template with {{AGENT_ID}} placeholders.}

## How Execution Works
{How your platform executes agents.}

## Running a Workflow
{Python API and CLI examples.}

## Dependencies
{Installation instructions.}
```

## Blackboard Channel (Sibling Coordination)

Delegation loop runs ship with a minimal **blackboard** for sibling-worker
coordination. Every manager run owns an append-only JSONL file at
`<workflow_dir>/workspace/blackboard/<manager_run_id>.jsonl`. Workers
spawned by the same manager can post and read signals on it via two
builtin, run-scoped tools:

- **`board.post`** — `{topic: str, payload: dict}` → `{entry_id}`.
  Appends an entry for the current manager run.
- **`board.read`** — `{topic?: str, since?: str}` → `{entries: [...]}`.
  Returns entries for the current manager run, optionally filtered by
  topic and/or "strictly newer than" marker (entry id or timestamp).

The bind between a running DelegationLoopRunner and its `Blackboard` is
a `ContextVar` (`awp.runtime.blackboard.current_blackboard`) set inside
`DelegationLoopRunner.run()`. That means:

- Multiple delegation loops can run in parallel without cross-talk.
- **Submanagers get their own blackboard** (different `run_id`) — the
  parent loop is re-bound automatically when the child returns.
- Workers of other runs cannot read or write this run's board.

Before each manager iteration, the runner reads any NEW entries (via
`since=<last_seen_id>`) and injects them into the manager prompt as a
`## SIBLING SIGNALS` block. If there are no new entries the block is
omitted — the prompt stays lean.

The feature is controlled by `orchestration.delegation_loop.blackboard_enabled`
(defaults to `true`). When false, no blackboard is created, no signals
are injected, and the two tools are not exposed to workers. File-backed
writes are process-safe via `fcntl.flock` on POSIX.

## Hierarchical Context Digest

Delegation loops also ship with a per-level, content-addressed
**digest** that compresses each iteration into a compact, deterministic
summary. The feature targets deep delegation graphs (depth >=3) where a
full rolling history would blow past the manager prompt budget.

Every manager run owns a :class:`DigestStore` at
`<workflow_dir>/workspace/runs/<run_id>/digest/<sha>.json`. After each
iteration the runner calls `build_digest_from_iteration(...)` to build
a :class:`Digest` (goal, key_facts, open_questions, confidence_trend,
child_digest_hashes) and persists it — same content, same SHA.

Before each manager iteration the prompt gets two injected blocks:

- `## MY DIGEST` — this level's current digest, rendered via
  `Digest.to_markdown()`.
- `## CHILDREN DIGESTS` — up to `digest_max_depth` inlined child
  digests, each shown as `<sha12> iter=N facts=... questions=...:
  <goal preview>`. Deeper layers stay reachable via the
  `digest.fetch` tool.

When the digest is active the rolling-history detail window is capped
at 3 iterations so the prompt tokens are spent on the structured
digest, not duplicated key-findings text.

Submanager integration: when the parent spawns a child, its current
digest SHA rides along in the child's inherited state under the
reserved key `__parent_digest_sha`. When the child returns, its final
digest SHA is surfaced on the wrapper result and the parent folds it
into the next digest's `child_digest_hashes`, forming the hierarchy.

New builtin tool, run-scoped via the ContextVar
`awp.runtime.digest.current_digest_store`:

- **`digest.fetch`** — `{sha: str}` → `{digest: {...}}`. Returns the
  digest at this SHA from the current run's store. Cannot read
  digests from other runs.

Configuration on `orchestration.delegation_loop`:

- `digest_enabled: bool = true` — master switch.
- `digest_mode: str = "deterministic"` — only mode supported in v1;
  `"llm"` is reserved and raises `NotImplementedError` if selected.
- `digest_max_depth: int = 1` — children inlined in the prompt;
  workers can always go deeper with `digest.fetch`.

Generation is deterministic and cheap: no LLM call, sorted+deduped
lists, never fabricates fields. Missing worker outputs leave the
corresponding digest field empty.

## Auto-Curation (Long-Term Memory Writeback)

After the root manager's delegation loop terminates, the runtime
instantiates :class:`awp.runtime.curator.Curator` and calls its
`curate()` method. The curator walks the run's digest hierarchy,
the `ToolRegistry._dynamic_tools` map, and the runner's
`_failed_signatures` list, and deterministically writes reusable
knowledge into `<workflow_dir>/memory/`:

| Path | Source | Dedup rule |
|------|--------|------------|
| `memory/tools/<recipe>.md` | Dynamic tools registered during the run | `name + content_hash(spec)` — same hash is a no-op, different hash appends `## v{n}` |
| `memory/facts/YYYY-MM-DD.md` | `key_facts` appearing in `>=2` digests across the tree | Exact line match within the day file |
| `memory/antipatterns/<sha>.md` | Redundant signatures + worker errors + confidence `<0.3` | `sha256(signature)[:16]` |

The curator runs **only on root managers** (parent_digest_sha is
`None`), is wrapped in try/except (never fails a run), and is
idempotent: re-running on the same run writes nothing.

Configuration on `orchestration.delegation_loop`:

- `auto_curation_enabled: bool = true` — master switch for both
  writeback at run end AND the `## PRIOR RUN MEMORY` priming
  block injected by `_build_manager_task` on the first iteration
  of the root manager.

On the next run, `Curator.read_prior_memory(workflow_dir)` reads
those three directories back and produces a compact markdown
block capped at ~3000 chars which the runner injects into the
root manager's very first prompt. Submanagers inherit priors via
the parent digest sha, not via this block. See
[memory.md](memory.md#auto-curation-baustein-4) for the full
extraction rules.

The curator report (`{tools_added, tools_versioned, facts_added,
antipatterns_added, errors}`) is attached to the wrapped return
value at `delegation_loop.curation_report` for observability.

