"""Path helpers for the experiment > task > run hierarchy."""

from __future__ import annotations

import os
import re
from pathlib import Path

EXPERIMENTS_ROOT = Path(os.environ.get("AWP_EXPERIMENTS_ROOT", "/tmp/awp-experiments"))


def experiment_dir(experiment_id: str) -> Path:
    return EXPERIMENTS_ROOT / experiment_id


def task_dir(experiment_id: str, task_id: str) -> Path:
    return experiment_dir(experiment_id) / "tasks" / task_id


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slug_from_prompt(prompt: str, max_len: int = 50) -> str:
    lowered = prompt.strip().lower()
    slug = _SLUG_RE.sub("-", lowered).strip("-")
    slug = slug[:max_len] or "task"
    return slug


def task_id_for(task_number: int, slug: str) -> str:
    if not 1 <= task_number <= 999:
        raise ValueError(f"task_number out of range [1..999]: {task_number}")
    return f"{task_number:03d}-{slug}"
