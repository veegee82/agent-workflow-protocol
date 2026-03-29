"""AWP Tool Registry -- Built-in and custom MCP tool execution.

Provides built-in tools (web.search, http.request, file.read, file.write,
file.list, shell.execute, terminal.execute, arithmetic.*, memory.*) and discovers custom
tools from the workflow's mcp/ directory.

Custom tools in mcp/ may override built-in tools by using the same FQN
(e.g., a project can provide its own web.search implementation).

All tools return the standard AWP result format:
    {"ok": bool, "status": int, "data": Any, "error": str | None}
"""

from __future__ import annotations

import ast
import importlib.util
import logging
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

    def __init__(
        self,
        workflow_dir: Optional[Path] = None,
        secrets: Optional[dict[str, str]] = None,
    ) -> None:
        self._tools: dict[str, ToolFunc] = {}
        self._definitions: dict[str, dict[str, Any]] = {}
        self._tool_secrets: dict[str, list[str]] = {}  # tool FQN → declared secret keys
        self._dynamic_tools: dict[str, dict[str, Any]] = {}  # FQN → provenance metadata
        self._secrets: dict[str, str] = secrets or {}
        self._workflow_dir = workflow_dir
        self._memory_dir: Optional[Path] = None
        self._message_bus: Any = None
        self._code_executor: Any = None
        self._dynamic_tool_factory: Any = None
        self._security_context: Any = None
        self._current_agent_id: str = ""
        self._run_id: str = ""

        if workflow_dir:
            ws = workflow_dir / "workspace"
            if ws.exists() or True:  # always set, created on write
                self._memory_dir = ws

        self._register_builtins()
        if workflow_dir:
            self._discover_custom_tools(workflow_dir)

    def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Execute a tool by FQN name.

        If the tool declared secrets via ``secrets=["KEY"]`` in its decorator
        and those secrets are available, they are injected as a ``_secrets``
        kwarg. The LLM never sees these values.

        Args:
            name: Tool fully qualified name (e.g., "file.read").
            arguments: Tool arguments dict (from LLM).

        Returns:
            Standard AWP tool result.
        """
        # Access control check
        if self._security_context and self._current_agent_id:
            ac = self._security_context.access_controller
            if ac and not ac.is_allowed(self._current_agent_id, name):
                return _err(
                    f"Access denied: agent '{self._current_agent_id}' cannot use '{name}'",
                    403,
                )

        fn = self._tools.get(name)
        if fn is None:
            return _err(f"Unknown tool: {name}", 404)
        try:
            declared = self._tool_secrets.get(name, [])
            if declared and self._secrets:
                tool_secrets = {
                    k: self._secrets[k] for k in declared if k in self._secrets
                }
                return fn(**arguments, _secrets=tool_secrets)
            return fn(**arguments)
        except TypeError as exc:
            return _err(f"Invalid arguments for {name}: {exc}", 400)
        except Exception as exc:
            logger.error("Tool %s failed: %s", name, exc)
            return _err(str(exc), 500)

    def get_definitions(
        self, allowed: Optional[list[str]] = None
    ) -> list[dict[str, Any]]:
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

    def validate_secrets(
        self, allowed_tools: Optional[list[str]] = None
    ) -> dict[str, list[str]]:
        """Validate that all declared secrets are present.

        Missing secrets are logged as warnings but do not block execution.
        Tools are expected to handle missing secrets gracefully.

        Args:
            allowed_tools: Optional list of tool FQNs or patterns to check.

        Returns:
            Dict of tool_name → list of missing secret keys. Empty if all OK.
        """
        tools_to_check: list[str]
        if allowed_tools:
            tools_to_check = []
            for name in self._tools:
                for pattern in allowed_tools:
                    if pattern == name:
                        tools_to_check.append(name)
                        break
                    if "*" in pattern:
                        regex = pattern.replace(".", r"\.").replace("*", ".*")
                        if re.match(f"^{regex}$", name):
                            tools_to_check.append(name)
                            break
        else:
            tools_to_check = list(self._tools.keys())

        missing: dict[str, list[str]] = {}
        for tool_name in tools_to_check:
            declared = self._tool_secrets.get(tool_name, [])
            for key in declared:
                if key not in self._secrets:
                    missing.setdefault(tool_name, []).append(key)

        if missing:
            for tool, keys in missing.items():
                logger.warning(
                    "Tool '%s' has missing secrets: %s -- "
                    "tool may run with reduced functionality",
                    tool,
                    ", ".join(keys),
                )

        return missing

    def inject_secrets(self, new_secrets: dict[str, str]) -> None:
        """Inject additional secrets at runtime (e.g., from interactive prompt)."""
        self._secrets.update(new_secrets)

    # -- Built-in tools -----------------------------------------------

    def _register_builtins(self) -> None:
        self._register(
            "file.read",
            self._file_read,
            {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path to read"},
                    "encoding": {
                        "type": "string",
                        "description": "File encoding",
                        "default": "utf-8",
                    },
                },
                "required": ["path"],
            },
            "Read file contents from disk",
        )

        self._register(
            "file.write",
            self._file_write,
            {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path to write"},
                    "content": {"type": "string", "description": "Content to write"},
                    "mode": {
                        "type": "string",
                        "description": "overwrite or append",
                        "default": "overwrite",
                    },
                },
                "required": ["path", "content"],
            },
            "Write content to a file",
        )

        self._register(
            "file.list",
            self._file_list,
            {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Directory path"},
                    "pattern": {
                        "type": "string",
                        "description": "Glob pattern",
                        "default": "*",
                    },
                    "recursive": {
                        "type": "boolean",
                        "description": "Include subdirectories",
                        "default": False,
                    },
                },
                "required": ["path"],
            },
            "List files in a directory",
        )

        self._register(
            "shell.execute",
            self._shell_execute,
            {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "Shell command to execute",
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "Timeout in seconds",
                        "default": 30,
                    },
                    "cwd": {"type": "string", "description": "Working directory"},
                },
                "required": ["command"],
            },
            "Execute a shell command",
        )

        self._register(
            "terminal.execute",
            self._terminal_execute,
            {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "Shell command to execute (sudo is forbidden)",
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "Timeout in seconds",
                        "default": 30,
                    },
                    "cwd": {"type": "string", "description": "Working directory"},
                },
                "required": ["command"],
            },
            "Execute a shell command with full terminal access (sudo forbidden)",
        )

        for op in ("add", "subtract", "multiply", "divide"):
            self._register(
                f"arithmetic.{op}",
                getattr(self, f"_arith_{op}"),
                {
                    "type": "object",
                    "properties": {
                        "a": {"type": "number", "description": "First operand"},
                        "b": {"type": "number", "description": "Second operand"},
                    },
                    "required": ["a", "b"],
                },
                f"{op.capitalize()} two numbers",
            )

        self._register(
            "memory.read",
            self._memory_read,
            {
                "type": "object",
                "properties": {
                    "target": {
                        "type": "string",
                        "description": "long_term, daily, or dates",
                        "default": "long_term",
                    },
                    "date": {
                        "type": "string",
                        "description": "Date for daily log (YYYY-MM-DD)",
                    },
                },
            },
            "Read memory (MEMORY.md or daily log)",
        )

        self._register(
            "memory.write",
            self._memory_write,
            {
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "Content to write"},
                    "target": {
                        "type": "string",
                        "description": "daily or long_term",
                        "default": "daily",
                    },
                },
                "required": ["content"],
            },
            "Write to memory (daily log or MEMORY.md)",
        )

        self._register(
            "memory.search",
            self._memory_search,
            {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "max_results": {
                        "type": "integer",
                        "description": "Max results",
                        "default": 10,
                    },
                },
                "required": ["query"],
            },
            "Search across memory files",
        )

        self._register_memory_curate()

        self._register(
            "web.search",
            self._web_search,
            {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query (1-500 chars)",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum results (1-100)",
                        "default": 10,
                    },
                    "language": {
                        "type": "string",
                        "description": "Language filter (ISO 639-1)",
                        "default": "en",
                    },
                },
                "required": ["query"],
            },
            "Search the web for information",
        )

        self._register(
            "http.request",
            self._http_request,
            {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "Target URL"},
                    "method": {
                        "type": "string",
                        "description": "HTTP method",
                        "default": "GET",
                    },
                    "headers": {
                        "type": "object",
                        "description": "HTTP headers",
                        "default": {},
                    },
                    "body": {"type": "string", "description": "Request body"},
                    "timeout": {
                        "type": "integer",
                        "description": "Timeout in seconds",
                        "default": 30,
                    },
                },
                "required": ["url"],
            },
            "Make an HTTP request",
        )

    def _register(
        self,
        name: str,
        fn: ToolFunc,
        params: dict,
        desc: str,
        secrets_keys: Optional[list[str]] = None,
    ) -> None:
        self._tools[name] = fn
        self._definitions[name] = {
            "type": "function",
            "function": {
                "name": name,
                "description": desc,
                "parameters": params,
            },
        }
        self._tool_secrets[name] = secrets_keys or []

    # -- File tools ---------------------------------------------------

    def _resolve_path(self, path: str) -> Path:
        """Resolve a path, trying workspace-relative if the literal path doesn't exist.

        Search order:
        1. Literal path
        2. workspace/{path}
        3. workspace/inputs/{path}
        4. workspace/inputs/{basename} (fallback for wrong directory prefixes)
        """
        p = Path(path)
        if p.exists():
            return p
        if self._workflow_dir and not p.is_absolute():
            ws_path = self._workflow_dir / "workspace" / path
            if ws_path.exists():
                return ws_path
            # Also check workspace/inputs/
            inputs_path = self._workflow_dir / "workspace" / "inputs" / path
            if inputs_path.exists():
                return inputs_path
            # Fallback: try just the filename in workspace/inputs/
            basename_path = self._workflow_dir / "workspace" / "inputs" / p.name
            if basename_path.exists():
                return basename_path
        return p  # return original for error reporting

    def _file_read(self, *, path: str, encoding: str = "utf-8") -> dict[str, Any]:
        try:
            resolved = self._resolve_path(path)
            content = resolved.read_text(encoding=encoding)
            return _ok({"content": content, "size": len(content)})
        except FileNotFoundError:
            return _err(f"File not found: {path}", 404)
        except Exception as e:
            return _err(str(e))

    def _file_write(
        self, *, path: str, content: str, mode: str = "overwrite"
    ) -> dict[str, Any]:
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

    def _file_list(
        self, *, path: str, pattern: str = "*", recursive: bool = False
    ) -> dict[str, Any]:
        try:
            p = self._resolve_path(path)
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

    def _shell_execute(
        self, *, command: str, timeout: int = 30, cwd: Optional[str] = None
    ) -> dict[str, Any]:
        timeout = min(timeout, 120)  # hard cap
        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=cwd,
            )
            return _ok(
                {
                    "stdout": result.stdout[:50000],
                    "stderr": result.stderr[:10000],
                    "returncode": result.returncode,
                }
            )
        except subprocess.TimeoutExpired:
            return _err(f"Timeout after {timeout}s", 408)
        except Exception as e:
            return _err(str(e))

    # -- Terminal tools (sudo-free shell) --------------------------------

    # Patterns that indicate sudo usage.  We check the raw command string
    # after splitting on shell meta-characters so that constructs like
    # ``echo hi && sudo rm -rf /`` are caught.
    _SUDO_PATTERN = re.compile(
        r"""
        (?:^|[;&|`\n]\s*)   # start of string or after shell separator
        sudo\b               # the word "sudo"
        """,
        re.VERBOSE,
    )

    @staticmethod
    def _contains_sudo(command: str) -> bool:
        """Return True if *command* attempts to use sudo in any form."""
        # Also catch common evasion attempts:
        #   sudo, /usr/bin/sudo, env sudo, command sudo, pkexec, doas
        for token in re.split(r"[;&|`\n]+", command):
            stripped = token.strip()
            # Direct sudo invocation
            if re.match(r"^sudo\b", stripped):
                return True
            # Absolute path to sudo
            if re.match(r"^(/usr/bin/|/bin/)?sudo\b", stripped):
                return True
            # Via env or command builtins
            if re.match(r"^(env|command)\s+sudo\b", stripped):
                return True
            # pkexec and doas are sudo-equivalents
            if re.match(r"^(pkexec|doas)\b", stripped):
                return True
        return False

    def _terminal_execute(
        self, *, command: str, timeout: int = 30, cwd: Optional[str] = None
    ) -> dict[str, Any]:
        """Execute a shell command, rejecting any command that uses sudo."""
        if self._contains_sudo(command):
            return _err(
                "terminal.execute forbids sudo and privilege escalation commands. "
                "Use shell.execute if elevated privileges are required.",
                403,
            )
        timeout = min(timeout, 120)  # hard cap
        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=cwd,
            )
            return _ok(
                {
                    "stdout": result.stdout[:50000],
                    "stderr": result.stderr[:10000],
                    "returncode": result.returncode,
                }
            )
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

    def _memory_read(
        self, *, target: str = "long_term", date: Optional[str] = None
    ) -> dict[str, Any]:
        if not self._memory_dir:
            return _err("No workspace directory configured", 404)

        if target == "long_term":
            mem_file = self._memory_dir / "MEMORY.md"
            if not mem_file.exists():
                return _ok({"content": "", "exists": False})
            return _ok(
                {"content": mem_file.read_text(encoding="utf-8"), "exists": True}
            )

        elif target == "daily":
            d = date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
            log_file = self._memory_dir / "memory" / f"{d}.md"
            if not log_file.exists():
                return _ok({"content": "", "date": d, "exists": False})
            return _ok(
                {
                    "content": log_file.read_text(encoding="utf-8"),
                    "date": d,
                    "exists": True,
                }
            )

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
                    results.append(
                        {"source": "MEMORY.md", "line": i + 1, "text": line.strip()}
                    )

        # Search daily logs
        mem_dir = self._memory_dir / "memory"
        if mem_dir.exists():
            for log_file in sorted(mem_dir.glob("*.md"), reverse=True):
                content = log_file.read_text(encoding="utf-8")
                for i, line in enumerate(content.split("\n")):
                    if query_lower in line.lower():
                        results.append(
                            {
                                "source": log_file.name,
                                "line": i + 1,
                                "text": line.strip(),
                            }
                        )
                if len(results) >= max_results:
                    break

        return _ok({"results": results[:max_results], "total": len(results)})

    # -- Web tools ----------------------------------------------------

    def _web_search(
        self, *, query: str, max_results: int = 10, language: str = "en"
    ) -> dict[str, Any]:
        """Search the web via DuckDuckGo HTML (no API key required)."""
        import urllib.parse
        import urllib.request

        try:
            encoded = urllib.parse.urlencode(
                {
                    "q": query,
                    "kl": f"{language}-{language}",
                }
            )
            url = f"https://html.duckduckgo.com/html/?{encoded}"
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "AWP-Runtime/1.0",
                },
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                html = resp.read().decode("utf-8", errors="replace")

            # Extract result snippets from DuckDuckGo HTML
            results: list[dict[str, str]] = []
            # Simple regex extraction of result blocks
            import re as _re

            for match in _re.finditer(
                r'class="result__a"[^>]*href="([^"]*)"[^>]*>([^<]*)</a>.*?'
                r'class="result__snippet"[^>]*>(.*?)</span>',
                html,
                _re.DOTALL,
            ):
                if len(results) >= max_results:
                    break
                href, title, snippet = match.groups()
                # DuckDuckGo wraps URLs in a redirect; extract the actual URL
                actual_url = href
                ud_match = _re.search(r"uddg=([^&]+)", href)
                if ud_match:
                    actual_url = urllib.parse.unquote(ud_match.group(1))
                results.append(
                    {
                        "title": title.strip(),
                        "url": actual_url,
                        "snippet": _re.sub(r"<[^>]+>", "", snippet).strip(),
                    }
                )

            return _ok({"results": results, "count": len(results), "query": query})
        except Exception as e:
            return _err(f"Web search failed: {e}")

    def _http_request(
        self,
        *,
        url: str,
        method: str = "GET",
        headers: Optional[dict[str, str]] = None,
        body: Optional[str] = None,
        timeout: int = 30,
    ) -> dict[str, Any]:
        """Make an HTTP request using urllib (no external dependencies)."""
        import urllib.request
        import urllib.error

        timeout = min(timeout, 120)  # hard cap
        try:
            req = urllib.request.Request(
                url,
                data=body.encode("utf-8") if body else None,
                headers=headers or {},
                method=method.upper(),
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                resp_body = resp.read().decode("utf-8", errors="replace")
                return _ok(
                    {
                        "status_code": resp.status,
                        "headers": dict(resp.headers),
                        "body": resp_body[:100000],  # cap response size
                    }
                )
        except urllib.error.HTTPError as e:
            body_text = ""
            try:
                body_text = e.read().decode("utf-8", errors="replace")[:10000]
            except Exception:
                pass
            return _ok(
                {
                    "status_code": e.code,
                    "headers": dict(e.headers) if e.headers else {},
                    "body": body_text,
                }
            )
        except urllib.error.URLError as e:
            return _err(f"URL error: {e.reason}")
        except Exception as e:
            return _err(f"HTTP request failed: {e}")

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

        # Find @app.tool("fqn", secrets=["KEY"]) decorators
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
                        # Extract secrets=["KEY1", "KEY2"] from decorator kwargs
                        secrets_keys: list[str] = []
                        for kw in dec.keywords:
                            if kw.arg == "secrets" and isinstance(kw.value, ast.List):
                                for elt in kw.value.elts:
                                    if isinstance(elt, ast.Constant) and isinstance(
                                        elt.value, str
                                    ):
                                        secrets_keys.append(elt.value)
                        self._register_custom_tool(fqn, py_file, node, secrets_keys)

    def _register_custom_tool(
        self,
        fqn: str,
        py_file: Path,
        func_node: ast.FunctionDef,
        secrets_keys: Optional[list[str]] = None,
    ) -> None:
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
        except Exception:
            # FastMCP may reject _secrets parameter in validation.
            # Retry with mcp blocked so the stub fallback is used.
            try:
                module = importlib.util.module_from_spec(spec)
                module.__dict__["__builtins__"] = module.__dict__.get(
                    "__builtins__", {}
                )
                # Temporarily hide the real mcp package so the stub is used
                saved = sys.modules.get("mcp.server.fastmcp")
                sys.modules["mcp.server.fastmcp"] = None  # type: ignore[assignment]
                try:
                    spec.loader.exec_module(module)
                finally:
                    if saved is not None:
                        sys.modules["mcp.server.fastmcp"] = saved
                    else:
                        sys.modules.pop("mcp.server.fastmcp", None)
            except Exception as exc2:
                logger.warning(
                    "Failed to load custom tool module %s: %s", py_file.name, exc2
                )
                return

        # Find the function in the module
        fn = getattr(module, func_node.name, None)
        if fn is None:
            return

        # Merge AST-extracted secrets with runtime attribute (fallback)
        merged_secrets = list(secrets_keys or [])
        if hasattr(fn, "_awp_secrets"):
            for k in fn._awp_secrets:
                if k not in merged_secrets:
                    merged_secrets.append(k)

        # Extract parameters from function signature (excluding _secrets)
        import inspect

        sig = inspect.signature(fn)
        params: dict[str, Any] = {"type": "object", "properties": {}, "required": []}
        for pname, param in sig.parameters.items():
            if pname in ("self", "cls", "_secrets"):
                continue
            ptype = "string"
            if param.annotation != inspect.Parameter.empty:
                ann = param.annotation
                if ann in (int, float):
                    ptype = "number"
                elif ann is bool:
                    ptype = "boolean"
                elif ann in (list, list):
                    ptype = "array"
            params["properties"][pname] = {"type": ptype, "description": pname}
            if param.default == inspect.Parameter.empty:
                params["required"].append(pname)

        desc = (
            func_node.body[0].value.value
            if (
                func_node.body
                and isinstance(func_node.body[0], ast.Expr)
                and isinstance(func_node.body[0].value, ast.Constant)
            )
            else f"Custom tool: {fqn}"
        )

        self._register(fqn, fn, params, desc, secrets_keys=merged_secrets)
        logger.info("Registered custom tool: %s from %s", fqn, py_file.name)

    # -- Integration methods (called by WorkflowRunner) -------------------

    def set_message_bus(self, bus: Any) -> None:
        """Wire message bus tools into the registry."""
        self._message_bus = bus

        self._register(
            "agent.send_message",
            self._agent_send_message,
            {
                "type": "object",
                "properties": {
                    "to": {
                        "type": "string",
                        "description": "Recipient agent ID or '*' for broadcast",
                    },
                    "content": {
                        "description": "Message content (any JSON-serializable value)"
                    },
                    "channel": {
                        "type": "string",
                        "description": "Channel name",
                        "default": "direct",
                    },
                    "type": {
                        "type": "string",
                        "description": "Message type: request, response, event",
                        "default": "event",
                    },
                },
                "required": ["to", "content"],
            },
            "Send a message to another agent via the message bus",
        )

        self._register(
            "agent.list_messages",
            self._agent_list_messages,
            {
                "type": "object",
                "properties": {
                    "channel": {
                        "type": "string",
                        "description": "Filter by channel name",
                    },
                    "from_agent": {
                        "type": "string",
                        "description": "Filter by sender agent ID",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum messages to return",
                        "default": 50,
                    },
                },
            },
            "List messages received by this agent",
        )

    def set_run_id(self, run_id: str) -> None:
        """Set the current run ID for output isolation."""
        self._run_id = run_id

    def set_code_executor(self, executor: Any) -> None:
        """Wire code execution tool into the registry."""
        self._code_executor = executor

        self._register(
            "code.execute",
            self._code_execute,
            {
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "Python code to execute"},
                    "timeout": {
                        "type": "integer",
                        "description": "Timeout in seconds",
                        "default": 30,
                    },
                },
                "required": ["code"],
            },
            "Execute Python code in a sandboxed subprocess",
        )

    def set_security_context(self, security_ctx: Any) -> None:
        """Set security context for access control enforcement."""
        self._security_context = security_ctx

    def set_dynamic_tool_factory(self, factory: Any) -> None:
        """Set the DynamicToolFactory for runtime tool creation."""
        self._dynamic_tool_factory = factory

    def register_dynamic(
        self,
        name: str,
        fn: ToolFunc,
        params: dict,
        desc: str,
        creator_agent: str,
        secrets_keys: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        """Register a dynamically created tool with provenance tracking.

        Args:
            name: Tool FQN.
            fn: Tool callable.
            params: JSON Schema for parameters.
            desc: Tool description.
            creator_agent: ID of the agent that created this tool.
            secrets_keys: Optional secret keys (usually empty for dynamic tools).

        Returns:
            Standard AWP result format.
        """
        if name in self._tools:
            return _err(f"Tool already exists: {name}", 409)
        self._register(name, fn, params, desc, secrets_keys=secrets_keys)
        self._dynamic_tools[name] = {
            "creator": creator_agent,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        return _ok({"name": name, "registered": True})

    def unregister(self, name: str) -> dict[str, Any]:
        """Remove a tool from the registry. Only dynamic tools can be removed.

        Args:
            name: Tool FQN to remove.

        Returns:
            Standard AWP result format.
        """
        if name not in self._dynamic_tools:
            return _err(f"Cannot unregister non-dynamic tool: {name}", 403)
        self._tools.pop(name, None)
        self._definitions.pop(name, None)
        self._tool_secrets.pop(name, None)
        self._dynamic_tools.pop(name, None)
        return _ok({"name": name, "unregistered": True})

    def get_dynamic_tools(self) -> list[str]:
        """Return FQNs of all dynamically registered tools."""
        return list(self._dynamic_tools.keys())

    # -- Message bus tools ------------------------------------------------

    def _agent_send_message(
        self,
        *,
        to: str,
        content: Any,
        channel: str = "direct",
        type: str = "event",
    ) -> dict[str, Any]:
        if not self._message_bus:
            return _err("Message bus not configured", 503)
        from_agent = self._current_agent_id or "unknown"
        if to == "*":
            msg_id = self._message_bus.broadcast(from_agent, content, channel=channel)
        else:
            msg_id = self._message_bus.send(
                from_agent, to, content, channel=channel, msg_type=type
            )
        return _ok(
            {"message_id": msg_id, "from": from_agent, "to": to, "channel": channel}
        )

    def _agent_list_messages(
        self,
        *,
        channel: Optional[str] = None,
        from_agent: Optional[str] = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        if not self._message_bus:
            return _err("Message bus not configured", 503)
        agent_id = self._current_agent_id or "unknown"
        messages = self._message_bus.list_messages(
            agent_id, channel=channel, from_agent=from_agent, limit=limit
        )
        return _ok({"messages": messages, "count": len(messages)})

    # -- Code execution tool ----------------------------------------------

    def _code_execute(self, *, code: str, timeout: int = 30) -> dict[str, Any]:
        if not self._code_executor:
            return _err("Code executor not configured", 503)

        # Inject _workspace_dir and _output_dir so executed code can save files
        preamble = ""
        if self._workflow_dir:
            ws = self._workflow_dir / "workspace"
            ws.mkdir(parents=True, exist_ok=True)
            if self._run_id:
                out = self._workflow_dir / "output" / self._run_id
            else:
                out = self._workflow_dir / "output"
            out.mkdir(parents=True, exist_ok=True)
            preamble = f"_workspace_dir = {str(ws)!r}\n_output_dir = {str(out)!r}\n"

        return self._code_executor.execute(preamble + code, timeout=timeout)

    # -- Memory curate tool -----------------------------------------------

    def _register_memory_curate(self) -> None:
        """Register the memory.curate tool (called during builtin registration)."""
        self._register(
            "memory.curate",
            self._memory_curate,
            {
                "type": "object",
                "properties": {
                    "days": {
                        "type": "integer",
                        "description": "Number of recent days to curate from",
                        "default": 7,
                    },
                },
            },
            "Extract stable facts from recent daily logs into long-term memory",
        )

    def _memory_curate(self, *, days: int = 7) -> dict[str, Any]:
        """Extract key facts from recent daily logs and append to MEMORY.md."""
        if not self._memory_dir:
            return _err("No workspace directory configured", 404)

        mem_dir = self._memory_dir / "memory"
        if not mem_dir.exists():
            return _ok({"curated": 0, "message": "No daily logs found"})

        # Collect recent daily logs
        from datetime import timedelta

        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        entries: list[str] = []
        for log_file in sorted(mem_dir.glob("*.md"), reverse=True):
            try:
                date_str = log_file.stem
                file_date = datetime.strptime(date_str, "%Y-%m-%d").replace(
                    tzinfo=timezone.utc
                )
                if file_date < cutoff:
                    break
                content = log_file.read_text(encoding="utf-8").strip()
                if content:
                    entries.append(f"## {date_str}\n{content}")
            except (ValueError, OSError):
                continue

        if not entries:
            return _ok({"curated": 0, "message": "No recent entries to curate"})

        # Write curation summary to MEMORY.md
        mem_file = self._memory_dir / "MEMORY.md"
        mem_file.parent.mkdir(parents=True, exist_ok=True)
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        curation = f"\n\n---\n### Curation {date_str}\n"
        curation += f"Curated from {len(entries)} daily log(s):\n"
        for entry in entries[:5]:  # Limit to 5 most recent
            # Extract first meaningful line from each entry
            lines = [
                line.strip()
                for line in entry.split("\n")
                if line.strip() and not line.startswith("##")
            ]
            if lines:
                curation += f"- {lines[0][:200]}\n"

        with mem_file.open("a", encoding="utf-8") as f:
            f.write(curation)

        return _ok({"curated": len(entries), "path": str(mem_file)})
