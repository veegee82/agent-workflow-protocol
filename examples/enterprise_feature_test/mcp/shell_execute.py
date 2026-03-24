"""
Built-in MCP Tool: shell.execute

Sandboxed shell command execution.
Auto-generated for tool implementation mode.
"""

from __future__ import annotations

import subprocess
from typing import Any, Dict


class FastMCP:
    def __init__(self, name: str) -> None:
        self.name = name

    def tool(self, _name: str, *, secrets: list[str] | None = None):
        def _decorator(fn):
            fn._awp_secrets = secrets or []
            return fn
        return _decorator


app = FastMCP("shell")


@app.tool("shell.execute")
def execute(
    *, command: str, timeout: int = 30, cwd: str = None, _secrets: dict = {},
) -> Dict[str, Any]:
    """Execute a shell command in a sandboxed environment.

    Args:
        command: Command to execute.
        timeout: Timeout in seconds.
        cwd: Working directory.
    """
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
        )

        return {
            "ok": result.returncode == 0,
            "status": 200 if result.returncode == 0 else 500,
            "data": {
                "stdout": result.stdout[:50000],
                "stderr": result.stderr[:10000],
                "returncode": result.returncode,
            },
            "error": result.stderr[:500] if result.returncode != 0 else None,
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "status": 408, "data": {}, "error": f"Command timed out after {timeout}s"}
    except Exception as e:
        return {"ok": False, "status": 500, "data": {}, "error": str(e)}
