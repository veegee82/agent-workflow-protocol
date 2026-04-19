"""Task-suite specification for the outer loop (Phase A2).

A *suite* is a YAML file that defines a set of tasks the outer loop runs
sequentially in one epoch. Each task is one ``AgentWorkflow`` invocation;
its run artifacts feed into :func:`awp.outer_loop.loss.compute_run_loss`,
and the per-task losses are aggregated into the epoch mean.

Phase A2 adds the schema, parser, and loader. The runner that consumes
these specs lives in :mod:`awp.outer_loop.runner`.

YAML schema
-----------

.. code-block:: yaml

    name: research_writeup_v1
    description: Two-task suite for the writeup-quality regression.
    baseline_artifacts:
      worker_pitfalls: 0
      manager_planning_preamble: 0
    tasks:
      - name: task_a
        task: "Summarise the attached paper in three paragraphs."
        workflow: examples/workflows/01_simple_pipeline    # optional
        model: openai/gpt-5-mini                            # optional
        budget:                                             # optional
          max_loops: 8
          max_total_workers: 6
          max_total_tokens: 800000
          max_wall_time: 1200
        weights:                                            # optional
          eval: 0.5
          critique: 0.3
          gate_rejections: 0.1
          budget: 0.05
          status: 0.05

The schema is validated with Pydantic; unknown top-level keys raise.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .loss import LossWeights


class SuiteTaskBudget(BaseModel):
    """Per-task budget overrides. All fields are optional."""

    model_config = ConfigDict(extra="forbid")

    max_loops: int | None = None
    max_total_workers: int | None = None
    max_total_tokens: int | None = None
    max_wall_time: int | None = None
    max_tool_calls: int | None = None
    max_depth: int | None = None


class SuiteTaskWeights(BaseModel):
    """Per-task loss-weight overrides. All fields are optional."""

    model_config = ConfigDict(extra="forbid")

    eval: float | None = None
    critique: float | None = None
    gate_rejections: float | None = None
    budget: float | None = None
    status: float | None = None

    def to_loss_weights(self, base: LossWeights | None = None) -> LossWeights:
        """Merge with ``base`` (or default :class:`LossWeights`)."""
        b = base or LossWeights()
        return LossWeights(
            eval=self.eval if self.eval is not None else b.eval,
            critique=self.critique if self.critique is not None else b.critique,
            gate_rejections=self.gate_rejections
            if self.gate_rejections is not None
            else b.gate_rejections,
            budget=self.budget if self.budget is not None else b.budget,
            status=self.status if self.status is not None else b.status,
        )


class SuiteTask(BaseModel):
    """A single task entry in a :class:`TaskSuiteSpec`."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1)
    task: str = Field(..., min_length=1)
    workflow: str | None = None
    model: str | None = None
    worker_model: str | None = None
    budget: SuiteTaskBudget | None = None
    weights: SuiteTaskWeights | None = None
    extra: dict[str, Any] = Field(default_factory=dict)

    @field_validator("name")
    @classmethod
    def _validate_name(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("task name must not be blank")
        return v


class TaskSuiteSpec(BaseModel):
    """Top-level suite specification, parsed from YAML."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1)
    description: str | None = None
    baseline_artifacts: dict[str, int] = Field(default_factory=dict)
    tasks: list[SuiteTask] = Field(default_factory=list)

    @field_validator("tasks")
    @classmethod
    def _at_least_one_task(cls, v: list[SuiteTask]) -> list[SuiteTask]:
        if not v:
            raise ValueError("suite must define at least one task")
        # Names must be unique within a suite — they are the join key for
        # ``epoch_runs.task_name``.
        names = [t.name for t in v]
        if len(set(names)) != len(names):
            dupes = sorted({n for n in names if names.count(n) > 1})
            raise ValueError(f"duplicate task names in suite: {dupes}")
        return v


def load_suite(path: Path) -> TaskSuiteSpec:
    """Load and validate a suite YAML file.

    Raises :class:`FileNotFoundError` if ``path`` does not exist and
    :class:`pydantic.ValidationError` if the document violates the schema.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Suite file not found: {path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"Suite YAML root must be a mapping, got {type(raw).__name__}")
    return TaskSuiteSpec.model_validate(raw)


__all__ = [
    "SuiteTask",
    "SuiteTaskBudget",
    "SuiteTaskWeights",
    "TaskSuiteSpec",
    "load_suite",
]
