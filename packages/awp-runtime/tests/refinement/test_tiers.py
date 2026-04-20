"""Unit tests for :mod:`awp.refinement.tiers` (spec §13.1)."""

from __future__ import annotations

import pytest

from awp.refinement.tiers import ModelPair, TierPlan

# ---------------------------------------------------------------------------
# The §5 table (N, k→tier) — single source of truth for the mapping tests.
# ---------------------------------------------------------------------------

MAPPING_TABLE: dict[int, list[str]] = {
    1:  ["high"],
    2:  ["low", "high"],
    3:  ["low", "mid", "high"],
    4:  ["low", "low", "mid", "high"],
    5:  ["low", "low", "mid", "mid", "high"],
    6:  ["low", "low", "mid", "mid", "high", "high"],
    7:  ["low", "low", "low", "mid", "mid", "high", "high"],
    8:  ["low", "low", "low", "mid", "mid", "mid", "high", "high"],
    9:  ["low", "low", "low", "mid", "mid", "mid", "high", "high", "high"],
    10: ["low", "low", "low", "low", "mid", "mid", "mid", "high", "high", "high"],
}


def _flatten_table() -> list[tuple[int, int, str]]:
    """Expand the table into (n, k, tier) triples for parametrization."""
    triples: list[tuple[int, int, str]] = []
    for n, tiers in MAPPING_TABLE.items():
        for k, tier in enumerate(tiers, start=1):
            triples.append((n, k, tier))
    return triples


# ---------------------------------------------------------------------------
# tier_for — exact mapping per §5
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("n,k,expected", _flatten_table())
def test_tier_for_matches_spec_table(n: int, k: int, expected: str) -> None:
    plan = TierPlan()
    assert plan.tier_for(k, n) == expected


def test_tier_for_all_n_at_least_one_of_each_tier_for_n_ge_3() -> None:
    """Invariant #1 (§5): for all N ≥ 3, each tier has at least one iter."""
    plan = TierPlan()
    for n in range(3, 11):
        tiers = [plan.tier_for(k, n) for k in range(1, n + 1)]
        assert "low" in tiers, f"N={n}: missing low"
        assert "mid" in tiers, f"N={n}: missing mid"
        assert "high" in tiers, f"N={n}: missing high"


def test_tier_for_is_monotonic() -> None:
    """Invariant #2 (§5): once a later tier fires, no earlier tier follows."""
    order = {"low": 0, "mid": 1, "high": 2}
    plan = TierPlan()
    for n in range(1, 11):
        ranks = [order[plan.tier_for(k, n)] for k in range(1, n + 1)]
        for a, b in zip(ranks, ranks[1:]):
            assert a <= b, f"N={n}: non-monotonic tier sequence {ranks}"


def test_tier_for_count_inequality_for_n_ge_3() -> None:
    """Invariant #3 (§5): count(low) ≥ count(mid) ≥ count(high)."""
    plan = TierPlan()
    for n in range(3, 11):
        tiers = [plan.tier_for(k, n) for k in range(1, n + 1)]
        counts = {t: tiers.count(t) for t in ("low", "mid", "high")}
        assert counts["low"] >= counts["mid"] >= counts["high"], (
            f"N={n}: counts={counts} violates low ≥ mid ≥ high"
        )


# ---------------------------------------------------------------------------
# tier_for — invalid inputs raise ValueError (§6)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "k,n",
    [
        (0, 5),
        (-1, 5),
        (6, 5),
        (1, 0),
        (1, -1),
        (3, 2),
    ],
)
def test_tier_for_raises_on_out_of_range(k: int, n: int) -> None:
    with pytest.raises(ValueError):
        TierPlan().tier_for(k, n)


# ---------------------------------------------------------------------------
# for_iteration — fallback semantics (§7)
# ---------------------------------------------------------------------------


def test_for_iteration_only_high_manager_set_falls_back_for_others() -> None:
    """User fills only ``high.manager`` — low/mid yield seed pair, high mixes."""
    plan = TierPlan(
        high=ModelPair(manager="gpt-5.4"),
        seed_manager="seed-mgr",
        seed_worker="seed-wkr",
    )
    n = 5  # mapping: L, L, M, M, H
    low_res = plan.for_iteration(1, n)
    mid_res = plan.for_iteration(3, n)
    high_res = plan.for_iteration(5, n)

    assert low_res.tier == "low"
    assert low_res.manager_model == "seed-mgr"
    assert low_res.worker_model == "seed-wkr"

    assert mid_res.tier == "mid"
    assert mid_res.manager_model == "seed-mgr"
    assert mid_res.worker_model == "seed-wkr"

    assert high_res.tier == "high"
    assert high_res.manager_model == "gpt-5.4"
    assert high_res.worker_model == "seed-wkr"


def test_for_iteration_all_tiers_fully_set_no_seed_fallback() -> None:
    plan = TierPlan(
        low=ModelPair(manager="low-m", worker="low-w"),
        mid=ModelPair(manager="mid-m", worker="mid-w"),
        high=ModelPair(manager="high-m", worker="high-w"),
        seed_manager="seed-mgr",
        seed_worker="seed-wkr",
    )
    n = 3
    for k, expected_tier, expected_mgr, expected_wkr in [
        (1, "low", "low-m", "low-w"),
        (2, "mid", "mid-m", "mid-w"),
        (3, "high", "high-m", "high-w"),
    ]:
        res = plan.for_iteration(k, n)
        assert res.tier == expected_tier
        assert res.manager_model == expected_mgr
        assert res.worker_model == expected_wkr


def test_for_iteration_all_tiers_empty_resolves_to_seed_pair() -> None:
    plan = TierPlan(seed_manager="seed-mgr", seed_worker="seed-wkr")
    n = 6
    for k in range(1, n + 1):
        res = plan.for_iteration(k, n)
        assert res.manager_model == "seed-mgr"
        assert res.worker_model == "seed-wkr"


def test_for_iteration_empty_string_behaves_like_none() -> None:
    plan = TierPlan(
        high=ModelPair(manager="", worker=""),
        seed_manager="seed-mgr",
        seed_worker="seed-wkr",
    )
    res = plan.for_iteration(1, 1)
    assert res.tier == "high"
    assert res.manager_model == "seed-mgr"
    assert res.worker_model == "seed-wkr"


def test_for_iteration_seed_missing_yields_none_fallback() -> None:
    plan = TierPlan(low=ModelPair(manager="low-m"))  # no seed_manager/worker
    res = plan.for_iteration(1, 3)  # iter 1 of 3 → low
    assert res.manager_model == "low-m"
    assert res.worker_model is None


# ---------------------------------------------------------------------------
# is_trivial
# ---------------------------------------------------------------------------


def test_is_trivial_default_is_true() -> None:
    assert TierPlan().is_trivial() is True


def test_is_trivial_with_seed_only_still_true() -> None:
    """Seed pair does not count as tiering — is_trivial remains True."""
    plan = TierPlan(seed_manager="seed", seed_worker="seed")
    assert plan.is_trivial() is True


@pytest.mark.parametrize(
    "plan",
    [
        TierPlan(low=ModelPair(manager="x")),
        TierPlan(low=ModelPair(worker="x")),
        TierPlan(mid=ModelPair(manager="x")),
        TierPlan(mid=ModelPair(worker="x")),
        TierPlan(high=ModelPair(manager="x")),
        TierPlan(high=ModelPair(worker="x")),
    ],
)
def test_is_trivial_false_when_any_tier_field_set(plan: TierPlan) -> None:
    assert plan.is_trivial() is False
