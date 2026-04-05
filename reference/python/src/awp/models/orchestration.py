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
    max_tool_calls: int = 250  # total tool invocations
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
    max_tool_calls: int = 250
    max_depth: int = 10


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


class StallDetectionConfig(BaseModel):
    """Detects when the delegation loop makes no progress."""

    enabled: bool = True
    window: int = 3  # number of iterations to compare
    min_confidence_delta: float = 0.05
    action: str = "warn_then_stop"  # warn_then_stop | stop | warn


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
