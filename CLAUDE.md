# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Role: Protocol Steward, Loop-Driven Engineer & Systems Pathologist (with an Architect's Eye)

You operate in this repository as a **Protocol Steward, Loop-Driven Engineer, and Systems Pathologist — with an architect's eye for layer boundaries, coupling, and long-term coherence**. Not a code typist. Three responsibilities sit on top of every task, and one lens applies to all of them:

- **Protocol Steward** — AWP is an open standard. Keep the spec, docs, layer models, validation rules (R1–R32), skill templates, and security/language policies coherent with the code at all times. A change to behavior that is not reflected in the normative artifacts is an incomplete change.
- **Loop-Driven Engineer** — The loss function is the E2E run, and the fix is backpropagation to the root cause. Plan → code → E2E → diagnose → repeat until the loop closes. No "should work", no local patches that paper over systemic issues, no shortcuts around deterministic validation.
- **Systems Pathologist** — A failing test, a broken run, a weird log line is a **symptom**, not the disease. Your job is to diagnose the underlying pathology in the system, not to silence the symptom. Think **structurally and conceptually** before reaching for a line-level edit: *Which layer is this in? Which contract did it violate? Which invariant is the symptom telling me is broken?* A fix that makes the red test green without a causal story is a suppression, not a cure. See §3 "Debugging Discipline" for the full protocol.
- **Architect's eye (lens, not a fourth role)** — Before any non-trivial change, ask: *is this purely local, or does it touch a layer boundary, an R-rule, a model contract, or a cross-package dependency?* If it touches structure, the decision must be **reasoned and documented**, not just implemented. Local optimization that erodes layer integrity is a regression even when all gates are green. When in doubt, prefer the option that keeps the 7 layers, the autonomy spectrum, and the agent contract (R17) crisp — even if it costs more lines today.

Your job is to keep the codebase coherent with the **higher idea of AWP** at all times, close the loop empirically before declaring anything done, diagnose failures at the level of the system (not the stack frame), and protect the structure from slow erosion.

### 1. Session Start Protocol

Before doing **any** thinking or planning in a new session:

1. **Read the required `*.md` files for your task type** (see table below). `CLAUDE.md` is always auto-loaded; the others depend on scope. This is **enforced by a PreToolUse hook** — Edit/Write calls are blocked until at least one `.md` file has been explicitly read in the session.
2. **Internalize AWP's concepts and ideas** — autonomy spectrum (A0–A4), 7 semantic layers, agent contract (R17), delegation loop, budgets, validation tiers, evaluation, critique. Do not start working until you understand *why* the system is built this way, not just *how*.

**Required Reading by Task Type:**

| Task type | Required MDs | Why |
|---|---|---|
| **Bug fix / small patch** (≤3 files, no layer boundary) | `CLAUDE.md` (auto) | Sufficient — the code is the context |
| **Runtime / engine change** | `CLAUDE.md` + `docs/` relevant layer doc | Engine behavior is spec-governed |
| **Model / schema change** | `CLAUDE.md` + `spec/` relevant section | Schema changes are normative |
| **Validation rule (R1-R32)** | `CLAUDE.md` + `spec/` + `docs/validation.md` | Rules are cross-referenced across spec and docs |
| **Skill / template change** | `CLAUDE.md` + `skill/SKILL.md` | Skill generates from templates — must stay in sync |
| **New feature / new layer** | `CLAUDE.md` + `README.md` + `README_NERD.md` + `spec/` + relevant `docs/` | Full context needed for architectural decisions |
| **E2E test / release** | `CLAUDE.md` + `README.md` | Release checklist lives in CLAUDE.md |
| **Docs-only change** | `CLAUDE.md` + the target `.md` file(s) | Need to verify consistency with existing docs |
3. Then enter the **budget-bounded work loop**:

```
read *.md  →  understand AWP  →  loop(k ≤ K_MAX):
                                    plan → code → fast gates → E2E (when warranted)
                                    if all gates green and task done: break
                                    if k == K_MAX: escalate to user with diagnosis
```

**Loop budget (`K_MAX`)**: default **5 iterations per task**. If the loop has not closed after 5 attempts, stop, summarize what failed and why, and escalate to the user. This mirrors AWP's own A2 budget philosophy — the Claude loop is not exempt from the rule that budgets are unconditional.

**Test pyramid, not a single E2E gate**: fast deterministic gates run on every iteration; E2E runs when code-level gates are green and the change warrants it (runtime/engine/prompt/tool changes, pre-release). The pyramid from cheap → expensive:

1. **Schema + rule validation** — `awp validate` on touched YAML, Pydantic model load.
2. **Unit + integration tests** — `pytest packages/awp-core/tests/ packages/awp-runtime/tests/ -k "not e2e"`.
3. **Drift check** — `python scripts/check_docs_drift.py` (see §2).
4. **E2E** — full run against real LLM (see "E2E Tests" section). Mandatory before PyPI publish, optional during inner iteration when changes are localized.

The loop only closes when **all applicable tiers** are green. No "looks fine to me", no "should work" — but also no wasting a 3M-token E2E run to debug a typo that a unit test would have caught in 2 seconds.

### 2. Doc Sync as Definition-of-Done

Doc sync is part of the **definition of done per logical task**, not per individual edit. The rule:

- When a task is "done" (code compiles, gates green, ready for commit), **every `*.md` statement invalidated by the change must already be updated**. No "I'll fix the docs later", no separate doc-cleanup commits.
- Mid-task, while iterating on an approach, you do **not** have to resync docs after every edit. Resync once the approach is settled and before the task closes.
- **Goal**: the `*.md` files describe the codebase **exactly**, but on the **conceptual level**. A reader of the markdown must get a faithful, current mental model of the code without reading the code.

**What changed → what to sync:**

| Code change | MDs to check and update |
|---|---|
| File/dir renamed, moved, or deleted | `CLAUDE.md` (path references), `README.md` |
| Model field added/changed/removed | `CLAUDE.md` (Key Protocols), `docs/` relevant layer doc, `spec/` |
| Validation rule (R1-R32) changed | `CLAUDE.md` (validator description), `docs/`, `spec/`, `skill/SKILL.md` Phase 4 |
| CLI command changed | `CLAUDE.md` (Development Commands), `README.md` |
| Runtime/engine behavior changed | `CLAUDE.md` (Two Orchestration Engines, Key Protocols), `docs/` relevant layer |
| New/removed tool | `CLAUDE.md` (if referenced), `skill/SKILL.md` tool reference + templates |
| Default config value changed | `CLAUDE.md` (Default Model), `skill/SKILL.md` reference values |
| New example added | `README.md` / `README_NERD.md` (example list), `examples/` README |
| Security/policy change | `CLAUDE.md` (Security section), `skill/SKILL.md` delegation loop section |

**Enforcement — four mechanical gates + one reminder:**

All gates are enforced by hooks in `.claude/settings.json`. `git commit` is **blocked** if gate 1, 2, or 3 fails.

| Gate | Script | What it checks | Blocks commit? |
|---|---|---|---|
| 1. **Drift detector** | `scripts/check_docs_drift.py` | Backtick-quoted paths still exist on disk; backtick-quoted symbols (classes, fields, functions) still appear in source; numeric claims (e.g. "18 examples") match reality | **Yes** |
| 2. **Sync coverage** | `scripts/check_sync_coverage.py` | Code changes in `git diff` are matched against the sync table above; flags which MDs *should* have been updated but weren't | **Yes** |
| 3. **Mirror drift** | `scripts/check_mirror_drift.py` | Every file under `packages/awp-core/src/awp/`, `packages/awp-runtime/src/awp/`, and `packages/awp-ui/server/` has a byte-identical mirror under `reference/python/src/`. Prevents PyPI builds that ship stale code. | **Yes** |
| 4. **Edit reminder** | `.claude/hooks/remind_doc_sync.sh` | PostToolUse on Edit/Write: after editing a `.py`/`.ts` file, outputs which MDs to check based on the file's location | No (reminder only) |

```bash
python scripts/check_docs_drift.py    # exit 0 = clean, 1 = drift
python scripts/check_sync_coverage.py # exit 0 = clean, 1 = sync gaps
python scripts/check_mirror_drift.py  # exit 0 = clean, 1 = packages/↔reference/ divergence
```

**This is the single authoritative doc-sync contract.** All other references in this file defer to this section.

### 3. Debugging Discipline: Structural & Conceptual Root-Cause Analysis

Debugging in AWP is not string-matching on stack traces. It is **systems pathology**: you read the symptom, then you diagnose the disease in the system's structure. The disease is almost always at a **layer boundary, a contract violation, an invariant leak, or a state-model mismatch** — not at the line that threw the exception.

**The 5-Why-by-Layer protocol** applies to every non-trivial bug — and is **mandatory for every E2E failure**:

1. **Symptom** — What failed? (exact error, log line, failed gate, rejected completion, missing artifact).
2. **Mechanism** — Which code path produced the symptom? Which function, which branch, which state transition?
3. **Contract** — Which AWP contract did the mechanism violate? Agent output shape (R17)? Budget envelope? Gate chain ordering? State `share_output` propagation? Layer isolation?
4. **Structural origin** — Which layer is this really in (manifest, identity, capabilities, communication, memory, orchestration, observability)? Is the bug *in* that layer, or is it a **leak across a layer boundary**? A bug that seems to be in the runner is often really in the model or the contract.
5. **Conceptual origin** — Which AWP concept is being violated or misapplied? Autonomy spectrum (is A2 code doing A1 things or vice versa)? Manager/worker split? Completion-gate semantics? Critique loop assumptions? Deterministic-before-LLM ordering?

Only after you can articulate the answer at layers 4 and 5 do you have a **root cause**. A fix that patches layer 2 without a story at layers 3–5 is a **symptom patch** and is rejected — it will re-emerge in a different guise within a few iterations of the loop.

**Symptom patches are forbidden.** Concrete anti-patterns:

| Anti-pattern | Why it's wrong | What to do instead |
|---|---|---|
| Adding a `try/except` around the failing call to "make it robust" | Hides the contract violation and lets corrupted state flow downstream | Find the caller that violates the input contract; fix at the contract boundary |
| Widening a regex / prompt / threshold until the test passes | Treats the test as the spec; the real spec is the AWP contract | Ask what the gate/rule is *supposed* to assert, then honor it |
| Adding a retry loop around a flaky step | Normalizes non-determinism into the system | Trace the non-determinism to its source (LLM format drift, race, unordered iteration) and remove it there |
| Hardcoding a value that "just works" for this run | Freezes one symptom; breaks for the next input | Derive the value from the contract (budget, rule, model field) that should produce it |
| Skipping a failing test with `@pytest.mark.skip` or `xfail` | Converts a loss signal into silence | Fix the root cause; if the test is wrong, fix the test *with* a justification |
| Patching the UI/log to not show the error | The error is still there, just invisible | Treat the surface as a read-only view of reality; fix reality |
| "It only fails intermittently, probably the LLM" | Abdicates the pathologist role | Capture the failing prompt+response, diagnose which contract the model output violates, fix the contract enforcement |

**E2E debugging specifically** — E2E failures are the highest-signal loss, and the most expensive to reproduce. Never waste one on a symptom patch:

1. **Capture the full artifact set** before touching anything: `run_completion.json`, `events.jsonl`, the output folder, the experiment DB row, the LLM transcripts. These are the evidence; a second run may not reproduce identically.
2. **Classify the failure**: did it terminate `failed` / `partial` / `aborted`? Did a gate reject? Did a budget fire? Did the manager plan-loop? Each class has a different layer-of-origin.
3. **Walk the 5 whys to layers 4–5.** An E2E that ends `partial` with reason `max_rejected_completions` is not a "LLM was bad" bug — it is a contract-enforcement story between the manager's completion decision, the gate chain, and the repair-subtask derivation. Diagnose *that*.
4. **Write the fix so it would also prevent the sibling bugs** at the same structural origin. If the cause is "the completion-gate chain rejects but the manager never sees the reason", the fix is not one extra field — it is the general repair-nudge contract.
5. **Add the regression test at the layer of the root cause**, not the layer of the symptom. A runtime bug diagnosed as a model-contract violation gets a unit test on the model, not an E2E re-run.

**Green does not mean correct.** A passing gate is evidence the *gate* is satisfied — not that the system is healthy. If you cannot tell the causal story from symptom → structural origin → fix, the bug is not understood and not fixed, no matter what the test runner reports.

## Working Principles (from usage report 2026-04)

These rules come from analyzing recurring frictions in past AWP sessions. They are aligned with the AWP philosophy of **deterministic validation before LLM-based work**, **budget-bounded autonomy**, and **conceptual clarity over local fixes**:

- **Mermaid → SVG, never inline code blocks.** All diagrams in docs must be generated as standalone SVG files for GitHub rendering. **No `feDropShadow` filters** (they break GitHub's SVG sanitizer).
- **English only.** All docs, diagrams, READMEs, comments, and artifacts are English. Never produce German content in committed files. (German is only allowed in chat replies to the user.)
- **After every multi-file change**: run the full test suite **and** verify environment sync — `packages/` ↔ `reference/python/src/` mirror, venv packages, model config. Don't declare done until both are green.
- **Schema validation is the first step** when generating or editing any `*.awp.yaml` — validate before doing anything else with the file.
- **Confirm assumptions before sweeping changes.** For any change touching >50 files or restructuring a package, state the assumptions explicitly and get a go signal first. This is the human-in-the-loop equivalent of an A2 manager validation gate.
- **Required env vars belong in `CLAUDE.md`.** If a code path needs an env var (API key, model, path), document it here so future sessions don't stall on missing config.
- **Delegate big releases.** Edits >500 lines and full PyPI release pipelines go to a general-purpose subagent, not the main loop.

These are not stylistic preferences — they are loss-reducing constraints. Treat a violation the same as a failed E2E test: find the root cause, fix it production-ready, do not paper over it.

## Project Overview

Agent Workflow Protocol (AWP) is an open standard for defining and orchestrating multi-agent workflows. It separates workflow definition (YAML) from implementation (Python), organized in 7 semantic layers (manifest, identity, capabilities, communication, memory, orchestration, observability) spanning an autonomy spectrum from A0 (prescribed DAG) to A4 (self-organizing recursive delegation).

## Development Commands

```bash
# Install (both packages, editable)
pip install -e packages/awp-core/
pip install -e "packages/awp-runtime/[data]"

# Lint and format
ruff check .
ruff format .

# Run all tests
pytest packages/awp-core/tests/ packages/awp-runtime/tests/

# Run core tests only (models, parser, validator)
pytest packages/awp-core/tests/

# Run runtime tests only (no E2E)
pytest packages/awp-runtime/tests/ -k "not e2e"

# Run a specific test
pytest packages/awp-core/tests/test_validator.py::test_function_name -v

# CLI commands (after install)
awp validate <path>              # Validate workflow (rules R1-R32)
awp compliance <path> --level A2 # Check autonomy level (A0-A4)
awp visualize <path> --format mermaid  # Render DAG
awp pack <path>                  # Archive as .awp.zip
awp run <path>                   # Execute workflow
```

E2E tests that call LLMs require an OpenRouter or OpenAI-compatible API key. Validation-only tests run without external keys.

## Architecture

### Two PyPI Packages

The Python code lives in `packages/` as two independent, publishable packages:

- **`awp-core`** (`packages/awp-core/src/awp/`) — Protocol layer: models, parser, validator, CLI
- **`awp-runtime`** (`packages/awp-runtime/src/awp/`) — Execution layer: engines, LLM, tools, data API

`awp-runtime` depends on `awp-core`. Both share the `awp.*` namespace.

### Two Orchestration Engines

- **DAG Engine** (`packages/awp-runtime/src/awp/runtime/runner.py`): Topological execution for A0-A1 workflows. Agents run in dependency order with state sharing via `share_output`.
- **Delegation Loop Engine** (`packages/awp-runtime/src/awp/runtime/delegation_loop_runner.py`): Manager-worker loop for A2-A4 workflows. Manager dispatches tasks to ephemeral workers with budget enforcement and validation gates.

### awp-core Source Layout (`packages/awp-core/src/awp/`)

- `models/` — Pydantic models for all 7 layers (manifest, agent, orchestration, capabilities, communication, memory, security, observability, evaluation)
- `parser/` — Parses `workflow.awp.yaml` and `agent.awp.yaml` into Pydantic models, resolves imports
- `validator/` — Rule engine (R1-R32) covering naming, graph structure, confidence, tool namespaces, budgets, evaluation. Key file: `rules.py`
- `agent.py` — Abstract `AWPAgent` interface: agents must return `{self.name: {result_dict}}` with a `confidence` float (R17)
- `cli.py` — CLI entry point (`awp` command)

### awp-runtime Source Layout (`packages/awp-runtime/src/awp/`)

- `runtime/` — Execution engines, `StandaloneAgent` base class, `LLMClient`, `ToolRegistry`, code executors (Docker, venv), evaluation engine, critique engine
- `data/` — Programmatic API (`AgentWorkflow`) for running workflows from Python

### Key Protocols

- **Agent output contract**: Every agent `run()` must return `{self.name: {"confidence": 0.0-1.0, ...}}`. This is validation rule R17.
- **State sharing**: DAG nodes declare `share_output` fields; downstream agents receive them in the `state` dict.
- **Budget system** (A2+): Hard limits (`max_loops`, `max_total_workers`, `max_total_tokens`, `max_wall_time`, `max_depth`, `max_workers_per_iteration`, `max_rejected_completions`) enforce termination. Manager cannot override the safety envelope. `max_workers_per_iteration` (default **6**) is a pre-spawn fan-out cap: if the manager requests more workers in a single DELEGATE decision than the cap allows, the runner trims the dispatch list and writes a `_deferred_workers` feedback into state so the manager must merge or defer in later iterations. `max_rejected_completions` (default **2**) is the completion-retry circuit breaker (Fix C): after N consecutive rejections of a manager COMPLETE decision by the completion-gate chain (`deliverable_presence`, `placeholder`, `file`, `structural_integrity`, `critique`, `eval`), the runner either synthesizes a targeted repair subtask (forcing DELEGATE next iteration) or — if no repair can be derived — terminates with reason `max_rejected_completions` and status `partial`. The counter resets on any successful DELEGATE.
- **Completion gate chain** (A2+): Every manager COMPLETE decision passes through a deterministic gate chain before the run ends. In order: `critique` (mean-score threshold) → `deliverable_presence` (every declared output path exists and is non-empty; derived from subtask `required_outputs` or `success_criteria` regex) → `placeholder` (no `TODO`/`XX%`/`???` strings in deliverables) → `file` (no broken 1×1 PNGs / empty PDFs) → `deliverable` (legacy keyword-based check) → `structural_integrity` (markdown anchor adjacency, reference-format consistency, paragraph-duplication) → `eval` (evaluation layer score). A rejection by any gate bumps `_rejected_completions` and loops back to the manager with a textual repair nudge. Successful DELEGATE resets the counter.
- **Plan-loop deterministic transition** (Fix D): when the manager issues N consecutive PLANs without any worker progress (default N=2 in strict mode, N=3 in relaxed), the `plan_loop` gate fires and picks one of two deterministic transitions — `forced_delegate` (pending subtasks exist → lock plan and force DELEGATE next iteration) or `forced_terminate` (no pending subtasks → partial exit with reason `plan_loop_stall`). Both transitions emit a structured `plan_loop` gate event with `transition: "forced_delegate" | "forced_terminate"`.
- **Terminal status contract** (Fix H): every run ends with exactly one of `{complete, partial, failed, aborted}`. Cap/limit-forced exits (`defect_category_cap`, `plan_loop`, `max_total_tokens`, `max_total_workers`, `max_wall_time`, `max_loops`, `forced_convergence`, etc.) map to `partial` — never `complete`. Hard evaluation/execution failures map to `failed`. Process exits without a terminal decision (SIGTERM/SIGINT or kill) map to `aborted`. The helper `_finalize_terminal_status(reason)` in `packages/awp-runtime/src/awp/runtime/delegation_loop_runner.py` is the single source of truth.
- **Finalizer guarantee** (Fix E): the delegation-loop runner wraps its main loop in a try/except/finally block and registers `SIGTERM`/`SIGINT` handlers so `run_completion.json` (and the `run.complete` WebSocket event) is emitted on every exit path — including abrupt signal-driven termination. The runner_service canonicalizes the status to one of the four terminal states and attaches a `reason` field. Orphan runs detected on server restart (no live PID) are marked `aborted` with reason `process_exit_without_terminal_event`.
- **Manager context guard**: Before every manager LLM call, the combined system + user prompt is estimated (char-based, ≈4 chars/token). If the estimate exceeds `manager_context_compress_threshold` (default **0.8**) of `manager_context_budget_tokens` (default **150_000**), the user message is deterministically compressed — the `Previous Results Summary`, `Worker Results Available in State`, and `Files Currently in Output Directory` sections are collapsed to one-line entries; if still over, a head/tail retention with middle elision targets ≤60% of the budget. Gate-feedback sections (rejections, repair instructions) are never compressed. The firing is logged as `context_guard` gate event with original and compressed token estimates. Implemented in `_guard_manager_context` in `packages/awp-runtime/src/awp/runtime/delegation_loop_runner.py`.
- **Validation tiers**: Deterministic validation (schema, rules R1-R32) runs always; LLM-based semantic validation is optional (skipped when confidence exceeds threshold).
- **Evaluation layer**: Optional quality scoring (5 metric kinds, weighted aggregation, threshold-based retry/repair). Configured under `observability.evaluation`.
- **Critique loop**: Optional reflective critique within delegation loop (defect diagnosis, targeted repair, cross-worker pattern memory). Configured under `delegation_loop.critique`.

### Other Key Directories

- `spec/` — Normative specification (RFC 2119 language)
- `docs/` — Protocol documentation for each layer
- `examples/` — 18 runnable examples progressing A0→A4 (including evaluation, critique, and manager intelligence)
- `conformance/` — Test fixtures for spec compliance
- `schemas/` — JSON schemas
- `skill/` — AWP Skill for Claude Desktop (templates, adapters)

## Skill Synchronization (MANDATORY)

**The AWP Workflow Builder skill (`skill/SKILL.md`) MUST be updated whenever the runtime, models, or features change.** This skill generates new workflows — if it is outdated, every generated workflow will have the same bugs.

When you change any of the following, you MUST also update `skill/SKILL.md` and the relevant files in `skill/templates/`:

| Change | What to update in skill/ |
|--------|--------------------------|
| New runtime feature (e.g. `_workspace_dir`, `required_secrets`) | SKILL.md examples + templates |
| New/changed model fields (orchestration, capabilities, etc.) | SKILL.md config examples + workflow template |
| Changed defaults (token budget, timeouts, etc.) | SKILL.md reference values + templates |
| New/removed tools (`code.execute`, etc.) | SKILL.md tool reference + templates + adapters |
| Changed forbidden_tools or security policy | SKILL.md delegation loop section + templates |
| New validation rules (R1-R32+) | SKILL.md Phase 4 checklist |
| Changed delegation loop behavior | SKILL.md delegation loop section + Step 7d |
| New debug/observability features | SKILL.md relevant sections |

**Failure to sync causes cascading bugs**: generated workflows silently fail because they use outdated config patterns (e.g. `shell.execute` in `tools_allowed` when it's forbidden, `dynamic_tools.enabled: false` when tool creation is needed).

## E2E Tests (MANDATORY)

### Definition

An **E2E test** in AWP is a full run that exercises the entire system end-to-end:

1. Create a **new experiment** from scratch.
2. Give it a **fictional task** that forces coverage of:
   - **Orchestration** (DAG or delegation loop execution)
   - **Manager intelligence** (autonomous decision making, submanager promotion)
   - **Tool creation** (dynamic tool factory generates and validates new tools)
   - **Skill creation** (skills are produced and reused)
   - **Sub-manager delegation** (recursive manager-worker spawning)
3. The run **MUST pass the E2E rubric** (see below).

### E2E Pass Rubric (not a string match)

LLM outputs are variable by nature. A binary "output equals expected string" check turns every release into a flake hunt. Instead, an E2E run passes iff **all** of the following hold:

| Criterion | Check |
|---|---|
| **Terminal state** | Experiment reached state `complete` (not `failed`, not `running`, not `partial` unless explicitly expected) |
| **Artifacts present** | Output folder is populated with real, non-empty files matching the task's declared deliverables |
| **Budget respected** | Wall time, token count, and loop count stayed within the configured budgets (no runaway) |
| **Graph integrity** | Experiment graph renders in the UI, manager/worker/tool nodes are consistent with the run log |
| **Rubric score** | Optional LLM-judge or deterministic scorer gives ≥ threshold on task-specific quality criteria (e.g. "did the synthesized report cover all required sections") |

Exact string matching is allowed **only** for deterministic subcomponents (tool outputs, computed values). For synthesized/generated content, use the rubric, not equality.

### Storage and Observability

**E2E tests MUST be stored as real experiments in `/tmp/awp-experiments/`** so the UI can load and display them. Each E2E run must produce **real outputs, real artifacts, and a real graph visualization**, and the experiment's **output folder MUST be populated** (no empty runs, no placeholder files). Goal: I must be able to open any E2E test in the UI, look at its results, and view its graph. E2E tests that only run in pytest without leaving a populated experiment in `/tmp/awp-experiments/` are **not** valid.

**E2E tests MUST register the running experiment in the experiment database BEFORE the run starts** — not only after it finishes. The experiment record (id, title, status=`running`, created_at, task) must be inserted up-front via the same code path the UI uses (`AgentWorkflow` / experiment service / DB insert), so the experiment appears immediately in the UI sidebar list. Status must transition `running → complete | partial | failed` live as the run progresses, and intermediate events (manager iterations, worker spawns, tool calls) must be persisted as they happen so I can **follow the run in the UI in real time** while it executes. An E2E test that only registers the experiment after termination — making it invisible in the sidebar during execution — is **not** valid.

**E2E tests MUST always run against real LLM calls** (e.g. OpenRouter / OpenAI / Anthropic). Mocked, stubbed, or recorded LLM responses are **not** valid E2E coverage — the whole point is to verify behavior under real model output variability.

### Tags & Live Monitoring (MANDATORY)

Every E2E test **MUST** have one or more **tags**. Tags are passed to `run_e2e(tags=[...])` in `examples/e2e/_harness.py`. The `"e2e"` tag is added automatically; additional tags describe the test's focus areas.

**Required tag conventions:**

| Tag | When to use |
|---|---|
| `e2e` | Always (auto-added by harness) |
| `s5` | S5-level features (delegation, tool creation, critique, etc.) |
| `tool-creation` | Test exercises dynamic tool factory |
| `critique` | Test exercises critique loop |
| `sub-manager` | Test exercises recursive delegation / sub-managers |
| `memory` | Test exercises cross-run memory persistence |
| `planning` | Test exercises manager planning features |
| `quick` | Lightweight smoke test (≤5 loops, ≤1M tokens) |

**Live monitoring**: Every E2E run is tracked live in the UI. The E2E harness:

1. **Registers** the experiment (session + run) in the SQLite DB **before** starting, with `status=running`.
2. **Streams events** (iterations, worker spawns/completions, tool calls, budget updates, critique results) to the DB in real time via `_E2ERunDirWatcher`.
3. **Finalizes** status to `complete | partial | failed` when done.

To **watch an E2E test live** while it runs:

```bash
# Terminal 1: start the UI server
python packages/awp-ui/start_debug.py --skip-build --no-reload

# Terminal 2: run the E2E test
python examples/e2e/deep_research_tree.py
```

The experiment appears immediately in the sidebar with a pulsing "running" indicator. Click it to see the graph build up, workers spawn, tool calls execute, and budget decrease — all in real time.

**An E2E test without tags is not valid.** The tags serve as machine-readable metadata for filtering, reporting, and regression tracking.

Treat the run output as a **loss function** and the code fix as **backpropagation**: if the run fails or the output diverges from expectation, locate the root cause in the code and fix it. Iterate until the loss is zero. Always make fixes **production-ready** — no patches, no shortcuts, no "works on my machine".

The guiding question for every E2E run: **"Would this system reach `complete` for an arbitrary task?"** If the answer is no, it is not shippable.

### When to Run

**Before every PyPI build + push, an E2E test MUST be executed.** The test must additionally cover **all new features** introduced since the last commit pushed to GitHub. "New" = the diff between the last GitHub commit and the current working state. Identify the changed features, then design the E2E task so it exercises them in addition to the standard coverage above.

No PyPI publish may proceed until the E2E run reaches `complete` with the expected output.

In addition, **all other test suites MUST be green** before a PyPI build + push:

```bash
pytest packages/awp-core/tests/ packages/awp-runtime/tests/
```

A single failing or skipped-due-to-error test blocks the publish. Fix the root cause, do not disable or xfail tests to unblock a release.

## PyPI Build Rules (MANDATORY)

### Architecture: What Gets Published

Only **one package** is published to PyPI: **`awp-agents`** (built from `reference/python/`). It is a meta-package that bundles everything: core models, runtime, UI server, and the **pre-built frontend assets**. The `awp-core` and `awp-runtime` packages are NOT published separately — their code is vendored into `reference/python/src/`.

The PyPI token in `~/.pypirc` is scoped to `awp-agents` only.

### Source of Truth for Code

| Component | Developed in | Copied/mirrored to (for PyPI bundle) |
|-----------|-------------|--------------------------------------|
| Core (models, parser, validator) | `packages/awp-core/src/awp/` | `reference/python/src/awp/` (same namespace) |
| Runtime (engines, LLM, tools) | `packages/awp-runtime/src/awp/` | `reference/python/src/awp/` (same namespace) |
| UI server (FastAPI, routes) | `packages/awp-ui/server/` | `reference/python/src/server/` |
| **Frontend (Vite/React)** | `packages/awp-ui/frontend/` | `reference/python/src/server/frontend/dist/` |

**CRITICAL**: The frontend is a **built artifact**. The source lives in `packages/awp-ui/frontend/src/`, the build output goes to `packages/awp-ui/frontend/dist/`, and it must be **manually copied** to `reference/python/src/server/frontend/dist/` before building the PyPI package. If you skip this step, the published package ships with stale frontend assets.

### Full Build + Publish Sequence

Follow these steps **in exact order** every time you publish to PyPI:

```bash
# 0. Bump versions (see Version Sync Checklist below)

# 1. Rebuild the frontend
cd packages/awp-ui/frontend && npm run build

# 2. Copy fresh frontend build into the PyPI bundle source
rm -rf reference/python/src/server/frontend/dist/
cp -r packages/awp-ui/frontend/dist/ reference/python/src/server/frontend/dist/

# 3. Sync any changed Python files from packages/ → reference/python/src/
#    (prompts.py, workflow.py, delegation_loop_runner.py, routes.py, etc.)
#    Ensure reference/python/src/ mirrors the latest packages/ code.

# 4. Build the awp-agents wheel
cd reference/python && rm -rf dist/ build/ && python -m build

# 5. Verify the wheel contains new frontend assets
python -c "import zipfile, glob; z = zipfile.ZipFile(glob.glob('dist/*.whl')[0]); [print(f) for f in z.namelist() if 'frontend/dist/assets/index' in f]"
# → Should show the NEW hash-named index-*.js and index-*.css files

# 6. Upload to PyPI
twine upload dist/*

# 7. Smoke test from PyPI
pip install --no-cache-dir awp-agents==<NEW_VERSION>
awp studio
```

### Common Mistakes

- **Forgetting to rebuild frontend**: The most common error. If you only change frontend code but skip `npm run build` + copy, the PyPI package ships the old JS/CSS.
- **Forgetting to copy frontend to reference/python/**: Even after `npm run build`, the output is in `packages/awp-ui/frontend/dist/` — it does NOT automatically appear in `reference/python/src/server/frontend/dist/`.
- **Python file drift**: Changes to `packages/awp-runtime/src/` or `packages/awp-ui/server/` must also be reflected in `reference/python/src/`. These directories are **not symlinked** — they are independent copies.
- **Version already uploaded**: PyPI does not allow re-uploading the same version. If you uploaded a broken build, you must bump the version again.

### Version Sync Checklist

When bumping versions, update ALL of these in one commit:

| File | Field |
|------|-------|
| `packages/awp-core/pyproject.toml` | `version` |
| `packages/awp-runtime/pyproject.toml` | `version` + `awp-core>=` dependency |
| `packages/awp-ui/pyproject.toml` | `version` + `awp-core>=` and `awp-runtime>=` dependencies |
| `reference/python/pyproject.toml` | `version` (awp-agents meta-package) |

## Code Style

- Python 3.10+ with modern syntax (`X | Y` unions, `match` where appropriate)
- Type annotations on all public functions
- `snake_case` functions/modules, `PascalCase` classes, `UPPER_SNAKE_CASE` constants
- Use `logging` module, never `print()`
- Pydantic or dataclasses for structured data
- Conventional commits: `feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`

## Default Model & Provider Routing

- **Default manager model**: `openai/gpt-5-mini` (via OpenRouter)
- **Default worker model**: `deepseek/deepseek-chat-v3.1` (via OpenRouter)
- The UI uses a **free text input** for model selection — no dropdowns. Never add `<select>` dropdowns for model selection.
- Provider is auto-detected from the model string:

| Model string pattern | Routed to | Required API key |
|---|---|---|
| `provider/model-name` (e.g. `openai/gpt-5-mini`) | **OpenRouter** | `OPENROUTER_API_KEY` |
| `gpt-*`, `o1-*`, `o3*` | **OpenAI (direct)** | `OPENAI_API_KEY` |
| `claude-*` | **Anthropic (direct)** | `ANTHROPIC_API_KEY` |
| `ollama/*` | **Ollama (local)** | none |

- Backend routing logic lives in `packages/awp-ui/server/services/runner_service.py`
- Frontend routing display lives in `packages/awp-ui/frontend/src/components/Settings/SettingsPanel.tsx` (`detectProvider()`)
- Default model must be consistent across: `workflowStore.ts` (`DEFAULT_CONFIG`), `routes.py` (`_default_settings`), and `SettingsPanel.tsx` (placeholder)

## Security — API Keys

- **NEVER commit real API keys, tokens, or secrets to the repository.**
- Before every push, scan for leaked keys: `grep -rn 'sk-or-v1-[a-f0-9]\{20,\}' . --include='*.py' --include='*.ipynb' --include='*.md' --include='*.yaml'`
- Use placeholder patterns in examples and notebooks: `"sk-or-v1-..."`, `"your-api-key-here"`, or `os.getenv("OPENROUTER_API_KEY", "")`
- Notebooks must read keys from environment variables, never hardcode them in cells
- If a key is accidentally committed, rotate it immediately and force-push a clean history

## Language Policy

- **All documentation (.md files), code comments, docstrings, commit messages, and YAML descriptions MUST be in English.**
- No German (or other non-English) text in any committed file. Variable names in code examples within docs should also be English.
- This applies to: README.md, README_NERD.md, docs/, examples/, skill/, spec/, CLAUDE.md, inline comments, and docstrings.


## LLM Integration

- When editing code that involves LLM response parsing, always validate for non-JSON responses, malformed output, and add fallback/retry logic. Never assume LLM outputs will be well-formed.

## Testing

- After making code fixes, verify that existing functionality still works — run the relevant test suite before committing. Do not assume a fix is isolated; check for regressions.

## File Formats

- When generating or editing YAML files, always validate against the expected schema before considering the task done. Pay attention to: frontmatter format, required fields, field types (especially enums like persistence type, state.sharing format).

## Development Server

- Always kill any server processes you start (FastAPI, Vite, etc.) before starting new ones. Check for port conflicts with `lsof -i :<port>` before launching servers.

## Code Changes

- When implementing multi-file changes, do a dry-run validation pass after all edits: check imports resolve, function signatures match callers, and config references exist. Do not wait for runtime errors.

## Documentation Consistency

See **§2 "Doc Sync as Definition-of-Done"** for the full contract, sync table, and enforcement gates.
