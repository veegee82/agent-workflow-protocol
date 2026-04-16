"""REST API routes for the AWP UI server."""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
import uuid
from datetime import datetime, timezone
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
    "model": "openai/gpt-5-mini",
    "worker_model": "deepseek/deepseek-chat-v3.1",
    "api_key": None,
    "max_loops": 100,
    "max_total_tokens": 10_000_000,
    "max_wall_time": 14400,
    "max_tool_calls": 1500,
    "max_total_workers": 500,
    "max_depth": 4,
    "sandbox": "subprocess",
    "packages": [],
    "code_mode": True,
    "tool_creation": True,
    "verbose": False,
    "trace_enabled": False,
    # Critique
    "critique_enabled": True,
    "critique_max_repair_attempts": 2,
    # Manager Intelligence (all enabled by default)
    "planning_enabled": True,
    "planning_max_subtasks": 10,
    "diagnosis_enabled": True,
    "diagnosis_max_hypotheses": 3,
    "diagnosis_confidence_threshold": 0.3,
    "strategy_switching_enabled": True,
    "budget_reservation_enabled": True,
    "decision_journal_enabled": True,
    "decision_journal_max_entries": 20,
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

    model = body.get("model") or _default_settings.get("model") or "openai/gpt-5-mini"
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

    # Auto-session (Phase 2.1): if no session_id was passed, create an
    # ad-hoc session so every run automatically gets cross-run continuity
    # (experiment_context, shared/ tools, memory). Before this, only runs
    # started from the UI sidebar got a session — CLI / direct POST calls
    # bypassed continuity entirely.
    if not session_id:
        session_id = uuid.uuid4().hex[:12]
        try:
            await store.create_session(
                session_id=session_id,
                title=(config.task or "ad-hoc run")[:60],
                description="",
                hypothesis="",
                tags=["auto"],
                base_dir=_default_settings.get("base_dir") or "",
            )
            await store.update_session(session_id, status="running")
        except Exception:
            logger.warning(
                "Auto-session creation failed for run %s — falling back to "
                "session-less run (no continuity)", run_id, exc_info=True,
            )
            session_id = None

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
                experiment_dir = Path(base) / f"{title_slug}_{session_id}"
                config_dict["output_dir"] = str(experiment_dir / "runs" / run_id)
                config_dict["_experiment_dir"] = str(experiment_dir)

    # Persist to DB
    await store.save_run(
        run_id=run_id,
        task=config.task,
        model=config.model,
        config=config_dict,
        status="running",
    )

    # Auto-add to session if provided and flip status to running
    if session_id:
        session_data = await store.get_session(session_id)
        if session_data:
            await store.add_run_to_session(session_id, run_id)
            await store.update_session(session_id, status="running")

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

    # Try to find the run directory from the result metadata.
    # Prefer the exact run_dir (pinned to the root run) over the generic
    # workspace-based lookup which can land on a sub-manager directory.
    # For multi-run experiments where several runs share one workspace,
    # ``metadata.run_id`` uniquely identifies the delegation loop run
    # directory inside ``{workspace}/workspace/runs/{run_id}``.
    result = row.get("result") or {}
    metadata = result.get("metadata", {})
    explicit_run_dir = metadata.get("run_dir")
    workspace = metadata.get("workspace")
    loop_run_id = metadata.get("run_id")

    run_dir: Path | None = None
    if explicit_run_dir:
        p = Path(explicit_run_dir)
        if p.exists():
            run_dir = p
    # Prefer exact match via loop_run_id to avoid picking up a sibling
    # run in a shared workspace (multi-run experiments).
    if run_dir is None and workspace and loop_run_id:
        candidate = Path(workspace) / "workspace" / "runs" / loop_run_id
        if candidate.exists():
            run_dir = candidate
    if run_dir is None and workspace:
        workspace_path = Path(workspace)
        run_dir = find_run_dir(workspace_path)

    if run_dir:
        graph = build_graph(run_dir)
        return graph.model_dump(mode="json")

    # Fallback: derive workspace from config's output_dir (for running runs
    # before early metadata has been written or for legacy runs).
    if run_dir is None:
        config = row.get("config") or {}
        cfg_output = config.get("output_dir", "")
        if cfg_output:
            cfg_path = Path(cfg_output)
            if cfg_path.exists():
                run_dir = find_run_dir(cfg_path)
            if run_dir:
                graph = build_graph(run_dir)
                return graph.model_dump(mode="json")

    # Fallback: find via session base_dir (works for running runs
    # that don't yet have result metadata).
    if run_dir is None:
        try:
            async with store._db.execute(
                "SELECT s.base_dir FROM sessions s "
                "JOIN session_runs sr ON sr.session_id = s.id "
                "WHERE sr.run_id = ?",
                [run_id],
            ) as cursor:
                row2 = await cursor.fetchone()
                if row2 and row2[0]:
                    bd = Path(row2[0])
                    if bd.exists():
                        run_dir = find_run_dir(bd)
                        if run_dir:
                            graph = build_graph(run_dir)
                            return graph.model_dump(mode="json")
        except Exception:
            pass

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
    internal_run_id = metadata.get("run_id", "")

    # If output_dir points to the experiment base (not the output/ subdir),
    # narrow it to the output/ directory so workspace files aren't tagged
    # as output.  Keep run-specific subdirs as-is (submanager outputs are
    # merged there by _merge_submanager_outputs).
    if output_dir:
        od_path = Path(output_dir)
        # Check if output_dir is the experiment base (has output/ subdir)
        candidate = od_path / "output"
        if candidate.is_dir():
            output_dir = str(candidate)

    # Fallback: during a running E2E test, result_json is still NULL.
    # The harness stores the workflow_dir in config_json, and the session
    # has a base_dir — use those as fallbacks so artifacts are visible
    # while the run is still in progress.
    config = row.get("config") or {}
    if not output_dir and not workspace:
        workflow_dir = config.get("workflow_dir", config.get("output_dir", ""))
        if not workflow_dir:
            # Last resort: check session base_dir
            cursor = await store.db.execute(
                "SELECT s.base_dir FROM sessions s "
                "JOIN session_runs sr ON sr.session_id = s.id "
                "WHERE sr.run_id = ?",
                (run_id,),
            )
            sess_row = await cursor.fetchone()
            if sess_row and sess_row["base_dir"]:
                workflow_dir = sess_row["base_dir"]

        if workflow_dir:
            wf_path = Path(workflow_dir)
            # Scan the full output/ subdirectory (worker-produced artifacts).
            # The DelegationLoopRunner writes final outputs here — each run
            # (including submanagers) gets its own subdirectory.  We scan the
            # entire output/ folder so all results are visible.
            candidate_output = wf_path / "output"
            if candidate_output.is_dir():
                output_dir = str(candidate_output)
                workspace = workflow_dir
            else:
                # No output/ yet — scan the workspace root; output is empty
                workspace = workflow_dir

    artifacts: list[dict[str, Any]] = []
    # Scan output_dir and workspace for renderable files.
    # output_dir contains final artifacts; workspace contains intermediate
    # worker results. Both are scanned so the user sees outputs as they
    # are produced during a live run.
    # Each artifact is tagged with source="output" or source="workspace".

    # Guard: if output_dir == workspace (both point to the experiment root),
    # the narrowing above failed.  In that case, try to discover the real
    # output subdirectory inside the workspace so we don't tag *everything*
    # as source="output".
    if output_dir and workspace and Path(output_dir).resolve() == Path(workspace).resolve():
        ws_path = Path(workspace)
        # Try workspace/output/ — DelegationLoopRunner writes there
        candidate_out = ws_path / "output"
        if candidate_out.is_dir():
            output_dir = str(candidate_out)
        else:
            # No output/ subdir at all — nothing to tag as "output"
            output_dir = ""

    scan_dirs: list[tuple[Path, str]] = []
    if output_dir:
        scan_dirs.append((Path(output_dir), "output"))
    if workspace:
        scan_dirs.append((Path(workspace), "workspace"))

    IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp"}
    TABLE_EXT = {".csv", ".tsv"}
    HTML_EXT = {".html", ".htm"}
    TEXT_EXT = {".txt", ".md", ".log", ".json", ".yaml", ".yml"}
    BINARY_EXT = {
        ".zip", ".gz", ".tar", ".bz2", ".xz", ".7z", ".rar",
        ".whl", ".egg", ".pyc", ".pyo", ".so", ".dll", ".dylib",
        ".exe", ".bin", ".o", ".a", ".lib",
        ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
        ".sqlite", ".db", ".pickle", ".pkl",
        ".mp3", ".mp4", ".wav", ".avi", ".mov", ".mkv",
        ".ttf", ".otf", ".woff", ".woff2", ".eot",
        ".ico",
    }

    seen: set[str] = set()
    for scan_dir, source_tag in scan_dirs:
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
            elif ext in BINARY_EXT:
                continue
            else:
                kind = "code"
            artifacts.append({
                "name": fpath.name,
                "path": abs_path,
                "relative": rel,
                "kind": kind,
                "size": fpath.stat().st_size,
                "run_id": run_id,
                "source": source_tag,
            })

    return {"artifacts": artifacts, "run_id": run_id}


@router.get("/runs/{run_id}/trace/{worker_path:path}")
async def get_worker_trace(run_id: str, worker_path: str) -> dict[str, Any]:
    """Fetch all LLM trace call files for a specific worker or manager.

    ``worker_path`` can be:
    - ``{iteration}/{worker_id}`` — worker trace in
      ``iterations/{iteration}/delegations/{worker_id}/llm_trace/``
    - ``manager/{iteration}`` — manager trace in
      ``iterations/{iteration}/manager_trace/``
    """
    import json as _json

    from server.app import store
    from server.services.graph_builder import find_run_dir

    row = await store.get_run(run_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Run not found")

    # Resolve the run directory (same logic as get_run_graph)
    result = row.get("result") or {}
    metadata = result.get("metadata", {})
    explicit_run_dir = metadata.get("run_dir")
    workspace = metadata.get("workspace")
    loop_run_id = metadata.get("run_id")

    run_dir: Path | None = None
    if explicit_run_dir:
        p = Path(explicit_run_dir)
        if p.exists():
            run_dir = p
    if run_dir is None and workspace and loop_run_id:
        candidate = Path(workspace) / "workspace" / "runs" / loop_run_id
        if candidate.exists():
            run_dir = candidate
    if run_dir is None and workspace:
        run_dir = find_run_dir(Path(workspace))
    if run_dir is None:
        config = row.get("config") or {}
        cfg_output = config.get("output_dir", "")
        if cfg_output:
            cfg_path = Path(cfg_output)
            if cfg_path.exists():
                run_dir = find_run_dir(cfg_path)

    if run_dir is None:
        raise HTTPException(status_code=404, detail="Run directory not found")

    # Determine trace directory based on worker_path
    parts = worker_path.strip("/").split("/")
    trace_dir: Path | None = None
    if len(parts) == 2 and parts[0] == "manager":
        # manager/{iteration} → iterations/{iteration}/manager_trace/
        iteration = parts[1]
        trace_dir = run_dir / "iterations" / iteration / "manager_trace"
    elif len(parts) == 2:
        # {iteration}/{worker_id} → iterations/{iteration}/delegations/{worker_id}/llm_trace/
        iteration, worker_id = parts
        trace_dir = run_dir / "iterations" / iteration / "delegations" / worker_id / "llm_trace"
    else:
        raise HTTPException(status_code=400, detail="Invalid worker_path format; expected '{iteration}/{worker_id}' or 'manager/{iteration}'")

    if trace_dir is None or not trace_dir.exists():
        return {"calls": [], "summary": None}

    # Read all call_NNN.json files in order
    calls: list[dict[str, Any]] = []
    call_files = sorted(trace_dir.glob("call_*.json"))
    for cf in call_files:
        try:
            data = _json.loads(cf.read_text(encoding="utf-8"))
            calls.append(data)
        except (OSError, _json.JSONDecodeError):
            logger.warning("Failed to read trace file %s", cf)

    # Read summary if available
    summary: dict[str, Any] | None = None
    summary_path = trace_dir / "summary.json"
    if summary_path.exists():
        try:
            summary = _json.loads(summary_path.read_text(encoding="utf-8"))
        except (OSError, _json.JSONDecodeError):
            pass

    return {"calls": calls, "summary": summary}


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
    from datetime import datetime, timezone

    from server.app import store
    from server.services.runner_service import runner_service

    found = runner_service.stop_run(run_id)
    if not found:
        raise HTTPException(
            status_code=404, detail="Run not found or already completed"
        )
    # Persist 'stopped' status so the sidebar no longer shows the run as live.
    # The background thread may still be winding down, but from the user's
    # perspective the experiment has been stopped.
    try:
        await store.update_run(
            run_id,
            status="stopped",
            completed_at=datetime.now(tz=timezone.utc).isoformat(),
        )
    except Exception:
        logger.warning("Failed to persist stopped status for run %s", run_id, exc_info=True)
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
            experiment_dir = Path(base) / f"{title_slug}_{session_id}"
            config_dict["output_dir"] = str(experiment_dir / "runs" / run_id)
            config_dict["_experiment_dir"] = str(experiment_dir)

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
    await store.update_session(session_id, settings=session_settings, status="running")

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

        # Build graph from workspace if available. For multi-run
        # experiments, pin to the exact delegation-loop run dir
        # via metadata.run_id to avoid picking the latest sibling.
        graph_data: dict[str, Any] | None = None
        result = run.get("result") or {}
        metadata = result.get("metadata", {})
        workspace = metadata.get("workspace")
        loop_run_id = metadata.get("run_id")
        run_dir: Path | None = None
        if workspace and loop_run_id:
            candidate = Path(workspace) / "workspace" / "runs" / loop_run_id
            if candidate.exists():
                run_dir = candidate
        if run_dir is None and workspace:
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


@router.get("/sessions/{session_id}/memory/long-term")
async def list_long_term_memory(session_id: str) -> dict[str, Any]:
    """List long-term memory files (tools, facts, antipatterns) from the experiment's memory/ directory."""
    from server.app import store

    session = await store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    base_dir = session.get("base_dir", "")
    if not base_dir:
        return {"tools": [], "facts": [], "antipatterns": [], "session_id": session_id}

    memory_dir = Path(base_dir) / "memory"
    result: dict[str, list[dict[str, str]]] = {"tools": [], "facts": [], "antipatterns": []}

    for category in ("tools", "facts", "antipatterns"):
        cat_dir = memory_dir / category
        if not cat_dir.is_dir():
            continue
        for fpath in sorted(cat_dir.glob("*.md")):
            if not fpath.is_file():
                continue
            try:
                content = fpath.read_text(encoding="utf-8", errors="replace")
            except OSError:
                content = ""
            result[category].append({
                "name": fpath.stem,
                "filename": fpath.name,
                "content": content,
            })

    return {**result, "session_id": session_id}


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
