"""Deterministic Phase Runner (R33, Phase 2).

Runs a :class:`DeterministicPhase` in an isolated subprocess with the
sandbox semantics spec'd in §9:

* Secrets (``*_API_KEY``, ``*_TOKEN``, ``*_SECRET``, ``*_PASSWORD``) are
  scrubbed from the child environment; ``PATH`` / ``HOME`` / ``PYTHONPATH``
  / ``LANG`` / ``LC_ALL`` are preserved so user callables can still
  invoke subprocesses and load locale-aware libraries.
* ``timeout_s`` is enforced via :func:`subprocess.run` with a ``timeout=``
  argument; a timeout maps to ``PhaseResult(status="partial",
  reason="deterministic_timeout")``.
* Arg values may reference ``${state.key}``, ``${workspace}``,
  ``${output}``, ``${workflow_dir}``; the runner substitutes them before
  dispatch using the same semantics as the delegation-loop executor.
* The callable is loaded via ``importlib.import_module`` inside the
  child process — ``module.path:function`` — and its return value is
  JSON-serialised to stdout and parsed by the parent.

The runner itself is deliberately stateless; one instance can be reused
across phases in the same run. It is **not** thread-safe per phase — a
given :class:`PhaseResult` is returned only after the subprocess exits,
but concurrent ``run()`` calls on the same instance are safe because no
mutable state is stored.
"""

from __future__ import annotations

import json
import logging
import os
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from awp.models.capabilities import SandboxConfig
from awp.models.orchestration import DeterministicPhase

from .invariants import ExecutionContext, InvariantCheckRegistry
from .result import InvariantCheckResult, PhaseResult

logger = logging.getLogger(__name__)


# Env-var name substrings that unconditionally indicate a secret and MUST
# be stripped from the child environment. The list matches spec §9's
# sandbox requirement. Kept as substrings (rather than exact match) so
# provider-specific variants (``OPENROUTER_API_KEY``,
# ``AWS_SECRET_ACCESS_KEY``) are caught.
_SECRET_SUBSTRINGS = ("API_KEY", "TOKEN", "SECRET", "PASSWORD")

# Env vars that MUST survive the secret scrub so user callables can still
# run: find binaries, know their home directory, import shared Python
# libraries, and format output with the right locale.
_PRESERVE_ENV = (
    "PATH",
    "HOME",
    "PYTHONPATH",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "TMPDIR",
    "TEMP",
    "TMP",
    "USER",
    "LOGNAME",
    "SHELL",
    # Virtual-env markers must survive so a deterministic phase picks up
    # the same interpreter environment the runner is using.
    "VIRTUAL_ENV",
    "PYTHONHOME",
    "PYTHONUNBUFFERED",
    "PYTHONDONTWRITEBYTECODE",
)


def _scrub_secrets(env: Dict[str, str]) -> Dict[str, str]:
    """Return a copy of ``env`` with secret-bearing keys removed.

    A variable is dropped iff any of the :data:`_SECRET_SUBSTRINGS`
    appears in its name (case-sensitive — all known secret env vars use
    upper-case naming). Variables listed in :data:`_PRESERVE_ENV` are
    unconditionally kept even if their name coincidentally matches.
    """
    out: Dict[str, str] = {}
    for k, v in env.items():
        if k in _PRESERVE_ENV:
            out[k] = v
            continue
        if any(s in k for s in _SECRET_SUBSTRINGS):
            continue
        out[k] = v
    return out


def _substitute_args(
    args: Dict[str, Any], ctx: ExecutionContext
) -> Dict[str, Any]:
    """Substitute ``${...}`` placeholders in string args.

    Supports:
      * ``${workspace}``      -> ctx.workspace_dir
      * ``${output}``         -> ctx.output_dir
      * ``${workflow_dir}``   -> ctx.workflow_dir
      * ``${state.key}``      -> ctx.state[key] (stringified)
      * ``${state.a.b.c}``    -> nested lookup; missing intermediate
                                 keys leave the token unsubstituted
                                 (caller sees the raw placeholder and
                                 can fail loudly in the callable).

    Non-string leaves are left unchanged. Lists and dicts are walked
    recursively. This is intentionally minimal — the substitution
    surface mirrors the delegation-loop executor's contract.
    """

    def _replace(s: str) -> str:
        out = s
        out = out.replace("${workspace}", str(ctx.workspace_dir))
        out = out.replace("${output}", str(ctx.output_dir))
        out = out.replace("${workflow_dir}", str(ctx.workflow_dir))
        # state.key / state.a.b.c — scan for tokens and resolve.
        import re as _re

        def _state(m: "_re.Match[str]") -> str:
            path = m.group(1).split(".")
            cur: Any = ctx.state
            for p in path:
                if isinstance(cur, dict) and p in cur:
                    cur = cur[p]
                else:
                    return m.group(0)  # leave unchanged
            return str(cur)

        out = _re.sub(r"\$\{state\.([a-zA-Z0-9_.]+)\}", _state, out)
        return out

    def _walk(v: Any) -> Any:
        if isinstance(v, str):
            return _replace(v)
        if isinstance(v, list):
            return [_walk(x) for x in v]
        if isinstance(v, dict):
            return {k: _walk(x) for k, x in v.items()}
        return v

    return {k: _walk(v) for k, v in args.items()}


_BOOTSTRAP = r"""
import json
import os
import sys

try:
    import importlib
    mod = importlib.import_module(%(module)r)
    fn = getattr(mod, %(func)r, None)
    if fn is None or not callable(fn):
        err = {"error": "callable_not_found",
               "detail": "%(module)s has no callable attr %(func)r"}
        sys.stdout.write("AWP_PHASE_RESULT:" + json.dumps({"ok": False, "error": err}))
        sys.exit(3)
    args = json.loads(os.environ.get("AWP_PHASE_ARGS_JSON", "{}"))
    result = fn(**args)
    if result is None:
        result = {}
    if not isinstance(result, dict):
        result = {"value": result}
    sys.stdout.write("AWP_PHASE_RESULT:" + json.dumps({"ok": True, "result": result}))
    sys.exit(0)
except SystemExit:
    raise
except BaseException as exc:  # noqa: BLE001
    import traceback
    err = {"error": type(exc).__name__, "detail": str(exc),
           "traceback": traceback.format_exc(limit=10)}
    sys.stdout.write("AWP_PHASE_RESULT:" + json.dumps({"ok": False, "error": err}))
    sys.exit(4)
"""


def _parse_callable(spec: str) -> tuple[str, str]:
    """Split ``module.path:function_name`` into its two parts."""
    if ":" not in spec:
        raise ValueError(
            f"callable must be 'module.path:function_name', got {spec!r}"
        )
    module, _, func = spec.partition(":")
    if not module or not func:
        raise ValueError(f"callable {spec!r} has empty module or function part")
    return module, func


@dataclass
class _Completed:
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool


def _run_subprocess(
    module: str,
    func: str,
    args: Dict[str, Any],
    timeout_s: int,
    cwd: Path,
    env: Dict[str, str],
) -> _Completed:
    """Invoke the bootstrap script in a child python, enforcing timeout."""
    bootstrap = _BOOTSTRAP % {"module": module, "func": func}
    full_env = dict(env)
    full_env["AWP_PHASE_ARGS_JSON"] = json.dumps(args)
    # Propagate the parent's sys.path into PYTHONPATH so the child can
    # import modules that were installed in editable mode or added to
    # sys.path programmatically (e.g. ``monkeypatch.syspath_prepend``
    # in tests, or a workflow-local ``agents/`` directory). This matches
    # the spec's sandbox requirement — PYTHONPATH is explicitly preserved
    # — while guaranteeing the child has at least as much reach as the
    # parent interpreter.
    existing_pythonpath = full_env.get("PYTHONPATH", "")
    parent_paths = [p for p in sys.path if p and p != ""]
    if existing_pythonpath:
        combined = existing_pythonpath + os.pathsep + os.pathsep.join(parent_paths)
    else:
        combined = os.pathsep.join(parent_paths)
    full_env["PYTHONPATH"] = combined
    cmd = [sys.executable, "-c", bootstrap]
    logger.debug(
        "deterministic phase subprocess: %s  cwd=%s  timeout=%ss",
        shlex.join(cmd),
        cwd,
        timeout_s,
    )
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd),
            env=full_env,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
        return _Completed(
            returncode=proc.returncode,
            stdout=proc.stdout,
            stderr=proc.stderr,
            timed_out=False,
        )
    except subprocess.TimeoutExpired as exc:
        return _Completed(
            returncode=-1,
            stdout=(exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")),
            stderr=(exc.stderr.decode() if isinstance(exc.stderr, bytes) else (exc.stderr or "")),
            timed_out=True,
        )


def _parse_bootstrap_output(raw: str) -> tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """Extract the structured payload from bootstrap stdout.

    Returns ``(result, error)`` where at most one is non-None. If the
    marker is missing (e.g. user callable printed its own stdout and
    crashed before the marker), both are None and the caller should
    treat the phase as failed.
    """
    marker = "AWP_PHASE_RESULT:"
    idx = raw.rfind(marker)
    if idx < 0:
        return None, None
    payload = raw[idx + len(marker) :].strip()
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return None, None
    if data.get("ok"):
        res = data.get("result")
        return (res if isinstance(res, dict) else {}, None)
    return None, data.get("error") or {"error": "unknown"}


class DeterministicPhaseRunner:
    """Runs deterministic phases declared under ``orchestration.phases``.

    Per spec §9, the runner MUST:
      * resolve the callable via ``importlib`` (no ``eval``, no shell);
      * enforce ``timeout_s`` via :func:`subprocess.run`;
      * scrub secrets from the child env;
      * evaluate every invariant against the callable's output.

    The runner is intentionally decoupled from the DAG runner: it takes
    a :class:`DeterministicPhase` + :class:`ExecutionContext` and returns
    a :class:`PhaseResult`. The DAG runner is responsible for assembling
    the context (workspace / output dirs, state snapshot) and for
    persisting the result under ``output/<run_id>/phase_<id>/``.
    """

    def __init__(
        self,
        workflow_dir: Path,
        logger: Optional[logging.Logger] = None,
        sandbox: Optional[SandboxConfig] = None,
    ) -> None:
        self.workflow_dir = Path(workflow_dir)
        self.logger = logger or logging.getLogger(__name__)
        # sandbox is accepted for interface symmetry with the delegation-
        # loop runner's SandboxEnforcement envelope, but the current
        # scope (Phase 2) only uses cwd + env scrubbing. Additional
        # sandbox modes (docker, seccomp) land in Phase 2.x.
        self.sandbox = sandbox

    def run(
        self,
        phase: DeterministicPhase,
        context: ExecutionContext,
        invariant_registry: Optional[InvariantCheckRegistry] = None,
    ) -> PhaseResult:
        """Execute a single deterministic phase and return its result.

        ``context.output_dir`` / ``context.workspace_dir`` must be
        directories that already exist; the runner does not create them.
        ``invariant_registry`` defaults to the module-level registry.
        """
        registry = invariant_registry or InvariantCheckRegistry()
        started = time.monotonic()

        # Validate the callable spec up-front — a malformed spec is an
        # R33 error at validation time, but we still guard at runtime
        # because a config may be constructed programmatically.
        try:
            module, func = _parse_callable(phase.callable)
        except ValueError as exc:
            return PhaseResult(
                phase_id=phase.id,
                status="failed",
                reason=f"deterministic_failure: {exc}",
                duration_s=time.monotonic() - started,
            )

        # Runtime re-check of the R33 import-purity rule: if the
        # callable's module imports ``awp.runtime.llm``, reject.
        # Cheap grep on the source file when available; skipped silently
        # when the module is pure-Python-less (e.g. C extension) since
        # in that case there can be no hidden LLM import either.
        purity_reason = self._check_runtime_purity(module)
        if purity_reason is not None:
            return PhaseResult(
                phase_id=phase.id,
                status="failed",
                reason=f"deterministic_failure: {purity_reason}",
                duration_s=time.monotonic() - started,
            )

        # Substitute placeholders in args.
        resolved_args = _substitute_args(dict(phase.args or {}), context)

        # Prepare environment.
        env = _scrub_secrets(dict(os.environ))

        cwd = context.workspace_dir if context.workspace_dir.exists() else self.workflow_dir
        completed = _run_subprocess(
            module=module,
            func=func,
            args=resolved_args,
            timeout_s=phase.timeout_s,
            cwd=cwd,
            env=env,
        )

        duration_s = time.monotonic() - started

        if completed.timed_out:
            self.logger.warning(
                "Deterministic phase %s timed out after %ss",
                phase.id,
                phase.timeout_s,
            )
            return PhaseResult(
                phase_id=phase.id,
                status="partial",
                reason="deterministic_timeout",
                duration_s=duration_s,
                stdout=completed.stdout,
                stderr=completed.stderr,
                returncode=completed.returncode,
            )

        result_dict, err_dict = _parse_bootstrap_output(completed.stdout)
        if err_dict is not None:
            self.logger.error(
                "Deterministic phase %s callable raised: %s",
                phase.id,
                err_dict,
            )
            return PhaseResult(
                phase_id=phase.id,
                status="failed",
                reason=(
                    f"deterministic_failure: {err_dict.get('error')}: "
                    f"{err_dict.get('detail', '')}"
                ),
                duration_s=duration_s,
                stdout=completed.stdout,
                stderr=completed.stderr,
                returncode=completed.returncode,
                callable_result={"error": err_dict},
            )

        if completed.returncode != 0 or result_dict is None:
            return PhaseResult(
                phase_id=phase.id,
                status="failed",
                reason=(
                    "deterministic_failure: "
                    f"returncode={completed.returncode}, "
                    f"no structured result in stdout"
                ),
                duration_s=duration_s,
                stdout=completed.stdout,
                stderr=completed.stderr,
                returncode=completed.returncode,
            )

        # Run invariants — first-failure semantics for terminal reason,
        # but every invariant result is recorded for observability.
        per_invariant: list[InvariantCheckResult] = []
        first_fail: Optional[InvariantCheckResult] = None
        unknown_kind: Optional[str] = None
        for inv in phase.invariants:
            if not registry.has(inv.kind):
                unknown_kind = inv.kind
                ir = InvariantCheckResult(
                    kind=inv.kind,
                    ok=False,
                    reason=f"unknown invariant kind: {inv.kind}",
                )
            else:
                ir = registry.run(inv, result_dict, context)
            per_invariant.append(ir)
            if not ir.ok and first_fail is None:
                first_fail = ir

        if unknown_kind is not None:
            return PhaseResult(
                phase_id=phase.id,
                status="failed",
                reason="unknown_invariant_kind",
                duration_s=duration_s,
                stdout=completed.stdout,
                stderr=completed.stderr,
                returncode=completed.returncode,
                callable_result=result_dict,
                invariants=per_invariant,
            )

        if first_fail is not None:
            return PhaseResult(
                phase_id=phase.id,
                status="partial",
                reason=f"invariant_{first_fail.kind}_violated",
                duration_s=duration_s,
                stdout=completed.stdout,
                stderr=completed.stderr,
                returncode=completed.returncode,
                callable_result=result_dict,
                invariants=per_invariant,
            )

        return PhaseResult(
            phase_id=phase.id,
            status="complete",
            reason="",
            duration_s=duration_s,
            stdout=completed.stdout,
            stderr=completed.stderr,
            returncode=completed.returncode,
            callable_result=result_dict,
            invariants=per_invariant,
        )

    def _check_runtime_purity(self, module_name: str) -> Optional[str]:
        """Grep the callable's source for forbidden LLM imports.

        Mirrors the R33 static check in the validator. Returns a
        human-readable reason if a forbidden import is found, else
        ``None``.
        """
        try:
            import importlib.util
            import re as _re

            spec = importlib.util.find_spec(module_name)
        except (ImportError, ValueError, ModuleNotFoundError):
            return None
        origin = getattr(spec, "origin", None) if spec is not None else None
        if not origin or origin == "built-in":
            return None
        p = Path(origin)
        if not p.is_file():
            return None
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None

        imp_re = _re.compile(r"^\s*(?:from|import)\s+([a-zA-Z_][a-zA-Z0-9_.]*)")
        forbidden_exact = {"awp.runtime.llm", "openai", "anthropic", "langchain"}
        forbidden_tokens = _re.compile(r"\b(llm|openai|anthropic|langchain)\b")
        for line in text.splitlines():
            m = imp_re.match(line)
            if not m:
                continue
            imported = m.group(1)
            if imported in forbidden_exact:
                return (
                    f"callable module '{module_name}' imports forbidden "
                    f"module '{imported}' (R33 purity violation)"
                )
            tokens = imported.split(".")
            if any(forbidden_tokens.search(t) for t in tokens):
                return (
                    f"callable module '{module_name}' imports module "
                    f"'{imported}' matching forbidden LLM-token pattern "
                    f"(R33 purity violation)"
                )
        return None
