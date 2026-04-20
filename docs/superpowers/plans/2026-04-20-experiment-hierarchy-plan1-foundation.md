# Plan 1 — Foundation: Experiment/Task Model + DB + CLI

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land the data layer for the three-level hierarchy: Pydantic models for `experiment.json` / `task.json`, schema migrations on `~/.awp/awp_ui.db`, and the `awp experiment` + `awp task` CLI commands. No runtime wiring yet — `awp run` / `awp refine` / `awp optimize` are untouched.

**Architecture:** Disk-first, DB-as-cache. Each operation writes the JSON manifest to disk first, then mirrors to `awp_ui.db`. R37 (continuation requires inputs) is enforced by Pydantic validators on `TaskManifest`, so the rule fires at both CLI parse-time and any direct model instantiation. The CLI is the only way to create experiments/tasks in this plan — UI integration comes in Plan 5.

**Tech Stack:** Python 3.10+, Pydantic v2, aiosqlite, argparse, pytest.

**Spec reference:** `docs/superpowers/specs/2026-04-20-experiment-task-hierarchy-design.md` §4 decisions 1/4, §6 data model, §8 CLI, §11 R37.

**Out of scope for this plan:**
- `awp run --task` wiring, implicit experiment (Plan 2).
- BEST finaliser + `awp task set-best` (Plan 2 — needs runs to be meaningful).
- `awp refine --task` / `awp optimize --task` (Plan 4).
- UI routes + sidebar tree (Plan 5).
- `awp experiment purge-legacy` (Plan 6).

---

## File structure

**Created:**
- `packages/awp-core/src/awp/models/experiment.py` — `ExperimentManifest` Pydantic model.
- `packages/awp-core/src/awp/models/task.py` — `TaskMode`, `InputRole`, `TaskInput`, `TaskManifest`.
- `packages/awp-core/src/awp/experiment/__init__.py` — package marker.
- `packages/awp-core/src/awp/experiment/paths.py` — path helpers (`experiment_dir(exp_id)`, `task_dir(exp_id, task_id)`, slug from prompt).
- `packages/awp-core/src/awp/experiment/disk.py` — `write_experiment_manifest` / `read_experiment_manifest` / `write_task_manifest` / `read_task_manifest` / `append_task_to_order`.
- `packages/awp-core/tests/models/test_experiment.py`
- `packages/awp-core/tests/models/test_task.py`
- `packages/awp-core/tests/experiment/test_disk.py`
- `packages/awp-core/tests/cli/test_experiment_cli.py`
- `packages/awp-core/tests/cli/test_task_cli.py`
- `packages/awp-ui/server/tests/test_store_experiments.py`

**Modified:**
- `packages/awp-core/src/awp/models/__init__.py` — export new models.
- `packages/awp-core/src/awp/cli.py` — register `experiment` + `task` subparsers and dispatch.
- `packages/awp-ui/server/services/store.py` — add `experiments` + `tasks` tables to `_SCHEMA_SQL`, add `_migrate_runs_for_hierarchy`, add async methods for experiment/task CRUD.
- `spec/versions/1.0/validation-rules.md` — add R37 under a new "Continuation" section alongside R36.
- `CLAUDE.md` — add the new CLI commands to the "Development Commands" block.

---

## Task 1: Pydantic model — `ExperimentManifest`

**Files:**
- Create: `packages/awp-core/src/awp/models/experiment.py`
- Test:   `packages/awp-core/tests/models/test_experiment.py`

- [ ] **Step 1: Write the failing test**

Create `packages/awp-core/tests/models/test_experiment.py`:

```python
"""Tests for ExperimentManifest."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from awp.models.experiment import ExperimentManifest


def test_new_assigns_id_and_timestamp() -> None:
    manifest = ExperimentManifest.new(name="AWP Paper", goal="A paper for publication")
    assert manifest.name == "AWP Paper"
    assert manifest.goal == "A paper for publication"
    assert manifest.experiment_id.startswith("exp_")
    assert len(manifest.experiment_id) == len("exp_") + 8
    assert manifest.created_at.endswith("+00:00")
    assert manifest.task_order == []


def test_new_honours_explicit_id() -> None:
    manifest = ExperimentManifest.new(name="X", experiment_id="exp_custom1")
    assert manifest.experiment_id == "exp_custom1"


def test_empty_name_rejected() -> None:
    with pytest.raises(ValidationError):
        ExperimentManifest(
            experiment_id="exp_aaaaaaaa",
            name="",
            goal="",
            created_at="2026-04-20T00:00:00+00:00",
            task_order=[],
        )


def test_roundtrip_json() -> None:
    manifest = ExperimentManifest.new(name="T", goal="G")
    manifest.task_order.append("001-task")
    restored = ExperimentManifest.model_validate_json(manifest.model_dump_json())
    assert restored == manifest
```

- [ ] **Step 2: Run test to verify it fails**

```
pytest packages/awp-core/tests/models/test_experiment.py -v
```

Expected: all four tests fail with `ModuleNotFoundError: No module named 'awp.models.experiment'`.

- [ ] **Step 3: Implement the model**

Create `packages/awp-core/src/awp/models/experiment.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

```
pytest packages/awp-core/tests/models/test_experiment.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add packages/awp-core/src/awp/models/experiment.py packages/awp-core/tests/models/test_experiment.py
git commit -m "feat(core): add ExperimentManifest Pydantic model"
```

---

## Task 2: Pydantic model — `TaskManifest` (with R37)

**Files:**
- Create: `packages/awp-core/src/awp/models/task.py`
- Test:   `packages/awp-core/tests/models/test_task.py`

- [ ] **Step 1: Write the failing test**

Create `packages/awp-core/tests/models/test_task.py`:

```python
"""Tests for TaskManifest, including R37 enforcement."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from awp.models.task import InputRole, TaskInput, TaskManifest, TaskMode


def _valid_seed_kwargs(**overrides):
    base = dict(
        task_id="001-draft",
        experiment_id="exp_aaaaaaaa",
        task_number=1,
        mode=TaskMode.SEED,
        user_prompt="Write a paper",
        user_feedback=None,
        inputs=[],
        created_at="2026-04-20T00:00:00+00:00",
    )
    base.update(overrides)
    return base


def _valid_cont_kwargs(**overrides):
    base = dict(
        task_id="002-improve",
        experiment_id="exp_aaaaaaaa",
        task_number=2,
        mode=TaskMode.CONTINUATION,
        user_prompt=None,
        user_feedback="make section 3 deeper",
        inputs=[TaskInput(from_task="001-draft", role=InputRole.PRIMARY, bundle="BEST/")],
        created_at="2026-04-20T00:00:00+00:00",
    )
    base.update(overrides)
    return base


def test_seed_valid() -> None:
    manifest = TaskManifest(**_valid_seed_kwargs())
    assert manifest.mode == TaskMode.SEED
    assert manifest.inputs == []


def test_seed_rejects_user_feedback() -> None:
    with pytest.raises(ValidationError, match="must not have user_feedback"):
        TaskManifest(**_valid_seed_kwargs(user_feedback="x"))


def test_seed_rejects_inputs() -> None:
    with pytest.raises(ValidationError, match="must not have inputs"):
        TaskManifest(
            **_valid_seed_kwargs(
                inputs=[TaskInput(from_task="001-x", role=InputRole.PRIMARY, bundle="BEST/")]
            )
        )


def test_seed_requires_user_prompt() -> None:
    with pytest.raises(ValidationError, match="requires user_prompt"):
        TaskManifest(**_valid_seed_kwargs(user_prompt=None))


def test_continuation_valid() -> None:
    manifest = TaskManifest(**_valid_cont_kwargs())
    assert manifest.mode == TaskMode.CONTINUATION
    assert len(manifest.inputs) == 1


def test_continuation_r37_empty_inputs() -> None:
    with pytest.raises(ValidationError, match="R37"):
        TaskManifest(**_valid_cont_kwargs(inputs=[]))


def test_continuation_requires_user_feedback() -> None:
    with pytest.raises(ValidationError, match="requires user_feedback"):
        TaskManifest(**_valid_cont_kwargs(user_feedback=None))


def test_continuation_rejects_user_prompt() -> None:
    with pytest.raises(ValidationError, match="must not have user_prompt"):
        TaskManifest(**_valid_cont_kwargs(user_prompt="x"))


def test_task_input_requires_exactly_one_source() -> None:
    with pytest.raises(ValidationError, match="exactly one"):
        TaskInput(from_task="001", role=InputRole.PRIMARY)  # neither
    with pytest.raises(ValidationError, match="exactly one"):
        TaskInput(from_task="001", role=InputRole.PRIMARY, bundle="BEST/", paths=["a.md"])


def test_task_input_path_traversal_rejected() -> None:
    with pytest.raises(ValidationError, match="traversal"):
        TaskInput(from_task="001", role=InputRole.REFERENCE, paths=["../secrets.txt"])


def test_roundtrip_continuation_json() -> None:
    manifest = TaskManifest(**_valid_cont_kwargs())
    restored = TaskManifest.model_validate_json(manifest.model_dump_json())
    assert restored == manifest
```

- [ ] **Step 2: Run test to verify it fails**

```
pytest packages/awp-core/tests/models/test_task.py -v
```

Expected: all tests fail with `ModuleNotFoundError: No module named 'awp.models.task'`.

- [ ] **Step 3: Implement the model**

Create `packages/awp-core/src/awp/models/task.py`:

```python
"""TaskManifest — unit of user intention inside an experiment.

Enforces R37 (continuation tasks require non-empty inputs) at validation time.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field, model_validator


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
    def _exactly_one_source(self) -> "TaskInput":
        if (self.bundle is None) == (self.paths is None):
            raise ValueError("TaskInput requires exactly one of 'bundle' or 'paths'")
        return self

    @model_validator(mode="after")
    def _no_path_traversal(self) -> "TaskInput":
        if self.paths:
            for p in self.paths:
                if ".." in p.split("/") or p.startswith("/"):
                    raise ValueError(f"path traversal rejected: {p!r}")
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
```

- [ ] **Step 4: Run test to verify it passes**

```
pytest packages/awp-core/tests/models/test_task.py -v
```

Expected: 11 passed.

- [ ] **Step 5: Commit**

```bash
git add packages/awp-core/src/awp/models/task.py packages/awp-core/tests/models/test_task.py
git commit -m "feat(core): add TaskManifest model with R37 enforcement"
```

---

## Task 3: Export new models

**Files:**
- Modify: `packages/awp-core/src/awp/models/__init__.py`

- [ ] **Step 1: Read the current exports**

```
cat packages/awp-core/src/awp/models/__init__.py
```

- [ ] **Step 2: Add the new exports**

Append to `packages/awp-core/src/awp/models/__init__.py`:

```python
from .experiment import ExperimentManifest
from .task import InputRole, TaskInput, TaskManifest, TaskMode

__all__ = [*__all__, "ExperimentManifest", "InputRole", "TaskInput", "TaskManifest", "TaskMode"]
```

(If the file does not declare `__all__`, replace the last line with a fresh `__all__ = ["ExperimentManifest", "InputRole", "TaskInput", "TaskManifest", "TaskMode"]`.)

- [ ] **Step 3: Verify import surface**

```
python -c "from awp.models import ExperimentManifest, TaskManifest, TaskMode, InputRole, TaskInput; print('ok')"
```

Expected: prints `ok`.

- [ ] **Step 4: Commit**

```bash
git add packages/awp-core/src/awp/models/__init__.py
git commit -m "feat(core): export experiment + task models"
```

---

## Task 4: Path helpers — `awp.experiment.paths`

**Files:**
- Create: `packages/awp-core/src/awp/experiment/__init__.py`
- Create: `packages/awp-core/src/awp/experiment/paths.py`
- Test:   `packages/awp-core/tests/experiment/test_paths.py`

- [ ] **Step 1: Write the failing test**

Create `packages/awp-core/tests/experiment/test_paths.py`:

```python
"""Tests for experiment path helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from awp.experiment.paths import (
    EXPERIMENTS_ROOT,
    experiment_dir,
    slug_from_prompt,
    task_dir,
    task_id_for,
)


def test_experiments_root_default() -> None:
    assert EXPERIMENTS_ROOT == Path("/tmp/awp-experiments")


def test_experiment_dir() -> None:
    assert experiment_dir("exp_aaaaaaaa") == Path("/tmp/awp-experiments/exp_aaaaaaaa")


def test_task_dir() -> None:
    assert task_dir("exp_aaaaaaaa", "001-draft") == Path(
        "/tmp/awp-experiments/exp_aaaaaaaa/tasks/001-draft"
    )


def test_slug_from_prompt_ascii() -> None:
    assert slug_from_prompt("Write a Paper About AWP!") == "write-a-paper-about-awp"


def test_slug_from_prompt_truncates() -> None:
    slug = slug_from_prompt("a" * 200)
    assert len(slug) <= 50
    assert slug == "a" * 50


def test_slug_from_prompt_empty_fallback() -> None:
    assert slug_from_prompt("") == "task"
    assert slug_from_prompt("!!!") == "task"


@pytest.mark.parametrize(
    "number,slug,expected",
    [
        (1, "draft", "001-draft"),
        (42, "improve-sec3", "042-improve-sec3"),
        (999, "last", "999-last"),
    ],
)
def test_task_id_for(number: int, slug: str, expected: str) -> None:
    assert task_id_for(number, slug) == expected


def test_task_id_for_rejects_overflow() -> None:
    with pytest.raises(ValueError):
        task_id_for(1000, "x")
```

- [ ] **Step 2: Run test to verify it fails**

```
pytest packages/awp-core/tests/experiment/test_paths.py -v
```

Expected: all tests fail with `ModuleNotFoundError: No module named 'awp.experiment'`.

- [ ] **Step 3: Implement**

Create `packages/awp-core/src/awp/experiment/__init__.py`:

```python
"""Experiment-level on-disk + DB operations (excluding runtime integration)."""
```

Create `packages/awp-core/src/awp/experiment/paths.py`:

```python
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
```

- [ ] **Step 4: Create the tests dir marker and re-run**

```
mkdir -p packages/awp-core/tests/experiment
touch packages/awp-core/tests/experiment/__init__.py
pytest packages/awp-core/tests/experiment/test_paths.py -v
```

Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add packages/awp-core/src/awp/experiment/__init__.py packages/awp-core/src/awp/experiment/paths.py packages/awp-core/tests/experiment/__init__.py packages/awp-core/tests/experiment/test_paths.py
git commit -m "feat(core): add experiment path helpers (slug + task_id)"
```

---

## Task 5: Disk I/O — `awp.experiment.disk`

**Files:**
- Create: `packages/awp-core/src/awp/experiment/disk.py`
- Test:   `packages/awp-core/tests/experiment/test_disk.py`

- [ ] **Step 1: Write the failing test**

Create `packages/awp-core/tests/experiment/test_disk.py`:

```python
"""Tests for on-disk experiment + task persistence."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from awp.experiment import disk
from awp.experiment.paths import task_id_for
from awp.models.experiment import ExperimentManifest
from awp.models.task import InputRole, TaskInput, TaskManifest, TaskMode


@pytest.fixture
def tmp_root(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.setenv("AWP_EXPERIMENTS_ROOT", str(tmp_path))
    # Force reload of paths module to pick up the new env var
    import importlib

    import awp.experiment.paths as paths_mod

    importlib.reload(paths_mod)
    importlib.reload(disk)
    return tmp_path


def test_write_and_read_experiment(tmp_root: Path) -> None:
    manifest = ExperimentManifest.new(name="E", goal="G")
    path = disk.write_experiment_manifest(manifest)
    assert path == tmp_root / manifest.experiment_id / "experiment.json"
    assert path.exists()
    restored = disk.read_experiment_manifest(manifest.experiment_id)
    assert restored == manifest


def test_write_experiment_creates_shared_dirs(tmp_root: Path) -> None:
    manifest = ExperimentManifest.new(name="E")
    disk.write_experiment_manifest(manifest)
    exp = tmp_root / manifest.experiment_id
    assert (exp / "shared" / "memory").is_dir()
    assert (exp / "shared" / "dynamic_tools").is_dir()
    assert (exp / "shared" / "skills").is_dir()
    assert (exp / "tasks").is_dir()


def test_write_and_read_task_seed(tmp_root: Path) -> None:
    exp = ExperimentManifest.new(name="E")
    disk.write_experiment_manifest(exp)
    task = TaskManifest(
        task_id=task_id_for(1, "draft"),
        experiment_id=exp.experiment_id,
        task_number=1,
        mode=TaskMode.SEED,
        user_prompt="Write paper",
        inputs=[],
        created_at="2026-04-20T00:00:00+00:00",
    )
    path = disk.write_task_manifest(exp.experiment_id, task)
    assert path.exists()
    restored = disk.read_task_manifest(exp.experiment_id, task.task_id)
    assert restored == task


def test_append_task_to_order(tmp_root: Path) -> None:
    exp = ExperimentManifest.new(name="E")
    disk.write_experiment_manifest(exp)
    disk.append_task_to_order(exp.experiment_id, "001-draft")
    disk.append_task_to_order(exp.experiment_id, "002-next")
    reloaded = disk.read_experiment_manifest(exp.experiment_id)
    assert reloaded.task_order == ["001-draft", "002-next"]


def test_append_task_rejects_duplicate(tmp_root: Path) -> None:
    exp = ExperimentManifest.new(name="E")
    disk.write_experiment_manifest(exp)
    disk.append_task_to_order(exp.experiment_id, "001-draft")
    with pytest.raises(ValueError, match="already in task_order"):
        disk.append_task_to_order(exp.experiment_id, "001-draft")


def test_read_missing_experiment(tmp_root: Path) -> None:
    with pytest.raises(FileNotFoundError):
        disk.read_experiment_manifest("exp_missing1")


def test_read_missing_task(tmp_root: Path) -> None:
    exp = ExperimentManifest.new(name="E")
    disk.write_experiment_manifest(exp)
    with pytest.raises(FileNotFoundError):
        disk.read_task_manifest(exp.experiment_id, "001-missing")
```

- [ ] **Step 2: Run test to verify it fails**

```
pytest packages/awp-core/tests/experiment/test_disk.py -v
```

Expected: all tests fail with `ModuleNotFoundError: No module named 'awp.experiment.disk'`.

- [ ] **Step 3: Implement**

Create `packages/awp-core/src/awp/experiment/disk.py`:

```python
"""Persistence of experiment + task manifests to ``/tmp/awp-experiments/`` layout."""

from __future__ import annotations

from pathlib import Path

from awp.experiment.paths import experiment_dir, task_dir
from awp.models.experiment import ExperimentManifest
from awp.models.task import TaskManifest


def write_experiment_manifest(manifest: ExperimentManifest) -> Path:
    exp = experiment_dir(manifest.experiment_id)
    (exp / "shared" / "memory").mkdir(parents=True, exist_ok=True)
    (exp / "shared" / "dynamic_tools").mkdir(parents=True, exist_ok=True)
    (exp / "shared" / "skills").mkdir(parents=True, exist_ok=True)
    (exp / "tasks").mkdir(parents=True, exist_ok=True)
    path = exp / "experiment.json"
    path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    return path


def read_experiment_manifest(experiment_id: str) -> ExperimentManifest:
    path = experiment_dir(experiment_id) / "experiment.json"
    if not path.exists():
        raise FileNotFoundError(f"experiment.json not found: {path}")
    return ExperimentManifest.model_validate_json(path.read_text(encoding="utf-8"))


def append_task_to_order(experiment_id: str, task_id: str) -> None:
    manifest = read_experiment_manifest(experiment_id)
    if task_id in manifest.task_order:
        raise ValueError(f"task_id already in task_order: {task_id}")
    manifest.task_order.append(task_id)
    write_experiment_manifest(manifest)


def write_task_manifest(experiment_id: str, task: TaskManifest) -> Path:
    td = task_dir(experiment_id, task.task_id)
    td.mkdir(parents=True, exist_ok=True)
    path = td / "task.json"
    path.write_text(task.model_dump_json(indent=2), encoding="utf-8")
    return path


def read_task_manifest(experiment_id: str, task_id: str) -> TaskManifest:
    path = task_dir(experiment_id, task_id) / "task.json"
    if not path.exists():
        raise FileNotFoundError(f"task.json not found: {path}")
    return TaskManifest.model_validate_json(path.read_text(encoding="utf-8"))
```

- [ ] **Step 4: Run test to verify it passes**

```
pytest packages/awp-core/tests/experiment/test_disk.py -v
```

Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add packages/awp-core/src/awp/experiment/disk.py packages/awp-core/tests/experiment/test_disk.py
git commit -m "feat(core): add experiment + task on-disk persistence"
```

---

## Task 6: DB schema — new tables + runs columns

**Files:**
- Modify: `packages/awp-ui/server/services/store.py`
- Test:   `packages/awp-ui/server/tests/test_store_experiments.py`

- [ ] **Step 1: Write the failing test**

Create `packages/awp-ui/server/tests/test_store_experiments.py`:

```python
"""Tests for the experiments + tasks tables added by the hierarchy plan."""

from __future__ import annotations

from pathlib import Path

import pytest

from awp_ui.server.services.store import StoreService


@pytest.fixture
async def store(tmp_path: Path) -> StoreService:
    s = StoreService(db_path=tmp_path / "test.db")
    await s.init_db()
    yield s
    await s.close()


@pytest.mark.asyncio
async def test_experiments_table_created(store: StoreService) -> None:
    cur = await store.db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='experiments'"
    )
    row = await cur.fetchone()
    assert row is not None


@pytest.mark.asyncio
async def test_tasks_table_created(store: StoreService) -> None:
    cur = await store.db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='tasks'"
    )
    row = await cur.fetchone()
    assert row is not None


@pytest.mark.asyncio
async def test_runs_has_hierarchy_columns(store: StoreService) -> None:
    cur = await store.db.execute("PRAGMA table_info(runs)")
    cols = {row["name"] for row in await cur.fetchall()}
    assert "experiment_id" in cols
    assert "task_id" in cols
    assert "run_role" in cols
    assert "parent_run_id" in cols
    assert "loss" in cols
```

- [ ] **Step 2: Check whether the project uses `pytest-asyncio`**

```
grep -E "pytest-asyncio|asyncio_mode" packages/awp-ui/pyproject.toml packages/awp-ui/server/conftest.py 2>/dev/null
```

If `asyncio_mode = auto` is already configured, the `@pytest.mark.asyncio` lines are still safe. If not, add `asyncio_mode = "auto"` under `[tool.pytest.ini_options]` in `packages/awp-ui/pyproject.toml` and document the addition in the commit message.

- [ ] **Step 3: Run test to verify it fails**

```
pytest packages/awp-ui/server/tests/test_store_experiments.py -v
```

Expected: all three tests fail — `experiments` table missing, `tasks` table missing, `runs` has no new columns.

- [ ] **Step 4: Extend `_SCHEMA_SQL`**

In `packages/awp-ui/server/services/store.py`, locate the end of `_SCHEMA_SQL` (just before the closing `"""`) and append:

```sql

CREATE TABLE IF NOT EXISTS experiments (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    goal        TEXT NOT NULL DEFAULT '',
    base_dir    TEXT NOT NULL,
    created_at  REAL NOT NULL,
    archived_at REAL
);

CREATE TABLE IF NOT EXISTS tasks (
    id            TEXT PRIMARY KEY,
    experiment_id TEXT NOT NULL REFERENCES experiments(id) ON DELETE CASCADE,
    task_number   INTEGER NOT NULL,
    slug          TEXT NOT NULL,
    mode          TEXT NOT NULL CHECK(mode IN ('seed','continuation')),
    user_prompt   TEXT,
    user_feedback TEXT,
    inputs_json   TEXT NOT NULL DEFAULT '[]',
    best_run_id   TEXT,
    best_reason   TEXT CHECK(best_reason IN ('auto_loss','user_override') OR best_reason IS NULL),
    created_at    REAL NOT NULL,
    UNIQUE(experiment_id, task_number)
);

CREATE INDEX IF NOT EXISTS idx_tasks_experiment ON tasks(experiment_id);
```

- [ ] **Step 5: Add the migration for `runs` columns**

In `packages/awp-ui/server/services/store.py`, below the existing `_migrate_sessions` method, add:

```python
    async def _migrate_runs_for_hierarchy(self) -> None:
        """Add experiment_id / task_id / run_role / parent_run_id / loss to runs."""
        migrations = [
            ("runs", "experiment_id", "TEXT"),
            ("runs", "task_id", "TEXT"),
            ("runs", "run_role", "TEXT"),
            ("runs", "parent_run_id", "TEXT"),
            ("runs", "loss", "REAL"),
        ]
        for _table, column, col_type in migrations:
            try:
                await self.db.execute(
                    f"ALTER TABLE runs ADD COLUMN {column} {col_type}"
                )
            except Exception:
                pass  # Column already exists
        await self.db.commit()
```

Then in `init_db`, add a call right after `await self._migrate_sessions()`:

```python
        await self._migrate_runs_for_hierarchy()
```

- [ ] **Step 6: Run test to verify it passes**

```
pytest packages/awp-ui/server/tests/test_store_experiments.py -v
```

Expected: 3 passed.

- [ ] **Step 7: Verify existing store tests still pass**

```
pytest packages/awp-ui/server/tests/ -v
```

Expected: all green. If an existing test fails due to the new migration, investigate — do not paper over.

- [ ] **Step 8: Commit**

```bash
git add packages/awp-ui/server/services/store.py packages/awp-ui/server/tests/test_store_experiments.py
git commit -m "feat(ui-store): add experiments + tasks tables, hierarchy columns on runs"
```

---

## Task 7: Store methods — experiment CRUD

**Files:**
- Modify: `packages/awp-ui/server/services/store.py` (append methods to `StoreService`)
- Test:   `packages/awp-ui/server/tests/test_store_experiments.py` (extend)

- [ ] **Step 1: Write the failing tests**

Append to `packages/awp-ui/server/tests/test_store_experiments.py`:

```python
@pytest.mark.asyncio
async def test_create_and_get_experiment(store: StoreService) -> None:
    await store.create_experiment(
        experiment_id="exp_aaaaaaaa",
        name="E",
        goal="G",
        base_dir="/tmp/awp-experiments/exp_aaaaaaaa",
        created_at=1_700_000_000.0,
    )
    row = await store.get_experiment("exp_aaaaaaaa")
    assert row["id"] == "exp_aaaaaaaa"
    assert row["name"] == "E"
    assert row["goal"] == "G"
    assert row["archived_at"] is None


@pytest.mark.asyncio
async def test_list_experiments_newest_first(store: StoreService) -> None:
    await store.create_experiment("exp_aaaaaaaa", "First", "", "/tmp/a", 1_000.0)
    await store.create_experiment("exp_bbbbbbbb", "Second", "", "/tmp/b", 2_000.0)
    rows = await store.list_experiments()
    assert [r["id"] for r in rows] == ["exp_bbbbbbbb", "exp_aaaaaaaa"]


@pytest.mark.asyncio
async def test_delete_experiment_cascades(store: StoreService) -> None:
    await store.create_experiment("exp_aaaaaaaa", "E", "", "/tmp/a", 1.0)
    await store.create_task(
        task_id_key="exp_aaaaaaaa:001-draft",
        experiment_id="exp_aaaaaaaa",
        task_number=1,
        slug="draft",
        mode="seed",
        user_prompt="p",
        user_feedback=None,
        inputs_json="[]",
        created_at=1.0,
    )
    await store.delete_experiment("exp_aaaaaaaa")
    assert await store.get_experiment("exp_aaaaaaaa") is None
    cur = await store.db.execute("SELECT COUNT(*) AS c FROM tasks")
    row = await cur.fetchone()
    assert row["c"] == 0
```

- [ ] **Step 2: Run test to verify it fails**

```
pytest packages/awp-ui/server/tests/test_store_experiments.py -v
```

Expected: new three tests fail — methods undefined.

- [ ] **Step 3: Implement methods**

In `packages/awp-ui/server/services/store.py`, inside `StoreService`, add:

```python
    # ---- experiment CRUD ----

    async def create_experiment(
        self,
        experiment_id: str,
        name: str,
        goal: str,
        base_dir: str,
        created_at: float,
    ) -> None:
        await self.db.execute(
            """
            INSERT INTO experiments (id, name, goal, base_dir, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (experiment_id, name, goal, base_dir, created_at),
        )
        await self.db.commit()

    async def get_experiment(self, experiment_id: str) -> dict | None:
        cur = await self.db.execute(
            "SELECT * FROM experiments WHERE id = ?", (experiment_id,)
        )
        row = await cur.fetchone()
        return dict(row) if row else None

    async def list_experiments(self) -> list[dict]:
        cur = await self.db.execute(
            "SELECT * FROM experiments ORDER BY created_at DESC"
        )
        return [dict(r) for r in await cur.fetchall()]

    async def delete_experiment(self, experiment_id: str) -> None:
        await self.db.execute("DELETE FROM experiments WHERE id = ?", (experiment_id,))
        await self.db.commit()
```

- [ ] **Step 4: Add needed test import**

Add to the top of `packages/awp-ui/server/tests/test_store_experiments.py` (only if the test uses a helper not yet imported):

No extra imports needed — the existing tests use only `StoreService`.

- [ ] **Step 5: Run test to verify it passes**

```
pytest packages/awp-ui/server/tests/test_store_experiments.py -v
```

Expected: 6 passed (3 original + 3 new; the `delete` test depends on `create_task` which is implemented in Task 8 — mark this specific test as `@pytest.mark.xfail(reason="needs create_task from Task 8")` for now and remove the marker in Task 8).

- [ ] **Step 6: Commit**

```bash
git add packages/awp-ui/server/services/store.py packages/awp-ui/server/tests/test_store_experiments.py
git commit -m "feat(ui-store): add experiment CRUD methods"
```

---

## Task 8: Store methods — task CRUD

**Files:**
- Modify: `packages/awp-ui/server/services/store.py`
- Test:   `packages/awp-ui/server/tests/test_store_experiments.py` (extend; also un-xfail the cascade test)

- [ ] **Step 1: Write the failing tests**

Append to `packages/awp-ui/server/tests/test_store_experiments.py`:

```python
@pytest.mark.asyncio
async def test_create_and_get_task(store: StoreService) -> None:
    await store.create_experiment("exp_aaaaaaaa", "E", "", "/tmp/a", 1.0)
    await store.create_task(
        task_id_key="exp_aaaaaaaa:001-draft",
        experiment_id="exp_aaaaaaaa",
        task_number=1,
        slug="draft",
        mode="seed",
        user_prompt="p",
        user_feedback=None,
        inputs_json="[]",
        created_at=2.0,
    )
    row = await store.get_task("exp_aaaaaaaa:001-draft")
    assert row["id"] == "exp_aaaaaaaa:001-draft"
    assert row["mode"] == "seed"
    assert row["user_prompt"] == "p"


@pytest.mark.asyncio
async def test_list_tasks_for_experiment(store: StoreService) -> None:
    await store.create_experiment("exp_aaaaaaaa", "E", "", "/tmp/a", 1.0)
    await store.create_task(
        "exp_aaaaaaaa:001-a", "exp_aaaaaaaa", 1, "a", "seed", "p1", None, "[]", 10.0
    )
    await store.create_task(
        "exp_aaaaaaaa:002-b",
        "exp_aaaaaaaa",
        2,
        "b",
        "continuation",
        None,
        "fb",
        '[{"from_task":"001-a","role":"primary","bundle":"BEST/"}]',
        20.0,
    )
    rows = await store.list_tasks("exp_aaaaaaaa")
    assert [r["id"] for r in rows] == [
        "exp_aaaaaaaa:001-a",
        "exp_aaaaaaaa:002-b",
    ]


@pytest.mark.asyncio
async def test_unique_task_number_per_experiment(store: StoreService) -> None:
    await store.create_experiment("exp_aaaaaaaa", "E", "", "/tmp/a", 1.0)
    await store.create_task(
        "exp_aaaaaaaa:001-a", "exp_aaaaaaaa", 1, "a", "seed", "p", None, "[]", 1.0
    )
    with pytest.raises(Exception):
        await store.create_task(
            "exp_aaaaaaaa:001-b",
            "exp_aaaaaaaa",
            1,
            "b",
            "seed",
            "p",
            None,
            "[]",
            2.0,
        )


@pytest.mark.asyncio
async def test_delete_task(store: StoreService) -> None:
    await store.create_experiment("exp_aaaaaaaa", "E", "", "/tmp/a", 1.0)
    await store.create_task(
        "exp_aaaaaaaa:001-a", "exp_aaaaaaaa", 1, "a", "seed", "p", None, "[]", 1.0
    )
    await store.delete_task("exp_aaaaaaaa:001-a")
    assert await store.get_task("exp_aaaaaaaa:001-a") is None
```

Also remove the `@pytest.mark.xfail` marker from `test_delete_experiment_cascades` (Task 7, Step 5).

- [ ] **Step 2: Run test to verify it fails**

```
pytest packages/awp-ui/server/tests/test_store_experiments.py -v
```

Expected: the four new tests fail (`create_task` / `list_tasks` / `get_task` / `delete_task` undefined) and the un-xfail'd cascade test now fails for the same reason.

- [ ] **Step 3: Implement methods**

In `packages/awp-ui/server/services/store.py`, below the experiment CRUD block, add:

```python
    # ---- task CRUD ----

    async def create_task(
        self,
        task_id_key: str,
        experiment_id: str,
        task_number: int,
        slug: str,
        mode: str,
        user_prompt: str | None,
        user_feedback: str | None,
        inputs_json: str,
        created_at: float,
    ) -> None:
        await self.db.execute(
            """
            INSERT INTO tasks (
                id, experiment_id, task_number, slug, mode,
                user_prompt, user_feedback, inputs_json, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task_id_key,
                experiment_id,
                task_number,
                slug,
                mode,
                user_prompt,
                user_feedback,
                inputs_json,
                created_at,
            ),
        )
        await self.db.commit()

    async def get_task(self, task_id_key: str) -> dict | None:
        cur = await self.db.execute("SELECT * FROM tasks WHERE id = ?", (task_id_key,))
        row = await cur.fetchone()
        return dict(row) if row else None

    async def list_tasks(self, experiment_id: str) -> list[dict]:
        cur = await self.db.execute(
            "SELECT * FROM tasks WHERE experiment_id = ? ORDER BY task_number ASC",
            (experiment_id,),
        )
        return [dict(r) for r in await cur.fetchall()]

    async def delete_task(self, task_id_key: str) -> None:
        await self.db.execute("DELETE FROM tasks WHERE id = ?", (task_id_key,))
        await self.db.commit()
```

- [ ] **Step 4: Run test to verify it passes**

```
pytest packages/awp-ui/server/tests/test_store_experiments.py -v
```

Expected: all 10 tests pass (3 schema + 3 experiment + 4 task).

- [ ] **Step 5: Commit**

```bash
git add packages/awp-ui/server/services/store.py packages/awp-ui/server/tests/test_store_experiments.py
git commit -m "feat(ui-store): add task CRUD methods (R37 enforced at model layer)"
```

---

## Task 9: CLI — `awp experiment create/list/show/delete`

**Files:**
- Modify: `packages/awp-core/src/awp/cli.py`
- Test:   `packages/awp-core/tests/cli/test_experiment_cli.py`

- [ ] **Step 1: Write the failing test**

Create `packages/awp-core/tests/cli/__init__.py` (empty) and `packages/awp-core/tests/cli/test_experiment_cli.py`:

```python
"""CLI-level tests for `awp experiment ...`."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture
def tmp_experiments(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.setenv("AWP_EXPERIMENTS_ROOT", str(tmp_path))
    return tmp_path


def _run_cli(args: list[str], env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "awp", *args],
        capture_output=True,
        text=True,
        env=env,
    )


def test_experiment_create_writes_disk_and_prints_id(
    tmp_experiments: Path, monkeypatch
) -> None:
    import os

    env = os.environ.copy()
    env["AWP_EXPERIMENTS_ROOT"] = str(tmp_experiments)
    # Use an in-memory DB override so the test does not touch ~/.awp.
    env["AWP_UI_DB_PATH"] = str(tmp_experiments / "awp_ui.db")

    result = _run_cli(["experiment", "create", "AWP Paper", "--goal", "For pub"], env=env)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    exp_id = payload["experiment_id"]
    assert exp_id.startswith("exp_")
    assert (tmp_experiments / exp_id / "experiment.json").exists()
    manifest = json.loads(
        (tmp_experiments / exp_id / "experiment.json").read_text()
    )
    assert manifest["name"] == "AWP Paper"
    assert manifest["goal"] == "For pub"


def test_experiment_list_shows_created(
    tmp_experiments: Path,
) -> None:
    import os

    env = os.environ.copy()
    env["AWP_EXPERIMENTS_ROOT"] = str(tmp_experiments)
    env["AWP_UI_DB_PATH"] = str(tmp_experiments / "awp_ui.db")

    _run_cli(["experiment", "create", "First"], env=env)
    _run_cli(["experiment", "create", "Second"], env=env)
    result = _run_cli(["experiment", "list"], env=env)
    assert result.returncode == 0
    items = json.loads(result.stdout)
    assert len(items) == 2
    names = {item["name"] for item in items}
    assert names == {"First", "Second"}


def test_experiment_show_includes_tasks(
    tmp_experiments: Path,
) -> None:
    import os

    env = os.environ.copy()
    env["AWP_EXPERIMENTS_ROOT"] = str(tmp_experiments)
    env["AWP_UI_DB_PATH"] = str(tmp_experiments / "awp_ui.db")

    created = _run_cli(["experiment", "create", "E"], env=env)
    exp_id = json.loads(created.stdout)["experiment_id"]
    result = _run_cli(["experiment", "show", exp_id], env=env)
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["experiment_id"] == exp_id
    assert payload["task_order"] == []


def test_experiment_delete_removes_dir_and_db_row(
    tmp_experiments: Path,
) -> None:
    import os

    env = os.environ.copy()
    env["AWP_EXPERIMENTS_ROOT"] = str(tmp_experiments)
    env["AWP_UI_DB_PATH"] = str(tmp_experiments / "awp_ui.db")

    created = _run_cli(["experiment", "create", "E"], env=env)
    exp_id = json.loads(created.stdout)["experiment_id"]
    assert (tmp_experiments / exp_id).exists()
    result = _run_cli(["experiment", "delete", exp_id, "--yes"], env=env)
    assert result.returncode == 0
    assert not (tmp_experiments / exp_id).exists()
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest packages/awp-core/tests/cli/test_experiment_cli.py -v
```

Expected: all four tests fail — the `experiment` subcommand does not exist.

- [ ] **Step 3: Extend `cli.py` — subparser**

Open `packages/awp-core/src/awp/cli.py`. In `main`, after the existing subparsers are created and **before** the `args = parser.parse_args(argv)` call, insert:

```python
    # experiment
    p_exp = subparsers.add_parser("experiment", help="Manage experiments")
    exp_sub = p_exp.add_subparsers(dest="experiment_cmd", required=True)

    p_exp_create = exp_sub.add_parser("create", help="Create a new experiment")
    p_exp_create.add_argument("name")
    p_exp_create.add_argument("--goal", default="")

    p_exp_list = exp_sub.add_parser("list", help="List experiments")

    p_exp_show = exp_sub.add_parser("show", help="Show experiment detail")
    p_exp_show.add_argument("experiment_id")

    p_exp_delete = exp_sub.add_parser("delete", help="Delete an experiment")
    p_exp_delete.add_argument("experiment_id")
    p_exp_delete.add_argument("--yes", action="store_true", help="skip confirmation")
```

- [ ] **Step 4: Add the dispatch handler**

In the same file, locate the command-dispatch block (usually a chain of `if args.command == "validate": ...` checks). Add:

```python
    if args.command == "experiment":
        from .experiment.cli_handlers import handle_experiment_command

        return handle_experiment_command(args)
```

Create `packages/awp-core/src/awp/experiment/cli_handlers.py`:

```python
"""CLI handlers for `awp experiment ...` and `awp task ...`."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
import time
from argparse import Namespace
from pathlib import Path

from awp.experiment.disk import (
    read_experiment_manifest,
    write_experiment_manifest,
)
from awp.experiment.paths import experiment_dir
from awp.models.experiment import ExperimentManifest


def _ui_db_path() -> Path:
    override = os.environ.get("AWP_UI_DB_PATH")
    if override:
        return Path(override)
    return Path.home() / ".awp" / "awp_ui.db"


async def _with_store(fn):
    # Import here to avoid a hard dep when awp-ui is not installed.
    try:
        from awp_ui.server.services.store import StoreService
    except ModuleNotFoundError:
        return None
    store = StoreService(db_path=_ui_db_path())
    await store.init_db()
    try:
        return await fn(store)
    finally:
        await store.close()


def handle_experiment_command(args: Namespace) -> int:
    cmd = args.experiment_cmd
    if cmd == "create":
        return _exp_create(args.name, args.goal)
    if cmd == "list":
        return _exp_list()
    if cmd == "show":
        return _exp_show(args.experiment_id)
    if cmd == "delete":
        return _exp_delete(args.experiment_id, args.yes)
    print(f"unknown experiment subcommand: {cmd}", file=sys.stderr)
    return 2


def _exp_create(name: str, goal: str) -> int:
    manifest = ExperimentManifest.new(name=name, goal=goal)
    disk_path = write_experiment_manifest(manifest)

    async def _insert(store):
        await store.create_experiment(
            experiment_id=manifest.experiment_id,
            name=manifest.name,
            goal=manifest.goal,
            base_dir=str(experiment_dir(manifest.experiment_id)),
            created_at=time.time(),
        )

    asyncio.run(_with_store(_insert))
    print(
        json.dumps(
            {"experiment_id": manifest.experiment_id, "manifest_path": str(disk_path)},
            indent=2,
        )
    )
    return 0


def _exp_list() -> int:
    async def _fetch(store):
        return await store.list_experiments()

    rows = asyncio.run(_with_store(_fetch)) or []
    print(json.dumps(rows, indent=2, default=str))
    return 0


def _exp_show(experiment_id: str) -> int:
    try:
        manifest = read_experiment_manifest(experiment_id)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(manifest.model_dump_json(indent=2))
    return 0


def _exp_delete(experiment_id: str, yes: bool) -> int:
    exp = experiment_dir(experiment_id)
    if not yes:
        resp = input(f"Delete {exp} and all its runs? [y/N] ").strip().lower()
        if resp != "y":
            print("aborted.")
            return 1
    if exp.exists():
        shutil.rmtree(exp)

    async def _del(store):
        await store.delete_experiment(experiment_id)

    asyncio.run(_with_store(_del))
    print(f"deleted {experiment_id}")
    return 0
```

- [ ] **Step 5: Make `StoreService` accept an explicit path and a `close` method**

Check `packages/awp-ui/server/services/store.py`: the constructor already takes `db_path`. Verify a `close` method exists; if not, add:

```python
    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None
```

- [ ] **Step 6: Run tests to verify they pass**

```
pytest packages/awp-core/tests/cli/test_experiment_cli.py -v
```

Expected: 4 passed.

- [ ] **Step 7: Commit**

```bash
git add packages/awp-core/src/awp/cli.py packages/awp-core/src/awp/experiment/cli_handlers.py packages/awp-core/tests/cli/__init__.py packages/awp-core/tests/cli/test_experiment_cli.py packages/awp-ui/server/services/store.py
git commit -m "feat(cli): awp experiment create/list/show/delete"
```

---

## Task 10: CLI — `awp task create` (seed mode)

**Files:**
- Modify: `packages/awp-core/src/awp/cli.py`
- Modify: `packages/awp-core/src/awp/experiment/cli_handlers.py`
- Test:   `packages/awp-core/tests/cli/test_task_cli.py`

- [ ] **Step 1: Write the failing test**

Create `packages/awp-core/tests/cli/test_task_cli.py`:

```python
"""CLI-level tests for `awp task ...`."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


def _run_cli(args: list[str], env: dict) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "awp", *args],
        capture_output=True,
        text=True,
        env=env,
    )


@pytest.fixture
def env(tmp_path: Path) -> dict:
    env = os.environ.copy()
    env["AWP_EXPERIMENTS_ROOT"] = str(tmp_path)
    env["AWP_UI_DB_PATH"] = str(tmp_path / "awp_ui.db")
    return env


def _mk_exp(env: dict) -> str:
    r = _run_cli(["experiment", "create", "E"], env=env)
    return json.loads(r.stdout)["experiment_id"]


def test_task_create_seed_writes_manifest_and_db(env: dict, tmp_path: Path) -> None:
    exp_id = _mk_exp(env)
    result = _run_cli(
        ["task", "create", exp_id, "Write a paper about AWP"], env=env
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    task_id = payload["task_id"]
    assert task_id.startswith("001-")
    # Disk
    manifest_path = (
        tmp_path / exp_id / "tasks" / task_id / "task.json"
    )
    assert manifest_path.exists()
    manifest = json.loads(manifest_path.read_text())
    assert manifest["mode"] == "seed"
    assert manifest["user_prompt"] == "Write a paper about AWP"
    # Experiment task_order updated
    exp_manifest = json.loads((tmp_path / exp_id / "experiment.json").read_text())
    assert exp_manifest["task_order"] == [task_id]


def test_task_create_seed_increments_number(env: dict, tmp_path: Path) -> None:
    exp_id = _mk_exp(env)
    _run_cli(["task", "create", exp_id, "first"], env=env)
    r2 = _run_cli(["task", "create", exp_id, "second"], env=env)
    assert r2.returncode == 0
    second_id = json.loads(r2.stdout)["task_id"]
    assert second_id.startswith("002-")


def test_task_list_and_show(env: dict) -> None:
    exp_id = _mk_exp(env)
    r1 = _run_cli(["task", "create", exp_id, "first"], env=env)
    task_id = json.loads(r1.stdout)["task_id"]

    r_list = _run_cli(["task", "list", exp_id], env=env)
    assert r_list.returncode == 0
    items = json.loads(r_list.stdout)
    assert len(items) == 1

    r_show = _run_cli(
        ["task", "show", f"{exp_id}:{task_id}"], env=env
    )
    assert r_show.returncode == 0
    payload = json.loads(r_show.stdout)
    assert payload["task_id"] == task_id
    assert payload["mode"] == "seed"


def test_task_delete_removes_dir(env: dict, tmp_path: Path) -> None:
    exp_id = _mk_exp(env)
    r = _run_cli(["task", "create", exp_id, "first"], env=env)
    task_id = json.loads(r.stdout)["task_id"]
    task_path = tmp_path / exp_id / "tasks" / task_id
    assert task_path.exists()

    r_del = _run_cli(
        ["task", "delete", f"{exp_id}:{task_id}", "--yes"], env=env
    )
    assert r_del.returncode == 0
    assert not task_path.exists()
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest packages/awp-core/tests/cli/test_task_cli.py -v
```

Expected: all four fail — `task` subcommand missing.

- [ ] **Step 3: Add the `task` subparser**

In `packages/awp-core/src/awp/cli.py`, after the experiment subparsers:

```python
    # task
    p_task = subparsers.add_parser("task", help="Manage tasks within an experiment")
    task_sub = p_task.add_subparsers(dest="task_cmd", required=True)

    p_task_create = task_sub.add_parser("create", help="Create a task")
    p_task_create.add_argument("experiment_id")
    p_task_create.add_argument("prompt", help="user_prompt (seed) or user_feedback (continuation)")
    p_task_create.add_argument("--continuation", action="store_true")
    p_task_create.add_argument(
        "--from-task",
        action="append",
        default=[],
        help="source task_id (continuation only; may repeat)",
    )
    p_task_create.add_argument(
        "--primary",
        default=None,
        help="primary bundle path (defaults to BEST/ when --from-task given; continuation only)",
    )
    p_task_create.add_argument(
        "--reference",
        action="append",
        default=[],
        help="reference path under source task (may repeat; continuation only)",
    )

    p_task_list = task_sub.add_parser("list", help="List tasks in an experiment")
    p_task_list.add_argument("experiment_id")

    p_task_show = task_sub.add_parser("show", help="Show task detail")
    p_task_show.add_argument("task_key", help="<experiment_id>:<task_id>")

    p_task_delete = task_sub.add_parser("delete", help="Delete a task")
    p_task_delete.add_argument("task_key", help="<experiment_id>:<task_id>")
    p_task_delete.add_argument("--yes", action="store_true")
```

Add dispatch:

```python
    if args.command == "task":
        from .experiment.cli_handlers import handle_task_command

        return handle_task_command(args)
```

- [ ] **Step 4: Implement the handler (seed-mode path only in this task)**

In `packages/awp-core/src/awp/experiment/cli_handlers.py`, first extend the import block at the top of the file (the one added in Task 9) with:

```python
from datetime import datetime, timezone

from awp.experiment.disk import (
    append_task_to_order,
    read_task_manifest,
    write_task_manifest,
)
from awp.experiment.paths import slug_from_prompt, task_dir, task_id_for
from awp.models.task import InputRole, TaskInput, TaskManifest, TaskMode
```

Then append the handler functions below the existing experiment handlers:

```python
def handle_task_command(args: Namespace) -> int:
    cmd = args.task_cmd
    if cmd == "create":
        if args.continuation:
            return _task_create_continuation(args)
        return _task_create_seed(args)
    if cmd == "list":
        return _task_list(args.experiment_id)
    if cmd == "show":
        return _task_show(args.task_key)
    if cmd == "delete":
        return _task_delete(args.task_key, args.yes)
    print(f"unknown task subcommand: {cmd}", file=sys.stderr)
    return 2


def _next_task_number(experiment_id: str) -> int:
    manifest = read_experiment_manifest(experiment_id)
    return len(manifest.task_order) + 1


def _task_create_seed(args: Namespace) -> int:
    if args.from_task or args.primary or args.reference:
        print(
            "--from-task/--primary/--reference require --continuation", file=sys.stderr
        )
        return 2
    number = _next_task_number(args.experiment_id)
    slug = slug_from_prompt(args.prompt)
    tid = task_id_for(number, slug)
    manifest = TaskManifest(
        task_id=tid,
        experiment_id=args.experiment_id,
        task_number=number,
        mode=TaskMode.SEED,
        user_prompt=args.prompt,
        user_feedback=None,
        inputs=[],
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    return _persist_task(args.experiment_id, manifest, slug)


def _persist_task(experiment_id: str, manifest: TaskManifest, slug: str) -> int:
    path = write_task_manifest(experiment_id, manifest)
    append_task_to_order(experiment_id, manifest.task_id)

    async def _insert(store):
        await store.create_task(
            task_id_key=f"{experiment_id}:{manifest.task_id}",
            experiment_id=experiment_id,
            task_number=manifest.task_number,
            slug=slug,
            mode=manifest.mode.value,
            user_prompt=manifest.user_prompt,
            user_feedback=manifest.user_feedback,
            inputs_json=json.dumps(
                [inp.model_dump(mode="json") for inp in manifest.inputs]
            ),
            created_at=time.time(),
        )

    asyncio.run(_with_store(_insert))
    print(
        json.dumps(
            {
                "task_id": manifest.task_id,
                "manifest_path": str(path),
            },
            indent=2,
        )
    )
    return 0


def _task_list(experiment_id: str) -> int:
    async def _fetch(store):
        return await store.list_tasks(experiment_id)

    rows = asyncio.run(_with_store(_fetch)) or []
    print(json.dumps(rows, indent=2, default=str))
    return 0


def _split_key(task_key: str) -> tuple[str, str]:
    if ":" not in task_key:
        raise SystemExit("task key must be <experiment_id>:<task_id>")
    exp_id, tid = task_key.split(":", 1)
    return exp_id, tid


def _task_show(task_key: str) -> int:
    exp_id, tid = _split_key(task_key)
    try:
        manifest = read_task_manifest(exp_id, tid)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(manifest.model_dump_json(indent=2))
    return 0


def _task_delete(task_key: str, yes: bool) -> int:
    exp_id, tid = _split_key(task_key)
    td = task_dir(exp_id, tid)
    if not yes:
        resp = input(f"Delete {td}? [y/N] ").strip().lower()
        if resp != "y":
            return 1
    if td.exists():
        shutil.rmtree(td)

    async def _del(store):
        await store.delete_task(f"{exp_id}:{tid}")

    asyncio.run(_with_store(_del))

    # Remove from task_order
    manifest = read_experiment_manifest(exp_id)
    manifest.task_order = [t for t in manifest.task_order if t != tid]
    write_experiment_manifest(manifest)
    print(f"deleted {task_key}")
    return 0


def _task_create_continuation(args: Namespace) -> int:
    raise NotImplementedError("continuation tasks land in Task 11")
```

- [ ] **Step 5: Run tests to verify they pass**

```
pytest packages/awp-core/tests/cli/test_task_cli.py -v
```

Expected: 4 passed.

- [ ] **Step 6: Commit**

```bash
git add packages/awp-core/src/awp/cli.py packages/awp-core/src/awp/experiment/cli_handlers.py packages/awp-core/tests/cli/test_task_cli.py
git commit -m "feat(cli): awp task create (seed) / list / show / delete"
```

---

## Task 11: CLI — `awp task create --continuation` (R37 enforced)

**Files:**
- Modify: `packages/awp-core/src/awp/experiment/cli_handlers.py`
- Test:   `packages/awp-core/tests/cli/test_task_cli.py` (extend)

- [ ] **Step 1: Write the failing tests**

Append to `packages/awp-core/tests/cli/test_task_cli.py`:

```python
def test_continuation_requires_from_task(env: dict) -> None:
    exp_id = _mk_exp(env)
    _run_cli(["task", "create", exp_id, "seed"], env=env)
    r = _run_cli(
        ["task", "create", exp_id, "fb", "--continuation"], env=env
    )
    assert r.returncode != 0
    assert "requires at least one --from-task" in (r.stderr + r.stdout)


def test_continuation_rejects_nonexistent_from_task(env: dict) -> None:
    exp_id = _mk_exp(env)
    r = _run_cli(
        [
            "task",
            "create",
            exp_id,
            "fb",
            "--continuation",
            "--from-task",
            "001-nope",
        ],
        env=env,
    )
    assert r.returncode != 0
    assert "not found" in (r.stderr + r.stdout).lower()


def test_continuation_with_valid_parent(env: dict, tmp_path: Path) -> None:
    exp_id = _mk_exp(env)
    r1 = _run_cli(["task", "create", exp_id, "seed"], env=env)
    seed_id = json.loads(r1.stdout)["task_id"]
    # Fake a BEST/ directory so R37 parent-has-BEST check passes.
    best = tmp_path / exp_id / "tasks" / seed_id / "BEST"
    best.mkdir(parents=True)
    (best / "manifest.json").write_text('{"winner_run_id":"dummy"}')

    r2 = _run_cli(
        [
            "task",
            "create",
            exp_id,
            "improve",
            "--continuation",
            "--from-task",
            seed_id,
            "--primary",
            "BEST/",
        ],
        env=env,
    )
    assert r2.returncode == 0, r2.stderr + r2.stdout
    task_id = json.loads(r2.stdout)["task_id"]
    assert task_id.startswith("002-")
    manifest = json.loads(
        (tmp_path / exp_id / "tasks" / task_id / "task.json").read_text()
    )
    assert manifest["mode"] == "continuation"
    assert manifest["user_feedback"] == "improve"
    assert manifest["inputs"][0]["from_task"] == seed_id
    assert manifest["inputs"][0]["role"] == "primary"
    assert manifest["inputs"][0]["bundle"] == "BEST/"


def test_continuation_reference_paths(env: dict, tmp_path: Path) -> None:
    exp_id = _mk_exp(env)
    r1 = _run_cli(["task", "create", exp_id, "seed"], env=env)
    seed_id = json.loads(r1.stdout)["task_id"]
    best = tmp_path / exp_id / "tasks" / seed_id / "BEST"
    best.mkdir(parents=True)
    (best / "manifest.json").write_text("{}")

    r2 = _run_cli(
        [
            "task",
            "create",
            exp_id,
            "improve",
            "--continuation",
            "--from-task",
            seed_id,
            "--primary",
            "BEST/",
            "--reference",
            "BEST/analysis/facts.json",
        ],
        env=env,
    )
    assert r2.returncode == 0, r2.stderr + r2.stdout
    task_id = json.loads(r2.stdout)["task_id"]
    manifest = json.loads(
        (tmp_path / exp_id / "tasks" / task_id / "task.json").read_text()
    )
    roles = [inp["role"] for inp in manifest["inputs"]]
    assert "primary" in roles
    assert "reference" in roles
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest packages/awp-core/tests/cli/test_task_cli.py -v
```

Expected: the four continuation tests fail (`NotImplementedError`).

- [ ] **Step 3: Replace `_task_create_continuation`**

In `packages/awp-core/src/awp/experiment/cli_handlers.py`, replace the placeholder `_task_create_continuation` with:

```python
def _task_create_continuation(args: Namespace) -> int:
    if not args.from_task:
        print(
            "continuation task requires at least one --from-task (R37)",
            file=sys.stderr,
        )
        return 2
    # Validate every parent exists with a BEST/ directory
    from awp.experiment.paths import task_dir as _task_dir

    inputs: list[TaskInput] = []
    for src in args.from_task:
        parent_dir = _task_dir(args.experiment_id, src)
        if not parent_dir.exists():
            print(f"from_task not found: {src}", file=sys.stderr)
            return 2
        best = parent_dir / "BEST"
        if not best.exists():
            print(
                f"from_task {src} has no BEST/ — run it to completion first",
                file=sys.stderr,
            )
            return 2
        bundle = args.primary or "BEST/"
        inputs.append(
            TaskInput(from_task=src, role=InputRole.PRIMARY, bundle=bundle)
        )
        for ref in args.reference:
            inputs.append(
                TaskInput(
                    from_task=src, role=InputRole.REFERENCE, paths=[ref]
                )
            )

    number = _next_task_number(args.experiment_id)
    slug = slug_from_prompt(args.prompt)
    tid = task_id_for(number, slug)
    try:
        manifest = TaskManifest(
            task_id=tid,
            experiment_id=args.experiment_id,
            task_number=number,
            mode=TaskMode.CONTINUATION,
            user_prompt=None,
            user_feedback=args.prompt,
            inputs=inputs,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return _persist_task(args.experiment_id, manifest, slug)
```

- [ ] **Step 4: Run tests to verify they pass**

```
pytest packages/awp-core/tests/cli/test_task_cli.py -v
```

Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add packages/awp-core/src/awp/experiment/cli_handlers.py packages/awp-core/tests/cli/test_task_cli.py
git commit -m "feat(cli): awp task create --continuation with R37 enforcement"
```

---

## Task 12: Spec + CLAUDE.md updates

**Files:**
- Modify: `spec/versions/1.0/validation-rules.md`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Add R37 section to `validation-rules.md`**

Read `spec/versions/1.0/validation-rules.md` to locate the R36 section. Immediately after R36's section (before any closing horizontal rule or the next top-level heading), insert:

```markdown
## 13. Continuation Rules

### R37 — Continuation-Task Input Non-Emptiness

A task with `mode == "continuation"` **MUST** have a non-empty `inputs` array, and every entry **MUST** reference a `from_task` that exists in the same experiment and has produced a terminal run recorded in `BEST/manifest.json`. Tasks violating R37 are rejected at task-create time and **MUST NOT** produce a run.

**Rationale.** Silent "continuation-as-seed" tasks (created with `--continuation` but no inputs, or with a dangling `from_task`) would produce a Manager prompt containing the continuation scaffolding but no actual prior material. R37 makes the invariant load-bearing and refuses the run at creation time rather than at Manager-prompt time.

**Enforcement.** Pydantic validator on `TaskManifest` (`packages/awp-core/src/awp/models/task.py`) plus the CLI handler in `packages/awp-core/src/awp/experiment/cli_handlers.py`.
```

- [ ] **Step 2: Add CLI commands to `CLAUDE.md` Development Commands**

In `CLAUDE.md`, locate the "## Development Commands" code block and append (inside the same `bash` block):

```
# Experiment + task lifecycle (hierarchy — see spec 2026-04-20-experiment-task-hierarchy-design.md)
awp experiment create "<name>" [--goal "<goal>"]   # new top-level experiment
awp experiment list
awp experiment show <experiment_id>
awp experiment delete <experiment_id> [--yes]

awp task create <experiment_id> "<user_prompt>"    # mode=seed
awp task create <experiment_id> "<user_feedback>" \
    --continuation --from-task <task_id> \
    [--primary BEST/] [--reference <relpath> ...]  # mode=continuation (R37)
awp task list <experiment_id>
awp task show <experiment_id>:<task_id>
awp task delete <experiment_id>:<task_id> [--yes]
```

- [ ] **Step 3: Verify doc drift gate is green**

```
python scripts/check_docs_drift.py
```

Expected: exit 0. If it complains about the new path references, either the file paths are wrong or the drift script needs to acknowledge the new paths — fix whichever is actually wrong.

- [ ] **Step 4: Verify sync coverage gate is green**

```
python scripts/check_sync_coverage.py
```

Expected: exit 0.

- [ ] **Step 5: Commit**

```bash
git add spec/versions/1.0/validation-rules.md CLAUDE.md
git commit -m "docs(spec): add R37 (continuation input non-emptiness) + CLI surface"
```

---

## Task 13: Full suite regression + mirror sync

**Files:**
- Sync: `reference/python/src/awp/...` (mirror gate)

- [ ] **Step 1: Run the full unit + integration suite**

```
pytest packages/awp-core/tests/ packages/awp-runtime/tests/ -k "not e2e"
```

Expected: all green. If pre-existing failures surface, isolate whether they are plan-related or pre-existing — do **not** silence them.

- [ ] **Step 2: Sync the reference mirror**

```
rsync -a --delete packages/awp-core/src/awp/ reference/python/src/awp/
rsync -a --delete packages/awp-runtime/src/awp/ reference/python/src/awp/
rsync -a --delete packages/awp-ui/server/ reference/python/src/server/
```

Note: the three `rsync` commands partially overlap `awp/` — consult the existing sync procedure if one exists; the rule is that `packages/*/src/awp/` is byte-identical to `reference/python/src/awp/` **as enforced by** `scripts/check_mirror_drift.py`.

- [ ] **Step 3: Verify mirror drift gate**

```
python scripts/check_mirror_drift.py
```

Expected: exit 0.

- [ ] **Step 4: Commit the mirror sync**

```bash
git add reference/python/src/
git commit -m "chore(mirror): sync reference/python/src with hierarchy foundation"
```

---

## Self-review checklist

Before declaring the plan complete:

- Every required import in a code block is actually present in that block.
- `_with_store(fn)` is defined once in `cli_handlers.py` and reused across experiment + task commands — no duplication.
- `handle_task_command` dispatches to four functions that all exist (`_task_create_seed`, `_task_create_continuation`, `_task_list`, `_task_show`, `_task_delete`).
- `_persist_task` is called by both seed + continuation paths — no divergence in DB write logic.
- R37 fires at two places (Pydantic validator + CLI pre-check) and the error text contains the literal string `R37` at least in the Pydantic message — matching `test_continuation_r37_empty_inputs`.
- `AWP_EXPERIMENTS_ROOT` is respected everywhere (paths.py reads it at import; the disk test reloads the module via `importlib.reload`).
- The mirror gate runs last; no code-change commit after Task 13 without a re-run.

---

## Handoff to Plan 2

At the end of Plan 1 the repo has:
- Pydantic models for `ExperimentManifest` + `TaskManifest` (with R37).
- `experiments` + `tasks` tables in `awp_ui.db`; `experiment_id`/`task_id`/`run_role`/`parent_run_id`/`loss` columns on `runs`.
- Full CLI for experiment + task lifecycle.
- Spec + `CLAUDE.md` updates.

Plan 2 picks up:
- `awp run --task` integration, implicit experiment for bare `awp run`.
- BEST finaliser on run completion (auto lowest-loss).
- `awp task set-best --run / --auto` (now meaningful since runs exist).
- E2E: two tasks, real LLM, seed on Task 001, verify BEST is written and `runs.task_id` populated.
