"""
Built-in MCP Tool: http.request

HTTP request implementation using urllib.
Auto-generated for tool implementation mode.
"""

from __future__ import annotations

from typing import Any, Dict


class FastMCP:
    def __init__(self, name: str) -> None:
        self.name = name

    def tool(self, _name: str, *, secrets: list[str] | None = None):
        def _decorator(fn):
            fn._awp_secrets = secrets or []
            return fn
        return _decorator


app = FastMCP("http")


@app.tool("http.request")
def request(
    *,
    url: str,
    method: str = "GET",
    headers: dict = {},
    body: str = None,
    timeout: int = 30,
    _secrets: dict = {},
) -> Dict[str, Any]:
    """Make an arbitrary HTTP request.

    Args:
        url: Target URL.
        method: HTTP method (GET, POST, PUT, DELETE, PATCH).
        headers: HTTP headers as key-value pairs.
        body: Request body (for POST/PUT/PATCH).
        timeout: Timeout in seconds.
        _secrets: Injected by AWP runtime.
    """
    try:
        import urllib.request
        import json

        data = body.encode("utf-8") if body else None
        req = urllib.request.Request(url, data=data, headers=headers, method=method)

        with urllib.request.urlopen(req, timeout=timeout) as resp:
            content = resp.read().decode("utf-8", errors="replace")
            status = resp.status

        return {
            "ok": 200 <= status < 400,
            "status": status,
            "data": {"body": content[:50000], "status_code": status},
            "error": None,
        }
    except Exception as e:
        return {"ok": False, "status": 500, "data": {}, "error": str(e)}
