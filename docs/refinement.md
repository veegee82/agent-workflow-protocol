# AWP Refinement Mode

`awp refine` iteratively refines a completed run's deliverable using
critique defects, gate rejections, and eval deltas as the gradient.
It is orthogonal to `awp optimize` (which optimizes prompt artifacts
across a task suite) — refinement optimizes a single task's output
(y), not the policy (θ). The two commands do not share state and do
not interact in one invocation.

## When to use it

- A run completed with `status: partial` and a critique that flagged
  real defects.
- A run whose eval score is below threshold on one or more metrics.
- A run whose gate chain rejected COMPLETE attempts for reasons
  visible in `events.jsonl`.

## When NOT to use it

- The seed run completed with `status: complete` AND every eval metric
  above threshold AND zero critique defects. R36 aborts the call with
  exit 0 and message `"nothing to refine"`.
- You want to improve the *policy* for future runs — use
  `awp optimize` instead.

## CLI

    awp refine <seed_run_dir> [--iterations N] [--model M] [--worker-model M]

Exit codes:

| Code | Meaning |
|------|---------|
| `0`  | Improvement produced; `BEST/` updated. Also: empty gradient (nothing to do). |
| `1`  | No iteration improved loss. Seed still wins. |
| `2`  | Setup failure: seed missing / unreadable / no `FINAL/`. |

## Data flow

1. Read `<seed>/run_completion.json` + `<seed>/events.jsonl`.
2. Build `RefinementGradient` (defects, last 3 gate rejects, eval deltas).
3. R36 check — abort if gradient is empty.
4. For each iteration `k ∈ [1..N]`:
   1. Hard-link `<prior>/FINAL/` into `<workspace_k>/input/`.
   2. Persist `<workspace_k>/gradient_input.json`.
   3. Spawn `AgentWorkflow` with halved budget and the gradient prefix
      injected into iteration-1's manager user message.
   4. Compute loss via `compute_run_loss`.
   5. Apply stop-condition state machine.
5. Write `<seed>/refinement_sessions/<ts>.json` sidecar.
6. If improvement: update `<seed>/BEST/` (manifest + hard-linked files).

## Storage

- **Iteration run directory:** standalone experiment (usually under
  `/tmp/awp-experiments/refine_<ts>/iter_<k>/`) — an independent run
  with `parent_run_id` pointing at the prior iteration or the seed.
- **Session sidecar:** `<seed>/refinement_sessions/<session_id>.json`
  — records iteration list, best_iter, stop_reason.
- **BEST pointer:** `<seed>/BEST/` — hard-linked copy of the best
  iteration's `FINAL/` with `manifest.json` naming the winner. Only
  overwritten if a future session produces a lower loss than the
  incumbent.

## Stop conditions

| Condition | Trigger |
|-----------|---------|
| `max_iterations` | `k == N` |
| `regression` | `loss` rose vs. previous iter for 2 consecutive iterations |
| `plateau` | `|Δloss| < 0.01` for 2 consecutive iterations |
| `wall_time_exhausted` | cumulative wall-time ≥ 2 × seed observed wall-time |
| `empty_gradient` | R36 fires (only at iter 1) |
| `empty_gradient_midloop` | gradient went empty at iter k>1 (iteration ran succeeded completely) |

## Budget halving

Per iteration, counts (loops, workers, tool calls) are halved with
`ceil` and floored at 1; tokens are halved and floored at 1; wall-time
is halved from the seed's **observed** wall time and floored at 60 s;
depth is unchanged.

## R36 (normative)

A refinement iteration MUST have a non-empty `gradient_input.json`
before dispatch. See `spec/versions/1.0/validation-rules.md` for the
full rule text.

## Manager prefix injection

The refinement prefix is prepended to the manager's user message on
iteration 1 only. Both the inline manager path
(`_run_inline_manager`) and the agent-based path (`_run_manager`) in
`DelegationLoopRunner` honor this guard. Subsequent iterations see the
vanilla user message — by then the refinement intention is carried in
the plan and state.

## Relationship to `awp optimize`

`awp optimize` is SGD over θ (prompt artifacts) with rollback on mean
loss regression. `awp refine` is test-time inference-compute scaling
over y (deliverable) with best-iter tracking. Neither imports the
other; running one does not affect the other's state.
