"""Invariant check registry for deterministic phases (R33, Phase 2).

Implements the normative minimum set from spec §9 — 6 kinds. Additional
kinds may be registered at runtime via :func:`register_invariant`; unknown
kinds surface in the phase result as ``status=failed`` /
``reason=unknown_invariant_kind``.

Each check is a callable with the signature::

    check(inv: Invariant, result: dict, ctx: ExecutionContext) -> InvariantCheckResult

where ``result`` is the JSON-deserialised return value of the phase
callable (or ``{}`` if the callable did not return anything structured),
and ``ctx`` provides access to the workflow directory, output directory,
and state. Paths inside the invariant may reference ``${output}`` and
``${workspace}`` placeholders — the runner substitutes them before
dispatch.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from awp.models.orchestration import Invariant

from .result import InvariantCheckResult

# ---------------------------------------------------------------------------
# Execution context — small passive holder threaded through checks.
# ---------------------------------------------------------------------------


@dataclass
class ExecutionContext:
    """Passive context passed to invariant checks.

    Attributes:
        workflow_dir: Absolute path to the workflow root.
        workspace_dir: Absolute path to the run's workspace dir.
        output_dir: Absolute path to the run's output dir.
        state: Read-only view of the DAG state at the time the phase ran.
    """

    workflow_dir: Path
    workspace_dir: Path
    output_dir: Path
    state: Dict[str, Any]


# ---------------------------------------------------------------------------
# Individual check implementations.
# ---------------------------------------------------------------------------

# Maximum file size we read for text-based checks (regex_absent /
# regex_present). Bounded to prevent a pathological 2 GB file from
# stalling the phase. 100 MB is comfortably above any realistic
# text artifact a deterministic phase would produce.
_MAX_TEXT_READ_BYTES = 100 * 1024 * 1024


def _resolve_path(raw: Optional[str], ctx: ExecutionContext) -> Optional[Path]:
    """Resolve a path string against the execution context.

    Substitutes ``${output}`` / ``${workspace}`` / ``${workflow_dir}``
    tokens (both with and without trailing slash), then returns an
    absolute :class:`Path`. Returns ``None`` for empty/None input.
    """
    if not raw:
        return None
    s = str(raw)
    s = s.replace("${output}", str(ctx.output_dir))
    s = s.replace("${workspace}", str(ctx.workspace_dir))
    s = s.replace("${workflow_dir}", str(ctx.workflow_dir))
    p = Path(s)
    if not p.is_absolute():
        p = ctx.workflow_dir / p
    return p


def check_file_exists(
    inv: Invariant, result: Dict[str, Any], ctx: ExecutionContext
) -> InvariantCheckResult:
    path = _resolve_path(inv.path, ctx)
    if path is None:
        return InvariantCheckResult(kind="file_exists", ok=False, reason="missing path")
    exists = path.exists() and path.is_file()
    size = path.stat().st_size if exists else 0
    ok = exists and size > 0
    reason = ""
    if not exists:
        reason = f"file does not exist: {path}"
    elif size == 0:
        reason = f"file is empty: {path}"
    return InvariantCheckResult(
        kind="file_exists",
        ok=ok,
        reason=reason,
        detail={"path": str(path), "size": size},
    )


def check_file_size_range(
    inv: Invariant, result: Dict[str, Any], ctx: ExecutionContext
) -> InvariantCheckResult:
    path = _resolve_path(inv.path, ctx)
    if path is None or not path.exists():
        return InvariantCheckResult(
            kind="file_size_range",
            ok=False,
            reason=f"file does not exist: {path}",
            detail={"path": str(path) if path else None},
        )
    size = path.stat().st_size
    lo = inv.min_bytes or 0
    hi = inv.max_bytes if inv.max_bytes is not None else float("inf")
    ok = lo <= size <= hi
    reason = (
        "" if ok else f"size {size} not in [{lo}, {hi}]"
    )
    return InvariantCheckResult(
        kind="file_size_range",
        ok=ok,
        reason=reason,
        detail={"path": str(path), "size": size, "min": lo, "max": inv.max_bytes},
    )


def _read_text(path: Path) -> str:
    with open(path, "rb") as fh:
        data = fh.read(_MAX_TEXT_READ_BYTES + 1)
    if len(data) > _MAX_TEXT_READ_BYTES:
        # Truncate silently for the scan; noting the cap in detail.
        data = data[:_MAX_TEXT_READ_BYTES]
    return data.decode("utf-8", errors="replace")


def check_regex_absent(
    inv: Invariant, result: Dict[str, Any], ctx: ExecutionContext
) -> InvariantCheckResult:
    path = _resolve_path(inv.path, ctx)
    if path is None or not path.exists():
        return InvariantCheckResult(
            kind="regex_absent",
            ok=False,
            reason=f"file does not exist: {path}",
            detail={"path": str(path) if path else None},
        )
    try:
        content = _read_text(path)
    except OSError as exc:
        return InvariantCheckResult(
            kind="regex_absent",
            ok=False,
            reason=f"cannot read {path}: {exc}",
            detail={"path": str(path)},
        )
    try:
        pat = re.compile(inv.pattern or "")
    except re.error as exc:
        return InvariantCheckResult(
            kind="regex_absent",
            ok=False,
            reason=f"invalid pattern: {exc}",
            detail={"pattern": inv.pattern},
        )
    m = pat.search(content)
    ok = m is None
    reason = "" if ok else f"pattern '{inv.pattern}' found: {m.group(0)[:80]!r}"
    return InvariantCheckResult(
        kind="regex_absent",
        ok=ok,
        reason=reason,
        detail={
            "path": str(path),
            "pattern": inv.pattern,
            "matched_at": m.start() if m else None,
        },
    )


def check_regex_present(
    inv: Invariant, result: Dict[str, Any], ctx: ExecutionContext
) -> InvariantCheckResult:
    path = _resolve_path(inv.path, ctx)
    if path is None or not path.exists():
        return InvariantCheckResult(
            kind="regex_present",
            ok=False,
            reason=f"file does not exist: {path}",
            detail={"path": str(path) if path else None},
        )
    try:
        content = _read_text(path)
    except OSError as exc:
        return InvariantCheckResult(
            kind="regex_present",
            ok=False,
            reason=f"cannot read {path}: {exc}",
            detail={"path": str(path)},
        )
    try:
        pat = re.compile(inv.pattern or "")
    except re.error as exc:
        return InvariantCheckResult(
            kind="regex_present",
            ok=False,
            reason=f"invalid pattern: {exc}",
            detail={"pattern": inv.pattern},
        )
    m = pat.search(content)
    ok = m is not None
    reason = "" if ok else f"pattern '{inv.pattern}' not found"
    return InvariantCheckResult(
        kind="regex_present",
        ok=ok,
        reason=reason,
        detail={
            "path": str(path),
            "pattern": inv.pattern,
            "matched_at": m.start() if m else None,
        },
    )


def check_exit_code(
    inv: Invariant, result: Dict[str, Any], ctx: ExecutionContext
) -> InvariantCheckResult:
    actual = result.get("exit_code") if isinstance(result, dict) else None
    ok = actual == inv.expected
    reason = (
        "" if ok else f"exit_code {actual!r} != expected {inv.expected!r}"
    )
    return InvariantCheckResult(
        kind="exit_code",
        ok=ok,
        reason=reason,
        detail={"expected": inv.expected, "actual": actual},
    )


def check_python_predicate(
    inv: Invariant, result: Dict[str, Any], ctx: ExecutionContext
) -> InvariantCheckResult:
    if not inv.module or not inv.function:
        return InvariantCheckResult(
            kind="python_predicate",
            ok=False,
            reason="python_predicate requires module + function",
        )
    try:
        import importlib

        mod = importlib.import_module(inv.module)
    except ImportError as exc:
        return InvariantCheckResult(
            kind="python_predicate",
            ok=False,
            reason=f"cannot import module '{inv.module}': {exc}",
            detail={"module": inv.module, "function": inv.function},
        )
    fn: Optional[Callable[..., Any]] = getattr(mod, inv.function, None)
    if fn is None or not callable(fn):
        return InvariantCheckResult(
            kind="python_predicate",
            ok=False,
            reason=f"function '{inv.function}' not callable on module '{inv.module}'",
            detail={"module": inv.module, "function": inv.function},
        )
    try:
        verdict = fn(result)
    except Exception as exc:  # noqa: BLE001 — user code
        return InvariantCheckResult(
            kind="python_predicate",
            ok=False,
            reason=f"predicate raised: {type(exc).__name__}: {exc}",
            detail={"module": inv.module, "function": inv.function},
        )
    ok = bool(verdict)
    reason = "" if ok else f"predicate returned falsy value: {verdict!r}"
    return InvariantCheckResult(
        kind="python_predicate",
        ok=ok,
        reason=reason,
        detail={
            "module": inv.module,
            "function": inv.function,
            "verdict": bool(verdict),
        },
    )


# ---------------------------------------------------------------------------
# Registry — mapping kind -> check callable.
# ---------------------------------------------------------------------------


_CheckFn = Callable[[Invariant, Dict[str, Any], ExecutionContext], InvariantCheckResult]
INVARIANT_CHECKS: Dict[str, _CheckFn] = {
    "file_exists": check_file_exists,
    "file_size_range": check_file_size_range,
    "regex_absent": check_regex_absent,
    "regex_present": check_regex_present,
    "exit_code": check_exit_code,
    "python_predicate": check_python_predicate,
}


def register_invariant(
    kind: str,
    check: Callable[[Invariant, Dict[str, Any], ExecutionContext], InvariantCheckResult],
) -> None:
    """Register an additional invariant kind.

    Workflow authors MAY extend the normative minimum set this way.
    The registered name MUST NOT collide with a builtin kind — caller
    is responsible for choosing distinct names (typically namespaced,
    e.g. ``mycorp.docker_layer_count``).
    """
    if kind in INVARIANT_CHECKS:
        raise ValueError(f"Invariant kind '{kind}' is already registered")
    INVARIANT_CHECKS[kind] = check


class InvariantCheckRegistry:
    """Thin wrapper around the module-level registry for introspection.

    Kept as a class so callers can pass an explicit registry instance
    in tests without touching the module-global dict.
    """

    def __init__(
        self,
        checks: Optional[
            Dict[
                str,
                Callable[[Invariant, Dict[str, Any], ExecutionContext], InvariantCheckResult],
            ]
        ] = None,
    ) -> None:
        self._checks = dict(checks) if checks is not None else INVARIANT_CHECKS

    def has(self, kind: str) -> bool:
        return kind in self._checks

    def run(
        self,
        inv: Invariant,
        result: Dict[str, Any],
        ctx: ExecutionContext,
    ) -> InvariantCheckResult:
        fn = self._checks.get(inv.kind)
        if fn is None:
            return InvariantCheckResult(
                kind=inv.kind,
                ok=False,
                reason=f"unknown invariant kind: {inv.kind}",
            )
        return fn(inv, result, ctx)


# Silence unused-import warnings in slim builds.
__all__ = [
    "INVARIANT_CHECKS",
    "ExecutionContext",
    "InvariantCheckRegistry",
    "check_exit_code",
    "check_file_exists",
    "check_file_size_range",
    "check_python_predicate",
    "check_regex_absent",
    "check_regex_present",
    "register_invariant",
]

# ``os`` imported for symmetry with potential future checks; keep to avoid
# re-import churn if a future check needs it.
_ = os
