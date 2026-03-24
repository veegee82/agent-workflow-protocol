"""
Built-in MCP Tools: file.read, file.write, file.list

File system operations with sandboxed path validation.
Auto-generated for tool implementation mode.
"""

from __future__ import annotations

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


app = FastMCP("file")

# Sandbox: only allow operations within the workflow directory
_ALLOWED_ROOTS = [Path(".").resolve(), Path("data").resolve()]


def _validate_path(path_str: str) -> Path:
    """Validate that the path is within allowed roots."""
    p = Path(path_str).resolve()
    for root in _ALLOWED_ROOTS:
        if str(p).startswith(str(root)):
            return p
    raise PermissionError(f"Path '{path_str}' is outside allowed directories")


@app.tool("file.read")
def read(*, path: str, encoding: str = "utf-8", _secrets: dict = {}) -> Dict[str, Any]:
    """Read file contents from disk.

    Args:
        path: File path.
        encoding: File encoding (default: utf-8).
    """
    try:
        p = _validate_path(path)
        content = p.read_text(encoding=encoding)
        return {
            "ok": True,
            "status": 200,
            "data": {"content": content, "size": len(content), "path": str(p)},
            "error": None,
        }
    except FileNotFoundError:
        return {"ok": False, "status": 404, "data": {}, "error": f"File not found: {path}"}
    except Exception as e:
        return {"ok": False, "status": 500, "data": {}, "error": str(e)}


@app.tool("file.write")
def write(
    *, path: str, content: str, mode: str = "overwrite", _secrets: dict = {},
) -> Dict[str, Any]:
    """Write content to a file.

    Args:
        path: File path.
        content: Content to write.
        mode: 'overwrite' or 'append'.
    """
    try:
        p = _validate_path(path)
        p.parent.mkdir(parents=True, exist_ok=True)

        if mode == "append":
            with open(p, "a", encoding="utf-8") as f:
                f.write(content)
        else:
            p.write_text(content, encoding="utf-8")

        return {
            "ok": True,
            "status": 200,
            "data": {"path": str(p), "bytes_written": len(content.encode()), "mode": mode},
            "error": None,
        }
    except Exception as e:
        return {"ok": False, "status": 500, "data": {}, "error": str(e)}


@app.tool("file.list")
def list_files(
    *, path: str, pattern: str = "*", recursive: bool = False, _secrets: dict = {},
) -> Dict[str, Any]:
    """List files in a directory.

    Args:
        path: Directory path.
        pattern: Glob pattern.
        recursive: Include subdirectories.
    """
    try:
        p = _validate_path(path)
        if not p.is_dir():
            return {"ok": False, "status": 404, "data": {}, "error": f"Not a directory: {path}"}

        if recursive:
            files = [str(f.relative_to(p)) for f in p.rglob(pattern) if f.is_file()]
        else:
            files = [str(f.relative_to(p)) for f in p.glob(pattern) if f.is_file()]

        return {
            "ok": True,
            "status": 200,
            "data": {"files": files, "count": len(files), "path": str(p)},
            "error": None,
        }
    except Exception as e:
        return {"ok": False, "status": 500, "data": {}, "error": str(e)}
