"""REST API routes for the AWP UI server."""

from __future__ import annotations

import logging
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, UploadFile, File, Query

from server.models import (
    GraphData,
    MCPServerConfig,
    RunDetail,
    RunHistoryEntry,
    SettingsUpdate,
    SkillUpload,
    ToolConfig,
    WorkflowConfig,
)

logger = logging.getLogger(__name__)

router = APIRouter()

# ---------------------------------------------------------------------------
# Default settings (mutable at runtime)
# ---------------------------------------------------------------------------

_default_settings: dict[str, Any] = {
    "model": "openrouter/anthropic/claude-sonnet-4",
    "worker_model": None,
    "api_key": None,
    "max_loops": 100,
    "max_total_tokens": 1_000_000,
    "max_wall_time": 3000,
    "max_tool_calls": 100,
    "max_total_workers": 100,
    "max_depth": 10,
    "sandbox": "subprocess",
    "packages": [],
    "code_mode": True,
    "tool_creation": True,
    "verbose": False,
}

# Loaded skills / MCP tools state
_loaded_skills: list[dict[str, Any]] = []
_mcp_servers: list[dict[str, Any]] = []
_available_tools: list[dict[str, Any]] = [
    {"name": "code.execute", "description": "Execute Python code in sandbox", "enabled": True},
    {"name": "file.read", "description": "Read a file from the workspace", "enabled": True},
    {"name": "file.write", "description": "Write a file to the workspace", "enabled": True},
    {"name": "file.list", "description": "List files in a directory", "enabled": True},
    {"name": "file.delete", "description": "Delete a file", "enabled": True},
    {"name": "arithmetic.add", "description": "Add two numbers", "enabled": True},
    {"name": "arithmetic.subtract", "description": "Subtract two numbers", "enabled": True},
    {"name": "arithmetic.multiply", "description": "Multiply two numbers", "enabled": True},
    {"name": "arithmetic.divide", "description": "Divide two numbers", "enabled": True},
]


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------


@router.post("/runs")
async def create_run(config: WorkflowConfig) -> dict[str, Any]:
    """Start a new workflow run. Returns the run_id immediately."""
    from server.app import store
    from server.services.runner_service import runner_service

    run_id = uuid.uuid4().hex[:12]

    # Persist to DB
    await store.save_run(
        run_id=run_id,
        task=config.task,
        model=config.model,
        config=config.model_dump(mode="json"),
        status="running",
    )

    # Start the run in a background thread
    runner_service.start_run(run_id, config.model_dump(mode="json"))

    return {"run_id": run_id, "status": "running"}


@router.get("/runs")
async def list_runs(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    """List all runs with pagination."""
    from server.app import store

    rows = await store.list_runs(limit=limit, offset=offset)
    entries = [
        RunHistoryEntry(
            run_id=r["run_id"],
            task=r["task"],
            model=r["model"],
            status=r["status"],
            created_at=r["created_at"],
            completed_at=r.get("completed_at"),
        )
        for r in rows
    ]
    return {"runs": [e.model_dump() for e in entries], "total": len(entries)}


@router.get("/runs/{run_id}")
async def get_run(run_id: str) -> dict[str, Any]:
    """Get full run detail including result."""
    from server.app import store

    row = await store.get_run(run_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Run not found")

    detail = RunDetail(
        run_id=row["run_id"],
        task=row["task"],
        model=row["model"],
        status=row["status"],
        config=row.get("config", {}),
        result=row.get("result"),
        created_at=row["created_at"],
        completed_at=row.get("completed_at"),
    )
    return detail.model_dump(mode="json")


@router.get("/runs/{run_id}/events")
async def get_run_events(
    run_id: str,
    since_seq: int = Query(0, ge=0),
) -> dict[str, Any]:
    """Get all events for a run, optionally filtering by sequence number."""
    from server.app import store

    events = await store.get_events(run_id, since_seq=since_seq)
    return {"events": events}


@router.get("/runs/{run_id}/graph")
async def get_run_graph(run_id: str) -> dict[str, Any]:
    """Get the agent execution graph in React Flow format."""
    from server.app import store
    from server.services.graph_builder import build_graph, find_run_dir

    row = await store.get_run(run_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Run not found")

    # Try to find the run directory from the result metadata
    result = row.get("result") or {}
    metadata = result.get("metadata", {})
    workspace = metadata.get("workspace")

    if workspace:
        workspace_path = Path(workspace)
        run_dir = find_run_dir(workspace_path)
        if run_dir:
            graph = build_graph(run_dir)
            return graph.model_dump(mode="json")

    # Return empty graph if no run directory found
    return GraphData().model_dump(mode="json")


@router.delete("/runs/{run_id}")
async def delete_run(run_id: str) -> dict[str, str]:
    """Delete a run and its events."""
    from server.app import store

    deleted = await store.delete_run(run_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Run not found")
    return {"status": "deleted"}


@router.post("/runs/{run_id}/stop")
async def stop_run(run_id: str) -> dict[str, Any]:
    """Signal a running workflow to stop."""
    from server.services.runner_service import runner_service

    found = runner_service.stop_run(run_id)
    if not found:
        raise HTTPException(
            status_code=404, detail="Run not found or already completed"
        )
    return {"status": "stopping", "run_id": run_id}


# ---------------------------------------------------------------------------
# File upload
# ---------------------------------------------------------------------------


@router.post("/upload")
async def upload_files(files: list[UploadFile] = File(...)) -> dict[str, Any]:
    """Upload files and return their temporary paths."""
    upload_dir = Path(tempfile.mkdtemp(prefix="awp_upload_"))
    paths: list[str] = []

    for file in files:
        if not file.filename:
            continue
        dest = upload_dir / file.filename
        dest.parent.mkdir(parents=True, exist_ok=True)
        content = await file.read()
        dest.write_bytes(content)
        paths.append(str(dest))
        logger.info("Uploaded file: %s (%d bytes)", dest, len(content))

    return {"paths": paths, "upload_dir": str(upload_dir)}


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


@router.get("/settings")
async def get_settings() -> dict[str, Any]:
    """Get current default settings."""
    return dict(_default_settings)


@router.post("/settings")
async def update_settings(update: SettingsUpdate) -> dict[str, Any]:
    """Update default settings. Only non-None fields are applied."""
    for field, value in update.model_dump(exclude_none=True).items():
        _default_settings[field] = value
    return dict(_default_settings)


# ---------------------------------------------------------------------------
# Skills
# ---------------------------------------------------------------------------


@router.post("/skills/load")
async def load_skill(skill: SkillUpload) -> dict[str, Any]:
    """Load a skill from a path."""
    if not skill.path:
        raise HTTPException(status_code=400, detail="path is required")

    skill_path = Path(skill.path)
    if not skill_path.exists():
        raise HTTPException(status_code=404, detail=f"Skill path not found: {skill.path}")

    entry = {
        "path": str(skill_path.resolve()),
        "name": skill.name or skill_path.stem,
    }
    _loaded_skills.append(entry)
    logger.info("Loaded skill: %s from %s", entry["name"], entry["path"])

    return {"status": "loaded", "skill": entry, "total_skills": len(_loaded_skills)}


# ---------------------------------------------------------------------------
# Tools / MCP
# ---------------------------------------------------------------------------


@router.post("/tools/mcp")
async def connect_mcp_server(config: MCPServerConfig) -> dict[str, Any]:
    """Connect to an MCP server and discover its tools."""
    entry = {
        "url": config.url,
        "name": config.name or config.url,
        "tools": config.tools,
        "status": "connected",
    }
    _mcp_servers.append(entry)
    logger.info("Connected to MCP server: %s", entry["name"])

    # In a production implementation, this would actually connect to the MCP
    # server via the AWP runtime's ExternalTool.from_mcp() and discover tools.
    # For now, we register the config for use in workflow runs.

    return {"status": "connected", "server": entry}


@router.get("/tools/available")
async def list_available_tools() -> dict[str, Any]:
    """List all available tools including built-in and MCP tools."""
    tools = list(_available_tools)

    # Add tools from MCP servers
    for server in _mcp_servers:
        for tool_name in server.get("tools", []):
            tools.append({
                "name": tool_name,
                "description": f"MCP tool from {server['name']}",
                "enabled": True,
                "source": "mcp",
                "server": server["name"],
            })

    return {"tools": tools}
