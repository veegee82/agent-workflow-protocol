"""AWP Tool Registry -- Built-in and custom MCP tool execution.

Provides built-in tools (file.read, file.write, file.list, shell.execute,
arithmetic.*, memory.*) and discovers custom tools from the workflow's
mcp/ directory.

All tools return the standard AWP result format:
    {"ok": bool, "status": int, "data": Any, "error": str | None}
"""

from __future__ import annotations

import ast
import importlib.util
import json
import logging
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

# Type for tool functions
ToolFunc = Callable[..., dict[str, Any]]

# Standard result helpers
def _ok(data: Any, log: str = "") -> dict[str, Any]:
    return {"ok": True, "status": 200, "data": data, "error": None, "log": log}

def _err(msg: str, status: int = 500) -> dict[str, Any]:
    return {"ok": False, "status": status, "data": {}, "error": msg, "log": ""}


class ToolRegistry:
    """Registry of available AWP tools.

    Discovers built-in tools and optionally loads custom tools from
    a workflow's mcp/ directory.
    """

    def __init__(self, workflow_dir: Optional[Path] = None) -> None:
        self._tools: dict[str, ToolFunc] = {}
        self._definitions: dict[str, dict[str, Any]] = {}
        self._workflow_dir = workflow_dir
        self._memory_dir: Optional[Path] = None

        if workflow_dir:
            ws = workflow_dir / "workspace"
            if ws.exists() or True:  # always set, created on write
                self._memory_dir = ws

        self._register_builtins()
        if workflow_dir:
            self._discover_custom_tools(workflow_dir)

    def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Execute a tool by FQN name.

        Args:
            name: Tool fully qualified name (e.g., "file.read").
            arguments: Tool arguments dict.

        Returns:
            Standard AWP tool result.
        """
        fn = self._tools.get(name)
        if fn is None:
            return _err(f"Unknown tool: {name}", 404)
        try:
            return fn(**arguments)
        except TypeError as exc:
            return _err(f"Invalid arguments for {name}: {exc}", 400)
        except Exception as exc:
            logger.error("Tool %s failed: %s", name, exc)
            return _err(str(exc), 500)

    def get_definitions(self, allowed: Optional[list[str]] = None) -> list[dict[str, Any]]:
        """Get tool definitions in OpenAI function calling format.

        Args:
            allowed: Optional list of tool FQNs or patterns (e.g., ["web.*", "file.read"]).
                     None or empty list means all tools.
        """
        if not allowed:
            return list(self._definitions.values())

        result = []
        for name, defn in self._definitions.items():
            for pattern in allowed:
                if pattern == name:
                    result.append(defn)
                    break
                if "*" in pattern:
                    regex = pattern.replace(".", r"\.").replace("*", ".*")
                    if re.match(f"^{regex}$", name):
                        result.append(defn)
                        break
        return result

    @property
    def tool_names(self) -> list[str]:
        return sorted(self._tools.keys())

    # -- Built-in tools -----------------------------------------------

    def _register_builtins(self) -> None:
        self._register("file.read", self._file_read, {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path to read"},
                "encoding": {"type": "string", "description": "File encoding", "default": "utf-8"},
            },
            "required": ["path"],
        }, "Read file contents from disk")

        self._register("file.write", self._file_write, {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path to write"},
                "content": {"type": "string", "description": "Content to write"},
                "mode": {"type": "string", "description": "overwrite or append", "default": "overwrite"},
            },
            "required": ["path", "content"],
        }, "Write content to a file")

        self._register("file.list", self._file_list, {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Directory path"},
                "pattern": {"type": "string", "description": "Glob pattern", "default": "*"},
                "recursive": {"type": "boolean", "description": "Include subdirectories", "default": False},
            },
            "required": ["path"],
        }, "List files in a directory")

        self._register("shell.execute", self._shell_execute, {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Shell command to execute"},
                "timeout": {"type": "integer", "description": "Timeout in seconds", "default": 30},
                "cwd": {"type": "string", "description": "Working directory"},
            },
            "required": ["command"],
        }, "Execute a shell command")

        for op in ("add", "subtract", "multiply", "divide"):
            self._register(f"arithmetic.{op}", getattr(self, f"_arith_{op}"), {
                "type": "object",
                "properties": {
                    "a": {"type": "number", "description": "First operand"},
                    "b": {"type": "number", "description": "Second operand"},
                },
                "required": ["a", "b"],
            }, f"{op.capitalize()} two numbers")

        self._register("memory.read", self._memory_read, {
            "type": "object",
            "properties": {
                "target": {"type": "string", "description": "long_term, daily, or dates", "default": "long_term"},
                "date": {"type": "string", "description": "Date for daily log (YYYY-MM-DD)"},
            },
        }, "Read memory (MEMORY.md or daily log)")

        self._register("memory.write", self._memory_write, {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "Content to write"},
                "target": {"type": "string", "description": "daily or long_term", "default": "daily"},
            },
            "required": ["content"],
        }, "Write to memory (daily log or MEMORY.md)")

        self._register("memory.search", self._memory_search, {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "max_results": {"type": "integer", "description": "Max results", "default": 10},
            },
            "required": ["query"],
        }, "Search across memory files")

    def _register(self, name: str, fn: ToolFunc, params: dict, desc: str) -> None:
        self._tools[name] = fn
        self._definitions[name] = {
            "type": "function",
            "function": {
                "name": name,
                "description": desc,
                "parameters": params,
            },
        }

    # -- File tools ---------------------------------------------------

    def _file_read(self, *, path: str, encoding: str = "utf-8") -> dict[str, Any]:
        try:
            content = Path(path).read_text(encoding=encoding)
            return _ok({"content": content, "size": len(content)})
        except FileNotFoundError:
            return _err(f"File not found: {path}", 404)
        except Exception as e:
            return _err(str(e))

    def _file_write(self, *, path: str, content: str, mode: str = "overwrite") -> dict[str, Any]:
        try:
            p = Path(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            if mode == "append":
                with p.open("a", encoding="utf-8") as f:
                    f.write(content)
            else:
                p.write_text(content, encoding="utf-8")
            return _ok({"path": str(p), "size": len(content)})
        except Exception as e:
            return _err(str(e))

    def _file_list(self, *, path: str, pattern: str = "*", recursive: bool = False) -> dict[str, Any]:
        try:
            p = Path(path)
            if not p.exists():
                return _err(f"Directory not found: {path}", 404)
            if recursive:
                files = [str(f.relative_to(p)) for f in p.rglob(pattern) if f.is_file()]
            else:
                files = [str(f.relative_to(p)) for f in p.glob(pattern) if f.is_file()]
            return _ok({"files": sorted(files), "count": len(files)})
        except Exception as e:
            return _err(str(e))

    # -- Shell tools --------------------------------------------------

    def _shell_execute(self, *, command: str, timeout: int = 30, cwd: Optional[str] = None) -> dict[str, Any]:
        timeout = min(timeout, 120)  # hard cap
        try:
            result = subprocess.run(
                command, shell=True, capture_output=True, text=True,
                timeout=timeout, cwd=cwd,
            )
            return _ok({
                "stdout": result.stdout[:50000],
                "stderr": result.stderr[:10000],
                "returncode": result.returncode,
            })
        except subprocess.TimeoutExpired:
            return _err(f"Timeout after {timeout}s", 408)
        except Exception as e:
            return _err(str(e))

    # -- Arithmetic ---------------------------------------------------

    def _arith_add(self, *, a: float, b: float) -> dict[str, Any]:
        return _ok({"result": a + b})

    def _arith_subtract(self, *, a: float, b: float) -> dict[str, Any]:
        return _ok({"result": a - b})

    def _arith_multiply(self, *, a: float, b: float) -> dict[str, Any]:
        return _ok({"result": a * b})

    def _arith_divide(self, *, a: float, b: float) -> dict[str, Any]:
        if b == 0:
            return _err("Division by zero", 400)
        return _ok({"result": a / b})

    # -- Memory tools -------------------------------------------------

    def _memory_read(self, *, target: str = "long_term", date: Optional[str] = None) -> dict[str, Any]:
        if not self._memory_dir:
            return _err("No workspace directory configured", 404)

        if target == "long_term":
            mem_file = self._memory_dir / "MEMORY.md"
            if not mem_file.exists():
                return _ok({"content": "", "exists": False})
            return _ok({"content": mem_file.read_text(encoding="utf-8"), "exists": True})

        elif target == "daily":
            d = date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
            log_file = self._memory_dir / "memory" / f"{d}.md"
            if not log_file.exists():
                return _ok({"content": "", "date": d, "exists": False})
            return _ok({"content": log_file.read_text(encoding="utf-8"), "date": d, "exists": True})

        elif target == "dates":
            mem_dir = self._memory_dir / "memory"
            if not mem_dir.exists():
                return _ok({"dates": []})
            dates = sorted(f.stem for f in mem_dir.glob("*.md"))
            return _ok({"dates": dates})

        return _err(f"Unknown target: {target}", 400)

    def _memory_write(self, *, content: str, target: str = "daily") -> dict[str, Any]:
        if not self._memory_dir:
            return _err("No workspace directory configured", 404)

        if target == "long_term":
            mem_file = self._memory_dir / "MEMORY.md"
            mem_file.parent.mkdir(parents=True, exist_ok=True)
            with mem_file.open("a", encoding="utf-8") as f:
                f.write(f"\n{content}\n")
            return _ok({"target": "long_term", "path": str(mem_file)})

        elif target == "daily":
            d = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            log_dir = self._memory_dir / "memory"
            log_dir.mkdir(parents=True, exist_ok=True)
            log_file = log_dir / f"{d}.md"
            timestamp = datetime.now(timezone.utc).strftime("%H:%M:%S")
            with log_file.open("a", encoding="utf-8") as f:
                f.write(f"\n### {timestamp}\n{content}\n")
            return _ok({"target": "daily", "date": d, "path": str(log_file)})

        return _err(f"Unknown target: {target}", 400)

    def _memory_search(self, *, query: str, max_results: int = 10) -> dict[str, Any]:
        if not self._memory_dir:
            return _err("No workspace directory configured", 404)

        results = []
        query_lower = query.lower()

        # Search MEMORY.md
        mem_file = self._memory_dir / "MEMORY.md"
        if mem_file.exists():
            content = mem_file.read_text(encoding="utf-8")
            for i, line in enumerate(content.split("\n")):
                if query_lower in line.lower():
                    results.append({"source": "MEMORY.md", "line": i + 1, "text": line.strip()})

        # Search daily logs
        mem_dir = self._memory_dir / "memory"
        if mem_dir.exists():
            for log_file in sorted(mem_dir.glob("*.md"), reverse=True):
                content = log_file.read_text(encoding="utf-8")
                for i, line in enumerate(content.split("\n")):
                    if query_lower in line.lower():
                        results.append({"source": log_file.name, "line": i + 1, "text": line.strip()})
                if len(results) >= max_results:
                    break

        return _ok({"results": results[:max_results], "total": len(results)})

    # -- Custom tool discovery ----------------------------------------

    def _discover_custom_tools(self, workflow_dir: Path) -> None:
        """Load custom MCP tools from workflow's mcp/ directory."""
        for mcp_dir_name in ("mcp", "tools"):
            mcp_dir = workflow_dir / mcp_dir_name
            if not mcp_dir.exists():
                continue

            for py_file in sorted(mcp_dir.glob("*.py")):
                if py_file.name.startswith("_"):
                    continue
                self._load_custom_tool_file(py_file)

    def _load_custom_tool_file(self, py_file: Path) -> None:
        """Load @app.tool() decorated functions from a Python file."""
        try:
            content = py_file.read_text(encoding="utf-8")
            tree = ast.parse(content)
        except Exception as exc:
            logger.warning("Failed to parse custom tool %s: %s", py_file.name, exc)
            return

        # Find @app.tool("fqn") decorators
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for dec in node.decorator_list:
                if not isinstance(dec, ast.Call):
                    continue
                func = dec.func
                if isinstance(func, ast.Attribute) and func.attr == "tool":
                    if dec.args and isinstance(dec.args[0], ast.Constant):
                        fqn = dec.args[0].value
                        self._register_custom_tool(fqn, py_file, node)

    def _register_custom_tool(self, fqn: str, py_file: Path, func_node: ast.FunctionDef) -> None:
        """Register a discovered custom tool."""
        # Load the module
        spec = importlib.util.spec_from_file_location(
            f"awp_custom_{py_file.stem}", py_file
        )
        if spec is None or spec.loader is None:
            return

        try:
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        except Exception as exc:
            logger.warning("Failed to load custom tool module %s: %s", py_file.name, exc)
            return

        # Find the function in the module
        fn = getattr(module, func_node.name, None)
        if fn is None:
            return

        # Extract parameters from function signature
        import inspect
        sig = inspect.signature(fn)
        params: dict[str, Any] = {"type": "object", "properties": {}, "required": []}
        for pname, param in sig.parameters.items():
            if pname in ("self", "cls"):
                continue
            ptype = "string"
            if param.annotation != inspect.Parameter.empty:
                ann = param.annotation
                if ann in (int, float):
                    ptype = "number"
                elif ann == bool:
                    ptype = "boolean"
                elif ann in (list, list):
                    ptype = "array"
            params["properties"][pname] = {"type": ptype, "description": pname}
            if param.default == inspect.Parameter.empty:
                params["required"].append(pname)

        desc = func_node.body[0].value.value if (
            func_node.body and isinstance(func_node.body[0], ast.Expr)
            and isinstance(func_node.body[0].value, ast.Constant)
        ) else f"Custom tool: {fqn}"

        self._tools[fqn] = fn
        self._definitions[fqn] = {
            "type": "function",
            "function": {"name": fqn, "description": desc, "parameters": params},
        }
        logger.info("Registered custom tool: %s from %s", fqn, py_file.name)
