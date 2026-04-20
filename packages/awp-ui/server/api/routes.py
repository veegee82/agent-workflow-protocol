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


# ---------------------------------------------------------------------------
# Outer-loop / Optimizer (A5) — read-only views into ~/.awp/outer_loop.db
# ---------------------------------------------------------------------------


@router.get("/runs/{run_id}/epoch")
async def get_run_epoch(run_id: str) -> Any:
    """Return the optimizer epoch context for a run, or null if none.

    The run_id is looked up in the outer-loop ``epoch_runs`` table
    (``~/.awp/outer_loop.db`` or ``$AWP_OUTER_LOOP_DB``). If the run is
    not part of any epoch, we return ``null`` — this is the common case
    for ad-hoc runs that never went through ``awp optimize``.
    """
    from server.services.outer_loop_service import get_run_epoch as _get

    return _get(run_id)


@router.get("/suites")
async def list_outer_loop_suites() -> dict[str, Any]:
    """List every task suite tracked by the outer-loop DB."""
    from server.services.outer_loop_service import list_suites

    return {"suites": list_suites()}


@router.get("/suites/{suite_id}/epochs")
async def get_suite_epochs(suite_id: str) -> dict[str, Any]:
    """Return every epoch of a suite with per-task losses and artifact events.

    Shape::

        { "epochs": [
            { "epoch_id", "epoch_num", "started_at", "completed_at",
              "mean_loss", "parent_artifacts": {name: version},
              "child_artifacts": {name: version},
              "events": [{"type": "update"|"rollback", ...}, ...],
              "per_task_losses": [
                {"run_id", "task_name", "loss", "scores": {...}}, ...
              ]
            }, ...
        ]}

    Returns 404 if the suite (or the outer-loop DB) does not exist.
    """
    from server.services.outer_loop_service import list_suite_epochs

    epochs = list_suite_epochs(suite_id)
    if epochs is None:
        raise HTTPException(status_code=404, detail="Suite not found")
    return {"epochs": epochs}


@router.get("/artifacts/{name}/versions")
async def get_artifact_versions(name: str) -> dict[str, Any]:
    """Return every version (including synthetic v0) of an artifact.

    Shape::

        { "versions": [
            {"version": 0, "content": "...", "parent_version": null,
             "created_at": "...", "is_active": true|false}, ...
        ]}

    404 if the artifact name is unknown (not in ``DEFAULTS``). The
    endpoint always returns at least the synthetic v0 default — even when
    the outer-loop DB is missing.
    """
    from server.services.outer_loop_service import list_artifact_versions

    versions = list_artifact_versions(name)
    if versions is None:
        raise HTTPException(status_code=404, detail="Artifact not found")
    return {"versions": versions}


@router.get("/suites/{suite_id}/graph")
async def get_suite_graph(suite_id: str) -> dict[str, Any]:
    """Return the chained graph for every run across every epoch of a suite.

    Each run's React Flow graph is rendered via the existing
    :func:`server.services.graph_builder.build_graph` and then stitched
    together vertically with decorative ``epochMarker`` nodes inserted
    between consecutive epochs. The marker carries the epoch number,
    mean loss, and the artifact delta vs the previous epoch.
    """
    from server.services.graph_builder import build_graph, find_run_dir
    from server.services.outer_loop_service import (
        get_suite_graph_runs,
        get_suite_meta,
    )
    from server.app import store

    suite_meta = get_suite_meta(suite_id)
    if suite_meta is None:
        raise HTTPException(status_code=404, detail="Suite not found")

    epoch_runs = get_suite_graph_runs(suite_id)
    if not epoch_runs:
        return {
            "nodes": [],
            "edges": [],
            "stats": {
                "suite_id": suite_id,
                "suite_name": suite_meta["name"],
                "epoch_count": 0,
                "run_count": 0,
            },
            "tool_registry": [],
            "skill_registry": [],
        }

    # Y-stacking: each run occupies ~1200 px vertically; epoch markers
    # are 140 px tall and sit between epoch blocks.
    run_block_height = 1200.0
    marker_height = 140.0

    chained_nodes: list[dict[str, Any]] = []
    chained_edges: list[dict[str, Any]] = []
    y_cursor = 0.0
    prev_epoch_num: int | None = None
    prev_child: dict[str, int] = {}

    for entry in epoch_runs:
        # Insert an epoch marker at the start of each new epoch
        if prev_epoch_num != entry["epoch_num"]:
            delta_label = _format_artifact_delta(prev_child, entry["parent_artifacts"])
            loss_str = (
                f"{entry['mean_loss']:.3f}"
                if entry["mean_loss"] is not None
                else "pending"
            )
            marker_id = f"epoch_marker_{suite_id}_{entry['epoch_num']}"
            chained_nodes.append(
                {
                    "id": marker_id,
                    "type": "epochMarker",
                    "position": {"x": -400.0, "y": y_cursor},
                    "data": {
                        "label": (
                            f"Epoch {entry['epoch_num']} — {suite_meta['name']} — "
                            f"mean_loss={loss_str}"
                            + (f" — {delta_label}" if delta_label else "")
                        ),
                        "nodeType": "epochMarker",
                        "suite_id": suite_id,
                        "suite_name": suite_meta["name"],
                        "epoch_num": entry["epoch_num"],
                        "mean_loss": entry["mean_loss"],
                        "delta": delta_label,
                        "status": "complete",
                    },
                    "style": {"width": 1600, "height": marker_height},
                    "zIndex": -1,
                }
            )
            y_cursor += marker_height + 20.0
            prev_epoch_num = entry["epoch_num"]
            prev_child = entry["child_artifacts"] or entry["parent_artifacts"]

        # Resolve the per-run directory via the same mechanism as
        # /api/runs/{run_id}/graph, then build_graph + shift Y.
        run_row = await store.get_run(entry["run_id"])
        run_dir: Path | None = None
        if run_row:
            result = run_row.get("result") or {}
            metadata = result.get("metadata", {})
            explicit_run_dir = metadata.get("run_dir")
            workspace = metadata.get("workspace")
            loop_run_id = metadata.get("run_id")
            if explicit_run_dir and Path(explicit_run_dir).exists():
                run_dir = Path(explicit_run_dir)
            if run_dir is None and workspace and loop_run_id:
                candidate = Path(workspace) / "workspace" / "runs" / loop_run_id
                if candidate.exists():
                    run_dir = candidate
            if run_dir is None and workspace:
                run_dir = find_run_dir(Path(workspace))

        if run_dir is None:
            # Placeholder node so the suite graph still shows an entry even
            # if the run artifacts have been cleaned up.
            placeholder_id = f"missing_{entry['run_id']}"
            chained_nodes.append(
                {
                    "id": placeholder_id,
                    "type": "task",
                    "position": {"x": 0.0, "y": y_cursor},
                    "data": {
                        "label": f"{entry['task_name']} (artifacts missing)",
                        "nodeType": "task",
                        "status": "error",
                        "run_id": entry["run_id"],
                    },
                }
            )
            y_cursor += 200.0
            continue

        graph = build_graph(run_dir)
        prefix = f"e{entry['epoch_num']}_{entry['run_id']}_"
        for node in graph.nodes:
            data = dict(node.data)
            data["epoch_num"] = entry["epoch_num"]
            data["suite_id"] = suite_id
            data["source_run_id"] = entry["run_id"]
            chained_nodes.append(
                {
                    "id": prefix + node.id,
                    "type": node.type,
                    "position": {
                        "x": node.position.get("x", 0.0),
                        "y": node.position.get("y", 0.0) + y_cursor,
                    },
                    "data": data,
                    **(
                        {"parentNode": prefix + node.parentNode}
                        if node.parentNode
                        else {}
                    ),
                    **({"extent": node.extent} if node.extent else {}),
                    **({"style": node.style} if node.style else {}),
                    **(
                        {"zIndex": node.zIndex} if node.zIndex is not None else {}
                    ),
                }
            )
        for edge in graph.edges:
            chained_edges.append(
                {
                    "id": prefix + edge.id,
                    "source": prefix + edge.source,
                    "target": prefix + edge.target,
                    "type": edge.type,
                    "animated": edge.animated,
                    "style": edge.style,
                    "data": edge.data,
                }
            )
        y_cursor += run_block_height

    return {
        "nodes": chained_nodes,
        "edges": chained_edges,
        "stats": {
            "suite_id": suite_id,
            "suite_name": suite_meta["name"],
            "epoch_count": len({e["epoch_num"] for e in epoch_runs}),
            "run_count": len(epoch_runs),
        },
        "tool_registry": [],
        "skill_registry": [],
    }


def _format_artifact_delta(
    prev: dict[str, int], curr: dict[str, int]
) -> str:
    """Return a compact description of artifact-version changes.

    Example: ``"pitfalls v1→v2, rubric v0→v1"``. Empty string if no
    versions moved — used by the epoch marker label.
    """
    changes: list[str] = []
    for name, new_v in curr.items():
        old_v = prev.get(name, 0)
        if old_v != new_v:
            short = name.split(".")[-1].replace("_", " ")
            changes.append(f"{short} v{old_v}->v{new_v}")
    return ", ".join(changes[:4])


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


# ---------------------------------------------------------------------------
# Refinement Mode (y-axis optimization) — see docs/refinement.md
# ---------------------------------------------------------------------------


async def _resolve_seed_run_dir(store: Any, run_id: str) -> Path | None:
    """Locate the seed run's directory (containing run_completion.json + FINAL/)
    from a DB run_id. Mirrors the lookup strategy used by ``get_run_graph``.

    Returns None if no usable directory can be found. The caller is responsible
    for surfacing a 404.
    """
    from server.services.graph_builder import find_run_dir

    row = await store.get_run(run_id)
    if row is None:
        return None

    result = row.get("result") or {}
    metadata = result.get("metadata", {}) if isinstance(result, dict) else {}
    explicit_run_dir = metadata.get("run_dir")
    workspace = metadata.get("workspace")
    loop_run_id = metadata.get("run_id")

    candidates: list[Path] = []
    if explicit_run_dir:
        candidates.append(Path(explicit_run_dir))
    if workspace and loop_run_id:
        candidates.append(Path(workspace) / "workspace" / "runs" / loop_run_id)
    if workspace:
        rd = find_run_dir(Path(workspace))
        if rd:
            candidates.append(rd)

    config = row.get("config") or {}
    cfg_output = config.get("output_dir")
    if cfg_output:
        cfg_path = Path(cfg_output)
        if cfg_path.exists():
            rd = find_run_dir(cfg_path)
            if rd:
                candidates.append(rd)

    for c in candidates:
        if c.exists() and (c / "run_completion.json").exists():
            return c
    return None


@router.post("/experiments/{run_id}/refine", status_code=202)
async def start_refinement(run_id: str, body: dict[str, Any]) -> dict[str, Any]:
    """Kick off a refinement session against a completed run.

    Request body::

        {
          "iterations":   int [1..10],
          "model":        str | null,    # legacy single-model path
          "worker_model": str | null,    # legacy single-model path
          "tier_low":     {"manager": str, "worker": str} | null,
          "tier_mid":     {"manager": str, "worker": str} | null,
          "tier_high":    {"manager": str, "worker": str} | null
        }

    Tier handling (spec 2026-04-20 §10):

    * If any ``tier_*`` field is present in the body, build a ``TierPlan``
      with the user-supplied tiers and seed fallbacks (parsed from the
      seed ``run_completion.json``), and instantiate ``RefinementLoop``
      with ``tier_plan=plan`` (legacy ``model``/``worker_model`` ignored).
    * Mixed body (``model``/``worker_model`` AND any ``tier_*``): tier_*
      wins, legacy fields fully ignored, a warning is logged.
    * Else: legacy path unchanged — ``tier_plan=None``.

    Response (202)::

        {"session_id": "refine_<ts>", "status": "running"}

    Errors:
      * 404 — run_id not found in the experiment DB.
      * 409 — seed run has no FINAL/ or status not in {"complete", "partial"}.
      * 422 — ``iterations`` out of [1, 10].
    """
    from server.app import store

    iterations = int(body.get("iterations", 3))
    if iterations < 1 or iterations > 10:
        raise HTTPException(
            status_code=422,
            detail=f"iterations must be in [1, 10] (got {iterations})",
        )

    seed_dir = await _resolve_seed_run_dir(store, run_id)
    if seed_dir is None:
        raise HTTPException(
            status_code=404, detail=f"seed run not found: {run_id}"
        )
    if not (seed_dir / "FINAL").exists():
        raise HTTPException(
            status_code=409,
            detail=f"seed run has no FINAL/ deliverable: {seed_dir}",
        )

    row = await store.get_run(run_id)
    if row and row.get("status") not in {"complete", "partial", "completed"}:
        # Allow `partial` runs (the primary refinement target) and
        # `complete` runs (where the user explicitly wants more
        # inference compute); reject running/failed/aborted.
        raise HTTPException(
            status_code=409,
            detail=f"seed run status {row.get('status')!r} is not refinable",
        )

    # Import the loop lazily — keeps startup cheap and avoids pulling
    # the runtime into every UI server import.
    from awp.refinement.loop import RefinementLoop
    from awp.refinement.tiers import ModelPair, TierPlan

    legacy_model = body.get("model") or None
    legacy_worker_model = body.get("worker_model") or None

    # Tier detection — "present" means the key exists in the body, even
    # if its value is an empty dict. Per spec §10 / §12 last row, an
    # all-empty tier body still drives the tiered code path (tier_plan
    # non-None, resolves to seed pair for every iteration).
    tier_keys = ("tier_low", "tier_mid", "tier_high")
    has_any_tier = any(k in body for k in tier_keys)

    tier_plan: TierPlan | None = None
    if has_any_tier:
        if legacy_model or legacy_worker_model:
            # Spec §10: tier_* wins, legacy fields are ignored (not even
            # used as a baseline — seed's parsed model is the fallback).
            logger.warning(
                "refinement.mixed_body: tier_* set; ignoring legacy "
                "model/worker_model"
            )

        seed_manager, seed_worker = _parse_seed_models(seed_dir)

        def _pair(key: str) -> ModelPair:
            raw = body.get(key) or {}
            if not isinstance(raw, dict):
                return ModelPair()
            # Treat empty strings and None identically.
            return ModelPair(
                manager=(raw.get("manager") or None),
                worker=(raw.get("worker") or None),
            )

        tier_plan = TierPlan(
            low=_pair("tier_low"),
            mid=_pair("tier_mid"),
            high=_pair("tier_high"),
            seed_manager=seed_manager,
            seed_worker=seed_worker,
        )

    if tier_plan is not None:
        loop = RefinementLoop(
            seed_run_dir=seed_dir,
            model=None,
            worker_model=None,
            tier_plan=tier_plan,
        )
    else:
        loop = RefinementLoop(
            seed_run_dir=seed_dir,
            model=legacy_model,
            worker_model=legacy_worker_model,
            tier_plan=None,
        )
    # Generate a session_id up-front so the client can correlate the
    # background run with its sidecar once it lands.
    from awp.refinement.loop import _new_session_id

    session_id = _new_session_id()

    import threading

    def _worker() -> None:
        try:
            loop.run(iterations=iterations)
        except Exception as exc:  # noqa: BLE001
            logger.warning("refinement session %s failed: %s", session_id, exc)

    threading.Thread(target=_worker, daemon=True).start()

    return {"session_id": session_id, "status": "running"}


def _parse_seed_models(seed_dir: Path) -> tuple[str | None, str | None]:
    """Extract the seed run's manager/worker model strings for tier fallback.

    Reads ``<seed>/run_completion.json`` and looks for the models under
    any of the shapes the runtime or synthetic fixtures use:

    * ``models.manager`` / ``models.worker``         (runtime shape)
    * ``model`` / ``worker_model``                    (flat shape)
    * ``config.model`` / ``config.worker_model``      (UI-init shape)

    Returns ``(None, None)`` if the file is missing, unreadable, or
    carries no recognizable model keys — the loop then falls through to
    ``AgentWorkflow``'s default (matches today's empty-model semantics).
    """
    import json as _json

    rc = seed_dir / "run_completion.json"
    if not rc.exists():
        return None, None
    try:
        data = _json.loads(rc.read_text(encoding="utf-8"))
    except (OSError, _json.JSONDecodeError):
        return None, None
    if not isinstance(data, dict):
        return None, None

    models = data.get("models") if isinstance(data.get("models"), dict) else {}
    config = data.get("config") if isinstance(data.get("config"), dict) else {}

    manager = (
        models.get("manager")
        or data.get("model")
        or config.get("model")
        or None
    )
    worker = (
        models.get("worker")
        or data.get("worker_model")
        or config.get("worker_model")
        or None
    )
    return (str(manager) if manager else None, str(worker) if worker else None)


@router.get("/experiments/{run_id}/refinement_sessions")
async def get_refinement_sessions(run_id: str) -> dict[str, Any]:
    """Return all refinement sessions and the current BEST pointer for a seed run.

    Response::

        {
          "sessions": [<session JSON from refinement_sessions/*.json>, ...],
          "best":     <BEST/manifest.json> | null
        }

    Errors:
      * 404 — run_id not found.
    """
    from server.app import store

    seed_dir = await _resolve_seed_run_dir(store, run_id)
    if seed_dir is None:
        raise HTTPException(
            status_code=404, detail=f"seed run not found: {run_id}"
        )

    import json as _json

    sessions_dir = seed_dir / "refinement_sessions"
    sessions: list[dict[str, Any]] = []
    if sessions_dir.exists():
        for path in sorted(sessions_dir.glob("*.json")):
            try:
                sessions.append(_json.loads(path.read_text(encoding="utf-8")))
            except (OSError, _json.JSONDecodeError) as exc:
                logger.warning("skipping unreadable session sidecar %s: %s", path, exc)

    best: dict[str, Any] | None = None
    best_manifest = seed_dir / "BEST" / "manifest.json"
    if best_manifest.exists():
        try:
            best = _json.loads(best_manifest.read_text(encoding="utf-8"))
        except (OSError, _json.JSONDecodeError) as exc:
            logger.warning("unreadable BEST manifest %s: %s", best_manifest, exc)

    return {"sessions": sessions, "best": best}
