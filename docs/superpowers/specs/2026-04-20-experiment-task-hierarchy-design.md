# Experiment-Task Hierarchy with Deliverable-Continuation — Design

**Status:** draft → for review
**Date:** 2026-04-20
**Author:** Claude (Protocol Steward) + user
**Scope:** Experiment lifecycle end-to-end — on-disk layout, `awp_ui.db` schema, runtime integration for `awp run` / `awp refine` / `awp optimize`, CLI, UI navigation.
**Depends on:** `docs/refinement.md`, `docs/outer-loop.md`, `docs/e2e.md`
**New rule:** R37 (see §11)

---

## 1. Motivation

Today AWP has three disjoint experiment-management systems:

1. **`awp run`** — stores a single run in `/tmp/awp-experiments/<slug>-<ts>-<uuid>/`, registers a row in `~/.awp/awp_ui.db` (`runs`, `sessions`, `session_runs`, `events`).
2. **`awp refine`** — iterations land as sibling directories `/tmp/awp-experiments/refine_<ts>/iter_<k>/`, linked to the seed only through `parent_run_id` inside each `run_completion.json` plus a sidecar at `<seed>/refinement_sessions/<session_id>.json`. The UI shows each iteration as a standalone, disconnected run.
3. **`awp optimize`** — artifact versions, epochs, and epoch-runs live in a **global** `~/.awp/outer_loop.db`. The underlying run folders sit in the same flat `/tmp/awp-experiments/` bucket. The UI is unaware of the epoch structure.

Three consequences fall out of this:

- **No umbrella.** There is no first-class entity that groups a sequence of user-intentions. `sessions` (UI-DB) exists but is used only for ad-hoc CLI batches, never by refine or optimize.
- **No deliverable continuity.** A user who wants to "take the paper draft from the previous run, add my feedback, improve it" has no mechanism. Every `awp run` starts from scratch; the repository is re-analysed, the draft is re-written, and the prior deliverable is at best a reference the user manually pastes in.
- **Lost navigation.** A run, a refinement iteration, and an optimize-epoch-run are indistinguishable in the sidebar. Loss and metrics are locked inside per-run JSON files with no task- or experiment-level aggregation.

This spec introduces a three-level hierarchy — **experiment → task → run** — that makes task-to-task continuation a first-class concept, relocates refinement and optimization under the task they belong to, and isolates outer-loop learning per experiment.

---

## 2. Non-goals

- **Full experiment portability** (per-experiment UI DB, zip-and-ship). The UI DB stays global. Portability is a later iteration, not this one.
- **C-style transfer channels** (critique aggregation, plan skeletons, tool-usage statistics). The user will in practice decide which of these matter only after running real multi-task experiments. Out of scope here.
- **Task branching.** Tasks are strictly sequential per experiment (one `task_order` list per experiment, no forks).
- **Automatic task-boundary detection.** The user creates each task explicitly; the system does not try to "detect when a task is done."
- **Migration of existing experiments.** The user has explicitly chosen a clean cut: `awp experiment purge-legacy` deletes old flat experiments at upgrade. No legacy code paths in runtime or UI.
- **Changes to the agent output contract (R17).** Continuation is a Manager-prompt-prefix mechanism, not a new agent interface.

---

## 3. Mental model

```
Experiment  =  user's campaign toward a goal
      |                                                 "AWP Paper"
      +─ Task 001 (mode=seed)          user_prompt
      |       +─ seed run                                   │ refine loop (y)
      |       +─ refinement sessions ◄─────────────────────┘
      |       +─ optimize suites    ◄── θ-SGD on the task's prompt artifacts
      |       +─ BEST/              ◄── auto lowest-loss, user-overridable
      |
      +─ Task 002 (mode=continuation) user_feedback + inputs←{001.BEST}
      |       +─ seed run (continuation-loaded: prior bundle + feedback)
      |       +─ refinements, optimizations, BEST
      |
      +─ Task 003 …                  inputs can span multiple prior tasks
```

Why these three levels and not two or four:

1. **Experiment** is the unit the user thinks in (*"the paper project"*) and the unit that should own the isolated learning state (outer-loop artifacts, shared memory, induced tools).
2. **Task** is the unit of user intention and the unit that carries a single coherent gradient from the user (*"make section 3 deeper"*). Refinement and optimization are modifiers of a task, not peers.
3. **Run** is the unit of execution. It is the lowest level that has a loss and terminal state.

Why **deliverable continuation (D)** and not outer-loop-only transfer (B) or full-state transfer (C):

- The user's requirement is *"the next run builds on the existing deliverable without re-analysing the repo."* That is a statement about **y** (the artifact) crossing the task boundary, not about **θ** (the prompts) evolving.
- B (per-experiment outer-loop artifacts) addresses θ continuity but leaves the paper draft to be rewritten from scratch.
- C stacks automatic transfer channels (critique aggregation, plan skeletons, eval focus) on top — useful eventually, but costly to debug and easy to contaminate.
- D puts the actual bundle (the draft + analysis artifacts) into the next task's Manager context and treats the user's feedback as the gradient. It is a direct generalisation of the refinement mechanism that already exists.

D and B are orthogonal. B can be added later. The spec keeps per-experiment outer-loop DBs (see §4) so that when B is added it does not fight an already-global artifact registry.

---

## 4. Decisions locked in this spec

1. **Three-level hierarchy.** Every run belongs to exactly one task; every task to exactly one experiment. A run without a task is not representable after this change.
2. **Deliverable continuation (D).** A continuation task pre-loads the prior task's `BEST/` bundle into the Manager context at iteration 1 of its seed run, with user feedback as the gradient prefix.
3. **Bundle loading = γ + δ.** The whole `BEST/` bundle is loaded for each `inputs[]` entry. Entries carry `role ∈ {"primary", "reference"}`; primary is inline, reference is a path registry (the Manager can fetch but the prefix does not inline it). `inputs[]` may contain entries from multiple prior tasks (δ).
4. **BEST per task = auto lowest-loss, user override.** `<task>/BEST/manifest.json` records `{winner_run_id, reason ∈ {"auto_loss","user_override"}, loss, updated_at}`. Default is auto; UI offers an override knob. `loss` comes from `compute_run_loss` (`packages/awp-runtime/src/awp/outer_loop/loss.py`).
5. **Isolation β.** The outer-loop database moves from `~/.awp/outer_loop.db` to `<experiment>/outer_loop.db`. Per-experiment learning state. `awp_ui.db` stays global and gains three new tables/columns.
6. **No legacy support.** No migration script, no dual-layout rendering. `awp experiment purge-legacy` deletes flat-layout experiments from disk and removes orphan `runs` rows.

---

## 5. Physical layout

```
/tmp/awp-experiments/<experiment_id>/
├── experiment.json                     # id, name, goal, created_at, task_order
├── outer_loop.db                       # per-experiment (6 prompt artifacts + epochs)
├── shared/
│   ├── memory/                         # accumulates across all tasks
│   ├── dynamic_tools/                  # induced tools stay available across tasks
│   └── skills/
└── tasks/
    ├── 001-<slug>/
    │   ├── task.json                   # user_prompt, mode, inputs[], created_at
    │   ├── seed/
    │   │   └── output/
    │   │       └── <run_id>/
    │   │           ├── run_completion.json
    │   │           ├── FINAL/
    │   │           ├── events.jsonl
    │   │           └── metrics.jsonl
    │   ├── refinements/
    │   │   └── session_<ts>/
    │   │       ├── session.json        # relocated from <seed>/refinement_sessions/
    │   │       ├── iter_1/<run_id>/
    │   │       └── iter_2/<run_id>/
    │   ├── optimizations/
    │   │   └── suite_<ts>/
    │   │       ├── suite.json          # suite_yaml ref, epoch count, mean_loss curve
    │   │       ├── epoch_1/
    │   │       │   └── runs/<run_id>/
    │   │       └── epoch_2/
    │   └── BEST/
    │       ├── manifest.json
    │       └── <hardlinks into winner's FINAL/>
    └── 002-<slug>/
        └── …
```

> Note: the `seed/output/` layer reflects `AgentWorkflow`'s native run-dir shape and is kept for runtime fidelity; it is not a user-facing concept.

Changes relative to today:

- Refinement iterations live inside the task they refine, not as sibling directories under `/tmp/awp-experiments/refine_<ts>/`.
- Optimize epoch-runs live inside the task they optimize, not as loose runs under `/tmp/awp-experiments/`.
- `~/.awp/outer_loop.db` is gone. Each experiment has its own `<experiment>/outer_loop.db`. The `AWP_OUTER_LOOP_DB` environment variable remains supported as a testing override.

The `shared/` directory is experiment-scoped as it is today for single-experiment containers, but it now intentionally spans all tasks within the experiment. Memory entries accumulated in Task 001 are visible to the Manager of Task 002 through the existing `shared/memory/` mechanism — no new code.

---

## 6. Data model

### 6.1 `experiment.json`

```json
{
  "experiment_id": "exp_2b4c9f",
  "name": "AWP Paper",
  "goal": "A well-structured paper about AWP for publication",
  "created_at": "2026-04-20T12:00:00Z",
  "task_order": ["001-draft", "002-improve-sec3", "003-benchmarks"]
}
```

- `task_order` is authoritative for task sequence. New tasks append. Deleted tasks are removed from the list and their directory is removed; gaps in numbering are allowed (no renumbering).

### 6.2 `task.json`

Seed task:
```json
{
  "task_id": "001-draft",
  "experiment_id": "exp_2b4c9f",
  "task_number": 1,
  "mode": "seed",
  "user_prompt": "Write a paper about AWP",
  "inputs": [],
  "created_at": "2026-04-20T12:01:00Z"
}
```

Continuation task:
```json
{
  "task_id": "002-improve-sec3",
  "experiment_id": "exp_2b4c9f",
  "task_number": 2,
  "mode": "continuation",
  "user_feedback": "Section 3 deeper, add benchmarks, shorten intro",
  "inputs": [
    {"from_task": "001-draft", "role": "primary",   "bundle": "BEST/"},
    {"from_task": "001-draft", "role": "reference", "paths": ["BEST/analysis/repo_facts.json"]}
  ],
  "created_at": "2026-04-20T14:00:00Z"
}
```

Schema rules (validated at task-create and at run-start):

- `mode ∈ {"seed", "continuation"}`.
- `mode == "seed"` → `user_prompt` required, `user_feedback` forbidden, `inputs` must be empty.
- `mode == "continuation"` → `user_feedback` required, `inputs` must be non-empty (R37).
- Each `inputs[]` entry has `from_task` (must exist in the same experiment with a BEST pointer), `role ∈ {"primary","reference"}`, and exactly one of `bundle` (shorthand for the whole BEST dir) or `paths` (list of relative paths under the source task's directory).
- An `inputs[]` entry is rejected if its `from_task` has no `BEST/manifest.json` (i.e. the source task has not produced at least one terminal run).

### 6.3 `awp_ui.db` (global) — schema additions

New table `experiments`:
```sql
CREATE TABLE experiments (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  goal TEXT,
  base_dir TEXT NOT NULL,
  created_at REAL NOT NULL,
  archived_at REAL
);
```

New table `tasks`:
```sql
CREATE TABLE tasks (
  id TEXT PRIMARY KEY,                 -- "<experiment_id>:<task_slug>"
  experiment_id TEXT NOT NULL REFERENCES experiments(id) ON DELETE CASCADE,
  task_number INTEGER NOT NULL,
  slug TEXT NOT NULL,
  mode TEXT NOT NULL CHECK(mode IN ('seed','continuation')),
  user_prompt TEXT,
  user_feedback TEXT,
  inputs_json TEXT NOT NULL DEFAULT '[]',
  best_run_id TEXT,                    -- FK into runs.id (soft; set by finaliser)
  best_reason TEXT CHECK(best_reason IN ('auto_loss','user_override') OR best_reason IS NULL),
  created_at REAL NOT NULL,
  UNIQUE(experiment_id, task_number)
);
```

Additions to `runs`:
```sql
ALTER TABLE runs ADD COLUMN experiment_id TEXT REFERENCES experiments(id) ON DELETE CASCADE;
ALTER TABLE runs ADD COLUMN task_id       TEXT REFERENCES tasks(id)       ON DELETE CASCADE;
ALTER TABLE runs ADD COLUMN run_role      TEXT CHECK(run_role IN ('seed','refine_iter','optimize_epoch_run'));
ALTER TABLE runs ADD COLUMN parent_run_id TEXT;            -- for refinement chain within a session
ALTER TABLE runs ADD COLUMN loss          REAL;            -- cached from run_completion.json at completion
```

After the schema change, `experiment_id`, `task_id`, and `run_role` are NOT NULL for all new runs. The schema allows NULL only to make the `ALTER TABLE` statements non-rewriting; the runtime enforces non-null at insert.

The `sessions` and `session_runs` tables remain for backward compatibility with the existing CLI batch-grouping feature but are no longer touched by `awp run`, `awp refine`, or `awp optimize`. A follow-up spec may retire them; this spec does not.

### 6.4 `<experiment>/outer_loop.db`

Schema unchanged (`artifact_versions`, `task_suites`, `epochs`, `epoch_runs`). The store-opening function `awp.outer_loop.store.get_store` acquires a new parameter `experiment_dir: Path` and opens `experiment_dir / "outer_loop.db"`. `AWP_OUTER_LOOP_DB` continues to override the path.

### 6.5 `<task>/BEST/manifest.json`

```json
{
  "task_id": "001-draft",
  "winner_run_id": "abc123…",
  "winner_source": "refinement_session/session_20260420_1345/iter_3",
  "reason": "auto_loss",
  "loss": 0.42,
  "loss_breakdown": { "eval": 0.12, "critique": 0.08, "gate_reject": 0.15, "budget_burn": 0.05, "terminal": 0.02 },
  "updated_at": "2026-04-20T16:00:00Z"
}
```

Hardlinks: the files under the winner run's `FINAL/` are hardlinked into `<task>/BEST/` (fall back to copy if cross-filesystem, matching the existing refinement behaviour in `packages/awp-runtime/src/awp/refinement/session.py`).

---

## 7. Runtime — continuation loader

New module: `packages/awp-runtime/src/awp/continuation/`.

### 7.1 `bundle_loader.py`

Public API:
```python
def load_continuation_bundle(task_dir: Path, experiment_dir: Path) -> ContinuationBundle: ...
```

Reads `task_dir / "task.json"`. For each `inputs[]` entry:

- Resolves `from_task` to `<experiment>/tasks/<from_task>/`.
- Verifies that the source task has `BEST/manifest.json`. Missing → `ContinuationInputError` with actionable message.
- For `bundle: "BEST/"`, enumerates all files under the source `BEST/`.
- For `paths: [...]`, enumerates only those paths (validated to stay under the source task's directory; no `..` escape).

Returns a `ContinuationBundle` with two lists:

- `primary_materials: list[BundleEntry]` — entries with `role == "primary"`, each carrying `(source_task, relative_path, content_bytes)`.
- `reference_paths: list[ReferencePointer]` — entries with `role == "reference"`, each carrying `(source_task, absolute_path, size_bytes, summary_head)`.

### 7.2 `prompt_injection.py`

Public API:
```python
def render_continuation_prefix(bundle: ContinuationBundle, user_feedback: str) -> str: ...
```

Produces a deterministic text block:

```
## Continuation Context

### Prior deliverable (primary)
{inline content of every primary entry, each prefixed with the source path}

### Reference material (available via fs.read)
{for each reference: source_task, path, size, first 200 characters}

## User Feedback
{user_feedback}

## Your Task
Produce the evolved deliverable based on the prior material and the user feedback.
Do not re-derive material that is already present above; build on it. Use the
reference material only if the primary material has a gap the feedback asks to fill.
```

### 7.3 Context-budget guard

Before returning the prefix, `render_continuation_prefix` estimates token count (4 chars/token) and applies the existing Manager-context guard (`packages/awp-runtime/src/awp/runtime/delegation_loop_runner.py::_guard_manager_context`):

- If the combined prefix + expected Manager user-message stays below `manager_context_compress_threshold` (default 0.8) × `manager_context_budget_tokens` (default 150 000): return as-is.
- Above the threshold: **primary is never compressed**. Reference entries degrade to metadata stubs (path + size + first 200 chars, no body). If still over: the reference block is dropped entirely.
- If primary alone exceeds the budget: hard error `ContinuationBudgetError` with message suggesting the task be split.

### 7.4 Hook into `DelegationLoopRunner`

The prefix is injected at the same point as refinement's `manager_prompt_prefix` — before iteration 1 of the seed run's Manager user message, in both `_run_inline_manager` and `_run_manager`. Gate feedback, budget nudges, and plan-loop nudges still apply normally to subsequent iterations. Refinement iterations within the same task do **not** re-apply the continuation prefix; they are handled by the existing refinement prefix on top of whatever state is reached.

If `mode == "seed"`, the continuation code path is not entered at all.

### 7.5 BEST finaliser

A new module `packages/awp-runtime/src/awp/experiment/best_finaliser.py` is invoked at two points:

1. **On run completion** — after `run_completion.json` is written, the finaliser reads the run's `loss`, compares it against the current `<task>/BEST/manifest.json::loss`, and — if strictly lower — rewrites the manifest and hardlinks the winner's `FINAL/` into `<task>/BEST/`. It also updates `tasks.best_run_id` and `tasks.best_reason = 'auto_loss'` in `awp_ui.db`. Runs with `loss IS NULL` (non-terminal, crashed) are skipped.

2. **On user override** — `POST /tasks/{task_id}/best {run_id}` validates the target run is terminal, rewrites the manifest with `reason: 'user_override'`, re-hardlinks, and updates `awp_ui.db`. A subsequent lower-loss run does **not** auto-displace a user override; auto-BEST resumes only after the user explicitly clears the override via `awp task set-best --auto`.

### 7.6 Refinement under the new layout

`awp refine` is re-pointed to operate on the **best run of a task** by default (`--task exp:001-…` → use `<task>/BEST/manifest.json::winner_run_id` as the seed run). An explicit `--run <run_id>` remains supported for refining a specific non-BEST run. Refinement sessions are written to `<task>/refinements/session_<ts>/` instead of `<seed>/refinement_sessions/` + `/tmp/awp-experiments/refine_<ts>/`. The session sidecar schema is unchanged.

### 7.7 Optimize under the new layout

`awp optimize --task exp:001-…` opens `<experiment>/outer_loop.db`, writes epoch-runs under `<task>/optimizations/suite_<ts>/epoch_<n>/runs/`, and updates the experiment-scoped artifact versions. The store-opening function picks up `experiment_dir` from the task path.

---

## 8. CLI

### 8.1 Experiment management

```
awp experiment create "AWP Paper" --goal "Paper for publication"
awp experiment list
awp experiment show <experiment_id>
awp experiment delete <experiment_id>         # removes directory + DB rows
awp experiment purge-legacy                   # one-shot: deletes all flat-layout runs
```

### 8.2 Task management

```
awp task create <experiment_id> "<user_prompt>"           # mode=seed
awp task create <experiment_id> "<user_feedback>" \
    --continuation \
    --from-task <task_id> [--from-task <task_id>] \
    --primary BEST/ \
    [--reference <relpath> [--reference <relpath> …]]
awp task list <experiment_id>
awp task show <experiment_id>:<task_slug>
awp task delete <experiment_id>:<task_slug>                    # removes dir + DB rows
awp task set-best <experiment_id>:<task_slug> --run <run_id>   # user override
awp task set-best <experiment_id>:<task_slug> --auto           # clear override, resume auto
```

### 8.3 Run / refine / optimize

```
awp run --task <experiment_id>:<task_slug> [workflow.yaml]
awp refine --task <experiment_id>:<task_slug> [--run <run_id>] [--iterations N] [--tiers …]
awp optimize --task <experiment_id>:<task_slug> SUITE.yaml [--with-textgrad] [--epochs N]
```

### 8.4 Implicit experiment for bare `awp run`

`awp run workflow.yaml` without `--task` is still accepted. Runtime auto-creates an experiment `ad_hoc_<ts>` with a single seed task `001-<workflow-name>` and then proceeds. This keeps one-off invocations ergonomic while the schema invariant "every run has a task" holds.

---

## 9. UI surface

### 9.1 Sidebar (three-level tree)

```
▾ Experiments
  ▾ AWP Paper                     [goal snippet · 3 tasks · latest loss 0.31]
    ▾ 001 Write paper             [mode: seed · best 0.42]
      • seed run abc123           [complete · loss 0.55]
      ▸ refinement session        [3 iters · best 0.42]
      ▸ optimize suite            [2 epochs]
    ▸ 002 Improve section 3       [mode: continuation ← 001 · best 0.31]
  ▸ Another Experiment
```

Each level is collapsible. The selected node drives the main view.

### 9.2 Experiment-detail view (new)

- Header: name, goal, task count, aggregate metrics.
- **Loss curve across tasks.** X-axis: `task_number`. Y-axis: `best_loss` per task. A visible monotonic decrease is the visual confirmation that the campaign is converging.
- Tabs:
  - **Overview** — summary + best-loss curve + task list.
  - **Tasks** — table with per-task status, mode, best loss, best run, input provenance.
  - **Shared artifacts** — contents of `shared/memory/`, `shared/dynamic_tools/`, `shared/skills/`.
  - **Outer-loop history** — artifact-version diffs and epoch history from `<experiment>/outer_loop.db`.
- "New Task" button → continuation wizard (pick parent task, pick input roles, enter feedback).

### 9.3 Task-detail view (new)

- Header: user prompt / user feedback, mode, input pointers (clickable → source task).
- **Loss curve across runs in the task.** X-axis: run timeline. Separate series for seed, refinement, optimize. Badge for the BEST winner.
- Tabs:
  - **Seed run** — standard run view.
  - **Refinement sessions** — list of sessions; each expands to iterations with per-iter loss and gate outcomes.
  - **Optimize suites** — list of suites; each shows `mean_loss` per epoch + artifact-version diff.
  - **BEST pointer** — manifest, winner source, loss breakdown, "Override BEST" button.
- "Compare runs" action opens two runs side-by-side (loss breakdown, gate outcomes, deliverable diff if both are text).

### 9.4 Run-detail view (existing)

Unchanged internally. Adds:

- Breadcrumb `Experiment → Task → Run`.
- "Compare with task-best" action.
- Loss block rendered uniformly for seed, refine-iter, optimize-epoch-run using the same `loss_breakdown` from `run_completion.json`.

### 9.5 Loss and metrics placement

| Level             | Metrics shown                                                                  |
|-------------------|---------------------------------------------------------------------------------|
| Run               | `compute_run_loss` breakdown (eval, critique, gate-rejects, budget-burn, terminal), eval per-metric, token usage |
| Refinement session| Loss curve over iterations, stop reason, Δ vs. seed                             |
| Optimize suite    | `mean_loss` per epoch, artifact-version diff, rollback events, learning rate   |
| Task              | Best loss, Δ seed-to-best, run count by role, token budget used                |
| Experiment        | Best-loss curve across tasks, aggregate token spend, active outer-loop versions |

### 9.6 API routes (additions to `packages/awp-ui/server/api/routes.py`)

```
POST   /experiments                              create
GET    /experiments
GET    /experiments/{id}                         detail + task list + aggregates
DELETE /experiments/{id}

POST   /experiments/{id}/tasks                   create task (seed or continuation)
GET    /experiments/{id}/tasks
GET    /tasks/{task_id}                          detail + runs + BEST manifest
DELETE /tasks/{task_id}                          removes directory + DB rows
POST   /tasks/{task_id}/best                     user override {run_id} or {auto: true}
```

The existing `POST /runs/create` accepts a new `task_id` query parameter; when provided, the run is registered under that task. When absent, the implicit-experiment flow (§8.4) kicks in.

---

## 10. Error handling

| Case                                                          | Behaviour                                                                                       |
|---------------------------------------------------------------|-------------------------------------------------------------------------------------------------|
| Continuation task with empty `inputs`                          | R37 fail at task-create; CLI exits non-zero with the list of prior tasks that have a `BEST/`.   |
| `from_task` does not exist                                     | CLI fail at task-create; lists available tasks.                                                 |
| `from_task` has no `BEST/manifest.json`                        | CLI fail; message suggests running the source task to completion first.                         |
| Bundle exceeds `manager_context_budget_tokens`                 | Reference stubs first, then drop references; primary never compressed; if primary alone overflows, `ContinuationBudgetError` — user must split the task. |
| Run exits without `run_completion.json`                        | `runs.loss = NULL`; run is ignored for auto-BEST selection. User override is refused for non-terminal runs. |
| User overrides BEST to a non-terminal run                      | UI + API refuse.                                                                                |
| `<experiment>/outer_loop.db` missing on `awp optimize`         | Created automatically (first epoch in this experiment).                                         |
| `AWP_OUTER_LOOP_DB` set                                        | Overrides per-experiment DB for that process (test-only; emits a warning event in the run).    |
| Legacy run directory encountered by UI                         | Does not happen after `purge-legacy`. Until then, UI refuses to open it with a clear message.  |

---

## 11. New normative rule — R37

> **R37 (Continuation-Task Input Non-Emptiness).** A task with `mode == "continuation"` MUST have a non-empty `inputs` array, and every `inputs[]` entry MUST reference a `from_task` that exists in the same experiment and has a terminal run recorded in `BEST/manifest.json`. Tasks violating R37 are rejected at task-create time and MUST NOT produce a run.

Rationale: silent "continuation-as-seed" tasks (created with `--continuation` but no inputs, or with a dangling `from_task`) would produce the surprising behaviour of a Manager prompt containing the continuation scaffolding but no actual prior material. R37 makes the invariant load-bearing and refuses the run at creation time rather than at Manager-prompt time.

R37 is added to `spec/versions/1.0/validation-rules.md` under the Continuation section, alongside R36.

---

## 12. Testing strategy

### 12.1 Unit

- `task.json` schema validator: positive/negative cases for `mode`, `inputs`, `user_prompt`/`user_feedback` mutual exclusivity.
- `bundle_loader.py`: primary-only, reference-only, mixed, multi-task inputs (δ), path-traversal rejection, missing-BEST rejection.
- `prompt_injection.render_continuation_prefix`: deterministic output given inputs; compression path (reference stubs → reference drop); primary-only-overflow raises.
- BEST-finaliser: auto lowest-loss selection given a set of runs with varying losses, including NULL-loss runs (must be skipped).

### 12.2 Integration

- Two-task experiment with a mocked LLM runner: Task 001 writes a fake deliverable to its `FINAL/`; BEST is finalised; Task 002 (continuation) loads the bundle and the continuation prefix is built; we assert the Manager user-message at iteration 1 contains both the primary file content and the user feedback.
- Refinement under the new layout: running `awp refine --task exp:001` writes to `tasks/001/refinements/session_<ts>/` and updates `BEST/manifest.json` if a lower-loss iteration wins.
- Optimize under the new layout: running `awp optimize --task exp:001 SUITE.yaml` opens `<experiment>/outer_loop.db`, writes to `tasks/001/optimizations/suite_<ts>/`, and updates artifact versions in the per-experiment DB.

### 12.3 E2E (tag `continuation`)

Two-task experiment with a real LLM:

- Task 001: *"Write a 500-word explainer about the AWP autonomy spectrum A0–A4. Cite examples from the codebase."* The seed run produces a draft plus whatever analysis artifacts the Manager chose to extract.
- Task 002 (continuation, inputs = Task 001 BEST): user feedback *"Add a diagram-in-ASCII of the spectrum, and strengthen the A2 section with a concrete delegation-loop example. Keep everything else."*

Rubric checks:
1. Terminal state of Task 002 is `complete`.
2. Manager trace of Task 002 iteration 1 contains the primary content of Task 001's draft.
3. Worker activity in Task 002 shows **no repeat repo scan** for A0–A4 content (the Manager uses the inherited analysis).
4. Final deliverable in Task 002 visibly incorporates Task 001's structure (measured: ≥ 60% of Task 001's section headings appear in Task 002, and the ASCII diagram plus strengthened A2 section are present as requested by the feedback).
5. Loss of Task 002's BEST is lower than Task 001's BEST.

---

## 13. Migration

### 13.1 Legacy purge

`awp experiment purge-legacy` is a one-shot command:

1. Enumerates `/tmp/awp-experiments/*` that do **not** contain an `experiment.json` at their root.
2. Lists them to stdout, prompts confirmation (unless `--yes`).
3. Deletes the directories.
4. Deletes `runs` rows in `awp_ui.db` whose `experiment_id IS NULL`.
5. Deletes `~/.awp/outer_loop.db` if present.

The user has explicitly accepted that no existing runs survive. If a reader of this spec needs to preserve specific runs, they run `awp experiment show` + manual copy **before** upgrading.

### 13.2 Schema migration

On `awp`-runtime startup, if `awp_ui.db` is present but lacks the new tables, the runtime runs the `CREATE TABLE` statements and `ALTER TABLE` additions (§6.3). All new columns have safe defaults for migration; after the first write from the new code the DB is fully populated.

---

## 14. Accepted risks / antithesis

1. **Outer-loop artifacts become experiment-local.** Anyone relying on a global, long-running optimisation curve across arbitrary `awp optimize` invocations loses that curve. Accepted: the user model is per-experiment learning.
2. **Refinement accepts non-seed runs as base.** Refining an optimize-epoch-run has never been exercised; edge cases in `parent_run_id` accounting may surface. Accepted; covered by integration tests and the existing R36 guard for empty-gradient aborts.
3. **Long continuation chains eventually hit the context budget.** The reference-stub fallback is a patch, not a solution. Accepted for iteration 1; a later "bundle summarisation" step (C-adjacent) is a follow-up.
4. **One seed run per task.** A crashed seed or a re-worded prompt requires deleting the task and re-creating it; no `seed_rerun` shortcut. Accepted: no implicit state; all edits are structural.
5. **Implicit experiment for bare `awp run`.** Introduces a side-effect of creating an `ad_hoc_<ts>` experiment on every bare invocation. Accepted: the invariant "every run has a task" is worth more than one surprising directory on disk; the UI labels these clearly.

---

## 15. Open questions for the implementation plan

1. **Should `sessions` / `session_runs` be retired in this change or kept as dead code for one release?** Preference: keep for this release, retire in the follow-up that also lands γ portability.
2. **Does `awp task create --continuation` immediately spawn a run, or only register the task?** Preference: register only; the user explicitly issues `awp run --task` afterwards. This matches today's `awp run` ergonomics.
3. **How does the UI continuation wizard present Task 001's BEST when helping the user pick references?** Tree view of `BEST/` with checkboxes? Or free-form path input? Preference: tree view with a "select all" shortcut that is equivalent to `--primary BEST/`.
4. **Per-experiment `outer_loop.db`: does `awp optimize-inspect` take an experiment scope?** Proposed: yes. `awp optimize-inspect --experiment <id> --artifact <name>`. CLI is updated to require the experiment scope.
5. **Token-accounting for the continuation prefix.** Counted toward the task's seed-run token budget? Preference: yes; it is part of the Manager's input.
6. **Continuation documentation location.** R37 itself lands in `spec/versions/1.0/validation-rules.md` alongside R1–R36 (non-negotiable, matches existing pattern). The mechanism description is a separate question: should we add `docs/continuation.md` or extend `docs/refinement.md`? Preference: new `docs/continuation.md` — the mechanism is related to but distinct from refinement (user-gradient across tasks vs. auto-gradient within one run).
