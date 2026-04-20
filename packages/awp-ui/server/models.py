"""Pydantic models for the AWP UI API."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class RunState(str, Enum):
    """Lifecycle state of a workflow run."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETE = "complete"
    FAILED = "failed"
    STOPPED = "stopped"
    BUDGET_EXCEEDED = "budget_exceeded"
    STALL_DETECTED = "stall_detected"
    PARTIAL = "partial"
    ERROR = "error"


class EventType(str, Enum):
    """Discriminator for WebSocket / stored events."""

    AGENT_START = "agent.start"
    AGENT_COMPLETE = "agent.complete"
    TOOL_CALL = "tool.call"
    ITERATION_START = "iteration.start"
    ITERATION_DECISION = "iteration.decision"
    BUDGET_UPDATE = "budget.update"
    WORKER_SPAWN = "worker.spawn"
    WORKER_COMPLETE = "worker.complete"
    CRITIQUE_RESULT = "critique.result"
    WORKER_REPAIR = "worker.repair"
    DELEGATION_START = "delegation.start"
    LOG = "log"
    ERROR = "error"
    RUN_START = "run.start"
    RUN_COMPLETE = "run.complete"
    GRAPH_UPDATE = "graph.update"
    # Metric events — lightweight observability snapshots emitted at natural
    # points in the delegation loop. Pure observers: no runtime control flow
    # depends on them. Consumers render these as live-updating charts in the
    # UI MetricsPanel. See docs/observability.md (Metric events section).
    METRIC_CONFIDENCE = "metric.confidence"
    METRIC_CRITIQUE = "metric.critique"
    METRIC_EVAL = "metric.eval"
    METRIC_BUDGET = "metric.budget"
    METRIC_GATE = "metric.gate"
    METRIC_TOOL_CALL = "metric.tool_call"


# ---------------------------------------------------------------------------
# Workflow configuration (mirrors AgentWorkflow.__init__ params)
# ---------------------------------------------------------------------------


class WorkflowConfig(BaseModel):
    """All parameters accepted by AgentWorkflow, exposed via the REST API."""

    task: str = Field(..., min_length=1, description="Human-readable task description.")
    model: str = Field(..., min_length=1, description="LLM model identifier.")
    api_key: str | None = Field(None, description="LLM API key (falls back to env).")
    worker_model: str | None = Field(None, description="Model for worker agents.")

    # Inputs
    inputs: dict[str, Any] = Field(default_factory=dict, description="Arbitrary inputs.")
    input_files: list[str] = Field(
        default_factory=list,
        description="Paths to uploaded files to include as inputs.",
    )

    # Budget
    max_loops: int = Field(100, ge=1)
    max_total_tokens: int = Field(1_000_000, ge=1)
    max_wall_time: int = Field(3000, ge=1, description="Max wall time in seconds.")
    max_tool_calls: int = Field(100, ge=1)
    max_total_workers: int = Field(100, ge=1)
    max_depth: int = Field(10, ge=1)

    # Sandbox
    sandbox: str = Field("subprocess", description="subprocess | docker | venv | none")
    packages: list[str] = Field(default_factory=list)

    # Tools
    tools: list[str] | None = None
    forbidden_tools: list[str] | None = None

    # Features
    code_mode: bool = True
    tool_creation: bool = True
    verbose: bool = False

    # Output
    output_dir: str | None = None

    # Secrets (key-value, injected into tool registry)
    secrets: dict[str, str] = Field(default_factory=dict)

    # Skills
    skills: list[str] = Field(default_factory=list, description="Paths to skill files/dirs.")
    skills_dir: str | None = Field(None, description="Directory containing skills to load.")

    # Critique
    critique_enabled: bool = True
    critique_max_repair_attempts: int = 2

    # Manager Intelligence
    planning_enabled: bool = True
    planning_max_subtasks: int = 10
    diagnosis_enabled: bool = True
    diagnosis_max_hypotheses: int = 3
    diagnosis_confidence_threshold: float = 0.3
    strategy_switching_enabled: bool = True
    budget_reservation_enabled: bool = True
    decision_journal_enabled: bool = True
    decision_journal_max_entries: int = 20

    # Experiment cascade
    auto_refine_after_seed: bool = False
    auto_refine_iterations: int = 2
    auto_optimize_after_seed: bool = False
    auto_optimize_epochs: int = 1

    # Experiment/task linkage (for cascade)
    experiment_id: str | None = Field(None, description="Experiment ID for hierarchy context.")
    task_id: str | None = Field(None, description="Task ID for hierarchy context.")

    # Raw runtime overrides (keyed by section name: "critique", "planning", ...)
    # Needed so UI callers can raise caps like defect_category_hard_cap when
    # running workflows that legitimately need more repair iterations than the
    # default (e.g. multi-section paper assembly with the structural-integrity
    # gate forcing targeted repairs).
    extra_config: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Run status / detail
# ---------------------------------------------------------------------------


class RunStatus(BaseModel):
    """Lightweight run metadata returned in listings."""

    run_id: str
    task: str
    model: str
    status: RunState = RunState.PENDING
    created_at: datetime
    completed_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class RunDetail(BaseModel):
    """Full run information including result and config."""

    run_id: str
    task: str
    model: str
    status: RunState = RunState.PENDING
    config: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] | None = None
    created_at: datetime
    completed_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class RunHistoryEntry(BaseModel):
    """Single entry in run history listings."""

    run_id: str
    task: str
    model: str
    status: str
    created_at: str
    completed_at: str | None = None


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------


class ExperimentStatus(str, Enum):
    """Lifecycle state of an experiment."""

    DRAFT = "draft"
    RUNNING = "running"
    COMPLETE = "complete"
    FAILED = "failed"
    ARCHIVED = "archived"


class SessionInfo(BaseModel):
    """Lightweight session/experiment metadata returned in listings."""

    id: str
    title: str
    description: str = ""
    hypothesis: str = ""
    status: str = "draft"
    tags: list[str] = Field(default_factory=list)
    base_dir: str | None = None
    created_at: str
    updated_at: str
    run_count: int = 0
    last_run_status: str | None = None


class MemoryEntry(BaseModel):
    """A single experiment memory entry (note, observation, finding, decision)."""

    id: int
    session_id: str
    run_id: str | None = None
    type: str = "note"  # note, observation, finding, decision
    content: str
    source: str = "user"  # user, agent, system
    created_at: str
    updated_at: str


class MemoryCreate(BaseModel):
    """Request body for creating an experiment memory entry."""

    type: str = "note"
    content: str
    source: str = "user"
    run_id: str | None = None


class MemoryUpdate(BaseModel):
    """Request body for updating an experiment memory entry."""

    content: str


class SessionUpdate(BaseModel):
    """Request body for updating experiment metadata."""

    title: str | None = None
    description: str | None = None
    hypothesis: str | None = None
    status: str | None = None
    tags: list[str] | None = None
    base_dir: str | None = None


class SessionDetail(BaseModel):
    """Full session/experiment information including runs and memory."""

    id: str
    title: str
    description: str = ""
    hypothesis: str = ""
    status: str = "draft"
    tags: list[str] = Field(default_factory=list)
    base_dir: str | None = None
    created_at: str
    updated_at: str
    runs: list[RunHistoryEntry] = []
    settings: dict[str, Any] = {}
    memory: list[MemoryEntry] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Secrets
# ---------------------------------------------------------------------------


class SecretEntry(BaseModel):
    """Secret metadata (value is NEVER exposed in API responses)."""

    key: str
    created_at: str
    updated_at: str


class SecretCreate(BaseModel):
    """Request body for creating/updating a secret."""

    key: str
    value: str


# ---------------------------------------------------------------------------
# Settings (persistent)
# ---------------------------------------------------------------------------


class SettingsData(BaseModel):
    """Full settings model for persistence."""

    model: str = ""
    worker_model: str = ""
    api_key: str = ""  # stored as secret reference
    max_loops: int = 20
    max_total_tokens: int = 500_000
    max_wall_time: int = 600
    max_total_workers: int = 30
    max_tool_calls: int = 200
    max_depth: int = 5
    sandbox: str = "subprocess"
    packages: list[str] = []
    code_mode: bool = True
    tool_creation: bool = True
    tools: list[str] = []
    forbidden_tools: list[str] = []
    verbose: bool = False
    base_dir: str = ""


# ---------------------------------------------------------------------------
# WebSocket event
# ---------------------------------------------------------------------------


class RunEvent(BaseModel):
    """A single event emitted during workflow execution."""

    run_id: str
    seq: int = 0
    type: EventType
    data: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: datetime.now())


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


class SettingsUpdate(BaseModel):
    """Partial settings update from the UI."""

    # Workflow config
    model: str | None = None
    worker_model: str | None = None
    api_key: str | None = None
    max_loops: int | None = None
    max_total_tokens: int | None = None
    max_wall_time: int | None = None
    max_tool_calls: int | None = None
    max_total_workers: int | None = None
    max_depth: int | None = None
    sandbox: str | None = None
    packages: list[str] | None = None
    code_mode: bool | None = None
    tool_creation: bool | None = None
    verbose: bool | None = None

    # Critique
    critique_enabled: bool | None = None
    critique_max_repair_attempts: int | None = None

    # Manager Intelligence
    planning_enabled: bool | None = None
    planning_max_subtasks: int | None = None
    diagnosis_enabled: bool | None = None
    diagnosis_max_hypotheses: int | None = None
    diagnosis_confidence_threshold: float | None = None
    strategy_switching_enabled: bool | None = None
    budget_reservation_enabled: bool | None = None
    decision_journal_enabled: bool | None = None
    decision_journal_max_entries: int | None = None

    # UI state
    sidebar_open: bool | None = None
    inspector_open: bool | None = None
    active_panel: str | None = None
    last_session_id: str | None = None

    # Experiment base directory
    base_dir: str | None = None


# ---------------------------------------------------------------------------
# Skills / Tools / MCP
# ---------------------------------------------------------------------------


class SkillUpload(BaseModel):
    """Skill loading request."""

    path: str | None = None
    name: str | None = None


class ToolConfig(BaseModel):
    """Tool configuration entry."""

    name: str
    enabled: bool = True
    description: str = ""
    parameters: dict[str, Any] = Field(default_factory=dict)


class MCPServerConfig(BaseModel):
    """MCP (Model Context Protocol) server connection config."""

    url: str
    name: str | None = None
    api_key: str | None = None
    tools: list[str] = Field(default_factory=list, description="Tool filter.")


# ---------------------------------------------------------------------------
# Graph data (React Flow compatible)
# ---------------------------------------------------------------------------


class GraphNode(BaseModel):
    """A single node in the React Flow graph."""

    id: str
    type: str  # task | manager | iteration | worker | toolCall | completion | submanager | subRunCluster
    position: dict[str, float] = Field(default_factory=lambda: {"x": 0, "y": 0})
    data: dict[str, Any] = Field(default_factory=dict)
    # React Flow Subflows: parentNode lets a node be rendered inside another
    # node (used for sub-run clusters in A4 recursive delegation).
    parentNode: str | None = None
    extent: str | None = None  # "parent" to clip child to parent bounds
    style: dict[str, Any] = Field(default_factory=dict)
    zIndex: int | None = None


class GraphEdge(BaseModel):
    """A single edge in the React Flow graph."""

    id: str
    source: str
    target: str
    type: str = "default"
    animated: bool = False
    style: dict[str, Any] = Field(default_factory=dict)
    data: dict[str, Any] = Field(default_factory=dict)


class GraphData(BaseModel):
    """Complete graph payload for React Flow."""

    nodes: list[GraphNode] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)
    stats: dict[str, Any] = Field(default_factory=dict)
    # Dynamic tool definitions surfaced as a side-panel registry rather than
    # in-graph nodes. Each entry: {fqn, creator_agent, description, called,
    # call_count}. Consumers render this in the ToolRegistryPanel.
    tool_registry: list[dict[str, Any]] = Field(default_factory=list)
    # Persisted skills surfaced as a side-panel registry. Each entry:
    # {name, title, description, size_bytes, path}. Consumers render this
    # in the SkillRegistryPanel. Skills are cross-run shared in an
    # experiment (runtime symlinks shared/skills into every run workspace).
    skill_registry: list[dict[str, Any]] = Field(default_factory=list)
