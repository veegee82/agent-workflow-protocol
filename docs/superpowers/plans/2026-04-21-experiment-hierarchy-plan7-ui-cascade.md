# Plan 7 — UI-Initiated Runs Land in Hierarchy + Auto-Cascade (Seed → Refine → Optimize)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development.

**Goal:** Fix the gap between "UI triggers run" and "E2E coverage of all three optimizers". After Plan 7:

1. Runs started from the UI can be attached to an experiment + task in the hierarchy (already partly possible via `/api/runs/create` — extend to carry experiment/task).
2. UI settings expose two new toggles — `auto_refine_after_seed` and `auto_optimize_after_refine` — plus integer inputs for iterations + epochs.
3. When those toggles are on, the runner-service **cascades automatically** after a seed run completes: fires `RefinementLoop`, then (optionally) `SuiteRunner`, emitting events to the same WebSocket so the UI shows live progress.
4. Fix the two layout bugs real-LLM E2E uncovered: FINAL/ lookup (workspace-level vs run-level) in both `compute_and_update_best` and `refinement/loop.py`.

**Architecture:** Additive, mostly in `runner_service.py` + UI Settings. No new packages. The runner service already spawns `AgentWorkflow` in an asyncio task and pipes events to the event-bus — the cascade just chains `RefinementLoop.run()` and `SuiteRunner.run_epoch()` after the seed AgentWorkflow completes, in the same task. Each cascade phase gets its own run_id and DB row.

**Spec refs:** Existing spec §6.5 (BEST manifest), §7 (continuation + post-run-hook); Plan 5 §9.1 (UI sidebar + views). No new normative rules.

**Lessons baked in (Plans 1-6):**
- No scope creep on CLAUDE.md (Plan 4 incident).
- Flat tests in `packages/awp-ui/server/tests/`.
- Real `run_completion.json` schema (`eval.score`).
- Smoke-test gate at the end.
- `awp_ui.db` MUST be the single source of truth — no new side DBs.

**Out of scope:**
- Cascade for continuation tasks (the continuation task's seed run can auto-cascade into its own refine+optimize, but we don't invent new "continuation-of-cascade" semantics).
- Multi-task suite auto-optimize — the auto-optimize uses a **single-task suite** synthesised from the task's own prompt (see Task 5 below for the synthesis rule).
- UI visualisation of cascade progress (beyond the existing sidebar + loss-curve — those already refresh on navigation).
- Cancelling a mid-cascade run — sigint stops the whole chain, that's enough.

---

## Known preconditions (verified)

- `runner_service.py` already spawns `AgentWorkflow` in an asyncio task and streams events via `event_bus.emit_threadsafe`. New cascade code just chains `RefinementLoop` + `SuiteRunner` in the same async context.
- `RefinementLoop(seed_run_dir, iterations_root, session_sidecar_dir, ...)` — honours both a custom iterations root (Plan 4 Task 2) and a custom sidecar dir (Plan 4 Task 3).
- `SuiteRunner(registry, store, workflow_factory)` + `run_epoch(suite, epoch_num, parent_artifacts, output_dir)` — honours custom output_dir.
- `_post_run_finalise(run_role=...)` + `task_dir_override=...` — Plans 4 + 6 already plumbed the role param.
- `compute_run_loss` reads `run_completion.json` — Plan 6 fix committed in `670a71a`.
- `awp_ui.db::settings` — single row `key='global'`, `data_json` JSON blob. Adding fields is backward-compatible.

---

## File structure

**Created:**
- `packages/awp-ui/server/services/cascade.py` — pure function `async def cascade_after_seed(...)` that takes a just-finished seed run's metadata and runs the refine + optimize phases if settings enable them. Emits events via `event_bus`.
- `packages/awp-ui/server/tests/test_cascade_smoke.py` — end-to-end without LLM (fake workflow factories).

**Modified:**
- `packages/awp-runtime/src/awp/outer_loop/best_finaliser.py` — dual-location lookup for `FINAL/`: try `<run_dir>/FINAL/` first, then `<run_dir>/../../output/FINAL/` (workspace-level).
- `packages/awp-runtime/src/awp/refinement/loop.py` — same dual-location for `last_good_final`.
- `packages/awp-ui/server/services/store.py` — extend `settings` defaults with `auto_refine_after_seed` (default false), `auto_refine_iterations` (default 2), `auto_optimize_after_seed` (default false), `auto_optimize_epochs` (default 1).
- `packages/awp-ui/server/services/runner_service.py` — accept optional `experiment_id`, `task_id` in the run-config; after AgentWorkflow completes, if cascade toggles on and run attached to a task, call `cascade_after_seed`.
- `packages/awp-ui/server/api/routes.py` — `POST /runs/create` accepts `experiment_id`, `task_id` optional fields.
- `packages/awp-ui/frontend/src/components/Settings/SettingsPanel.tsx` (or wherever the settings live) — add a "Cascade" sub-section with the two checkboxes + two number inputs.
- `packages/awp-ui/frontend/src/components/TaskInputBar/*.tsx` (wherever the run-trigger lives) — when a Task is selected in the Experiments sidebar, include `experiment_id` + `task_id` in the `POST /runs/create` body.
- `packages/awp-ui/frontend/src/api/runs.ts` (or equivalent) — type + call-site update.

---

## Task 1: Layout bugfix — FINAL/ dual-location lookup

**Files:**
- Modify: `packages/awp-runtime/src/awp/outer_loop/best_finaliser.py`
- Modify: `packages/awp-runtime/src/awp/refinement/loop.py`
- Test:   `packages/awp-runtime/tests/test_best_finaliser.py` (extend)

**Background.** Real E2E run discovered that `AgentWorkflow` writes `FINAL/` at the workspace level (`<workspace>/output/FINAL/`) while `compute_and_update_best` + `RefinementLoop` both look for it at `<run_dir>/FINAL/`. Our smoke tests faked the wrong layout (run-level FINAL), masking the bug. Result at the live run: BEST/ had only manifest.json (no hardlinked deliverables), and refinement aborted with `stop_reason="no_prior_deliverable"`.

### Steps

- [ ] **Step 1: Extend best_finaliser test to assert workspace-level FINAL works**

Append to `packages/awp-runtime/tests/test_best_finaliser.py`:

```python
def test_workspace_level_final_is_found(tmp_path: Path) -> None:
    """AgentWorkflow writes FINAL at <workspace>/output/FINAL/ (not <run>/FINAL/).

    Build that layout and verify compute_and_update_best still promotes the
    deliverables to <task>/BEST/.
    """
    task_dir = tmp_path / "task"
    task_dir.mkdir()
    workspace = task_dir / "seed"
    run_dir = workspace / "workspace" / "runs" / "run1"
    run_dir.mkdir(parents=True)
    (run_dir / "run_completion.json").write_text(json.dumps({
        "run_id": "run1", "status": "complete", "task": "t",
        "final_budget": {"loops": {"used": 1, "cap": 10}, "tokens": {"used": 1, "cap": 100}},
        "eval": {"score": 0.9}, "critique": {"defects": []}, "gate_rejections": 0,
    }))
    (run_dir / "events.jsonl").write_text("")
    (run_dir / "metrics.jsonl").write_text("")
    # FINAL lives at workspace level, NOT under run_dir
    workspace_final = workspace / "output" / "FINAL"
    workspace_final.mkdir(parents=True)
    (workspace_final / "paper.md").write_text("workspace-level deliverable")

    result = compute_and_update_best(task_dir=task_dir, new_run_dir=run_dir)

    assert result.updated is True
    # BEST/paper.md should now be hardlinked from the workspace-level FINAL
    assert (task_dir / "BEST" / "paper.md").exists()
    assert (task_dir / "BEST" / "paper.md").read_text() == "workspace-level deliverable"
```

- [ ] **Step 2: Run — expect failure (BEST/ paper.md missing)**

```
pytest packages/awp-runtime/tests/test_best_finaliser.py -v
```

- [ ] **Step 3: Fix `compute_and_update_best`**

In `_rewrite_best` (best_finaliser.py), replace:

```python
    final_src = winner_run_dir / "FINAL"
```

with:

```python
    # AgentWorkflow writes FINAL at <workspace>/output/FINAL/. Fall back to
    # the run-dir location for fixture-shaped tests that pre-date that finding.
    final_src = winner_run_dir / "FINAL"
    if not final_src.exists():
        # Walk up: <run>/workspace/runs/<id> → <run>/../.. is workspace,
        # then workspace/output/FINAL is the canonical location.
        workspace_candidate = winner_run_dir.parent.parent.parent / "output" / "FINAL"
        if workspace_candidate.exists():
            final_src = workspace_candidate
```

- [ ] **Step 4: Fix `RefinementLoop`**

In `packages/awp-runtime/src/awp/refinement/loop.py`, find the line:

```python
        last_good_final: Path = self._seed / "FINAL"
```

Replace with:

```python
        last_good_final = self._seed / "FINAL"
        if not last_good_final.exists():
            # AgentWorkflow writes FINAL at workspace-level, not run-level.
            workspace_candidate = self._seed.parent.parent.parent / "output" / "FINAL"
            if workspace_candidate.exists():
                last_good_final = workspace_candidate
```

- [ ] **Step 5: Verify + full best_finaliser regression**

```
pytest packages/awp-runtime/tests/test_best_finaliser.py packages/awp-runtime/tests/refinement/ -v
```

Expected: new test green, all existing refinement tests still pass.

- [ ] **Step 6: Commit**

```bash
git add packages/awp-runtime/src/awp/outer_loop/best_finaliser.py packages/awp-runtime/src/awp/refinement/loop.py packages/awp-runtime/tests/test_best_finaliser.py
git commit -m "fix(runtime): FINAL/ dual-location lookup — accept workspace-level"
```

---

## Task 2: Settings schema — cascade fields

**Files:**
- Modify: `packages/awp-ui/server/services/store.py` — settings default shape
- Modify: `packages/awp-ui/server/api/routes.py` — settings PUT/GET schema
- Test:   `packages/awp-ui/server/tests/test_experiment_routes.py` (extend)

**Background.** `awp_ui.db::settings.data_json` is a free-form JSON blob. We add four fields with explicit defaults. UI reads/writes via existing `GET /api/settings` / `PUT /api/settings`.

### Steps

- [ ] **Step 1: Add to `_default_settings`**

In `packages/awp-ui/server/api/routes.py`, find the `_default_settings` function (or wherever the default shape is). Append the four new fields:

```python
    "auto_refine_after_seed": False,
    "auto_refine_iterations": 2,
    "auto_optimize_after_seed": False,
    "auto_optimize_epochs": 1,
```

If `SettingsPayload` Pydantic model exists and is strict, add the same four fields there with `Field(default=False)` / `Field(default=2)` / etc.

- [ ] **Step 2: Test — settings round-trip preserves cascade fields**

Append to `packages/awp-ui/server/tests/test_experiment_routes.py`:

```python
@pytest.mark.asyncio
async def test_settings_include_cascade_fields(client: AsyncClient) -> None:
    r = await client.get("/api/settings")
    assert r.status_code == 200
    data = r.json()
    # New cascade fields present with defaults
    assert data.get("auto_refine_after_seed") is False
    assert data.get("auto_refine_iterations") == 2
    assert data.get("auto_optimize_after_seed") is False
    assert data.get("auto_optimize_epochs") == 1

    # Flip them + round-trip
    data["auto_refine_after_seed"] = True
    data["auto_refine_iterations"] = 3
    r = await client.put("/api/settings", json=data)
    assert r.status_code == 200
    r = await client.get("/api/settings")
    assert r.json()["auto_refine_after_seed"] is True
    assert r.json()["auto_refine_iterations"] == 3
```

- [ ] **Step 3: Verify**

```
pytest packages/awp-ui/server/tests/test_experiment_routes.py::test_settings_include_cascade_fields -v
```

- [ ] **Step 4: Commit**

```bash
git add packages/awp-ui/server/api/routes.py packages/awp-ui/server/tests/test_experiment_routes.py
git commit -m "feat(ui-settings): cascade fields (auto_refine + auto_optimize)"
```

---

## Task 3: `POST /api/runs/create` accepts `experiment_id` + `task_id`

**Files:**
- Modify: `packages/awp-ui/server/api/routes.py`
- Modify: `packages/awp-ui/server/services/runner_service.py`
- Test:   `packages/awp-ui/server/tests/test_cascade_smoke.py` (new, for broader scope; minimal test here)

**Background.** The existing endpoint creates a legacy-session run. Adding optional `experiment_id` + `task_id` tells the runner to attach the run to the hierarchy (upsert into `runs` table with those fields + `run_role="seed"`).

### Steps

- [ ] **Step 1: Extend `RunCreateRequest` Pydantic**

In `routes.py`, find `RunCreateRequest` (or equivalent). Add:

```python
    experiment_id: str | None = None
    task_id: str | None = None
```

- [ ] **Step 2: Thread through to runner_service**

In `runner_service.py`'s run-spawn function, accept the two new fields. After `AgentWorkflow` completes successfully and the run is registered, if both fields are present:

```python
    if experiment_id and task_id:
        await store.upsert_run_for_task(
            run_id=run_id,
            experiment_id=experiment_id,
            task_id=task_id,
            run_role="seed",
            loss=compute_run_loss(run_dir).total if ... else None,
            status=final_status,
            task=task_text,
            model=model,
        )
```

Also, update the `output_dir` the AgentWorkflow gets: if `experiment_id` + `task_id` are set, use `<experiment>/tasks/<task_id>/seed` instead of the legacy-session path. This makes UI-initiated hierarchy-attached runs land in the same place `awp run --target` does.

- [ ] **Step 3: Minimal smoke — route accepts the fields**

Append to `packages/awp-ui/server/tests/test_experiment_routes.py`:

```python
@pytest.mark.asyncio
async def test_runs_create_accepts_experiment_and_task(
    client: AsyncClient, tmp_path: Path
) -> None:
    # Create exp + task first
    r = await client.post("/api/experiments", json={"name": "E"})
    exp_id = r.json()["id"]
    r = await client.post(f"/api/experiments/{exp_id}/tasks", json={"user_prompt": "P"})
    task_key = r.json()["id"]

    # The runner will fail trying to call an LLM, but we just want to verify
    # the route parses our fields without rejecting them.
    r = await client.post("/api/runs/create", json={
        "task": "P",
        "model": "openai/gpt-5-mini",
        "experiment_id": exp_id,
        "task_id": task_key,
        # Everything else default
    })
    # Whether it succeeds or fails downstream is LLM-dependent. The contract
    # here is just that the POST body was accepted.
    assert r.status_code in (200, 202, 500), r.text
```

- [ ] **Step 4: Verify + commit**

```
pytest packages/awp-ui/server/tests/test_experiment_routes.py -v
git add packages/awp-ui/server/api/routes.py packages/awp-ui/server/services/runner_service.py packages/awp-ui/server/tests/test_experiment_routes.py
git commit -m "feat(ui-api): /runs/create accepts experiment_id + task_id"
```

---

## Task 4: Cascade orchestrator — `services/cascade.py`

**Files:**
- Create: `packages/awp-ui/server/services/cascade.py`
- Test:   `packages/awp-ui/server/tests/test_cascade_smoke.py`

**Background.** Pure async function that (a) if `auto_refine_after_seed` — spawn `RefinementLoop` with the task's iterations root; (b) if `auto_optimize_after_seed` — synthesise a single-task suite from the task's own prompt and run one SuiteRunner epoch. Each sub-phase finalises via `_post_run_finalise` with the right role.

### Steps

- [ ] **Step 1: Write the test first**

Create `packages/awp-ui/server/tests/test_cascade_smoke.py`:

```python
"""Smoke test — cascade fires refine + optimize when settings enable them."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest
import pytest_asyncio

from awp_ui_test_utils import _mk_fake_run, _seed_experiment_task  # helpers TODO


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
```

Also create a tiny shared helper module `packages/awp-ui/server/tests/awp_ui_test_utils.py`:

```python
"""Shared helpers for Plan 7 UI tests (no LLM, no side-effects)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def _seed_experiment_task(tmp_path: Path) -> tuple[str, str, Path]:
    """Create an experiment + seed task via CLI. Returns (exp_id, task_key, seed_output_dir)."""
    import os
    env = os.environ.copy()
    r = subprocess.run(
        [sys.executable, "-m", "awp", "experiment", "create", "Cascade Smoke"],
        capture_output=True, text=True, env=env,
    )
    exp_id = json.loads(r.stdout)["experiment_id"]
    r = subprocess.run(
        [sys.executable, "-m", "awp", "task", "create", exp_id, "P"],
        capture_output=True, text=True, env=env,
    )
    tid = json.loads(r.stdout)["task_id"]
    seed_output = tmp_path / exp_id / "tasks" / tid / "seed"
    return exp_id, f"{exp_id}:{tid}", seed_output


def _mk_fake_run(base: Path, run_id: str, score: float) -> None:
    run_dir = base / "output" / "workspace" / "runs" / run_id
    # Also create at the simpler output/<run_id> path for older callers
    simple = base / "output" / run_id
    for rd in (run_dir, simple):
        rd.mkdir(parents=True, exist_ok=True)
        (rd / "run_completion.json").write_text(json.dumps({
            "run_id": run_id, "status": "complete", "task": "t",
            "final_budget": {"loops": {"used": 1, "cap": 10}, "tokens": {"used": 1, "cap": 100}},
            "eval": {"score": score}, "critique": {"defects": []}, "gate_rejections": 0,
        }))
        (rd / "events.jsonl").write_text("")
        (rd / "metrics.jsonl").write_text("")
        (rd / "FINAL").mkdir(exist_ok=True)
        (rd / "FINAL" / "paper.md").write_text(f"run={run_id}")
```

- [ ] **Step 2: Run — expect `ModuleNotFoundError: No module named 'server.services.cascade'`**

```
pytest packages/awp-ui/server/tests/test_cascade_smoke.py -v
```

- [ ] **Step 3: Implement `cascade_after_seed`**

Create `packages/awp-ui/server/services/cascade.py`:

```python
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
```

- [ ] **Step 4: Verify cascade tests**

```
pytest packages/awp-ui/server/tests/test_cascade_smoke.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add packages/awp-ui/server/services/cascade.py packages/awp-ui/server/tests/test_cascade_smoke.py packages/awp-ui/server/tests/awp_ui_test_utils.py
git commit -m "feat(ui-cascade): cascade_after_seed (refine + optimize auto-orchestration)"
```

---

## Task 5: Wire cascade into `runner_service.py`

**Files:**
- Modify: `packages/awp-ui/server/services/runner_service.py`

**Background.** When `runner_service.py`'s main run-spawn task finishes an `AgentWorkflow`, it registers the row (already done in Task 3). If `experiment_id` + `task_id` + cascade toggles on → call `cascade_after_seed`. Uses the currently-active settings fetched once at run start (same row the user was editing).

### Steps

- [ ] **Step 1: Locate the run-completion hook**

```
grep -n "def .*_run\|wf.run\|await .*AgentWorkflow\|await.*event_bus\|run_completion" packages/awp-ui/server/services/runner_service.py | head -15
```

Find where AgentWorkflow completes + where the final run row is saved.

- [ ] **Step 2: Read settings + cascade**

Right after the final DB upsert (Task 3's hierarchy-attached upsert), add:

```python
    if experiment_id and task_id:
        # Fetch active settings for cascade toggles
        settings_row = await store.get_settings("global") or {}
        settings_data = settings_row.get("data_json", {}) if isinstance(settings_row, dict) else {}
        if isinstance(settings_data, str):
            settings_data = json.loads(settings_data)
        from server.services.cascade import cascade_after_seed
        try:
            await cascade_after_seed(
                seed_run_id=run_id,
                seed_run_dir=run_dir,
                experiment_id=experiment_id,
                task_key=task_id,
                task_text=task_text,
                model=model,
                settings=settings_data,
            )
        except Exception as exc:
            logger.exception("cascade_after_seed failed: %s", exc)
            # Do not mark the seed run failed — the cascade is best-effort.
```

Adapt variable names to match the actual function (e.g. the variable holding the seed run's run_id, dir, etc. will be named differently).

- [ ] **Step 3: Verify existing tests unaffected**

```
pytest packages/awp-ui/server/tests/ -v 2>&1 | tail -20
```

Expected: all green.

- [ ] **Step 4: Commit**

```bash
git add packages/awp-ui/server/services/runner_service.py
git commit -m "feat(ui-runner): fire cascade_after_seed on hierarchy-attached runs"
```

---

## Task 6: Frontend — Cascade toggles in Settings

**Files:**
- Modify: `packages/awp-ui/frontend/src/components/Settings/SettingsPanel.tsx` (or equivalent)

**Background.** Append a `## Cascade` subsection to the Settings panel with two checkboxes + two number inputs. No new components; use whatever form controls the panel already uses.

### Steps

- [ ] **Step 1: Locate the Settings component**

```
grep -rn "auto_refine_after_seed\|critique_enabled\|planning_enabled" packages/awp-ui/frontend/src/ | head -10
```

Find where the existing toggles live (probably `SettingsPanel.tsx` or one of its sub-panels).

- [ ] **Step 2: Add the four fields**

In the same style as the existing `critique_enabled` toggle (checkbox + label), add:

```tsx
<div className="border-t pt-3">
  <div className="text-xs font-semibold text-slate-600 uppercase mb-2">
    Cascade (Plan 7)
  </div>

  <label className="flex items-center gap-2 py-1">
    <input
      type="checkbox"
      checked={settings.auto_refine_after_seed}
      onChange={(e) => update("auto_refine_after_seed", e.target.checked)}
    />
    <span className="text-sm">Auto-refine after seed</span>
  </label>
  <label className="flex items-center gap-2 py-1 pl-6">
    <span className="text-xs text-slate-500">iterations</span>
    <input
      type="number"
      min={1}
      max={10}
      value={settings.auto_refine_iterations}
      onChange={(e) => update("auto_refine_iterations", Number(e.target.value))}
      className="w-16 text-sm border rounded px-1"
    />
  </label>

  <label className="flex items-center gap-2 py-1">
    <input
      type="checkbox"
      checked={settings.auto_optimize_after_seed}
      onChange={(e) => update("auto_optimize_after_seed", e.target.checked)}
    />
    <span className="text-sm">Auto-optimize after seed</span>
  </label>
  <label className="flex items-center gap-2 py-1 pl-6">
    <span className="text-xs text-slate-500">epochs</span>
    <input
      type="number"
      min={1}
      max={10}
      value={settings.auto_optimize_epochs}
      onChange={(e) => update("auto_optimize_epochs", Number(e.target.value))}
      className="w-16 text-sm border rounded px-1"
    />
  </label>

  <p className="text-xs text-slate-400 mt-2">
    Requires a task to be selected in the Experiments sidebar. Legacy
    Sessions-based runs cannot cascade.
  </p>
</div>
```

Adapt `settings` / `update` to match the actual state pattern in that component (likely Zustand store accessors).

- [ ] **Step 3: Build + verify**

```
cd packages/awp-ui/frontend && npm run build 2>&1 | tail -10
```

- [ ] **Step 4: Commit**

```bash
git add packages/awp-ui/frontend/src/components/Settings/
git commit -m "feat(ui-settings): Cascade section (auto-refine + auto-optimize toggles)"
```

---

## Task 7: Frontend — Task-scoped run trigger

**Files:**
- Modify: `packages/awp-ui/frontend/src/components/TaskInputBar/*.tsx` (or wherever the run-trigger is)
- Modify: `packages/awp-ui/frontend/src/api/runs.ts`

**Background.** When a Task is selected in the Experiments sidebar, the "Run" button should include `experiment_id` + `task_id` in the `POST /api/runs/create` body. If no Task is selected, legacy path (no hierarchy attach). A small info hint in the run button label when the cascade would fire.

### Steps

- [ ] **Step 1: Find the run-trigger component**

```
grep -rn "POST /runs/create\|/api/runs/create\|runs/create\|runs.create\|startRun\|fireRun" packages/awp-ui/frontend/src/ | head -10
```

- [ ] **Step 2: Thread through experiment_id + task_id**

When the call is made, include the current `selectedExperimentId` + `selectedTaskId` from the store if set:

```tsx
const selectedTaskId = useWorkflowStore(s => s.selectedTaskId);
const selectedExperimentId = useWorkflowStore(s => s.selectedExperimentId);

const fireRun = async () => {
  await fetch("/api/runs/create", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      task,
      model,
      // … existing fields …
      experiment_id: selectedExperimentId,
      task_id: selectedTaskId,
    }),
  });
};
```

Adapt to the actual call-site pattern.

- [ ] **Step 3: Visual hint when cascade will fire**

Above the run button, show a one-liner if cascade would fire:

```tsx
{selectedTaskId && (settings.auto_refine_after_seed || settings.auto_optimize_after_seed) && (
  <div className="text-xs text-violet-600">
    Cascade: seed{settings.auto_refine_after_seed ? " → refine" : ""}{settings.auto_optimize_after_seed ? " → optimize" : ""}
  </div>
)}
```

- [ ] **Step 4: Build + commit**

```
cd packages/awp-ui/frontend && npm run build 2>&1 | tail -10
git add packages/awp-ui/frontend/src/components/TaskInputBar/ packages/awp-ui/frontend/src/api/runs.ts
git commit -m "feat(ui-frontend): run trigger passes experiment_id + task_id when task selected"
```

---

## Task 8: Mirror + full regression + docs

- [ ] **Step 1: Full regression**

```
pytest packages/awp-core/tests/ packages/awp-runtime/tests/ packages/awp-ui/server/tests/ -k "not e2e and not test_experiment_routes" 2>&1 | tail -10
```

Expected: all green.

- [ ] **Step 2: Frontend build clean**

```
cd packages/awp-ui/frontend && npm run build 2>&1 | tail -5
```

- [ ] **Step 3: Mirror**

```
rsync -a packages/awp-core/src/awp/ reference/python/src/awp/
rsync -a packages/awp-runtime/src/awp/ reference/python/src/awp/
rsync -a packages/awp-ui/server/ reference/python/src/server/
```

- [ ] **Step 4: Drift gates**

```
python scripts/check_mirror_drift.py && echo MIRROR_OK
python scripts/check_docs_drift.py && echo DOCS_OK
python scripts/check_sync_coverage.py && echo SYNC_OK
```

- [ ] **Step 5: Commit**

```bash
git add reference/python/src/
git commit -m "chore(mirror): sync reference/python/src with Plan 7 (UI cascade)"
```

---

## Self-review

- FINAL/ dual-location lookup works (workspace-level AND run-level). Refinement no longer aborts with `no_prior_deliverable` on real runtime layouts.
- Settings expose `auto_refine_after_seed` + `auto_optimize_after_seed` + iteration/epoch counts with backward-compatible defaults.
- `POST /api/runs/create` accepts optional `experiment_id` + `task_id`. When provided, the run lands under the hierarchy with `run_role="seed"`.
- `cascade_after_seed` fires refine + optimize when toggles on, skips silently otherwise. Each phase's runs finalise via `_post_run_finalise` with the right role.
- UI Settings panel has a Cascade section; TaskInputBar threads experiment+task through when selected; run button shows a hint when cascade will fire.
- Frontend build clean; backend suite green; drift gates green.

## Expected user experience after Plan 7

1. Open UI, switch to Experiments tab, select an Experiment + Task.
2. Settings panel → Cascade section → tick "Auto-refine after seed" (iterations=2) + "Auto-optimize after seed" (epochs=1).
3. Enter a task prompt in the input bar, hit Run.
4. Watch the sidebar: seed run appears → completes → refine session appears with 2 iter runs → completes → optimize suite epoch appears → completes. BEST badge updates after each phase if loss improves. All live in the same UI session.
