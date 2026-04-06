# Example 16: Manager Intelligence

This example demonstrates all five Manager Intelligence features working together
in a data analysis workflow.

## Features Enabled

| Feature | Effect in This Workflow |
|---------|----------------------|
| Task Decomposition | Manager creates a plan with subtasks for data loading, analysis, and visualization |
| Hypothesis-Driven Debugging | If a worker fails (confidence < 0.3), manager diagnoses root cause before retrying |
| Strategy Switching | On stall, manager tries decompose_finer → simplify → reframe → escalate |
| Budget Reservation | 60% for analysis, 20% for validation, 15% for report, 5% reserve |
| Decision Journal | Manager reflects on what worked and what didn't across iterations |

## Running

```bash
awp run examples/workflows/16-manager-intelligence/
```

## What to Observe

1. **Iteration 1**: Manager issues a PLAN decision, decomposing the task into subtasks
2. **Subsequent iterations**: Manager delegates workers aligned with the plan, tracking progress
3. **On failure**: Manager uses DIAGNOSE to generate hypotheses before retrying
4. **Budget panel**: Shows current phase and remaining phase budget in logs
5. **Journal entries**: Show decision-outcome patterns and self-reflection

## Learn More

See [Manager Intelligence Documentation](../../docs/manager-intelligence.md) for full details.
