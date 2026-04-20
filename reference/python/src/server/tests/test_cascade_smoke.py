"""Smoke test — cascade fires refine + optimize when settings enable them."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
import pytest_asyncio

# Make awp_ui_test_utils importable
sys.path.insert(0, str(Path(__file__).parent))
from awp_ui_test_utils import _mk_fake_run, _seed_experiment_task


@pytest.mark.asyncio
async def test_cascade_fires_refine_then_optimize(tmp_path: Path, monkeypatch) -> None:
    """Given a completed seed + cascade toggles on, both phases run."""
    # 1. Scaffold experiment + seed task + fake completed seed run on disk.
    monkeypatch.setenv("AWP_EXPERIMENTS_ROOT", str(tmp_path))
    monkeypatch.setenv("AWP_UI_DB_PATH", str(tmp_path / "test.db"))
    exp_id, task_key, seed_output = _seed_experiment_task(tmp_path)
    _mk_fake_run(seed_output, "seed_run_1", score=0.5)

    # 2. Call cascade_after_seed with toggles enabled. Patch the two heavy
    #    dependencies (RefinementLoop + SuiteRunner) to return fake outcomes
    #    so the test runs without an LLM.
    from server.services.cascade import cascade_after_seed

    refine_calls = []
    optimize_calls = []

    class _FakeRefinementLoop:
        def __init__(self, seed_run_dir, iterations_root, **kw):
            refine_calls.append((seed_run_dir, iterations_root, kw))
            self.iterations_root = iterations_root

        def run(self, iterations: int):
            # Create one fake iter with a better score
            iter_dir = Path(self.iterations_root) / "iter_1"
            _mk_fake_run(iter_dir, "iter1_run", score=0.9)
            return type("Result", (), {"best_iter": 1})()

    class _FakeSuiteRunner:
        def __init__(self, **kw):
            pass
        def run_epoch(self, suite, epoch_num, parent_artifacts, output_dir):
            optimize_calls.append((suite, epoch_num, output_dir))
            # Create one fake epoch run under the output_dir
            _mk_fake_run(Path(output_dir) / "epoch_1" / "x", "epoch_run", score=0.7)
            return None

    with patch("server.services.cascade.RefinementLoop", _FakeRefinementLoop), \
         patch("server.services.cascade.SuiteRunner", _FakeSuiteRunner):
        await cascade_after_seed(
            seed_run_id="seed_run_1",
            seed_run_dir=seed_output / "output" / "workspace" / "runs" / "seed_run_1",
            experiment_id=exp_id,
            task_key=task_key,
            task_text="P",
            model="openai/gpt-5-mini",
            settings={
                "auto_refine_after_seed": True,
                "auto_refine_iterations": 1,
                "auto_optimize_after_seed": True,
                "auto_optimize_epochs": 1,
            },
        )

    assert len(refine_calls) == 1
    assert len(optimize_calls) == 1


@pytest.mark.asyncio
async def test_cascade_skips_when_toggles_off(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("AWP_EXPERIMENTS_ROOT", str(tmp_path))
    monkeypatch.setenv("AWP_UI_DB_PATH", str(tmp_path / "test.db"))
    exp_id, task_key, seed_output = _seed_experiment_task(tmp_path)
    _mk_fake_run(seed_output, "seed_run_1", score=0.5)

    from server.services.cascade import cascade_after_seed
    refine_calls = []

    class _FakeRefinementLoop:
        def __init__(self, **kw):
            refine_calls.append(kw)
        def run(self, iterations: int):
            return None

    with patch("server.services.cascade.RefinementLoop", _FakeRefinementLoop):
        await cascade_after_seed(
            seed_run_id="seed_run_1",
            seed_run_dir=seed_output,
            experiment_id=exp_id,
            task_key=task_key,
            task_text="P",
            model="openai/gpt-5-mini",
            settings={
                "auto_refine_after_seed": False,
                "auto_refine_iterations": 2,
                "auto_optimize_after_seed": False,
                "auto_optimize_epochs": 1,
            },
        )
    assert refine_calls == []
