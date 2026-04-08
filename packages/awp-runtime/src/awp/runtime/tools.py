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

        # ----- Argument validation against the registered JSON schema -----
        # Without this gate the LLM can send arbitrary kwargs that crash
        # deep inside the Python implementation with unhelpful TypeError
        # messages (e.g. ".join(notes) if not" being passed as a kwarg name
        # because the LLM emitted code in the wrong field). Validating up
        # front and returning a structured error gives the model a clear
        # corrective signal it can act on within the same iteration.
        defn = self._definitions.get(name, {}).get("function", {})
        schema = defn.get("parameters") or {}
        props = schema.get("properties") or {}
        required = schema.get("required") or []
        if isinstance(arguments, dict) and props:
            allowed_keys = set(props.keys())
            unknown = [k for k in arguments.keys() if k not in allowed_keys and not k.startswith("_")]
            missing = [k for k in required if k not in arguments]
            if unknown or missing:
                parts: list[str] = []
                if missing:
                    parts.append(f"missing required arguments: {missing}")
                if unknown:
                    parts.append(
                        f"unknown arguments: {unknown}. "
                        f"Valid arguments are: {sorted(allowed_keys)}. "
                        f"HINT: do NOT put code, JSON or shell snippets into "
                        f"argument names — emit them as VALUES of the declared "
                        f"parameters instead."
                    )
                return _err(
                    f"Invalid arguments for {name}: " + "; ".join(parts),
                    400,
                )

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

    # Sensitive system paths that agents should never read/write
    _SENSITIVE_PATHS: frozenset[str] = frozenset({
        "/etc/shadow", "/etc/gshadow", "/etc/master.passwd",
        "/etc/sudoers",
        "/root/.ssh", "/root/.bash_history", "/root/.gnupg",
    })

    # Sensitive path prefixes — block entire directories
    _SENSITIVE_PREFIXES: tuple[str, ...] = (
        "/proc/", "/sys/", "/dev/",
        "/root/.ssh/", "/root/.gnupg/",
    )

    def _is_path_allowed(self, resolved: Path) -> tuple[bool, str]:
        """Check if a resolved path is allowed for file operations.

        When a workflow_dir is set, file access is sandboxed to:
        - The workflow directory tree
        - /tmp and temp directories

        Always blocked: sensitive system files regardless of sandbox.

        Returns:
            Tuple of (allowed, reason).
        """
        try:
            resolved_str = str(resolved.resolve())
        except (PermissionError, OSError):
            resolved_str = str(resolved)

        # Always block sensitive system files
        for sensitive in self._SENSITIVE_PATHS:
            if resolved_str == sensitive or resolved_str.startswith(sensitive + "/"):
                return False, f"Access to '{sensitive}' is forbidden"

        for prefix in self._SENSITIVE_PREFIXES:
            if resolved_str.startswith(prefix):
                return False, f"Access to '{prefix}' is forbidden"

        # If workflow_dir is set, enforce sandbox
        if self._workflow_dir:
            workflow_root = str(self._workflow_dir.resolve())
            # Allow access within workflow dir
            if resolved_str.startswith(workflow_root):
                return True, ""
            # Allow /tmp and system temp dirs
            import tempfile
            tmp_dir = tempfile.gettempdir()
            if resolved_str.startswith(tmp_dir) or resolved_str.startswith("/tmp"):
                return True, ""
            # Block everything else when sandboxed
            return False, (
                f"Path '{resolved_str}' is outside the workflow directory. "
                f"File access is restricted to: {workflow_root}"
            )

        return True, ""

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
        # Early sandbox check on the raw path (before resolve, which may
        # raise PermissionError on protected directories like /root/)
        allowed, reason = self._is_path_allowed(Path(path))
        if not allowed:
            return _err(reason, 403)
        try:
            resolved = self._resolve_path(path)
            # Re-check resolved path (in case resolve changed it)
            allowed, reason = self._is_path_allowed(resolved)
            if not allowed:
                return _err(reason, 403)

            # Binary sniff: peek at the first 4 KiB and reject obvious
            # binary content with a structured, actionable error instead
            # of letting Python raise a cryptic UnicodeDecodeError. Real
            # workers in the wild repeatedly tried to file.read PNG/PDF
            # outputs with the default utf-8 encoding.
            _BINARY_EXT = {".png", ".jpg", ".jpeg", ".gif", ".pdf",
                            ".zip", ".gz", ".tar", ".xz", ".bz2",
                            ".parquet", ".feather", ".npy", ".npz",
                            ".so", ".dylib", ".dll", ".exe", ".pyc",
                            ".woff", ".woff2", ".ttf", ".otf", ".ico"}
            ext = resolved.suffix.lower()
            try:
                with resolved.open("rb") as _bf:
                    head = _bf.read(4096)
            except FileNotFoundError:
                return _err(f"File not found: {path}", 404)
            looks_binary = (
                ext in _BINARY_EXT
                or b"\x00" in head
                or (head and sum(b > 127 or b < 9 for b in head) / len(head) > 0.30)
            )
            if looks_binary:
                return {
                    "ok": False,
                    "status": 415,
                    "data": {
                        "path": str(resolved),
                        "ext": ext,
                        "size_bytes": resolved.stat().st_size,
                    },
                    "error": (
                        f"file.read refused: '{path}' looks binary "
                        f"(ext={ext or 'none'}). file.read returns text only. "
                        f"For images/PDFs/archives use code.execute with "
                        f"open(path, 'rb') or a domain-specific library "
                        f"(PIL, pypdf, zipfile). To check existence/size use "
                        f"file.list."
                    ),
                }

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
            # Path sandbox check
            allowed, reason = self._is_path_allowed(p)
            if not allowed:
                return _err(reason, 403)
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
        # Early sandbox check on raw path
        allowed, reason = self._is_path_allowed(Path(path))
        if not allowed:
            return _err(reason, 403)
        try:
            p = self._resolve_path(path)
            # Re-check resolved path
            allowed, reason = self._is_path_allowed(p)
            if not allowed:
                return _err(reason, 403)
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
        # Block dangerous commands (fork bombs, rm -rf /, disk format, etc.)
        is_dangerous, reason = self._is_dangerous_command(command)
        if is_dangerous:
            return _err(
                f"shell.execute blocked: command matches dangerous pattern ({reason}). "
                f"This command could cause irreversible damage.",
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
        #   sudo, /usr/bin/sudo, env sudo, command sudo, pkexec, doas, su
        #   $(sudo ...), bash -c 'sudo ...'
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
            # su with -c flag (privilege escalation)
            if re.match(r"^su\s+(-\w*c|.*-c)", stripped):
                return True
            # su to root (su without username or with "root")
            if re.match(r"^su\s*$", stripped) or re.match(r"^su\s+root\b", stripped):
                return True

        # Check for sudo inside $(...) subshell substitution
        if re.search(r"\$\([^)]*\bsudo\b", command):
            return True

        # Check for sudo inside nested shell invocations:
        # bash -c 'sudo ...', sh -c "sudo ...", python -c "os.system('sudo ...')"
        if re.search(r"(bash|sh|zsh|dash)\s+(-\w*c\s+['\"].*\bsudo\b)", command):
            return True

        return False

    # -- Dangerous command detection for shell.execute --------------------

    # Patterns that indicate destructive or dangerous commands.
    # These are blocked in both shell.execute and terminal.execute.
    _DANGEROUS_COMMAND_PATTERNS: list[tuple[re.Pattern[str], str]] = [
        # Fork bombs
        (re.compile(r":\(\)\s*\{.*\}"), "fork bomb"),
        (re.compile(r"\.\(\)\s*\{.*\}"), "fork bomb"),
        # Destructive rm patterns
        (re.compile(r"\brm\s+(-\w*r\w*f|-\w*f\w*r)\s+/\s*$"), "recursive delete of root"),
        (re.compile(r"\brm\s+(-\w*r\w*f|-\w*f\w*r)\s+/\*"), "recursive delete of root"),
        (re.compile(r"\brm\s+(-\w*r\w*f|-\w*f\w*r)\s+~\s*$"), "recursive delete of home"),
        # Format/wipe disk
        (re.compile(r"\bmkfs\b"), "filesystem format"),
        (re.compile(r"\bdd\s+.*\bof=/dev/"), "raw disk write"),
        # Shutdown/reboot
        (re.compile(r"\b(shutdown|reboot|halt|poweroff|init\s+[06])\b"), "system shutdown/reboot"),
        # Dangerous file overwrites
        (re.compile(r">\s*/dev/sd[a-z]"), "raw device overwrite"),
        (re.compile(r">\s*/etc/(passwd|shadow|sudoers)"), "critical system file overwrite"),
        # Network exfiltration patterns (curl/wget piped to shell)
        (re.compile(r"\b(curl|wget)\b.*\|\s*(ba)?sh\b"), "download-and-execute"),
        # Python/perl one-liners that spawn reverse shells
        (re.compile(r"python[23]?\s+-c\s+.*socket.*connect", re.IGNORECASE), "reverse shell"),
        (re.compile(r"\bnc\s+.*-e\s+/bin/", re.IGNORECASE), "netcat reverse shell"),
        # Crontab manipulation
        (re.compile(r"\bcrontab\s+-r\b"), "crontab removal"),
        # iptables flush (can lock out)
        (re.compile(r"\biptables\s+-F\b"), "firewall flush"),
    ]

    @classmethod
    def _is_dangerous_command(cls, command: str) -> tuple[bool, str]:
        """Check if a shell command matches known dangerous patterns.

        Returns:
            Tuple of (is_dangerous, reason).
        """
        for pattern, reason in cls._DANGEROUS_COMMAND_PATTERNS:
            if pattern.search(command):
                return True, reason
        return False, ""

    def _terminal_execute(
        self, *, command: str, timeout: int = 30, cwd: Optional[str] = None
    ) -> dict[str, Any]:
        """Execute a shell command, rejecting sudo and dangerous commands."""
        if self._contains_sudo(command):
            return _err(
                "terminal.execute forbids sudo and privilege escalation commands. "
                "Use shell.execute if elevated privileges are required.",
                403,
            )
        is_dangerous, reason = self._is_dangerous_command(command)
        if is_dangerous:
            return _err(
                f"terminal.execute blocked: command matches dangerous pattern ({reason}). "
                f"This command could cause irreversible damage.",
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
        import urllib.error
        import urllib.request

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

        self._register(
            "pip.install",
            self._pip_install,
            {
                "type": "object",
                "properties": {
                    "packages": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of pip package specifiers (e.g. ['pandas>=1.0', 'numpy'])",
                    },
                },
                "required": ["packages"],
            },
            "Install Python packages via pip at runtime",
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

    def _code_execute(self, *, code: str, timeout: int = 120) -> dict[str, Any]:
        if not self._code_executor:
            return _err("Code executor not configured", 503)

        # Inject _workspace_dir and _output_dir so executed code can save files.
        # Also inject an _ensure_dir helper so LLM code can create subdirectories
        # without needing to import os.makedirs explicitly.
        preamble = ""
        if self._workflow_dir:
            ws = self._workflow_dir / "workspace"
            ws.mkdir(parents=True, exist_ok=True)
            if self._run_id:
                out = self._workflow_dir / "output" / self._run_id
            else:
                out = self._workflow_dir / "output"
            out.mkdir(parents=True, exist_ok=True)
            # Build a snapshot of all existing files so workers know what's available
            tree_lines = self._snapshot_workspace_tree(ws, out)
            tree_comment = "\n".join(f"# {l}" for l in tree_lines) if tree_lines else "# (empty workspace)"

            preamble = (
                f"import os as _os\n"
                f"import builtins as _builtins\n"
                f"import sys as _sys\n"
                f"_workspace_dir = {str(ws)!r}\n"
                f"_output_dir = {str(out)!r}\n"
                # Mirror as env vars so LLM-written `os.environ['_workspace_dir']`
                # / `os.environ['_output_dir']` patterns also work.
                f"_os.environ['_workspace_dir'] = _workspace_dir\n"
                f"_os.environ['_output_dir'] = _output_dir\n"
                # Inject all known secrets as a `_secrets` dict so plain
                # `code.execute` calls can access API keys via `_secrets.get(...)`
                # without having to wrap them in a dynamic tool first.
                f"_secrets = {dict(self._secrets)!r}\n"
                # Mirror secrets into os.environ as well — many LLM patterns use
                # `os.environ['HF_TOKEN']` directly.
                f"for _k, _v in _secrets.items():\n"
                f"    if _k and _v and _k not in _os.environ:\n"
                f"        _os.environ[_k] = str(_v)\n"
                f"def _ensure_dir(path):\n"
                f"    d = _os.path.dirname(path) if not _os.path.isdir(path) else path\n"
                f"    _os.makedirs(d, exist_ok=True)\n"
                f"    return path\n"
                f"def _output_file(*parts):\n"
                f"    \"\"\"Build a path under _output_dir. Example: _output_file('chart.png')\"\"\"\n"
                f"    return _os.path.join(_output_dir, *parts)\n"
                f"def _input_file(*parts):\n"
                f"    \"\"\"Build a path under _workspace_dir/inputs. Example: _input_file('data.csv')\"\"\"\n"
                f"    return _os.path.join(_workspace_dir, 'inputs', *parts)\n"
                f"def _list_files(directory=None):\n"
                f"    \"\"\"List all files in a directory (defaults to _workspace_dir). Returns list of relative paths.\"\"\"\n"
                f"    base = directory or _workspace_dir\n"
                f"    found = []\n"
                f"    for root, dirs, files in _os.walk(base):\n"
                f"        for f in sorted(files):\n"
                f"            full = _os.path.join(root, f)\n"
                f"            found.append(_os.path.relpath(full, base))\n"
                f"    return found\n"
                f"\n"
                f"# Auto-create parent dirs for writes under _output_dir / _workspace_dir\n"
                f"_orig_open = _builtins.open\n"
                f"def _safe_open(path, mode='r', *args, **kwargs):\n"
                f"    p = str(path)\n"
                f"    if any(m in str(mode) for m in ('w', 'a', 'x')):\n"
                f"        parent = _os.path.dirname(p)\n"
                f"        if parent and not _os.path.isdir(parent):\n"
                f"            _os.makedirs(parent, exist_ok=True)\n"
                f"    return _orig_open(path, mode, *args, **kwargs)\n"
                f"_builtins.open = _safe_open\n"
                f"\n"
                f"# --- Matplotlib safety: auto-install and configure non-interactive backend ---\n"
                f"_AWP_MATPLOTLIB_AVAILABLE = False\n"
                f"try:\n"
                f"    import matplotlib as _mpl\n"
                f"    _mpl.use('Agg')\n"
                f"    _AWP_MATPLOTLIB_AVAILABLE = True\n"
                f"except ImportError:\n"
                f"    # Auto-install matplotlib + reportlab so plots and PDFs work out of the box\n"
                f"    try:\n"
                f"        import subprocess as _sp\n"
                f"        _sp.check_call([_sys.executable, '-m', 'pip', 'install', '-q',\n"
                f"                        'matplotlib', 'reportlab'], stdout=_sp.DEVNULL, stderr=_sp.DEVNULL)\n"
                f"        import matplotlib as _mpl\n"
                f"        _mpl.use('Agg')\n"
                f"        _AWP_MATPLOTLIB_AVAILABLE = True\n"
                f"        print('INFO: Auto-installed matplotlib + reportlab for plotting/PDF support.', file=_sys.stderr)\n"
                f"    except Exception:\n"
                f"        print('WARNING: matplotlib is not installed and auto-install failed. Use pip.install tool.', file=_sys.stderr)\n"
                f"\n"
                f"# --- PNG validation helper: verify saved images are real ---\n"
                f"def _verify_png(path):\n"
                f"    \"\"\"Check if a saved PNG is a real image (not a placeholder). Call after savefig().\"\"\"\n"
                f"    import struct as _struct\n"
                f"    try:\n"
                f"        with open(path, 'rb') as _f:\n"
                f"            _header = _f.read(24)\n"
                f"        if len(_header) < 24:\n"
                f"            print(f'WARNING: {{path}} is too small ({{len(_header)}} bytes) — not a valid PNG', file=_sys.stderr)\n"
                f"            return False\n"
                f"        _w = _struct.unpack('>I', _header[16:20])[0]\n"
                f"        _h = _struct.unpack('>I', _header[20:24])[0]\n"
                f"        _size = _os.path.getsize(path)\n"
                f"        if _w < 10 or _h < 10 or _size < 500:\n"
                f"            print(f'WARNING: {{path}} is {{_w}}x{{_h}} ({{_size}} bytes) — placeholder, not a real chart', file=_sys.stderr)\n"
                f"            return False\n"
                f"        return True\n"
                f"    except Exception as _e:\n"
                f"        print(f'WARNING: Could not verify {{path}}: {{_e}}', file=_sys.stderr)\n"
                f"        return False\n"
                f"\n"
                f"# === WORKSPACE FILE TREE (snapshot at execution time) ===\n"
                f"{tree_comment}\n"
                f"# === END FILE TREE ===\n"
            )

        # Snapshot files before execution so we can detect new/changed files
        from .file_validator import snapshot_file_state, validate_changed_files
        dirs_to_watch = []
        if self._workflow_dir:
            dirs_to_watch = [
                self._workflow_dir / "workspace",
                self._workflow_dir / "output",
            ]
        snapshots_before = {str(d): snapshot_file_state(d) for d in dirs_to_watch}

        result = self._code_executor.execute(preamble + code, timeout=timeout)

        # --- File output validation (Phase 1: immediate feedback) ---
        file_warnings: list[str] = []
        changed_paths: list[Path] = []
        if dirs_to_watch:
            from .file_validator import (
                build_repair_instructions,
                classify_warning_severity,
                find_changed_files,
            )
            snapshots_after = {str(d): snapshot_file_state(d) for d in dirs_to_watch}
            for d_str in snapshots_before:
                w = validate_changed_files(snapshots_before[d_str], snapshots_after[d_str])
                file_warnings.extend(w)
                changed_paths.extend(
                    find_changed_files(snapshots_before[d_str], snapshots_after[d_str])
                )

        if file_warnings:
            # Build structured repair instructions with severity levels
            warning_pairs = []
            has_critical = False
            for p in changed_paths:
                from .file_validator import validate_file
                w = validate_file(p)
                if w:
                    warning_pairs.append((p, w))
                    severity = classify_warning_severity(p, w)
                    if severity == "critical":
                        has_critical = True

            repair_instructions = build_repair_instructions(warning_pairs)
            warning_block = (
                "\n\n⚠ OUTPUT FILE VALIDATION WARNINGS:\n"
                + "\n".join(f"  - {w}" for w in file_warnings)
                + "\n\n" + repair_instructions
            )

            if has_critical:
                warning_block += (
                    "\n\n🛑 STOP: You have CRITICAL file errors. "
                    "Do NOT proceed to the next task. Fix these files FIRST by "
                    "re-running the code that generates them. "
                    "Common fix pattern:\n"
                    "1. Ensure matplotlib is installed: pip.install(packages=['matplotlib'])\n"
                    "2. Import and configure: import matplotlib; matplotlib.use('Agg')\n"
                    "3. Plot REAL data (not empty): plt.plot(x_data, y_data)\n"
                    "4. Save: plt.savefig(path, dpi=150, bbox_inches='tight')\n"
                    "5. Close: plt.close()\n"
                    "NEVER write base64 placeholder images as a fallback."
                )

            if result["ok"]:
                # Attach file warnings to stdout so the LLM sees them,
                # but do NOT flip ok to False.  Forcing failure caused
                # workers to burn tool-call rounds on retries for
                # legitimately small output files (scatter plots, summary
                # CSVs, etc.).  The LLM can still read the warnings and
                # self-correct if it deems them actionable.
                data = result.get("data", {})
                stdout = data.get("stdout", "") if isinstance(data, dict) else ""
                if isinstance(data, dict):
                    data["stdout"] = stdout + warning_block
                    result["data"] = data
                result["_file_warnings"] = file_warnings
                result["_has_critical_file_errors"] = has_critical
            else:
                # Append to error so even failed executions report file issues
                result["error"] = (result.get("error") or "") + warning_block
                result["_file_warnings"] = file_warnings
                result["_has_critical_file_errors"] = has_critical

        # Enhance error messages with actionable hints so the LLM can self-correct
        if not result["ok"]:
            error = result.get("error", "")
            stderr = result.get("data", {}).get("stderr", "")
            error_text = error or stderr

            hints: list[str] = []

            # Detect missing packages and hint at pip.install
            if "ModuleNotFoundError" in error_text or "ImportError" in error_text:
                # Extract module name from error
                import re
                m = re.search(r"No module named ['\"]([^'\"]+)['\"]", error_text)
                module = m.group(1).split(".")[0] if m else "the_package"
                hints.append(
                    f"HINT: Use the pip.install tool to install missing packages "
                    f"before retrying. Example: pip.install(packages=[\"{module}\"])"
                )

            # Detect common syntax patterns
            if "SyntaxError" in error_text:
                hints.append(
                    "HINT: Check for unescaped quotes, missing colons, or "
                    "indentation errors in the code string."
                )

            # Detect NameError for common sandbox variables
            if "NameError" in error_text:
                if "_workspace_dir" in error_text or "_output_dir" in error_text:
                    hints.append(
                        "HINT: _workspace_dir and _output_dir are pre-defined variables. "
                        "Use them directly — do not redefine them."
                    )
                if "_secrets" in error_text:
                    hints.append(
                        "HINT: _secrets is only available in dynamic tools, "
                        "not in direct code.execute calls."
                    )

            # Detect file not found
            if "FileNotFoundError" in error_text or "No such file or directory" in error_text:
                hints.append(
                    "HINT: Use _workspace_dir + \"/inputs/FILENAME\" for input files "
                    "and _output_dir + \"/FILENAME\" for output files. "
                    "Call _list_files() to see all available files in the workspace, "
                    "or _list_files(_output_dir) for output files. "
                    "Use _ensure_dir(path) before writing to subdirectories."
                )

            if hints:
                result["error"] = error_text + "\n\n" + "\n".join(hints)

        return result

    @staticmethod
    def _snapshot_workspace_tree(
        workspace: Path, output: Path, max_files: int = 80
    ) -> list[str]:
        """Build a compact directory tree of workspace + output for the preamble.

        Returns lines like:
            _workspace_dir/
              inputs/
                data.csv  (12.3 KB)
              context/
            _output_dir/
              chart.png  (45.1 KB)
        """
        lines: list[str] = []
        count = 0

        def _walk(base: Path, label: str, indent: int = 0) -> None:
            nonlocal count
            if count >= max_files:
                return
            prefix = "  " * indent
            lines.append(f"{prefix}{label}/")
            if not base.exists():
                return
            try:
                entries = sorted(base.iterdir(), key=lambda p: (p.is_file(), p.name))
            except OSError:
                return
            for entry in entries:
                if count >= max_files:
                    lines.append(f"{prefix}  ... (truncated)")
                    return
                if entry.name.startswith(".") or entry.name == "__pycache__":
                    continue
                if entry.is_dir():
                    _walk(entry, entry.name, indent + 1)
                else:
                    size = entry.stat().st_size
                    if size < 1024:
                        size_str = f"{size} B"
                    elif size < 1024 * 1024:
                        size_str = f"{size / 1024:.1f} KB"
                    else:
                        size_str = f"{size / (1024 * 1024):.1f} MB"
                    lines.append(f"{prefix}  {entry.name}  ({size_str})")
                    count += 1

        _walk(workspace, "_workspace_dir")
        _walk(output, "_output_dir")
        return lines

    def _pip_install(self, *, packages: list[str]) -> dict[str, Any]:
        if not self._code_executor:
            return _err("Code executor not configured", 503)
        return self._code_executor.install_runtime_packages(packages)

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
