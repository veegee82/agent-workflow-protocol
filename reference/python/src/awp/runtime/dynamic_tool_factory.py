"""AWP Dynamic Tool Factory -- Runtime tool creation via Code Mode.

Enables agents to create, register, and manage MCP tools at runtime
through the Code Mode SDK. Tools are validated via AST, wrapped in
sandboxed executors, and registered in the shared ToolRegistry.

All dynamic tools follow the standard AWP tool contract (CT1-CT9)
plus additional dynamic tool rules (DT1-DT8).

Namespace Capabilities (NC1-NC3):
    NC1: Capabilities are declared by the workflow author in YAML, not by agents.
    NC2: Per-namespace import policies are derived from declared capabilities.
    NC3: ALWAYS_DENIED imports cannot be unlocked by any capability.
"""

from __future__ import annotations

import ast
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Imports that are NEVER allowed, regardless of namespace capabilities.
# These provide arbitrary code execution, privilege escalation, or process
# control that cannot be safely sandboxed.
# ---------------------------------------------------------------------------
ALWAYS_DENIED: frozenset[str] = frozenset(
    {
        "os",
        "subprocess",
        "sys",
        "ctypes",
        "importlib",
        "signal",
        "multiprocessing",
    }
)

# ---------------------------------------------------------------------------
# Capability-gated import groups.
# Each capability unlocks a set of imports that would otherwise be denied.
# ---------------------------------------------------------------------------
NETWORK_IMPORTS: frozenset[str] = frozenset(
    {"socket", "http", "urllib", "requests", "httpx", "asyncio"}
)

FILESYSTEM_IMPORTS: frozenset[str] = frozenset(
    {"pathlib", "glob", "shutil", "tempfile"}
)

THREADING_IMPORTS: frozenset[str] = frozenset(
    {"threading", "asyncio"}
)

# Per-sandbox-type import policies (backward-compatible).
# Docker allows most imports since code runs in a disposable container.
# Venv is intermediate -- allows filesystem but blocks system/network.
# Subprocess is the most restrictive (original default).
IMPORT_POLICIES: dict[str, frozenset[str]] = {
    "subprocess": frozenset(
        {
            "os",
            "subprocess",
            "sys",
            "shutil",
            "socket",
            "signal",
            "ctypes",
            "importlib",
            "pathlib",
            "glob",
            "tempfile",
            "multiprocessing",
            "threading",
            "asyncio",
            "http",
            "urllib",
            "requests",
            "httpx",
        }
    ),
    "venv": frozenset(
        {
            "os",
            "subprocess",
            "sys",
            "shutil",
            "socket",
            "signal",
            "ctypes",
            "importlib",
            "multiprocessing",
        }
    ),
    "docker": frozenset(
        {
            "ctypes",
            "signal",
        }
    ),
    "none": frozenset(),
}

# Backward-compatible alias
DENIED_IMPORTS = IMPORT_POLICIES["subprocess"]


def _denied_for_capabilities(
    capabilities: list[str],
    sandbox_type: str = "subprocess",
) -> frozenset[str]:
    """Compute the denied-import set for a given list of capabilities.

    Starts from the sandbox-type baseline, then removes imports that are
    unlocked by the declared capabilities.  ALWAYS_DENIED imports can
    never be removed.

    Args:
        capabilities: List of capability names (e.g. ["compute", "network"]).
        sandbox_type: Sandbox type for the baseline policy.

    Returns:
        Frozenset of denied module names.
    """
    baseline = set(IMPORT_POLICIES.get(sandbox_type, IMPORT_POLICIES["subprocess"]))

    if "network" in capabilities:
        baseline -= NETWORK_IMPORTS
    if "filesystem" in capabilities:
        baseline -= FILESYSTEM_IMPORTS

    # Re-add ALWAYS_DENIED — these can never be unlocked.
    baseline |= ALWAYS_DENIED

    return frozenset(baseline)

# Reserved namespaces (from Layer 2, Section 4.2)
RESERVED_NAMESPACES = frozenset(
    {
        "web",
        "http",
        "file",
        "shell",
        "agent",
        "memory",
        "arithmetic",
        "numpy",
        "matplot",
        "pandas",
        "doc",
        "sklearn",
        "code",
        "tools",
    }
)


def _ok(data: Any, log: str = "") -> dict[str, Any]:
    return {"ok": True, "status": 200, "data": data, "error": None, "log": log}


def _err(msg: str, status: int = 500) -> dict[str, Any]:
    return {"ok": False, "status": status, "data": {}, "error": msg, "log": ""}


class DynamicToolRecord:
    """Metadata about a dynamically created tool."""

    __slots__ = (
        "fqn",
        "creator_agent",
        "created_at",
        "code",
        "parameters",
        "description",
        "meta",
        "required_secrets",
    )

    def __init__(
        self,
        fqn: str,
        creator_agent: str,
        code: str,
        parameters: dict[str, Any],
        description: str,
        meta: Optional[dict[str, Any]] = None,
        required_secrets: Optional[list[str]] = None,
    ) -> None:
        self.fqn = fqn
        self.creator_agent = creator_agent
        self.created_at = datetime.now(timezone.utc).isoformat()
        self.code = code
        self.parameters = parameters
        self.description = description
        self.meta = meta or {}
        self.required_secrets = required_secrets or []

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
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
        if self.required_secrets:
            d["required_secrets"] = self.required_secrets
        return d


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
        code_executor: Any,  # CodeExecutor / BaseExecutor
        config: Optional[Any] = None,
        workflow_dir: Optional[Path] = None,
        sandbox_type: str = "subprocess",
    ) -> None:
        self._registry = registry
        self._executor = code_executor
        self._workflow_dir = workflow_dir
        self._records: dict[str, DynamicToolRecord] = {}
        self._agent_counts: dict[str, int] = {}
        self._sandbox_type = sandbox_type
        # Backward-compatible global denied imports (used when no namespace
        # capabilities are configured).
        self._denied_imports = IMPORT_POLICIES.get(sandbox_type, DENIED_IMPORTS)

        # Per-namespace capability configs: name -> {"capabilities": [...], ...}
        self._namespace_configs: dict[str, dict[str, Any]] = {}

        # Extract config values
        if config is None:
            self._enabled = False
            self._persist = False
            self._max_total = 50
            self._allowed_namespaces = ["dynamic"]
            self._code_review = False
        else:
            self._enabled = (
                getattr(config, "enabled", False)
                if hasattr(config, "enabled")
                else config.get("enabled", False)
            )
            self._persist = (
                getattr(config, "persist", False)
                if hasattr(config, "persist")
                else config.get("persist", False)
            )
            self._max_total = (
                getattr(config, "max_total", 50)
                if hasattr(config, "max_total")
                else config.get("max_total", 50)
            )
            ns = (
                getattr(config, "allowed_namespaces", None)
                if hasattr(config, "allowed_namespaces")
                else config.get("allowed_namespaces", None)
            )
            raw_namespaces = ns if ns else ["dynamic"]

            # Parse allowed_namespaces: supports both plain strings and
            # NamespaceCapability objects/dicts with per-namespace capabilities.
            self._allowed_namespaces = []
            for entry in raw_namespaces:
                if isinstance(entry, str):
                    self._allowed_namespaces.append(entry)
                elif isinstance(entry, dict):
                    name = entry.get("name", "")
                    if name:
                        self._allowed_namespaces.append(name)
                        self._namespace_configs[name] = entry
                elif hasattr(entry, "name"):
                    # Pydantic NamespaceCapability model
                    self._allowed_namespaces.append(entry.name)
                    self._namespace_configs[entry.name] = {
                        "name": entry.name,
                        "capabilities": getattr(entry, "capabilities", ["compute"]),
                        "network_allowlist": getattr(
                            entry, "network_allowlist", []
                        ),
                    }

            self._code_review = (
                getattr(config, "code_review", False)
                if hasattr(config, "code_review")
                else config.get("code_review", False)
            )

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
        required_secrets: Optional[list[str]] = None,
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
            required_secrets: List of secret key names the tool needs at
                runtime (e.g. ``["OPENAI_API_KEY", "GITHUB_TOKEN"]``).
                Values are injected into the sandbox as ``_secrets`` dict.
                Only keys that actually exist in the registry are passed.

        Returns:
            Standard AWP result format.
        """
        if not self._enabled:
            return _err("Dynamic tool creation is not enabled", 403)

        # DT1: Validate FQN format
        if "." not in name:
            return _err(
                f"Invalid tool name '{name}': must be namespace.action format", 400
            )

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
                f"Agent '{creator_agent}' can only create tools in "
                f"namespace '{allowed_namespace}', not '{namespace}'",
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

        # DT4: Validate code via AST (namespace-aware policy)
        validation = self.validate_code(code, namespace=namespace)
        if not validation["ok"]:
            return validation

        # Code review logging
        if self._code_review:
            logger.info(
                "Dynamic tool code review [%s by %s]:\n%s",
                name,
                creator_agent,
                code,
            )

        secrets_list = required_secrets or []

        # Log secret binding
        if secrets_list:
            available = [
                k for k in secrets_list if k in (self._registry._secrets or {})
            ]
            missing = [
                k for k in secrets_list if k not in (self._registry._secrets or {})
            ]
            logger.info(
                "Dynamic tool %s requests secrets: %s (available: %s, missing: %s)",
                name,
                secrets_list,
                available,
                missing,
            )

        # Create sandboxed wrapper function (with secret injection support)
        tool_fn = self._make_sandboxed_tool(code, name, secrets_list)

        # Register in ToolRegistry (with secret keys so call() injects _secrets)
        self._registry.register_dynamic(
            name,
            tool_fn,
            parameters,
            description,
            creator_agent,
            secrets_keys=secrets_list if secrets_list else None,
        )

        # Track the record
        record = DynamicToolRecord(
            fqn=name,
            creator_agent=creator_agent,
            code=code,
            parameters=parameters,
            description=description,
            meta=meta,
            required_secrets=secrets_list,
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
            0,
            self._agent_counts.get(record.creator_agent, 1) - 1,
        )

        # Remove persisted file
        if self._persist and self._workflow_dir:
            persist_path = (
                self._workflow_dir / "workspace" / "dynamic_tools" / f"{name}.json"
            )
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
            tools.append(
                {
                    "name": record.fqn,
                    "description": record.description,
                    "creator": record.creator_agent,
                    "created_at": record.created_at,
                }
            )
        return _ok({"tools": tools, "count": len(tools)})

    def cleanup(self) -> None:
        """Remove all dynamic tools. Called at workflow completion."""
        for name in list(self._records.keys()):
            self._registry.unregister(name)
        self._records.clear()
        self._agent_counts.clear()
        logger.info("Dynamic tools cleaned up")

    def _get_denied_for_namespace(self, namespace: Optional[str] = None) -> frozenset[str]:
        """Return the denied-import set for a namespace.

        If the namespace has declared capabilities, compute a custom policy.
        Otherwise fall back to the global sandbox-type policy.
        """
        if namespace and namespace in self._namespace_configs:
            caps = self._namespace_configs[namespace].get("capabilities", ["compute"])
            return _denied_for_capabilities(caps, self._sandbox_type)
        return self._denied_imports

    def get_namespace_capabilities(self, namespace: str) -> list[str]:
        """Return the declared capabilities for a namespace."""
        if namespace in self._namespace_configs:
            return list(self._namespace_configs[namespace].get("capabilities", ["compute"]))
        return ["compute"]

    def get_network_allowlist(self, namespace: str) -> list[str]:
        """Return the network allowlist for a namespace (empty = unrestricted)."""
        if namespace in self._namespace_configs:
            return list(self._namespace_configs[namespace].get("network_allowlist", []))
        return []

    def validate_code(self, code: str, namespace: Optional[str] = None) -> dict[str, Any]:
        """Validate Python code via AST without executing it.

        Checks:
        1. Syntax validity
        2. No denied imports (namespace-capability-aware)
        3. Contains exactly one ``def handler(*, ...)`` function

        Args:
            code: Python source code string.
            namespace: Optional namespace for per-namespace capability policy.

        Returns:
            Standard AWP result format.
        """
        # Parse
        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            return _err(f"Syntax error in tool code: {e}", 400)

        # Check for denied imports (namespace-capability-aware policy)
        denied = self._get_denied_for_namespace(namespace)
        caps_info = ""
        if namespace and namespace in self._namespace_configs:
            caps = self._namespace_configs[namespace].get("capabilities", ["compute"])
            caps_info = f", capabilities: {caps}"
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root_module = alias.name.split(".")[0]
                    if root_module in denied:
                        return _err(
                            f"Import of '{alias.name}' is not allowed in dynamic tool code "
                            f"(sandbox type: {self._sandbox_type}{caps_info})",
                            403,
                        )
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    root_module = node.module.split(".")[0]
                    if root_module in denied:
                        return _err(
                            f"Import from '{node.module}' is not allowed in dynamic tool code "
                            f"(sandbox type: {self._sandbox_type}{caps_info})",
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

        # Validate handler signature: must use keyword-only arguments (after *)
        handler_node = handlers[0]
        args = handler_node.args

        # Check for positional args (should have none, or only after *)
        has_kw_only = bool(args.kwonlyargs)
        has_var_keyword = args.kwarg is not None  # **kwargs
        has_positional = bool(args.args)

        if has_positional and not has_kw_only and not has_var_keyword:
            return _err(
                "Handler must use keyword-only arguments: 'def handler(*, arg1, arg2)'. "
                "Found positional arguments instead. Add '*' before parameters.",
                400,
            )

        if not has_kw_only and not has_var_keyword:
            # handler() with no args at all — warn but allow (may be a no-arg tool)
            logger.warning(
                "Handler has no parameters — tool will ignore all inputs"
            )

        # Check handler has a return statement (common LLM mistake: forgetting return)
        has_return = False
        for node in ast.walk(handler_node):
            if isinstance(node, ast.Return) and node.value is not None:
                has_return = True
                break
        if not has_return:
            return _err(
                "Handler function must have a return statement that returns a dict. "
                "Expected: return {\"ok\": True, \"status\": 200, \"data\": {...}, \"error\": None}",
                400,
            )

        return _ok({"valid": True})

    def _make_sandboxed_tool(
        self, code: str, fqn: str, required_secrets: Optional[list[str]] = None
    ) -> Any:
        """Create a callable that executes tool code in a subprocess sandbox.

        Each invocation spawns a fresh subprocess for isolation.  If the tool
        declared ``required_secrets``, the matching values from the registry
        are injected into the sandbox script as a ``_secrets`` dict so the
        handler can access them via ``_secrets["KEY_NAME"]``.

        Args:
            code: Python code string with ``def handler(*, ...)``.
            fqn: Tool FQN (for error messages).
            required_secrets: Secret key names the tool declared.

        Returns:
            A callable matching the ToolFunc signature.
        """
        executor = self._executor
        _required = required_secrets or []
        _workflow_dir = self._workflow_dir
        _registry = self._registry

        def tool_fn(**kwargs: Any) -> dict[str, Any]:
            # Extract _secrets injected by ToolRegistry.call() and remove
            # from kwargs (handler doesn't receive them as a kwarg —
            # they are injected as a top-level variable in the script).
            injected_secrets: dict[str, str] = kwargs.pop("_secrets", None) or {}

            # Build execution script
            args_json = json.dumps(kwargs)

            # Inject secrets as a dedicated variable in the sandbox.
            # Only the keys declared by the tool and actually present
            # in the registry are passed — never the full secret store.
            secrets_json = json.dumps(injected_secrets)

            # Resolve workspace and output directories so tool code can
            # write files (PNGs, CSVs, JSONs, …) to disk.
            workspace_dir = ""
            output_dir = ""
            if _workflow_dir:
                ws = _workflow_dir / "workspace"
                ws.mkdir(parents=True, exist_ok=True)
                workspace_dir = str(ws)
                _run_id = getattr(_registry, "_run_id", "") if _registry else ""
                if _run_id:
                    out = _workflow_dir / "output" / _run_id
                else:
                    out = _workflow_dir / "output"
                out.mkdir(parents=True, exist_ok=True)
                output_dir = str(out)

            script = (
                f"import json\n"
                f"_secrets = json.loads({json.dumps(secrets_json)})\n"
                f"_workspace_dir = {json.dumps(workspace_dir)}\n"
                f"_output_dir = {json.dumps(output_dir)}\n"
                f"{code}\n"
                f"_args = json.loads({json.dumps(args_json)})\n"
                f"_result = handler(**_args)\n"
                f"print(json.dumps(_result))\n"
            )

            if _required:
                logger.debug(
                    "Dynamic tool %s executing with secrets: %s",
                    fqn,
                    list(injected_secrets.keys()),
                )

            exec_result = executor.execute(script, timeout=10000)

            if exec_result["ok"]:
                stdout = exec_result["data"]["stdout"].strip()
                stderr = exec_result["data"].get("stderr", "").strip()
                if stdout:
                    # Take only the last line as JSON output — handler may
                    # print debug info before the final json.dumps() line.
                    lines = stdout.strip().split("\n")
                    json_line = lines[-1]
                    try:
                        return json.loads(json_line)
                    except json.JSONDecodeError:
                        # Fall back to trying the full stdout
                        try:
                            return json.loads(stdout)
                        except json.JSONDecodeError:
                            return _err(
                                f"Dynamic tool '{fqn}' returned invalid JSON. "
                                f"Last line: {json_line[:200]}. "
                                f"Handler must return a dict via: "
                                f'return {{"ok": True, "status": 200, "data": {{}}, "error": None}}',
                            )
                # No stdout but success exit code — handler forgot to return
                return _err(
                    f"Dynamic tool '{fqn}' produced no output. "
                    f"Ensure handler() returns a dict and the script ends with "
                    f"print(json.dumps(result))."
                    + (f" stderr: {stderr[:500]}" if stderr else ""),
                )
            # Execution failed — include stderr for debugging
            error = exec_result.get("error", "")
            stderr = exec_result.get("data", {}).get("stderr", "")
            return _err(
                f"Dynamic tool '{fqn}' execution failed: {error}"
                + (f"\nstderr: {stderr[:1000]}" if stderr and stderr not in error else ""),
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
                    logger.warning(
                        "Skipping persisted tool %s: %s", fqn, validation["error"]
                    )
                    continue

                # Register (with secret keys if persisted)
                persisted_secrets = data.get("required_secrets", [])
                tool_fn = self._make_sandboxed_tool(
                    data["code"], fqn, persisted_secrets
                )
                creator = data.get("provenance", {}).get("creator_agent", "persisted")
                self._registry.register_dynamic(
                    fqn,
                    tool_fn,
                    data["parameters"],
                    data["description"],
                    creator,
                    secrets_keys=persisted_secrets if persisted_secrets else None,
                )
                self._records[fqn] = DynamicToolRecord(
                    fqn=fqn,
                    creator_agent=creator,
                    code=data["code"],
                    parameters=data["parameters"],
                    description=data["description"],
                    meta=data.get("meta"),
                    required_secrets=persisted_secrets,
                )
                logger.info("Loaded persisted dynamic tool: %s", fqn)

            except Exception as exc:
                logger.warning(
                    "Failed to load persisted tool %s: %s", json_file.name, exc
                )
