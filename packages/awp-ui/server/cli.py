"""CLI entry point for the AWP UI server."""

from __future__ import annotations

import argparse
import logging
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


def main() -> None:
    """Launch the AWP UI server via uvicorn."""
    parser = argparse.ArgumentParser(
        prog="awp-ui",
        description="Start the AWP UI server (FastAPI + WebSocket)",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Bind address (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8420,
        help="Port number (default: 8420)",
    )
    parser.add_argument(
        "--dev",
        action="store_true",
        help="Development mode: enable auto-reload and start Vite dev server",
    )
    parser.add_argument(
        "--log-level",
        default="info",
        choices=["debug", "info", "warning", "error"],
        help="Log level (default: info)",
    )
    args = parser.parse_args()

    log_level = args.log_level.upper()
    logging.basicConfig(
        level=getattr(logging, log_level),
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )

    vite_proc: subprocess.Popen[bytes] | None = None

    if args.dev:
        # Start Vite dev server as a subprocess (if frontend/ exists)
        frontend_dir = Path(__file__).resolve().parent.parent / "frontend"
        if frontend_dir.is_dir() and (frontend_dir / "package.json").exists():
            logger.info("Starting Vite dev server in %s", frontend_dir)
            try:
                vite_proc = subprocess.Popen(
                    ["npm", "run", "dev"],
                    cwd=str(frontend_dir),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                )
            except FileNotFoundError:
                logger.warning(
                    "npm not found; skipping Vite dev server. "
                    "Install Node.js to enable frontend hot-reload."
                )

    try:
        import uvicorn

        uvicorn.run(
            "server.app:create_app",
            factory=True,
            host=args.host,
            port=args.port,
            reload=args.dev,
            log_level=args.log_level,
        )
    except KeyboardInterrupt:
        logger.info("Shutting down AWP UI server")
    finally:
        if vite_proc is not None:
            logger.info("Terminating Vite dev server")
            vite_proc.terminate()
            try:
                vite_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                vite_proc.kill()


if __name__ == "__main__":
    main()
