# Refinement Model Tiers (low / mid / high) — Design

**Status:** draft → for review
**Date:** 2026-04-20
**Author:** Claude (Protocol Steward) + user
**Scope:** `awp refine` (y-axis SGD). Outer loop (`awp optimize`) is explicitly out of scope.
**Depends on:** `docs/refinement.md`, `docs/outer-loop.md`
**New rule:** none (see §11)

---

## 1. Motivation

Refinement is a task-local SGD loop: every iteration is a forward pass with
a halved budget, and the gradient is a deterministic text prefix built from
critique defects + gate rejections + eval deltas. Today all iterations run
with a **single** `(manager_model, worker_model)` pair chosen at session
start.

The ML-lens reading of the loop says otherwise. Model strength ≈ gradient
precision (inverse-noise). Refinement has diminishing returns — the
residual loss shrinks per iteration — so you want the most precise model
where the residual is smallest, i.e. late. Early iterations can tolerate a
weaker, cheaper model; they surface structural defects for the gradient
extractor, which feeds them to a stronger late model. This matches
coarse-to-fine annealing.

This spec adds that dimension: three ordered **tiers** (`low`, `mid`,
`high`), each a `{manager, worker}` pair, mapped across the N iterations so
that *low runs early, high runs late*.

---

## 2. Non-goals

- Outer loop (`awp optimize`) is **not** extended in this spec. Its
  `manager_model` / TextGrad-optimizer-model remains a single value. A
  follow-up spec may revisit this once refinement tiers have production
  runs behind them.
- No change to the agent output contract (R17), no change to R36, no new
  R-rule.
- No dynamic per-iter model selection based on observed loss. The mapping
  is fixed at session start. Dynamic selection is out of scope; fixed
  mapping keeps the session reproducible and the sidecar deterministic.
- No tier semantics for `awp run` (the base delegation loop). Tiers are a
  refinement-loop concept only.

---

## 3. Mental model

```
iteration index k ∈ 1..N
                     ┌──────────────┬──────────────┬──────────────┐
                     │   low        │   mid        │   high       │
budget per iter      │ halved + …   │ halved + …   │ halved + …   │
model precision      │ noisy        │ medium       │ precise      │
loss reduction goal  │ structural   │ residual     │ polish       │
                     │ defects      │ defects      │              │
                     └──────────────┴──────────────┴──────────────┘
```

Why low→high and not the reverse:

1. **Diminishing-returns match.** Residual shrinks per iter, so precision
   matters most late.
2. **Gradient visibility.** Weak early models *produce* the defects the
   gradient extractor needs; a strong early model may silently paper them
   over and starve the loop of signal.
3. **Budget halving cooperates.** Weakest tier has the largest budget
   headroom; strongest tier operates on the smallest residual where the
   halved budget is still ample.
4. **Stop-conditions fire early.** Plateau / regression kill the loop
   around iteration 3–5. Thirds mapping (see §5) guarantees that each
   tier gets at least one iteration before the first realistic abort.

---

## 4. Decisions locked in this spec

| # | Decision | Chosen option |
|---|---|---|
| 1 | Iter → tier mapping | **A (Thirds, proportional)** — see §5 |
| 2 | Tier scope (what's tiered) | **C (coupled {manager, worker} per tier)** — 6 inputs, grouped as 3 pairs |
| 3 | Config location | **C (hybrid)** — defaults in `SettingsPanel`, per-session override in `RefineModal` |
| 4 | Empty-tier fallback | **B (fall back to seed's model)** — matches today's "empty = seed" semantics |
| 5 | Outer loop coverage | **A (refinement only)** — outer loop deferred |
| 6 | Implementation shape | **γ (TierPlan object + `awp.refinement.tiers` module)** |

---

## 5. Tier-mapping algorithm (the pure function)

```
low_end    = ceil(n / 3)
high_start = n - floor(n / 3) + 1

if k <= low_end:    tier = "low"
elif k >= high_start: tier = "high"
else:               tier = "mid"
```

Special cases (explicit, not derived from the formula):

- `N = 1` → `[high]`. A single-iteration refinement deserves maximum
  precision; weak-only offers no tiering benefit.
- `N = 2` → `[low, high]`. Mid is dropped; two iterations can't
  meaningfully express three tiers.

Full table, `N ∈ [1, 10]`:

| N  | Mapping                              | low | mid | high |
|----|--------------------------------------|-----|-----|------|
| 1  | H                                    | 0   | 0   | 1    |
| 2  | L, H                                 | 1   | 0   | 1    |
| 3  | L, M, H                              | 1   | 1   | 1    |
| 4  | L, L, M, H                           | 2   | 1   | 1    |
| 5  | L, L, M, M, H                        | 2   | 2   | 1    |
| 6  | L, L, M, M, H, H                     | 2   | 2   | 2    |
| 7  | L, L, L, M, M, H, H                  | 3   | 2   | 2    |
| 8  | L, L, L, M, M, M, H, H               | 3   | 3   | 2    |
| 9  | L, L, L, M, M, M, H, H, H            | 3   | 3   | 3    |
| 10 | L, L, L, L, M, M, M, H, H, H         | 4   | 3   | 3    |

**Invariants** (unit-testable):

- For all `N ≥ 3`: each tier has at least one iteration.
- The mapping is monotonic: once a later-tier iteration has fired, no
  earlier-tier iteration follows.
- `count(low) ≥ count(mid) ≥ count(high)` for every `N ≥ 3` — early
  exploration dominates late polish.

---

## 6. `TierPlan` — the boundary object

New module: `packages/awp-runtime/src/awp/refinement/tiers.py`.

```python
from __future__ import annotations
import math
from pydantic import BaseModel
from typing import Literal, Optional


class ModelPair(BaseModel):
    """One tier's (manager, worker) model configuration.

    Either field may be None/empty → the resolver falls back to the seed's
    corresponding model (§7).
    """
    manager: Optional[str] = None
    worker:  Optional[str] = None


TierLabel = Literal["low", "mid", "high"]


class TierResolution(BaseModel):
    """What RefinementLoop actually passes to the factory per iteration."""
    tier:          TierLabel
    manager_model: Optional[str]
    worker_model:  Optional[str]


class TierPlan(BaseModel):
    """Immutable resolution plan for one refinement session.

    Constructed at the API / CLI boundary from user config + seed models.
    RefinementLoop consumes it as a read-only plan; the Plan does not
    perform I/O and has no runtime dependencies beyond pydantic + math.
    """
    low:  ModelPair = ModelPair()
    mid:  ModelPair = ModelPair()
    high: ModelPair = ModelPair()
    seed_manager: Optional[str] = None
    seed_worker:  Optional[str] = None

    def tier_for(self, k: int, n: int) -> TierLabel:
        if n <= 0 or k < 1 or k > n:
            raise ValueError(f"invalid (k, n) = ({k}, {n})")
        if n == 1:
            return "high"
        if n == 2:
            return "low" if k == 1 else "high"
        low_end    = math.ceil(n / 3)
        high_start = n - (n // 3) + 1
        if k <= low_end:
            return "low"
        if k >= high_start:
            return "high"
        return "mid"

    def for_iteration(self, k: int, n: int) -> TierResolution:
        tier = self.tier_for(k, n)
        pair = getattr(self, tier)  # ModelPair
        return TierResolution(
            tier=tier,
            manager_model=(pair.manager or None) or self.seed_manager,
            worker_model =(pair.worker  or None) or self.seed_worker,
        )

    def is_trivial(self) -> bool:
        """True iff all three tiers resolve to the seed — no tiering in effect."""
        return not any([
            self.low.manager,  self.low.worker,
            self.mid.manager,  self.mid.worker,
            self.high.manager, self.high.worker,
        ])
```

**Why a dataclass and not three parameters on `RefinementLoop`:** the plan
is a cohesive unit built at the boundary and consumed read-only. Threading
three separate dicts through the call chain would leak structure that
belongs inside one object (and make logging/serialization duplicate-prone).

---

## 7. Fallback semantics (empty tier field)

For a tier `T` and an iteration resolving to that tier:

```
resolved_manager = T.manager if T.manager else seed_manager
resolved_worker  = T.worker  if T.worker  else seed_worker
```

Consequences:

- User fills only `high.manager = "gpt-5.4"` → `high` iterations use
  `gpt-5.4` manager with seed's worker; `low` and `mid` iterations use
  seed's manager + worker entirely. Cheapest way to say "upgrade only the
  last third".
- User fills all three tiers completely → full custom tiering.
- User fills nothing (all fields empty) → `TierPlan.is_trivial()` is True
  and the caller can choose to fall through to the legacy `model` /
  `worker_model` path (see §8).

---

## 8. `RefinementLoop` change

Signature delta:

```python
class RefinementLoop:
    def __init__(
        self,
        *,
        seed_run_dir: Path,
        workflow_factory: WorkflowFactory | None = None,
        iterations_root: Path | None = None,
        model: str | None = None,           # unchanged — legacy single-model path
        worker_model: str | None = None,    # unchanged
        tier_plan: TierPlan | None = None,  # NEW
    ) -> None:
        ...
```

Inside `run()`, the single change is in the iteration loop body where the
factory is called:

```python
if self._tier_plan is not None:
    resolved = self._tier_plan.for_iteration(k, iterations)
    iter_manager = resolved.manager_model
    iter_worker  = resolved.worker_model
    iter_tier    = resolved.tier
else:
    iter_manager = self._model
    iter_worker  = self._worker_model
    iter_tier    = None  # logged as null in sidecar

run_id, run_dir = self._factory(
    ...,
    model=iter_manager,
    worker_model=iter_worker,
)
```

The `IterationOutcome` dataclass gains three fields (all optional for
backward-compat with existing session readers):

```python
@dataclass
class IterationOutcome:
    k: int
    run_id: str
    run_dir: Path
    loss: float
    status: str
    parent_run_id: str
    tier: TierLabel | None = None          # NEW
    model_manager: str | None = None       # NEW
    model_worker:  str | None = None       # NEW
```

`RefinementSession` and `RefinementIteration` mirror these optional fields
in the sidecar JSON writer.

**Invariant:** when `tier_plan is None`, the factory is called with
identical arguments as today. Test evidence: `test_refinement_loop.py`
runs unchanged.

---

## 9. Config shape (UI + store)

### 9.1 `workflowStore.ts` — new `DEFAULT_CONFIG` keys

```typescript
export type ModelPair = { manager: string; worker: string };

// Added to DEFAULT_CONFIG:
refinement_tier_low:  { manager: "", worker: "" },
refinement_tier_mid:  { manager: "", worker: "" },
refinement_tier_high: { manager: "", worker: "" },
```

Empty-string defaults keep the UI off-by-default: empty tiers + no modal
toggle = legacy behavior end-to-end.

### 9.2 `SettingsPanel.tsx` — new collapsible "Model Tiers" block

- Location: under the existing Optimizers section (same panel that hosts
  `refinement_default_iterations`).
- Default state: collapsed.
- Layout: 3 rows × 2 free-text inputs.
  ```
  ┌──────┬────────────────────────────┬──────────────────────────────┐
  │ Tier │ Manager                    │ Worker                       │
  ├──────┼────────────────────────────┼──────────────────────────────┤
  │ low  │ [ e.g. nemotron3 ]         │ [ e.g. deepseek-chat-v3.1 ]  │
  │ mid  │ [ e.g. openai/gpt-5-mini ] │ [ e.g. deepseek-chat-v3.1 ]  │
  │ high │ [ e.g. openai/gpt-5.4 ]    │ [ e.g. claude-sonnet-4-6 ]   │
  └──────┴────────────────────────────┴──────────────────────────────┘
  ```
- Placeholders show illustrative strings only; no dropdowns (per CLAUDE.md).
- Inputs persist into the workflow store on change (same mechanism as
  `refinement_default_iterations`).
- Help text below: "Low runs early, high runs late. Empty fields fall back
  to the seed run's model."

### 9.3 `RefineModal.tsx` — tiered-mode toggle

- New toggle above the existing Manager/Worker inputs: **"Use tiered
  models across iterations"** — default **off**.
- Off → modal renders identical to today: single Manager/Worker fields,
  request body omits `tier_*`.
- On → single Manager/Worker fields are hidden. 3 × 2 grid of tier inputs
  replaces them, pre-filled from the store (§9.1), per-session
  overridable. Request body includes `tier_low`, `tier_mid`, `tier_high`.
- Hint under grid: "Low = early iterations, high = late. Empty = seed's
  model."
- Toggle state is **per-session only** (local `useState`), not persisted
  to the workflow store. The persistent artifact is the three tier
  default pairs in §9.1; the toggle is a modal-local UI affordance for
  "opt in for this session."

---

## 10. API contract — `POST /api/experiments/<run_id>/refine`

Body schema (all new fields optional):

```json
{
  "iterations": 3,
  "model":        "...",
  "worker_model": "...",
  "tier_low":  {"manager": "...", "worker": "..."},
  "tier_mid":  {"manager": "...", "worker": "..."},
  "tier_high": {"manager": "...", "worker": "..."}
}
```

Backend resolution rule in `routes.start_refinement`:

1. If any of `tier_low`, `tier_mid`, `tier_high` is present in the body:
   - read seed `run_completion.json` to extract seed's manager + worker
   - build `TierPlan` with the user-supplied tiers and seed fallbacks
   - instantiate `RefinementLoop(tier_plan=plan, model=None, worker_model=None)`
2. Else (legacy path): instantiate `RefinementLoop(model=body.model,
   worker_model=body.worker_model, tier_plan=None)` — unchanged from today.

Validation:

- Missing `tier_*` → treated as absent (legacy path); no error.
- Present `tier_*` with empty `{"manager":"", "worker":""}` → accepted and
  results in seed-fallback for both roles (normal empty-field semantics).
- Both `model` / `worker_model` and any `tier_*` present → `tier_*` takes
  precedence; `model` / `worker_model` are **fully ignored** (not used
  as the baseline either — the seed's parsed model remains the fallback
  per §7). API logs a `logger.warning` with message
  `"refinement.mixed_body: tier_* set; ignoring legacy model/worker_model"`
  but returns 202 normally (no 4xx). Rationale: simpler contract, and
  the UI toggle design prevents mixed bodies in practice — mixed bodies
  only reach the backend through direct API callers, who can read the
  warning.

---

## 11. Observability — session sidecar extension

`<seed>/refinement_sessions/<session_id>.json` gains two levels of
optional fields:

Session level:

```json
"tier_plan_used": true   // NEW — false or absent on legacy sessions
```

Per iteration (non-breaking for readers that don't know these keys):

```json
{
  "k": 2,
  "run_id": "…",
  "loss": 0.35,
  "status": "partial",
  "tier": "mid",                          // NEW
  "model_manager": "openai/gpt-5-mini",   // NEW — resolved after fallback
  "model_worker":  "deepseek/deepseek-chat-v3.1"  // NEW — resolved
}
```

`RefinementSessionsList.tsx` renders `tier` as a small label next to each
iteration row when present, falls through silently when absent.

---

## 12. Error handling & edge cases

| Case | Behavior |
|---|---|
| `iterations = 1`, tiers set | Uses `high` (per §5). The other tiers are still sent in the body but never consulted. |
| `iterations = 2`, tiers set | Uses `{low, high}`. `mid` is in the body but never consulted. |
| Seed manager/worker can't be parsed from `run_completion.json` | `seed_manager` / `seed_worker` on `TierPlan` stay `None`. Empty tier → `None` passed to `AgentWorkflow`, which then applies its own default (same failure mode as today's "empty model" path). |
| User sets `tier_high.manager` to a non-existent provider string | Runtime surfaces it as an `AgentWorkflow` init error on that iteration. The session sidecar records it as `status: "error"` for that `k`; the refinement loop continues to the next iteration. (Matches today's error-handling contract.) |
| Client sends all three `tier_*` fields but every sub-field is empty | Backend still builds a `TierPlan` (because `tier_*` keys are present) and `TierPlan.is_trivial()` returns True. The loop runs under the tiered path, but every iteration resolves to `(seed_manager, seed_worker)` — functionally equivalent to the legacy path. `tier_plan_used` is recorded `true` (tiered code path was exercised); every iteration's `tier` field is still populated per §5, which makes the session explicable even if no model changes. No error. |
| Mid-session swap of the store config | Does not affect running sessions — the plan is captured at session start. |

---

## 13. Tests

### 13.1 Unit — `packages/awp-runtime/tests/refinement/test_tiers.py` (new)

- Parametrized `tier_for(k, n)` over all `n ∈ [1, 10]` and all valid `k`,
  compared against the table in §5. ~40 assertions.
- `for_iteration` with sparse tier configs:
  - only `high.manager` set → `low`/`mid` iters yield `seed_manager`;
    `high` iters yield user string + `seed_worker`.
  - all tiers fully set → no seed fallback anywhere.
  - all tiers empty + seed set → every iter resolves to seed pair.
- `is_trivial()` returns True for all-empty, False as soon as any tier
  field is non-empty.
- Invalid `(k, n)` pairs (k < 1, k > n, n ≤ 0) raise `ValueError`.

### 13.2 Integration — `packages/awp-runtime/tests/refinement/test_loop_tiered.py` (new)

- Fake `workflow_factory` records every `(model, worker_model)` it
  receives. Fixture seed with known loss > 0.
- Case A: `tier_plan=None` → factory receives `(session_model,
  session_worker)` on every iter (regression proof for legacy path).
- Case B: 3 iterations, tiers fully set → factory receives
  `(low_mgr, low_wkr)`, `(mid_mgr, mid_wkr)`, `(high_mgr, high_wkr)` in
  that order.
- Case C: 5 iterations, only `high` set → factory receives seed pair for
  iter 1–3, seed pair for iter 4, user's high pair for iter 5 (per §5
  table and §7 fallback).

### 13.3 Regression — existing tests run unchanged

- `tests/refinement/test_refinement_loop.py` — all cases keep passing
  without modification. This is the mechanical proof of stability
  contract #1 (purely additive).

### 13.4 UI — light touch

- `RefineModal`: assert that toggling "Use tiered models" hides the
  legacy fields and renders the 3×2 grid. Assert request body shape in
  both modes.
- `SettingsPanel`: assert the Tier block renders, inputs bind to the
  store.

### 13.5 E2E — mandatory

A new E2E is required before this work is considered done. Rationale:
per CLAUDE.md the E2E run is the forward pass and the only gate that
proves the full loop closes with real LLMs; tier routing changes *which
model executes each iteration*, which is exactly the kind of behavior
that unit + integration coverage cannot prove end-to-end.

**New test:** `packages/awp-runtime/tests/e2e/test_e2e_refinement_tiered.py`

- Tags: `["e2e", "refinement", "tiered"]`.
- Spec: a fictional refinement task against a seed run of sufficient
  residual loss that tiering can measurably affect the outcome (e.g.
  deliberately under-polished seed deliverable). N = 3 iterations so
  all three tiers fire exactly once (Table §5).
- Assertions:
  1. `refinement_sessions/<session>.json.tier_plan_used == true`.
  2. `iterations[0].tier == "low"`, `iterations[1].tier == "mid"`,
     `iterations[2].tier == "high"` (mapping correctness, §5).
  3. `iterations[k].model_manager` and `iterations[k].model_worker`
     match the TierPlan (resolved, including seed fallback).
  4. Terminal status of each iteration is in `{complete, partial}`.
  5. Session ends with `best_iter > 0` (improvement was achieved) —
     smoke assertion only; we don't require that `high` specifically
     wins, just that the tiered session produces a valid BEST pointer.
  6. LLM trace is persisted for every iteration (per CLAUDE.md §E2E
     Mandatory Properties).
- Actively monitored per CLAUDE.md; on stagnation, abort + diagnose +
  restart per the hard rule.

Plan-step coherence (per E2E-driven-plan guidance): the implementation
plan produced by `writing-plans` must show how each intermediate step
advances this E2E — e.g. step 1 (pure function) makes §5 table
verifiable in isolation; step 2 (loop integration) enables the
per-iteration tier assertion; step 3 (sidecar) enables assertions 1-3;
step 8 (mirror + build) is the final gate. The E2E itself is the last
step and the only step that closes the loop.

---

## 14. Doc-sync (per CLAUDE.md §2 sync table)

| Code change | MD updates |
|---|---|
| New module `awp/refinement/tiers.py` | `docs/refinement.md` — new §6.6 "Model Tiering" with full mapping table + fallback rule + cross-links |
| `RefinementLoop.__init__` gains `tier_plan` | `CLAUDE.md §Refinement Mode` — one new bullet line: *"Model tiering: low/mid/high via `TierPlan` (purely additive; legacy behavior preserved when `tier_plan=None`)"* |
| New config keys `refinement_tier_*` in store | `docs/refinement.md §6.6` — references `workflowStore.ts` and `SettingsPanel.tsx` paths |
| API body fields `tier_low/mid/high` | `docs/refinement.md §6.6` — new sub-table for body shape |
| Session sidecar keys `tier`, `model_manager`, `model_worker`, `tier_plan_used` | `docs/refinement.md §4` (Reading a session) — example JSON augmented with the new fields, explicitly marked optional |
| **No `spec/` change** | Confirmed: no new R-rule, R36 untouched. |
| **No `skill/SKILL.md` change** | Confirmed: skill doesn't generate refinement calls. |
| **No mirror gate issue** | Standard runtime edits; `reference/python/` mirrors on release as usual. |

---

## 15. Implementation order (stability-first)

1. **Pure function first.** Implement `tiers.py` with `TierPlan` and full
   unit tests (§13.1). Green before touching anything else.
2. **Loop integration.** Thread `tier_plan` through `RefinementLoop` and
   `IterationOutcome`. Add integration tests (§13.2). Verify legacy
   tests (§13.3) still pass unchanged.
3. **Session sidecar.** Extend `RefinementIteration` + `RefinementSession`
   writers with optional fields. Verify readers (incl. `RefinementSessionsList`)
   don't regress on old sessions.
4. **API layer.** Add body-field handling + `TierPlan` construction in
   `routes.start_refinement`. Add the precedence warning (§10).
5. **CLI layer.** Add `--tier-low`, `--tier-mid`, `--tier-high` flags
   (format `manager:worker`) to `cmd_refine`. Legacy flags untouched.
6. **UI layer.** Store keys → SettingsPanel block → RefineModal toggle +
   grid. UI tests (§13.4).
7. **Doc-sync.** Update `docs/refinement.md` and `CLAUDE.md` per §14.
   Run `scripts/check_docs_drift.py` + `scripts/check_sync_coverage.py`.
8. **Mirror + build.** Before any release, run
   `scripts/check_mirror_drift.py`. No release needed as part of this
   spec — release flow is separate.

Each step is independently revertible and each step closes with a green
gate. No step requires the next to compile.

---

## 16. Open questions for reviewer

None at the time of writing — the 5 clarifying questions in the
brainstorming session resolved the key structural choices (§4). If the
reviewer spots an ambiguity not pinned down here, flag it explicitly;
otherwise this spec transitions to `writing-plans`.
