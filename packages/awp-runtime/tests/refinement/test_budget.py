"""Unit tests for refinement budget scaling."""

from __future__ import annotations

from awp.refinement.budget import budget_for_iteration


def test_halves_all_cost_dimensions() -> None:
    out = budget_for_iteration(
        seed_budget={
            "max_loops": 20,
            "max_total_workers": 40,
            "max_total_tokens": 1_000_000,
            "max_wall_time": 3600,
            "max_depth": 4,
            "max_tool_calls": 600,
        },
        observed_wall_time=1800,
    )
    assert out["max_loops"] == 10
    assert out["max_total_workers"] == 20
    assert out["max_total_tokens"] == 500_000
    assert out["max_tool_calls"] == 300
    # wall-time uses observed, not cap, halved.
    assert out["max_wall_time"] == 900
    # depth is structural, unchanged.
    assert out["max_depth"] == 4


def test_floor_clamps() -> None:
    out = budget_for_iteration(
        seed_budget={
            "max_loops": 1,
            "max_total_workers": 1,
            "max_total_tokens": 10,
            "max_wall_time": 30,
            "max_depth": 1,
            "max_tool_calls": 1,
        },
        observed_wall_time=10,
    )
    assert out["max_loops"] == 1
    assert out["max_total_workers"] == 1
    assert out["max_total_tokens"] == 5
    assert out["max_tool_calls"] == 1
    # wall-time floor 60s.
    assert out["max_wall_time"] == 60
    assert out["max_depth"] == 1


def test_observed_wall_time_zero_falls_back_to_cap() -> None:
    out = budget_for_iteration(
        seed_budget={
            "max_loops": 10,
            "max_total_workers": 10,
            "max_total_tokens": 1000,
            "max_wall_time": 600,
            "max_depth": 2,
            "max_tool_calls": 100,
        },
        observed_wall_time=0,
    )
    # No observed signal → scale from cap instead.
    assert out["max_wall_time"] == 300
