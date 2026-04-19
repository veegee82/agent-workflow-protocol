"""Layer 0 Output Contract — data models and check protocol.

This module defines the types that every Layer-0 (L0) output-contract
check consumes and returns. L0 checks are **fast, bit-level, and
domain-agnostic**: they scan worker output for trivial defects (stale
placeholders, text loops, append leaks, duplicate headings, unbalanced
delimiters, malformed JSON) without spending any LLM tokens.

Conformance requirements (per spec R34):

* Checks MUST be **synchronous** and **side-effect free**: no network,
  no subprocesses, no model calls. An L0 check that talks to an LLM
  defeats the entire purpose of the layer.
* Checks MUST return within **100 ms on a 10 MB input**. The contract
  runs once per worker output per COMPLETE attempt; a slow check
  degrades the whole loop.
* Checks MUST be pure functions of ``(path, content, context)``. The
  same input MUST always produce the same ``CheckResult``.

See ``packages/awp-runtime/src/awp/runtime/critique/l0_validator.py``
for the bundled default checks and the orchestrator class.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

__all__ = [
    "OutputContract",
    "CheckResult",
    "OutputContractCheck",
]


@dataclass
class OutputContract:
    """Declarative configuration of the L0 contract chain.

    ``checks`` may contain the special token ``"default"`` which the
    validator expands into the 6 built-in checks (order: ``no_placeholder``
    → ``no_text_loop`` → ``file_size_delta`` → ``no_duplicate_headings``
    → ``balanced_delimiters`` → ``json_valid_if_claimed``).

    ``extra`` lists workflow-specific checks. Each entry is a dict with at
    least ``name: str`` and ``implementation: "module.path:ClassName"``.
    The implementation MUST conform to the ``OutputContractCheck``
    protocol.

    ``enabled`` lets users disable the whole contract chain (the L0 gate
    becomes a no-op; the gate chain falls through to the critique gate
    unchanged). Default ``True``.
    """

    checks: list[str] = field(default_factory=lambda: ["default"])
    extra: list[dict[str, Any]] = field(default_factory=list)
    enabled: bool = True


@dataclass
class CheckResult:
    """Outcome of a single L0 check on a single artifact.

    Fields
    ------
    ok : bool
        ``True`` when the artifact passes the check (no defect), ``False``
        when a violation was detected.
    check : str
        The name of the check (matches the key used in the L0 chain
        registry — e.g. ``"no_placeholder"``).
    reason : str
        Short, user-facing summary of why the check rejected. Empty
        string when ``ok`` is True.
    severity : str
        ``"error"`` (default) to reject hard and short-circuit the chain;
        ``"warning"`` to record the issue without halting (non-short-
        circuit mode). ``"info"`` is advisory only.
    violating_path : str
        Absolute or workflow-relative path of the offending artifact.
        Empty when the check runs on in-memory content without a path.
    detail : dict[str, Any]
        Free-form, JSON-serialisable diagnostics for downstream
        consumers (repair-nudge assembly, scorecards, the UI panel).
    """

    ok: bool
    check: str
    reason: str = ""
    severity: str = "error"  # error | warning | info
    violating_path: str = ""
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "check": self.check,
            "reason": self.reason,
            "severity": self.severity,
            "violating_path": self.violating_path,
            "detail": self.detail,
        }


@runtime_checkable
class OutputContractCheck(Protocol):
    """Protocol every L0 check implementation must satisfy.

    An implementation is a callable (class instance with ``__call__`` or
    a free function) that accepts a path, the file's bytes, and an
    optional context dict and returns a :class:`CheckResult`.

    Contract
    --------
    * MUST be synchronous (no ``async def``).
    * MUST NOT perform I/O beyond inspecting the provided ``content``.
    * MUST NOT invoke an LLM client, spawn subprocesses, or open sockets.
    * MUST complete within 100 ms on a 10 MB ``content``.
    * SHOULD populate ``violating_path`` with the ``path`` argument
      (or the sub-path when the defect is in a collection artifact).

    The ``context`` dict may include:

    * ``previous_size``: Optional[int] — byte size of the previous
      repair attempt of the same artifact (used by ``file_size_delta``).
    * ``attempt``: int — 1-indexed repair attempt number.
    * ``claimed_format``: Optional[str] — the runtime's declared format
      for this artifact (e.g. ``"json"`` for non-``.json`` filenames).

    Implementations MUST tolerate missing keys gracefully.
    """

    @property
    def name(self) -> str:
        """Stable, dotless identifier — used in events and config filters."""
        ...

    def __call__(
        self,
        path: str,
        content: bytes,
        context: dict[str, Any] | None = None,
    ) -> CheckResult:
        ...
