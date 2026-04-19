"""Deterministic budget scaling for refinement iterations.

Counts and token caps are halved with ``ceil`` (floored at 1). Wall
time is halved from the observed wall time of the seed (not its cap),
floored at 60 s. Depth is structural and passes through unchanged.
"""

from __future__ import annotations

from math import ceil
from typing import Any

_COUNT_FIELDS = ("max_loops", "max_total_workers", "max_tool_calls")
_COUNT_FLOOR = 1
_TOKEN_FLOOR = 1
_WALL_FLOOR = 60


def budget_for_iteration(
    *,
    seed_budget: dict[str, Any],
    observed_wall_time: float,
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for f in _COUNT_FIELDS:
        v = int(seed_budget.get(f, 0))
        out[f] = max(_COUNT_FLOOR, ceil(v * 0.5)) if v else _COUNT_FLOOR

    tokens = int(seed_budget.get("max_total_tokens", 0))
    out["max_total_tokens"] = max(_TOKEN_FLOOR, tokens // 2) if tokens else _TOKEN_FLOOR

    if observed_wall_time and observed_wall_time > 0:
        wall_seed = float(observed_wall_time)
    else:
        wall_seed = float(seed_budget.get("max_wall_time", 0))
    out["max_wall_time"] = (
        max(_WALL_FLOOR, int(wall_seed * 0.5)) if wall_seed else _WALL_FLOOR
    )

    out["max_depth"] = int(seed_budget.get("max_depth", 1))
    return out
