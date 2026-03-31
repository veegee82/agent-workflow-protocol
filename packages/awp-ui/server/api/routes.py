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
    SecretCreate,
    SessionDetail,
    SessionInfo,
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
    # UI state
    "sidebar_open": True,
    "inspector_open": True,
    "active_panel": "output",
    "last_session_id": None,
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
async def create_run(config: WorkflowConfig, session_id: str | None = Query(None)) -> dict[str, Any]:
    """Start a new workflow run. Returns the run_id immediately.

    If session_id is provided, the run is automatically added to that session.
    """
    from server.app import store
    from server.services.runner_service import runner_service

    run_id = uuid.uuid4().hex[:12]

    # Inject secrets from the store into the config
    config_dict = config.model_dump(mode="json")
    stored_secrets = await _load_secrets_for_run(store)
    if stored_secrets:
        merged = dict(stored_secrets)
        merged.update(config_dict.get("secrets") or {})
        config_dict["secrets"] = merged

    # Persist to DB
    await store.save_run(
        run_id=run_id,
        task=config.task,
        model=config.model,
        config=config_dict,
        status="running",
    )

    # Auto-add to session if provided
    if session_id:
        session = await store.get_session(session_id)
        if session:
            await store.add_run_to_session(session_id, run_id)

    # Start the run in a background thread
    runner_service.start_run(run_id, config_dict)

    return {"run_id": run_id, "status": "running", "session_id": session_id}


async def _load_secrets_for_run(store: Any) -> dict[str, str]:
    """Load all secrets from the store and return as a dict for injection."""
    secret_keys = await store.list_secrets()
    secrets: dict[str, str] = {}
    for key in secret_keys:
        value = await store.get_secret(key)
        if value is not None:
            secrets[key] = value
    return secrets


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

    # Redact secrets from config before returning
    config = dict(row.get("config", {}))
    if "secrets" in config:
        config["secrets"] = {k: "***" for k in config["secrets"]}
    if "api_key" in config and config["api_key"]:
        config["api_key"] = "***"

    detail = RunDetail(
        run_id=row["run_id"],
        task=row["task"],
        model=row["model"],
        status=row["status"],
        config=config,
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


@router.get("/runs/{run_id}/artifacts")
async def list_run_artifacts(run_id: str) -> dict[str, Any]:
    """List all output artifacts (images, tables, HTML, text) for a run."""
    from server.app import store

    row = await store.get_run(run_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Run not found")

    result = row.get("result") or {}
    metadata = result.get("metadata", {})
    workspace = metadata.get("workspace", "")
    output_dir = metadata.get("output_dir", "")

    artifacts: list[dict[str, Any]] = []
    # Scan workspace and output_dir for renderable files
    scan_dirs = []
    if output_dir:
        scan_dirs.append(Path(output_dir))
    if workspace:
        scan_dirs.append(Path(workspace))

    IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp"}
    TABLE_EXT = {".csv", ".tsv"}
    HTML_EXT = {".html", ".htm"}
    TEXT_EXT = {".txt", ".md", ".log", ".json", ".yaml", ".yml"}

    seen: set[str] = set()
    for scan_dir in scan_dirs:
        if not scan_dir.exists():
            continue
        for fpath in sorted(scan_dir.rglob("*")):
            if not fpath.is_file():
                continue
            abs_path = str(fpath.resolve())
            if abs_path in seen:
                continue
            seen.add(abs_path)
            ext = fpath.suffix.lower()
            rel = str(fpath.relative_to(scan_dir))
            if ext in IMAGE_EXT:
                kind = "image"
            elif ext in TABLE_EXT:
                kind = "table"
            elif ext in HTML_EXT:
                kind = "html"
            elif ext in TEXT_EXT:
                kind = "text"
            elif ext == ".py":
                kind = "code"
            else:
                continue
            artifacts.append({
                "name": fpath.name,
                "path": abs_path,
                "relative": rel,
                "kind": kind,
                "size": fpath.stat().st_size,
                "run_id": run_id,
            })

    return {"artifacts": artifacts, "run_id": run_id}


@router.get("/files/serve")
async def serve_file(path: str = Query(...)) -> Any:
    """Serve a file from the workspace by absolute path."""
    from fastapi.responses import FileResponse

    file_path = Path(path)
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    # Security: only serve files from /tmp or known workspace dirs
    abs_str = str(file_path.resolve())
    if not (abs_str.startswith("/tmp/") or abs_str.startswith("/home/")):
        raise HTTPException(status_code=403, detail="Access denied")

    return FileResponse(file_path)


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
    """Get current default settings (loaded from SQLite, falling back to defaults)."""
    from server.app import store

    persisted = await store.get_settings()
    if persisted:
        # Merge persisted over defaults so new keys have defaults
        merged = dict(_default_settings)
        merged.update(persisted)
        return merged
    return dict(_default_settings)


@router.post("/settings")
async def update_settings(update: SettingsUpdate) -> dict[str, Any]:
    """Update default settings. Persists to SQLite."""
    from server.app import store

    # Load current persisted settings or start from defaults
    persisted = await store.get_settings()
    current = dict(_default_settings)
    if persisted:
        current.update(persisted)

    # Apply non-None updates
    for field, value in update.model_dump(exclude_none=True).items():
        current[field] = value
        _default_settings[field] = value

    # Persist to DB
    await store.save_settings(current)
    return current


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


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------


@router.post("/sessions")
async def create_session(body: dict[str, Any]) -> dict[str, Any]:
    """Create a new session."""
    from server.app import store

    session_id = uuid.uuid4().hex[:12]
    title = body.get("title", "Untitled Session")
    await store.create_session(session_id, title)
    session = await store.get_session(session_id)
    return session or {"id": session_id, "title": title}


@router.get("/sessions")
async def list_sessions(
    limit: int = Query(50, ge=1, le=500),
) -> dict[str, Any]:
    """List all sessions, newest first."""
    from server.app import store

    rows = await store.list_sessions(limit=limit)
    entries = [
        SessionInfo(
            id=r["id"],
            title=r["title"],
            created_at=r["created_at"],
            updated_at=r["updated_at"],
            run_count=r["run_count"],
            last_run_status=r.get("last_run_status"),
        )
        for r in rows
    ]
    return {"sessions": [e.model_dump() for e in entries]}


@router.get("/sessions/{session_id}")
async def get_session(session_id: str) -> dict[str, Any]:
    """Get session detail with runs."""
    from server.app import store

    session = await store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    runs = await store.get_session_runs(session_id)
    run_entries = [
        RunHistoryEntry(
            run_id=r["run_id"],
            task=r["task"],
            model=r["model"],
            status=r["status"],
            created_at=r["created_at"],
            completed_at=r.get("completed_at"),
        )
        for r in runs
    ]

    detail = SessionDetail(
        id=session["id"],
        title=session["title"],
        created_at=session["created_at"],
        updated_at=session["updated_at"],
        runs=run_entries,
        settings=session.get("settings", {}),
    )
    return detail.model_dump()


@router.put("/sessions/{session_id}")
async def update_session(session_id: str, body: dict[str, Any]) -> dict[str, Any]:
    """Rename session."""
    from server.app import store

    session = await store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    title = body.get("title")
    await store.update_session(session_id, title=title)
    updated = await store.get_session(session_id)
    return updated or session


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str) -> dict[str, str]:
    """Delete session and all its run links."""
    from server.app import store

    deleted = await store.delete_session(session_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"status": "deleted"}


@router.post("/sessions/{session_id}/runs")
async def add_run_to_session(session_id: str, body: dict[str, Any]) -> dict[str, Any]:
    """Create a run within a session."""
    from server.app import store
    from server.services.runner_service import runner_service

    session = await store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    # Build a WorkflowConfig from the body
    config = WorkflowConfig(**body)
    run_id = uuid.uuid4().hex[:12]

    # Inject secrets
    config_dict = config.model_dump(mode="json")
    stored_secrets = await _load_secrets_for_run(store)
    if stored_secrets:
        merged = dict(stored_secrets)
        merged.update(config_dict.get("secrets") or {})
        config_dict["secrets"] = merged

    await store.save_run(
        run_id=run_id,
        task=config.task,
        model=config.model,
        config=config_dict,
        status="running",
    )
    await store.add_run_to_session(session_id, run_id)

    # Persist session settings (config without task/secrets for reproducibility)
    session_settings = {
        k: v for k, v in config_dict.items()
        if k not in ("task", "secrets", "api_key", "input_files")
    }
    await store.update_session(session_id, settings=session_settings)

    runner_service.start_run(run_id, config_dict)

    return {"run_id": run_id, "status": "running", "session_id": session_id}


@router.get("/sessions/{session_id}/history")
async def get_session_history(session_id: str) -> dict[str, Any]:
    """Get chat-like history for session (tasks + results)."""
    from server.app import store

    session = await store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    history = await store.get_session_history(session_id)
    return {"session_id": session_id, "history": history}


@router.get("/sessions/{session_id}/full")
async def get_session_full(session_id: str) -> dict[str, Any]:
    """Load a complete session with all runs, events, and config for full restore."""
    from server.app import store
    from server.services.graph_builder import build_graph, find_run_dir

    session = await store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    runs = await store.get_session_runs(session_id)
    runs_with_events: list[dict[str, Any]] = []

    for run in runs:
        events = await store.get_events(run["run_id"])

        # Redact secrets
        config = dict(run.get("config", {}))
        if "secrets" in config:
            config["secrets"] = {k: "***" for k in config["secrets"]}
        if config.get("api_key"):
            config["api_key"] = "***"

        # Build graph from workspace if available
        graph_data: dict[str, Any] | None = None
        result = run.get("result") or {}
        metadata = result.get("metadata", {})
        workspace = metadata.get("workspace")
        if workspace:
            run_dir = find_run_dir(Path(workspace))
            if run_dir:
                graph_data = build_graph(run_dir).model_dump(mode="json")

        runs_with_events.append({
            "run_id": run["run_id"],
            "task": run["task"],
            "model": run["model"],
            "status": run["status"],
            "config": config,
            "result": run.get("result"),
            "events": events,
            "graph": graph_data,
            "created_at": run["created_at"],
            "completed_at": run.get("completed_at"),
        })

    return {
        "session": {
            "id": session["id"],
            "title": session["title"],
            "created_at": session["created_at"],
            "updated_at": session["updated_at"],
            "settings": session.get("settings", {}),
        },
        "runs": runs_with_events,
    }


# ---------------------------------------------------------------------------
# Secrets
# ---------------------------------------------------------------------------


@router.get("/secrets")
async def list_secrets() -> dict[str, Any]:
    """List secret keys (values never exposed)."""
    from server.app import store

    metadata = await store.list_secrets_metadata()
    return {"secrets": metadata}


@router.post("/secrets")
async def create_secret(body: SecretCreate) -> dict[str, Any]:
    """Store a secret."""
    from server.app import store

    await store.save_secret(body.key, body.value)
    return {"status": "saved", "key": body.key}


@router.delete("/secrets/{key}")
async def delete_secret(key: str) -> dict[str, str]:
    """Delete a secret."""
    from server.app import store

    deleted = await store.delete_secret(key)
    if not deleted:
        raise HTTPException(status_code=404, detail="Secret not found")
    return {"status": "deleted"}
