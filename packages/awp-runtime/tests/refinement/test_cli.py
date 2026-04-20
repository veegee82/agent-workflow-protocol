"""Integration test: `awp refine` CLI wired to RefinementLoop."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest


def _make_perfect_seed(tmp_path: Path) -> Path:
    seed = tmp_path / "perfect"
    (seed / "FINAL").mkdir(parents=True)
    (seed / "FINAL" / "a.md").write_text("ok", encoding="utf-8")
    (seed / "run_completion.json").write_text(
        json.dumps(
            {
                "run_id": "run_perfect",
                "status": "complete",
                "confidence": 1.0,
                "task": "trivial",
                "critique": {"defects": []},
                "evaluation": {
                    "per_metric": {"q": 1.0},
                    "thresholds": {"q": 0.5},
                    "total_score": 1.0,
                },
            }
        ),
        encoding="utf-8",
    )
    (seed / "events.jsonl").write_text("", encoding="utf-8")
    return seed


def test_refine_cli_empty_gradient_exit_0(tmp_path: Path) -> None:
    seed = _make_perfect_seed(tmp_path)

    awp_bin = shutil.which("awp") or "awp"
    result = subprocess.run(
        [awp_bin, "refine", str(seed), "--iterations", "1"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "nothing to refine" in (result.stdout + result.stderr).lower()


def test_refine_cli_missing_seed_exit_2(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "awp",
            "refine",
            str(tmp_path / "no_such"),
            "--iterations",
            "1",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2


def test_refine_cli_help_mentions_iterations() -> None:
    awp_bin = shutil.which("awp") or "awp"
    result = subprocess.run([awp_bin, "refine", "--help"], capture_output=True, text=True)
    assert result.returncode == 0
    assert "--iterations" in result.stdout


def test_refine_cli_help_mentions_tier_flags() -> None:
    """--tier-low / --tier-mid / --tier-high must be in the refine help text."""
    awp_bin = shutil.which("awp") or "awp"
    result = subprocess.run([awp_bin, "refine", "--help"], capture_output=True, text=True)
    assert result.returncode == 0
    for flag in ("--tier-low", "--tier-mid", "--tier-high"):
        assert flag in result.stdout, f"{flag} missing from awp refine --help"


def _make_refineable_seed(tmp_path: Path) -> Path:
    """Seed with a non-empty gradient, FINAL/, and a recorded seed model."""
    seed = tmp_path / "seed"
    (seed / "FINAL").mkdir(parents=True)
    (seed / "FINAL" / "paper.md").write_text("# seed\n", encoding="utf-8")
    (seed / "run_completion.json").write_text(
        json.dumps(
            {
                "run_id": "run_seed",
                "status": "partial",
                "task": "write a paper",
                "models": {"manager": "seed_mgr", "worker": "seed_wkr"},
                "critique": {"defects": [{"summary": "missing", "severity": "high"}]},
                "evaluation": {
                    "per_metric": {"m1": 0.5},
                    "thresholds": {"m1": 0.9},
                    "total_score": 0.5,
                },
            }
        ),
        encoding="utf-8",
    )
    (seed / "events.jsonl").write_text("", encoding="utf-8")
    return seed


class _CapturingCLILoop:
    """Stub RefinementLoop used to capture the constructor args the CLI passes.

    Instantiation writes the kwargs into ``last_kwargs``; ``run`` returns a
    RefinementResult-like object so ``cmd_refine``'s reporting code path
    executes without needing a real iteration.
    """

    last_kwargs: "dict" = {}

    def __init__(self, **kwargs):
        _CapturingCLILoop.last_kwargs = dict(kwargs)

    def run(self, *, iterations):
        class R:
            session_id = "refine_CLI"
            seed_run_id = "run_seed"
            seed_loss = 0.5
            best_iter = 1
            best_loss = 0.3
            stop_reason = "max_iterations"
            iterations: list = []

        return R()


def test_refine_cli_tier_flags_build_tier_plan(tmp_path: Path) -> None:
    """`awp refine --tier-high 'hm:hw'` should pass a TierPlan to RefinementLoop."""
    seed = _make_refineable_seed(tmp_path)

    # Drive cmd_refine directly so we can intercept RefinementLoop.
    from awp.cli import cmd_refine
    from awp.refinement import loop as loop_mod
    from awp.refinement.tiers import TierPlan

    import argparse

    ns = argparse.Namespace(
        seed=str(seed),
        iterations=3,
        model=None,
        worker_model=None,
        tier_low=None,
        tier_mid="mid_mgr:mid_wkr",
        tier_high="high_mgr:",
    )

    with patch.object(loop_mod, "RefinementLoop", _CapturingCLILoop):
        rc = cmd_refine(ns)

    assert rc == 0  # best_iter=1 → exit 0
    kwargs = _CapturingCLILoop.last_kwargs
    assert kwargs["model"] is None
    assert kwargs["worker_model"] is None
    plan = kwargs["tier_plan"]
    assert isinstance(plan, TierPlan)
    assert plan.low.manager is None and plan.low.worker is None
    assert plan.mid.manager == "mid_mgr"
    assert plan.mid.worker == "mid_wkr"
    assert plan.high.manager == "high_mgr"
    # --tier-high "high_mgr:" → worker part is "" → None after strip.
    assert plan.high.worker is None
    # Seed fallback parsed from run_completion.json.models.
    assert plan.seed_manager == "seed_mgr"
    assert plan.seed_worker == "seed_wkr"


def test_refine_cli_mixed_flags_tier_wins_and_warns(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    """Giving --model AND --tier-high → tier wins, warning emitted on stderr."""
    seed = _make_refineable_seed(tmp_path)

    from awp.cli import cmd_refine
    from awp.refinement import loop as loop_mod

    import argparse

    ns = argparse.Namespace(
        seed=str(seed),
        iterations=1,
        model="legacy_mgr",
        worker_model="legacy_wkr",
        tier_low=None,
        tier_mid=None,
        tier_high="h:w",
    )

    with patch.object(loop_mod, "RefinementLoop", _CapturingCLILoop):
        rc = cmd_refine(ns)

    assert rc == 0
    kwargs = _CapturingCLILoop.last_kwargs
    assert kwargs["model"] is None
    assert kwargs["worker_model"] is None
    assert kwargs["tier_plan"] is not None
    err = capsys.readouterr().err
    assert "tier-*" in err.lower() or "tier_*" in err.lower() or "ignoring" in err.lower()


def test_refine_cli_no_tier_flags_takes_legacy_path(tmp_path: Path) -> None:
    """Without any --tier-* flag, tier_plan must be None and legacy model passed."""
    seed = _make_refineable_seed(tmp_path)

    from awp.cli import cmd_refine
    from awp.refinement import loop as loop_mod

    import argparse

    ns = argparse.Namespace(
        seed=str(seed),
        iterations=1,
        model="legacy_mgr",
        worker_model="legacy_wkr",
        tier_low=None,
        tier_mid=None,
        tier_high=None,
    )

    with patch.object(loop_mod, "RefinementLoop", _CapturingCLILoop):
        rc = cmd_refine(ns)

    assert rc == 0
    kwargs = _CapturingCLILoop.last_kwargs
    # Legacy path: tier_plan is omitted from the ctor (positional args),
    # so kwargs must NOT contain it — OR it is explicitly None.
    assert "tier_plan" not in kwargs or kwargs.get("tier_plan") is None
    assert kwargs["model"] == "legacy_mgr"
    assert kwargs["worker_model"] == "legacy_wkr"
