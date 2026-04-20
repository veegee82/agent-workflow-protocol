# Plan 2 — Runtime Integration: `awp run --target`, DB Registration, BEST Finaliser

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **IMPORTANT — Flag Rename Applied Post-Draft:**
> The new hierarchy-attach flag is **`--target`**, NOT `--task`. `awp run --task "<free text>"` already exists pre-Plan-2 as a **required positional** for the task description — we must NOT collide with it. Everywhere this plan document says `--task` in the context of "attach this run to a task in the hierarchy", read it as **`--target`**. Correspondingly, `args.task` (the key validation target) becomes `args.target`. The attribute `args.task` still holds the legacy free-text task description and is passed to the runner as before.
>
> Task 1 was already implemented with this rename applied (commit `113831f` + follow-up `70a77b1` — see git log). Subsequent tasks MUST use `--target` / `args.target` anywhere code below references `--task` as a key-attach flag.

**Goal:** A seed task run via `awp run --task <exp>:<task>` lands under `<experiment>/tasks/<task>/seed/output/<run_id>/`, the row is registered in `awp_ui.db` with `experiment_id`/`task_id`/`run_role`/`loss`, and `<task>/BEST/manifest.json` auto-updates to point at the lowest-loss run.

**Architecture:** Thin-slice integration at the CLI wrapper layer, **no runtime-internal changes**. `awp run --task …` bypasses the legacy `WorkflowRunner` and calls `AgentWorkflow` (delegation-loop path) with `output_dir` preset to the task's seed directory. A post-run hook reads `run_completion.json`, computes loss via `compute_run_loss`, upserts the `runs` row, and invokes the BEST finaliser. The BEST finaliser is a standalone module that compares the new run's loss against the current `<task>/BEST/manifest.json` and hardlinks in the winner's `FINAL/`.

**Tech Stack:** Python 3.10+, Pydantic v2, aiosqlite, argparse, pytest. Uses existing `compute_run_loss` (`packages/awp-runtime/src/awp/outer_loop/loss.py`).

**Spec reference:** `docs/superpowers/specs/2026-04-20-experiment-task-hierarchy-design.md` §4 decisions 1/4, §6.5 BEST manifest, §7.5 BEST finaliser, §8.3 CLI.

**Out of scope for this plan:**
- Implicit experiment for bare `awp run` (deferred — not critical for core flow).
- Continuation-task runs — Plan 2 REJECTS `--task <cont>` at CLI time with a clear error pointing at Plan 3. R37 is already enforced at task-create time.
- Refinement / optimize relocation (Plan 4).
- UI routes + sidebar tree (Plan 5).
- `AgentWorkflow` signature extensions (no new params; we use the existing `output_dir` / `parent_run_id` / `tags` already in place).

---

## Known-deviation note: `FINAL/` extra layer

The runtime writes artifacts to `<output_dir>/output/<run_id>/` — not directly to `<output_dir>/<run_id>/`. This means a seed run with `output_dir=<task>/seed/` produces:

```
<task>/seed/output/<run_id>/{run_completion.json, FINAL/, events.jsonl, …}
```

The spec §5 showed `<task>/seed/<run_id>/{…}` (no extra `output/` layer). This plan follows the **runtime's natural shape** (`seed/output/<run_id>/`) and treats the spec figure as illustrative. The spec is updated in Task 8 to match.

---

## File structure

**Created:**
- `packages/awp-runtime/src/awp/experiment/__init__.py` — package marker (runtime-side experiment helpers).
- `packages/awp-runtime/src/awp/experiment/best_finaliser.py` — `compute_and_update_best(task_dir, new_run_dir, force_override=False, ui_db_path=None)`.
- `packages/awp-runtime/tests/experiment/__init__.py`
- `packages/awp-runtime/tests/experiment/test_best_finaliser.py`
- `packages/awp-core/tests/cli/test_run_task_cli.py` — integration tests for `awp run --task` (no real LLM; uses a recorded fake `run_completion.json`).
- `packages/awp-core/tests/cli/test_task_set_best_cli.py` — tests for `awp task set-best --run/--auto`.

**Modified:**
- `packages/awp-core/src/awp/cli.py` — add `--task` to the existing `awp run` subparser.
- `packages/awp-core/src/awp/experiment/cli_handlers.py` — add `_post_run_register` helper + extend `handle_task_command` with the `set_best` case + extend the CLI dispatch in `cli.py` for `awp task set-best`.
- `packages/awp-core/src/awp/cli.py` — post-run hook after `cmd_run` completes, when `--task` was passed.
- `packages/awp-ui/server/services/store.py` — add `upsert_run_for_task(run_id, experiment_id, task_id, run_role, loss, status)` and `get_best_for_task(task_id_key) -> dict | None` and `set_task_best(task_id_key, run_id, reason, loss) -> None`.
- `packages/awp-core/src/awp/cli.py` — `awp task set-best` subparser (new subsubcommand on `task`).

---

## Task 1: CLI — add `--task` option to `awp run`

**Files:**
- Modify: `packages/awp-core/src/awp/cli.py`
- Test:   `packages/awp-core/tests/cli/test_run_task_cli.py`

**Background.** The `awp run` subparser exists (lines ~106-135 in `cli.py`) and already takes `path` + model flags. We add a single optional `--task` argument. Absent → behavior unchanged; present → triggers the task-aware path in Task 4.

- [ ] **Step 1: Write failing test**

Create `packages/awp-core/tests/cli/test_run_task_cli.py`:

```python
"""CLI-level tests for `awp run --task`."""

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


def test_run_rejects_continuation_task(env: dict, tmp_path: Path) -> None:
    # Setup: create an experiment + seed task + a fake BEST manifest,
    # then create a continuation task that references it.
    r = _run_cli(["experiment", "create", "E"], env=env)
    exp_id = json.loads(r.stdout)["experiment_id"]
    r = _run_cli(["task", "create", exp_id, "seed"], env=env)
    seed_id = json.loads(r.stdout)["task_id"]
    best = tmp_path / exp_id / "tasks" / seed_id / "BEST"
    best.mkdir(parents=True)
    (best / "manifest.json").write_text("{}")
    r = _run_cli(
        [
            "task", "create", exp_id, "fb",
            "--continuation", "--from-task", seed_id, "--primary", "BEST/",
        ],
        env=env,
    )
    cont_id = json.loads(r.stdout)["task_id"]

    # Act: `awp run --task <exp>:<cont>` must refuse
    r = _run_cli(
        ["run", "nonexistent-workflow.yaml", "--task", f"{exp_id}:{cont_id}"],
        env=env,
    )
    assert r.returncode != 0
    combined = r.stderr + r.stdout
    assert "continuation" in combined.lower()
    assert "plan 3" in combined.lower()


def test_run_rejects_unknown_task(env: dict) -> None:
    r = _run_cli(
        ["run", "nonexistent-workflow.yaml", "--task", "exp_nosuch1:001-x"],
        env=env,
    )
    assert r.returncode != 0
    assert "experiment not found" in (r.stderr + r.stdout).lower() or \
           "task not found" in (r.stderr + r.stdout).lower()


def test_run_rejects_malformed_task_key(env: dict) -> None:
    r = _run_cli(
        ["run", "nonexistent-workflow.yaml", "--task", "not-a-key"],
        env=env,
    )
    assert r.returncode != 0
    assert "<experiment_id>:<task_id>" in (r.stderr + r.stdout)
```

Note: these three tests intentionally pass a nonexistent workflow file — they should fail **before** the runner is invoked (the `--task` validation happens first).

- [ ] **Step 2: Run — expect failures**

```
pytest packages/awp-core/tests/cli/test_run_task_cli.py -v
```

Expected: all three fail (either argparse rejects `--task` or the validation is missing).

- [ ] **Step 3: Add `--task` to the `awp run` subparser**

In `packages/awp-core/src/awp/cli.py`, locate the `awp run` subparser registration. Search for:

```
grep -n "subparsers.add_parser(" packages/awp-core/src/awp/cli.py | grep -i '"run"'
```

Add one line after the existing `--worker-model` / `--debug` flags:

```python
    p_run.add_argument(
        "--task",
        default=None,
        help="Target task key (format: <experiment_id>:<task_id>)",
    )
```

- [ ] **Step 4: Add validation at the top of `cmd_run`**

In `packages/awp-core/src/awp/cli.py`, find `def cmd_run(args)` (around line 916). At the very top of the function (before any existing logic), insert:

```python
    if args.task is not None:
        from .experiment.cli_handlers import validate_task_key_for_run

        rc = validate_task_key_for_run(args.task)
        if rc != 0:
            return rc
```

- [ ] **Step 5: Implement the validator**

In `packages/awp-core/src/awp/experiment/cli_handlers.py`, add:

```python
def validate_task_key_for_run(task_key: str) -> int:
    """Validate --task argument for `awp run`. Returns 0 on OK, non-zero on error."""
    if ":" not in task_key:
        print(
            "--task must be <experiment_id>:<task_id>",
            file=sys.stderr,
        )
        return 2
    exp_id, tid = task_key.split(":", 1)
    from awp.experiment.paths import experiment_dir as _exp_dir
    if not _exp_dir(exp_id).exists():
        print(f"experiment not found: {exp_id}", file=sys.stderr)
        return 2
    try:
        manifest = read_task_manifest(exp_id, tid)
    except FileNotFoundError:
        print(f"task not found: {task_key}", file=sys.stderr)
        return 2
    if manifest.mode.value == "continuation":
        print(
            f"continuation task runs are not yet supported in this build "
            f"(scheduled for Plan 3 — continuation-loader). Task {task_key} "
            f"has mode=continuation.",
            file=sys.stderr,
        )
        return 2
    return 0
```

- [ ] **Step 6: Run tests — expect pass**

```
pytest packages/awp-core/tests/cli/test_run_task_cli.py -v
```

Expected: 3 passed.

- [ ] **Step 7: Full core regression**

```
pytest packages/awp-core/tests/ 2>&1 | tail -5
```

Expected: no regressions.

- [ ] **Step 8: Commit**

```bash
git add packages/awp-core/src/awp/cli.py packages/awp-core/src/awp/experiment/cli_handlers.py packages/awp-core/tests/cli/test_run_task_cli.py
git commit -m "feat(cli): awp run --task validates experiment/task key"
```

---

## Task 2: Store method — upsert run for a task

**Files:**
- Modify: `packages/awp-ui/server/services/store.py`
- Test:   `packages/awp-ui/server/tests/test_store_experiments.py` (extend)

**Background.** CLI-invoked runs never touched `awp_ui.db` before. For the hierarchy, we need to upsert a row keyed on `run_id` that carries `experiment_id`, `task_id`, `run_role`, `loss`, and `status`.

- [ ] **Step 1: Write failing tests**

Append to `packages/awp-ui/server/tests/test_store_experiments.py`:

```python
@pytest.mark.asyncio
async def test_upsert_run_inserts_new(store: StoreService) -> None:
    await store.create_experiment("exp_aaaaaaaa", "E", "", "/tmp/a", 1.0)
    await store.create_task(
        "exp_aaaaaaaa:001-s", "exp_aaaaaaaa", 1, "s", "seed", "p", None, "[]", 1.0,
    )
    await store.upsert_run_for_task(
        run_id="2026-04-20_15-00-00_abc12345",
        experiment_id="exp_aaaaaaaa",
        task_id="exp_aaaaaaaa:001-s",
        run_role="seed",
        loss=0.42,
        status="complete",
        task="Write paper",
        model="openai/gpt-5-mini",
    )
    cur = await store.db.execute(
        "SELECT id, experiment_id, task_id, run_role, loss, status FROM runs WHERE id = ?",
        ("2026-04-20_15-00-00_abc12345",),
    )
    row = await cur.fetchone()
    assert row is not None
    assert row["experiment_id"] == "exp_aaaaaaaa"
    assert row["task_id"] == "exp_aaaaaaaa:001-s"
    assert row["run_role"] == "seed"
    assert row["loss"] == pytest.approx(0.42)
    assert row["status"] == "complete"


@pytest.mark.asyncio
async def test_upsert_run_updates_existing(store: StoreService) -> None:
    await store.create_experiment("exp_aaaaaaaa", "E", "", "/tmp/a", 1.0)
    await store.create_task(
        "exp_aaaaaaaa:001-s", "exp_aaaaaaaa", 1, "s", "seed", "p", None, "[]", 1.0,
    )
    # First insert (e.g. run just started, loss unknown)
    await store.upsert_run_for_task(
        run_id="rid1",
        experiment_id="exp_aaaaaaaa",
        task_id="exp_aaaaaaaa:001-s",
        run_role="seed",
        loss=None,
        status="running",
        task="t",
        model="m",
    )
    # Second upsert (run completed)
    await store.upsert_run_for_task(
        run_id="rid1",
        experiment_id="exp_aaaaaaaa",
        task_id="exp_aaaaaaaa:001-s",
        run_role="seed",
        loss=0.3,
        status="complete",
        task="t",
        model="m",
    )
    cur = await store.db.execute(
        "SELECT loss, status FROM runs WHERE id = ?", ("rid1",)
    )
    row = await cur.fetchone()
    assert row["loss"] == pytest.approx(0.3)
    assert row["status"] == "complete"


@pytest.mark.asyncio
async def test_set_and_get_task_best(store: StoreService) -> None:
    await store.create_experiment("exp_aaaaaaaa", "E", "", "/tmp/a", 1.0)
    await store.create_task(
        "exp_aaaaaaaa:001-s", "exp_aaaaaaaa", 1, "s", "seed", "p", None, "[]", 1.0,
    )
    await store.upsert_run_for_task(
        "rid1", "exp_aaaaaaaa", "exp_aaaaaaaa:001-s", "seed", 0.5, "complete", "t", "m",
    )
    await store.set_task_best(
        task_id_key="exp_aaaaaaaa:001-s",
        run_id="rid1",
        reason="auto_loss",
    )
    best = await store.get_best_for_task("exp_aaaaaaaa:001-s")
    assert best is not None
    assert best["best_run_id"] == "rid1"
    assert best["best_reason"] == "auto_loss"
```

- [ ] **Step 2: Run — expect failures**

```
pytest packages/awp-ui/server/tests/test_store_experiments.py -v -k "upsert or task_best"
```

Expected: 3 failures (methods undefined).

- [ ] **Step 3: Implement the methods**

In `packages/awp-ui/server/services/store.py`, inside `StoreService`, after the existing task CRUD block, add:

```python
    # ---- run registration (task-aware) ----

    async def upsert_run_for_task(
        self,
        run_id: str,
        experiment_id: str,
        task_id: str,
        run_role: str,
        loss: float | None,
        status: str,
        task: str,
        model: str,
    ) -> None:
        """Insert or update a run row with hierarchy metadata."""
        now = datetime.now(timezone.utc).isoformat()
        await self.db.execute(
            """
            INSERT INTO runs (
                id, task, model, status, experiment_id, task_id, run_role, loss,
                config_json, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, '{}', ?)
            ON CONFLICT(id) DO UPDATE SET
                status = excluded.status,
                loss = excluded.loss,
                experiment_id = excluded.experiment_id,
                task_id = excluded.task_id,
                run_role = excluded.run_role
            """,
            (
                run_id, task, model, status, experiment_id, task_id, run_role, loss,
                now,
            ),
        )
        await self.db.commit()

    async def set_task_best(
        self,
        task_id_key: str,
        run_id: str,
        reason: str,
    ) -> None:
        await self.db.execute(
            "UPDATE tasks SET best_run_id = ?, best_reason = ? WHERE id = ?",
            (run_id, reason, task_id_key),
        )
        await self.db.commit()

    async def get_best_for_task(self, task_id_key: str) -> dict | None:
        cur = await self.db.execute(
            "SELECT best_run_id, best_reason FROM tasks WHERE id = ?",
            (task_id_key,),
        )
        row = await cur.fetchone()
        if row is None or row["best_run_id"] is None:
            return None
        return dict(row)
```

Also ensure `from datetime import datetime, timezone` is imported at the top of `store.py` (existing imports may already cover this — verify).

- [ ] **Step 4: Run tests — expect pass**

```
pytest packages/awp-ui/server/tests/test_store_experiments.py -v
```

Expected: 13 passed (10 from Plan 1 + 3 new).

- [ ] **Step 5: Commit**

```bash
git add packages/awp-ui/server/services/store.py packages/awp-ui/server/tests/test_store_experiments.py
git commit -m "feat(ui-store): upsert_run_for_task + set_task_best + get_best_for_task"
```

---

## Task 3: BEST finaliser module

**Files:**
- Create: `packages/awp-runtime/src/awp/experiment/__init__.py`
- Create: `packages/awp-runtime/src/awp/experiment/best_finaliser.py`
- Test:   `packages/awp-runtime/tests/experiment/__init__.py` (empty)
- Test:   `packages/awp-runtime/tests/experiment/test_best_finaliser.py`

**Background.** The BEST finaliser is a pure function: given a task directory and a freshly-finished run directory, it reads both, computes loss via `compute_run_loss`, decides whether the new run wins, and rewrites `<task>/BEST/manifest.json` + hardlinks the new `FINAL/` into `<task>/BEST/`.

- [ ] **Step 1: Write failing tests**

Create `packages/awp-runtime/tests/experiment/__init__.py` (empty) and `packages/awp-runtime/tests/experiment/test_best_finaliser.py`:

```python
"""Tests for the BEST finaliser."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from awp.experiment.best_finaliser import compute_and_update_best


def _mk_run_dir(
    base: Path,
    run_id: str,
    status: str = "complete",
    eval_score: float = 0.8,
    gate_rejections: int = 0,
) -> Path:
    """Build a minimal run_dir with a run_completion.json + FINAL/."""
    run_dir = base / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "FINAL").mkdir(exist_ok=True)
    (run_dir / "FINAL" / "paper.md").write_text(f"draft from {run_id}")
    completion = {
        "run_id": run_id,
        "status": status,
        "task": "t",
        "final_budget": {"loops": {"used": 1, "cap": 10}, "tokens": {"used": 1000, "cap": 100000}},
        "evaluation": {"score": eval_score, "per_metric": {}},
        "critique": {"defects": []},
        "gate_rejections": gate_rejections,
    }
    (run_dir / "run_completion.json").write_text(json.dumps(completion))
    (run_dir / "events.jsonl").write_text("")
    (run_dir / "metrics.jsonl").write_text("")
    return run_dir


def test_first_run_becomes_best(tmp_path: Path) -> None:
    task_dir = tmp_path / "task"
    task_dir.mkdir()
    run = _mk_run_dir(task_dir / "seed" / "output", "run1", eval_score=0.8)

    result = compute_and_update_best(task_dir=task_dir, new_run_dir=run)

    assert result.updated is True
    assert result.reason == "auto_loss"
    manifest_path = task_dir / "BEST" / "manifest.json"
    assert manifest_path.exists()
    manifest = json.loads(manifest_path.read_text())
    assert manifest["winner_run_id"] == "run1"
    assert manifest["reason"] == "auto_loss"
    assert manifest["loss"] == pytest.approx(result.new_loss)
    assert (task_dir / "BEST" / "paper.md").exists()


def test_lower_loss_wins(tmp_path: Path) -> None:
    task_dir = tmp_path / "task"
    task_dir.mkdir()
    run1 = _mk_run_dir(task_dir / "seed" / "output", "run1", eval_score=0.5)
    compute_and_update_best(task_dir=task_dir, new_run_dir=run1)
    run2 = _mk_run_dir(task_dir / "seed" / "output", "run2", eval_score=0.95)

    result = compute_and_update_best(task_dir=task_dir, new_run_dir=run2)

    assert result.updated is True
    manifest = json.loads((task_dir / "BEST" / "manifest.json").read_text())
    assert manifest["winner_run_id"] == "run2"
    assert (task_dir / "BEST" / "paper.md").read_text() == "draft from run2"


def test_higher_loss_does_not_win(tmp_path: Path) -> None:
    task_dir = tmp_path / "task"
    task_dir.mkdir()
    run1 = _mk_run_dir(task_dir / "seed" / "output", "run1", eval_score=0.95)
    compute_and_update_best(task_dir=task_dir, new_run_dir=run1)
    run2 = _mk_run_dir(task_dir / "seed" / "output", "run2", eval_score=0.1)

    result = compute_and_update_best(task_dir=task_dir, new_run_dir=run2)

    assert result.updated is False
    manifest = json.loads((task_dir / "BEST" / "manifest.json").read_text())
    assert manifest["winner_run_id"] == "run1"


def test_user_override_is_preserved(tmp_path: Path) -> None:
    task_dir = tmp_path / "task"
    task_dir.mkdir()
    run1 = _mk_run_dir(task_dir / "seed" / "output", "run1", eval_score=0.5)
    compute_and_update_best(task_dir=task_dir, new_run_dir=run1)
    # Simulate user override
    manifest_path = task_dir / "BEST" / "manifest.json"
    m = json.loads(manifest_path.read_text())
    m["reason"] = "user_override"
    manifest_path.write_text(json.dumps(m))

    # A new, objectively lower-loss run must NOT displace the override
    run2 = _mk_run_dir(task_dir / "seed" / "output", "run2", eval_score=0.99)
    result = compute_and_update_best(task_dir=task_dir, new_run_dir=run2)

    assert result.updated is False
    assert result.skip_reason == "user_override"
    m2 = json.loads(manifest_path.read_text())
    assert m2["winner_run_id"] == "run1"
    assert m2["reason"] == "user_override"


def test_force_override_replaces_any(tmp_path: Path) -> None:
    task_dir = tmp_path / "task"
    task_dir.mkdir()
    run1 = _mk_run_dir(task_dir / "seed" / "output", "run1", eval_score=0.95)
    compute_and_update_best(task_dir=task_dir, new_run_dir=run1)
    # A higher-loss run forced to BEST by user action
    run2 = _mk_run_dir(task_dir / "seed" / "output", "run2", eval_score=0.1)

    result = compute_and_update_best(
        task_dir=task_dir,
        new_run_dir=run2,
        force_override=True,
    )

    assert result.updated is True
    assert result.reason == "user_override"
    m = json.loads((task_dir / "BEST" / "manifest.json").read_text())
    assert m["winner_run_id"] == "run2"
    assert m["reason"] == "user_override"


def test_non_terminal_run_is_skipped(tmp_path: Path) -> None:
    task_dir = tmp_path / "task"
    task_dir.mkdir()
    # status other than complete/partial
    run = _mk_run_dir(task_dir / "seed" / "output", "run1", status="failed")

    result = compute_and_update_best(task_dir=task_dir, new_run_dir=run)

    assert result.updated is False
    assert result.skip_reason == "non_terminal"
    assert not (task_dir / "BEST" / "manifest.json").exists()
```

- [ ] **Step 2: Run — expect ModuleNotFoundError**

```
pytest packages/awp-runtime/tests/experiment/test_best_finaliser.py -v
```

- [ ] **Step 3: Implement**

Create `packages/awp-runtime/src/awp/experiment/__init__.py`:

```python
"""Runtime-side experiment helpers (BEST finaliser, loss integration)."""
```

Create `packages/awp-runtime/src/awp/experiment/best_finaliser.py`:

```python
"""BEST finaliser: auto-updates <task>/BEST/ based on lowest `compute_run_loss`.

This module is a pure function-level API. It does NOT touch the UI DB —
the CLI caller is responsible for mirroring the decision to `awp_ui.db` via
`StoreService.set_task_best`.
"""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from awp.outer_loop.loss import compute_run_loss


@dataclass
class FinaliseResult:
    updated: bool
    reason: str | None          # "auto_loss" or "user_override" on update
    new_loss: float | None
    prior_loss: float | None
    skip_reason: str | None     # "user_override" | "non_terminal" | "no_change"


def compute_and_update_best(
    task_dir: Path,
    new_run_dir: Path,
    force_override: bool = False,
) -> FinaliseResult:
    """Compare new_run_dir to <task>/BEST/ and update if new loss is strictly lower.

    Semantics:
    - If `force_override` is True, the new run becomes BEST unconditionally with
      reason="user_override" (used by `awp task set-best --run`).
    - If the current BEST manifest has `reason == "user_override"` and
      `force_override is False`, the new run is NOT auto-displaced.
    - Only runs with `status in {"complete","partial"}` are eligible for BEST.
    - Loss must be present; NULL loss runs are skipped.
    """
    completion_path = new_run_dir / "run_completion.json"
    if not completion_path.exists():
        return FinaliseResult(
            updated=False, reason=None, new_loss=None, prior_loss=None,
            skip_reason="no_completion",
        )
    completion = json.loads(completion_path.read_text())
    status = completion.get("status")
    if status not in ("complete", "partial") and not force_override:
        return FinaliseResult(
            updated=False, reason=None, new_loss=None, prior_loss=None,
            skip_reason="non_terminal",
        )

    new_loss_breakdown = compute_run_loss(new_run_dir)
    new_loss = new_loss_breakdown.total

    best_dir = task_dir / "BEST"
    manifest_path = best_dir / "manifest.json"
    prior_manifest: dict | None = None
    prior_loss: float | None = None
    if manifest_path.exists():
        prior_manifest = json.loads(manifest_path.read_text())
        prior_loss = prior_manifest.get("loss")
        if prior_manifest.get("reason") == "user_override" and not force_override:
            return FinaliseResult(
                updated=False, reason=None, new_loss=new_loss, prior_loss=prior_loss,
                skip_reason="user_override",
            )

    if (
        not force_override
        and prior_loss is not None
        and new_loss >= prior_loss
    ):
        return FinaliseResult(
            updated=False, reason=None, new_loss=new_loss, prior_loss=prior_loss,
            skip_reason="no_change",
        )

    # Update BEST
    reason = "user_override" if force_override else "auto_loss"
    _rewrite_best(
        best_dir=best_dir,
        winner_run_dir=new_run_dir,
        winner_run_id=completion.get("run_id") or new_run_dir.name,
        loss=new_loss,
        loss_breakdown=new_loss_breakdown,
        reason=reason,
    )
    return FinaliseResult(
        updated=True, reason=reason, new_loss=new_loss, prior_loss=prior_loss,
        skip_reason=None,
    )


def _rewrite_best(
    best_dir: Path,
    winner_run_dir: Path,
    winner_run_id: str,
    loss: float,
    loss_breakdown,
    reason: str,
) -> None:
    # Clear existing files (except manifest.json, which we'll rewrite)
    if best_dir.exists():
        for p in best_dir.iterdir():
            if p.name == "manifest.json":
                continue
            if p.is_dir():
                shutil.rmtree(p)
            else:
                p.unlink()
    best_dir.mkdir(parents=True, exist_ok=True)

    # Hardlink or copy files from winner's FINAL/
    final_src = winner_run_dir / "FINAL"
    if final_src.exists() and final_src.is_dir():
        for src in final_src.rglob("*"):
            if src.is_dir():
                continue
            rel = src.relative_to(final_src)
            dst = best_dir / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.link(src, dst)
            except OSError:
                shutil.copy2(src, dst)

    manifest = {
        "winner_run_id": winner_run_id,
        "winner_source": str(winner_run_dir),
        "reason": reason,
        "loss": loss,
        "loss_breakdown": {
            "eval": loss_breakdown.eval_loss,
            "critique": loss_breakdown.critique_loss,
            "gate_reject": loss_breakdown.gate_reject_loss,
            "budget_burn": loss_breakdown.budget_burn_loss,
            "terminal": loss_breakdown.terminal_loss,
        },
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    (best_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
```

**Note:** The `loss_breakdown` attribute names (`eval_loss`, `critique_loss`, etc.) must match `LossBreakdown`'s actual field names. If they differ, adjust the dict keys — look at `packages/awp-runtime/src/awp/outer_loop/loss.py:62` for the dataclass definition and use the real field names.

- [ ] **Step 4: Run tests**

```
pytest packages/awp-runtime/tests/experiment/test_best_finaliser.py -v
```

Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add packages/awp-runtime/src/awp/experiment/ packages/awp-runtime/tests/experiment/
git commit -m "feat(runtime): BEST finaliser — compute_and_update_best"
```

---

## Task 4: Wire `awp run --task` → `AgentWorkflow` path

**Files:**
- Modify: `packages/awp-core/src/awp/cli.py`
- Modify: `packages/awp-core/src/awp/experiment/cli_handlers.py`
- Test:   `packages/awp-core/tests/cli/test_run_task_cli.py` (extend with one positive-path test using a mock)

**Background.** When `--task <exp>:<task>` is provided, `cmd_run` must bypass the old `WorkflowRunner` and invoke `AgentWorkflow` with `output_dir=<experiment>/tasks/<task>/seed/`. For Plan 2 we DO NOT touch `WorkflowRunner` — the old path stays for bare `awp run`.

Because `AgentWorkflow` lives in `awp-runtime` (not `awp-core`), the import must be deferred (inside the function).

- [ ] **Step 1: Add a positive-path integration test using a fake workflow runner**

Append to `packages/awp-core/tests/cli/test_run_task_cli.py`:

```python
def test_run_with_task_calls_agentworkflow_with_task_output_dir(
    env: dict, tmp_path: Path, monkeypatch
) -> None:
    """Verify cmd_run with --task routes through the task-aware path."""
    # Setup
    r = _run_cli(["experiment", "create", "E"], env=env)
    exp_id = json.loads(r.stdout)["experiment_id"]
    r = _run_cli(["task", "create", exp_id, "seed"], env=env)
    task_id = json.loads(r.stdout)["task_id"]

    # A dummy workflow.yaml (does not need to be valid — we assert on path
    # resolution before the runner actually runs).
    wf = tmp_path / "wf"
    wf.mkdir()
    (wf / "workflow.awp.yaml").write_text("name: test\n")

    # Use a monkeypatch-style env flag to make AgentWorkflow fail fast
    # but print the output_dir it was asked to use.
    env2 = env.copy()
    env2["AWP_RUN_TASK_DRY_RUN"] = "1"

    r = _run_cli(
        ["run", str(wf), "--task", f"{exp_id}:{task_id}"],
        env=env2,
    )
    combined = r.stdout + r.stderr
    # The dry-run branch prints the target output_dir and exits 0.
    expected_prefix = str(tmp_path / exp_id / "tasks" / task_id / "seed")
    assert r.returncode == 0, combined
    assert expected_prefix in combined
```

The `AWP_RUN_TASK_DRY_RUN` env var is introduced in Step 3 below as an internal test hook — it makes the handler print the computed `output_dir` and exit before calling the heavy runner.

- [ ] **Step 2: Run — expect failure (env var ignored, runner attempts to run)**

```
pytest packages/awp-core/tests/cli/test_run_task_cli.py::test_run_with_task_calls_agentworkflow_with_task_output_dir -v
```

Expected: fails (runner tries to actually execute the fake workflow).

- [ ] **Step 3: Add the task-aware dispatch in `cmd_run`**

In `packages/awp-core/src/awp/cli.py`, inside `cmd_run`, **after** the `validate_task_key_for_run` block added in Task 1, add:

```python
    if args.task is not None:
        from .experiment.cli_handlers import run_task_aware

        return run_task_aware(args)
```

Everything below this in `cmd_run` stays unchanged — it handles the bare `awp run` path.

- [ ] **Step 4: Implement `run_task_aware`**

In `packages/awp-core/src/awp/experiment/cli_handlers.py`, add:

```python
def run_task_aware(args) -> int:
    """Handle `awp run --task <exp>:<task>` by delegating to AgentWorkflow."""
    from awp.experiment.paths import task_dir as _task_dir

    exp_id, tid = args.task.split(":", 1)
    td = _task_dir(exp_id, tid)
    output_dir = td / "seed"
    output_dir.mkdir(parents=True, exist_ok=True)

    if os.environ.get("AWP_RUN_TASK_DRY_RUN") == "1":
        print(json.dumps({"output_dir": str(output_dir), "task": args.task}))
        return 0

    # Lazy import — AgentWorkflow lives in awp-runtime
    try:
        from awp.data.workflow import AgentWorkflow
    except ImportError as exc:  # pragma: no cover - deployment concern
        print(
            f"awp-runtime is required for task-aware runs: {exc}",
            file=sys.stderr,
        )
        return 2

    # Read the task prompt from task.json (seed: user_prompt; continuation: user_feedback)
    manifest = read_task_manifest(exp_id, tid)
    task_text = manifest.user_prompt  # continuation is blocked in Task 1

    # Build model kwargs from args (only pass non-None)
    model = args.manager_model or args.model or "openai/gpt-5-mini"
    worker_model = args.worker_model or "deepseek/deepseek-chat-v3.1"

    # Read workflow inputs if a file was provided
    workflow_path = Path(args.path)
    inputs = {}
    if workflow_path.is_file():
        inputs["workflow_path"] = str(workflow_path)
    elif workflow_path.is_dir():
        inputs["workflow_dir"] = str(workflow_path)

    wf = AgentWorkflow(
        inputs=inputs,
        task=task_text,
        model=model,
        worker_model=worker_model,
        output_dir=str(output_dir),
        tags=["task", exp_id, tid],
    )
    result = wf.run()
    # The run's files are under output_dir/output/<run_id>/; the post-run
    # hook (Task 5) reads run_completion.json from there and does DB + BEST.
    from .cli_handlers import _post_run_finalise  # self-import defensive
    return _post_run_finalise(
        output_dir=output_dir,
        run_id=result.run_id if hasattr(result, "run_id") else None,
        exp_id=exp_id,
        task_key=args.task,
        task_text=task_text,
        model=model,
    )
```

Also ensure these imports exist at the top of `cli_handlers.py`:

```python
import os  # may already be present
```

**Note:** `result.run_id` — the return shape of `AgentWorkflow.run()` may be a dict, a dataclass, or something else. Verify at implementation time by reading `packages/awp-runtime/src/awp/data/workflow.py`. If the run_id isn't returned directly, read the latest subdir under `<output_dir>/output/` to recover it. Fall back gracefully.

- [ ] **Step 5: Run tests — expect the dry-run positive path to pass**

```
pytest packages/awp-core/tests/cli/test_run_task_cli.py -v
```

Expected: 4 passed (3 from Task 1 + 1 new dry-run test).

The full positive path with a real `AgentWorkflow.run()` is not exercised here — Task 5 covers that with a stubbed hook, and Task 9 (E2E) covers it with a real run.

- [ ] **Step 6: Commit**

```bash
git add packages/awp-core/src/awp/cli.py packages/awp-core/src/awp/experiment/cli_handlers.py packages/awp-core/tests/cli/test_run_task_cli.py
git commit -m "feat(cli): awp run --task routes through AgentWorkflow with seed output dir"
```

---

## Task 5: Post-run hook — upsert DB row + call BEST finaliser

**Files:**
- Modify: `packages/awp-core/src/awp/experiment/cli_handlers.py`
- Test:   `packages/awp-core/tests/cli/test_run_task_cli.py` (extend)

**Background.** After `AgentWorkflow.run()` returns, `_post_run_finalise` must:
1. Locate the run_dir (`<output_dir>/output/<run_id>/`).
2. Read `run_completion.json` and extract status.
3. Compute loss via `compute_run_loss`.
4. Upsert the row in `awp_ui.db` via `StoreService.upsert_run_for_task`.
5. Call `compute_and_update_best` to update `<task>/BEST/`.
6. If BEST was updated, mirror to DB via `set_task_best`.

- [ ] **Step 1: Write a test that calls the hook directly with a pre-built run directory**

Append to `packages/awp-core/tests/cli/test_run_task_cli.py`:

```python
def test_post_run_finalise_updates_db_and_best(env: dict, tmp_path: Path) -> None:
    """End-to-end of the post-run hook using a pre-built fake run_dir."""
    import os
    from pathlib import Path
    # Set env vars in this process too, so the handler module sees them
    os.environ["AWP_EXPERIMENTS_ROOT"] = env["AWP_EXPERIMENTS_ROOT"]
    os.environ["AWP_UI_DB_PATH"] = env["AWP_UI_DB_PATH"]

    # Setup: experiment + task via CLI
    r = _run_cli(["experiment", "create", "E"], env=env)
    exp_id = json.loads(r.stdout)["experiment_id"]
    r = _run_cli(["task", "create", exp_id, "seed"], env=env)
    task_id = json.loads(r.stdout)["task_id"]

    # Build a fake finished run_dir
    output_dir = tmp_path / exp_id / "tasks" / task_id / "seed"
    run_id = "2026-04-20_15-00-00_abc12345"
    run_dir = output_dir / "output" / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "FINAL").mkdir()
    (run_dir / "FINAL" / "paper.md").write_text("fake deliverable")
    (run_dir / "events.jsonl").write_text("")
    (run_dir / "metrics.jsonl").write_text("")
    (run_dir / "run_completion.json").write_text(json.dumps({
        "run_id": run_id,
        "status": "complete",
        "task": "t",
        "final_budget": {"loops": {"used": 1, "cap": 10}, "tokens": {"used": 100, "cap": 1000}},
        "evaluation": {"score": 0.9},
        "critique": {"defects": []},
        "gate_rejections": 0,
    }))

    # Call the hook directly
    import importlib
    cli_handlers = importlib.import_module("awp.experiment.cli_handlers")
    rc = cli_handlers._post_run_finalise(
        output_dir=output_dir,
        run_id=run_id,
        exp_id=exp_id,
        task_key=f"{exp_id}:{task_id}",
        task_text="t",
        model="m",
    )
    assert rc == 0

    # Verify BEST was written
    best_manifest = output_dir.parent / "BEST" / "manifest.json"
    assert best_manifest.exists()
    m = json.loads(best_manifest.read_text())
    assert m["winner_run_id"] == run_id
    # Verify BEST contains the deliverable
    assert (output_dir.parent / "BEST" / "paper.md").exists()

    # Verify the DB row
    import sqlite3
    con = sqlite3.connect(env["AWP_UI_DB_PATH"])
    con.row_factory = sqlite3.Row
    row = con.execute(
        "SELECT experiment_id, task_id, run_role, loss, status FROM runs WHERE id = ?",
        (run_id,),
    ).fetchone()
    con.close()
    assert row is not None
    assert row["experiment_id"] == exp_id
    assert row["task_id"] == f"{exp_id}:{task_id}"
    assert row["run_role"] == "seed"
    assert row["status"] == "complete"
    assert row["loss"] is not None
```

- [ ] **Step 2: Run — expect failure**

```
pytest packages/awp-core/tests/cli/test_run_task_cli.py::test_post_run_finalise_updates_db_and_best -v
```

- [ ] **Step 3: Implement `_post_run_finalise`**

In `packages/awp-core/src/awp/experiment/cli_handlers.py`, add:

```python
def _post_run_finalise(
    output_dir: Path,
    run_id: str | None,
    exp_id: str,
    task_key: str,
    task_text: str,
    model: str,
) -> int:
    """Read the freshly-finished run, register it in awp_ui.db, and update BEST/."""
    # Locate run_dir if run_id not known
    runs_root = output_dir / "output"
    if run_id is None:
        candidates = sorted(
            (p for p in runs_root.iterdir() if p.is_dir()),
            key=lambda p: p.stat().st_mtime,
        )
        if not candidates:
            print(f"no run output found under {runs_root}", file=sys.stderr)
            return 1
        run_dir = candidates[-1]
        run_id = run_dir.name
    else:
        run_dir = runs_root / run_id

    completion_path = run_dir / "run_completion.json"
    if not completion_path.exists():
        print(f"missing run_completion.json at {completion_path}", file=sys.stderr)
        return 1
    completion = json.loads(completion_path.read_text())
    status = completion.get("status", "unknown")

    # Compute loss (skip for non-terminal)
    loss: float | None = None
    if status in ("complete", "partial"):
        try:
            from awp.outer_loop.loss import compute_run_loss
            loss = compute_run_loss(run_dir).total
        except Exception as exc:  # pragma: no cover - defensive
            print(f"compute_run_loss failed: {exc}", file=sys.stderr)

    # Upsert DB row
    async def _upsert(store):
        await store.upsert_run_for_task(
            run_id=run_id,
            experiment_id=exp_id,
            task_id=task_key,
            run_role="seed",
            loss=loss,
            status=status,
            task=task_text,
            model=model,
        )

    asyncio.run(_with_store(_upsert))

    # Invoke BEST finaliser
    try:
        from awp.experiment.best_finaliser import compute_and_update_best
    except ImportError as exc:  # pragma: no cover
        print(f"awp-runtime required: {exc}", file=sys.stderr)
        return 1

    task_dir = output_dir.parent  # <exp>/tasks/<task>/
    result = compute_and_update_best(task_dir=task_dir, new_run_dir=run_dir)

    # Mirror BEST to DB if it changed
    if result.updated:
        async def _set_best(store):
            await store.set_task_best(
                task_id_key=task_key,
                run_id=run_id,
                reason=result.reason,
            )
        asyncio.run(_with_store(_set_best))

    print(
        json.dumps({
            "run_id": run_id,
            "status": status,
            "loss": loss,
            "best_updated": result.updated,
            "best_reason": result.reason,
        }, indent=2)
    )
    return 0
```

Imports at the top of `cli_handlers.py` may need extending — verify `Path`, `asyncio`, `json`, `sys`, `os` are all there (Plan 1 already covers most of these).

- [ ] **Step 4: Run tests**

```
pytest packages/awp-core/tests/cli/test_run_task_cli.py -v
```

Expected: all 5 tests pass.

- [ ] **Step 5: Full regression**

```
pytest packages/awp-core/tests/ packages/awp-runtime/tests/ -k "not e2e" 2>&1 | tail -5
```

Expected: green except the known pre-existing outer-loop test.

- [ ] **Step 6: Commit**

```bash
git add packages/awp-core/src/awp/experiment/cli_handlers.py packages/awp-core/tests/cli/test_run_task_cli.py
git commit -m "feat(cli): post-run hook — upsert runs row + update BEST via finaliser"
```

---

## Task 6: CLI — `awp task set-best --run <id>` / `--auto`

**Files:**
- Modify: `packages/awp-core/src/awp/cli.py`
- Modify: `packages/awp-core/src/awp/experiment/cli_handlers.py`
- Test:   `packages/awp-core/tests/cli/test_task_set_best_cli.py`

**Background.** User override: forces a specific run to be the task's BEST (reason="user_override"). Subsequent auto-updates are blocked unless `--auto` clears the override.

- [ ] **Step 1: Write tests**

Create `packages/awp-core/tests/cli/test_task_set_best_cli.py`:

```python
"""CLI tests for `awp task set-best --run <id>` and `--auto`."""

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


def _mk_run_in_task(task_dir: Path, run_id: str, score: float) -> Path:
    output_dir = task_dir / "seed" / "output" / run_id
    output_dir.mkdir(parents=True)
    (output_dir / "FINAL").mkdir()
    (output_dir / "FINAL" / "art.md").write_text(f"run={run_id}")
    (output_dir / "events.jsonl").write_text("")
    (output_dir / "metrics.jsonl").write_text("")
    (output_dir / "run_completion.json").write_text(json.dumps({
        "run_id": run_id,
        "status": "complete",
        "task": "t",
        "final_budget": {"loops": {"used": 1, "cap": 10}, "tokens": {"used": 1, "cap": 100}},
        "evaluation": {"score": score},
        "critique": {"defects": []},
        "gate_rejections": 0,
    }))
    return output_dir


def _setup(env: dict, tmp_path: Path) -> tuple[str, str, Path]:
    r = _run_cli(["experiment", "create", "E"], env=env)
    exp_id = json.loads(r.stdout)["experiment_id"]
    r = _run_cli(["task", "create", exp_id, "seed"], env=env)
    tid = json.loads(r.stdout)["task_id"]
    return exp_id, tid, tmp_path / exp_id / "tasks" / tid


def test_set_best_with_run_sets_user_override(env: dict, tmp_path: Path) -> None:
    exp_id, tid, task_dir = _setup(env, tmp_path)
    # Two runs, run2 is objectively better
    _mk_run_in_task(task_dir, "run_low", score=0.1)
    _mk_run_in_task(task_dir, "run_high", score=0.99)

    # User picks run_low
    r = _run_cli(
        ["task", "set-best", f"{exp_id}:{tid}", "--run", "run_low"],
        env=env,
    )
    assert r.returncode == 0, r.stderr

    manifest = json.loads((task_dir / "BEST" / "manifest.json").read_text())
    assert manifest["winner_run_id"] == "run_low"
    assert manifest["reason"] == "user_override"


def test_set_best_auto_clears_override(env: dict, tmp_path: Path) -> None:
    exp_id, tid, task_dir = _setup(env, tmp_path)
    _mk_run_in_task(task_dir, "run_low", score=0.1)
    _mk_run_in_task(task_dir, "run_high", score=0.99)

    # Pin low first
    _run_cli(["task", "set-best", f"{exp_id}:{tid}", "--run", "run_low"], env=env)

    # Then --auto: should select the lowest-loss eligible run (run_high)
    r = _run_cli(["task", "set-best", f"{exp_id}:{tid}", "--auto"], env=env)
    assert r.returncode == 0, r.stderr
    manifest = json.loads((task_dir / "BEST" / "manifest.json").read_text())
    assert manifest["winner_run_id"] == "run_high"
    assert manifest["reason"] == "auto_loss"


def test_set_best_requires_run_or_auto(env: dict, tmp_path: Path) -> None:
    exp_id, tid, _ = _setup(env, tmp_path)
    r = _run_cli(["task", "set-best", f"{exp_id}:{tid}"], env=env)
    assert r.returncode != 0


def test_set_best_rejects_unknown_run(env: dict, tmp_path: Path) -> None:
    exp_id, tid, task_dir = _setup(env, tmp_path)
    _mk_run_in_task(task_dir, "run1", score=0.5)
    r = _run_cli(
        ["task", "set-best", f"{exp_id}:{tid}", "--run", "does-not-exist"],
        env=env,
    )
    assert r.returncode != 0
    assert "not found" in (r.stderr + r.stdout).lower()
```

- [ ] **Step 2: Run — expect failure**

```
pytest packages/awp-core/tests/cli/test_task_set_best_cli.py -v
```

Expected: all four fail (no `set-best` subparser).

- [ ] **Step 3: Register the `set-best` subparser**

In `packages/awp-core/src/awp/cli.py`, find the `task_sub` block added in Plan 1 Task 10. Add just before the `return parser.parse_args(argv)` line (inside the same block):

```python
    p_task_set_best = task_sub.add_parser("set-best", help="Pick the best run of a task")
    p_task_set_best.add_argument("task_key", help="<experiment_id>:<task_id>")
    grp = p_task_set_best.add_mutually_exclusive_group(required=True)
    grp.add_argument("--run", dest="run_id", help="pin this run as BEST (user override)")
    grp.add_argument("--auto", action="store_true", help="clear override, reselect automatically")
```

- [ ] **Step 4: Extend `handle_task_command`**

In `packages/awp-core/src/awp/experiment/cli_handlers.py`, update `handle_task_command` to dispatch the new subcommand:

```python
    if cmd == "set-best":
        return _task_set_best(args)
```

And add the handler:

```python
def _task_set_best(args) -> int:
    exp_id, tid = _split_key(args.task_key)
    task_dir_ = task_dir(exp_id, tid)
    if not task_dir_.exists():
        print(f"task not found: {args.task_key}", file=sys.stderr)
        return 2

    try:
        from awp.experiment.best_finaliser import compute_and_update_best
    except ImportError as exc:
        print(f"awp-runtime required: {exc}", file=sys.stderr)
        return 2

    runs_root = task_dir_ / "seed" / "output"

    if args.run_id:
        # User override
        new_run_dir = runs_root / args.run_id
        if not new_run_dir.exists():
            print(f"run not found: {args.run_id}", file=sys.stderr)
            return 2
        result = compute_and_update_best(
            task_dir=task_dir_, new_run_dir=new_run_dir, force_override=True,
        )
        if not result.updated:
            print(
                f"BEST not updated: skip_reason={result.skip_reason}",
                file=sys.stderr,
            )
            return 1
        # Mirror to DB
        async def _mirror(store):
            await store.set_task_best(
                task_id_key=args.task_key, run_id=args.run_id, reason="user_override",
            )
        asyncio.run(_with_store(_mirror))
        print(json.dumps({"best_run_id": args.run_id, "reason": "user_override"}))
        return 0

    # --auto: clear any override, pick lowest-loss run
    # Step 1: remove existing manifest so finaliser treats all runs as fresh
    manifest_path = task_dir_ / "BEST" / "manifest.json"
    if manifest_path.exists():
        manifest_path.unlink()
    # Step 2: iterate all runs, compute loss, pick the lowest via finaliser
    if not runs_root.exists():
        print(f"no runs under {runs_root}", file=sys.stderr)
        return 2
    best_result = None
    best_run_id = None
    for run_dir in sorted(runs_root.iterdir()):
        if not run_dir.is_dir():
            continue
        result = compute_and_update_best(task_dir=task_dir_, new_run_dir=run_dir)
        if result.updated:
            best_result = result
            best_run_id = run_dir.name
    if best_run_id is None:
        print("no eligible terminal runs found", file=sys.stderr)
        return 1
    # Mirror to DB
    async def _mirror2(store):
        await store.set_task_best(
            task_id_key=args.task_key, run_id=best_run_id, reason="auto_loss",
        )
    asyncio.run(_with_store(_mirror2))
    print(json.dumps({"best_run_id": best_run_id, "reason": "auto_loss"}))
    return 0
```

- [ ] **Step 5: Run tests**

```
pytest packages/awp-core/tests/cli/test_task_set_best_cli.py -v
```

Expected: 4 passed.

- [ ] **Step 6: Commit**

```bash
git add packages/awp-core/src/awp/cli.py packages/awp-core/src/awp/experiment/cli_handlers.py packages/awp-core/tests/cli/test_task_set_best_cli.py
git commit -m "feat(cli): awp task set-best --run / --auto"
```

---

## Task 7: Docs — CLAUDE.md, spec

**Files:**
- Modify: `CLAUDE.md`
- Modify: `spec/versions/1.0/validation-rules.md` (refine R37 note about run-time enforcement)
- Modify: `docs/superpowers/specs/2026-04-20-experiment-task-hierarchy-design.md` — acknowledge the `output/` layer in §5

- [ ] **Step 1: Update CLAUDE.md Development Commands**

In `CLAUDE.md`, extend the Development Commands block (added in Plan 1 Task 12) with:

```
# Task-aware run + BEST override (Plan 2)
awp run <workflow_path> --task <experiment_id>:<task_id>  # task-aware seed run
                                                          # (continuation rejected; see Plan 3)
awp task set-best <experiment_id>:<task_id> --run <run_id>   # user override
awp task set-best <experiment_id>:<task_id> --auto           # clear override, auto-pick
```

- [ ] **Step 2: Annotate the spec's §5 physical layout**

In `docs/superpowers/specs/2026-04-20-experiment-task-hierarchy-design.md`, find the `seed/` block in §5 and update it to reflect the actual runtime structure:

```
    │   ├── seed/
    │   │   └── output/
    │   │       └── <run_id>/
    │   │           ├── run_completion.json
    │   │           ├── FINAL/
    │   │           ├── events.jsonl
    │   │           └── metrics.jsonl
```

Add a one-line footnote: "The `output/` subdirectory reflects `AgentWorkflow`'s native layout; it is not a user-visible concept but kept to match the runtime's canonical run-dir shape."

- [ ] **Step 3: Run drift gates**

```
python scripts/check_docs_drift.py
python scripts/check_sync_coverage.py
```

Both must exit 0.

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md docs/superpowers/specs/2026-04-20-experiment-task-hierarchy-design.md
git commit -m "docs: document awp run --task + awp task set-best (Plan 2)"
```

---

## Task 8: Mirror sync + full regression

**Files:**
- Sync: `reference/python/src/awp/experiment/` and related

- [ ] **Step 1: Regression**

```
pytest packages/awp-core/tests/ packages/awp-runtime/tests/ -k "not e2e" 2>&1 | tail -5
```

Expected: all green except the pre-existing `test_manager_prompt_uses_default_worker_pitfalls`.

- [ ] **Step 2: Sync mirror**

Plan 2 added files only under `packages/awp-runtime/src/awp/experiment/` (new package on the runtime side).

```
rsync -a packages/awp-runtime/src/awp/ reference/python/src/awp/
rsync -a packages/awp-core/src/awp/ reference/python/src/awp/
rsync -a packages/awp-ui/server/ reference/python/src/server/
```

No `--delete` (nothing was removed).

- [ ] **Step 3: Verify all three drift gates**

```
python scripts/check_mirror_drift.py && echo MIRROR_OK
python scripts/check_docs_drift.py && echo DOCS_OK
python scripts/check_sync_coverage.py && echo SYNC_OK
```

All three must emit the OK line.

- [ ] **Step 4: Commit**

```bash
git add reference/python/src/
git commit -m "chore(mirror): sync reference/python/src with Plan 2 (runtime integration)"
```

---

## Self-review checklist

Before declaring Plan 2 complete:

- `awp run --task` for a seed task creates: `<exp>/tasks/<task>/seed/output/<run_id>/`, a `runs` row with the full hierarchy metadata, and a `<task>/BEST/manifest.json` pointing at the run (if the run terminated).
- `awp run --task` for a continuation task exits non-zero with a clear "Plan 3" pointer.
- `awp task set-best --run <id>` freezes BEST with `reason="user_override"`; subsequent auto runs skip.
- `awp task set-best --auto` clears the override and reselects the lowest-loss eligible run.
- `_post_run_finalise` is called once per run, is idempotent on the DB side (upsert), and does not crash when `run_completion.json` is absent (returns error code).
- `_rewrite_best` preserves / recreates `<task>/BEST/` atomically (old files cleared before new hardlinks).
- `compute_run_loss` field names match reality (verified against `packages/awp-runtime/src/awp/outer_loop/loss.py` at implementation time).
- Pre-existing outer-loop test failure remains unchanged (not in scope).

---

## Handoff to Plan 3

After Plan 2, the repo supports:
- Creating experiments + seed tasks (Plan 1)
- Running seed tasks through `awp run --task`, landing artifacts in the task hierarchy, upserting the DB, and auto-updating BEST (Plan 2)
- User-overriding BEST (Plan 2)

Plan 3 picks up:
- Continuation loader (`packages/awp-runtime/src/awp/continuation/`) — loads prior `BEST/` into Manager prompt prefix.
- Lifts the Task 1 guard: `awp run --task <cont>` actually runs (with continuation prefix injected).
- R37 enforcement at runtime side (already enforced at CLI + Pydantic).
- E2E: 2-task experiment, continuation task must build on Task 1's deliverable without re-analysing.
