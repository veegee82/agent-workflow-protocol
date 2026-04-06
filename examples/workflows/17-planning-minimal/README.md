# Example 17: Minimal Planning

This example shows the Task Decomposition feature in isolation. The manager
creates an explicit plan on the first iteration, then delegates workers
aligned with the plan.

## Running

```bash
awp run examples/workflows/17-planning-minimal/
```

## What to Observe

1. **Iteration 1**: Manager issues a PLAN decision with subtasks
2. **Iteration 2+**: Manager delegates workers, referencing the plan
3. **Progress tracking**: Task Plan Progress section shows subtask completion status

## Learn More

See [Manager Intelligence — Task Decomposition](../../docs/manager-intelligence.md#task-decomposition-planning-phase).
