"""
Built-in MCP Tool: web.search

DuckDuckGo-based web search implementation.
Auto-generated for tool implementation mode.
"""

from __future__ import annotations

from typing import Any, Dict


class FastMCP:
    """AWP-compatible tool registry stub."""

    def __init__(self, name: str) -> None:
        self.name = name

    def tool(self, _name: str, *, secrets: list[str] | None = None):
        def _decorator(fn):
            fn._awp_secrets = secrets or []
            return fn

        return _decorator


app = FastMCP("web")


@app.tool("web.search")
def search(
    *, query: str, max_results: int = 10, language: str = "en", _secrets: dict = {},
) -> Dict[str, Any]:
    """Search the web for information using DuckDuckGo.

    Args:
        query: Search query (1-500 chars).
        max_results: Maximum results to return (1-100).
        language: Language filter (ISO 639-1).
        _secrets: Injected by AWP runtime.

    Returns:
        Standardized AWP tool result with search results.
    """
    try:
        import urllib.request
        import urllib.parse
        import json

        params = urllib.parse.urlencode({
            "q": query,
            "format": "json",
            "no_redirect": 1,
            "no_html": 1,
        })
        url = f"https://api.duckduckgo.com/?{params}"

        req = urllib.request.Request(url, headers={"User-Agent": "AWP/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())

        results = []
        for item in (data.get("RelatedTopics", []) or [])[:max_results]:
            if isinstance(item, dict) and "Text" in item:
                results.append({
                    "title": item.get("Text", "")[:100],
                    "url": item.get("FirstURL", ""),
                    "snippet": item.get("Text", ""),
                })

        return {
            "ok": True,
            "status": 200,
            "data": {
                "query": query,
                "results": results,
                "total": len(results),
            },
            "error": None,
        }
    except Exception as e:
        return {
            "ok": False,
            "status": 500,
            "data": {},
            "error": str(e),
        }
