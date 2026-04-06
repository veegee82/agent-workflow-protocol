# Manager Intelligence

AWP's Manager Intelligence features enhance the delegation loop manager's problem-solving capabilities with five independently configurable subsystems: task decomposition, hypothesis-driven debugging, strategy switching, predictive budget reservation, and a decision journal.

## Overview

| Feature | Purpose | Config Key | Default |
|---------|---------|------------|---------|
| Task Decomposition | Explicit planning before delegation | `planning.enabled` | `false` |
| Hypothesis-Driven Debugging | Systematic failure diagnosis | `diagnosis.enabled` | `false` |
| Strategy Switching | Meta-reasoning on stall detection | `termination.strategy_switching.enabled` | `false` |
| Predictive Budget Reservation | Phase-based budget allocation | `budget_reservation.enabled` | `false` |
| Decision Journal | Reflective decision tracking | `decision_journal.enabled` | `false` |

All features are disabled by default and can be enabled independently.

<p align="center">
  <img src="../assets/manager-intelligence-overview.svg" alt="Manager Intelligence Overview" width="900"/>
</p>

## Task Decomposition (Planning Phase)

When enabled, the manager can issue a **PLAN** decision on the first iteration, creating an explicit task graph before delegating any work.

### How It Works

1. On iteration 1, the manager analyzes the task and creates a list of subtasks with IDs, descriptions, dependencies, priorities, and success criteria
2. The plan is stored and shown to the manager on every subsequent iteration as a progress table
3. As workers complete, their results are mapped to subtasks automatically (via matching `worker_id` to subtask `id`)
4. The manager sees which subtasks are actionable (dependencies met) and which are blocked

<p align="center">
  <img src="../assets/manager-intelligence-planning.svg" alt="Task Decomposition Flow" width="900"/>
</p>

### Configuration

```yaml
orchestration:
  delegation_loop:
    planning:
      enabled: true
      max_subtasks: 10    # Maximum subtasks in a plan
```

### Configuration Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enabled` | bool | `false` | Enable task decomposition |
| `max_subtasks` | int | `10` | Maximum number of subtasks in a plan |

### Example Plan Output

```json
{
  "decision": "plan",
  "reasoning": "Breaking the analysis into data loading, processing, and visualization phases",
  "subtasks": [
    {"id": "load_data", "description": "Load and validate CSV input", "dependencies": [], "priority": "high", "success_criteria": "DataFrame loaded with >0 rows"},
    {"id": "analyze", "description": "Run statistical analysis", "dependencies": ["load_data"], "priority": "high", "success_criteria": "Key metrics computed"},
    {"id": "visualize", "description": "Generate charts from analysis results", "dependencies": ["analyze"], "priority": "normal", "success_criteria": "PNG charts saved to output"}
  ]
}
```

## Hypothesis-Driven Debugging

When a worker produces low-confidence results (below a configurable threshold) or fails, the manager can issue a **DIAGNOSE** decision instead of blindly retrying.

### How It Works

1. After a worker fails or returns confidence below the threshold, the manager sees a "Diagnosis Suggested" hint
2. The manager generates up to N hypotheses about the failure cause, each with an ID, description, test method, and likelihood estimate
3. Hypotheses are shown in subsequent iterations as an "Active Hypotheses" table
4. The manager can delegate lightweight diagnostic workers to test specific hypotheses
5. Hypothesis status updates to "confirmed" or "refuted" based on diagnostic worker results
6. The confirmed root cause informs the actual retry delegation

<p align="center">
  <img src="../assets/manager-intelligence-diagnosis.svg" alt="Hypothesis-Driven Debugging Flow" width="900"/>
</p>

### Configuration

```yaml
orchestration:
  delegation_loop:
    diagnosis:
      enabled: true
      max_hypotheses: 3           # Max hypotheses per diagnosis
      confidence_threshold: 0.3   # Trigger below this confidence
```

### Configuration Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enabled` | bool | `false` | Enable hypothesis-driven debugging |
| `max_hypotheses` | int | `3` | Maximum hypotheses per DIAGNOSE decision |
| `confidence_threshold` | float | `0.3` | Worker confidence below this triggers diagnosis suggestion |

## Strategy Switching (Meta-Reasoning)

When stall detection fires (confidence not improving), instead of stopping the loop, the manager rotates through a pool of meta-strategies designed to break through plateaus.

### How It Works

1. Stall detector fires (confidence delta < threshold over N iterations)
2. Instead of warning/stopping, the system selects the next strategy from the pool
3. A "Strategy Directive" section is injected into the manager's prompt with the strategy name and explanation
4. The manager MUST change its delegation approach according to the directive
5. If the new strategy produces progress, execution continues normally
6. If stall recurs, the next strategy in the pool is tried
7. Only when ALL strategies are exhausted does the loop stop

<p align="center">
  <img src="../assets/manager-intelligence-strategy.svg" alt="Strategy Switching State Machine" width="900"/>
</p>

### Strategy Pool

| Strategy | Description |
|----------|-------------|
| `decompose_finer` | Break work into smaller, more specific subtasks |
| `simplify` | Solve a simpler version first, then extend |
| `reframe` | Reformulate the problem from a different angle |
| `escalate` | Use more powerful tools, higher temperature, or different methodology |

### Configuration

```yaml
orchestration:
  delegation_loop:
    termination:
      enabled: true
      window: 3
      min_confidence_delta: 0.05
      strategy_switching:
        enabled: true
        strategies:
          - decompose_finer
          - simplify
          - reframe
          - escalate
```

### Configuration Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enabled` | bool | `false` | Enable strategy switching on stall |
| `strategies` | list[str] | `["decompose_finer", "simplify", "reframe", "escalate"]` | Ordered list of strategies to try |

## Predictive Budget Reservation

Pre-allocates the total budget into phases with guaranteed reservations, preventing the common failure mode of exhausting all budget on analysis with nothing left for synthesis.

### How It Works

1. At the start of the run, the budget is divided into phases (default: 60/20/15/5 split)
2. The manager sees its current phase and remaining phase budget in every iteration
3. Phase transitions happen automatically based on overall budget consumption
4. When a phase's budget drops below 10%, the manager receives a warning
5. The reserve phase (5%) provides an emergency buffer for graceful completion

<p align="center">
  <img src="../assets/manager-intelligence-budget.svg" alt="Budget Reservation Phases" width="900"/>
</p>

### Default Phases

| Phase | Fraction | Description |
|-------|----------|-------------|
| `core_work` | 60% | Primary task execution and analysis |
| `validation_repair` | 20% | Validation, critique, and repair cycles |
| `synthesis` | 15% | Final synthesis, formatting, and output generation |
| `reserve` | 5% | Emergency buffer for graceful completion |

### Configuration

```yaml
orchestration:
  delegation_loop:
    budget_reservation:
      enabled: true
      phases:
        - name: core_work
          fraction: 0.60
          description: Primary task execution
        - name: validation_repair
          fraction: 0.20
          description: Validation and repair cycles
        - name: synthesis
          fraction: 0.15
          description: Final synthesis and output
        - name: reserve
          fraction: 0.05
          description: Emergency reserve
```

### Configuration Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enabled` | bool | `false` | Enable budget reservation |
| `phases` | list[BudgetPhase] | 4 default phases | Ordered list of budget phases (fractions must sum to 1.0) |

## Decision Journal

The manager maintains a reflective log of its decisions and their outcomes, enabling pattern recognition and self-correction within a single run.

### How It Works

1. After every manager decision, an entry is recorded: iteration, decision type, rationale, and worker IDs
2. After worker results come in, outcomes (confidence scores) are attached to the entry
3. Auto-derived lessons flag low-confidence patterns ("consider changing approach") and successful strategies ("approach is effective")
4. The journal is shown to the manager with a reflection prompt: "Given the pattern of decisions and outcomes above, what adjustment would improve the next iteration?"
5. Oldest entries are evicted when the journal exceeds `max_entries`

<p align="center">
  <img src="../assets/manager-intelligence-journal.svg" alt="Decision Journal Flow" width="900"/>
</p>

### Configuration

```yaml
orchestration:
  delegation_loop:
    decision_journal:
      enabled: true
      max_entries: 20    # Oldest entries evicted when exceeded
```

### Configuration Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enabled` | bool | `false` | Enable the decision journal |
| `max_entries` | int | `20` | Maximum journal entries before eviction |

### Example Journal Entry (in manager prompt)

```
- **Iter 1** [plan]: Breaking task into 3 subtasks
- **Iter 2** [delegate]: Delegating data loading → outcomes: load_worker=0.85 | Lesson: High confidence — approach is effective
- **Iter 3** [delegate]: Delegating analysis → outcomes: analyze_worker=0.25 | Lesson: Low confidence — consider changing approach
- **Iter 4** [diagnose]: Worker failed — generating hypotheses before retrying

**Reflection**: Given the pattern of decisions and outcomes above, what adjustment would improve the next iteration?
```

## Feature Interactions

The five features are designed to compose. Here is how they interact:

| Feature A | Feature B | Interaction |
|-----------|-----------|-------------|
| Planning | Budget Reservation | Subtask count can inform core_work phase sizing |
| Planning | Decision Journal | Plan creation is recorded as the first journal entry |
| Diagnosis | Strategy Switching | Diagnosis results inform which strategy to switch to |
| Diagnosis | Decision Journal | Each hypothesis and result is logged |
| Strategy Switching | Planning | "decompose_finer" strategy tells the manager to re-plan with more granular subtasks |
| Strategy Switching | Decision Journal | Strategy switches are recorded, showing what has been tried |
| Budget Reservation | Strategy Switching | Approaching phase limits can trigger a strategy switch |

## Full Configuration Reference

All Manager Intelligence features enabled:

```yaml
orchestration:
  engine: delegation_loop
  delegation_loop:
    budget:
      max_loops: 100
      max_total_workers: 500
      max_total_tokens: 10000000
      max_wall_time: 600
    termination:
      enabled: true
      window: 3
      min_confidence_delta: 0.05
      strategy_switching:
        enabled: true
        strategies:
          - decompose_finer
          - simplify
          - reframe
          - escalate
    planning:
      enabled: true
      max_subtasks: 10
    diagnosis:
      enabled: true
      max_hypotheses: 3
      confidence_threshold: 0.3
    budget_reservation:
      enabled: true
      phases:
        - name: core_work
          fraction: 0.60
          description: Primary task execution
        - name: validation_repair
          fraction: 0.20
          description: Validation and repair cycles
        - name: synthesis
          fraction: 0.15
          description: Final synthesis and output
        - name: reserve
          fraction: 0.05
          description: Emergency reserve
    decision_journal:
      enabled: true
      max_entries: 20
```

## Backward Compatibility

All Manager Intelligence features default to **disabled**. Existing workflows continue to work without any changes. The features only activate when explicitly enabled in the YAML configuration. No new dependencies or breaking changes are introduced.
