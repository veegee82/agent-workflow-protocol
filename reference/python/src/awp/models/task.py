"""TaskManifest — unit of user intention inside an experiment.

Enforces R37 (continuation tasks require non-empty inputs) at validation time.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field, model_validator


def _reject_unsafe_path(p: str) -> None:
    """Reject paths with traversal, absolute, home, or encoding attacks."""
    if not p:
        raise ValueError("path traversal rejected: empty path")
    if "\x00" in p:
        raise ValueError(f"path traversal rejected: NUL in {p!r}")
    if "\\" in p:
        raise ValueError(f"path traversal rejected: backslash in {p!r}")
    if p.startswith(("/", "~")):
        raise ValueError(f"path traversal rejected: absolute/home in {p!r}")
    if len(p) >= 2 and p[1] == ":":  # Windows drive letter
        raise ValueError(f"path traversal rejected: drive letter in {p!r}")
    if "%" in p:
        raise ValueError(f"path traversal rejected: percent-encoded in {p!r}")
    parts = p.split("/")
    if ".." in parts:
        raise ValueError(f"path traversal rejected: .. in {p!r}")


class TaskMode(str, Enum):
    SEED = "seed"
    CONTINUATION = "continuation"


class InputRole(str, Enum):
    PRIMARY = "primary"
    REFERENCE = "reference"


class TaskInput(BaseModel):
    from_task: str
    role: InputRole
    bundle: str | None = None
    paths: list[str] | None = None

    @model_validator(mode="after")
    def _validate_source(self) -> "TaskInput":
        if (self.bundle is None) == (self.paths is None):
            raise ValueError("TaskInput requires exactly one of 'bundle' or 'paths'")
        if self.paths:
            for p in self.paths:
                _reject_unsafe_path(p)
        return self


class TaskManifest(BaseModel):
    """On-disk shape of ``<experiment>/tasks/<task_id>/task.json``."""

    task_id: str = Field(..., pattern=r"^\d{3}-[a-z0-9-]+$")
    experiment_id: str
    task_number: int = Field(..., ge=1)
    mode: TaskMode
    user_prompt: str | None = None
    user_feedback: str | None = None
    inputs: list[TaskInput] = Field(default_factory=list)
    created_at: str

    @model_validator(mode="after")
    def _validate_mode_fields(self) -> "TaskManifest":
        if self.mode == TaskMode.SEED:
            if not self.user_prompt:
                raise ValueError("seed task requires user_prompt")
            if self.user_feedback:
                raise ValueError("seed task must not have user_feedback")
            if self.inputs:
                raise ValueError("seed task must not have inputs")
        else:  # CONTINUATION
            if not self.user_feedback:
                raise ValueError("continuation task requires user_feedback")
            if self.user_prompt:
                raise ValueError("continuation task must not have user_prompt")
            if not self.inputs:
                raise ValueError(
                    "continuation task requires at least one input (R37)"
                )
        return self
