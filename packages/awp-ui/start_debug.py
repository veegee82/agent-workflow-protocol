#!/usr/bin/env python3
"""Launch AWP Workflow Studio from local source (no PyPI install needed).

Rebuilds the frontend, wires up local awp-core and awp-runtime packages,
and starts the server with auto-reload — useful for testing changes without
publishing.

Every launch guarantees:
- Frontend is rebuilt (unless --skip-build)
- All Python modules are loaded fresh from local source
- Any running server on the port is killed first
- uvicorn watches source dirs for changes and auto-reloads
"""

from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

DEFAULT_PORT = 8420

# ---------------------------------------------------------------------------
# Resolve local package paths relative to this file
# ---------------------------------------------------------------------------

_THIS_DIR = Path(__file__).resolve().parent                 # packages/awp-ui/
_PACKAGES_DIR = _THIS_DIR.parent                            # packages/
_REPO_ROOT = _PACKAGES_DIR.parent                           # repo root

_AWP_CORE_SRC = _PACKAGES_DIR / "awp-core" / "src"
_AWP_RUNTIME_SRC = _PACKAGES_DIR / "awp-runtime" / "src"
_AWP_UI_DIR = _THIS_DIR                                     # packages/awp-ui/
_FRONTEND_DIR = _THIS_DIR / "frontend"


def _kill_port(port: int) -> None:
    """Kill any process listening on *port* (Linux/macOS)."""
    try:
        result = subprocess.run(
            ["lsof", "-ti", f":{port}"],
            capture_output=True,
            text=True,
        )
        pids = result.stdout.strip().split()
        for pid in pids:
            if pid.isdigit():
                try:
                    os.kill(int(pid), signal.SIGTERM)
                except ProcessLookupError:
                    pass
        if pids:
            time.sleep(0.5)
            # Force-kill any survivors
            for pid in pids:
                if pid.isdigit():
                    try:
                        os.kill(int(pid), signal.SIGKILL)
                    except (ProcessLookupError, PermissionError):
                        pass
            time.sleep(0.3)
    except FileNotFoundError:
        pass


def _port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def _build_frontend() -> None:
    """Run `npm run build` in the frontend directory."""
    if not (_FRONTEND_DIR / "package.json").exists():
        print("  WARNING: frontend/package.json not found, skipping build")
        return

    print("  Building frontend...")
    result = subprocess.run(
        ["npm", "run", "build"],
        cwd=str(_FRONTEND_DIR),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"  Frontend build failed:\n{result.stderr}")
        sys.exit(1)
    print("  Frontend built successfully.")


def _flush_awp_modules() -> None:
    """Remove all cached awp.* and server.* modules so fresh source is loaded."""
    stale = [
        name for name in sys.modules
        if name.startswith("awp") or name.startswith("server")
    ]
    for name in stale:
        del sys.modules[name]


def main() -> None:
    port = DEFAULT_PORT

    # Parse --port from argv if given
    if "--port" in sys.argv:
        idx = sys.argv.index("--port")
        if idx + 1 < len(sys.argv) and sys.argv[idx + 1].isdigit():
            port = int(sys.argv[idx + 1])

    skip_build = "--skip-build" in sys.argv

    # Free the port — kill ANY existing server
    if _port_in_use(port):
        print(f"  Port {port} is in use — killing existing server...")
        _kill_port(port)
        # Wait and verify
        for _ in range(10):
            if not _port_in_use(port):
                break
            time.sleep(0.3)
        if _port_in_use(port):
            print(f"  ERROR: Could not free port {port}. Stop the process manually.")
            sys.exit(1)
        print(f"  Port {port} is now free.")

    # Build frontend (unless --skip-build)
    if not skip_build:
        _build_frontend()

    # Wire up local source packages so they take priority over installed ones
    for src_path in [str(_AWP_CORE_SRC), str(_AWP_RUNTIME_SRC), str(_AWP_UI_DIR)]:
        if src_path not in sys.path:
            sys.path.insert(0, src_path)

    # Flush any previously imported awp/server modules to guarantee fresh code
    _flush_awp_modules()

    print(f"\n  AWP Workflow Studio (DEBUG / local source)")
    print(f"  {'─' * 40}")
    print(f"  awp-core:    {_AWP_CORE_SRC}")
    print(f"  awp-runtime: {_AWP_RUNTIME_SRC}")
    print(f"  awp-ui:      {_AWP_UI_DIR}")
    print(f"  frontend:    {_FRONTEND_DIR / 'dist'}")
    print(f"  URL:         http://127.0.0.1:{port}")
    print(f"  Auto-reload: ON (watching source dirs)")
    print(f"  {'─' * 40}\n")

    # Launch uvicorn directly with reload enabled, watching all source dirs.
    # This ensures every code change is picked up without restarting.
    import uvicorn

    uvicorn.run(
        "server.app:create_app",
        factory=True,
        host="127.0.0.1",
        port=port,
        reload=True,
        reload_dirs=[
            str(_AWP_CORE_SRC),
            str(_AWP_RUNTIME_SRC),
            str(_AWP_UI_DIR / "server"),
        ],
        log_level="info",
    )


if __name__ == "__main__":
    main()
