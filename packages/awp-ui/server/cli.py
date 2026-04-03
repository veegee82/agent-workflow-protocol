"""CLI entry point for the AWP UI server.

Can be invoked as:
    awp-ui              # standalone command (pip install awp-ui)
    awp studio          # via awp CLI (pip install awp-core awp-ui)
    python -m server    # direct module execution
"""

from __future__ import annotations

import argparse
import logging
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path

logger = logging.getLogger(__name__)

# Ensure the server package is importable regardless of how we're invoked.
_PACKAGE_ROOT = Path(__file__).resolve().parent.parent
if str(_PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(_PACKAGE_ROOT))


def main() -> None:
    """Launch the AWP Workflow Studio."""
    parser = argparse.ArgumentParser(
        prog="awp-ui",
        description="AWP Workflow Studio — browser-based agent workflow UI",
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
        "--no-open",
        action="store_true",
        help="Do not open browser automatically",
    )
    parser.add_argument(
        "--no-update",
        action="store_true",
        help="Skip automatic PyPI update check",
    )
    parser.add_argument(
        "--base-dir",
        default=None,
        help="Default base directory for experiment data storage",
    )
    parser.add_argument(
        "--log-level",
        default="info",
        choices=["debug", "info", "warning", "error"],
        help="Log level (default: info)",
    )
    args = parser.parse_args()

    # --- Pre-flight: auto-update from PyPI ---
    if not args.no_update and not args.dev:
        print("  Checking for updates...")
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pip", "install", "--upgrade", "awp-agents"],
                capture_output=True, text=True, timeout=60,
            )
            output = result.stdout + result.stderr
            if "Successfully installed" in output:
                import re
                pkgs = re.findall(r"awp[_-]\S+", output)
                print(f"  Updated: {', '.join(pkgs) if pkgs else 'awp-agents'}")
            else:
                print("  Already up to date.")
        except Exception as exc:
            print(f"  Update check failed ({exc}), continuing with current version.")

    log_level = args.log_level.upper()
    logging.basicConfig(
        level=getattr(logging, log_level),
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )

    host = args.host
    port = args.port
    url = f"http://{host}:{port}" if host != "0.0.0.0" else f"http://localhost:{port}"

    # Store base_dir for the app to pick up
    if args.base_dir:
        import os
        os.environ["AWP_BASE_DIR"] = args.base_dir

    # Resolve version dynamically
    try:
        from importlib.metadata import version as _pkg_version
        _version = _pkg_version("awp-agents")
    except Exception:
        _version = "dev"

    print(f"\n  AWP Workflow Studio v{_version}")
    print(f"  {'─' * 40}")
    print(f"  URL:      {url}")
    print(f"  Mode:     {'development' if args.dev else 'production'}")
    if args.base_dir:
        print(f"  Base Dir: {args.base_dir}")
    print(f"  {'─' * 40}")
    print(f"  Press Ctrl+C to stop\n")

    vite_proc: subprocess.Popen[bytes] | None = None

    if args.dev:
        frontend_dir = _PACKAGE_ROOT / "frontend"
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

    # Auto-open browser
    if not args.no_open:

        def _open_browser() -> None:
            import time

            time.sleep(1.5)
            webbrowser.open(url)

        t = threading.Thread(target=_open_browser, daemon=True)
        t.start()

    try:
        import uvicorn

        uvicorn.run(
            "server.app:create_app",
            factory=True,
            host=host,
            port=port,
            reload=args.dev,
            log_level=args.log_level,
        )
    except KeyboardInterrupt:
        print("\n  Shutting down AWP Workflow Studio")
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
