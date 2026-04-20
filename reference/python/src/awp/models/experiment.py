"""ExperimentManifest — top-level container for a campaign of sequential tasks."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from pydantic import BaseModel, Field, field_validator


class ExperimentManifest(BaseModel):
    """On-disk shape of ``<experiment>/experiment.json`` and DB mirror source."""

    experiment_id: str = Field(..., pattern=r"^exp_[a-z0-9]{6,16}$")
    name: str
    goal: str = ""
    created_at: str
    task_order: list[str] = Field(default_factory=list)

    @field_validator("name")
    @classmethod
    def _name_nonempty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("name must be non-empty")
        return v

    @classmethod
    def new(
        cls,
        name: str,
        goal: str = "",
        experiment_id: str | None = None,
    ) -> "ExperimentManifest":
        eid = experiment_id or f"exp_{uuid.uuid4().hex[:8]}"
        return cls(
            experiment_id=eid,
            name=name,
            goal=goal,
            created_at=datetime.now(timezone.utc).isoformat(),
            task_order=[],
        )
