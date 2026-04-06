# Example 18: Manager Intelligence — End-to-End Feature Test

This example exercises all 5 Manager Intelligence features on a fictional
**customer churn analysis** task. No LLM required — it uses synthetic manager
decisions to demonstrate each concept with visible output.

## Features Tested

| # | Feature | What It Does | Key Output |
|---|---------|-------------|------------|
| 1 | **Task Decomposition** | Manager creates explicit task plan before delegating | Subtask table with dependencies, progress tracking |
| 2 | **Hypothesis Debugging** | On worker failure, generates causal hypotheses | Hypothesis table, confirmed/refuted status |
| 3 | **Strategy Switching** | Rotates through meta-strategies on stall | Strategy name + description per stall event |
| 4 | **Budget Reservation** | Pre-allocates budget to phases (60/20/15/5) | Phase transitions, warnings, budget snapshot |
| 5 | **Decision Journal** | Tracks decisions and outcomes for self-correction | Journal entries with lessons and reflection prompt |

## Running

```bash
python examples/workflows/18-intelligence-e2e/test_intelligence.py
```

## What to Observe

### Task Decomposition (Iterations 1-4)
- Iteration 1: Manager creates a PLAN with 5 subtasks and dependency graph
- Progress table updates as workers complete: `load_data -> explore_data -> feature_eng -> ...`
- Dependency resolution: `explore_data` only becomes actionable after `load_data` completes

### Hypothesis Debugging (Iterations 4-6)
- Iteration 4: `train_worker` returns confidence=0.15 (below threshold 0.3)
- Iteration 5: Manager issues DIAGNOSE with 3 hypotheses ranked by likelihood
- H1 (class imbalance, 70% likely) is confirmed by a diagnostic worker
- Iteration 6: Manager retries with root cause knowledge (SMOTE oversampling)

### Strategy Switching (Stall Detection)
- Confidence stagnates at 0.45-0.48 across iterations
- Stall detector fires -> switches to `decompose_finer`
- Another stall -> switches to `simplify`
- Progress detected -> resets
- Next stall -> `reframe`, then `escalate`
- All strategies exhausted -> loop stops

### Budget Reservation (Phase Tracking)
- Budget split: 60% core_work, 20% validation_repair, 15% synthesis, 5% reserve
- Phase transitions triggered by budget consumption
- Warnings at <10% of phase budget remaining
- Budget snapshot includes phase info in JSON output

### Decision Journal (Full Run)
- Every decision recorded with rationale and worker IDs
- Outcomes attached after worker results (confidence scores)
- Auto-derived lessons: "Low confidence — consider changing approach"
- Reflection prompt: "What adjustment would improve the next iteration?"

## Expected Output

See [EXPECTED_OUTPUT.txt](EXPECTED_OUTPUT.txt) for the full reference output.

## Learn More

- [Manager Intelligence Documentation](../../../docs/manager-intelligence.md)
- [Delegation Loop Engine](../../../docs/ORCHESTRATION_ENGINES.md)
