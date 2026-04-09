"""FastAPI application for AWP UI — WebSocket streaming + REST API."""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from server import __version__
from server.event_bus import event_bus
from server.services.store import StoreService

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Shared service instances
# ---------------------------------------------------------------------------

store = StoreService()

# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Startup / shutdown lifecycle."""
    # Bind the event bus to the current event loop
    event_bus.bind_loop(asyncio.get_running_loop())

    # Initialise the SQLite database
    await store.init_db()

    # Reap runs left in 'running' state by a previous (crashed/reloaded)
    # process so the sidebar doesn't show a permanently pulsing blue dot
    # for experiments whose threads no longer exist.  Runs owned by a
    # live external process (E2E harness) are kept as 'running'.
    await store.cleanup_orphan_runs()
    # Reconcile session status from their linked runs — catches sessions
    # stuck on 'running' after an unclean shutdown.
    await store.reconcile_session_status()

    # Load persisted settings into the in-memory defaults
    persisted_settings = await store.get_settings()
    if persisted_settings:
        from server.api.routes import _default_settings

        _default_settings.update(persisted_settings)
        logger.info("Loaded persisted settings from database")

    # Apply --base-dir from CLI if set via env var
    import os
    cli_base_dir = os.environ.get("AWP_BASE_DIR")
    if cli_base_dir:
        from server.api.routes import _default_settings

        _default_settings["base_dir"] = cli_base_dir
        await store.save_settings(dict(_default_settings))
        logger.info("Set base_dir from CLI: %s", cli_base_dir)

    # Auto-import API keys from environment variables into the secrets store
    # so users who already have keys set in their shell can use them immediately
    _AUTO_IMPORT_KEYS = [
        "OPENROUTER_API_KEY",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "LLM_API_KEY",
    ]
    for env_key in _AUTO_IMPORT_KEYS:
        env_val = os.environ.get(env_key, "")
        if env_val:
            existing = await store.get_secret(env_key)
            if not existing:
                await store.save_secret(env_key, env_val)
                logger.info("Auto-imported %s from environment", env_key)

    logger.info("AWP UI server started")
    yield
    await store.close()
    logger.info("AWP UI server stopped")


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

def _find_frontend_dist() -> Path:
    """Locate the built frontend dist directory."""
    base = Path(__file__).resolve().parent
    # PyPI install: dist is inside the server package
    candidate = base / "frontend" / "dist"
    if (candidate / "index.html").is_file():
        return candidate
    # Dev layout (packages/awp-ui): dist is a sibling of server/
    candidate = base.parent / "frontend" / "dist"
    if (candidate / "index.html").is_file():
        return candidate
    return base / "frontend" / "dist"  # fallback path for error messages


_FRONTEND_DIST = _find_frontend_dist()


def create_app() -> FastAPI:
    """Build and configure the FastAPI application."""
    app = FastAPI(
        title="AWP UI",
        description="Agent Workflow Protocol — Web UI backend with real-time WebSocket streaming",
        version=__version__,
        lifespan=lifespan,
    )

    # CORS — allow localhost dev origins
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:3000",
            "http://localhost:5173",
            "http://localhost:8420",
            "http://127.0.0.1:3000",
            "http://127.0.0.1:5173",
            "http://127.0.0.1:8420",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ------------------------------------------------------------------
    # Health check
    # ------------------------------------------------------------------

    @app.get("/api/health")
    async def health_check() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    # ------------------------------------------------------------------
    # REST API routes
    # ------------------------------------------------------------------

    from server.api.routes import router as api_router  # noqa: E402

    app.include_router(api_router, prefix="/api")

    # ------------------------------------------------------------------
    # WebSocket endpoint
    # ------------------------------------------------------------------

    @app.websocket("/ws/{run_id}")
    async def ws_run(websocket: WebSocket, run_id: str) -> None:
        await websocket.accept()
        logger.info("WebSocket client connected for run %s", run_id)

        # Determine if this is a server-managed run (in-process event bus)
        # or an external run (E2E harness — events only in DB).
        from server.services.runner_service import _active_runs, _active_lock

        with _active_lock:
            is_local = run_id in _active_runs

        if is_local:
            # Server-started run: stream from the in-process event bus
            try:
                async for event in event_bus.subscribe(run_id):
                    payload = event.model_dump(mode="json")
                    await websocket.send_text(json.dumps(payload, default=str))
            except WebSocketDisconnect:
                logger.info("WebSocket client disconnected for run %s", run_id)
            except Exception:
                logger.exception("WebSocket error for run %s", run_id)
        else:
            # External run (E2E test in another process): poll the DB
            # for new events and stream them to the client.
            logger.info(
                "Run %s is external — polling DB for live events", run_id
            )
            try:
                await _poll_db_events(websocket, run_id)
            except WebSocketDisconnect:
                logger.info("WebSocket client disconnected for run %s", run_id)
            except Exception:
                logger.exception("WebSocket error for run %s", run_id)
        logger.debug("WebSocket handler exiting for run %s", run_id)

    async def _poll_db_events(
        websocket: WebSocket, run_id: str, poll_interval: float = 0.5
    ) -> None:
        """Poll the events table for an external run and stream to WebSocket.

        Sends all existing events first (replay), then polls for new ones
        every *poll_interval* seconds until the run leaves 'running' status.
        """
        from server.models import EventType

        last_seq = 0
        terminal = False

        while not terminal:
            events = await store.get_events(run_id, since_seq=last_seq)
            for evt in events:
                if evt["seq"] <= last_seq:
                    continue
                last_seq = evt["seq"]
                # Build a payload compatible with RunEvent.model_dump()
                payload = {
                    "run_id": run_id,
                    "seq": evt["seq"],
                    "type": evt["type"],
                    "data": evt["data"],
                    "timestamp": evt["timestamp"],
                }
                await websocket.send_text(json.dumps(payload, default=str))

                # Check for terminal events
                if evt["type"] in ("run.complete", "error"):
                    terminal = True
                    break

            if terminal:
                break

            # Also check if the run status changed to a terminal state
            # (in case run_completion.json was never written but the harness
            # finalized the run in the DB)
            run = await store.get_run(run_id)
            if run and run["status"] not in ("running", "pending"):
                # Send a synthetic run.complete so the frontend transitions
                if not any(
                    e["type"] == "run.complete"
                    for e in await store.get_events(run_id, since_seq=last_seq)
                ):
                    payload = {
                        "run_id": run_id,
                        "seq": last_seq + 1,
                        "type": "run.complete",
                        "data": {
                            "status": run["status"],
                            "result": run.get("result"),
                        },
                        "timestamp": run.get("completed_at", ""),
                    }
                    await websocket.send_text(json.dumps(payload, default=str))
                terminal = True
                break

            await asyncio.sleep(poll_interval)

    # ------------------------------------------------------------------
    # Static file serving (production SPA)
    # ------------------------------------------------------------------

    if _FRONTEND_DIST.is_dir():
        # Serve static assets (js, css, images, etc.)
        app.mount(
            "/assets",
            StaticFiles(directory=str(_FRONTEND_DIST / "assets"), check_dir=False),
            name="assets",
        )

        # SPA catch-all: serve index.html for any non-API, non-WS route
        @app.get("/{full_path:path}")
        async def serve_spa(full_path: str) -> FileResponse:
            # If the exact file exists in dist/, serve it (favicon, etc.)
            candidate = _FRONTEND_DIST / full_path
            if full_path and candidate.is_file():
                return FileResponse(str(candidate))
            # Otherwise serve index.html for client-side routing
            index = _FRONTEND_DIST / "index.html"
            if index.is_file():
                return FileResponse(str(index))
            return JSONResponse({"error": "Frontend not built"}, status_code=404)

    return app
