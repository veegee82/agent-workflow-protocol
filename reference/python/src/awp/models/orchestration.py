"""AWP Orchestration models (Layer 5) — DAG, execution, loops, fan-out, delegation loop."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from .common import AgentId


class ConditionalDependency(BaseModel):
    """Dependency with condition."""

    agent: AgentId
    condition: str = "success"  # success | failure | always | expression
    when: Optional[str] = None  # Safe expression evaluated at runtime


class LoopConfig(BaseModel):
    """Loop execution configuration for an agent."""

    enabled: bool = False
    max_iterations: int = 5
    until_condition: str = ""  # Safe Python expression
    mode: str = "standard"  # standard | interactive
    poll_interval: float = 2.0


class FanOutConfig(BaseModel):
    """Fan-out configuration for parallel agent spawning."""

    enabled: bool = False
    source_field: str = ""  # State field containing items
    agent_template: str = ""  # Agent to spawn per item
    max_parallel: int = 4
    aggregation: str = "merge"  # merge | concat | custom


class GraphNode(BaseModel):
    """Single node in the orchestration DAG."""

    id: AgentId
    agent: str  # Agent directory name
    enabled: bool = True
    depends_on: list[str | ConditionalDependency] = Field(default_factory=list)
    share_input: dict[str, list[str]] = Field(default_factory=dict)
    share_output: list[str] = Field(default_factory=list)
    description: str = ""
    on_failure: str = "continue"  # continue | skip | abort
    when: Optional[str] = None  # Safe expression: "state.analyst.risk_score > 0.3"
    loop: Optional[LoopConfig] = None
    fan_out: Optional[FanOutConfig] = None
    timeout: Optional[int] = None  # Override per-agent timeout
    retry: int = 0
    # Delegation loop support: a DAG node can be a delegation_loop
    type: Optional[str] = None  # None = normal agent, "delegation_loop" = embedded loop
    config: Optional[DelegationLoopConfig] = None  # Only when type=delegation_loop


class ErrorHandling(BaseModel):
    """Error handling configuration."""

    default: str = "continue"  # continue | stop | retry
    max_retries: int = 1
    retry_delay: float = 2.0
    fallback_agent: Optional[str] = None


class TimeoutConfig(BaseModel):
    """Timeout configuration."""

    per_agent: int = 120
    total: int = 300


class AWPExecutionConfig(BaseModel):
    """Execution configuration."""

    mode: str = "parallel"  # sequential | parallel | conditional
    timeout: TimeoutConfig = Field(default_factory=TimeoutConfig)
    max_parallel_agents: int = 4
    error_handling: ErrorHandling = Field(default_factory=ErrorHandling)


class SubworkflowRef(BaseModel):
    """Reference to a sub-workflow."""

    name: str
    ref: str  # Path or registry reference
    input_mapping: dict[str, str] = Field(default_factory=dict)
    output_mapping: dict[str, str] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Run Budget — Global limits for any workflow (DAG or delegation loop)
# ---------------------------------------------------------------------------


class RunBudgetLimits(BaseModel):
    """Global run budget limits applicable to any workflow type.

    Each limit can be individually enabled or disabled via ``enabled_limits``.
    This allows the user to choose in the run wizard exactly which constraints
    apply to a given run.

    Note: ``max_cost_usd`` is automatically disabled for free models
    (``":free"`` suffix) because they incur no cost.  In that case
    ``max_total_tokens`` serves as the primary resource limit.
    """

    max_wall_time: int = 600  # seconds — total execution time
    max_total_tokens: int = 10_000_000  # LLM token cap across all agents
    max_tool_calls: int = 1500  # total tool invocations
    max_agent_runs: int = 50  # total agent executions (incl. retries)
    max_cost_usd: float = 5.0  # monetary cost cap (estimated, ignored for free models)

    # Which limits are active — list of field names.
    # Empty list = all limits active.  Use this to selectively disable limits.
    enabled_limits: list[str] = Field(
        default_factory=lambda: [
            "max_wall_time",
            "max_total_tokens",
            "max_tool_calls",
            "max_agent_runs",
            "max_cost_usd",
        ]
    )


# ---------------------------------------------------------------------------
# Delegation Loop Models — Dynamic manager-worker orchestration
# ---------------------------------------------------------------------------


class ContextBudget(BaseModel):
    """Controls how much worker/agent context is inlined vs spilled to files.

    When a worker result exceeds its share of ``total_chars``, the full JSON
    is written to ``workspace/context/<worker_id>.json`` and only a preview
    is shown in the prompt.  This prevents context-window overflow while
    ensuring no data is lost — workers can read the spilled file via
    ``code.execute``.

    Auto-detect (default): ``total_chars`` is divided equally among the
    number of context entries.  Each entry gets at least ``min_per_entry``
    characters.
    """

    total_chars: int = 64_000  # ~16K tokens total context budget
    min_per_entry: int = 4_000  # floor per entry even with many workers
    preview_chars: int = 2_000  # preview length for spilled results


class DelegationBudget(BaseModel):
    """Resource budget for the delegation loop and recursive sub-delegations."""

    max_loops: int = 100
    max_total_workers: int = 500
    max_total_tokens: int = 10_000_000
    max_wall_time: int = 600  # seconds
    max_tool_calls: int = 1500
    max_depth: int = 2
    # Hard caps on the number of submanagers (recursive child runners) the
    # delegation loop is allowed to spawn. Without these the manager can
    # cascade into an unbounded submanager forest.
    max_concurrent_submanagers: int = 3
    max_total_submanagers_per_run: int = 6


class SandboxEnforcement(BaseModel):
    """Sandbox constraints that the manager cannot override."""

    type: str = "subprocess"
    max_memory_mb: int = 512
    max_cpu_seconds: int = 30
    network: bool = False


class CodeModeEnforcement(BaseModel):
    """Code mode constraints enforced on workers."""

    max_tools_per_worker: int = 10


class RateLimitEnforcement(BaseModel):
    """Rate limiting enforced on workers."""

    max_llm_calls_per_minute: int = 30


class WorkerPolicyEnforced(BaseModel):
    """Immutable security envelope — manager cannot override these."""

    sandbox: SandboxEnforcement = Field(default_factory=SandboxEnforcement)
    codemode: CodeModeEnforcement = Field(default_factory=CodeModeEnforcement)
    rate_limiting: RateLimitEnforcement = Field(default_factory=RateLimitEnforcement)
    forbidden_tools: list[str] = Field(
        default_factory=lambda: ["file.write_outside_workspace", "shell.execute"]
    )


class WorkerPolicy(BaseModel):
    """Worker policy: what the manager can and cannot control."""

    enforced: WorkerPolicyEnforced = Field(default_factory=WorkerPolicyEnforced)
    manager_controlled: list[str] = Field(
        default_factory=lambda: [
            "instructions",
            "skills",
            "tools_allowed",
            "output_contract",
            "codemode.enabled",
            "codemode.tool_creation",
            "temperature",
        ]
    )


class StrategySwitchingConfig(BaseModel):
    """Strategy rotation on stall detection.

    When enabled and the stall detector fires, the manager rotates
    through meta-strategies instead of stopping. Only stops when
    all strategies have been exhausted.
    """

    enabled: bool = False
    strategies: list[str] = Field(
        default_factory=lambda: ["decompose_finer", "simplify", "reframe", "escalate"]
    )


class StallDetectionConfig(BaseModel):
    """Detects when the delegation loop makes no progress."""

    enabled: bool = True
    window: int = 3  # number of iterations to compare
    min_confidence_delta: float = 0.05
    action: str = "warn_then_stop"  # warn_then_stop | stop | warn
    strategy_switching: StrategySwitchingConfig = Field(default_factory=StrategySwitchingConfig)


class DeterministicValidationConfig(BaseModel):
    """Deterministic (cheap) validation checks."""

    always: bool = True
    checks: list[str] = Field(
        default_factory=lambda: ["schema", "required_fields", "confidence", "budget"]
    )


class LLMValidationConfig(BaseModel):
    """LLM-based semantic validation."""

    enabled: bool = True
    skip_when_confidence_above: float = 0.95
    skip_when_budget_remaining_below: float = 0.1


class ValidationConfig(BaseModel):
    """Two-tier validation: deterministic + LLM."""

    deterministic: DeterministicValidationConfig = Field(
        default_factory=DeterministicValidationConfig
    )
    llm: LLMValidationConfig = Field(default_factory=LLMValidationConfig)


class CritiqueConfig(BaseModel):
    """Reflective Critique Loop configuration.

    When enabled, worker results pass through a critique phase before
    returning to the manager. The critic diagnoses defects, prescribes
    targeted repairs, and accumulates cross-worker failure patterns.
    """

    enabled: bool = False
    mode: str = "inline"  # "inline" (uses worker model) | "dedicated" (separate agent)
    model: Optional[str] = None  # None = use worker model
    max_repair_attempts: int = 2  # per worker, before escalating to manager
    repair_budget_fraction: float = 0.15  # max fraction of total budget for repairs
    pattern_memory: bool = True  # accumulate cross-worker failure patterns
    # Hard gate before run.complete: if the mean critique score across the
    # most recent iteration is below this threshold, the manager's "complete"
    # decision is overridden and another iteration is forced (until budget
    # is exhausted). Setting to 0.0 disables the gate.
    min_score_to_complete: float = 0.6
    defect_categories: list[str] = Field(
        default_factory=lambda: [
            "missing_data",
            "wrong_format",
            "incomplete",
            "hallucinated",
            "stale",
            "policy_violation",
        ]
    )


# ---------------------------------------------------------------------------
# Manager Intelligence Models — Enhanced problem-solving capabilities
# ---------------------------------------------------------------------------


class DecisionJournalConfig(BaseModel):
    """Reflective workspace memory for the manager.

    When enabled, the manager maintains a decision journal that tracks
    its own decisions and their outcomes across iterations, enabling
    intra-run learning and self-correction.
    """

    enabled: bool = False
    max_entries: int = 20  # oldest entries evicted when exceeded


class BudgetPhase(BaseModel):
    """A named phase in the predictive budget reservation system."""

    name: str
    fraction: float  # 0.0-1.0, share of total budget
    description: str = ""


class BudgetReservationConfig(BaseModel):
    """Predictive budget reservation — pre-allocates budget to phases.

    When enabled, the total budget is divided into phases with guaranteed
    reservations. The manager sees its current phase and remaining phase
    budget, preventing the common failure mode of exhausting all budget
    on analysis with nothing left for synthesis.
    """

    enabled: bool = False
    phases: list[BudgetPhase] = Field(
        default_factory=lambda: [
            BudgetPhase(name="core_work", fraction=0.60, description="Primary task execution"),
            BudgetPhase(
                name="validation_repair", fraction=0.20, description="Validation and repair cycles"
            ),
            BudgetPhase(name="synthesis", fraction=0.15, description="Final synthesis and output"),
            BudgetPhase(name="reserve", fraction=0.05, description="Emergency reserve"),
        ]
    )


class PlanningConfig(BaseModel):
    """Task decomposition — explicit planning phase before delegation.

    When enabled, the manager can create an explicit task graph on
    the first iteration (PLAN decision), decomposing the problem into
    subtasks with dependencies and success criteria. Subsequent
    iterations track progress against this plan.
    """

    enabled: bool = False
    max_subtasks: int = 10  # cap on plan complexity



class DiagnosisConfig(BaseModel):
    """Hypothesis-driven debugging for worker failures.

    When enabled and a worker produces low-confidence or failed results,
    the manager can generate causal hypotheses and optionally delegate
    lightweight diagnostic workers to test them before retrying.
    """

    enabled: bool = False
    max_hypotheses: int = 3
    confidence_threshold: float = 0.3  # trigger diagnosis below this confidence


class HistoryConfig(BaseModel):
    """Rolling summary and history configuration."""

    rolling_summary: bool = True
    full_results_window: int = 3  # last N results kept in full
    persist_to_disk: bool = True


class DelegationLoopModels(BaseModel):
    """Model configuration for manager and worker agents."""

    manager: Optional[str] = None  # CLI --manager-model → YAML → LLM_MODEL
    worker: Optional[str] = None  # CLI --worker-model → YAML → manager model


class DelegationLoggingConfig(BaseModel):
    """Logging format and artifact persistence."""

    format: str = "dual"  # dual (json + md) | json | md
    persist_artifacts: bool = True  # keep generated skills and tools


class DelegationLoopConfig(BaseModel):
    """Complete configuration for the delegation loop orchestration engine.

    The delegation loop is an alternative to the static DAG engine. A manager
    agent dynamically generates instructions, skills, and tools for ephemeral
    worker agents. Workers execute and report back. The loop continues until
    the manager decides the task is complete, a budget limit is hit, or stall
    detection triggers.

    Workers can recursively sub-delegate within their allocated budget.
    """

    manager: str = ""  # Agent directory path, e.g. "agents/manager"
    models: DelegationLoopModels = Field(default_factory=DelegationLoopModels)
    worker_policy: WorkerPolicy = Field(default_factory=WorkerPolicy)
    budget: DelegationBudget = Field(default_factory=DelegationBudget)
    context_budget: ContextBudget = Field(default_factory=ContextBudget)
    termination: Optional[StallDetectionConfig] = Field(default_factory=StallDetectionConfig)
    validation: ValidationConfig = Field(default_factory=ValidationConfig)
    history: HistoryConfig = Field(default_factory=HistoryConfig)
    logging: DelegationLoggingConfig = Field(default_factory=DelegationLoggingConfig)
    critique: CritiqueConfig = Field(default_factory=CritiqueConfig)
    # Manager Intelligence features
    planning: PlanningConfig = Field(default_factory=PlanningConfig)
    diagnosis: DiagnosisConfig = Field(default_factory=DiagnosisConfig)
    budget_reservation: BudgetReservationConfig = Field(default_factory=BudgetReservationConfig)
    decision_journal: DecisionJournalConfig = Field(default_factory=DecisionJournalConfig)
    # Selective-forget blacklist for submanager state inheritance.
    #
    # By default, a spawned submanager inherits ALL parent state keys so
    # children are not "born blind". Any key listed here is stripped from
    # the inherited state before it reaches the child. Per-delegation
    # overrides are supported via the envelope's ``forbidden_inheritance_keys``
    # field, and an explicit per-delegation ``inherited_state_keys`` whitelist
    # still wins over this default (full backward compatibility).
    forbidden_inheritance_keys: list[str] = Field(default_factory=list)
    # Blackboard channel for sibling-worker coordination.
    #
    # When enabled (default), every manager run gets its own append-only
    # JSONL blackboard at `<workspace>/blackboard/<manager_run_id>.jsonl`.
    # Workers receive two run-scoped tools (`board.post` / `board.read`)
    # so siblings can broadcast partial findings to the next manager
    # iteration. Submanagers get their OWN blackboard (different run_id);
    # parent and child never share signals.
    blackboard_enabled: bool = True
    # Hierarchical Context Digest (HCD) — per-level compact summary that
    # lets deep delegation graphs (depth >=3) keep context without
    # overflowing the manager prompt. Deterministic generation in v1
    # (no LLM call); "llm" mode is reserved for a future version and
    # raises NotImplementedError when invoked.
    digest_enabled: bool = True
    digest_mode: str = "deterministic"
    # How many levels of children to inline in the manager prompt as
    # part of the CHILDREN DIGESTS block. Deeper layers remain reachable
    # via the ``digest.fetch`` tool.
    digest_max_depth: int = 1
    # Auto-Curation (Baustein 4). When enabled, a deterministic curator
    # runs at the end of every delegation-loop run and writes reusable
    # knowledge (tool recipes, cross-confirmed facts, antipatterns) into
    # ``<workflow_dir>/memory/``. On the next run, the root manager's
    # first-iteration prompt is primed with a compact ``PRIOR RUN MEMORY``
    # block read back from that directory.
    auto_curation_enabled: bool = True

    model_config = {"extra": "allow"}


class AWPOrchestrationConfig(BaseModel):
    """Complete orchestration configuration (Layer 5)."""

    engine: str = "dag"  # "dag" | "delegation_loop"
    graph: list[GraphNode] = Field(default_factory=list)
    execution: AWPExecutionConfig = Field(default_factory=AWPExecutionConfig)
    subworkflows: list[SubworkflowRef] = Field(default_factory=list)
    # Delegation loop config (only used when engine=delegation_loop)
    delegation_loop: Optional[DelegationLoopConfig] = None
    # Global run budget — applies to any engine (DAG or delegation loop)
    run_budget: Optional[RunBudgetLimits] = None
    # Context budget — controls inline vs file spillover for agent results
    context_budget: ContextBudget = Field(default_factory=ContextBudget)

    model_config = {"extra": "allow"}


# Forward reference resolution for GraphNode.config
GraphNode.model_rebuild()
