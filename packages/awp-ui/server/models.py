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
    LOG = "log"
    ERROR = "error"
    RUN_START = "run.start"
    RUN_COMPLETE = "run.complete"
    GRAPH_UPDATE = "graph.update"


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
    type: str  # task | manager | iteration | worker | toolCall | completion
    position: dict[str, float] = Field(default_factory=lambda: {"x": 0, "y": 0})
    data: dict[str, Any] = Field(default_factory=dict)


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
