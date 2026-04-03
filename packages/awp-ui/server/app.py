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
        try:
            async for event in event_bus.subscribe(run_id):
                payload = event.model_dump(mode="json")
                await websocket.send_text(json.dumps(payload, default=str))
        except WebSocketDisconnect:
            logger.info("WebSocket client disconnected for run %s", run_id)
        except Exception:
            logger.exception("WebSocket error for run %s", run_id)
        finally:
            logger.debug("WebSocket handler exiting for run %s", run_id)

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
