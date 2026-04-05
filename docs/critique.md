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

<svg viewBox="0 0 620 520" xmlns="http://www.w3.org/2000/svg" font-family="system-ui, -apple-system, sans-serif" font-size="11">
<!-- Worker result -->
  <rect x="180" y="5" width="220" height="30" rx="6" fill="#dce6f7" stroke="#4a6fa5" stroke-width="1.5"/>
  <text x="290" y="25" text-anchor="middle" font-weight="600" fill="#2a3f5f">Worker produces result</text>
  <!-- Critic -->
  <rect x="140" y="55" width="300" height="40" rx="6" fill="#e8d5f5" stroke="#7b4ea3" stroke-width="1.5"/>
  <text x="290" y="72" text-anchor="middle" font-weight="700" fill="#5a2d82">Critic analyzes result</text>
  <text x="290" y="88" text-anchor="middle" fill="#7b4ea3" font-size="10">LLM or heuristic fallback</text>
  <!-- Envelope -->
  <rect x="120" y="115" width="340" height="60" rx="6" fill="#fef3cd" stroke="#d4a017" stroke-width="1.2"/>
  <text x="290" y="132" text-anchor="middle" font-weight="600" fill="#856404">CritiqueEnvelope</text>
  <text x="145" y="148" fill="#a88a04" font-size="10">score (0.0-1.0) | defects (categorized) | prescriptions</text>
  <text x="145" y="163" fill="#a88a04" font-size="10">reusable_patterns (for other workers) | effort_estimate</text>
  <!-- Decision diamond -->
  <polygon points="290,195 360,220 290,245 220,220" fill="#fff3e0" stroke="#e65100" stroke-width="1.5"/>
  <text x="290" y="224" text-anchor="middle" font-weight="600" fill="#e65100" font-size="10">Critical defects?</text>
  <!-- No path -->
  <rect x="420" y="205" width="180" height="30" rx="6" fill="#d5f5e3" stroke="#27ae60" stroke-width="1.2"/>
  <text x="510" y="225" text-anchor="middle" fill="#1a6b3c" font-size="11">Accept, record patterns</text>
  <!-- Repair loop box -->
  <rect x="100" y="265" width="380" height="160" rx="8" fill="#fdf0f0" stroke="#c0392b" stroke-width="1.5"/>
  <text x="290" y="283" text-anchor="middle" font-weight="700" fill="#922b21">Targeted Repair Loop</text>
  <text x="290" y="298" text-anchor="middle" fill="#c0392b" font-size="10">(up to max_repair_attempts)</text>
  <rect x="130" y="308" width="320" height="24" rx="4" fill="#fde2e2" stroke="#c0392b" stroke-width="0.8"/>
  <text x="290" y="324" text-anchor="middle" fill="#922b21" font-size="10">Build repair prompt with defect list + prescriptions</text>
  <rect x="130" y="340" width="320" height="24" rx="4" fill="#fde2e2" stroke="#c0392b" stroke-width="0.8"/>
  <text x="290" y="356" text-anchor="middle" fill="#922b21" font-size="10">Re-run worker with repair instructions</text>
  <rect x="130" y="372" width="320" height="24" rx="4" fill="#fde2e2" stroke="#c0392b" stroke-width="0.8"/>
  <text x="290" y="388" text-anchor="middle" fill="#922b21" font-size="10">Re-critique result</text>
  <rect x="130" y="404" width="320" height="14" rx="3" fill="none"/>
  <text x="290" y="414" text-anchor="middle" fill="#999" font-size="10">Score improved? Keep. Not improved? Stop.</text>
  <!-- Pattern memory -->
  <rect x="150" y="445" width="280" height="30" rx="6" fill="#e8d5f5" stroke="#7b4ea3" stroke-width="1.2"/>
  <text x="290" y="465" text-anchor="middle" font-weight="600" fill="#5a2d82">Patterns recorded in PatternMemory</text>
  <!-- Next workers -->
  <rect x="120" y="495" width="340" height="24" rx="6" fill="#d5f5e3" stroke="#27ae60" stroke-width="1.5"/>
  <text x="290" y="512" text-anchor="middle" font-weight="600" fill="#1a6b3c">Next workers receive "Known Pitfalls"</text>
  <!-- Arrows -->
  <line x1="290" y1="37" x2="290.0" y2="51.0" stroke="#4a6fa5" stroke-width="1.3"/>
  <polygon points="290.0,53.0 287.0,47.0 293.0,47.0" fill="#4a6fa5"/>
  <line x1="290" y1="97" x2="290.0" y2="111.0" stroke="#4a6fa5" stroke-width="1.3"/>
  <polygon points="290.0,113.0 287.0,107.0 293.0,107.0" fill="#4a6fa5"/>
  <line x1="290" y1="177" x2="290.0" y2="191.0" stroke="#4a6fa5" stroke-width="1.3"/>
  <polygon points="290.0,193.0 287.0,187.0 293.0,187.0" fill="#4a6fa5"/>
  <line x1="362" y1="220" x2="416.0" y2="220.0" stroke="#27ae60" stroke-width="1.3"/>
  <polygon points="418.0,220.0 412.0,223.0 412.0,217.0" fill="#27ae60"/>
  <text x="390" y="214" fill="#27ae60" font-size="10">No</text>
  <line x1="290" y1="247" x2="290.0" y2="261.0" stroke="#c0392b" stroke-width="1.3"/>
  <polygon points="290.0,263.0 287.0,257.0 293.0,257.0" fill="#c0392b"/>
  <text x="305" y="258" fill="#c0392b" font-size="10">Yes</text>
  <line x1="290" y1="427" x2="290.0" y2="441.0" stroke="#4a6fa5" stroke-width="1.3"/>
  <polygon points="290.0,443.0 287.0,437.0 293.0,437.0" fill="#4a6fa5"/>
  <line x1="290" y1="477" x2="290.0" y2="491.0" stroke="#4a6fa5" stroke-width="1.3"/>
  <polygon points="290.0,493.0 287.0,487.0 293.0,487.0" fill="#4a6fa5"/>
  <!-- Accept also goes to pattern memory -->
  <path d="M510,237 Q510,460 432,460" fill="none" stroke="#27ae60" stroke-width="1" stroke-dasharray="4,2"/>
</svg>

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
