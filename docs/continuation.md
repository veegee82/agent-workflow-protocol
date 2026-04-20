# Continuation Mode (y-axis carry-over across tasks)

## What it is

Continuation mode lets a task reuse the prior task's deliverable as
starting material, combined with user feedback as the learning signal.
It is the runtime counterpart of the experiment-task hierarchy
(`docs/superpowers/specs/2026-04-20-experiment-task-hierarchy-design.md`)
for the user-task axis — distinct from refinement (`docs/refinement.md`,
y-optimisation within a single run) and outer-loop optimisation
(`docs/outer-loop.md`, θ-optimisation over prompt artifacts).

## Mental model

```
Task 001 (seed)  →  Task 001/BEST/paper.md
                         │
                         ▼
Task 002 (continuation, inputs=[{from_task:001,role:primary,bundle:BEST/}])
     user_feedback = "deepen section 2, add benchmarks"
     │
     ▼
  manager_prompt_prefix = render_continuation_prefix(bundle, feedback)
     │
     ▼
  AgentWorkflow(manager_prompt_prefix=…)
     │
     ▼ Task 002 Manager sees prior draft + feedback at iteration 1
  Task 002 produces evolved deliverable, NOT re-derived from scratch.
```

## Mechanism

1. **`task.json.inputs`** is non-empty (R37). Each entry has
   `from_task`, `role ∈ {primary, reference}`, and exactly one of
   `bundle: "BEST/"` or `paths: [...]`.
2. **`load_continuation_bundle(task_dir, experiment_dir)`** resolves
   each entry against `<experiment>/tasks/<from_task>/BEST/`. Primary
   entries inline the file contents; reference entries carry only
   path + size + first 200 chars.
3. **`render_continuation_prefix(bundle, max_chars=480_000)`** builds
   a deterministic prefix:
   - `## Continuation Context`
   - `### Prior deliverable (primary)` — each primary inlined
   - `### Reference material (available via fs.read)` — list, optionally dropped
   - `## User Feedback` — verbatim
   - `## Your Task` — build-on-prior boilerplate
4. **Budget fallback ladder.** Full → reference-stubs → no-reference →
   `ContinuationBudgetError` (primary alone over budget → split the task).
5. **CLI dispatch.** `awp run --target <exp>:<cont-task>` detects
   `mode=="continuation"`, calls the loader, renders the prefix, and
   passes it as `AgentWorkflow(manager_prompt_prefix=…)`. The
   `DelegationLoopRunner` (already plumbed for refinement) prepends
   the prefix to the Manager's iteration-1 user message.

## Relationship to refinement

Refinement (`docs/refinement.md`) also injects a prefix, but:
- Scope = one run, multiple iterations (y-axis within a run).
- Gradient = auto-extracted from critique + gate rejections + eval deltas.
- Prefix is applied to iteration 1 of the refinement session's run.

Continuation:
- Scope = task → next task (y-axis across tasks).
- Gradient = user-written feedback (free text).
- Prefix is applied to iteration 1 of the next task's seed run.

Both mechanisms can compose: a continuation task's seed run can also
be refined, and the refinement engine's prefix will overlay on top of
whatever state the continuation prefix produced in iteration 1.

## R37

Continuation tasks with empty `inputs` are rejected at task-create
time and at runtime (bundle loader refuses without BEST). See
`spec/versions/1.0/validation-rules.md`.

## Files

- `packages/awp-runtime/src/awp/continuation/bundle_loader.py` — `load_continuation_bundle`
- `packages/awp-runtime/src/awp/continuation/prompt_injection.py` — `render_continuation_prefix`
- `packages/awp-core/src/awp/experiment/cli_handlers.py` — CLI dispatch (`run_task_aware`)

## See also

- `docs/refinement.md` — y-axis optimisation within a single run (auto-extracted gradient). Continuation is the cross-task analogue.
- `docs/outer-loop.md` — θ-axis optimisation over prompt artifacts. Runs per-experiment after Plan 4.
- `docs/superpowers/specs/2026-04-20-experiment-task-hierarchy-design.md` — the design this mechanism implements, §7.1–§7.4.
- `spec/versions/1.0/validation-rules.md` — R37 (continuation input non-emptiness).
