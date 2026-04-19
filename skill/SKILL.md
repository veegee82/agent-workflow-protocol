---
name: awp-workflow-builder
description: >
  Generate complete Agent Workflow Protocol (AWP) compliant multi-agent
  workflows from natural language descriptions. Produces workflow.awp.yaml,
  agent configs, prompts, schemas, and optionally custom tools and skills.
  Tracks AWP spec v1.0 validation rules R1–R32 and runtime contracts of
  awp-agents >= 1.0.52 (completion-gate chain, blackboard, hierarchical
  context digest, auto-curation, archetype-based dynamic tools).
version: "1.0.52"
user-invocable: true
allowed-tools: Read Write Edit Bash Glob Grep
---

# AWP Workflow Builder

## AWP 7-Layer Model

AWP organizes a workflow into seven protocol layers. Each layer answers one question:

<svg viewBox="0 0 620 290" xmlns="http://www.w3.org/2000/svg" font-family="sans-serif" font-size="13">
  <rect x="20" y="5" width="580" height="34" rx="4" fill="#dce6f7" stroke="#4a6fa5" stroke-width="1.5"/>
  <text x="30" y="27" font-weight="bold" fill="#2a3f5f">Layer 6</text>
  <text x="120" y="27" fill="#2a3f5f">OBSERVABILITY</text>
  <text x="590" y="27" text-anchor="end" fill="#666">How do I monitor this workflow?</text>
  <rect x="20" y="43" width="580" height="34" rx="4" fill="#d5e8d4" stroke="#5b8c5a" stroke-width="1.5"/>
  <text x="30" y="65" font-weight="bold" fill="#2d5a2d">Layer 5</text>
  <text x="120" y="65" fill="#2d5a2d">ORCHESTRATION</text>
  <text x="590" y="65" text-anchor="end" fill="#666">In what order and under what conditions?</text>
  <rect x="20" y="81" width="580" height="34" rx="4" fill="#fef3cd" stroke="#d4a017" stroke-width="1.5"/>
  <text x="30" y="103" font-weight="bold" fill="#856404">Layer 4</text>
  <text x="120" y="103" fill="#856404">MEMORY &amp; STATE</text>
  <text x="590" y="103" text-anchor="end" fill="#666">What does the workflow remember?</text>
  <rect x="20" y="119" width="580" height="34" rx="4" fill="#e8d5f5" stroke="#7b4ea3" stroke-width="1.5"/>
  <text x="30" y="141" font-weight="bold" fill="#5a2d82">Layer 3</text>
  <text x="120" y="141" fill="#5a2d82">COMMUNICATION</text>
  <text x="590" y="141" text-anchor="end" fill="#666">How do agents talk to each other?</text>
  <rect x="20" y="157" width="580" height="34" rx="4" fill="#fde2e2" stroke="#c0392b" stroke-width="1.5"/>
  <text x="30" y="179" font-weight="bold" fill="#922b21">Layer 2</text>
  <text x="120" y="179" fill="#922b21">CAPABILITIES</text>
  <text x="590" y="179" text-anchor="end" fill="#666">What can an agent do? (tools, skills)</text>
  <rect x="20" y="195" width="580" height="34" rx="4" fill="#d5f5e3" stroke="#27ae60" stroke-width="1.5"/>
  <text x="30" y="217" font-weight="bold" fill="#1a6b3c">Layer 1</text>
  <text x="120" y="217" fill="#1a6b3c">AGENT IDENTITY</text>
  <text x="590" y="217" text-anchor="end" fill="#666">Who is this agent?</text>
  <rect x="20" y="233" width="580" height="34" rx="4" fill="#f0f0f0" stroke="#888" stroke-width="1.5"/>
  <text x="30" y="255" font-weight="bold" fill="#333">Layer 0</text>
  <text x="120" y="255" fill="#333">MANIFEST</text>
  <text x="590" y="255" text-anchor="end" fill="#666">What is this workflow?</text>
</svg>

You start at the bottom. Layer 0 (manifest) and Layer 1 (agent identity)
are always required. Everything above is opt-in.

## Autonomy Levels

Autonomy levels measure HOW AUTONOMOUS the workflow is, not WHAT FEATURES it has.
Communication, memory, and observability are cross-cutting features available at any level.

| Level | Name | Description |
|-------|------|-------------|
| A0 | Prescribed | Static DAG, predefined agents, fixed tools. Minimum viable workflow. |
| A1 | Adaptive | Conditional execution, loops, fan-out, multi-agent DAG. |
| A2 | Delegating | Manager spawns workers dynamically (delegation loop). Budget required. |
| A3 | Self-Tooling | Agents create tools and skills at runtime. Safety envelope required. |
| A4 | Self-Organizing | Recursive delegation, budget distribution. Observability required. |

**Cross-cutting features (any level):** Communication, Memory, Observability, Security.

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
| Archetypes & Recipes | runtime, no YAML | Six generic tool archetypes (compute / fetch / parse / transform / render / probe). The manager plans capabilities as `reuse_or_generate: "synthesize"` with `archetype_id` + `recipe_params`, the runtime synthesises a deterministic handler, and successful instantiations are auto-captured as content-addressed Recipes under `~/.awp/recipes/` (Quarantined → Probationary → Trusted) for replay-gated reuse on future runs. Replaces the old hand-rolled pattern library as the primary path for new tools — see R31 below. |

### Orchestration Engines

AWP provides two orchestration engines. The choice determines how agents coordinate:

**DAG Engine** (default, A0-A1):
Static graph of agents. Dependencies defined in YAML. Topological execution.
```yaml
orchestration:
  engine: dag
  graph:
    - id: planner
      agent: planner
    - id: researcher
      agent: researcher
      depends_on: [planner]
```

**Delegation Loop Engine** (A2-A4):
A manager agent dynamically spawns ephemeral workers. Workers receive generated instructions, skills, and tool configurations. The loop iterates until the manager declares completion or budget is exhausted.

```yaml
orchestration:
  engine: delegation_loop
  delegation_loop:
    manager: agents/manager
    models:
      manager: null    # --manager-model CLI flag
      worker: null     # --worker-model CLI flag
    budget:
      max_loops: 10
      max_total_workers: 20
      max_wall_time: 300
      max_depth: 2                       # Recursive submanager depth cap (default 2)
      max_concurrent_submanagers: 3      # Max submanagers running at once
      max_total_submanagers_per_run: 6   # Hard cap on submanagers per run
      max_workers_per_iteration: 6       # Per-iteration fan-out cap (default 6)
      max_rejected_completions: 2        # Completion-retry circuit breaker (default 2)
    worker_policy:
      enforced:
        sandbox: {type: subprocess, max_memory_mb: 512}
        forbidden_tools: [shell.execute, file.write_outside_workspace]
      manager_controlled:
        - instructions
        - skills
        - tools_allowed
        - output_contract
        - codemode.enabled
        - codemode.tool_creation
        - temperature              # Manager sets per-worker LLM temperature
  # NOTE: shell.execute is forbidden — workers MUST use code.execute instead.
  # For non-codemode terminal access, use terminal.execute (sudo-free shell).
  # The manager should include code.execute in tools_allowed for codemode workers.
    termination:
      enabled: true
      window: 3
      min_confidence_delta: 0.05
    validation:
      deterministic: {always: true}
      llm: {enabled: true, skip_when_confidence_above: 0.95}
    history:
      rolling_summary: true
      full_results_window: 3
    logging:
      format: dual
      persist_artifacts: true
    # Sibling-coordination blackboard (default: true). When enabled,
    # every manager run gets an append-only JSONL board and workers
    # receive the `board.post` / `board.read` run-scoped tools.
    blackboard_enabled: true
    # Hierarchical Context Digest (HCD). Per-level deterministic summary
    # of each manager iteration, injected into the next prompt as
    # ## MY DIGEST + ## CHILDREN DIGESTS so deep delegation graphs
    # (depth >=3) keep context without overflowing the prompt.
    digest_enabled: true
    digest_mode: deterministic   # "deterministic" only; "llm" reserved
    digest_max_depth: 1          # children inlined in the prompt
    # Auto-Curation (Baustein 4). When true, a deterministic curator
    # writes reusable knowledge (tool recipes, cross-confirmed facts,
    # failed-delegation antipatterns) into <workflow_dir>/memory/ at
    # run end, and the next run's root manager is primed with a
    # `## PRIOR RUN MEMORY` block on its first iteration.
    auto_curation_enabled: true
    # LLM Call Tracing. When enabled, every LLM API call (manager + workers)
    # is persisted as llm_trace/call_NNN.json with full messages, response,
    # token usage, and latency. Disabled by default to avoid I/O overhead.
    trace_enabled: false
    # Optional selective-forget blacklist for submanager state inheritance.
    # Keys listed here are stripped before being passed to child runs.
    # forbidden_inheritance_keys: [secret_token, raw_dump]
```

Key concepts:
- **Delegation Envelope**: Manager generates instructions + skills + tools config + temperature for each worker
- **Budget System**: Hard limits on loops, workers, tokens, wall time. Required at A2+. Includes `max_workers_per_iteration` (default **6**) — a per-DELEGATE fan-out cap. Over-cap dispatches are trimmed pre-spawn and the overflow is surfaced to the manager via `state["_deferred_workers"]` so it must merge subtasks or dispatch in a later iteration.
- **Terminal Status Contract**: Every run ends with exactly one of `{complete, partial, failed, aborted}`. Cap-forced exits (`defect_category_cap`, `plan_loop`, `forced_convergence`, `max_total_tokens`, `max_total_workers`, `max_wall_time`, `max_loops`) are always `partial` — never `complete`. Hard errors are `failed`. Signal-driven or abrupt process exits are `aborted`. The `run.complete` event + `run_completion.json` are emitted on every exit path via a `try/except/finally` + `SIGTERM`/`SIGINT` handler finalizer.
- **Safety Envelope**: Immutable security constraints the manager cannot override. Required at A3+.
- **Two-Tier Validation**: Deterministic (schema, confidence) + LLM semantic (does result address task?)
- **Stall Detection**: Auto-stop when confidence stops improving. Also includes
  worker-level tool-call repeat-loop detection: if a worker emits 3 identical
  tool calls in a row, the runner forces a final round with `tool_choice="none"`
  so the worker completes gracefully instead of looping forever on a broken tool.
- **Dual Logging**: JSON (machines) + Markdown (humans) in workspace/runs/
- **Fan-Out**: Multiple workers per iteration, executed in parallel
- **Recursive Delegation (A4)**: Workers can be auto-promoted to submanagers
  that own their own delegation loop. Promotion is decided by a deterministic
  **complexity scorer** (subtask word length, presence of keywords like
  "research"/"validate", deliverable count, declared priority) — only subtasks
  scoring ≥3 are promoted, with bonuses for collective fan-outs and a 50%
  promotion cap so the parent budget cannot be blown.
- **Budget Reservation Model (A4)**: When a submanager is spawned, capacity is
  **pre-charged** against the parent budget via `allocate_child(fraction)`,
  so concurrent siblings see a shrinking pool and the no-over-commit invariant
  always holds. `reclaim_child()` refunds unused capacity when the sub-run
  finishes. This is what gives A4 its termination guarantees even under
  parallel recursive delegation.
- **Submanager state inheritance (A4)**: Submanagers inherit the parent's
  **full state dict by default** (children are no longer "born blind").
  Precedence when resolving the inherited slice:
  1. Explicit per-envelope `inherited_state_keys` whitelist wins (legacy).
  2. Otherwise, inherit all keys except those in `forbidden_inheritance_keys`
     (per-envelope or at `delegation_loop.forbidden_inheritance_keys` in the
     workflow config — add `forbidden_inheritance_keys: [secret_token, ...]`
     under `delegation_loop` to strip sensitive/oversized keys globally).
  3. If neither is set, the full parent state is passed through.
- **Sibling coordination via blackboard (A2-A4)**: Every manager run owns
  a run-scoped append-only JSONL board at
  `<workspace>/blackboard/<manager_run_id>.jsonl`. Workers get two
  builtin tools — **`board.post`** (`topic`, `payload`) and
  **`board.read`** (`topic?`, `since?`) — to broadcast partial findings,
  dead ends, and de-duplication hints to their siblings. Before every
  manager iteration, new entries are injected into the manager prompt as
  a `## SIBLING SIGNALS` block (silent when empty). Submanagers get
  their OWN blackboard (different run id) and never share signals with
  the parent. Controlled by `delegation_loop.blackboard_enabled`
  (default `true`). Workers do NOT need to list `board.post` / `board.read`
  in `tools_allowed` — the runtime injects them automatically when the
  feature is on.
- **Hierarchical Context Digest (A2-A4)**: Every manager run owns a
  per-level **digest** that compresses each iteration into a compact,
  deterministic record (goal, key_facts from confidence>=0.8 workers,
  open_questions from confidence<0.7 workers, confidence_trend, child
  digest SHAs). Digests live content-addressed at
  `<workspace>/runs/<run_id>/digest/<sha>.json`. Before every manager
  iteration the runner injects a `## MY DIGEST` block (this level's
  current digest) and a `## CHILDREN DIGESTS` block (up to
  `digest_max_depth` inlined submanager digests); deeper layers stay
  reachable via the run-scoped **`digest.fetch`** tool. When the
  digest is active the rolling history detail window auto-caps at 3
  iterations so the prompt spend flows into the structured digest.
  Submanagers receive the parent's current digest sha via the
  reserved `__parent_digest_sha` inherited-state key, and their final
  digest sha flows back to the parent and is folded into its next
  digest's `child_digest_hashes`. Controlled by
  `delegation_loop.digest_enabled` (default `true`), `digest_mode`
  (`"deterministic"` only; `"llm"` raises NotImplementedError), and
  `digest_max_depth` (default `1`). Workers do NOT need to list
  `digest.fetch` in `tools_allowed` — the runtime injects it
  automatically when the feature is on.
- **Auto-Curation & Prior-Run Memory (A2-A4)**: When
  `delegation_loop.auto_curation_enabled` is true (default), a
  deterministic Curator runs at the end of every root-manager run
  and writes reusable knowledge into `<workflow_dir>/memory/`:
  * `memory/tools/<recipe>.md` — recipes for every dynamic tool
    created this run, deduped by `name + content_hash(spec)`;
    same name with a new hash appends a `## v{n}` section.
  * `memory/facts/YYYY-MM-DD.md` — cross-confirmed key facts that
    appeared in `>=2` digests across the run's digest hierarchy.
  * `memory/antipatterns/<sha>.md` — redundant delegation
    signatures, worker errors, and worker confidence `<0.3`.
  On the next run, `Curator.read_prior_memory(workflow_dir)` reads
  these three directories and the runner injects a compact
  `## PRIOR RUN MEMORY` block (capped ~3000 chars) into the root
  manager's very first prompt. Submanagers do NOT receive the
  block directly — they inherit priors via the parent digest sha
  to avoid amplifying prompt cost with depth. Set
  `auto_curation_enabled: false` to disable both writeback and
  priming.
- **Content-aware redundancy guard (A2-A4)**: The delegation signature used
  to veto duplicate dispatches now hashes worker instructions **together
  with a canonical JSON of the context the envelope references** (`context`,
  `input_context`, or the set of `inherited_state_keys`). Identical
  instructions run against different input contexts are no longer falsely
  flagged as redundant. Envelopes that carry no context hash identically
  to the legacy signature, so existing workflows are unaffected.
- **Submanager output merging (A4)**: Each submanager writes into its own
  `output/<sub_run_id>/` sandbox under the parent workflow dir. On completion
  the parent runner merges those files back into the parent `_output_dir`;
  name collisions are renamed `<submanager_name>__<filename>`. The merged
  filenames are attached to the child result as `_merged_files`.
- **Completion gates**: before accepting a `COMPLETE` decision the runner
  enforces (1) a **placeholder scanner** over `final_result` and text
  deliverables (`TODO`, `XX%`, template stubs like `your`/`field_name`),
  (2) a **file-validator gate** rejecting 1x1 PNGs and files `< 512 B`,
  (3) a **deliverable-presence gate** that refuses completion when the task
  text implies an artifact (image / pdf / csv / ...) and `_output_dir` is
  empty, and (4) the critique-score gate (`min_score_to_complete`, default
  `0.6`). Any gate firing forces another iteration with a targeted repair
  hint in state. When a task-implied deliverable already exists on disk,
  the critic's narrative pessimism is overruled (ground-truth bypass).
- **Convergence detector**: the loop force-completes with
  `reason: forced_convergence` when confidence delta across the last two
  iterations is `< 0.05` or three consecutive iterations produce identical
  `key_findings`. A sorted instruction-hash signature detects redundant
  re-delegation and pushes the manager into DIAGNOSE instead of re-issuing
  the same subtasks.

When generating a delegation loop workflow:
- The manager agent gets a full agent.awp.yaml with SYSTEM_PROMPT.md
- Workers are ephemeral — no YAML files, configured by the manager at runtime
- The manager's system prompt must instruct it to use the DELEGATE/COMPLETE/FAIL decision format

### Dynamic Tool Creation

Agents with Code Mode can create new MCP tools at runtime via `sdk.tools.create()`.

**CRITICAL**: When generating a delegation loop workflow that uses Code Mode or dynamic tools, you MUST:
1. Set `dynamic_tools.enabled: true` in workflow.awp.yaml (otherwise tool creation silently fails)
2. Set `dynamic_tools.persist: true` to save generated tools as JSON files for debugging
3. Include `code.execute` (NOT `shell.execute`) in the workers' `tools_allowed` — `shell.execute` is in `forbidden_tools` by default and will be silently removed
4. Set `tool_creation: true` in the codemode envelope (not just `enabled: true`)

Configuration in workflow.awp.yaml:
```yaml
dynamic_tools:
  enabled: true           # MUST be true for tool creation to work
  persist: true            # Save tools as JSON in workspace/dynamic_tools/
  max_total: 20
  allowed_namespaces:
    - scoring                                  # compute only (default)
    - analysis                                 # compute only (default)
    - name: api_client                         # grant network access
      capabilities: [compute, network]
      network_allowlist: [api.example.com]     # optional host restriction
    - name: data_proc                          # grant filesystem access
      capabilities: [compute, filesystem]
  code_review: true        # Log all generated code for debugging
```

**Namespace Capabilities** (NC1-NC3): Each namespace can be granted additional capabilities beyond pure computation. Plain string entries default to `compute` only. Capability objects can grant:
- `compute`: Pure Python (always implicit)
- `network`: Unlocks `requests`, `httpx`, `urllib`, `http`, `socket`
- `filesystem`: Unlocks `pathlib`, `glob`, `shutil`, `tempfile`

**Always denied** (cannot be unlocked): `os`, `subprocess`, `sys`, `ctypes`, `importlib`, `signal`, `multiprocessing`.

In agent.awp.yaml:
```yaml
capabilities:
  codemode:
    enabled: true
    tool_creation: true
    tool_creation_namespace: scoring
    max_tools: 10
```

In the delegation loop, the manager can enable tool creation for workers:
```json
{
  "codemode": {
    "enabled": true,
    "tool_creation": true,
    "tool_creation_namespace": "scoring"
  }
}
```

**Tools with API Key Access (required_secrets):**

Dynamic tools can declare `required_secrets` to access API keys from the workflow's secrets store.
Available secret key names (not values) are shown to the worker automatically.
The secrets are injected as a `_secrets` dict variable in the sandbox:

```json
{
  "name": "dynamic.api_fetch",
  "description": "Fetch data from external API",
  "required_secrets": ["API_KEY"],
  "parameters": {"type": "object", "properties": {"url": {"type": "string"}}},
  "code": "import urllib.request, json\ndef handler(*, url):\n    api_key = _secrets.get('API_KEY', '')\n    req = urllib.request.Request(url, headers={'Authorization': f'Bearer {api_key}'})\n    resp = urllib.request.urlopen(req, timeout=10)\n    return {'ok': True, 'status': 200, 'data': json.loads(resp.read()), 'error': None}"
}
```

**File Output from Dynamic Tools and code.execute:**

Generated tool code and `code.execute` calls have access to two pre-defined path variables:
- `_workspace_dir` — path to workspace/ (intermediate files)
- `_output_dir` — path to output/ (final deliverables: charts, CSVs, reports)

Use `open()` (builtin) and string concatenation for paths. Do NOT import `os` or `pathlib`.

```python
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

def handler(*, data, filename):
    plt.figure()
    plt.plot(data)
    plt.savefig(_output_dir + "/" + filename, dpi=150)
    plt.close()
    return {"ok": True, "status": 200, "data": {"file": _output_dir + "/" + filename}, "error": None}
```

Tools are persisted in workspace/runs/{run_id}/artifacts/tools/ and workspace/dynamic_tools/.
Each persisted tool JSON contains: name, description, parameters, code, required_secrets, provenance (creator, timestamp).

### Code Execution in Workers

Workers with `codemode.enabled: true` should use the `code.execute` tool for running Python code.
**Do NOT use `shell.execute`** — it is in `forbidden_tools` by default.

The manager should include `code.execute` in the delegation envelope `tools_allowed`:
```json
{
  "tools_allowed": ["code.execute", "file.read", "file.write"],
  "codemode": {"enabled": true}
}
```

In `code.execute`, the variables `_workspace_dir` and `_output_dir` are automatically available.

The runtime also auto-injects a small standard preamble into every `code.execute` snippet so common modules do not need to be imported in every call:

- Pre-imported modules: `json`, `pathlib`, `re`, `math`, `datetime`, plus `os`/`sys`/`builtins` (aliased as `_os`, `_sys`, `_builtins`)
- Pre-injected helpers: `_workspace_dir`, `_output_dir`, `_secrets`, `_ensure_dir()`, `_output_file()`, `_input_file()`, `_list_files()`, `_verify_png()`
- Text-mode `open(path, "w")` is auto-upgraded to binary mode if the caller writes `bytes` (prevents `TypeError: write() argument must be str, not bytes` from LLM-written snippets).

Note: within a single worker, `code.execute` calls now share a **warm, persistent Python subprocess** by default — variables, imports, and helper functions defined in one call ARE still live in the next. Heavy imports (numpy, pandas, matplotlib) are paid once per worker, not once per call. Passing state via files under `_workspace_dir` is still correct (and required for state shared BETWEEN workers), but generated workflows no longer need to reload DataFrames or re-import modules inside every snippet. Each worker has its own namespace; a crash inside the warm subprocess triggers an automatic restart with a silent history replay so the namespace feels preserved.

**Repair workers continue the prior worker's context.** When the runtime dispatches a worker whose id ends in `_repair`, `_retry`, `_vN`, `_strict`, `_final`, `_runN`, or `_subtask_N`, it re-enters the original worker's warm namespace and prepends a `REPAIR MODE` block to the worker's system prompt. Generated workflows MUST NOT assume a repair worker starts from a blank state; reload or re-import only when strictly necessary. The manager can force a clean slate per-dispatch via envelope field `fresh_worker: true` — do not add this flag by default, it defeats the α-fix and wastes tokens.

**Auto-emergent tools.** When `N=3` distinct workers execute the same shape of `code.execute` snippet (same AST skeleton, differing only in literals / identifier names), the runtime auto-synthesizes a generalized tool via `DynamicToolFactory`, persists it at `shared/dynamic_tools/dynamic.induced_<hash6>.json`, and exposes it through `tool.list` for later workers. `N=3` is a hardcoded constant — no config knob. Generated workflows should NOT fight induction: do not suppress `code.execute` recording, do not normalize worker ids to reduce diversity, and do not assume `tool.list` returns only LLM-authored tools. Induced tools satisfy rules DT1-DT8 exactly like explicit `tool.create` output.

### Dynamic Skill Generation

In the delegation loop, the manager generates domain-specific skills (Markdown) for each worker.
Each dynamically generated skill MUST follow the same structure as project skills:

```json
{
  "skills": [
    "# Market Analysis\n\n## Purpose\nEvaluate market opportunity using quantitative frameworks.\n\n## Concepts\n- **TAM**: Total addressable market — the full revenue opportunity.\n- **SAM**: Serviceable addressable market — the segment you can reach.\n- **SOM**: Serviceable obtainable market — the realistic short-term capture.\n\n## Rules\n1. Always calculate all three tiers (TAM → SAM → SOM).\n2. State the source and year for every market-size figure.\n3. Express SOM as a percentage of SAM with justification.\n\n## Procedure\n1. Define the market boundaries.\n2. Calculate TAM from industry reports.\n3. Narrow to SAM based on geographic and segment filters.\n4. Estimate SOM based on competitive positioning.\n\n## Examples\n### Example 1: SaaS CRM\n**Input:** Global CRM market, mid-market segment, NA region\n**Output:** TAM $65B, SAM $12B, SOM $180M (1.5% — new entrant)\n"
  ]
}
```

**Required sections in every dynamic skill:** Purpose, Concepts, Rules.
**Optional sections:** Procedure (for multi-step tasks), Examples (when correct application is non-obvious).

Skills are persisted in workspace/runs/{run_id}/artifacts/skills/.


## STRICT RULES

These rules define validation requirements for AWP workflows. Rules marked **(recommended for Python)** apply to the Python reference implementation but may be adapted for other platforms.

- **R1:** `workflow.name` MUST match the workflow directory name.
- **R2:** All agent IDs MUST be `snake_case` (lowercase letters, digits, underscores).
- **R3 (recommended for Python):** Every `agent.py` SHOULD define a class named `Agent` that extends `StandaloneAgent` (for standalone runtime) or `AWPAgent` (for other platforms).
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
- **R14:** Tool names in `tools.allowed` MUST reference registered MCP tools. When tool implementation mode is enabled, built-in tools MUST have generated implementations in `mcp/`. When disabled, built-in tools are assumed to be provided by the target runtime.
- **R15:** If `tools.execute` is false, `tools.allowed` MUST be empty or omitted.
- **R16:** `execution.mode` MUST be one of: `sequential`, `parallel`, `conditional`.
- **R17:** All output schemas MUST include a `confidence` field (number, 0.0-1.0).
- **R18:** All `output_schema.json` files MUST be valid JSON Schema draft-07 with `"type": "object"` at the root.
- **R31 (delegation loop, runtime-enforced):** Manager PLAN decisions MUST include a non-empty `tool_manifest` per subtask. Each entry declares a capability and one of three modes: `reuse` (set `pattern_id` from the seeded pattern table), `synthesize` (set `archetype_id` ∈ {compute, fetch, parse, transform, render, probe} + `recipe_params` matching the archetype's required params — PREFERRED for new tools), or `generate` (last resort, requires an `assumptions` list). Workers instantiating archetype-based tools MUST forward `archetype_id` + `recipe_params` via `dynamic.create_tool` meta so the runtime can build the deterministic skeleton and auto-capture the recipe.


## Workflow Generation Phases

### Phase 0: Intelligent Task Analysis

**CRITICAL:** Before asking any questions, analyze the user's task description and silently
determine the optimal architecture. This analysis drives which questions you ask and which
defaults you recommend. Do NOT present this analysis to the user — use it to make smart
recommendations in Phase 1.

#### Step 0a: Pattern Detection

Read the task description and classify it into the best-fit design pattern:

| Signal in task description | Recommended Pattern | Autonomy |
|---------------------------|-------------------|----------|
| "pipeline", "step by step", "then", sequential process | Pipeline | A0-A1 |
| "analyze multiple", "compare", "parallel", batch items | Fan-Out / Fan-In | A1 |
| "if ... then", "depending on", "triage", "route" | Conditional Branching | A1 |
| "research", "investigate", "deep dive", open-ended | Manager-Worker | A2 |
| "score", "evaluate", "rate", configurable criteria | Tool Builder | A3 |
| "complex", "multi-faceted", "comprehensive", many dimensions | Self-Organizing Team | A4 |

#### Step 0b: Autonomy Level Detection

Apply the **minimum autonomy principle** — start at A0 and only increase if the task demands it:

```
Is the number of steps known upfront?
  YES → Are there conditional branches or parallel paths?
    NO  → A0 Prescribed (simple pipeline)
    YES → A1 Adaptive (DAG with conditions)
  NO  → Does the task need runtime tool/skill creation?
    NO  → A2 Delegating (delegation loop)
    YES → Is the task multi-dimensional with sub-teams?
      NO  → A3 Self-Tooling (tool creation)
      YES → A4 Self-Organizing (recursive delegation)
```

#### Step 0c: Engine Selection

| Autonomy | Engine | Rationale |
|----------|--------|-----------|
| A0-A1 | `dag` | Known steps, predictable flow |
| A2-A4 | `delegation_loop` | Steps emerge at runtime |
| Mixed | DAG with embedded delegation_loop node | Predictable outer, adaptive inner |

#### Step 0d: Capability Planning

Based on the task, pre-plan:

1. **Agents** — How many? What roles? (Fewer is better — merge roles that don't justify separation)
2. **Tools** — Which MCP tools? (Only what's needed — don't add tools "just in case")
3. **Skills** — Does the task need domain knowledge? (Generate skills only for specialized domains)
4. **Memory** — Is cross-session persistence needed? (Most tasks don't need it)
5. **Code Mode** — Does any agent need >5 tool calls? (If yes, Code Mode saves tokens)
6. **Budget** — For A2+: estimate loops, workers, wall time from task complexity

Carry this analysis into Phase 1 — it determines your recommendations.

### Phase 1: Requirements Gathering (Interactive Questionnaire)

**IMPORTANT:** Before generating anything, you MUST present the user with a structured
questionnaire. Do NOT skip this phase. Even if the user gave a detailed description,
there are always decisions that need clarification. Present ALL questions at once in a
single message so the user can answer them together.

For every question: provide concrete suggestions based on what the user already told you,
mark one as the recommended default (with `← recommended`), and always
include an "Other" option so the user can specify something not listed.

If the user already answered a question clearly in their initial request, pre-fill the
answer and mark it with `✓ (from your description)` — but still show it so the user
can correct it.

---

**Present the following questionnaire:**

#### 1. Workflow Basics

**1.1 Name:** What should the workflow be called?
> Suggestions: `{suggest 2-3 snake_case names based on user's description}`
> Other: ___

**1.2 Description:** What should the workflow do in one sentence?
> Suggestion: `{1-sentence summary based on user's description}`
> Other: ___

**1.3 Prompt Language:** In which language should the system prompts and outputs be?
> a) English ← recommended
> b) Other: ___

---

#### 2. Agents & Roles

**2.1 Which agents should the workflow have?** Each agent has a clearly defined role.
> Suggestions (based on your description):
> {list each suggested agent with id, role name, and 1-line description}
>
> Should agents be added, removed, or renamed?
> Other: ___

**2.2 Execution Order:** How should the agents be executed?
> a) Sequential (one after another in fixed order) ← recommended
> b) Parallel (independent agents simultaneously)
> c) Conditional (agents are skipped depending on results)
> d) Other: ___

**2.3 Data Flow:** Which data does each agent pass to the next?
> Suggestion:
> {show suggested data flow: agent_a → [fields] → agent_b → [fields] → agent_c}
>
> Changes? Other: ___

---

#### 3. LLM Configuration

> **Note:** LLM models are **not** specified in the workflow. They are
> configured at startup via the **Run-Wizard** (`awp run`) or the environment variable
> `LLM_MODEL`. This allows the user to switch models at any time
> without modifying the workflow.

**3.1 Temperature:** How creative should the agents respond?
> a) Low (0.1) — factual, precise ← recommended for analysis/research
> b) Medium (0.3) — balanced
> c) High (0.7) — creative, variable
> d) Different per agent (please specify)
> e) Other: ___

---

#### 4. Tools, Code Mode & Capabilities

**4.1 Which tools do the agents need?**
> Suggestions per agent:
> {for each agent, list suggested tools with brief explanation, e.g.:}
> - `{agent_id}`: `web.search` (web search), `memory.write` (save results)
> - `{agent_id}`: no tools (pure LLM agent)
>
> Changes? Other: ___

> **Note:** Advanced tool-calling options (`tool_choice`, `parallel_calls`)
> can be configured per agent in `agent.awp.yaml` under `capabilities.tools`.
> Defaults are sensible for most workflows — only adjust when needed.

**4.2 Generate tool implementations?** Should working implementations
be generated for the tools (e.g., `web.search` with DuckDuckGo, `memory.*` with
file storage)? Without this, tools are only placeholders that an AWP runtime must provide.
> a) Yes — generate all used tools as MCP implementations ← recommended for Standalone
> b) No — only tool declarations, runtime provides them ← recommended for AWP Runtime
> c) Only implement specific tools (please specify)
> d) Other: ___

**4.3 Code Mode (Alternative Tool Execution)?** Instead of calling tools individually,
the agent writes code against a typed SDK. Reduces token consumption and
LLM roundtrips when using many tools.
> a) No — classic tool calls ← recommended for simple workflows
> b) Yes — agent writes TypeScript against SDK ← recommended for >5 tools
> c) Yes — agent writes Python against SDK
> d) Other: ___

---

#### 4b. API Keys & Secrets

**4b.1 Do the tools need API keys or credentials?** Secrets are provided via
`secrets.yaml` (gitignored) and securely injected into tools — the LLM
never sees them.
> Suggestions based on the selected tools:
> {for each tool that typically needs API keys, e.g.:}
> - `web.search`: Optional — DuckDuckGo (free, no key) or premium API (Google, Bing, SearXNG)
> - `http.request`: Depends on target API — Bearer Token, API Key, etc.
> - Custom tools: please list keys
>
> a) No API keys needed ← recommended for getting started
> b) Yes — the following keys are needed: ___
> c) Other: ___

---

#### 5. Output Format & Schemas

**5.1 Output format of the agents:**
> a) JSON (structured, machine-readable) ← recommended
> b) Markdown (free text, human-readable)
> c) Mixed (some JSON, some Markdown — please specify)
> d) Other: ___

**5.2 Which fields should each agent output?**
> Suggestions:
> {for each agent, list suggested output fields with types}
> (Note: `confidence` (0.0-1.0) is automatically added — AWP required field.)
>
> Changes? Other: ___

---

#### 6. Memory & Persistence

**6.1 Should the workflow have long-term memory?** (Store results across sessions)
> a) No — each run is independent ← recommended for simple workflows
> b) Yes — MEMORY.md for cross-session insights
> c) Yes — with daily logs and MEMORY.md ← recommended for recurring tasks
> d) Other: ___

---

#### 7. Skills & Domain Knowledge

**7.1 Does the workflow need specific domain knowledge?** (Injected as SKILL.md into prompts)
> a) No
> b) Yes — please describe topic/domain: ___
> c) Suggestion: `{suggest a skill based on user's domain, e.g.: "industry-regulations"}`
> d) Other: ___

---

#### 8. Output Directory & Project Structure

**8.1 Where should the workflow be saved?**
> a) `{suggest path based on context, e.g.: ~/projects/{workflow_name}/}`
> b) Current directory
> c) Other: ___

---

#### 9. Target Platform

**9.1 Where should the workflow run?**
> a) **Standalone (Python)** — local execution with `awp-agents` ← recommended for getting started
> b) **Cloudflare Workers** — serverless Edge deployment (TypeScript)
> c) Other: ___

---

#### 10. Autonomy Level

**10.1 Which AWP Autonomy Level?**
> a) **A0 Prescribed** — static DAG, fixed agents and tools ← recommended for getting started
> b) **A1 Adaptive** — conditions, loops, fan-out ← recommended for most workflows
> c) **A2 Delegating** — manager spawns workers dynamically (budget required)
> d) **A3 Self-Tooling** — agents create tools at runtime (safety envelope required)
> e) **A4 Self-Organizing** — recursive delegation, budget distribution
> f) Other: ___
>
> **Note:** Communication, Memory, Observability, and Security are features that can be used at any level.

---

#### 11. Other

**11.1 Are there any additional requirements, constraints, or requests?**
> e.g., timeouts, error handling, security requirements, special data sources,
> target audience for output, ...
> ___

---

#### 11b. Orchestration Engine (if A2+ selected)

```
Which Orchestration Engine?

a) DAG — Static graph, fixed agents                          ← for A0-A1
b) Delegation Loop — Manager spawns workers dynamically      ← recommended for A2+
c) Hybrid — DAG with embedded Delegation Loop

If Delegation Loop:
- Budget: Max Loops? [10]  Max Workers? [20]  Max Wall Time? [300s]
- Context Budget: Total chars? [64000]  Min per entry? [4000]  Preview chars? [2000]
  (Auto-detect divides total budget equally among workers. Large results spill to
  workspace/context/ files with inline preview. Tune up for data-heavy workflows.)
- Safety Envelope active? [Yes, required from A3]
- LLM Validation? [Yes / No]
- Stall Detection? [Yes, recommended]
```

---

**After receiving answers:** Analyze the responses, resolve any conflicts, and proceed
to Phase 2. If answers are ambiguous or contradictory, ask targeted follow-up questions
(but not another full questionnaire). If the user says "defaults" or "passt so", use
all recommended defaults.

### Phase 2: Workflow-Plan (From Abstract to Concrete)

**IMPORTANT:** Before generating any files, you MUST create a structured workflow plan
and present it to the user for confirmation. This plan bridges the gap between the
abstract idea and the concrete implementation. It ensures that the user understands
exactly what will be built before a single file is created.

The plan follows a **top-down refinement** -- starting with the high-level goal and
progressively adding detail until every file, field, and dependency is specified.

Present the plan as a single, structured document:

---

#### Step 1: Goal Statement (Abstract)

Summarize the workflow's purpose in 2-3 sentences. What problem does it solve?
What is the expected input and output? This is the "elevator pitch" for the workflow.

> **Goal:** {what the workflow does, in plain language}
> **Input:** {what the user provides to start the workflow}
> **Output:** {what the user gets at the end}

#### Step 2: Agent Roles & Responsibilities (Conceptual)

For each agent, describe its role in non-technical terms. Focus on **what** it does,
not **how**. Think of this as a team of people -- what is each person's job?

| Agent | Role | Receives from | Delivers to |
|-------|------|--------------|-------------|
| `{id}` | {role in plain language} | {upstream agent or "user input"} | {downstream agent or "final output"} |

#### Step 3: Data Flow & Contracts (Architectural)

Now make the data flow concrete. Define what data moves between agents:

```
User Input
  │
  ▼
[agent_a] ──── produces: {field_1, field_2, confidence}
  │                shares: {field_1, field_2}
  ▼
[agent_b] ──── receives: {field_1, field_2}
  │                produces: {field_3, field_4, confidence}
  │                shares: {field_3}
  ▼
[agent_c] ──── receives: {field_3}
                   produces: {final_output, confidence}
```

For each shared field, specify the type and a one-line description.

#### Step 4: Tool & Capability Mapping (Technical)

Map each agent to its concrete capabilities:

| Agent | Tools | Memory | Skills | Reasoning |
|-------|-------|--------|--------|-----------|
| `{id}` | `{tool.fqn}`, ... | {yes/no, tier} | {skill name or none} | {enabled/disabled} |

#### Step 5: File Manifest (Implementation)

List every file that will be generated, grouped by agent:

```
{workflow_name}/
  workflow.awp.yaml
  secrets.yaml.example          (if secrets needed)
  mcp/
    {tool_file}.py              ← {purpose}
  skills/
    {skill_name}/SKILL.md       ← {purpose}
  agents/
    {agent_id}/
      agent.awp.yaml
      agent.py
      workflow/
        instructions/SYSTEM_PROMPT.md
        prompt/00_INTRO.md
        output_schema/output_schema.json
        output_schema_desc/output_schema_desc.json
    ...
```

State the total file count and the target autonomy level.

#### Step 6: Validation Preview

List which of the 32 rules (R1-R32) apply and confirm they will be satisfied:

> **Autonomy Target:** A{N} {Level Name}
> **Applicable Rules:** R1-R{max} (all satisfied by this plan, up to R30 if evaluation enabled)
> **Special Considerations:** {any edge cases, e.g., conditional execution, cyclic risk}

#### Step 6b: Delegation Loop Plan (if engine is delegation_loop)

If the orchestration engine is delegation_loop, the plan must include:
- Manager agent role and system prompt strategy
- Expected iteration flow (Phase 1: tool creation, Phase 2: analysis, Phase 3: synthesis)
- Budget allocation
- Worker types the manager will spawn (with example skills)
- Termination strategy

---

#### Step 7: Plan Validation Menu

After presenting the plan (Steps 1-6), you MUST present a **dynamic validation menu**
as a set of multiple-choice questions. Each question targets one key design decision
from the plan. For every question: pre-select the answer that matches your plan
(marked with `→`), provide 2-4 concrete alternatives, and always include a free-text
option. The user validates by confirming or correcting each point.

**IMPORTANT:** The questions must be **specific** to the generated plan -- not generic.
Use actual agent names, field names, tool names, and values from the plan. The menu
is a focused checklist, not a second questionnaire.

---

**Plan Validation -- please check the following items:**

**V1. Agent Count and Roles**
> → a) {N} Agents: `{agent_1}` ({role_1}), `{agent_2}` ({role_2}), ... ← from the plan
> b) Add agent: e.g., `{suggested_extra_agent}` ({suggested_role})
> c) Remove agent: which one? ___
> d) Rename agent: which one? ___
> e) Other: ___

**V2. Execution Order**
> → a) {mode from the plan}: `{agent_1}` → `{agent_2}` → `{agent_3}` ← from the plan
> b) {alternative_mode}: {concrete alternative, e.g., agent_1 + agent_2 parallel, then agent_3}
> c) Conditional: {suggest a condition, e.g., "agent_2 only if agent_1.confidence > 0.7"}
> d) Other: ___

**V3. Data Flow Between Agents**
> → a) As planned: `{agent_1}` shares `{field_1}, {field_2}` → `{agent_2}` shares `{field_3}` → `{agent_3}` ← from the plan
> b) Add field: which one, for which agent? ___
> c) Remove field: which one? ___
> d) Other: ___

**V4. Tools Per Agent**
> One line for each agent:
> → a) `{agent_1}`: `{tool_1}`, `{tool_2}` ← from the plan
> → b) `{agent_2}`: no tools ← from the plan
> → c) `{agent_3}`: `{tool_3}` ← from the plan
> Changes? Add/remove tools? ___

**V5. Output Fields Per Agent**
> Planned output fields for each agent:
> → a) `{agent_1}`: `{field_1}` (string), `{field_2}` (array), `confidence` (number) ← from the plan
> → b) `{agent_2}`: `{field_3}` (object), `confidence` (number) ← from the plan
> Change/add/remove fields? ___

**V6. Autonomy Level**
> → a) A{N} {Level Name} ← from the plan
> b) Lower: A{N-1} {Name} (removes: {what is dropped})
> c) Higher: A{N+1} {Name} (adds: {what is gained})
> d) Other: ___

**V7. Memory & Persistence**
> → a) {planned memory configuration, e.g., "No memory" or "MEMORY.md + daily logs"} ← from the plan
> b) {alternative, e.g., "Add memory: MEMORY.md for cross-session insights"}
> c) {alternative, e.g., "Daily logs only, no long-term memory"}
> d) Other: ___

**V8. Code Mode**
> → a) {planned Code Mode, e.g., "No — classic tool calls"} ← from the plan
> b) {alternative, e.g., "Yes — TypeScript Code Mode with SDK"}
> c) {alternative, e.g., "Yes — Python Code Mode with SDK"}
> d) Other: ___

**V9. Target Platform**
> → a) {planned platform, e.g., "Standalone (Python)"} ← from the plan
> b) {alternative, e.g., "Cloudflare Workers (TypeScript)"}
> c) Other: ___

**V10. Tool Implementations**
> → a) {planned mode, e.g., "Yes -- all tools as MCP implementations"} ← from the plan
> b) {alternative, e.g., "No -- declarations only, runtime provides them"}
> c) Only implement specific ones: which? ___
> d) Other: ___

**V11. Overall Assessment**
> → a) Plan is correct -- please generate
> b) Adjust plan (please correct the affected items above)
> c) Discard plan and re-plan
> d) Questions about the plan: ___

---

**After receiving validation answers:**
- If V11 = a) (approved): proceed directly to Phase 3 (file generation).
- If V11 = b) (adjustments): apply the corrections from V1-V10, re-present
  **only the changed sections** of the plan (not the full plan), and show
  an updated validation menu with only the changed questions.
- If V11 = c) (discard): return to Phase 1 or Phase 2 Step 1.
- If V11 = d) (questions): answer the questions, then re-present V11.

Iterate until the user selects V11 = a). Do NOT generate any files until
the plan is explicitly approved. The plan is the contract between AI and user.

### Phase 3: Generate the Project

Generate files in this order:

#### Step 1: Workflow Manifest

Create `{workflow_dir}/workflow.awp.yaml` with:
- `project` section (name, version, description).
- `graph` section (all agents with depends_on and share_output).
- `execution` section (mode, timeouts, error handling).
- `state` section (persistence, sharing strategy).
- Additional sections as needed: `memory`, `communication`, `observability`, `security` (cross-cutting features, available at any autonomy level).
- If quality scoring is desired, add `observability.evaluation` with metrics, thresholds, and optional retry policy. See the evaluation section below.
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

| Platform | Adapter | Generated Files |
|----------|---------|----------------|
| **Standalone (awp-agents)** | `adapters/standalone.md` | `agent.py` (Python) |
| **Cloudflare Workers** | `adapters/cloudflare-dynamic-workers.md` | `src/index.ts`, `wrangler.toml` (TypeScript) |

**Default (Standalone):** Use `templates/agent.py` which inherits from
`awp.runtime.agent.StandaloneAgent`. This makes every generated agent **fully
functional out of the box** — it can load its own config, build prompts, call
the LLM, handle tools, and enforce output contracts without any additional code.

**Mandatory rules for generated `agent.py` (Standalone adapter):**

1. The `Agent` class MUST inherit from `StandaloneAgent` (not `AWPAgent`).
2. The `__init__` MUST accept optional `agent_dir`, `workflow_dir`, `llm`, and
   `tool_registry` parameters with auto-detection defaults via `Path(__file__)`.
3. The agent MUST be instantiable with no arguments: `Agent()` works standalone.
4. Do NOT override `run()` with stub logic — the inherited `StandaloneAgent.run()`
   provides the complete LLM pipeline. Only override when the agent needs
   custom pre-/post-processing.
5. Include commented-out override hooks (`run`, `_build_system_prompt`,
   `_build_user_message`) so users know what they can customise.

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

#### Step 7b: Built-in Tool Implementations (if tool implementation mode is enabled)

When tool implementation mode is **enabled**, generate MCP implementations for every
built-in tool referenced in any agent's `tools.allowed` list that is **not** already
provided by an external runtime or custom tool. This ensures the workflow is
self-contained and can run without a full AWP runtime providing built-in tool stubs.

**Process:**

1. Collect all unique tool FQNs from every agent's `tools.allowed` across the workflow.
2. For each tool FQN that belongs to a **reserved namespace** (`web`, `http`, `file`,
   `shell`, `agent`, `memory`, `arithmetic`):
   - Generate a working MCP implementation in `{workflow_dir}/mcp/{namespace}_{action}.py`.
   - Use the FastMCP pattern from `templates/mcp-tool.py`.
   - Implement real logic (not stubs) appropriate to the tool's purpose.
   - Match the parameter signature from `references/tools-reference.md`.
3. Tools that the user explicitly provides (e.g., as external MCP servers or custom
   implementations already in `mcp/`) are **skipped** — do not overwrite them.

**Implementation guidelines per namespace:**

| Tool | Implementation approach |
|------|----------------------|
| `web.search` | Use `httpx` or `requests` to call a search API (e.g., DuckDuckGo, SearXNG, or a configurable endpoint). Return structured results. |
| `http.request` | Use `httpx` to make arbitrary HTTP requests with timeout and error handling. |
| `file.read` / `file.write` / `file.list` | Use Python `pathlib` with sandboxed path validation. |
| `shell.execute` | Use `subprocess.run` with timeout and cwd support. |
| `terminal.execute` | Like `shell.execute` but rejects any command containing `sudo`, `pkexec`, or `doas`. Use this for agents that need terminal access without privilege escalation. |
| `memory.write` / `memory.read` / `memory.search` / `memory.curate` | Use file-based storage in a `{workflow_dir}/.memory/` directory. |
| `agent.send_message` / `agent.list_messages` | Use file-based message queue in `{workflow_dir}/.messages/`. |
| `arithmetic.*` | Direct Python arithmetic operations. |
| `digest.fetch` | **Run-scoped Hierarchical Context Digest lookup** (delegation loop only). `digest.fetch(sha)` returns the compact per-level digest at this SHA from the current manager run's DigestStore (`<workspace>/runs/<run_id>/digest/<sha>.json`). Used by workers to pull deeper layers of the digest hierarchy that are not inlined in the manager prompt. Cross-run access is refused. Auto-injected into worker `tools_allowed` when `delegation_loop.digest_enabled` is `true` (the default). |
| `board.post` / `board.read` | **Run-scoped sibling-coordination blackboard** (delegation loop only). Append-only JSONL at `<workspace>/blackboard/<manager_run_id>.jsonl`. `board.post(topic, payload)` appends an entry, `board.read(topic?, since?)` returns entries (optionally filtered). Siblings in the SAME manager run see each other's signals; other runs (and submanagers, which get their own board) cannot. Workers don't need to list these explicitly — the runtime injects them automatically when `delegation_loop.blackboard_enabled` is `true` (the default). |

**Note:** When tool implementation mode is **disabled** (the default), this step is
skipped entirely. Built-in tool FQNs in `tools.allowed` are assumed to be provided
by the target runtime, per the AWP specification ("runtimes SHOULD provide").

**R14 compliance:** When tool implementation mode is enabled, R14 ("tools.allowed MUST
reference registered MCP tools") is satisfied by the generated implementations. When
disabled, R14 compliance depends on the target runtime registering these tools.

#### Step 7c: Code Mode SDK & Skill (if Code Mode is enabled)

When an agent has `capabilities.codemode.enabled: true`:

1. Generate a **typed SDK interface** from the agent's `tools.allowed`.
   Group methods by namespace (e.g., `sdk.web.search()`, `sdk.file.read()`).

   **TypeScript SDK template:**

   ```typescript
   // AWP Code Mode SDK — TypeScript Interface
   // Auto-generated from capabilities.tools.allowed

   /** AWP Tool SDK for Code Mode execution. All methods return a standard AWP ToolResult. */
   export interface AWPToolSDK {
     {{SDK_METHODS}}
   }

   /** Standard AWP tool result. */
   export interface ToolResult {
     ok: boolean;
     status: number;
     data: Record<string, unknown>;
     error: string | null;
   }

   /** Execute function signature. The agent writes a function matching this signature. */
   export type AgentExecuteFn = (sdk: AWPToolSDK) => Promise<Record<string, unknown>>;

   // ── Example SDK shape (when tools include web.*, file.*, memory.*) ──
   //
   // interface AWPToolSDK {
   //   web: {
   //     search(query: string, maxResults?: number): Promise<ToolResult>;
   //   };
   //   file: {
   //     read(path: string): Promise<ToolResult>;
   //     write(path: string, content: string): Promise<ToolResult>;
   //     list(directory: string): Promise<ToolResult>;
   //   };
   //   memory: {
   //     read(key: string): Promise<ToolResult>;
   //     write(key: string, value: string): Promise<ToolResult>;
   //     search(query: string): Promise<ToolResult>;
   //   };
   // }
   ```

   **Python SDK template:**

   ```python
   # AWP Code Mode SDK — Python Class
   # Auto-generated from capabilities.tools.allowed

   from typing import Any

   class ToolResult:
       """Standard AWP tool result."""
       ok: bool
       status: int
       data: dict[str, Any]
       error: str | None

   class AWPToolSDK:
       """AWP Tool SDK for Code Mode execution. All methods return a standard AWP ToolResult."""

       {{SDK_METHODS}}

   # ── Example SDK shape (when tools include web.*, file.*, memory.*) ──
   #
   # class AWPToolSDK:
   #     class web:
   #         async def search(query: str, max_results: int = 5) -> ToolResult: ...
   #
   #     class file:
   #         async def read(path: str) -> ToolResult: ...
   #         async def write(path: str, content: str) -> ToolResult: ...
   #         async def list(directory: str) -> ToolResult: ...
   #
   #     class memory:
   #         async def read(key: str) -> ToolResult: ...
   #         async def write(key: str, value: str) -> ToolResult: ...
   #         async def search(query: str) -> ToolResult: ...
   ```

2. Generate a **Code Mode skill** using `templates/codemode-skill.md`:
   - Replace `{{SDK_TYPE_DEFINITIONS}}` with the generated SDK interface
   - Replace `{{SDK_METHOD_LIST}}` with a list of available methods
   - Replace `{{OUTPUT_SCHEMA_FIELDS}}` with the agent's output contract
   - Replace `{{LANGUAGE}}` and `{{CODE_EXAMPLE}}` with appropriate examples

3. Place the skill at `{agent}/workflow/skills/codemode.md` (agent-level skill).

4. Ensure the agent's `agent.awp.yaml` has:
   - `capabilities.codemode.enabled: true`
   - `capabilities.codemode.language: {typescript|python}`
   - `capabilities.sandbox.type` set (not `none`)

#### Step 7d: Delegation Loop Generation (if engine is delegation_loop)

When generating a delegation_loop workflow:
1. Generate workflow.awp.yaml with `engine: delegation_loop` and full delegation_loop config
2. Generate ONE manager agent directory (agents/manager/) with:
   - agent.awp.yaml (tools disabled, JSON output)
   - SYSTEM_PROMPT.md with DELEGATE/COMPLETE/FAIL instructions
   - Output schema for delegation decisions
3. Workers are NOT generated as files — they are ephemeral
4. **ALWAYS** add the `dynamic_tools` section to workflow.awp.yaml:
   ```yaml
   dynamic_tools:
     enabled: true
     persist: true
     max_total: 50
     allowed_namespaces: [dynamic]
     code_review: true
   ```
5. **ALWAYS** include `code.execute` as a valid tool for workers. The manager's SYSTEM_PROMPT.md must instruct:
   - Use `code.execute` for code execution (NOT `shell.execute` — it is forbidden)
   - Include `code.execute`, `file.read`, `file.write` in `tools_allowed` for codemode workers
   - Set `tool_creation: true` in `codemode` envelope when workers should create reusable tools
   - Workers can save files via `_workspace_dir` and `_output_dir` path variables
6. **NEVER** put `shell.execute` in `tools_allowed` — it is in `forbidden_tools` and will be silently removed, leaving the worker unable to execute code
7. If the user needs quality analysis of worker outputs, add `critique` config under `delegation_loop`:
   ```yaml
   critique:
     enabled: true
     mode: inline
     max_repair_attempts: 2
     repair_budget_fraction: 0.15
     pattern_memory: true
   ```
8. If the user needs workflow-level quality scoring, add `evaluation` config under `observability` (see Evaluation section above)
9. **Manager Intelligence features** — add any of these under `delegation_loop` to enhance problem-solving:
   ```yaml
   # Task Decomposition: manager creates explicit plan before delegating
   planning:
     enabled: true
     max_subtasks: 10
   # Hypothesis-Driven Debugging: systematic failure diagnosis
   diagnosis:
     enabled: true
     max_hypotheses: 3
     confidence_threshold: 0.3
   # Strategy Switching: rotate strategies on stall instead of stopping
   termination:
     strategy_switching:
       enabled: true
       strategies: [decompose_finer, simplify, reframe, escalate]
   # Budget Reservation: phase-based budget allocation
   budget_reservation:
     enabled: true
     phases:
       - {name: core_work, fraction: 0.60}
       - {name: validation_repair, fraction: 0.20}
       - {name: synthesis, fraction: 0.15}
       - {name: reserve, fraction: 0.05}
   # Decision Journal: reflective decision tracking
   decision_journal:
     enabled: true
     max_entries: 20
   ```
   These features add two new manager decision types: **PLAN** (task decomposition, first iteration) and **DIAGNOSE** (failure hypothesis generation). All default to disabled.

#### Step 8: Project Skills (if needed)

If the workflow needs shared domain knowledge, create `{workflow_dir}/skills/{skill_name}/SKILL.md`.

Every generated skill MUST follow the standard skill structure (see `templates/project-skill.md`):

```markdown
---
name: {skill_name}
domain: {domain, e.g. finance, devops, nlp}
scope: project          # or "agent" for agent-level skills
version: "1.0"
---

# {Skill Name}

## Purpose
{One sentence: what decision or task does this skill support?}

## Concepts
{3-7 key terms/frameworks as definition list}

## Rules
{Numbered, testable constraints the agent MUST follow}

## Procedure
{Step-by-step sequence — omit if skill is purely declarative}

## Examples
{At least one input → output pair}

## References
{Optional: external standards or sources}
```

**Mandatory sections:** Purpose, Concepts, Rules.
**Conditional sections:** Procedure (include when the skill describes a multi-step process), Examples (include when correct application is non-obvious), References (include when the skill draws from external standards).

Do NOT generate skills that are just a flat list of bullet points — every skill must have the structured sections above so agents can reliably parse and apply the knowledge.

#### Step 9: WORKFLOW.md (Project Overview)

Generate `{workflow_dir}/WORKFLOW.md` as specified in Phase 4b. This file MUST always
be generated — it is not optional. It serves as the human-readable entry point for
anyone opening the project. The file uses only plain-text ASCII diagrams so it is
universally readable without rendering tools.

### Phase 4: Validation Checklist

After generating all files, verify:

- [ ] R1: workflow.name matches directory name.
- [ ] R2: All agent IDs are snake_case.
- [ ] R3: All agent.py files define class Agent extending StandaloneAgent (standalone) or AWPAgent (other platforms).
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
- [ ] R14: tools.allowed references valid MCP tools (if tool implementation mode: verify generated implementations exist in mcp/).
- [ ] R15: tools.execute=false implies empty allowed list.
- [ ] R16: execution.mode is sequential, parallel, or conditional.
- [ ] R17: All output schemas include confidence field.
- [ ] R18: All output_schema.json are valid JSON Schema draft-07 with type: object.
- [ ] R19: If codemode.enabled, then tools.enabled must be true.
- [ ] R20: If codemode.enabled, sandbox.type must be set (not "none").
- [ ] R21: codemode.language is typescript, python, or javascript.
- [ ] R22: If sdk_surface.mode is "explicit", include list is non-empty.
- [ ] R23: sdk_surface.exclude entries match tools in tools.allowed.
- [ ] R24: If sandbox.type is "isolate", sandbox.network is defined.
- [ ] R25: WORKFLOW.md exists at project root with ASCII diagram and abstract-to-concrete description.
- [ ] R27: If evaluation enabled, all metric kinds are valid (deterministic_test, deterministic_assertion, rubric_judge, budget_utility, policy_score).
- [ ] R28: Evaluation thresholds satisfy accept >= retry >= fail, all in [0, 1].
- [ ] R29: Evaluation metric weights are >= 0 with at least one > 0.
- [ ] R30: step_scores.hooks uses valid hooks; retry_policy actions are valid.
- [ ] If `budget_reservation.enabled`, phase fractions sum to 1.0.
- [ ] If `planning.enabled`, `max_subtasks` is a positive integer.
- [ ] If `diagnosis.enabled`, `confidence_threshold` is in [0.0, 1.0].
- [ ] If `strategy_switching.enabled`, `strategies` list is non-empty.
- [ ] `budget.max_workers_per_iteration` is a positive integer (default 6) when delegation_loop is used. Keep it ≤ `max_total_workers / max_loops` for sensible fan-out.
- [ ] `budget.max_rejected_completions` is a positive integer (default 2) when delegation_loop is used. Bounds how many times the completion-gate chain (`deliverable_presence`, `placeholder`, `file`, `structural_integrity`, `critique`, `eval`) may reject a `COMPLETE` decision before the runner synthesizes a repair subtask or terminates as `partial` with reason `max_rejected_completions`.
- [ ] Subtasks that produce files SHOULD include an explicit `required_outputs: [<relpath>, …]` list so the `deliverable_presence` gate can verify them deterministically (priority 1 over regex-scraping `success_criteria`).
- [ ] PLAN `tool_manifest` entries marked `reuse_or_generate: "reuse"` MUST set `pattern_id` to one of the values listed under "Known pattern_ids" in the manager prompt. If no concrete pattern fits, use `reuse_or_generate: "synthesize"` with an `archetype_id` — never invent a `pattern_id` (the R31 validator surfaces the full known-pattern list on rejection).
- [ ] Terminal status: every example and template treats cap-forced exits (`defect_category_cap`, `plan_loop`, `plan_loop_stall`, `forced_convergence`, `max_total_*`, `max_wall_time`, `max_loops`, `max_rejected_completions`) as `partial` — never `complete`. Hard errors are `failed`. Process exits without a terminal decision are `aborted`.

### Evaluation / Quality Scoring (Optional)

AWP supports an optional evaluation layer under `observability.evaluation` that scores workflow results on problem-solving quality. This is separate from validation (which checks structural correctness).

**When to use evaluation:**
- When you need measurable quality scores on workflow outputs
- When workflows should retry/repair based on result quality
- When comparing different models or configurations on the same task

**Example evaluation config:**

```yaml
observability:
  evaluation:
    enabled: true
    metrics:
      - name: correctness
        kind: deterministic_test
        weight: 2.0
        params:
          expr: "result.confidence > 0.7 and 'error' not in result"
      - name: completeness
        kind: deterministic_assertion
        weight: 1.0
        params:
          assertions:
            - "'data' in result"
            - "result.confidence > 0"
      - name: efficiency
        kind: budget_utility
        weight: 0.5
    thresholds:
      accept: 0.85
      retry: 0.65
      fail: 0.40
    step_scores:
      enabled: true
      hooks:
        - worker_result
        - final_answer
    retry_policy:
      enabled: true
      max_repairs: 2
      actions:
        below_retry: retry_with_repair
        below_fail: fail_workflow
```

**Metric kinds:**
- `deterministic_test` — safe expression eval (params: `expr`)
- `deterministic_assertion` — list of assertions, fraction passing (params: `assertions`)
- `rubric_judge` — LLM-based scoring with a rubric (params: `rubric`)
- `budget_utility` — efficiency score based on budget usage
- `policy_score` — governance/policy assertion checks (params: `assertions`)

**Important:** The `step_scores` field uses `hooks` (not `on`) because `on` is a YAML boolean keyword.

### Reflective Critique Loop (Optional, A2+ only)

AWP supports an optional critique system under `delegation_loop.critique` that analyzes worker outputs for defects and triggers targeted repairs. This is separate from evaluation (which scores the overall result).

**When to use critique:**
- When worker outputs need quality analysis before the manager sees them
- When you want automatic repair of defective outputs (not full workflow retry)
- When cross-worker failure pattern learning would improve later iterations

**Example critique config:**

```yaml
orchestration:
  engine: delegation_loop
  delegation_loop:
    critique:
      enabled: true
      mode: inline                    # "inline" (worker model) or "dedicated"
      max_repair_attempts: 2          # Per-worker repair cycles
      repair_budget_fraction: 0.15    # Max 15% of budget for repairs
      pattern_memory: true            # Learn from failures across workers
      defect_categories:
        - missing_data
        - wrong_format
        - incomplete
        - hallucinated
        - policy_violation
```

**Critique vs Evaluation:**
- **Critique** operates per-worker: diagnoses specific defects, prescribes fixes, repairs individual outputs
- **Evaluation** operates per-workflow: scores the overall result, decides accept/retry/fail
- Both can be enabled independently. When both active, critique repairs happen BEFORE evaluation scoring.

**Key fields:**
- `mode: inline` — uses the worker model (cheap). `mode: dedicated` — separate critic agent
- `pattern_memory: true` — accumulates failure patterns, injects "Known Pitfalls" into next workers
- `repair_budget_fraction` — caps total repair spend (e.g., 15% of budget)
- `defect_categories` — types: missing_data, wrong_format, incomplete, hallucinated, stale, policy_violation

### Phase 4b: Generate WORKFLOW.md (Project-Level Overview)

**IMPORTANT:** After validation and before presenting the summary, you MUST generate
a `{workflow_dir}/WORKFLOW.md` file at the project root. This file serves as the
always-readable, self-contained documentation of the workflow. It MUST use only
plain-text ASCII diagrams (no Mermaid, no HTML, no images) so it renders correctly
in any Markdown viewer, terminal, or text editor.

The file follows a **top-down structure** from abstract to concrete:

```markdown
# {Workflow Name}

> {One-sentence elevator pitch: what this workflow does and why.}

**AWP Autonomy:** A{N} {Level Name} | **Agents:** {count} | **Execution:** {mode}

---

## Workflow Diagram

{ASCII box-and-arrow diagram — see format below}

---

## Overview (Abstract)

{2-3 sentences: What problem does this workflow solve? What is the input,
what is the output? Written for someone who has never seen AWP.}

## Agent Roles (Conceptual)

{For each agent: name, role in plain language, what it receives, what it delivers.
Use a table or bullet list.}

| Agent | Role | Receives from | Delivers to |
|-------|------|--------------|------------|
| `{id}` | {role} | {upstream or "User input"} | {downstream or "Final output"} |

## Data Flow (Architectural)

{Concrete data contracts: which fields flow between agents, with types.
Use the ASCII arrow notation from Phase 2 Step 3.}

## Tools & Capabilities (Technical)

{Table mapping each agent to its tools, memory, skills, code mode.}

## File Structure (Implementation)

{Tree listing of all generated files, grouped by agent.}

## Getting Started

{Ready-to-use commands: install, run, validate.}

---

*Generated by AWP Workflow Builder — {date}*
```

**Diagram rendering rules:**

The ASCII diagram in `WORKFLOW.md` MUST be rendered with care for visual quality.
Use Unicode box-drawing characters (`┌ ┐ └ ┘ │ ─ ├ ┤ ┬ ┴ ┼ ▼ ▶ ◀ ▲`) for clean
rendering. Follow these rules:

1. **All agents** appear as labeled boxes with their role name.
2. **Data flow** between agents as arrows with the shared field names on the edge.
3. **Tools** attached to the agents that use them (as small labels inside the box).
4. **Memory** tiers if the workflow uses persistence.
5. **Input** (top) and **Output** (bottom) clearly marked.
6. **Consistent box widths** — all boxes at the same level should have the same width.
7. **Center-aligned** — the diagram should be visually centered and balanced.
8. For **parallel agents**, show them side by side with a horizontal spread.
9. For **conditional execution**, annotate arrows with the condition in `[brackets]`.
10. **No Mermaid, no HTML** — only plain-text ASCII so the file is universally readable.

### Phase 5: Summary & Workflow Overview

**CRITICAL — This is the final presentation to the user.** Phase 5 MUST always
be displayed **in Claude's terminal output** before any zip/pack file is offered.
The user should see the complete workflow at a glance — diagram, description,
files, and autonomy level — directly in the conversation. This is NOT optional.
Do not skip to the zip output. Do not abbreviate. The terminal presentation
IS the deliverable that the user reviews before accepting the workflow.

Present the following sections **in this exact order**:

---

#### 5a. Workflow Header

```
═══════════════════════════════════════════════════════════════
  AWP Workflow: {workflow_name}
  Autonomy: A{N} {Level Name} │ Agents: {count} │ Mode: {execution_mode}
═══════════════════════════════════════════════════════════════
```

#### 5b. Workflow Architecture Diagram

**This is the visual centerpiece.** The ASCII diagram MUST be rendered directly
in Claude's output with maximum visual quality. It is the first thing the user
sees and must immediately convey the workflow's structure.

Rendering rules:
- Use Unicode box-drawing characters (`┌ ┐ └ ┘ │ ─ ├ ┤ ┬ ┴ ┼ ▼ ▶ ◀ ▲`)
- Align all boxes cleanly, consistent widths per level
- Balance whitespace so the diagram is visually centered
- A well-rendered diagram is worth more than paragraphs of text

The diagram MUST show:

1. **All agents** as labeled boxes with their role name
2. **Data flow** between agents as arrows with shared field names
3. **Tools** attached to each agent (as labels inside the box)
4. **Code Mode** indicator (`⚡ Code Mode`) for agents with codemode enabled
5. **Skills** indicator (`📖 {skill_name}`) for agents with injected skills
6. **Memory** tiers if the workflow uses persistence
7. **Input** (top) and **Output** (bottom) clearly marked

Use this format:

```
                        ┌─────────────────────┐
                        │     User Input       │
                        │  "{task_description}" │
                        └──────────┬──────────┘
                                   │
                                   ▼
                  ┌────────────────────────────────────┐
                  │  {agent_id}                         │
                  │  Role: {role_description}           │
                  │  Tools: {tool_1}, {tool_2}          │
                  │  ⚡ Code Mode ({language})           │
                  │  📖 Skill: {skill_name}              │
                  │  Output: {field_1}, {field_2}       │
                  └──────────────────┬─────────────────┘
                                     │ shares: {field_1}
                                     ▼
                  ┌────────────────────────────────────┐
                  │  {agent_id}                         │
                  │  Role: {role_description}           │
                  │  Tools: {tool_1}                    │
                  │  Output: {field_3}, confidence      │
                  └──────────────────┬─────────────────┘
                                     │
                                     ▼
                        ┌─────────────────────┐
                        │    Final Output      │
                        │  {output_description} │
                        └─────────────────────┘
```

For parallel agents, show them side by side with a horizontal spread.
For conditional execution, annotate arrows with the condition in `[brackets]`.
Adapt the layout to the actual complexity — a 2-agent workflow gets a simple
diagram, a 6-agent DAG with branches gets a more detailed one.

**For Delegation Loop workflows (A2-A4),** use this format:

```
                        ┌─────────────────────┐
                        │     User Input       │
                        └──────────┬──────────┘
                                   │
                  ┌────────────────▼────────────────┐
                  │         MANAGER AGENT            │
                  │  Role: {manager_role}            │
                  │  Model: {manager_model}          │
                  │  Decision: DELEGATE/COMPLETE/FAIL│
                  └──────┬──────────────────┬───────┘
                         │ Iteration 1      │ Iteration 2
                   ┌─────┴─────┐      ┌─────┴─────┐
                   ▼           ▼      ▼           ▼
              ┌─────────┐ ┌─────────┐ ┌─────────┐
              │Worker A │ │Worker B │ │Worker C │
              │{role_a} │ │{role_b} │ │{role_c} │
              │Skills: ✓│ │Skills: ✓│ │Tools: ✓ │
              └────┬────┘ └────┬────┘ └────┬────┘
                   └──────┬────┘           │
                          ▼                ▼
                  ┌───────────────┐ ┌───────────┐
                  │  Validation   │ │  Stall    │
                  │  (2-tier)     │ │  Check    │
                  └───────┬───────┘ └─────┬─────┘
                          └───────┬───────┘
                                  ▼
                        ┌─────────────────────┐
                        │    Final Output      │
                        │  Budget: {used}/{max}│
                        └─────────────────────┘
```

Show the iteration flow, fan-out workers, validation, and budget status.
For recursive delegation (A4), show the sub-manager hierarchy.

#### 5c. Workflow Description (Narrative Walkthrough)

Directly below the diagram, provide a **narrative walkthrough** of the workflow
in 4-8 sentences. This description must:

1. **Explain the purpose** — What problem does this workflow solve? What goes in,
   what comes out?
2. **Walk through each stage** — Describe what happens at each agent in plain
   language, as if explaining it to someone who hasn't read the config files.
3. **Highlight the generated capabilities** — Which skills were generated and why?
   Which custom MCP tools were created? Which agents use Code Mode and what
   advantage does it give them?
4. **Explain key design decisions** — Why this agent order? Why these tools?
   Why this data flow? Why this autonomy level?

Example:

> This workflow automates cloud security audits by orchestrating three specialized
> agents in a sequential pipeline. The **scanner** agent uses Code Mode (TypeScript)
> to execute 14 AWS API calls in a single LLM roundtrip via the generated
> `mcp/aws_scanner.py` tool — checking security groups, IAM policies, and S3
> bucket configurations. Its findings flow to the **analyzer** agent, which uses
> the generated `skills/aws-compliance/SKILL.md` (containing CIS Benchmark v8.0
> controls and NIST 800-53 mappings) to classify each finding by severity and
> recommend remediations. Finally, the **reporter** agent produces an executive
> summary with risk scores, using the `skills/report-writing/SKILL.md` for
> formatting standards. The workflow is A1 Adaptive (multi-agent DAG with state
> sharing and conditional execution) and requires only an OpenRouter API key to run.

#### 5d. Generated Capabilities Summary

Present a table of all generated skills, MCP tools, and Code Mode configurations:

```
  Generated Capabilities
  ──────────────────────────────────────────────────────────
  Skills:
    • skills/{name}/SKILL.md — {what domain knowledge it contains}
    • skills/{name}/SKILL.md — {what domain knowledge it contains}

  Custom MCP Tools:
    • mcp/{file}.py — {tool_fqn}: {what it does}
    • mcp/{file}.py — {tool_fqn}: {what it does}

  Code Mode Agents:
    • {agent_id} — {language}, sandbox: {type}, SDK surface: {tool_count} tools
  ──────────────────────────────────────────────────────────
```

If no custom skills, tools, or Code Mode agents were generated, state it
explicitly (e.g., "No custom MCP tools generated — workflow uses only built-in tools.").

#### 5e. Files Generated

List all generated files with count:

```
  Files Generated: {count}
  ──────────────────────────────────────────────────────────
  {workflow_name}/
    workflow.awp.yaml
    WORKFLOW.md
    agents/
      {agent_id}/
        agent.awp.yaml
        agent.py
        workflow/
          instructions/SYSTEM_PROMPT.md
          prompt/00_INTRO.md
          output_schema/output_schema.json
          output_schema_desc/output_schema_desc.json
    skills/
      {skill_name}/SKILL.md
    mcp/
      {tool_file}.py
  ──────────────────────────────────────────────────────────
```

#### 5f. Autonomy Badge & Validation

```
  ✅ Validation: All {count}/32 applicable rules passed
  🏷️  AWP A{N} {Level Name}
```

- Reference to `WORKFLOW.md` for the full project documentation.
- Any assumptions made or recommendations for improvement.

#### 5g. Quick Start Commands

**CRITICAL:** Always end with ready-to-run commands. The user should be able to
copy-paste and immediately test the workflow.

```
  ══════════════════════════════════════════════════════════
  ▶ Quick Start
  ──────────────────────────────────────────────────────────

  # Validate the workflow
  awp validate {workflow_name}/

  # Run it (DAG engine)
  awp run {workflow_name}/ --task "{example_task}" --debug

  # Run it (Delegation Loop — if A2+)
  awp run {workflow_name}/ --task "{example_task}" \
    --manager-model openrouter/anthropic/claude-sonnet-4 \
    --worker-model openrouter/anthropic/claude-sonnet-4

  # Check autonomy level
  awp compliance {workflow_name}/ --level A{N}

  # Pack for sharing
  awp pack {workflow_name}/
  ══════════════════════════════════════════════════════════
```

Show only the commands relevant to the generated workflow's engine type.
For delegation loop workflows, always show the `--manager-model` / `--worker-model` variant.
For DAG workflows, show the simple `awp run` command.

#### 5h. Transition to Zip / Pack

After the Quick Start commands, offer the packaged workflow:

```
  📦 Ready to pack: awp pack {workflow_name}/ → {workflow_name}.awp.zip
```

#### How to Use

Provide ready-to-use commands for running the workflow:

**Install dependencies:**

```bash
cd {workflow_name}/
pip install -r requirements.txt    # if requirements.txt was generated
# or
pip install awp-agents
```

**Run the workflow:**

```bash
awp run {workflow_name}/ --task "{example_task_description}"
```

**Run with Python:**

```python
from awp.runtime import WorkflowRunner

runner = WorkflowRunner("{workflow_name}")
result = runner.run("{example_task_description}")
print(result["{final_agent_id}"])
```

**Run on Cloudflare Workers** (if Cloudflare adapter was used):

```bash
cd {workflow_name}/
npm install
wrangler kv namespace create STATE
# → copy id into wrangler.toml
wrangler secret put LLM_API_KEY
wrangler deploy
```

```bash
# Invoke the deployed workflow
curl -X POST https://{workflow_name}.{account}.workers.dev \
  -H "Content-Type: application/json" \
  -d '{"task": "{example_task_description}"}'
```

**Customize:**

- Edit agent prompts in `agents/{agent_id}/workflow/instructions/SYSTEM_PROMPT.md`
- Adjust output schemas in `agents/{agent_id}/workflow/output_schema/`
- Add or change tools in `agents/{agent_id}/agent.awp.yaml` under `tools.allowed`
- Add domain knowledge in `skills/{skill_name}/SKILL.md`

If the workflow uses secrets, also show:

```bash
cp secrets.yaml.example secrets.yaml
# Edit secrets.yaml with your API keys
```

**Validate the workflow:**

```bash
awp validate {workflow_name}/
```

#### Required API Keys & Secrets

After the "How to Use" section, you MUST present a summary of **all API keys and
secrets** that are required (or optional) to run this workflow. This allows the
user to prepare everything before the first run.

Generate this section dynamically based on the workflow's actual configuration:

1. **LLM API Key:** Derived from the model the user will select at runtime.
   Always show the most common providers and their key sources.
2. **Tool Secrets:** Derived from the tools used across all agents (from
   `tools.allowed` in each `agent.awp.yaml`). Map each tool to the API key
   it typically needs.
3. **Custom Secrets:** Any secrets declared in the workflow's `env.required`
   section of `workflow.awp.yaml`.

Present in this format:

---

**Required API Keys**

> The LLM model is selected at startup via the **Run-Wizard** or `LLM_MODEL`.
> Depending on the model, a matching API key is required:

| Purpose | Env Variable | Provider | Obtain Key |
|---------|-------------|----------|------------|
| LLM (OpenRouter) | `OPENROUTER_API_KEY` | OpenRouter | https://openrouter.ai/keys (free) |
| LLM (OpenAI) | `OPENAI_API_KEY` | OpenAI | https://platform.openai.com/api-keys |
| LLM (Groq) | `GROQ_API_KEY` | Groq | https://console.groq.com/keys (free) |
| LLM (Ollama) | — | Ollama (local) | No key needed — https://ollama.com |
| LLM (Deepseek) | `DEEPSEEK_API_KEY` | DeepSeek | https://platform.deepseek.com/api_keys |
| LLM (Mistral) | `MISTRAL_API_KEY` | Mistral | https://console.mistral.ai/api-keys |
| LLM (Together) | `TOGETHER_API_KEY` | Together AI | https://api.together.xyz/settings/api-keys |
| LLM (Fireworks) | `FIREWORKS_API_KEY` | Fireworks | https://fireworks.ai/account/api-keys |
| LLM (universal) | `LLM_API_KEY` | Any | Overrides all provider-specific keys |

> **Tip:** Only **one** LLM key is needed — matching the chosen provider.
> OpenRouter is recommended as it provides access to many models via a single key.

{If the workflow uses tools that need API keys, add a second table:}

| Tool | Env Variable | Description | Obtain Key |
|------|-------------|------------|------------|
| `web.search` (Premium) | `SEARCH_API_KEY` | Optional — DuckDuckGo works without a key | Depends on provider (Google, Bing, SearXNG) |
| `http.request` | `AUTH_TOKEN` | Only if target API requires authentication | From the respective API provider |
| {custom_tool} | `{SECRET_NAME}` | {description} | {where to get it} |

{Only include tool rows that are actually used in this workflow. Omit the tool
table entirely if no tools need secrets.}

> **Setting up secrets:**
>
> ```bash
> # Option 1: Set environment variable
> export OPENROUTER_API_KEY="sk-or-..."
>
> # Option 2: Store in secrets.yaml (offered on first `awp run`)
> cp secrets.yaml.example secrets.yaml
> # Edit file and enter keys
>
> # Option 3: Set globally in ~/.awp/.env for all workflows
> echo 'OPENROUTER_API_KEY=sk-or-...' >> ~/.awp/.env
> ```

---

**IMPORTANT:** The API key table must be **specific** to this workflow. Do not
list providers that are irrelevant. If the workflow only uses web.search with
the free DuckDuckGo fallback, state that no tool secrets are required. Always
highlight which keys are **required** vs. **optional**.


### Design Patterns

AWP workflows follow common patterns. Use the right pattern for the task:

**Pipeline Pattern** (A0-A1)
Linear chain: each agent feeds the next.
```
planner → researcher → writer
```
Best for: sequential processing, ETL, document generation.

**Fan-Out / Fan-In Pattern** (A1)
One agent produces items, multiple agents process in parallel, one aggregates.
```
splitter → [worker_1, worker_2, worker_3] → aggregator
```
Best for: parallel analysis, batch processing.

**Conditional Branching Pattern** (A1)
Agents execute based on conditions from previous results.
```
analyzer → (if risk > 0.7) → deep_analysis
         → (if risk <= 0.7) → summary
```
Best for: triage, routing, adaptive workflows.

**Manager-Worker Pattern** (A2)
A manager delegates to dynamic workers, evaluates results, iterates.
```
manager → [worker_a, worker_b] → validate → manager → [worker_c] → complete
```
Best for: research, analysis, open-ended investigation.

**Tool Builder Pattern** (A3)
Phase 1: builder creates tools. Phase 2: analyst uses tools.
```
Iteration 1: manager → tool_builder (creates scoring.*)
Iteration 2: manager → [analyst_1, analyst_2] (uses scoring.*)
Iteration 3: manager → complete
```
Best for: configurable scoring, dynamic evaluation criteria.

**Self-Organizing Team Pattern** (A4)
Manager delegates to sub-managers who further delegate within their budget.
```
manager (budget: 20 workers)
├── sub_manager_a (budget: 8) → [worker_a1, worker_a2]
├── worker_b
└── sub_manager_c (budget: 6) → [worker_c1]
```
Best for: complex multi-faceted analysis, deep research.

### Example Workflows by Autonomy Level

**A0 Prescribed — Hello World**
```yaml
orchestration:
  engine: dag
  graph:
    - id: greeter
      agent: greeter
```
Single agent, fixed output. The simplest valid AWP workflow.

**A1 Adaptive — Research Pipeline**
```yaml
orchestration:
  engine: dag
  graph:
    - id: planner
      agent: planner
    - id: researcher
      agent: researcher
      depends_on: [planner]
    - id: writer
      agent: writer
      depends_on: [researcher]
```
Three agents in sequence, state shared between them.

**A2 Delegating — Dynamic Research**
```yaml
orchestration:
  engine: delegation_loop
  delegation_loop:
    manager: agents/manager
    budget: {max_loops: 5, max_total_workers: 10, max_wall_time: 300}
    context_budget: {total_chars: 64000, min_per_entry: 4000, preview_chars: 2000}
    validation: {deterministic: {always: true}, llm: {enabled: false}}
```
Manager analyzes task, spawns specialist workers with generated skills, iterates until confident.
Context sharing: small results inline, large results spill to `workspace/context/` with preview.

**A3 Self-Tooling — Configurable Scoring**
```yaml
orchestration:
  engine: delegation_loop
  delegation_loop:
    manager: agents/manager
    budget: {max_loops: 3, max_total_workers: 6, max_wall_time: 600}
    worker_policy:
      enforced: {sandbox: {type: subprocess}}
      manager_controlled: [instructions, skills, tools_allowed, codemode.enabled, codemode.tool_creation]

dynamic_tools:
  enabled: true
  allowed_namespaces: [scoring]
```
Manager spawns a tool-builder that creates scoring tools, then spawns analysts that use those tools.

**A4 Self-Organizing — Startup Evaluation**
```yaml
orchestration:
  engine: delegation_loop
  delegation_loop:
    manager: agents/manager
    budget: {max_loops: 5, max_total_workers: 12, max_wall_time: 900, max_depth: 2}
    worker_policy:
      enforced: {sandbox: {type: subprocess}}
    termination: {enabled: true, window: 3, min_confidence_delta: 0.02}
    validation: {deterministic: {always: true}, llm: {enabled: true}}
    logging: {format: dual, persist_artifacts: true}

dynamic_tools:
  enabled: true
  allowed_namespaces: [scoring, analysis]
```
Multi-phase: creates tools → evaluates items in parallel → synthesizes ranking. Workers can sub-delegate.


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
| `codemode-skill.md` | Code Mode execution skill (auto-generated from tools). |
| `adapters/cloudflare/` | Cloudflare Workers project templates (wrangler.toml, src/). |

**Auto-generated files (not templates, always created):**

| File | Purpose |
|------|---------|
| `WORKFLOW.md` | Project-level overview with ASCII diagram and abstract-to-concrete description. Always generated at project root. |

## Extensions (Skill Inheritance)

The `extensions/` directory contains domain-specific customizations that
**extend** this base skill -- like subclass inheritance.  An extension can:

- Override defaults (model, autonomy level, temperature)
- Add required agents (e.g., `risk_assessor` for financial workflows)
- Add required output fields (e.g., `data_sources` for every agent)
- Add domain-specific rules (F1, F2, ... or D1, D2, ...)
- Inject content into system prompts (prepend/append/replace)
- Include additional project-level skills
- Include additional custom MCP tools
- Set constraints (deny tools, require memory tiers, min autonomy level)

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
| `extensions/examples/financial.md` | Finance | Risk assessor agent, audit trail, regulatory compliance controls |
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
| `adapters/standalone.md` | Generate `agent.py` for the AWP standalone runtime (Python) |
| `adapters/cloudflare-dynamic-workers.md` | Generate TypeScript project for Cloudflare Workers deployment |
| `adapters/clawhub.md` | Publish AWP skills and workflows to ClawHub registry |

**Adapter selection:** Choose based on the user's answer to question 9.1 (target platform).
If Cloudflare is selected, read `adapters/cloudflare-dynamic-workers.md` for the full
generation instructions and use the templates in `templates/adapters/cloudflare/`.

Third-party platforms can add their own adapters following the same pattern.


## References

The `references/` directory contains condensed documentation for AI context:

| Reference | Purpose |
|-----------|---------|
| `spec-summary.md` | Condensed AWP specification (~2000 words). |
| `compliance-levels.md` | Quick reference for A0-A4 autonomy levels. |
| `validation-rules.md` | R1-R32 checklist format. |
| `tools-reference.md` | Built-in MCP tool catalog. |
| `architecture.md` | Architecture overview. |
