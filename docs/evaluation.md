# Evaluation Layer

AWP's evaluation layer provides **quality scoring** for workflow results. While validation (R1-R26) checks whether a workflow is structurally correct and safe, evaluation measures **how well the workflow solved the problem**.

## Evaluation vs Validation

| Aspect | Validation | Evaluation |
|--------|-----------|------------|
| Question | "Is this valid?" | "Is this good?" |
| When | Before/during execution | After execution |
| Output | pass/fail | 0.0-1.0 score |
| Required | Always | Optional |
| Location | `awp validate` | `observability.evaluation` |

## Configuration

Evaluation is configured under `observability.evaluation` in `workflow.awp.yaml`:

```yaml
observability:
  evaluation:
    enabled: true
    metrics:
      - name: correctness
        kind: deterministic_test
        weight: 2.0
        params:
          expr: "result.confidence > 0.7 and 'error' not in result"
      - name: completeness
        kind: deterministic_assertion
        weight: 1.5
        params:
          assertions:
            - "result.confidence > 0"
            - "'data' in result"
      - name: quality
        kind: rubric_judge
        weight: 1.0
      - name: efficiency
        kind: budget_utility
        weight: 0.5
      - name: safety
        kind: policy_score
        weight: 0.5
        params:
          assertions:
            - "'error' not in result"
    thresholds:
      accept: 0.85
      retry: 0.65
      fail: 0.40
    step_scores:
      enabled: true
      hooks:
        - worker_result
        - final_answer
    retry_policy:
      enabled: true
      max_repairs: 2
      actions:
        below_retry: retry_with_repair
        below_fail: fail_workflow
    rubric_judge:
      model: "openai/gpt-4o-mini"
      temperature: 0.0
    artifact_path: data/evaluation
```

When `enabled: false` (the default), evaluation is completely disabled and has zero runtime overhead.

## Metric Kinds

### `deterministic_test`

Evaluates a single safe expression. Returns 1.0 if truthy, 0.0 if falsy.

```yaml
- name: output_valid
  kind: deterministic_test
  weight: 1.0
  params:
    expr: "result.confidence > 0.5 and 'error' not in result"
```

Available variables in expressions: `result` (agent output dict), `state` (workflow state dict).

### `deterministic_assertion`

Evaluates a list of assertions. Returns the fraction that pass.

```yaml
- name: completeness
  kind: deterministic_assertion
  weight: 1.0
  params:
    assertions:
      - "result.confidence > 0"
      - "'data' in result"
      - "result.data.report_md != ''"
```

### `rubric_judge`

Sends the result to an LLM with a rubric prompt. The LLM returns a structured 0.0-1.0 score.

```yaml
- name: quality
  kind: rubric_judge
  weight: 1.0
  params:
    rubric: |
      Rate the output on completeness, accuracy, and formatting.
      Score 0.0 (worst) to 1.0 (best).
```

Configure the judge model separately:

```yaml
rubric_judge:
  model: "openai/gpt-4o-mini"
  temperature: 0.0
```

If no LLM client is available, rubric_judge gracefully degrades to 0.0 with a warning.

### `budget_utility`

Scores efficiency based on resource utilization. Returns `1.0 - average_utilization`.

```yaml
- name: efficiency
  kind: budget_utility
  weight: 0.5
```

Uses `_run_budget` state data (tokens, cost, wall time). A workflow that completes using 20% of its budget scores 0.8.

### `policy_score`

Checks policy/governance assertions. Returns fraction passing.

```yaml
- name: safety
  kind: policy_score
  weight: 0.5
  params:
    assertions:
      - "'error' not in result"
      - "result.confidence >= 0.3"
```

## Thresholds

Thresholds map scores to actions:

```
score >= accept  ->  ACCEPT (result is good)
retry <= score < accept  ->  ACCEPT_WITH_WARNING
fail <= score < retry  ->  RETRY_WITH_REPAIR (if retry_policy enabled)
score < fail  ->  FAIL_WORKFLOW
```

All threshold values must be in [0.0, 1.0] and satisfy `accept >= retry >= fail`.

## Step Scores

Step scores evaluate intermediate results at hook points:

- `worker_result` — after each worker/agent completes
- `generated_tool` — after dynamic tool creation
- `final_answer` — at workflow completion

Step scores are recorded in the evaluation artifact and feed into the final score.

## Retry Policy

When enabled, the retry policy can trigger re-execution based on scores:

```yaml
retry_policy:
  enabled: true
  max_repairs: 2
  actions:
    below_retry: retry_with_repair
    below_fail: fail_workflow
```

Available actions:
- `retry_with_repair` — inject evaluation feedback into state and retry
- `fail_workflow` — stop execution with a failure
- `accept_with_warning` — accept the result but log a warning

The retry policy respects existing budget limits. Retries consume budget (loops, tokens, workers).

## Weighted Aggregation

The final score is a weighted average of all metrics:

```
final_score = sum(score_i * weight_i) / sum(weight_i)
```

## Evaluation Artifacts

After a workflow run, evaluation artifacts are written to `data/evaluation/{run_id}.json`:

```json
{
  "run_id": "abc123",
  "final_score": 0.82,
  "final_action": "accept",
  "retries_used": 0,
  "step_records": [...],
  "final_result": {
    "score": 0.82,
    "metric_scores": [
      {"name": "correctness", "kind": "deterministic_test", "score": 0.95, "weight": 2.0},
      {"name": "efficiency", "kind": "budget_utility", "score": 0.75, "weight": 0.5}
    ],
    "action": "accept"
  }
}
```

## CLI

### Enable evaluation on a run

```bash
awp run path/to/workflow --task "..." --eval
```

The `--eval` flag enables evaluation even if the YAML config has `enabled: false`.

### View evaluation artifacts

```bash
awp eval path/to/workflow               # view latest
awp eval path/to/workflow --run-id abc123  # view specific run
```

## Validation Rules

Evaluation adds rules R27-R30 to the validator:

- **R27**: `metrics[].kind` must be a valid metric kind
- **R28**: Thresholds must satisfy `accept >= retry >= fail`, all in [0, 1]
- **R29**: Metric weights must be >= 0; at least one metric must have weight > 0
- **R30**: `step_scores.hooks` must use valid hooks; retry actions must be valid
