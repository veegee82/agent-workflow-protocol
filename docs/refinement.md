# AWP Refinement Mode

Refinement mode (`awp refine`) is under construction. This file will be
replaced with the authoritative protocol doc in a later task of the
refinement-mode implementation plan (see
`docs/superpowers/plans/2026-04-19-awp-refine-mode.md`).

Scope preview:

- Task-local iterative refinement of a completed run's deliverable.
- Orthogonal to `awp optimize` (prompt-artifact SGD).
- Gradient = critique defects + last 3 gate rejections + eval deltas.
- New normative rule `R36` — non-empty gradient required before
  dispatching an iteration.
