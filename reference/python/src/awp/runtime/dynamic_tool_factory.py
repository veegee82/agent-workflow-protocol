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
import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Structured error classes for runtime tool generation.
#
# These let the inline LLM repair loop in delegation_loop_runner decide
# whether a failure is *repairable* (LLM can produce a fixed version) or
# *terminal* (no point spending more tokens).  The classes are also used
# as machine-readable categories in metrics / observability.
# ---------------------------------------------------------------------------
class ToolCreationError(Exception):
    """Base class for all dynamic tool creation failures."""

    category: str = "unknown"
    repairable: bool = False
    status: int = 500

    def __init__(self, message: str, *, hint: str = "", status: Optional[int] = None) -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint
        if status is not None:
            self.status = status

    def to_result(self) -> dict[str, Any]:
        return {
            "ok": False,
            "status": self.status,
            "data": {},
            "error": self.message + (f" Hint: {self.hint}" if self.hint else ""),
            "log": "",
            "category": self.category,
            "repairable": self.repairable,
            "hint": self.hint,
        }


class ToolValidationError(ToolCreationError):
    category = "validation"
    repairable = True
    status = 400


class ToolImportError(ToolCreationError):
    category = "import"
    repairable = True
    status = 403


class ToolSchemaMismatchError(ToolCreationError):
    category = "schema_mismatch"
    repairable = True
    status = 400


class ToolDryRunError(ToolCreationError):
    category = "dry_run"
    repairable = True
    status = 422


class ToolPolicyError(ToolCreationError):
    """Policy / quota / namespace violation. Not repairable by an LLM."""

    category = "policy"
    repairable = False
    status = 403


# Alternative suggestions for forbidden imports — helps the LLM repair quickly.
IMPORT_ALTERNATIVES: dict[str, str] = {
    "os": "use the pre-defined `_output_dir`/`_workspace_dir` strings + builtin `open()`; for path joining use string concatenation or `pathlib`",
    "os.path": "use string concatenation (`_output_dir + '/' + name`) or `pathlib.Path`",
    "subprocess": "shell access is not available in dynamic tools — implement the logic in pure Python",
    "sys": "system access is not available; if you need to read env vars use `_secrets` (declared via required_secrets) instead",
    "ctypes": "ctypes is not available — use a pure-Python implementation",
    "importlib": "import directly with `import foo` at the top of the tool code",
    "signal": "signal handling is not available in the sandbox",
    "multiprocessing": "spawn no subprocesses — write a single-process implementation",
    "socket": "if you need network access, declare the `network` capability on the namespace and use `urllib.request`/`requests`",
}


def _suggest_import_alternative(module: str) -> str:
    root = module.split(".")[0]
    return IMPORT_ALTERNATIVES.get(root, "")

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
        "code_hash",
        "repair_attempts",
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
        code_hash: str = "",
        repair_attempts: int = 0,
    ) -> None:
        self.fqn = fqn
        self.creator_agent = creator_agent
        self.created_at = datetime.now(timezone.utc).isoformat()
        self.code = code
        self.parameters = parameters
        self.description = description
        self.meta = meta or {}
        self.required_secrets = required_secrets or []
        self.code_hash = code_hash or compute_tool_hash(fqn, code, parameters)
        self.repair_attempts = repair_attempts

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "fqn": self.fqn,
            "description": self.description,
            "parameters": self.parameters,
            "code": self.code,
            "meta": self.meta,
            "code_hash": self.code_hash,
            "repair_attempts": self.repair_attempts,
            "provenance": {
                "creator_agent": self.creator_agent,
                "created_at": self.created_at,
            },
        }
        if self.required_secrets:
            d["required_secrets"] = self.required_secrets
        return d


def compute_tool_hash(
    name: str, code: str, parameters: dict[str, Any]
) -> str:
    """Stable SHA256 hash of (fqn, normalised code, parameter schema).

    Used for content-addressable cache / dedup.  Whitespace at line ends
    is normalised so equivalent generations hit the cache.
    """
    norm_code = "\n".join(line.rstrip() for line in code.strip().splitlines())
    schema_blob = json.dumps(parameters or {}, sort_keys=True, default=str)
    payload = f"{name}\x00{norm_code}\x00{schema_blob}".encode()
    return hashlib.sha256(payload).hexdigest()


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
            if isinstance(config, dict):
                persist_val = config.get("persist", None)
            else:
                persist_val = getattr(config, "persist", None)
            self._persist = persist_val if persist_val is not None else self._enabled
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

        # B6: configurable timeout (seconds), dry-run flag, repair flag.
        # Defaults preserve previous behaviour.
        def _cfg_get(key: str, default: Any) -> Any:
            if config is None:
                return default
            if hasattr(config, key):
                v = getattr(config, key)
                return v if v is not None else default
            try:
                return config.get(key, default)
            except AttributeError:
                return default

        self._timeout_seconds = int(_cfg_get("timeout_seconds", 10))
        self._dry_run_enabled = bool(_cfg_get("dry_run", True))
        self._dry_run_timeout = int(_cfg_get("dry_run_timeout_seconds", 5))
        self._cache_enabled = bool(_cfg_get("cache", True))

        # B5: content-addressable cache: hash -> registered fqn
        self._hash_to_fqn: dict[str, str] = {}

        # B6: lightweight metrics counters
        self._metrics: dict[str, int] = {
            "attempts": 0,
            "successes": 0,
            "cache_hits": 0,
            "validation_failures": 0,
            "import_failures": 0,
            "schema_mismatches": 0,
            "dry_run_failures": 0,
            "policy_failures": 0,
            "repair_attempts": 0,
            "repair_successes": 0,
        }

        # Resolve and cache the cross-run shared dir path up-front so
        # _persist_tool / _load_persisted_tools use a consistent target.
        # Also pre-create it when persistence is enabled, so the first
        # successful tool create never races a missing directory.
        self._shared_dir: Optional[Path] = None
        if self._workflow_dir:
            self._shared_dir = self._resolve_shared_dir(self._workflow_dir)
            if self._persist and self._shared_dir is not None:
                try:
                    self._shared_dir.mkdir(parents=True, exist_ok=True)
                except Exception as exc:
                    logger.warning(
                        "Could not create shared dynamic_tools dir %s: %s",
                        self._shared_dir, exc,
                    )

        # Load persisted tools on init
        if self._persist and self._workflow_dir:
            self._load_persisted_tools()

    @staticmethod
    def _resolve_shared_dir(workflow_dir: Path) -> Optional[Path]:
        """Locate the cross-run ``shared/dynamic_tools`` directory.

        Supports two layouts:

        1. **Per-run isolation (current)**: ``workflow_dir`` is
           ``<exp>/runs/<run_id>``; shared dir lives at ``<exp>/shared/dynamic_tools``.
        2. **Legacy flat**: ``workflow_dir`` is the experiment root; the
           shared dir is ``<workflow_dir>/../shared/dynamic_tools`` if that
           exists, else ``<workflow_dir>/shared/dynamic_tools``.

        We walk upward a bounded number of levels and return the first
        match whose parent (``shared/``) already exists, OR the per-run
        candidate if the parent layout looks right (``runs/`` directory
        present). This makes the resolution robust to both layouts
        without over-reaching into unrelated parent directories.
        """
        try:
            wd = workflow_dir.resolve()
        except Exception:
            wd = workflow_dir

        # Case 1: per-run isolation — <exp>/runs/<run_id>.
        # Detect by checking that parent is named "runs" (or that a sibling
        # "shared" exists two levels up).
        if wd.parent.name == "runs" and wd.parent.parent.exists():
            return wd.parent.parent / "shared" / "dynamic_tools"

        # Case 2: an existing shared/ directory one level up (legacy migrated).
        one_up_shared = wd.parent / "shared"
        if one_up_shared.is_dir():
            return one_up_shared / "dynamic_tools"

        # Case 3: legacy flat — no cross-run shared dir. Return None so
        # callers fall back to workspace-local persistence only.
        return None

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def metrics(self) -> dict[str, int]:
        """Return a snapshot of tool-creation metrics counters."""
        return dict(self._metrics)

    def _bump(self, key: str, n: int = 1) -> None:
        self._metrics[key] = self._metrics.get(key, 0) + n

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
        self._bump("attempts")

        if not self._enabled:
            self._bump("policy_failures")
            return _err("Dynamic tool creation is not enabled", 403)

        # ----------------------------------------------------------------
        # Tool-Manifest-First Planning hooks (B2 + B3, opt-in via meta).
        #
        #   meta = {
        #       "pattern_id": "<id from awp.patterns>",  # zero-LLM path
        #       # OR
        #       "contract":   {...},                      # generate skeleton
        #       "smoke_test": "<python snippet>",         # custom smoke
        #       "smoke_packages": ["pkg1", ...],
        #   }
        #
        # When pattern_id is set we override the caller-supplied `code`
        # with the verified pattern skeleton entirely — the LLM never
        # needs to write the body. When `contract` is set we synthesise
        # a typed skeleton and the LLM-supplied `code` is treated as the
        # filled-in body wrapper.
        #
        # If either path is taken, we run a venv smoke test BEFORE
        # promoting the tool to the registry.
        # ----------------------------------------------------------------
        _smoke_required = False
        _smoke_snippet: str = ""
        _smoke_packages: list[str] = []
        _meta = meta or {}
        try:
            pattern_id = _meta.get("pattern_id")
            archetype_id = _meta.get("archetype_id")
            recipe_params = _meta.get("recipe_params")
            if pattern_id:
                from awp.patterns import get_pattern  # local import

                _pat = get_pattern(pattern_id)
                if _pat is None:
                    return _err(
                        f"Unknown pattern_id '{pattern_id}' "
                        f"(see awp.patterns.PATTERNS)",
                        400,
                    )
                logger.info(
                    "Tool '%s' instantiated from pattern '%s' (zero-LLM)",
                    name, pattern_id,
                )
                code = _pat.skeleton
                description = description or _pat.description
                _smoke_required = True
                _smoke_snippet = _pat.smoke_test
                _smoke_packages = list(_pat.packages)
            elif archetype_id and isinstance(recipe_params, dict):
                from awp.patterns import get_archetype  # local import

                _arch = get_archetype(archetype_id)
                if _arch is None:
                    return _err(
                        f"Unknown archetype_id '{archetype_id}' "
                        f"(see awp.patterns.ARCHETYPES)",
                        400,
                    )
                _params = dict(recipe_params)
                _params.setdefault("name", name)
                _errs = _arch.validate_params(_params)
                if _errs:
                    return _err(
                        f"archetype '{archetype_id}' params invalid: "
                        f"{'; '.join(_errs)}",
                        400,
                    )
                try:
                    _gen_code, _gen_pkgs = _arch.build_skeleton(_params)
                except Exception as _bexc:
                    return _err(
                        f"archetype '{archetype_id}' build_skeleton failed: {_bexc}",
                        400,
                    )
                logger.info(
                    "Tool '%s' synthesised from archetype '%s' (zero-LLM body)",
                    name, archetype_id,
                )
                code = _gen_code
                _smoke_required = True
                _smoke_snippet = _meta.get("smoke_test") or _arch.build_smoke(_params)
                _smoke_packages = list(_gen_pkgs) + list(_meta.get("smoke_packages") or [])
            else:
                contract = _meta.get("contract")
                if isinstance(contract, dict):
                    from .tool_skeleton import generate_skeleton

                    skeleton = generate_skeleton(contract)
                    # We do NOT replace the caller's code wholesale here;
                    # we expose the generated skeleton in meta for trace
                    # and let the validator catch structural drift.
                    _meta = dict(_meta)
                    _meta["_generated_skeleton"] = skeleton
                snippet = _meta.get("smoke_test")
                if isinstance(snippet, str) and snippet.strip():
                    _smoke_required = True
                    _smoke_snippet = snippet
                    _smoke_packages = list(_meta.get("smoke_packages") or [])
        except Exception as _hook_exc:  # pragma: no cover
            logger.warning(
                "Tool-manifest hook failed for '%s': %s", name, _hook_exc
            )

        # B5: Content-addressable cache — dedup identical generations.
        tool_hash = compute_tool_hash(name, code, parameters)
        if self._cache_enabled:
            cached_fqn = self._hash_to_fqn.get(tool_hash)
            if cached_fqn and cached_fqn in self._registry._tools:
                self._bump("cache_hits")
                self._bump("successes")
                logger.info(
                    "Dynamic tool cache hit: %s -> already registered as %s",
                    name,
                    cached_fqn,
                )
                return _ok(
                    {
                        "name": cached_fqn,
                        "registered": True,
                        "cache_hit": True,
                        "code_hash": tool_hash,
                    }
                )

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
            # Categorise validation failure for metrics + repair routing.
            err_text = validation.get("error", "")
            if "Import" in err_text or "import" in err_text:
                self._bump("import_failures")
                validation["category"] = "import"
                validation["repairable"] = True
            else:
                self._bump("validation_failures")
                validation["category"] = "validation"
                validation["repairable"] = True
            return validation

        # B2: Schema ↔ signature consistency check.
        schema_check = self._check_schema_signature(code, parameters)
        if not schema_check["ok"]:
            self._bump("schema_mismatches")
            schema_check["category"] = "schema_mismatch"
            schema_check["repairable"] = True
            return schema_check

        # DT9: Reject tools that generate placeholder/dummy output files.
        # LLMs sometimes create tools that write base64-encoded 1x1 PNGs or
        # minimal PDF stubs as a workaround for missing libraries.  These
        # bypass file validation and produce broken deliverables.
        _code_lower = code.lower()
        _desc_lower = description.lower()
        _placeholder_indicators = [
            # Base64-encoded 1x1 PNG payloads (multiple common variants)
            "ivborw0kggoaaaansuheugaaaaeaaaabca" in _code_lower,
            # Explicit placeholder/dummy language
            "placeholder" in _desc_lower and (
                "png" in _desc_lower or "image" in _desc_lower
                or "plot" in _desc_lower
            ),
            "placeholder" in name.lower(),
            # Minimal PDF stubs
            "placeholder pdf" in _code_lower,
            "%pdf-1.1\\n%placeholder" in _code_lower,
            b"%PDF-1.1".decode() in code and len(code) < 500 and "placeholder" in _code_lower,
        ]
        if any(_placeholder_indicators):
            return _err(
                f"Tool '{name}' appears to generate placeholder/dummy output files "
                f"(base64 PNGs, minimal PDF stubs, etc.). "
                f"This is not allowed — use real plotting libraries (matplotlib) "
                f"and PDF generators (reportlab) instead. "
                f"Install missing packages with pip.install first.",
                403,
            )

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

        # B3 (Tool-Manifest gate): if the caller declared a smoke_test
        # (either via pattern_id or explicit meta.smoke_test), execute it
        # in an isolated venv with the declared packages installed BEFORE
        # promoting the tool. A failing smoke test is repairable: the
        # caller (delegation loop) gets one repair attempt.
        if _smoke_required:
            from .tool_test_gate import smoke_test_tool

            gate = smoke_test_tool(
                code,
                smoke_snippet=_smoke_snippet,
                packages=_smoke_packages,
                timeout=max(self._timeout_seconds, 30),
            )
            if not gate.get("ok"):
                self._bump("dry_run_failures")
                err_text = (
                    gate.get("error")
                    or gate.get("data", {}).get("stderr", "")
                    or "smoke test failed"
                )
                logger.warning(
                    "Smoke gate REJECTED tool '%s': %s", name, err_text[:200]
                )
                return {
                    "ok": False,
                    "status": 422,
                    "data": gate.get("data", {}),
                    "error": f"smoke gate rejected '{name}': {err_text[:300]}",
                    "category": "smoke_gate",
                    "repairable": True,
                }
            logger.info(
                "Smoke gate ACCEPTED tool '%s' (%d pkgs)",
                name, len(_smoke_packages),
            )

        # B3: Dry-run probe — execute once with synthetic inputs to catch
        # runtime errors before registration.  Skipped if disabled or if
        # the namespace declares network/IO that would have side effects.
        if self._dry_run_enabled:
            dry = self._dry_run_tool(code, name, parameters, secrets_list)
            if not dry["ok"]:
                self._bump("dry_run_failures")
                dry["category"] = "dry_run"
                dry["repairable"] = True
                return dry

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
            code_hash=tool_hash,
        )
        self._records[name] = record
        self._agent_counts[creator_agent] = count + 1
        if self._cache_enabled:
            self._hash_to_fqn[tool_hash] = name
        self._bump("successes")

        # Persist if enabled
        if self._persist and self._workflow_dir:
            self._persist_tool(record)

        # ----------------------------------------------------------------
        # Recipe capture (auto-learning, opt-in via meta).
        #
        # If the manifest declared an ``archetype_id`` + ``recipe_params``
        # we persist a QUARANTINED recipe candidate so future runs can
        # find this exact instantiation by capability tag.  Failure here
        # is non-fatal — the foreground tool creation has already
        # succeeded.
        # ----------------------------------------------------------------
        try:
            arch_id = (meta or {}).get("archetype_id")
            recipe_params = (meta or {}).get("recipe_params")
            if arch_id and isinstance(recipe_params, dict):
                from awp.patterns import capture_recipe  # local import

                capture_recipe(
                    archetype_id=arch_id,
                    capability=(meta or {}).get("capability") or name,
                    description=description or "",
                    params=recipe_params,
                    smoke_test=_smoke_snippet,
                    smoke_packages=tuple(_smoke_packages),
                    learned_from_run=(meta or {}).get("run_id"),
                )
        except Exception as _cap_exc:  # pragma: no cover
            logger.warning("Recipe capture failed for '%s': %s", name, _cap_exc)

        logger.info("Dynamic tool created: %s (by %s, hash=%s)", name, creator_agent, tool_hash[:12])
        return _ok({"name": name, "registered": True, "code_hash": tool_hash})

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

    # Dangerous builtin function names that can bypass import restrictions
    _DANGEROUS_BUILTINS: frozenset[str] = frozenset({
        "eval", "exec", "compile", "__import__",
    })

    # Dangerous attribute names that indicate reflection-based import bypass
    _DANGEROUS_ATTRS: frozenset[str] = frozenset({
        "__import__", "__subclasses__", "__bases__", "__mro__",
        "__globals__", "__builtins__", "__loader__", "__spec__",
    })

    @staticmethod
    def _extract_handler_kwargs(handler_node: ast.AST) -> set[str]:
        """Return the set of kwarg keys the handler reads from its inputs.

        Walks the handler body and collects:
          - direct kwonly arg names (`def handler(*, foo, bar)`) — those
            are guaranteed inputs.
          - explicit `kwargs.get("x")` / `kwargs["x"]` style accesses
            when the handler uses `**kwargs`.

        Used by Pre-Flight check B2 to compare against
        ``parameters.properties`` keys.
        """
        used: set[str] = set()
        if not isinstance(handler_node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return used
        for a in handler_node.args.kwonlyargs:
            used.add(a.arg)
        kw_var = handler_node.args.kwarg.arg if handler_node.args.kwarg else None
        if kw_var is None:
            return used
        for node in ast.walk(handler_node):
            # kwargs["x"]
            if (
                isinstance(node, ast.Subscript)
                and isinstance(node.value, ast.Name)
                and node.value.id == kw_var
            ):
                idx = node.slice
                if isinstance(idx, ast.Constant) and isinstance(idx.value, str):
                    used.add(idx.value)
            # kwargs.get("x", default)
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == kw_var
                and node.func.attr in ("get", "pop")
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
            ):
                used.add(node.args[0].value)
        return used

    def _check_schema_signature(
        self, code: str, parameters: dict[str, Any]
    ) -> dict[str, Any]:
        """B2: Verify the parameter JSON Schema matches the handler signature.

        - Every property declared in ``parameters.properties`` SHOULD be
          read by the handler (warn-only via log; not blocking — some
          tools take optional fields they may not always use).
        - Every kwarg the handler reads MUST be present in
          ``parameters.properties`` — otherwise the LLM router will
          never pass it and the tool will silently break.
        """
        if not isinstance(parameters, dict):
            return _err(
                "Tool 'parameters' must be a JSON Schema object "
                "(dict with 'type': 'object' and 'properties').",
                400,
            )

        try:
            tree = ast.parse(code)
        except SyntaxError as exc:
            return _err(f"Syntax error during schema check: {exc}", 400)

        handler_node = None
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "handler":
                handler_node = node
                break
        if handler_node is None:
            return _ok({"valid": True})  # validate_code already errored

        used = self._extract_handler_kwargs(handler_node)
        properties = (parameters.get("properties") or {}) if isinstance(parameters, dict) else {}
        declared = set(properties.keys()) if isinstance(properties, dict) else set()

        missing_in_schema = sorted(used - declared - {"_secrets", "_workspace_dir", "_output_dir"})
        if missing_in_schema:
            return _err(
                "Tool parameter schema is missing keys that the handler reads: "
                f"{missing_in_schema}. "
                "Add them under `parameters.properties` (with type + description) "
                "and list the required ones under `parameters.required`. "
                "Every kwarg used in handler() MUST be declared in the schema.",
                400,
            )

        unused_in_schema = sorted(declared - used)
        if unused_in_schema:
            logger.warning(
                "Schema declares parameters not read by handler: %s",
                unused_in_schema,
            )

        return _ok({"valid": True, "kwargs_used": sorted(used), "schema_keys": sorted(declared)})

    def _synth_inputs_from_schema(self, parameters: dict[str, Any]) -> dict[str, Any]:
        """B3: Generate minimal synthetic inputs from a JSON Schema.

        Used by the dry-run probe.  We never invent values that could
        cause side-effects: empty strings, 0, [], {} or the first enum
        choice.  All declared properties are filled (not just `required`)
        so that handlers that fail-fast on missing optional keys still
        get something.
        """
        properties = parameters.get("properties") or {}
        out: dict[str, Any] = {}
        if not isinstance(properties, dict):
            return out
        for key, schema in properties.items():
            if not isinstance(schema, dict):
                out[key] = ""
                continue
            if "default" in schema:
                out[key] = schema["default"]
                continue
            if "enum" in schema and isinstance(schema["enum"], list) and schema["enum"]:
                out[key] = schema["enum"][0]
                continue
            t = schema.get("type", "string")
            if isinstance(t, list):
                t = t[0] if t else "string"
            if t == "string":
                out[key] = ""
            elif t in ("integer", "number"):
                out[key] = 0
            elif t == "boolean":
                out[key] = False
            elif t == "array":
                out[key] = []
            elif t == "object":
                out[key] = {}
            else:
                out[key] = None
        return out

    def _dry_run_tool(
        self,
        code: str,
        fqn: str,
        parameters: dict[str, Any],
        required_secrets: list[str],
    ) -> dict[str, Any]:
        """B3: Run the tool once with synthetic inputs before registering.

        On success returns ``_ok(...)``.  On failure returns an ``_err``
        result tagged with ``category='dry_run'`` so the repair loop can
        decide whether to ask the LLM to fix the code.

        Tools whose handler raises during dry-run are NOT registered —
        the worker iteration learns immediately instead of registering
        a broken tool that will fail on the first real call.
        """
        try:
            tool_fn = self._make_sandboxed_tool(
                code, fqn, required_secrets, timeout_override=self._dry_run_timeout
            )
        except Exception as exc:
            return _err(f"Dry-run setup failed: {exc}", 500)

        synth = self._synth_inputs_from_schema(parameters)
        # Restrict synthetic inputs to keys the handler actually reads —
        # otherwise a kwonly handler `def handler(*, x)` raises TypeError
        # when the schema declares additional optional fields.
        try:
            tree = ast.parse(code)
            handler_node = next(
                (n for n in ast.iter_child_nodes(tree)
                 if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                 and n.name == "handler"),
                None,
            )
            if handler_node is not None and handler_node.args.kwarg is None:
                # No **kwargs — restrict to declared kwonly args.
                allowed = {a.arg for a in handler_node.args.kwonlyargs}
                synth = {k: v for k, v in synth.items() if k in allowed}
        except SyntaxError:
            pass
        # ToolRegistry would normally inject _secrets; we mimic that with
        # an empty dict so handlers using `_secrets.get(...)` still work.
        synth["_secrets"] = {}
        try:
            result = tool_fn(**synth)
        except Exception as exc:
            return _err(
                f"Dry-run crashed before producing output: {exc}. "
                f"Handler must not raise on minimal inputs ({sorted(k for k in synth if not k.startswith('_'))}). "
                f"Add input validation or guard against empty values.",
                422,
            )

        if not isinstance(result, dict):
            return _err(
                f"Dry-run returned non-dict: {type(result).__name__}. "
                "Handler must return a dict (AWP standard format).",
                422,
            )

        if not result.get("ok", False):
            err = str(result.get("error") or "(no error message)")
            err_low = err.lower()
            # Tolerate missing third-party libraries — the worker will
            # `pip.install` them before the tool is called for real.
            if "modulenotfounderror" in err_low or "no module named" in err_low:
                logger.info(
                    "Dry-run for %s skipped: missing optional dependency "
                    "(will be installed at runtime)", fqn,
                )
                return _ok({"dry_run": "skipped_missing_dep"})
            # Tools legitimately return ok=False on bad inputs; tolerate
            # *only* handler-level errors. Crashes / no-output / sandbox
            # failures are flagged here.
            if (
                "execution failed" in err_low
                or "no output" in err_low
                or "traceback" in err_low
            ):
                return _err(
                    f"Dry-run failed: {err}",
                    422,
                )
            logger.info(
                "Dry-run for %s returned ok=False with handler-level error "
                "(tolerated): %s", fqn, err[:200],
            )

        return _ok({"dry_run": "passed"})

    def validate_code(self, code: str, namespace: Optional[str] = None) -> dict[str, Any]:
        """Validate Python code via AST without executing it.

        Checks:
        1. Syntax validity
        2. No denied imports (namespace-capability-aware)
        3. No dangerous builtins (eval, exec, compile, __import__)
        4. No reflection-based import bypass (__subclasses__, __globals__, etc.)
        5. Contains exactly one ``def handler(*, ...)`` function

        Args:
            code: Python source code string.
            namespace: Optional namespace for per-namespace capability policy.

        Returns:
            Standard AWP result format.
        """
        # --- Pre-parse auto-repair: empty kw-only handler signature ---
        # LLMs sometimes emit `def handler(*, ):` or `def handler(*):` for
        # zero-argument tools, which is a SyntaxError. Rewrite to a
        # tolerant signature that accepts (and ignores) any kwargs.
        import re as _re
        code = _re.sub(
            r"def\s+handler\s*\(\s*\*\s*,?\s*\)\s*:",
            "def handler(**_):",
            code,
        )

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
                        alt = _suggest_import_alternative(alias.name)
                        return _err(
                            f"Import of '{alias.name}' is not allowed in dynamic tool code "
                            f"(sandbox type: {self._sandbox_type}{caps_info})."
                            + (f" Alternative: {alt}" if alt else ""),
                            403,
                        )
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    root_module = node.module.split(".")[0]
                    if root_module in denied:
                        alt = _suggest_import_alternative(node.module)
                        return _err(
                            f"Import from '{node.module}' is not allowed in dynamic tool code "
                            f"(sandbox type: {self._sandbox_type}{caps_info})."
                            + (f" Alternative: {alt}" if alt else ""),
                            403,
                        )

            # --- Dangerous builtin calls: eval(), exec(), compile(), __import__() ---
            elif isinstance(node, ast.Call):
                func = node.func
                # Direct call: eval(...), exec(...), __import__(...)
                if isinstance(func, ast.Name) and func.id in self._DANGEROUS_BUILTINS:
                    return _err(
                        f"Use of '{func.id}()' is not allowed in dynamic tool code. "
                        f"This function can bypass import restrictions and execute "
                        f"arbitrary code.",
                        403,
                    )
                # Attribute call: builtins.__import__(...), builtins.eval(...)
                if isinstance(func, ast.Attribute):
                    if func.attr in self._DANGEROUS_BUILTINS:
                        return _err(
                            f"Use of '.{func.attr}()' is not allowed in dynamic tool code. "
                            f"This method can bypass import restrictions.",
                            403,
                        )
                # getattr(obj, '__import__') / getattr(obj, '__globals__') etc.
                if (
                    isinstance(func, ast.Name) and func.id == "getattr"
                    and len(node.args) >= 2
                    and isinstance(node.args[1], ast.Constant)
                    and isinstance(node.args[1].value, str)
                ):
                    attr_name = node.args[1].value
                    if attr_name in self._DANGEROUS_BUILTINS | self._DANGEROUS_ATTRS:
                        return _err(
                            f"Use of getattr(obj, '{attr_name}') is not allowed in "
                            f"dynamic tool code. This can bypass sandbox restrictions.",
                            403,
                        )

            # --- Dangerous attribute access: obj.__subclasses__, obj.__globals__ ---
            elif isinstance(node, ast.Attribute):
                if node.attr in self._DANGEROUS_ATTRS:
                    return _err(
                        f"Access to '.{node.attr}' is not allowed in dynamic tool code. "
                        f"This attribute can be used to escape the sandbox.",
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
        self,
        code: str,
        fqn: str,
        required_secrets: Optional[list[str]] = None,
        timeout_override: Optional[int] = None,
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
        _timeout = int(timeout_override or self._timeout_seconds)

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

            # Build preamble with RESTRICTED helpers only.
            # SECURITY: We do NOT expose os, sys, subprocess, or builtins
            # to dynamic tool code. Instead, we provide narrow helper
            # functions that only do what's needed (path joining, dir
            # creation, file listing) without giving access to the full
            # os/sys modules.  This is critical because ALWAYS_DENIED
            # blocks these imports in tool code, so the preamble must
            # not re-introduce them.
            script = (
                f"import json\n"
                f"_secrets = json.loads({json.dumps(secrets_json)})\n"
                f"_workspace_dir = {json.dumps(workspace_dir)}\n"
                f"_output_dir = {json.dumps(output_dir)}\n"
                f"\n"
                f"# --- Restricted helpers (no os/sys/subprocess exposed) ---\n"
                f"def _ensure_dir(path):\n"
                f"    from pathlib import Path as _P\n"
                f"    p = _P(path)\n"
                f"    target = p.parent if not p.is_dir() else p\n"
                f"    target.mkdir(parents=True, exist_ok=True)\n"
                f"    return str(path)\n"
                f"def _output_file(*parts):\n"
                f"    from pathlib import Path as _P\n"
                f"    return str(_P(_output_dir).joinpath(*parts))\n"
                f"def _input_file(*parts):\n"
                f"    from pathlib import Path as _P\n"
                f"    return str(_P(_workspace_dir, 'inputs', *parts))\n"
                f"def _list_files(directory=None):\n"
                f"    from pathlib import Path as _P\n"
                f"    base = _P(directory) if directory else _P(_workspace_dir)\n"
                f"    found = []\n"
                f"    for p in sorted(base.rglob('*')):\n"
                f"        if p.is_file():\n"
                f"            found.append(str(p.relative_to(base)))\n"
                f"    return found\n"
                f"\n"
                f"# Auto-create parent dirs for writes (via pathlib, not os)\n"
                f"import builtins as _builtins\n"
                f"_orig_open = _builtins.open\n"
                f"def _safe_open(path, mode='r', *args, **kwargs):\n"
                f"    from pathlib import Path as _P\n"
                f"    p = _P(str(path))\n"
                f"    if any(m in str(mode) for m in ('w', 'a', 'x')):\n"
                f"        p.parent.mkdir(parents=True, exist_ok=True)\n"
                f"    return _orig_open(path, mode, *args, **kwargs)\n"
                f"_builtins.open = _safe_open\n"
                f"del _builtins  # don't expose builtins module to tool code\n"
                f"\n"
                f"# Matplotlib safety (use pip.install tool to pre-install)\n"
                f"try:\n"
                f"    import matplotlib as _mpl\n"
                f"    _mpl.use('Agg')\n"
                f"except ImportError:\n"
                f"    pass  # agent should use pip.install tool instead\n"
                f"\n"
                f"# PNG validation helper\n"
                f"def _verify_png(path):\n"
                f"    import struct as _struct\n"
                f"    from pathlib import Path as _P\n"
                f"    try:\n"
                f"        with open(path, 'rb') as _f:\n"
                f"            _header = _f.read(24)\n"
                f"        if len(_header) < 24:\n"
                f"            return False\n"
                f"        _w = _struct.unpack('>I', _header[16:20])[0]\n"
                f"        _h = _struct.unpack('>I', _header[20:24])[0]\n"
                f"        _size = _P(path).stat().st_size\n"
                f"        if _w < 10 or _h < 10 or _size < 500:\n"
                f"            return False\n"
                f"        return True\n"
                f"    except Exception:\n"
                f"        return False\n"
                f"\n"
                f"# --- End preamble ---\n"
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

            # Snapshot files before execution for validation
            _snapshot_before: dict[str, dict] = {}
            _dirs_to_watch: list[Path] = []
            if _workflow_dir:
                _dirs_to_watch = [
                    _workflow_dir / "workspace",
                    _workflow_dir / "output",
                ]
                try:
                    from .file_validator import snapshot_file_state
                    _snapshot_before = {
                        str(d): snapshot_file_state(d) for d in _dirs_to_watch
                    }
                except Exception:
                    pass

            exec_result = executor.execute(script, timeout=_timeout)

            # --- File validation: dynamic tools must not create broken files ---
            if exec_result["ok"] and _dirs_to_watch and _snapshot_before:
                try:
                    from .file_validator import (
                        classify_warning_severity,
                        find_changed_files,
                        snapshot_file_state,
                        validate_file,
                    )
                    _snapshot_after = {
                        str(d): snapshot_file_state(d) for d in _dirs_to_watch
                    }
                    critical_files: list[str] = []
                    for d_str in _snapshot_before:
                        changed = find_changed_files(
                            _snapshot_before[d_str], _snapshot_after[d_str]
                        )
                        for p in changed:
                            w = validate_file(p)
                            if w and classify_warning_severity(p, w) == "critical":
                                critical_files.append(w)
                    if critical_files:
                        logger.warning(
                            "Dynamic tool %s created CRITICAL invalid files: %s",
                            fqn, critical_files,
                        )
                        return _err(
                            f"Dynamic tool '{fqn}' created invalid output files "
                            f"(placeholder PNGs, empty PDFs, etc.). "
                            f"Errors: {'; '.join(critical_files)}. "
                            f"Fix: use real data and proper libraries (matplotlib, "
                            f"reportlab) instead of base64 placeholders.",
                            422,
                        )
                except ImportError:
                    pass

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
        """Save tool definition as JSON manifest for local + cross-run reuse.

        Writes to two locations (either may resolve to the same file via a
        symlink, which is fine — the writes are idempotent):

        1. ``<workflow_dir>/workspace/dynamic_tools/<fqn>.json`` — the
           canonical per-run path. Under the UI layout this is usually a
           symlink to the experiment's ``shared/dynamic_tools`` directory,
           so writing here also populates the shared registry.
        2. ``<experiment>/shared/dynamic_tools/<fqn>.json`` — the direct
           shared path, written defensively so cross-run reuse works even
           if the symlink is broken or missing.

        Both writes log success/failure so an empty registry can never be
        silent.
        """
        if not self._workflow_dir:
            return

        payload = json.dumps(record.to_dict(), indent=2, ensure_ascii=False)
        wrote_any = False

        # 1) Workspace-local (primary). Under per-run isolation this is a
        #    symlink into shared/, so one write populates both.
        persist_dir = self._workflow_dir / "workspace" / "dynamic_tools"
        try:
            persist_dir.mkdir(parents=True, exist_ok=True)
            persist_path = persist_dir / f"{record.fqn}.json"
            persist_path.write_text(payload, encoding="utf-8")
            wrote_any = True
            logger.info(
                "Persisted dynamic tool %s -> %s", record.fqn, persist_path
            )
        except Exception as exc:
            logger.warning(
                "Failed to persist tool %s to workspace/: %s",
                record.fqn, exc,
            )

        # 2) Shared (defensive second write). Only reach here if the
        #    resolved shared_dir is DIFFERENT from the workspace target
        #    (after symlink resolution) — otherwise we'd be writing the
        #    same file twice.
        if self._shared_dir is not None:
            try:
                self._shared_dir.mkdir(parents=True, exist_ok=True)
                shared_path = self._shared_dir / f"{record.fqn}.json"

                # Resolve both targets to compare canonical paths. If they
                # collide (symlink layout), skip the second write.
                try:
                    ws_resolved = (persist_dir / f"{record.fqn}.json").resolve()
                    sh_resolved = shared_path.resolve()
                except Exception:
                    ws_resolved = persist_dir / f"{record.fqn}.json"
                    sh_resolved = shared_path

                if ws_resolved != sh_resolved:
                    shared_path.write_text(payload, encoding="utf-8")
                    wrote_any = True
                    logger.info(
                        "Persisted dynamic tool %s to shared/: %s",
                        record.fqn, shared_path,
                    )
                else:
                    logger.debug(
                        "shared_dir write for %s skipped — same inode as "
                        "workspace path (symlink layout)",
                        record.fqn,
                    )
            except Exception as exc:
                logger.warning(
                    "Failed to persist tool %s to shared/ (%s): %s",
                    record.fqn, self._shared_dir, exc,
                )

        if not wrote_any:
            logger.error(
                "Dynamic tool %s was registered in-memory but NOT persisted "
                "to disk (workspace_dir=%s, shared_dir=%s). Tool will not "
                "survive across runs.",
                record.fqn, self._workflow_dir, self._shared_dir,
            )

    def _load_persisted_tools(self) -> None:
        """Load previously persisted dynamic tools from workspace/ and shared/.

        Deduplicates across candidate directories by canonical path, so a
        symlink layout (workspace/dynamic_tools → shared/dynamic_tools)
        never double-loads the same file.
        """
        if not self._workflow_dir:
            return

        # Collect candidate directories: local workspace first, then shared.
        # We probe both; dedup happens per canonical path.
        candidate_dirs: list[Path] = []
        local_dir = self._workflow_dir / "workspace" / "dynamic_tools"
        if local_dir.exists():
            candidate_dirs.append(local_dir)
        if self._shared_dir is not None and self._shared_dir.exists():
            candidate_dirs.append(self._shared_dir)

        if not candidate_dirs:
            logger.debug(
                "No persisted dynamic tool directories found "
                "(workflow_dir=%s, shared_dir=%s)",
                self._workflow_dir, self._shared_dir,
            )
            return

        # Deduplicate by canonical path so a symlink doesn't double-register.
        seen_canonical: set[Path] = set()
        loaded_fqns: set[str] = set()
        load_failures = 0

        for persist_dir in candidate_dirs:
            for json_file in sorted(persist_dir.glob("*.json")):
                try:
                    canonical = json_file.resolve()
                except Exception:
                    canonical = json_file
                if canonical in seen_canonical:
                    continue
                seen_canonical.add(canonical)

                try:
                    data = json.loads(json_file.read_text(encoding="utf-8"))
                    fqn = data["fqn"]

                    # Skip if already registered (e.g. a tool with the
                    # same FQN was loaded in this init call or registered
                    # by another code path).
                    if fqn in self._registry._tools or fqn in loaded_fqns:
                        continue

                    # Validate code (namespace-aware when we have one)
                    ns_hint = fqn.split(".")[0] if "." in fqn else None
                    validation = self.validate_code(data["code"], namespace=ns_hint)
                    if not validation["ok"]:
                        logger.warning(
                            "Skipping persisted tool %s: %s", fqn, validation["error"]
                        )
                        load_failures += 1
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
                        code_hash=data.get("code_hash", ""),
                    )
                    # Re-populate the content-addressable cache so a
                    # subsequent create_tool() with identical code dedups
                    # instead of failing with "already exists".
                    if self._cache_enabled:
                        self._hash_to_fqn[self._records[fqn].code_hash] = fqn
                    loaded_fqns.add(fqn)
                    logger.info(
                        "Loaded persisted dynamic tool: %s (from %s)",
                        fqn, persist_dir,
                    )

                except Exception as exc:
                    load_failures += 1
                    logger.warning(
                        "Failed to load persisted tool %s: %s", json_file.name, exc
                    )

        if loaded_fqns or load_failures:
            logger.info(
                "Dynamic tool registry restored: %d loaded, %d failed "
                "(candidates: %s)",
                len(loaded_fqns), load_failures,
                [str(p) for p in candidate_dirs],
            )
