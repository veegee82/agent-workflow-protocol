# AWP Refinement Mode — Design Spec

**Date:** 2026-04-19
**Status:** Draft (awaiting user review)
**Author:** Claude (brainstormed with user)
**Scope:** New optimization mode `awp refine` — task-local iterative refinement of an existing run's deliverable, independent of and complementary to the outer-loop SGD over prompt artifacts.

---

## 1. Motivation and Framing

The existing outer loop (`awp optimize`) optimizes **θ** — the six prompt artifacts — across a task suite. Every run it triggers starts from an empty workspace; run outputs are not carried forward. This is the correct shape for policy improvement (prompts generalize across tasks), but it leaves a second, orthogonal axis unexploited: **y**, the deliverable produced by a single task.

Refinement Mode adds that second axis. Given a completed run, it iteratively refines the deliverable toward lower loss, reusing the full runtime (delegation loop, critique engine, gate chain, eval) and without touching prompts. In ML terms: the outer loop is policy improvement; refinement is test-time inference-compute scaling (Self-Refine / Reflexion family).

The two modes are independent and composable: `optimize` trains the policy; `refine` applies extra inference compute to any given output. Neither subsumes the other.

### Design principles

- **Orthogonal to outer loop.** Refine does not modify θ. Outer loop does not seed from prior y. Clean attribution of loss changes.
- **Reuse, do not duplicate.** The delegation loop, critique engine, gate chain, eval, loss function, and experiment DB are reused unchanged. Refinement is orchestration (Layer 6), not a new runtime.
- **Deterministic gradient.** The refinement signal is extracted mechanically from the prior run's artifacts (`run_completion.json`, `events.jsonl`), not invented by an LLM. The manager's first PLAN sees it as a fixed prefix.
- **YAGNI.** No user-supplied refinement prompt (option b/c from brainstorm), no θ updates during refine, no composition with `awp optimize`, no UI surface, no parallel iterations — deferred unless asked.

---

## 2. Architecture

### 2.1 Module layout

New package: `packages/awp-runtime/src/awp/refinement/`.

| File | Purpose |
|------|---------|
| `loop.py` | `RefinementLoop` class — orchestrates iterations, loss tracking, early-stop decisions, best-iteration pointer |
| `gradient.py` | Extracts critique defects, gate rejections, and eval deltas from the prior run's artifacts into a structured `RefinementGradient` payload |
| `seed.py` | Hard-links (copy fallback) the prior iteration's `FINAL/` into the next iteration's workspace input directory |
| `__init__.py` | Public API — `RefinementLoop`, `RefinementGradient`, `RefinementResult` |

No changes to `DelegationLoopRunner`, `AWPAgent`, `AgentWorkflow`, budget envelope, gate chain, critique engine, or the R1–R35 validator. Refinement wraps the existing runtime through `AgentWorkflow`.

### 2.2 CLI surface

New command registered in `packages/awp-core/src/awp/cli.py`:

```bash
awp refine <seed_run_id_or_dir> [--iterations N] [--model M] [--worker-model M]
```

| Flag | Default | Semantics |
|------|---------|-----------|
| `--iterations N` | `3` | Max refinement iterations, clamped to `[1, 10]` |
| `--model M` | inherited from seed run | Manager model for refine iterations |
| `--worker-model M` | inherited from seed run | Worker model for refine iterations |

Exit codes:

| Code | Meaning |
|------|---------|
| `0` | At least one iteration produced `loss < seed_loss`; `BEST` pointer updated |
| `0` | Gradient was empty (seed already `complete` with full eval score); refine aborted before iter 1 with message `"nothing to refine"` |
| `1` | No iteration improved loss; `BEST` pointer still points at seed |
| `2` | Setup failure (seed not found, unreadable `run_completion.json`, etc.) |

### 2.3 Layer placement

Refinement lives in **Layer 6 (Orchestration)**. It:

- Does not introduce new manifest fields, identity primitives, capabilities, communication channels, memory classes, or observability events beyond what existing code already emits.
- Does not change the agent contract (R17).
- Does not change the budget envelope — it only sets numeric values within the existing envelope.
- Adds one new normative rule (R36, §6).

---

## 3. Data Flow per Iteration

```
iteration k ∈ [1..N]:
  1. read prior run:
       - k == 1 → seed run's run_completion.json
       - k > 1  → iteration k-1's run_completion.json
  2. build RefinementGradient:
       - critique.defects (list of {summary, severity, evidence})
       - last 3 gate rejections from events.jsonl where type == "gate.reject"
       - per-metric eval deltas: {metric: max(0, threshold - actual)} for metrics below threshold
  3. if gradient is empty AND k == 1:
       - abort with exit 0, message "nothing to refine"
  4. prepare workspace_k:
       - mkdir <workspace_k>
       - hard-link (fallback: copy) prior FINAL/ → workspace_k/input/
       - write workspace_k/gradient_input.json (see §4)
  5. spawn AgentWorkflow:
       task         = seed.run_completion.task
       inputs       = {"prior_deliverable_path": "input/"}
       initial_state= {"refinement_gradient": <gradient dict>,
                       "refinement_iteration": k,
                       "seed_run_id": <seed id>}
       output_dir   = workspace_k
       budget       = budget_for_iteration(seed_budget, k)   # see §5
       model        = refine_cli_model OR seed.model
       worker_model = refine_cli_worker OR seed.worker_model
       tags         = ["refinement", f"refine-iter-{k}"] + seed.tags
       parent_run_id = iter_{k-1}.run_id if k > 1 else seed.run_id
  6. manager's first PLAN receives REFINEMENT CONTEXT prefix (§4.2).
     Subsequent manager calls do NOT receive the prefix — the intention
     is persisted into plan/state by the first PLAN.
  7. loss_k = compute_run_loss(workspace_k)
  8. acceptance:
       - if loss_k < best_loss: best_iter = k; best_loss = loss_k; regression_counter = 0
       - else: regression_counter += 1
  9. stop conditions (any → break loop):
       - regression_counter >= 2
       - |loss_k - loss_{k-1}| < 0.01 for 2 consecutive iterations (plateau)
       - cumulative_wall_time >= 2 × seed.observed_wall_time
       - k == N
10. finalize:
      - update seed's refinement_sessions/<session_ts>.json with iteration list + best_iter
      - update seed's BEST/ pointer (symlink or manifest) to best iteration's FINAL/
      - return RefinementResult
```

---

## 4. Gradient Extraction and Injection

### 4.1 `RefinementGradient` structure

Persisted to `workspace_k/gradient_input.json`:

```json
{
  "iteration": 2,
  "seed_run_id": "run_abc123",
  "prior_run_id": "run_def456",
  "prior_loss": {
    "total": 0.47,
    "raw_signals": { "eval_score": 0.62, "critique_score": 0.55, "gate_rejection_count": 3 }
  },
  "defects": [
    { "summary": "Section 3 missing required citations", "severity": "high", "evidence": "critique.defects[0]" }
  ],
  "rejected_gates": [
    { "gate": "deliverable_presence", "reason": "section_3_incomplete", "ts": "2026-04-19T12:34:56Z" }
  ],
  "eval_deltas": {
    "structural_completeness": 0.25,
    "factual_accuracy": 0.10
  }
}
```

Schema validation via a Pydantic model in `gradient.py`. Missing sections (e.g. no critique configured in seed) degrade gracefully to empty lists — they do not raise.

### 4.2 Manager prompt prefix

The refinement prefix is a **deterministic string** (not LLM-generated) built by `gradient.py::render_refinement_prefix`. It is injected into the manager's **first PLAN call only** via a new `AgentWorkflow` parameter `manager_prompt_prefix: str | None`. Subsequent manager calls in the same run do not see the prefix; by then the intention is represented in plan + state.

Template:

```
## REFINEMENT CONTEXT

You are refining an existing deliverable for the task below.

Prior deliverable is available at: input/
Prior loss: {prior_loss.total:.3f}
  - eval_score:   {raw_signals.eval_score:.3f}
  - critique:     {raw_signals.critique_score:.3f}
  - gate rejects: {raw_signals.gate_rejection_count}

Defects identified by prior critique:
{for d in defects: - [{d.severity}] {d.summary}}

Rejected gates in prior run:
{for g in rejected_gates: - {g.gate}: {g.reason}}

Metric gaps to close:
{for m, gap in eval_deltas: - {m}: +{gap:.2f} needed}

Objective: produce an improved deliverable that reduces total loss.
Preserve what works; fix what the gradient identifies above.
Do not rewrite from scratch — iterate on the prior deliverable in input/.
```

If a section's data is empty, the whole section (header + bullets) is omitted.

---

## 5. Budget, Stop Conditions, and Loss

### 5.1 Budget per iteration

`budget_for_iteration(seed_budget: BudgetEnvelope, k: int) -> BudgetEnvelope`:

- `max_loops` → `ceil(seed.max_loops * 0.5)`
- `max_total_workers` → `ceil(seed.max_total_workers * 0.5)`
- `max_total_tokens` → `seed.max_total_tokens // 2`
- `max_wall_time` → `seed.observed_wall_time * 0.5` (read from `run_completion.json`, not the budget cap)
- `max_depth` → `seed.max_depth` (unchanged — depth is a structural limit, not a cost)
- Other fields → inherited unchanged

All halving rounds with `ceil` for counts and floor for bytes/seconds, floored at 1 for counts and 60 s for wall time.

### 5.2 Stop conditions

| Condition | Default | Tunable |
|-----------|---------|---------|
| max iterations | 3 | `--iterations` (clamped to `[1, 10]`) |
| regression (loss increased) | stop after 2 consecutive | fixed |
| plateau (`\|Δloss\| < 0.01`) | stop after 2 consecutive | fixed |
| cumulative wall time | ≤ 2 × seed.observed_wall_time | fixed |
| empty gradient at iter 1 | immediate abort with exit 0 | fixed |

Stop reason is recorded in `refinement_sessions/<ts>.json.stop_reason` as one of:
`max_iterations | regression | plateau | wall_time_exhausted | empty_gradient`.

### 5.3 Loss accounting

`compute_run_loss` from `awp.outer_loop.loss` is reused unchanged. The refinement loop calls it on each iteration's `run_dir`. No weight customization — refinement uses the default `LossWeights`.

### 5.4 Best-iteration pointer

The loop maintains `best_iter` (defaults to `0`, meaning "seed wins"). After the final iteration:

- `<seed_run_dir>/BEST/` is created as a directory containing a `manifest.json` that names the winning run:
  ```json
  { "best_run_id": "run_iter_2", "best_loss": 0.31, "seed_loss": 0.47, "session_id": "refine_20260419T153000Z" }
  ```
  Plus hard-links (fallback: copies) of every file from the winning run's `FINAL/` directory. This is the canonical output consumers should read.

- `<seed_run_dir>/refinement_sessions/<session_ts>.json` records the full iteration history:
  ```json
  {
    "session_id": "refine_20260419T153000Z",
    "seed_run_id": "run_abc123",
    "iterations": [
      { "k": 1, "run_id": "run_iter_1", "loss": 0.42, "status": "partial" },
      { "k": 2, "run_id": "run_iter_2", "loss": 0.31, "status": "complete" }
    ],
    "best_iter": 2,
    "stop_reason": "max_iterations",
    "started_at": "...",
    "completed_at": "..."
  }
  ```

Multiple refine sessions against the same seed are allowed; each gets its own `<session_ts>.json`. `BEST/` is overwritten only if the new session produces a better loss than the current `BEST/`.

---

## 6. Storage Model: Independent Experiments with `parent_run_id`

### 6.1 Decision

Each refinement iteration is a **standalone experiment** in the experiment DB, linked to its predecessor via `metadata.parent_run_id`. Iterations do NOT live inside the seed run's directory.

Rationale:

- Consistent with the existing experiment model — the DB already supports parent/child links.
- Seed run directory remains immutable after completion (except for the small sidecar files in `refinement_sessions/` and `BEST/`).
- UI can render the refinement chain as a hierarchy without schema changes.
- Clean archival / deletion: removing an iteration does not corrupt the seed.

### 6.2 Disk layout

```
/tmp/awp-experiments/
├── run_abc123/                        # seed run (unchanged, pre-existing)
│   ├── run_completion.json
│   ├── events.jsonl
│   ├── FINAL/
│   ├── refinement_sessions/           # NEW: sidecar written by refine loop
│   │   └── refine_20260419T153000Z.json
│   └── BEST/                          # NEW: canonical post-refine output
│       ├── manifest.json
│       └── <deliverable files…>
│
├── run_iter_1/                        # iteration 1 experiment (own run)
│   ├── run_completion.json
│   ├── events.jsonl
│   ├── FINAL/
│   ├── input/                         # hard-linked from seed/FINAL
│   └── gradient_input.json
│
└── run_iter_2/                        # iteration 2 experiment (own run)
    ├── ...
    ├── input/                         # hard-linked from iter_1/FINAL
    └── gradient_input.json
```

### 6.3 Experiment DB fields

Each iteration's experiment row carries:

| Field | Value |
|-------|-------|
| `parent_run_id` | seed run's id (k=1) or previous iteration's id (k>1) |
| `tags` | `["refinement", "refine-iter-<k>"] + seed.tags` |
| `refinement_session_id` | same for all iterations in one session |
| `refinement_iteration` | `k` |

`parent_run_id` is stored via the existing experiment metadata channel; no schema migration required if the field already exists. If it does not exist on the current schema, adding it is a trivial additive column — included as a prerequisite task in the implementation plan.

---

## 7. New Normative Rule: R36

**R36 (Refinement Gradient Required).** A refinement iteration MUST have a non-empty `gradient_input.json` present in its workspace before the first manager call. If the gradient is empty (no defects, no rejected gates, no eval deltas), the iteration MUST NOT be dispatched; the refinement loop aborts with exit 0 and message `"nothing to refine"`.

Rationale: prevents zero-signal reruns — a refinement call against an already-perfect run is a waste of budget and muddies loss attribution.

Enforcement:

- In `refinement.loop.RefinementLoop._prepare_iteration`: gradient is built, serialized, and the non-emptiness check runs before `AgentWorkflow` is constructed.
- `awp validate` is not extended — R36 is a runtime rule, not a static schema rule (consistent with how R33/R34/R35 fire at runtime).

Spec text added to `spec/` in the same commit as the code.

---

## 8. Error Handling

| Condition | Handling |
|-----------|----------|
| Seed run dir missing | exit 2, message `"seed run not found: <path>"` |
| `run_completion.json` unreadable / malformed | exit 2, message includes parse error |
| Seed has no `FINAL/` directory | exit 2, message `"seed has no deliverable to refine"` |
| Empty gradient at k=1 | exit 0, message `"nothing to refine"` (not an error) |
| Iteration raises mid-run | record iteration as `status: "failed"` in session JSON, apply it to stop logic (a failed iteration counts as a regression), continue to next iteration unless regression cap hit |
| Hard-link fails (cross-device) | fall back to copy, log once per session |
| Budget math produces values below floor | clamp to floor (1 for counts, 60 s for wall-time), log warning |
| Experiment DB write fails | abort iteration, surface error (consistent with existing `AgentWorkflow` behavior) |

---

## 9. Testing

### 9.1 Unit tests

In `packages/awp-runtime/tests/refinement/`:

- `test_gradient.py` — gradient extraction from synthetic `run_completion.json` fixtures: all sections populated, partial, empty, malformed; prefix rendering for each.
- `test_loop_stop_conditions.py` — stop logic via a stubbed workflow factory that returns scripted loss sequences: max iterations, regression, plateau, wall-time, empty gradient.
- `test_best_pointer.py` — `BEST/` manifest and hard-link/copy fallback.
- `test_budget_scaling.py` — `budget_for_iteration` math, including floor clamping.
- `test_r36.py` — empty gradient aborts before `AgentWorkflow` is instantiated.

### 9.2 Integration tests

- `test_refine_cli.py` — end-to-end via `awp refine` against a recorded seed fixture using a stubbed LLM that returns scripted improvements.

### 9.3 E2E test (MANDATORY per CLAUDE.md §E2E)

`packages/awp-runtime/tests/e2e/test_e2e_refinement.py`:

1. Run a seed task that deterministically lands at `partial` — a bilingual paper prompt with a critique-detectable defect (e.g., a missing required section).
2. Invoke `awp refine <seed_run> --iterations 2` with real LLM calls.
3. Assertions:
   - `compute_run_loss(BEST/run_dir) < compute_run_loss(seed_run_dir)`
   - `BEST/manifest.json.best_iter >= 1`
   - `BEST/` contains the expected deliverable structure
   - Each iteration exists as an independent experiment row with `parent_run_id` chain seed → iter_1 → iter_2
   - Full LLM trace persisted per iteration
4. Tags: `["e2e", "refinement", "critique"]`.

Budget for the E2E: ≥ 25 loops / 3M tokens / 1h wall-time total across the whole refinement session (per the gpt-5-nano-limits memory).

### 9.4 Regression tests (existing suite)

No existing test should change behavior. Specifically:

- `awp optimize` tests: unchanged. Refinement code is not imported by the outer loop.
- `awp run` tests: unchanged. `manager_prompt_prefix` is an optional new parameter on `AgentWorkflow`; default `None` preserves existing behavior byte-for-byte.
- DAG engine and delegation loop tests: unchanged.

---

## 10. Documentation Sync (per CLAUDE.md §2)

In the same commit as the code:

| File | Change |
|------|--------|
| `CLAUDE.md` | New "Refinement Mode" bullet in Key Protocols. New `awp refine` entry in Development Commands. New row in the §2 sync table for "refinement changes → refinement.md". |
| `docs/refinement.md` | **NEW** — full protocol: data flow, gradient extraction, stop conditions, storage model, R36. Authoritative. |
| `README.md` | One-paragraph mention of refinement mode under the outer-loop section. |
| `README_NERD.md` | Same, slightly expanded with the θ/y framing. |
| `skill/SKILL.md` | `awp refine` entry in Commands Reference; short note on when to recommend it. |
| `spec/` | R36 inserted into the rules section with rationale. |
| `docs/e2e.md` | New tag `refinement` added to the tag list. |

Gates that must pass before commit:

- `scripts/check_docs_drift.py` → exit 0
- `scripts/check_sync_coverage.py` → exit 0
- `scripts/check_mirror_drift.py` → exit 0 (new files under `packages/awp-runtime/src/awp/refinement/` must be mirrored to `reference/python/src/awp/refinement/`)

---

## 11. Out of Scope (YAGNI)

Explicitly deferred; not part of this spec or its implementation plan:

- User-supplied refinement prompt (brainstorm option b/c) — only the critique-derived gradient is used.
- Prompt (θ) updates during refinement — θ is frozen; `awp optimize` and `awp refine` do not interact in one command.
- Composition (`awp optimize --refine-between-epochs`) — separate follow-up if requested.
- UI surface in `awp-ui` — "Refine this run" button can be added later; the CLI is the canonical entrypoint.
- Parallel iterations — iterations run strictly sequentially.
- Cross-task refinement — each refine session targets exactly one seed run.
- Custom loss weights per refinement — defaults only.
- Resume / continuation of a partial refinement session — each invocation is a fresh session (sessions are additive, not mutable).

---

## 12. Implementation Order (preview; detailed plan will come from `writing-plans`)

1. **Prereq:** confirm experiment DB supports `parent_run_id` on experiment rows; add if missing.
2. `gradient.py` + unit tests.
3. `seed.py` + unit tests (hard-link, copy fallback, clean workspace).
4. `loop.py` — `RefinementLoop` with stubbed workflow factory + unit tests for stop conditions, budget scaling, best-pointer.
5. `manager_prompt_prefix` parameter on `AgentWorkflow` (`awp.data.workflow`) + unit test showing it only reaches the first PLAN.
6. `awp refine` CLI command + integration test.
7. R36 enforcement + spec text.
8. Docs: `docs/refinement.md`, `CLAUDE.md`, `README.md`, `README_NERD.md`, `skill/SKILL.md`, `spec/`, `docs/e2e.md`.
9. Mirror sync to `reference/python/src/`.
10. E2E test `test_e2e_refinement.py` — run, debug via trace, until green.
11. Full test suite green; drift/sync/mirror gates green.
12. Commit.

PyPI release: NOT part of this spec. A release is triggered separately once this lands on `main` and an E2E against the published wheel is green.

---

## 13. Open Questions

None at spec-approval time. All brainstorm decisions captured:

- Mode: Option A (full delegation loop, task-local refinement). ✓
- Gradient source: (a) critique + gate + eval only, no user prompt. ✓
- Storage: independent experiments linked by `parent_run_id`. ✓

If the implementation surfaces blockers (e.g., `parent_run_id` schema gap wider than expected), the plan will flag them for user decision before proceeding past the prereq step.
