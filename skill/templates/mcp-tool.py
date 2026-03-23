"""
Custom MCP Tool: {{TOOL_NAMESPACE}}.{{TOOL_ACTION}}

Place this file in {workflow_dir}/mcp/ for automatic discovery.
The tool is registered as "{{TOOL_NAMESPACE}}.{{TOOL_ACTION}}" and
automatically added to every agent's allowed tools in this project.

Return format: {"ok": bool, "status": int, "data": {...}, "error": str | None}

Rules:
  CT1: Filename must NOT start with underscore
  CT2: Namespace must NOT collide with reserved (web, http, file, shell, agent, memory, arithmetic, ...)
  CT3: Tool name comes from @app.tool("ns.action") decorator, NOT from the function name
  CT4: Return MUST follow {"ok": bool, "status": int, "data": Any, "error": str|None} format
  CT5: File MUST contain FastMCP stub fallback (try/except block below)
  CT6: All parameters MUST have type annotations
  CT7: File MUST contain app = FastMCP("namespace") object
"""

from __future__ import annotations

from typing import Any, Dict

try:
    from mcp.server.fastmcp import FastMCP
except Exception:

    class FastMCP:  # type: ignore[no-redef]
        """Minimal stub so the file can be parsed without the MCP package."""

        def __init__(self, name: str) -> None:
            self.name = name

        def tool(self, _name: str):  # type: ignore[override]
            def _decorator(fn):  # type: ignore[override]
                return fn

            return _decorator


app = FastMCP("{{TOOL_NAMESPACE}}")


@app.tool("{{TOOL_NAMESPACE}}.{{TOOL_ACTION}}")
def tool_handler(*, param_name: str, param_count: int = 10) -> Dict[str, Any]:
    """{{TOOL_DESCRIPTION}}

    Args:
        param_name: Description of the parameter.
        param_count: Number of items to process.

    Returns:
        Standardized AWP tool result dict.
    """
    try:
        # --- Implement tool logic here ---
        result = {"output": param_name, "count": param_count}

        return {
            "ok": True,
            "status": 200,
            "data": result,
            "error": None,
        }
    except Exception as e:
        return {
            "ok": False,
            "status": 500,
            "data": {},
            "error": str(e),
        }
