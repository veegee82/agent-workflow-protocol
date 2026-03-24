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

Secrets:
  Tools can declare API keys they need via secrets=["KEY"] in the decorator.
  The AWP runtime injects them as a _secrets dict at call time — the LLM never
  sees these values. Declare keys in secrets.yaml at the workflow root.
"""

from __future__ import annotations

from typing import Any, Dict

try:
    from mcp.server.fastmcp import FastMCP as _BaseFastMCP

    class FastMCP(_BaseFastMCP):  # type: ignore[no-redef]
        """Wrapper that adds AWP secrets support to the real FastMCP."""

        def tool(self, _name: str, *, secrets: list[str] | None = None, **kwargs):  # type: ignore[override]
            base_decorator = super().tool(_name, **kwargs)

            def _decorator(fn):
                fn._awp_secrets = secrets or []
                return base_decorator(fn)

            return _decorator

except Exception:

    class FastMCP:  # type: ignore[no-redef]
        """Minimal stub so the file can be parsed without the MCP package."""

        def __init__(self, name: str) -> None:
            self.name = name

        def tool(self, _name: str, *, secrets: list[str] | None = None):  # type: ignore[override]
            def _decorator(fn):  # type: ignore[override]
                fn._awp_secrets = secrets or []
                return fn

            return _decorator


app = FastMCP("{{TOOL_NAMESPACE}}")


@app.tool("{{TOOL_NAMESPACE}}.{{TOOL_ACTION}}", secrets=["{{SECRET_KEY}}"])
def tool_handler(
    *, param_name: str, param_count: int = 10, _secrets: dict = {},
) -> Dict[str, Any]:
    """{{TOOL_DESCRIPTION}}

    Args:
        param_name: Description of the parameter.
        param_count: Number of items to process.
        _secrets: Injected by AWP runtime. Never passed by the LLM.

    Returns:
        Standardized AWP tool result dict.
    """
    try:
        # Access injected API key (never visible to the LLM)
        api_key = _secrets.get("{{SECRET_KEY}}", "")

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
