"""Deterministic Phase Runner (R33, Phase 2).

Exports the runner, result dataclasses, invariant registry, and
execution context. The public surface mirrors the shape of the
``critique/`` package — a small set of types other runtime code can
import without reaching into module internals.
"""

from __future__ import annotations

from .invariants import (
    INVARIANT_CHECKS,
    ExecutionContext,
    InvariantCheckRegistry,
    register_invariant,
)
from .result import InvariantCheckResult, PhaseResult, PhaseStatus
from .runner import DeterministicPhaseRunner

__all__ = [
    "DeterministicPhaseRunner",
    "ExecutionContext",
    "INVARIANT_CHECKS",
    "InvariantCheckRegistry",
    "InvariantCheckResult",
    "PhaseResult",
    "PhaseStatus",
    "register_invariant",
]
