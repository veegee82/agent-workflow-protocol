"""REST API routes for the AWP UI server."""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, UploadFile, File, Query

from server.models import (
    GraphData,
    MCPServerConfig,
    MemoryCreate,
    MemoryEntry,
    MemoryUpdate,
    RunDetail,
    RunHistoryEntry,
    SecretCreate,
    SessionDetail,
    SessionInfo,
    SessionUpdate,
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
    "model": "openai/gpt-5-nano",
    "worker_model": None,
    "api_key": None,
    "max_loops": 100,
    "max_total_tokens": 10_000_000,
    "max_wall_time": 600,
    "max_tool_calls": 250,
    "max_total_workers": 500,
    "max_depth": 10,
    "sandbox": "subprocess",
    "packages": [],
    "code_mode": True,
    "tool_creation": True,
    "verbose": False,
    # UI state
    "sidebar_open": True,
    "inspector_open": True,
    "active_panel": "protocol",
    "last_session_id": None,
    # Experiment base directory
    "base_dir": "",
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
# Task Refactoring
# ---------------------------------------------------------------------------


@router.post("/refactor-task")
async def refactor_task(body: dict[str, Any]) -> dict[str, Any]:
    """Use the manager LLM to refactor a vague task into a structured prompt."""
    from awp.runtime.llm import LLMClient
    from server.app import store as _store

    task = (body.get("task") or "").strip()
    if not task:
        raise HTTPException(status_code=400, detail="task is required")

    model = body.get("model") or _default_settings.get("model") or "openai/gpt-5-nano"
    api_key = body.get("api_key") or ""

    # Resolve API key from secrets if not provided directly
    if not api_key:
        secrets = await _load_secrets_for_run(_store)
        import re as _re
        m = model.lower().strip()
        if _re.match(r"^(gpt-|o[0-9]|dall-e|text-|tts-|whisper)", m):
            api_key = secrets.get("OPENAI_API_KEY", "") or os.environ.get("OPENAI_API_KEY", "")
        elif m.startswith("claude-"):
            api_key = secrets.get("ANTHROPIC_API_KEY", "") or os.environ.get("ANTHROPIC_API_KEY", "")
        else:
            api_key = secrets.get("OPENROUTER_API_KEY", "") or os.environ.get("OPENROUTER_API_KEY", "")
        if not api_key:
            api_key = secrets.get("LLM_API_KEY", "") or os.environ.get("LLM_API_KEY", "")

    if not api_key:
        raise HTTPException(
            status_code=400,
            detail="No API key available. Add one in Settings → API Keys.",
        )

    system_prompt = (
        "You are a task refactoring assistant. Your job is to take a user's raw, "
        "potentially vague task description and rewrite it into a clear, structured "
        "prompt that a manager agent can execute precisely.\n\n"
        "CRITICAL: Preserve the user's original language. If the task is in German, "
        "write the refactored version in German. If in English, write in English. "
        "Do NOT translate.\n\n"
        "CRITICAL: Do NOT add scope or requirements the user did not mention. "
        "Only clarify and structure what is already implied.\n\n"
        "Rewrite the task using this exact structure:\n\n"
        "## Objective\n"
        "One clear sentence describing what must be accomplished.\n\n"
        "## Context\n"
        "- Background information and constraints the agent needs\n"
        "- Assumptions being made\n\n"
        "## Goals\n"
        "1. First specific, measurable goal\n"
        "2. Second goal (if applicable)\n\n"
        "## Deliverables\n"
        "- [ ] Concrete output artifact 1\n"
        "- [ ] Concrete output artifact 2\n\n"
        "## Success Criteria\n"
        "- How to verify the task is complete\n"
        "- Expected quality bar\n\n"
        "Return ONLY the refactored task text. No meta-commentary, no preamble, "
        "no explanations outside the structure above."
    )

    try:
        client = LLMClient(model=model, api_key=api_key)
        refactored = await _run_llm_in_thread(client, system_prompt, task, model)
    except Exception as exc:
        logger.exception("Task refactoring failed")
        raise HTTPException(status_code=500, detail=f"LLM call failed: {exc}")

    return {"original_task": task, "refactored_task": refactored}


async def _run_llm_in_thread(client: Any, system_prompt: str, task: str, model: str) -> str:
    """Run blocking LLMClient.chat_text in a thread pool."""
    import asyncio

    def _do() -> str:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": task},
        ]
        return client.chat_text(messages, model=model)

    return await asyncio.get_event_loop().run_in_executor(None, _do)


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------


@router.post("/runs/preflight")
async def preflight_check(config: WorkflowConfig) -> dict[str, Any]:
    """Check if a run can succeed before starting it (API key validation)."""
    import re as _re
    from server.app import store as _store

    model = (config.model or "").lower().strip()
    secrets = await _load_secrets_for_run(_store)

    if model.startswith("ollama/") or model.startswith("localhost"):
        return {"ok": True, "provider": "Ollama (local)"}

    if _re.match(r"^(gpt-|o[0-9]|dall-e|text-|tts-|whisper)", model):
        required = "OPENAI_API_KEY"
        provider = "OpenAI"
    elif model.startswith("claude-"):
        required = "ANTHROPIC_API_KEY"
        provider = "Anthropic"
    else:
        required = "OPENROUTER_API_KEY"
        provider = "OpenRouter"

    has_key = bool(
        secrets.get(required)
        or os.environ.get(required)
        or secrets.get("LLM_API_KEY")
        or os.environ.get("LLM_API_KEY")
    )

    if has_key:
        return {"ok": True, "provider": provider}
    return {
        "ok": False,
        "provider": provider,
        "required_key": required,
        "message": f"No {required} found. Add it in Settings → API Keys.",
    }


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

    # Resolve output_dir from session base_dir if applicable
    if session_id and not config_dict.get("output_dir"):
        session = await store.get_session(session_id)
        if session:
            experiment_base = session.get("base_dir") or ""
            global_base = _default_settings.get("base_dir") or ""
            base = experiment_base or global_base
            if base:
                import re
                title_slug = (
                    session.get("title", "experiment")
                    .lower()
                    .replace(" ", "_")[:40]
                )
                title_slug = re.sub(r"[^a-z0-9_-]", "", title_slug) or "experiment"
                config_dict["output_dir"] = str(Path(base) / f"{title_slug}_{session_id}")

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
        session_data = await store.get_session(session_id)
        if session_data:
            await store.add_run_to_session(session_id, run_id)

    # Start the run in a background thread (pass session_id for experiment context)
    runner_service.start_run(run_id, config_dict, session_id=session_id)

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

    # Security: only serve files from temp dirs, home, or known workspace dirs
    import tempfile
    resolved = file_path.resolve()
    allowed_roots = [
        Path(tempfile.gettempdir()).resolve(),
        Path.home().resolve(),
    ]
    # Also allow base_dir from settings (e.g. ~/awp-experiments)
    global_base = _default_settings.get("base_dir")
    if global_base:
        allowed_roots.append(Path(global_base).resolve())
    if not any(resolved == root or root in resolved.parents for root in allowed_roots):
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
# Open directory in system file explorer
# ---------------------------------------------------------------------------


@router.post("/open-directory")
async def open_directory(body: dict[str, Any]) -> dict[str, Any]:
    """Open a directory in the system file explorer."""
    import platform
    import subprocess as sp

    dir_path = body.get("path", "")
    if not dir_path:
        raise HTTPException(status_code=400, detail="path is required")

    target = Path(dir_path)
    if not target.exists():
        # Try to create it
        try:
            target.mkdir(parents=True, exist_ok=True)
        except OSError:
            raise HTTPException(status_code=404, detail=f"Directory not found: {dir_path}")

    try:
        system = platform.system()
        if system == "Darwin":
            sp.Popen(["open", str(target)])
        elif system == "Windows":
            sp.Popen(["explorer", str(target)])
        else:
            sp.Popen(["xdg-open", str(target)])
        return {"status": "opened", "path": str(target)}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to open: {exc}")


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


@router.post("/skills/scan")
async def scan_skills_directory(body: dict[str, Any]) -> dict[str, Any]:
    """Scan a directory for skill files/subdirectories.

    Looks for:
    - .md files (single-file skills)
    - Subdirectories containing SKILL.md (directory skills)
    - .zip / .skill archives
    """
    dir_path = body.get("path", "")
    if not dir_path:
        raise HTTPException(status_code=400, detail="path is required")

    target = Path(dir_path).expanduser().resolve()
    if not target.exists():
        raise HTTPException(status_code=404, detail=f"Directory not found: {dir_path}")
    if not target.is_dir():
        raise HTTPException(status_code=400, detail=f"Not a directory: {dir_path}")

    skills: list[dict[str, Any]] = []

    try:
        for entry in sorted(target.iterdir()):
            if entry.name.startswith("."):
                continue

            if entry.is_file():
                ext = entry.suffix.lower()
                if ext == ".md":
                    skills.append({
                        "name": entry.stem,
                        "path": str(entry),
                        "type": "file",
                        "size": entry.stat().st_size,
                    })
                elif ext in (".zip", ".skill"):
                    skills.append({
                        "name": entry.stem,
                        "path": str(entry),
                        "type": "archive",
                        "size": entry.stat().st_size,
                    })

            elif entry.is_dir():
                # Check if it's a skill directory (contains SKILL.md)
                skill_md = entry / "SKILL.md"
                if skill_md.exists():
                    skills.append({
                        "name": entry.name,
                        "path": str(entry),
                        "type": "directory",
                    })
    except PermissionError:
        raise HTTPException(status_code=403, detail=f"Permission denied: {dir_path}")

    return {
        "directory": str(target),
        "skills": skills,
        "count": len(skills),
    }


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
    """Create a new experiment."""
    from server.app import store

    session_id = uuid.uuid4().hex[:12]
    title = body.get("title", "Untitled Experiment")

    # Resolve base_dir: explicit > global setting > default ~/awp-experiments
    base_dir = body.get("base_dir") or ""
    if not base_dir:
        base_dir = _default_settings.get("base_dir") or ""
    if not base_dir:
        base_dir = str(Path.home() / "awp-experiments")
        # Persist as global default so all future sessions use it
        _default_settings["base_dir"] = base_dir
        await store.save_settings(dict(_default_settings))

    # Ensure base_dir exists
    try:
        Path(base_dir).mkdir(parents=True, exist_ok=True)
    except OSError:
        pass

    await store.create_session(
        session_id,
        title=title,
        description=body.get("description", ""),
        hypothesis=body.get("hypothesis", ""),
        tags=body.get("tags"),
        base_dir=base_dir,
    )
    session = await store.get_session(session_id)
    return session or {"id": session_id, "title": title}


@router.get("/sessions")
async def list_sessions(
    limit: int = Query(50, ge=1, le=500),
) -> dict[str, Any]:
    """List all experiments, newest first."""
    from server.app import store

    rows = await store.list_sessions(limit=limit)
    entries = [
        SessionInfo(
            id=r["id"],
            title=r["title"],
            description=r.get("description", ""),
            hypothesis=r.get("hypothesis", ""),
            status=r.get("status", "draft"),
            tags=r.get("tags", []),
            base_dir=r.get("base_dir"),
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
    """Get experiment detail with runs and memory."""
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

    memory_rows = await store.get_memory_entries(session_id)
    memory_entries = [MemoryEntry(**m) for m in memory_rows]

    detail = SessionDetail(
        id=session["id"],
        title=session["title"],
        description=session.get("description", ""),
        hypothesis=session.get("hypothesis", ""),
        status=session.get("status", "draft"),
        tags=session.get("tags", []),
        base_dir=session.get("base_dir"),
        created_at=session["created_at"],
        updated_at=session["updated_at"],
        runs=run_entries,
        settings=session.get("settings", {}),
        memory=memory_entries,
    )
    return detail.model_dump()


@router.put("/sessions/{session_id}")
async def update_session(session_id: str, body: SessionUpdate) -> dict[str, Any]:
    """Update experiment metadata."""
    from server.app import store

    session = await store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    update_data = body.model_dump(exclude_none=True)
    if update_data:
        await store.update_session(session_id, **update_data)
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

    # Resolve output_dir from experiment base_dir if not explicitly set
    if not config_dict.get("output_dir"):
        experiment_base = session.get("base_dir") or ""
        global_base = _default_settings.get("base_dir") or ""
        base = experiment_base or global_base
        if base:
            # Create experiment-specific subdirectory: base_dir/experiment_title_slug/
            title_slug = (
                session.get("title", "experiment")
                .lower()
                .replace(" ", "_")[:40]
            )
            import re
            title_slug = re.sub(r"[^a-z0-9_-]", "", title_slug) or "experiment"
            config_dict["output_dir"] = str(Path(base) / f"{title_slug}_{session_id}")

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

    runner_service.start_run(run_id, config_dict, session_id=session_id)

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

    memory_rows = await store.get_memory_entries(session_id)

    return {
        "session": {
            "id": session["id"],
            "title": session["title"],
            "description": session.get("description", ""),
            "hypothesis": session.get("hypothesis", ""),
            "status": session.get("status", "draft"),
            "tags": session.get("tags", []),
            "base_dir": session.get("base_dir"),
            "created_at": session["created_at"],
            "updated_at": session["updated_at"],
            "settings": session.get("settings", {}),
        },
        "runs": runs_with_events,
        "memory": memory_rows,
    }


# ---------------------------------------------------------------------------
# Experiment Memory
# ---------------------------------------------------------------------------


@router.get("/sessions/{session_id}/memory")
async def list_memory(session_id: str) -> dict[str, Any]:
    """List all memory entries for an experiment."""
    from server.app import store

    session = await store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    entries = await store.get_memory_entries(session_id)
    return {"memory": entries, "session_id": session_id}


@router.post("/sessions/{session_id}/memory")
async def create_memory(session_id: str, body: MemoryCreate) -> dict[str, Any]:
    """Add a memory entry to an experiment."""
    from server.app import store

    session = await store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    entry = await store.save_memory_entry(
        session_id=session_id,
        content=body.content,
        entry_type=body.type,
        source=body.source,
        run_id=body.run_id,
    )
    return entry


@router.put("/sessions/{session_id}/memory/{memory_id}")
async def update_memory(session_id: str, memory_id: int, body: MemoryUpdate) -> dict[str, Any]:
    """Update a memory entry."""
    from server.app import store

    updated = await store.update_memory_entry(memory_id, body.content)
    if not updated:
        raise HTTPException(status_code=404, detail="Memory entry not found")
    return {"status": "updated", "id": memory_id}


@router.delete("/sessions/{session_id}/memory/{memory_id}")
async def delete_memory(session_id: str, memory_id: int) -> dict[str, str]:
    """Delete a memory entry."""
    from server.app import store

    deleted = await store.delete_memory_entry(memory_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Memory entry not found")
    return {"status": "deleted"}


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
