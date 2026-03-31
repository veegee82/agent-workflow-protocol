#!/usr/bin/env python3
"""Launch AWP Workflow Studio, ensuring the port is free first."""

from __future__ import annotations

import signal
import socket
import sys

DEFAULT_PORT = 8420


def _kill_port(port: int) -> None:
    """Kill any process listening on *port* (Linux/macOS)."""
    import subprocess

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
                    import os

                    os.kill(int(pid), signal.SIGTERM)
                except ProcessLookupError:
                    pass
        if pids:
            import time

            time.sleep(0.5)
    except FileNotFoundError:
        # lsof not available, fall back to socket check
        pass


def _port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def main() -> None:
    port = DEFAULT_PORT

    # Parse --port from argv if given
    if "--port" in sys.argv:
        idx = sys.argv.index("--port")
        if idx + 1 < len(sys.argv) and sys.argv[idx + 1].isdigit():
            port = int(sys.argv[idx + 1])

    # Free the port
    if _port_in_use(port):
        print(f"  Port {port} is in use — freeing it...")
        _kill_port(port)
        if _port_in_use(port):
            print(f"  ERROR: Could not free port {port}. Stop the process manually.")
            sys.exit(1)
        print(f"  Port {port} is now free.")

    # Launch studio
    from server.cli import main as studio_main

    studio_main()


if __name__ == "__main__":
    main()
