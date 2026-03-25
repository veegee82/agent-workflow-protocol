"""AWP Dynamic Tool Factory -- Runtime tool creation via Code Mode.

Enables agents to create, register, and manage MCP tools at runtime
through the Code Mode SDK. Tools are validated via AST, wrapped in
sandboxed executors, and registered in the shared ToolRegistry.

All dynamic tools follow the standard AWP tool contract (CT1-CT9)
plus additional dynamic tool rules (DT1-DT8).
"""

from __future__ import annotations

import ast
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Modules that dynamic tool code MUST NOT import
DENIED_IMPORTS = frozenset({
    "os", "subprocess", "sys", "shutil", "socket", "signal",
    "ctypes", "importlib", "pathlib", "glob", "tempfile",
    "multiprocessing", "threading", "asyncio",
    "http", "urllib", "requests", "httpx",
})

# Reserved namespaces (from Layer 2, Section 4.2)
RESERVED_NAMESPACES = frozenset({
    "web", "http", "file", "shell", "agent", "memory", "arithmetic",
    "numpy", "matplot", "pandas", "doc", "sklearn", "code", "tools",
})


def _ok(data: Any, log: str = "") -> dict[str, Any]:
    return {"ok": True, "status": 200, "data": data, "error": None, "log": log}


def _err(msg: str, status: int = 500) -> dict[str, Any]:
    return {"ok": False, "status": status, "data": {}, "error": msg, "log": ""}


class DynamicToolRecord:
    """Metadata about a dynamically created tool."""

    __slots__ = ("fqn", "creator_agent", "created_at", "code", "parameters",
                 "description", "meta")

    def __init__(
        self,
        fqn: str,
        creator_agent: str,
        code: str,
        parameters: dict[str, Any],
        description: str,
        meta: Optional[dict[str, Any]] = None,
    ) -> None:
        self.fqn = fqn
        self.creator_agent = creator_agent
        self.created_at = datetime.now(timezone.utc).isoformat()
        self.code = code
        self.parameters = parameters
        self.description = description
        self.meta = meta or {}

    def to_dict(self) -> dict[str, Any]:
        return {
            "fqn": self.fqn,
            "description": self.description,
            "parameters": self.parameters,
            "code": self.code,
            "meta": self.meta,
            "provenance": {
                "creator_agent": self.creator_agent,
                "created_at": self.created_at,
            },
        }


class DynamicToolFactory:
    """Creates, validates, and registers tools at runtime.

    Args:
        registry: Shared ToolRegistry instance.
        code_executor: CodeExecutor for sandboxed dynamic tool invocation.
        config: ``dynamic_tools`` section from workflow manifest (or empty dict).
        workflow_dir: Workflow root directory (for persistence).
    """

    def __init__(
        self,
        registry: Any,  # ToolRegistry (avoid circular import)
        code_executor: Any,  # CodeExecutor
        config: Optional[Any] = None,
        workflow_dir: Optional[Path] = None,
    ) -> None:
        self._registry = registry
        self._executor = code_executor
        self._workflow_dir = workflow_dir
        self._records: dict[str, DynamicToolRecord] = {}
        self._agent_counts: dict[str, int] = {}

        # Extract config values
        if config is None:
            self._enabled = False
            self._persist = False
            self._max_total = 50
            self._allowed_namespaces = ["dynamic"]
            self._code_review = False
        else:
            self._enabled = getattr(config, "enabled", False) if hasattr(config, "enabled") else config.get("enabled", False)
            self._persist = getattr(config, "persist", False) if hasattr(config, "persist") else config.get("persist", False)
            self._max_total = getattr(config, "max_total", 50) if hasattr(config, "max_total") else config.get("max_total", 50)
            ns = getattr(config, "allowed_namespaces", None) if hasattr(config, "allowed_namespaces") else config.get("allowed_namespaces", None)
            self._allowed_namespaces = ns if ns else ["dynamic"]
            self._code_review = getattr(config, "code_review", False) if hasattr(config, "code_review") else config.get("code_review", False)

        # Load persisted tools on init
        if self._persist and self._workflow_dir:
            self._load_persisted_tools()

    @property
    def enabled(self) -> bool:
        return self._enabled

    def create_tool(
        self,
        name: str,
        description: str,
        parameters: dict[str, Any],
        code: str,
        creator_agent: str,
        max_tools: int = 10,
        allowed_namespace: str = "dynamic",
        meta: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Validate, wrap, and register a dynamic tool.

        Args:
            name: Fully qualified name (namespace.action).
            description: Human-readable tool description.
            parameters: JSON Schema for tool parameters.
            code: Python code string containing ``def handler(*, ...)``.
            creator_agent: ID of the agent creating this tool.
            max_tools: Per-agent tool creation limit.
            allowed_namespace: Namespace this agent is allowed to use.
            meta: Optional tool metadata.

        Returns:
            Standard AWP result format.
        """
        if not self._enabled:
            return _err("Dynamic tool creation is not enabled", 403)

        # DT1: Validate FQN format
        if "." not in name:
            return _err(f"Invalid tool name '{name}': must be namespace.action format", 400)

        namespace = name.split(".")[0]

        # DT2: Check reserved namespaces
        if namespace in RESERVED_NAMESPACES:
            return _err(f"Namespace '{namespace}' is reserved", 403)

        # Check allowed namespaces (workflow-level)
        if namespace not in self._allowed_namespaces:
            return _err(
                f"Namespace '{namespace}' not in allowed namespaces: {self._allowed_namespaces}",
                403,
            )

        # Check agent's declared namespace
        if namespace != allowed_namespace and allowed_namespace != "*":
            return _err(
                f"Agent '{creator_agent}' can only create tools in namespace '{allowed_namespace}', "
                f"not '{namespace}'",
                403,
            )

        # DT8: Check uniqueness
        if name in self._registry._tools:
            return _err(f"Tool '{name}' already exists", 409)

        # Check per-agent limit
        count = self._agent_counts.get(creator_agent, 0)
        if count >= max_tools:
            return _err(
                f"Agent '{creator_agent}' has reached its tool creation limit ({max_tools})",
                429,
            )

        # Check global limit
        if len(self._records) >= self._max_total:
            return _err(
                f"Global dynamic tool limit reached ({self._max_total})",
                429,
            )

        # DT4: Validate code via AST
        validation = self.validate_code(code)
        if not validation["ok"]:
            return validation

        # Code review logging
        if self._code_review:
            logger.info(
                "Dynamic tool code review [%s by %s]:\n%s",
                name, creator_agent, code,
            )

        # Create sandboxed wrapper function
        tool_fn = self._make_sandboxed_tool(code, name)

        # Register in ToolRegistry
        self._registry.register_dynamic(
            name, tool_fn, parameters, description, creator_agent,
        )

        # Track the record
        record = DynamicToolRecord(
            fqn=name,
            creator_agent=creator_agent,
            code=code,
            parameters=parameters,
            description=description,
            meta=meta,
        )
        self._records[name] = record
        self._agent_counts[creator_agent] = count + 1

        # Persist if enabled
        if self._persist and self._workflow_dir:
            self._persist_tool(record)

        logger.info("Dynamic tool created: %s (by %s)", name, creator_agent)
        return _ok({"name": name, "registered": True})

    def remove_tool(self, name: str, requester_agent: str) -> dict[str, Any]:
        """Remove a dynamic tool. Only the creator may remove it.

        Args:
            name: Tool FQN to remove.
            requester_agent: Agent requesting removal.

        Returns:
            Standard AWP result format.
        """
        record = self._records.get(name)
        if record is None:
            return _err(f"Dynamic tool not found: {name}", 404)

        if record.creator_agent != requester_agent:
            return _err(
                f"Agent '{requester_agent}' cannot remove tool created by '{record.creator_agent}'",
                403,
            )

        # Unregister from ToolRegistry
        self._registry.unregister(name)
        del self._records[name]
        self._agent_counts[record.creator_agent] = max(
            0, self._agent_counts.get(record.creator_agent, 1) - 1,
        )

        # Remove persisted file
        if self._persist and self._workflow_dir:
            persist_path = self._workflow_dir / "workspace" / "dynamic_tools" / f"{name}.json"
            persist_path.unlink(missing_ok=True)

        logger.info("Dynamic tool removed: %s (by %s)", name, requester_agent)
        return _ok({"name": name, "unregistered": True})

    def list_tools(self, namespace: Optional[str] = None) -> dict[str, Any]:
        """List all dynamic tools, optionally filtered by namespace.

        Args:
            namespace: Optional namespace filter.

        Returns:
            Standard AWP result format with tool list.
        """
        tools = []
        for fqn, record in self._records.items():
            if namespace and not fqn.startswith(f"{namespace}."):
                continue
            tools.append({
                "name": record.fqn,
                "description": record.description,
                "creator": record.creator_agent,
                "created_at": record.created_at,
            })
        return _ok({"tools": tools, "count": len(tools)})

    def cleanup(self) -> None:
        """Remove all dynamic tools. Called at workflow completion."""
        for name in list(self._records.keys()):
            self._registry.unregister(name)
        self._records.clear()
        self._agent_counts.clear()
        logger.info("Dynamic tools cleaned up")

    def validate_code(self, code: str) -> dict[str, Any]:
        """Validate Python code via AST without executing it.

        Checks:
        1. Syntax validity
        2. No denied imports
        3. Contains exactly one ``def handler(*, ...)`` function

        Args:
            code: Python source code string.

        Returns:
            Standard AWP result format.
        """
        # Parse
        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            return _err(f"Syntax error in tool code: {e}", 400)

        # Check for denied imports
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root_module = alias.name.split(".")[0]
                    if root_module in DENIED_IMPORTS:
                        return _err(
                            f"Import of '{alias.name}' is not allowed in dynamic tool code",
                            403,
                        )
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    root_module = node.module.split(".")[0]
                    if root_module in DENIED_IMPORTS:
                        return _err(
                            f"Import from '{node.module}' is not allowed in dynamic tool code",
                            403,
                        )

        # Check for handler function
        handlers = []
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name == "handler":
                    handlers.append(node)

        if len(handlers) == 0:
            return _err(
                "Tool code must contain a 'def handler(*, ...)' function",
                400,
            )
        if len(handlers) > 1:
            return _err(
                "Tool code must contain exactly one 'handler' function",
                400,
            )

        return _ok({"valid": True})

    def _make_sandboxed_tool(self, code: str, fqn: str) -> Any:
        """Create a callable that executes tool code in a subprocess sandbox.

        Each invocation spawns a fresh subprocess for isolation.

        Args:
            code: Python code string with ``def handler(*, ...)``.
            fqn: Tool FQN (for error messages).

        Returns:
            A callable matching the ToolFunc signature.
        """
        executor = self._executor

        def tool_fn(**kwargs: Any) -> dict[str, Any]:
            # Remove _secrets (dynamic tools don't get secrets - proxy pattern)
            kwargs.pop("_secrets", None)

            # Build execution script
            args_json = json.dumps(kwargs)
            script = (
                f"import json\n"
                f"{code}\n"
                f"_args = json.loads({json.dumps(args_json)})\n"
                f"_result = handler(**_args)\n"
                f"print(json.dumps(_result))\n"
            )

            exec_result = executor.execute(script, timeout=30)

            if exec_result["ok"]:
                stdout = exec_result["data"]["stdout"].strip()
                if stdout:
                    try:
                        return json.loads(stdout)
                    except json.JSONDecodeError:
                        return _err(
                            f"Dynamic tool '{fqn}' returned invalid JSON: {stdout[:200]}",
                        )
                return _err(f"Dynamic tool '{fqn}' produced no output")
            return _err(
                exec_result.get("error", f"Dynamic tool '{fqn}' execution failed"),
            )

        return tool_fn

    def _persist_tool(self, record: DynamicToolRecord) -> None:
        """Save tool definition as JSON manifest to workspace/dynamic_tools/."""
        if not self._workflow_dir:
            return
        persist_dir = self._workflow_dir / "workspace" / "dynamic_tools"
        persist_dir.mkdir(parents=True, exist_ok=True)
        persist_path = persist_dir / f"{record.fqn}.json"
        persist_path.write_text(
            json.dumps(record.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        logger.debug("Persisted dynamic tool: %s", persist_path)

    def _load_persisted_tools(self) -> None:
        """Load previously persisted dynamic tools from workspace/dynamic_tools/."""
        if not self._workflow_dir:
            return
        persist_dir = self._workflow_dir / "workspace" / "dynamic_tools"
        if not persist_dir.exists():
            return

        for json_file in sorted(persist_dir.glob("*.json")):
            try:
                data = json.loads(json_file.read_text(encoding="utf-8"))
                fqn = data["fqn"]

                # Skip if already registered
                if fqn in self._registry._tools:
                    continue

                # Validate code
                validation = self.validate_code(data["code"])
                if not validation["ok"]:
                    logger.warning("Skipping persisted tool %s: %s", fqn, validation["error"])
                    continue

                # Register
                tool_fn = self._make_sandboxed_tool(data["code"], fqn)
                creator = data.get("provenance", {}).get("creator_agent", "persisted")
                self._registry.register_dynamic(
                    fqn, tool_fn, data["parameters"], data["description"], creator,
                )
                self._records[fqn] = DynamicToolRecord(
                    fqn=fqn,
                    creator_agent=creator,
                    code=data["code"],
                    parameters=data["parameters"],
                    description=data["description"],
                    meta=data.get("meta"),
                )
                logger.info("Loaded persisted dynamic tool: %s", fqn)

            except Exception as exc:
                logger.warning("Failed to load persisted tool %s: %s", json_file.name, exc)
