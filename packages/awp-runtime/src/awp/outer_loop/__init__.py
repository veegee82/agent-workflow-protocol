"""Outer Loop (A5, experimental).

The outer loop optimizes *prompt artifacts* above a normal AWP run. Phase A1
introduces the :class:`ArtifactRegistry` which serves versioned prompt
artifacts. Phase A1 is behavior-preserving: when no database is provided, the
registry returns the hardcoded v0 defaults bundled under
``awp.outer_loop.defaults``, so prompts are byte-identical to the pre-refactor
codebase.

Phase A2 adds:

* :func:`compute_run_loss` — deterministic scalar loss from a run's artifacts.
* :class:`TaskSuiteSpec` + :func:`load_suite` — YAML-defined task batches.
* :class:`SuiteRunner` — runs all tasks of one suite, persists epochs +
  per-run losses to the same SQLite store as the artifact registry.

Phase A2 is still OFF by default. The runner is invoked only via the
``awp optimize`` CLI and never imported on a normal ``awp run``. No
artifact updates happen yet — that arrives in Phase A3.
"""

from __future__ import annotations

from .artifacts import Artifact, ArtifactRegistry, ArtifactVersion
from .loss import LossBreakdown, LossWeights, compute_run_loss
from .runner import ALL_OPTIMIZABLE_ARTIFACTS, EpochResult, SuiteRunner, TaskRunResult
from .suite import (
    SuiteTask,
    SuiteTaskBudget,
    SuiteTaskWeights,
    TaskSuiteSpec,
    load_suite,
)
from .textgrad import ArtifactUpdate, TextGradOptimizer

__all__ = [
    "ALL_OPTIMIZABLE_ARTIFACTS",
    "Artifact",
    "ArtifactRegistry",
    "ArtifactUpdate",
    "ArtifactVersion",
    "EpochResult",
    "LossBreakdown",
    "LossWeights",
    "SuiteRunner",
    "SuiteTask",
    "SuiteTaskBudget",
    "SuiteTaskWeights",
    "TaskRunResult",
    "TaskSuiteSpec",
    "TextGradOptimizer",
    "compute_run_loss",
    "load_suite",
]
