"""Result dataclasses for deterministic phase execution (R33, Phase 2).

The runner returns a :class:`PhaseResult` that maps deterministically to
the run's terminal-status aggregation per spec §9:

* all invariants pass              -> ``status="complete"``
* timeout breach                   -> ``status="partial"``, reason ``deterministic_timeout``
* invariant violation              -> ``status="partial"``, reason ``invariant_<kind>_violated``
* callable raises / non-zero exit  -> ``status="failed"``, reason ``deterministic_failure``
* unknown invariant kind           -> ``status="failed"``, reason ``unknown_invariant_kind``

The structure is intentionally plain dataclasses (no Pydantic) so the
runtime can serialise results without paying a validation round-trip
per phase.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal, Optional

PhaseStatus = Literal["complete", "partial", "failed"]


@dataclass
class InvariantCheckResult:
    """Outcome of a single invariant check."""

    kind: str
    ok: bool
    reason: str = ""
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PhaseResult:
    """Outcome of a single deterministic-phase execution."""

    phase_id: str
    status: PhaseStatus
    reason: str = ""
    duration_s: float = 0.0
    stdout: str = ""
    stderr: str = ""
    returncode: Optional[int] = None
    callable_result: Optional[dict[str, Any]] = None
    invariants: list[InvariantCheckResult] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        # ``invariants`` is already a list of dicts from ``asdict``.
        return d
