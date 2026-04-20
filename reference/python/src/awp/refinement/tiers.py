"""Refinement model tiering (low / mid / high).

Coarse-to-fine annealing across the N iterations of a refinement session:
*low runs early* (weak/cheap, surfaces structural defects for the gradient
extractor), *high runs late* (precise, polishes the residual). The mapping
is a pure function of ``(k, N)`` with a thirds-proportional rule plus two
explicit small-N cases. See:

* ``docs/refinement.md`` §6.6
* ``docs/superpowers/specs/2026-04-20-refinement-model-tiers-design.md``

The module has no runtime dependencies beyond pydantic and the stdlib;
it performs no I/O. ``RefinementLoop`` consumes :class:`TierPlan` as a
read-only plan constructed at the CLI / API boundary.
"""

from __future__ import annotations

import math
from typing import Literal, Optional

from pydantic import BaseModel


class ModelPair(BaseModel):
    """One tier's (manager, worker) model configuration.

    Either field may be ``None`` / empty-string; the resolver falls back
    to the seed's corresponding model (see :meth:`TierPlan.for_iteration`).
    """

    manager: Optional[str] = None
    worker: Optional[str] = None


TierLabel = Literal["low", "mid", "high"]


class TierResolution(BaseModel):
    """The resolved tier + model pair for a single iteration.

    Exactly what :class:`~awp.refinement.loop.RefinementLoop` passes to the
    workflow factory per iteration.
    """

    tier: TierLabel
    manager_model: Optional[str]
    worker_model: Optional[str]


class TierPlan(BaseModel):
    """Immutable resolution plan for one refinement session.

    Constructed at the API / CLI boundary from user-supplied tier pairs
    plus the seed run's manager / worker models (used as fallback when a
    tier field is empty).
    """

    low: ModelPair = ModelPair()
    mid: ModelPair = ModelPair()
    high: ModelPair = ModelPair()
    seed_manager: Optional[str] = None
    seed_worker: Optional[str] = None

    def tier_for(self, k: int, n: int) -> TierLabel:
        """Return the tier label for iteration ``k`` of ``n`` (1-indexed).

        Mapping (spec §5):

        * ``n == 1`` → ``"high"``
        * ``n == 2`` → ``"low"`` if ``k == 1`` else ``"high"``
        * otherwise: thirds-proportional with
          ``low_end = ceil(n / 3)`` and ``high_start = n - floor(n / 3) + 1``

        :raises ValueError: if ``k`` or ``n`` is out of range.
        """
        if n <= 0 or k < 1 or k > n:
            raise ValueError(f"invalid (k, n) = ({k}, {n})")
        if n == 1:
            return "high"
        if n == 2:
            return "low" if k == 1 else "high"
        low_end = math.ceil(n / 3)
        high_start = n - (n // 3) + 1
        if k <= low_end:
            return "low"
        if k >= high_start:
            return "high"
        return "mid"

    def for_iteration(self, k: int, n: int) -> TierResolution:
        """Resolve iteration ``k`` of ``n`` to a :class:`TierResolution`.

        Per-role fallback: an empty / ``None`` tier field falls back to the
        corresponding ``seed_*`` model. Empty string and ``None`` are
        treated identically.
        """
        tier = self.tier_for(k, n)
        pair: ModelPair = getattr(self, tier)
        manager = (pair.manager or None) or self.seed_manager
        worker = (pair.worker or None) or self.seed_worker
        return TierResolution(
            tier=tier,
            manager_model=manager,
            worker_model=worker,
        )

    def is_trivial(self) -> bool:
        """True iff every tier field is empty — tiering is a no-op."""
        return not any(
            [
                self.low.manager,
                self.low.worker,
                self.mid.manager,
                self.mid.worker,
                self.high.manager,
                self.high.worker,
            ]
        )
