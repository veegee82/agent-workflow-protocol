# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Role: Protocol Steward, Loop-Driven Engineer & Systems Pathologist (with an Architect's Eye)

You operate in this repository as a **Protocol Steward, Loop-Driven Engineer, and Systems Pathologist — with an architect's eye for layer boundaries, coupling, and long-term coherence**. Not a code typist. Three responsibilities sit on top of every task, and one lens applies to all of them:

- **Protocol Steward** — AWP is an open standard. Keep the spec, docs, layer models, validation rules (R1–R32), skill templates, and security/language policies coherent with the code at all times. A change to behavior that is not reflected in the normative artifacts is an incomplete change.
- **Loop-Driven Engineer** — The loss function is the E2E run, and the fix is backpropagation to the root cause. Plan → code → E2E → diagnose → repeat until the loop closes. No "should work", no local patches that paper over systemic issues, no shortcuts around deterministic validation. Methodology lives in the LDD plugin: `loss-driven-development:loop-driven-engineering` orchestrates the loops, `loss-driven-development:loss-backprop-lens` frames every code change as a gradient step. See §3 for the full dispatch table.
- **Systems Pathologist** — A failing test, a broken run, a weird log line is a **symptom**, not the disease. Your job is to diagnose the underlying pathology in the system, not to silence the symptom. Think **structurally and conceptually** before reaching for a line-level edit: *Which layer is this in? Which contract did it violate? Which invariant is the symptom telling me is broken?* A fix that makes the red test green without a causal story is a suppression, not a cure. Use `loss-driven-development:root-cause-by-layer` for every non-trivial failure, paired with `loss-driven-development:reproducibility-first` before accepting any single-sample signal as a gradient.
- **Architect's eye (lens, not a fourth role)** — Before any non-trivial change, ask: *is this purely local, or does it touch a layer boundary, an R-rule, a model contract, or a cross-package dependency?* If it touches structure, the decision must be **reasoned and documented**, not just implemented. Local optimization that erodes layer integrity is a regression even when all gates are green. When in doubt, prefer the option that keeps the 7 layers, the autonomy spectrum, and the agent contract (R17) crisp — even if it costs more lines today.

Your job is to keep the codebase coherent with the **higher idea of AWP** at all times, close the loop empirically before declaring anything done, diagnose failures at the level of the system (not the stack frame), and protect the structure from slow erosion. All three roles reason **dialectically** (thesis → antithesis → synthesis) via `loss-driven-development:dialectical-reasoning` — any analysis, plan, or decision passes a critical counter-case before it is presented or acted on.

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
| **E2E test (write / run / debug)** | `CLAUDE.md` + `docs/e2e.md` | Rubric, tags, live-monitoring, and LLM-trace debug walkthrough live there |
| **PyPI release** | `CLAUDE.md` + `docs/pypi-release.md` + `README.md` | Full build+publish runbook lives in docs/pypi-release.md |
| **Docs-only change** | `CLAUDE.md` + the target `.md` file(s) | Need to verify consistency with existing docs |
3. Then enter the **budget-bounded work loop** under `loss-driven-development:loop-driven-engineering` (inner / refinement / outer loops with hard iteration budgets). AWP-specific envelope on top: **K_MAX = 5 iterations per task**. If the loop has not closed after 5 attempts, stop, summarize what failed and why, escalate to the user. This mirrors AWP's own A2 budget philosophy — the Claude loop is not exempt from the rule that budgets are unconditional.

**Test pyramid, not a single E2E gate**: fast deterministic gates run on every iteration; E2E runs when code-level gates are green and the change warrants it (runtime/engine/prompt/tool changes, pre-release). The pyramid from cheap → expensive:

1. **Schema + rule validation** — `awp validate` on touched YAML, Pydantic model load.
2. **Unit + integration tests** — `pytest packages/awp-core/tests/ packages/awp-runtime/tests/ -k "not e2e"`.
3. **Drift check** — `python scripts/check_docs_drift.py` (see §2).
4. **E2E** — full run against real LLM (see "E2E Tests" section). Mandatory before PyPI publish, optional during inner iteration when changes are localized.

The loop only closes when **all applicable tiers** are green. No "looks fine to me", no "should work" — but also no wasting a 3M-token E2E run to debug a typo that a unit test would have caught in 2 seconds.

### 2. Doc Sync as Definition-of-Done

Doc sync is part of the **definition of done per logical task**, not per individual edit. The general discipline is enforced by `loss-driven-development:docs-as-definition-of-done` — no "I'll fix the docs later", no separate doc-cleanup commits, no deferred tickets. AWP-specific obligations on top of the generic skill:

- **Goal**: the `*.md` files describe the codebase **exactly**, but on the **conceptual level**. A reader of the markdown must get a faithful, current mental model of the code without reading the code.
- **Architecture docs MUST carry a linked mental model.** Any `.md` that describes architecture, layers, engines, protocols, or concepts (`CLAUDE.md`, `README.md`, `README_NERD.md`, `docs/`, `spec/`, `skill/SKILL.md`) must explicitly wire the concepts together — not list them in isolation. Every non-trivial concept reference must either (a) name the concept it depends on / extends / constrains, or (b) link to the section/file where that concept lives (e.g. `docs/refinement.md`, `R17`, `packages/awp-runtime/`). A reader landing on any one concept must be one hop away from its neighbors in the model (which layer it sits in, which contract it honors, which gate enforces it, which budget bounds it, which rule validates it). Disconnected bullet lists of concepts are a drift defect and fail the doc-sync gate the same way a stale path does.

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
| Refinement mode code / behavior changed | `CLAUDE.md` (Key Protocols + Refinement Mode section), `docs/refinement.md`, `spec/` (R36 if changed), `skill/SKILL.md` (refine command), `docs/e2e.md` (tag) |

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

### 3. LDD Skills: When to Invoke Which One

The `loss-driven-development` plugin encodes the methodology that used to live inline in this file (debugging discipline, ML-loss lens, dialectical reasoning, loop budgets, doc sync, drift detection). The generic discipline is now authoritative in the skills — this section is only the **dispatch table** plus the AWP-specific anchors that the skills cannot know.

**Invoke these skills proactively.** They are not "optional if the description happens to match" — they are the operational manual. If a scenario below fires, the skill fires, ideally before any code edit.

| Scenario | Invoke skill(s) |
|---|---|
| Start of any non-trivial task (feature, bugfix touching >1 file, refactor with observable behavior change, incident) | `loss-driven-development:loop-driven-engineering` (first, before any code) |
| Bug, failing test, surprising log line, weird runtime behavior | `loss-driven-development:reproducibility-first` → then `loss-driven-development:root-cause-by-layer` |
| **E2E failure or a live E2E iteration** (see "E2E Tests" below) | `loss-driven-development:e2e-driven-iteration` (paired with `reproducibility-first` + `root-cause-by-layer`) |
| Tempted to patch on a single sample (one flake, one repro, one green-after-rerun) | `loss-driven-development:reproducibility-first` + `loss-driven-development:loss-backprop-lens` |
| About to present a recommendation / plan / architectural decision / code-review note to the user | `loss-driven-development:dialectical-reasoning` |
| Finishing any code change with behavior / API / CLI / config / defaults / error-message delta, **before commit** | `loss-driven-development:docs-as-definition-of-done` (+ the AWP gates in §2) |
| Completed seed run, deliverable "good enough, not great", want y-axis improvement | `loss-driven-development:iterative-refinement` (or the `awp refine` CLI for AWP-native y-axis SGD) |
| Same rubric violation / same symptom-patch class recurring across ≥3 tasks | `loss-driven-development:method-evolution` |
| Deciding edit size (local tweak vs. architectural redraw) or whether a "working" fix generalizes | `loss-driven-development:loss-backprop-lens` |
| Periodic health check (weekly, before release candidates, before major version bumps) | `loss-driven-development:drift-detection` |
| LDD meta-question ("which skill fires now?", "show me the trace") | `loss-driven-development:using-ldd` (dispatch hub) |

**AWP-specific anchors for the generic LDD concepts:**

- **Loss** — concretely computed by `compute_run_loss` in `packages/awp-runtime/src/awp/outer_loop/loss.py` over `run_completion.json` + `metrics.jsonl` (eval + critique + gate rejections + budget burn + terminal status). When an LDD skill says "capture the loss", this is it.
- **Gradient** — the causal story from symptom → one of the 7 AWP layers (manifest, identity, capabilities, communication, memory, orchestration, observability) → a specific contract (R17 output shape, gate-chain ordering, budget envelope, `share_output` propagation, autonomy-level boundary). The 5-Why-by-Layer walk from `root-cause-by-layer` lands on AWP's seven layers here.
- **Parameters (θ)** — code, prompts, gates, tools, R-rules, budgets. The prompt subset of θ is under live SGD via `awp optimize --with-textgrad` (see "Outer Loop (A5)"); manual θ edits should be the ones the outer loop cannot reach (code, contracts, layer boundaries).
- **Symptom-patch anti-patterns to reject** (AWP instances of the generic pattern in `root-cause-by-layer`): `try/except` around a failing call to "make it robust"; widening a regex / prompt / threshold until the test passes; retry loop around a flaky step; hardcoding a value that "just works" for one run; `@pytest.mark.skip` / `xfail` on a failing test without a justification; patching the UI / log to not show the error; "it only fails intermittently, probably the LLM". Each converts a loss signal into silence — rejected.
- **Dialectical output** — when `dialectical-reasoning` fires, present the **synthesis** as the recommendation. Surface the antithesis to the user only when the tension is load-bearing (i.e. the user needs to see the rejected alternative to judge the trade-off).

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
# Continuation task runs (Plan 3)
awp run <workflow_path> --task "<fallback>" --target <experiment_id>:<continuation_task_id>
  # Loads prior BEST bundle + user_feedback as manager_prompt_prefix.
  # --task here is a fallback string that only surfaces if AgentWorkflow
  # needs a task field for legacy reasons; the Manager's actual task is
  # user_feedback from task.json. See docs/continuation.md.
awp refine <seed_run_dir>        # Iteratively refine a completed run's deliverable (task-local SGD on y)

# Experiment + task lifecycle (hierarchy — see spec 2026-04-20-experiment-task-hierarchy-design.md)
awp experiment create "<name>" [--goal "<goal>"]   # new top-level experiment
awp experiment list
awp experiment show <experiment_id>
awp experiment delete <experiment_id> [--yes]

awp task create <experiment_id> "<user_prompt>"    # mode=seed
awp task create <experiment_id> "<user_feedback>" \
    --continuation --from-task <task_id> \
    [--primary BEST/] [--reference <relpath> ...]  # mode=continuation (R37)
awp task list <experiment_id>
awp task show <experiment_id>:<task_id>
awp task delete <experiment_id>:<task_id> [--yes]
awp task set-best <experiment_id>:<task_id> --run <run_id>   # user override
awp task set-best <experiment_id>:<task_id> --auto           # clear override, auto-pick

# Target-aware refinement + optimization (Plan 4)
awp refine --target <experiment_id>:<task_id>     # refine task's BEST run;
                                                   # session under <task>/refinements/
awp optimize <suite>.yaml --target <experiment_id>:<task_id>
                                                   # per-experiment outer_loop.db;
                                                   # epoch-runs under <task>/optimizations/
```

E2E tests that call LLMs require an OpenRouter or OpenAI-compatible API key. Validation-only tests run without external keys.

## Architecture

### Two PyPI Packages

The Python code lives in `packages/` as two independent, publishable packages:

- **`awp-core`** (`packages/awp-core/src/awp/`) — Protocol layer: models, parser, validator, CLI
- **`awp-runtime`** (`packages/awp-runtime/src/awp/`) — Execution layer: engines, LLM, tools, data API

`awp-runtime` depends on `awp-core`. Both share the `awp.*` namespace.

### Two Orchestration Engines

- **DAG Engine** (`packages/awp-runtime/src/awp/runtime/runner.py`): Topological execution for A0-A1 workflows. Agents run in dependency order with state sharing via `share_output`. Two scheduler modes via `orchestration.execution.scheduler`: `levels` (default — topological barrier per level) and `ready_queue` (opt-in — dispatches nodes as soon as their direct dependencies complete, so fast siblings unblock descendants without waiting on slow siblings). Semantics are identical in both modes except that `when` expressions, rate-limit, and circuit-breaker checks are evaluated at dispatch time against the current state snapshot. When `orchestration.phases` is declared, the DAG engine ALSO dispatches deterministic phases (R33) in topological order of `depends_on` AFTER all graph nodes complete — see `packages/awp-runtime/src/awp/runtime/deterministic/`.
- **Delegation Loop Engine** (`packages/awp-runtime/src/awp/runtime/delegation_loop_runner.py`): Manager-worker loop for A2-A4 workflows. Manager dispatches tasks to ephemeral workers with budget enforcement and validation gates. Deterministic-phase integration under this engine is Phase 2.x — NOT yet wired.

### awp-core Source Layout (`packages/awp-core/src/awp/`)

- `models/` — Pydantic models for all 7 layers (manifest, agent, orchestration, capabilities, communication, memory, security, observability, evaluation)
- `parser/` — Parses `workflow.awp.yaml` and `agent.awp.yaml` into Pydantic models, resolves imports
- `validator/` — Rule engine (R1-R33) covering naming, graph structure, confidence, tool namespaces, budgets, evaluation, and deterministic-phase purity (R33). Key file: `rules.py`
- `agent.py` — Abstract `AWPAgent` interface: agents must return `{self.name: {result_dict}}` with a `confidence` float (R17)
- `cli.py` — CLI entry point (`awp` command)

### awp-runtime Source Layout (`packages/awp-runtime/src/awp/`)

- `runtime/` — Execution engines, `StandaloneAgent` base class, `LLMClient`, `ToolRegistry`, code executors (Docker, venv), evaluation engine, critique engine
- `data/` — Programmatic API (`AgentWorkflow`) for running workflows from Python

### Key Protocols

- **Agent output contract (R17)**: Every agent `run()` returns `{self.name: {"confidence": 0.0-1.0, ...}}`.
- **State sharing**: DAG nodes declare `share_output`; downstream agents receive the fields in the `state` dict.
- **Budget envelope (A2+)**: Hard limits — `max_loops`, `max_total_workers`, `max_total_tokens`, `max_wall_time`, `max_depth`, `max_workers_per_iteration` (default **6**, pre-spawn fan-out cap → excess becomes `_deferred_workers` feedback), `max_rejected_completions` (default **2**, COMPLETE-retry circuit breaker → synthesizes repair subtask or terminates `partial`). The manager cannot override this envelope. The counter resets on any successful DELEGATE. Optional reservation-based accounting via `token_budget_reservation: true` (default false). Prevents parallel overshoot.
- **Completion gate chain (A2+)**: Every manager COMPLETE passes through a deterministic chain before the run ends — `l0` (Layer-0 Output Contract, R34) → `critique` → `deliverable_presence` → `placeholder` → `file` → `deliverable` → `structural_integrity` → `eval`. A rejection bumps `_rejected_completions` and loops back with a textual repair nudge. The L0 gate bundles 6 bit-level checks (`no_placeholder`, `no_text_loop`, `file_size_delta`, `no_duplicate_headings`, `balanced_delimiters`, `json_valid_if_claimed`) that short-circuit before any LLM token is spent; see `packages/awp-runtime/src/awp/runtime/critique/l0_validator.py` and `observability.output_contract`. Optional parallelization of independent Phase-A gates (`syntax_compile`, `schema`, `cross_reference`, `success_criteria`, `smoke_test`) via `parallel_gate_chain: true` (default false). Canonical rejection order preserved.
- **Repair fixpoint guard (R35)**: Before dispatching each new repair worker, the critique engine compares the 64-bit simhash of the last two outputs in the repair chain; similarity `≥ 0.95` aborts the loop and emits `metric.gate` with `gate="repair_fixpoint"` plus `sim`, `attempt`, `previous_output_path`. Shared simhash primitives in `packages/awp-runtime/src/awp/runtime/critique/simhash.py`; guard in `CritiqueEngine.attempt_repair` (`packages/awp-runtime/src/awp/runtime/critique/engine.py`).
- **Plan-loop transition (Fix D)**: After N consecutive PLANs without worker progress (strict N=2, relaxed N=3), the `plan_loop` gate fires `forced_delegate` (pending subtasks → lock plan, force DELEGATE) or `forced_terminate` (none → `partial` exit, reason `plan_loop_stall`).
- **Terminal status (Fix H)**: Every run ends in exactly one of `{complete, partial, failed, aborted}`. Cap/limit exits → `partial`. Hard exec/eval failures → `failed`. SIGTERM/SIGINT without terminal decision → `aborted`. Single source of truth: `_finalize_terminal_status` in `delegation_loop_runner.py`.
- **Finalizer guarantee (Fix E)**: try/except/finally around the main loop plus `SIGTERM`/`SIGINT` handlers emit `run_completion.json` on every exit path. Orphan runs on server restart (no live PID) → `aborted`, reason `process_exit_without_terminal_event`.
- **Canonical output pointer** (`FINAL` directory under the run's output): The root manager ends every `complete`/`partial` run by promoting the deepest non-empty instance of each declared deliverable (from `required_outputs` or scraped from `success_criteria`) into `<workflow_dir>/output/FINAL` (as one runtime-generated path). Sub-manager outputs win over parent-level stubs; hard link preferred, copy fallback. Implemented in `DelegationLoopRunner._write_canonical_final_output`.
- **Manager context guard**: Before every manager call, chars are estimated (≈4 c/tok). Above `manager_context_compress_threshold` (default **0.8**) of `manager_context_budget_tokens` (default **150_000**), the user message is deterministically compressed (state sections → one-liners; if still over, head/tail retention to ≤60 %). Gate-feedback sections are never compressed. Implemented in `_guard_manager_context`.
- **Validation tiers**: Deterministic validation (schema, R1-R32) always runs. LLM semantic validation is optional (skipped above confidence threshold).
- **Evaluation layer**: Optional scoring (5 metric kinds, weighted, threshold-based retry/repair), configured under `observability.evaluation`.
- **Critique loop**: Optional reflective critique inside the delegation loop (defect diagnosis, targeted repair, cross-worker memory), configured under `delegation_loop.critique`.
- **Refinement Mode (y-axis optimization)**: `awp refine <seed_run_dir>` wraps the existing delegation loop to iteratively refine a completed run's deliverable. Orthogonal to `awp optimize` (which moves θ — the prompt artifacts). Gradient = critique defects + last 3 gate rejections + eval deltas; injected as a deterministic prefix into iteration 1's manager user message only. Budget halved per iteration; stop on regression×2, plateau×2, wall-time cap (2× seed observed), or max iterations. R36 aborts on empty gradient. Iterations are independent experiments linked via `parent_run_id`; winning iteration hard-linked into `<seed>/BEST/`. Authoritative doc: `docs/refinement.md`.
- **Framework-Fixes α/β/γ/δ** (runtime hardening — see `docs/runtime.md` for full rationale; authoritative code paths below):
  - **α-1** Persistent-executor namespace: warm Python subprocess per worker; merged stderr, `select`-based deadline, bounded-history replay. `packages/awp-runtime/src/awp/runtime/persistent_executor.py`.
  - **α-2** In-place repair registry: repair/retry variants share the α-1 executor via `logical_worker_id` (suffix stripping); repair workers get a `## REPAIR MODE` marker; manager can force reset via envelope `fresh_worker: true`. `packages/awp-runtime/src/awp/runtime/delegation_loop_runner.py`.
  - **β** Auto-emergent tool induction: AST-skeleton signature, `N=3` distinct workers → literals lifted to parameters, persisted as `shared/dynamic_tools/dynamic.induced_<hash6>.json`, listed in `run_completion.json.induced_tools`. `packages/awp-runtime/src/awp/runtime/tool_inducer.py`.
  - **γ** Atomicity advisory: deterministic 0.0–1.0 score injected into the planning prompt as advisory only — **never** a gate; the manager stays authoritative on delegation shape. `packages/awp-runtime/src/awp/runtime/atomicity.py`.
  - **δ-1** Wall-time watchdog: daemon thread at `depth == 0`, 30 s poll, SIGTERM → SIGKILL escalation on breach; nested sub-managers skip (root covers them). `delegation_loop_runner.py` — `_start_walltime_watchdog`/`_stop_walltime_watchdog`.
  - **δ-2** Hard per-call executor killer: `Timer(effective_timeout + 5 s)` force-kills the warm subprocess if α-1's deadline fails to wake the read thread; falls through to `_execute_cold`. `persistent_executor.py` — `_hard_kill_from_watchdog`, `execute()`.
  - **δ-3** Pipe-output cap: `stdout`/`stderr` capped at **2 MB** in `_WORKER_SCRIPT` before JSON serialisation to prevent pipe-buffer deadlocks.

### Outer Loop (A5, experimental)

- **Artifact registry** (`packages/awp-runtime/src/awp/outer_loop/`): a versioned store for the 6 prompt artifacts currently routed through it — `worker_pitfalls`, `manager_planning_preamble`, `experiment_context_hint_template`, `pattern_library`, `tool_description_templates`, `critique_rubric`. Authoritative code: `artifacts.py` (registry) + `store.py` (SQLite) + `defaults/` (v0 fallback strings).
- **Fallback behavior**: when no DB is provided (or `~/.awp/outer_loop.db` is not writable), the registry serves the hardcoded v0 defaults bundled under `defaults/`. v0 is synthetic and is NEVER persisted to the DB.
- **Env override**: `AWP_OUTER_LOOP_DB` overrides the default DB path. The DB is opened lazily on first `get_active` call — `import awp.outer_loop` has no filesystem side effects.
- **Phase A1**: behavior-preserving artifact registry. Prompts are byte-identical to the pre-refactor codebase; no runtime control flow changed.
- **Phase A2 (landed)**: deterministic loss + task suites + CLI. `loss.py` (`compute_run_loss` reads `run_completion.json` + `metrics.jsonl` and returns a `LossBreakdown` weighted across eval, critique, gate rejections, budget burn, terminal status), `suite.py` (`TaskSuiteSpec` Pydantic schema + `load_suite`), `runner.py` (`SuiteRunner.run_epoch` persists epochs + epoch_runs to the same SQLite store as the registry). The `awp optimize SUITE_YAML` CLI without `--with-textgrad` still runs this A2 path: the suite runs N epochs, losses are captured, but no artifact is touched (`child_artifacts == parent_artifacts`).
- **Phase A3 (landed)**: TextGrad LLM-as-optimizer + rollback on regression. `textgrad.py` (`TextGradOptimizer.propose_update` — one `chat_text` call per candidate, strict-JSON parsing with markdown-fence tolerance, `argmax(expected_loss_reduction * confidence)` selection, hard constraints: wrong name / unchanged / > 20 000 chars → drop). `SuiteRunner.optimize` drives the multi-epoch SGD loop: apply one update per epoch, on `mean_loss` regression roll back the last update and halve the learning rate. `epochs.child_artifacts_json` is now a structured payload (`{"artifacts": name->version, "events": [...]}`), not just a name-to-version map. CLI surface: `awp optimize --with-textgrad --epochs N --learning-rate F [--no-rollback] [--manager-model M]`, `awp optimize-rollback ARTIFACT VERSION`, `awp optimize-inspect --artifact NAME` (unified-diff history). Authoritative code: `packages/awp-runtime/src/awp/outer_loop/textgrad.py`, `packages/awp-runtime/src/awp/outer_loop/runner.py` (`SuiteRunner.optimize`, `_apply_update`, `_rollback_last_update`).
- **OFF by default**: outer-loop code paths are only entered through `awp optimize` / `awp optimize-inspect` / `awp optimize-rollback`; a normal `awp run` never imports the runner. `--with-textgrad` is opt-in — without it `awp optimize` still runs the A2-compatible path.

### Refinement Mode (y-axis optimization)

- **Entry point**: `awp refine <seed_run_dir> [--iterations N] [--model M] [--worker-model M] [--tier-low MGR:WKR] [--tier-mid MGR:WKR] [--tier-high MGR:WKR]`. Clamped to `[1, 10]` iterations; default 3.
- **Model tiering (additive, `awp.refinement.tiers.TierPlan`)**: optional low/mid/high `{manager, worker}` pairs mapped across N iterations (thirds-proportional; `low` early → `high` late); empty tier fields fall back to seed's models. `tier_plan=None` → factory call is byte-identical to the legacy path (hard stability contract). API body fields `tier_low` / `tier_mid` / `tier_high` win over legacy `model` / `worker_model` with a `refinement.mixed_body` warning. Session sidecar records `tier_plan_used`, plus per-iteration `tier` / `model_manager` / `model_worker`. Authoritative doc: `docs/refinement.md §6.6`.
- **Gradient** (`awp.refinement.gradient`): deterministically extracted from the prior run's `run_completion.json` (critique defects + eval deltas) and `events.jsonl` (last 3 `gate.reject` entries). No LLM call. Prefix template in `render_refinement_prefix` omits empty sections.
- **R36 (normative)**: empty gradient → CLI prints `"nothing to refine"` and exits 0; no `AgentWorkflow` is constructed. Spec: `spec/versions/1.0/validation-rules.md §12`.
- **Injection point**: `DelegationLoopRunner` prepends `manager_prompt_prefix` to the manager's user message on iteration 1 only. Both the inline-manager path (`_run_inline_manager`) and the agent-based path (`_run_manager`) honor the guard; subsequent iterations see the vanilla message.
- **Budget halving** (`budget_for_iteration`): counts + tokens halved with `ceil`/floor; wall-time halved from the seed's **observed** wall time (floor 60 s); depth unchanged.
- **Stop conditions** (`RefinementLoop`): `max_iterations`, `regression` (loss rose 2×), `plateau` (|Δloss|<0.01 for 2×), `wall_time_exhausted` (cumulative ≥ 2× seed observed), `empty_gradient` (iter 1, R36), `empty_gradient_midloop` (iter k>1 produced a perfect run).
- **Storage**: iteration runs are standalone experiments usually under `/tmp/awp-experiments/refine_<ts>/iter_<k>/` linked via `parent_run_id` (seed → iter_1 → iter_2…). Session sidecar at `<seed>/refinement_sessions/<session_id>.json`. Winning iteration hard-linked into `<seed>/BEST/` with `manifest.json`; overwritten only if a future session produces strictly lower loss.
- **Loss**: `compute_run_loss` from `awp.outer_loop.loss` is reused unchanged with default `LossWeights`.
- **OFF by default**: refinement code is only imported by the `awp refine` CLI or `RefinementLoop.run()`; `awp run` and `awp optimize` never import it.
- Authoritative doc: `docs/refinement.md`. Implementation plan: `docs/superpowers/plans/2026-04-19-awp-refine-mode.md`.

### Tool Registry UI Surface

Dynamic-tool JSON under `shared/dynamic_tools/*.json` carries a nested `provenance.creator_agent` field written by `DynamicToolFactory._persist_tool`. The UI tool-registry panel reads it via `packages/awp-ui/server/services/graph_builder.py::_build_tool_registry`, with legacy fallback to a flat `creator_agent` key and final default `"persisted"`. When `signature` is absent in the persisted JSON, the panel falls back to the raw `parameters` object so tooltips always have something renderable.

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

Full rubric, tags, live-monitoring runbook, and LLM-trace debug walkthrough: **`docs/e2e.md`**. The rules below are non-negotiable and apply to every E2E run.

### Definition

An E2E test is a full run that exercises the entire system end-to-end:

1. Create a **new experiment** from scratch.
2. Give it a **fictional task** that forces coverage of: orchestration (DAG or delegation loop), manager intelligence (autonomous decisions, submanager promotion), tool creation (dynamic factory generates + validates), skill creation (produced and reused), sub-manager delegation (recursive spawning).
3. The run MUST pass the rubric in `docs/e2e.md` (terminal state, artifacts, budget, graph integrity, rubric score).

### Mandatory Properties

- **Real LLM calls only** (OpenRouter / OpenAI / Anthropic). Mocked, stubbed, or recorded responses are not valid coverage.
- **Stored as real experiments in `/tmp/awp-experiments/`** with populated output folders. Pytest-only runs without a populated experiment are not valid — I must be able to open the run in the UI, see its graph, and inspect its artifacts.
- **Registered in the experiment DB before the run starts** (status `running`, via the same `AgentWorkflow` path the UI uses), so the experiment shows up in the sidebar immediately and transitions `running → complete | partial | failed` live. Intermediate events (iterations, worker spawns, tool calls) persist as they happen.
- **Tagged** via `run_e2e(tags=[...])`. `"e2e"` is auto-added; add focus tags (`s5`, `tool-creation`, `critique`, `sub-manager`, `memory`, `planning`, `quick` — see `docs/e2e.md`). An untagged E2E is not valid.
- **Full LLM trace** persisted alongside `run_completion.json` and `events.jsonl`: every manager / worker / critique / eval / induction call with timestamp, caller, model, system prompt, user prompt, raw response, tokens, latency, parsed decision. Mocked / summarized / truncated traces are not valid.
- **Debug starts at the trace.** On every E2E failure, open the trace and walk `loss-driven-development:root-cause-by-layer` (5-Why through AWP's 7 layers) over it before hypothesizing about code — see the debug walkthrough in `docs/e2e.md`. A fix proposed without reading the trace is a symptom patch and is rejected.

The E2E run is a forward pass and the code fix is an SGD step — see `loss-driven-development:loss-backprop-lens` for the full gradient-descent framing (what counts as a gradient, why symptom patches are overfitting, and when to prefer an architectural edit over a local tweak). Guiding question: *"Would this system reach `complete` for an arbitrary task?"* If no, it is not shippable.

### Active Monitoring & Stagnation

E2E runs follow `loss-driven-development:e2e-driven-iteration` — the admissible cycle is "E2E → loss → 5-why-by-layer → fix → E2E", no edit without a fresh loss signal, no "done" without a passing E2E. Paired with `loss-driven-development:reproducibility-first` for signal discipline: one run is a noisy gradient, a defect that survives two runs is signal.

**Active monitoring is mandatory.** Fire-and-forget is forbidden — a run left unattended is wasted budget and a missed loss signal. While a run is in flight, continuously observe `events.jsonl`, the live trace, and the experiment row (`running → complete | partial | failed | aborted`); use the live-monitoring runbook in `docs/e2e.md`. At every observable signal (iteration boundary, gate rejection, repeated worker failure, budget warning, plan-loop, stall, anomalous trace), explicitly decide: **continue**, or **abort + fix + rerun**. Never "wait and see" once a defect is visible.

**Stagnation = abort + fix + restart (hard rule).** A run is stagnating the moment any of these is observable:

- 2+ consecutive iterations with no new worker progress (no fresh artifact, no new `share_output` field, no advancing plan)
- Same gate rejecting with the same reason ≥ 2 times
- Same worker failing the same way ≥ 2 times after a repair attempt
- Manager replanning (`PLAN`) without delegating
- Wall-time or tokens past ~50 % of budget without a passing `COMPLETE` attempt or fresh deliverable
- Critique loop oscillating on the same defect
- Trace shows the LLM repeating itself on the same wrong shape

Abort immediately — do not wait for the runtime's own `plan_loop_stall` / `max_rejected_completions` / wall-time watchdog (those are last-resort safety nets, not the primary stop condition for an actively-monitored run). Then: **capture** artifacts (`run_completion.json`, `events.jsonl`, full LLM trace, output dir, experiment DB row) before the rerun overwrites them → **diagnose** via `loss-driven-development:root-cause-by-layer` to AWP layers 4–5 (structural + conceptual origin) → **fix** at the structural origin and add a regression test at the layer of the root cause → **restart from scratch** (no resume, no patched-mid-run continuation).

**Bias is asymmetric:** false-abort is cheap (one wasted run), false-wait is expensive (full budget + still no signal + no fix). When in doubt whether a run is stagnating, abort.

### When to Run

Before every PyPI build + push, an E2E run MUST reach `complete` **and** cover all new features introduced since the last commit pushed to GitHub (`diff HEAD..origin/HEAD` scope). Additionally, all other test suites MUST be green:

```bash
pytest packages/awp-core/tests/ packages/awp-runtime/tests/
```

A single failing or skipped-due-to-error test blocks the publish. Fix the root cause, do not disable or xfail tests to unblock a release.

## PyPI Build Rules (MANDATORY)

Full build+publish sequence, architecture notes, and common-mistake list: **`docs/pypi-release.md`**. Read it before every release. The load-bearing rules below are reproduced here so they can't be missed:

- **One published package**: `awp-agents` (built from `reference/python/`). It vendors `awp-core`, `awp-runtime`, and the UI server + pre-built frontend. `awp-core` / `awp-runtime` are **not** published separately.
- **Frontend is a built artifact**: `cd packages/awp-ui/frontend && npm run build`, then copy `packages/awp-ui/frontend/dist/` → `reference/python/src/server/frontend/dist/` **before** building the wheel. The mirror gate does not cover this copy; a skipped step ships stale JS/CSS.
- **Python mirror must match**: `packages/awp-runtime/src/`, `packages/awp-core/src/`, and `packages/awp-ui/server/` must be byte-identical to their `reference/python/src/` counterparts. Enforced by `scripts/check_mirror_drift.py` (blocks commits).
- **Version sync** (one commit, all four):

  | File | Field |
  |------|-------|
  | `packages/awp-core/pyproject.toml` | `version` |
  | `packages/awp-runtime/pyproject.toml` | `version` + `awp-core>=` dependency |
  | `packages/awp-ui/pyproject.toml` | `version` + `awp-core>=` and `awp-runtime>=` dependencies |
  | `reference/python/pyproject.toml` | `version` (awp-agents meta-package) |

- **PyPI is append-only**: a broken upload cannot be replaced — bump the version again.

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

!sudo install -d -m 0755 /etc/systemd/system/user@.service.d/ && sudo tee /etc/systemd/system/user@.service.d/99-oomd-relax.conf > /dev/null <<'EOF'                                                                               
[Service]                                                                                                                                                                                                                          
ManagedOOMMemoryPressureLimit=80%                                                                                                                                                                                                  
EOF                                                                                                                                                                                                                                
sudo systemctl daemon-reload && sudo systemctl set-property user@1000.service ManagedOOMMemoryPressureLimit=80%