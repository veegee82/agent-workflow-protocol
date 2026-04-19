"""Integration test: `awp refine` CLI wired to RefinementLoop."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path


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
    result = subprocess.run(
        [awp_bin, "refine", "--help"], capture_output=True, text=True
    )
    assert result.returncode == 0
    assert "--iterations" in result.stdout
