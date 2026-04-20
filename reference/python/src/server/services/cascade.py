"""Auto-cascade orchestrator — runs refine + optimize after a seed run.

Invoked by runner_service after a hierarchy-attached seed run finishes.
Each sub-phase uses the existing Plan 4 entry points; no runtime-internal
changes. Loss + BEST updates happen via _post_run_finalise.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from pathlib import Path
from typing import Any

from awp.experiment.paths import experiment_dir, task_dir

logger = logging.getLogger(__name__)

# Lazy-imported runtime pieces so awp-ui tests don't pay the import cost.
try:
    from awp.refinement.loop import RefinementLoop
except ImportError:  # pragma: no cover
    RefinementLoop = None  # type: ignore

try:
    from awp.outer_loop.runner import SuiteRunner
    from awp.outer_loop.suite import TaskSuiteSpec, SuiteTask
    from awp.outer_loop.store import SqliteArtifactStore
    from awp.outer_loop import ArtifactRegistry
except ImportError:  # pragma: no cover
    SuiteRunner = None  # type: ignore


async def cascade_after_seed(
    *,
    seed_run_id: str,
    seed_run_dir: Path,
    experiment_id: str,
    task_key: str,
    task_text: str,
    model: str,
    settings: dict[str, Any],
) -> None:
    """Run refine + optimize (if enabled in settings) after a seed completes."""
    if settings.get("auto_refine_after_seed"):
        await _run_refine_phase(
            seed_run_id=seed_run_id,
            seed_run_dir=seed_run_dir,
            experiment_id=experiment_id,
            task_key=task_key,
            task_text=task_text,
            model=model,
            iterations=int(settings.get("auto_refine_iterations", 2)),
        )

    if settings.get("auto_optimize_after_seed"):
        await _run_optimize_phase(
            experiment_id=experiment_id,
            task_key=task_key,
            task_text=task_text,
            model=model,
            epochs=int(settings.get("auto_optimize_epochs", 1)),
        )


async def _run_refine_phase(
    *,
    seed_run_id: str,
    seed_run_dir: Path,
    experiment_id: str,
    task_key: str,
    task_text: str,
    model: str,
    iterations: int,
) -> None:
    if RefinementLoop is None:
        logger.warning("RefinementLoop not importable — skipping auto-refine")
        return

    exp_id, tid = task_key.split(":", 1)
    td = task_dir(exp_id, tid)
    ts = time.strftime("%Y%m%d_%H%M%S")
    iterations_root = td / "refinements" / f"session_{ts}"
    iterations_root.mkdir(parents=True, exist_ok=True)

    # Blocking LLM call — run in a thread so we don't block the asyncio loop.
    def _run_refine():
        loop = RefinementLoop(
            seed_run_dir=seed_run_dir,
            iterations_root=iterations_root,
            model=model,
            session_sidecar_dir=iterations_root,
        )
        return loop.run(iterations=iterations)

    await asyncio.to_thread(_run_refine)

    # Finalise each iteration's run.
    from awp.experiment.cli_handlers import _post_run_finalise

    def _finalise_iters():
        for iter_dir in sorted(iterations_root.glob("iter_*")):
            for run_dir in (iter_dir / "output").glob("*"):
                if not run_dir.is_dir():
                    continue
                _post_run_finalise(
                    output_dir=iter_dir,
                    run_id=run_dir.name,
                    exp_id=experiment_id,
                    task_key=task_key,
                    task_text="refine iteration (auto-cascade)",
                    model=model,
                    run_role="refine_iter",
                )

    await asyncio.to_thread(_finalise_iters)


async def _run_optimize_phase(
    *,
    experiment_id: str,
    task_key: str,
    task_text: str,
    model: str,
    epochs: int,
) -> None:
    if SuiteRunner is None:
        logger.warning("SuiteRunner not importable — skipping auto-optimize")
        return

    exp_id, tid = task_key.split(":", 1)
    exp_path = experiment_dir(exp_id)
    td = task_dir(exp_id, tid)
    ts = time.strftime("%Y%m%d_%H%M%S")
    output_dir = td / "optimizations" / f"suite_{ts}"

    # Synthesise a 1-task suite from the task's own prompt.
    suite = TaskSuiteSpec(
        name=f"auto_cascade_{ts}",
        description="Auto-cascade single-task suite",
        baseline_artifacts={},
        tasks=[
            SuiteTask(
                name=tid.split("-", 1)[1] if "-" in tid else "task",
                task=task_text,
                model=model,
                worker_model="deepseek/deepseek-chat-v3.1",
                budget={"max_loops": 3, "max_total_workers": 2,
                        "max_total_tokens": 20000, "max_wall_time": 120},
            ),
        ],
    )

    db_path = exp_path / "outer_loop.db"
    store = SqliteArtifactStore(db_path=str(db_path))
    registry = ArtifactRegistry(db_path=str(db_path))

    def _run_opt():
        runner = SuiteRunner(registry=registry, store=store)
        for n in range(1, epochs + 1):
            runner.run_epoch(
                suite=suite, epoch_num=n, parent_artifacts={},
                output_dir=output_dir,
            )

    await asyncio.to_thread(_run_opt)

    # Finalise every epoch-run SuiteRunner produced.
    from awp.experiment.cli_handlers import _post_run_finalise

    def _finalise_epochs():
        if output_dir.exists():
            for completion in output_dir.rglob("run_completion.json"):
                run_dir = completion.parent
                if run_dir.parent.name == "runs" and run_dir.parent.parent.name == "workspace":
                    opt_output = run_dir.parent.parent.parent
                else:
                    opt_output = run_dir.parent.parent
                _post_run_finalise(
                    output_dir=opt_output,
                    run_id=run_dir.name,
                    exp_id=experiment_id,
                    task_key=task_key,
                    task_text="optimize epoch (auto-cascade)",
                    model=model,
                    run_role="optimize_epoch_run",
                    task_dir_override=td,
                )

    await asyncio.to_thread(_finalise_epochs)
