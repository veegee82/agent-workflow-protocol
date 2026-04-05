# 15 — Reflective Critique Loop

Demonstrates the **Reflective Critique Loop (RCL)** — a structured feedback mechanism between worker execution and manager decision-making.

## What This Example Shows

1. **Structured Critique**: After each worker completes, a critic analyzes the output for defects (missing data, wrong format, incomplete results, hallucinations, policy violations)
2. **Targeted Repair**: Workers with critical defects get specific repair instructions and re-run, without requiring a full manager round-trip
3. **Cross-Worker Pattern Learning**: Failure patterns from earlier workers are injected as "Known Pitfalls" into later workers' skills
4. **Critique Artifacts**: All critique results, repair attempts, and patterns are logged to disk for inspection

## Key Configuration

```yaml
critique:
  enabled: true
  mode: inline               # Uses worker model for critique (cheap)
  max_repair_attempts: 2     # Max repairs per worker before escalating
  repair_budget_fraction: 0.20  # Max 20% of token budget for repairs
  pattern_memory: true        # Accumulate cross-worker patterns
```

## Running

```bash
awp run examples/workflows/15-critique-loop/ \
  --task "Analyze market trends for renewable energy sector: identify key players, growth metrics, and risk factors" \
  --manager-model openai/gpt-5-nano \
  --worker-model openai/gpt-5-nano
```

Or via AWP Studio:

```bash
awp studio
# Load the workflow directory, then run with the task above
```

## Inspecting Results

After a run, check the `workspace/runs/<run-id>/` directory:

```
workspace/runs/<run-id>/
  iterations/
    001/
      manager_decision.json    # What the manager decided
      critique.json            # Critique results for all workers
      CRITIQUE.md              # Human-readable critique summary
      delegations/
        <worker-id>/
          envelope.json        # Worker instructions
          result.json          # Worker output
          critique.json        # Per-worker critique
    002/
      ...
  history/
    ROLLING_SUMMARY.md         # Confidence trend + key findings
  RUN_SUMMARY.md               # Overall run summary
  run_manifest.json            # Run configuration
  run_completion.json          # Final status
```

## Graph Visualization

In AWP Studio, the GraphVis panel shows:
- **Worker nodes** with a `critique X%` badge showing the critique score
- **Repair indicators** (refresh icon) on workers that went through repair cycles
- **Tooltip details** showing individual defects, prescriptions, and repair history
- **Iteration nodes** with critique activity indicators

## Architecture

```
Manager → delegates → Workers (parallel)
                         ↓
                      Critic (per-worker)
                         ↓
                   Score < threshold?
                    YES → Targeted Repair (max N attempts)
                    NO  → Pass through
                         ↓
                   Pattern Memory (accumulated)
                         ↓
                   Manager sees: critique summary + patterns
                         ↓
                   Next iteration (with pitfalls injected into skills)
```
