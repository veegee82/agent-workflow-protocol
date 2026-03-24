"""
Built-in MCP Tools: memory.write, memory.read, memory.search, memory.curate

File-based memory implementation.
Auto-generated for tool implementation mode.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict


class FastMCP:
    def __init__(self, name: str) -> None:
        self.name = name

    def tool(self, _name: str, *, secrets: list[str] | None = None):
        def _decorator(fn):
            fn._awp_secrets = secrets or []
            return fn
        return _decorator


app = FastMCP("memory")

_MEMORY_DIR = Path(".memory")
_LONG_TERM = _MEMORY_DIR / "MEMORY.md"
_DAILY_DIR = _MEMORY_DIR / "daily"


def _ensure_dirs():
    _MEMORY_DIR.mkdir(exist_ok=True)
    _DAILY_DIR.mkdir(exist_ok=True)
    if not _LONG_TERM.exists():
        _LONG_TERM.write_text("# Long-Term Memory\n\n", encoding="utf-8")


@app.tool("memory.write")
def write(
    *, content: str, target: str = "daily", _secrets: dict = {},
) -> Dict[str, Any]:
    """Write to daily log or long-term memory.

    Args:
        content: Content to write.
        target: 'daily' or 'long_term'.
    """
    try:
        _ensure_dirs()
        now = datetime.now(timezone.utc)

        if target == "long_term":
            with open(_LONG_TERM, "a", encoding="utf-8") as f:
                f.write(f"\n## {now.isoformat()}\n\n{content}\n")
            path = str(_LONG_TERM)
        else:
            daily_file = _DAILY_DIR / f"{now.strftime('%Y-%m-%d')}.md"
            with open(daily_file, "a", encoding="utf-8") as f:
                f.write(f"\n### {now.strftime('%H:%M:%S')}\n\n{content}\n")
            path = str(daily_file)

        return {
            "ok": True,
            "status": 200,
            "data": {"path": path, "target": target, "timestamp": now.isoformat()},
            "error": None,
        }
    except Exception as e:
        return {"ok": False, "status": 500, "data": {}, "error": str(e)}


@app.tool("memory.read")
def read(
    *, target: str = "long_term", date: str = None, _secrets: dict = {},
) -> Dict[str, Any]:
    """Read MEMORY.md, daily log, or list available dates.

    Args:
        target: 'long_term', 'daily', or 'dates'.
        date: Specific date for daily log (YYYY-MM-DD).
    """
    try:
        _ensure_dirs()

        if target == "dates":
            dates = sorted([f.stem for f in _DAILY_DIR.glob("*.md")])
            return {
                "ok": True,
                "status": 200,
                "data": {"dates": dates, "count": len(dates)},
                "error": None,
            }
        elif target == "daily":
            if not date:
                date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            daily_file = _DAILY_DIR / f"{date}.md"
            if not daily_file.exists():
                return {"ok": False, "status": 404, "data": {}, "error": f"No daily log for {date}"}
            content = daily_file.read_text(encoding="utf-8")
        else:
            content = _LONG_TERM.read_text(encoding="utf-8")

        return {
            "ok": True,
            "status": 200,
            "data": {"content": content, "target": target},
            "error": None,
        }
    except Exception as e:
        return {"ok": False, "status": 500, "data": {}, "error": str(e)}


@app.tool("memory.search")
def search(
    *, query: str, max_results: int = 10, date_range: str = None, _secrets: dict = {},
) -> Dict[str, Any]:
    """Keyword search across all memory files.

    Args:
        query: Search query.
        max_results: Maximum results.
        date_range: Optional date filter (e.g., "2026-03-01:2026-03-24").
    """
    try:
        _ensure_dirs()
        results = []
        query_lower = query.lower()

        # Search long-term memory
        if _LONG_TERM.exists():
            content = _LONG_TERM.read_text(encoding="utf-8")
            for i, line in enumerate(content.split("\n")):
                if query_lower in line.lower():
                    results.append({"source": "long_term", "line": i + 1, "text": line.strip()})

        # Search daily logs
        for daily_file in sorted(_DAILY_DIR.glob("*.md")):
            if date_range:
                parts = date_range.split(":")
                if len(parts) == 2:
                    if daily_file.stem < parts[0] or daily_file.stem > parts[1]:
                        continue

            content = daily_file.read_text(encoding="utf-8")
            for i, line in enumerate(content.split("\n")):
                if query_lower in line.lower():
                    results.append({
                        "source": f"daily/{daily_file.stem}",
                        "line": i + 1,
                        "text": line.strip(),
                    })

        return {
            "ok": True,
            "status": 200,
            "data": {"results": results[:max_results], "total": len(results), "query": query},
            "error": None,
        }
    except Exception as e:
        return {"ok": False, "status": 500, "data": {}, "error": str(e)}


@app.tool("memory.curate")
def curate(
    *, days: int = 7, model: str = None, _secrets: dict = {},
) -> Dict[str, Any]:
    """Trigger curation: extract stable facts from daily logs into MEMORY.md.

    Args:
        days: Number of recent days to curate.
        model: Override curation model (not used in file-based impl).
    """
    try:
        _ensure_dirs()
        daily_files = sorted(_DAILY_DIR.glob("*.md"), reverse=True)[:days]
        curated_entries = []

        for daily_file in daily_files:
            content = daily_file.read_text(encoding="utf-8")
            # Simple extraction: lines starting with key phrases
            for line in content.split("\n"):
                stripped = line.strip()
                if stripped and not stripped.startswith("#") and len(stripped) > 20:
                    curated_entries.append(stripped)

        if curated_entries:
            now = datetime.now(timezone.utc)
            with open(_LONG_TERM, "a", encoding="utf-8") as f:
                f.write(f"\n## Curation {now.strftime('%Y-%m-%d')}\n\n")
                for entry in curated_entries[:20]:
                    f.write(f"- {entry}\n")
                f.write("\n")

        return {
            "ok": True,
            "status": 200,
            "data": {
                "curated_entries": len(curated_entries),
                "days_processed": len(daily_files),
                "target": str(_LONG_TERM),
            },
            "error": None,
        }
    except Exception as e:
        return {"ok": False, "status": 500, "data": {}, "error": str(e)}
