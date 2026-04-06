# Reflective Critique Loop

AWP's critique system provides **automated quality analysis and targeted repair** for worker outputs within the delegation loop. While [evaluation](evaluation.md) scores the overall workflow result, critique operates at the individual worker level — diagnosing specific defects, prescribing fixes, and learning from failures across workers.

## Critique vs Evaluation

| Aspect | Critique | Evaluation |
|--------|----------|------------|
| Scope | Per-worker output | Per-workflow result |
| Question | "What's wrong with this output?" | "How good is the overall result?" |
| Output | Defect list + repair instructions | 0.0-1.0 score |
| Action | Targeted repair of specific defects | Retry/accept/fail the workflow |
| Location | `delegation_loop.critique` | `observability.evaluation` |
| Engine | A2+ (delegation loop only) | Any engine (DAG or delegation loop) |

Both can be enabled independently. When both are active, critique repairs happen **before** evaluation scoring.

## Configuration

Critique is configured under `orchestration.delegation_loop.critique` in `workflow.awp.yaml`:

```yaml
orchestration:
  engine: delegation_loop
  delegation_loop:
    critique:
      enabled: true
      mode: inline                    # "inline" or "dedicated"
      model: null                     # LLM model (null = inherit worker model)
      max_repair_attempts: 2          # Per-worker repair cycles
      repair_budget_fraction: 0.15    # Max 15% of total budget for repairs
      pattern_memory: true            # Accumulate cross-worker failure patterns
      defect_categories:
        - missing_data
        - wrong_format
        - incomplete
        - hallucinated
        - stale
        - policy_violation
```

When `enabled: false` (the default), critique is completely disabled and has zero runtime overhead.

### Configuration Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enabled` | bool | `false` | Enable/disable the critique system |
| `mode` | string | `"inline"` | `"inline"` (uses worker model, cheap) or `"dedicated"` (separate critic agent) |
| `model` | string | `null` | LLM model for the critic. `null` inherits from the worker model |
| `max_repair_attempts` | int | `2` | Maximum repair cycles per worker before escalation |
| `repair_budget_fraction` | float | `0.15` | Maximum fraction of total budget that can be spent on repairs |
| `pattern_memory` | bool | `true` | Accumulate failure patterns across workers within a run |
| `defect_categories` | list | see above | Types of defects the critic should diagnose |

## How It Works

### Critique Flow

  <img src="diagrams/inline-critique.svg" alt="critique diagram" width="100%"/>

### Defect Categories

| Category | Description | Typical Severity |
|----------|-------------|-----------------|
| `missing_data` | Required data absent from output | critical |
| `wrong_format` | Output format doesn't match contract | critical |
| `incomplete` | Partial result, missing sections | warning |
| `hallucinated` | Fabricated data or unsupported claims | critical |
| `stale` | Outdated information | warning |
| `policy_violation` | Violates workflow policies | critical |

### Severity Levels

- **critical** — Defect that makes the output unusable. Triggers repair.
- **warning** — Quality issue but output is usable. Included in repair if repair is triggered.
- **info** — Minor observation. Never triggers repair.

## Critique Scoring

### LLM Critic Scoring Bands

| Score Range | Assessment | Action |
|-------------|-----------|--------|
| 0.9-1.0 | Excellent, no critical defects | Accept |
| 0.6-0.89 | Acceptable with warnings | Accept (log warnings) |
| 0.3-0.59 | Needs repair, critical defects present | Trigger repair |
| 0.0-0.29 | Fundamentally broken | Escalate to manager |

### Heuristic Fallback

When no LLM is available, a deterministic heuristic runs instead:

| Check | Penalty | Severity |
|-------|---------|----------|
| Missing confidence field | -0.3 | critical |
| Low confidence (< 0.3) | -0.2 | warning |
| Error field present | -0.4 | critical |
| Required field missing | -0.2 each | critical |
| Empty string in field | -0.1 each | warning |

Score starts at 1.0, penalties are subtracted, result is clamped to [0.0, 1.0].

## Pattern Memory

When `pattern_memory: true`, the critique engine accumulates failure patterns across all workers in a run.

### How Patterns Work

1. After each critique, `reusable_patterns` from the CritiqueEnvelope are recorded
2. Patterns track: category, frequency, description, prevention rule, first/last seen iteration
3. Patterns are sorted by frequency (most common first)
4. A "Known Pitfalls" section is injected into the next worker's skills

### Example Pattern Injection

```markdown
## Known Pitfalls

The following issues have occurred in prior workers during this run.
Avoid repeating them:

- [seen 3x] missing_data: Always include the 'summary' field in your output
- [seen 2x] wrong_format: Output confidence as a float, not a string
```

This creates a **learning loop within a single run** — later workers benefit from earlier mistakes without any human intervention.

## Repair Process

### Targeted Repair

Unlike evaluation retry (which re-runs the entire workflow), critique repair is **targeted**:

1. Only critical + warning defects are included in repair instructions
2. The worker receives its own previous output plus specific fix instructions
3. The repair prompt says: "Fix ONLY these defects. Keep everything else unchanged."
4. After repair, the result is re-critiqued to verify improvement
5. Repair stops if score doesn't improve (prevents infinite loops)

### Budget Controls

- Repairs consume budget (tokens, loops, worker runs)
- `repair_budget_fraction` caps the total repair spend (e.g., 15% of total budget)
- `max_repair_attempts` caps per-worker repair cycles
- If budget is exhausted, repair is skipped and the original result is kept

### Repair Artifacts

Each repair attempt is tracked:

```json
{
  "worker_id": "analyst_01",
  "attempt": 1,
  "original_score": 0.45,
  "repaired_score": 0.82,
  "defects_fixed": 3,
  "defects_remaining": 0
}
```

## Workspace Artifacts

When critique is enabled, additional artifacts are written per iteration:

```
workspace/runs/<run-id>/
  iterations/
    001/
      critique.json              # All worker critiques for this iteration
      CRITIQUE.md                # Human-readable summary
      delegations/
        <worker-id>/
          critique.json          # Per-worker critique detail
```

## Manager Integration

The manager receives a critique summary after each iteration, including:

- Per-worker scores and defect counts
- Top prescriptions
- Known patterns and their frequencies
- Repair history (original vs. repaired scores)

This helps the manager make better delegation decisions in subsequent iterations.

## Example

See [Example 15: Critique Loop](../examples/workflows/15-critique-loop/) for a complete working demonstration with:

- Inline critique mode
- Pattern memory enabled
- 2 repair attempts per worker
- 20% repair budget fraction
- Evaluation metrics + retry policy combined with critique
