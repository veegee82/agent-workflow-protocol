# Plan 5 — UI: Experiment/Task Hierarchy + Loss Curves + BEST Override

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox syntax.

**Goal:** The UI exposes the three-level hierarchy (`Experiment → Task → Run`) built by Plans 1-4. Users browse experiments in a tree sidebar, open an experiment detail view with loss across tasks, open a task detail view with loss across runs (seed + refine + optimize series), and override the BEST pointer from the UI.

**Architecture:** Pure additive. No deletions of existing components. New sidebar **component** lives alongside the existing `SessionSidebar` — the user toggles between "Sessions" and "Experiments" view modes. Two new React views (`ExperimentDetailView`, `TaskDetailView`). One reusable Recharts wrapper (`LossCurveGeneric`). Five new API routes on the FastAPI backend. Zustand store gets `experiments` / `tasks` slices. Existing run-detail rendering (Graph + Trace + Iterations) is reused unchanged — only breadcrumbs are added.

**Spec refs:** spec §9 UI surface.

**Tech Stack:** React 18, TypeScript, Zustand, Recharts 3.8, TailwindCSS 3, FastAPI, aiosqlite. All already in the project; no new dependencies.

**Lessons baked in** (Plans 1-4):
- No scope-creep. Touch only files listed below. If the implementer feels the urge to refactor CLAUDE.md or add "while we're at it" improvements, they MUST stop and escalate.
- Flat tests for new backend route tests (`test_experiment_routes.py`, not `tests/experiments/__init__.py`).
- Real schemas in fixtures (`eval.score`, not `evaluation.score`).
- Smoke-test gate at the end runs the real backend + asserts response shapes.
- No namespace-package collisions (frontend adds files under existing dirs; no new top-level packages).

**Out of scope:**
- Shared-artifacts view (memory / tools / skills browsable content) — deferred.
- Outer-loop-history tab populated with artifact-version diffs — shows a placeholder in Plan 5; data loader lands in Plan 6.
- Mobile / narrow-viewport layout — desktop-first only.
- Real-time push to the sidebar when a new task/experiment is created from CLI on the same machine — Plan 5 uses manual refresh / poll on navigation. A WebSocket broadcast for experiments is a Plan 6 polish item.
- Editing user_prompt / user_feedback post-hoc.

---

## Known preconditions (verified during exploration)

- Backend: FastAPI router in `packages/awp-ui/server/api/routes.py`. DB access via `server.services.store.StoreService` (already has `list_experiments`, `list_tasks`, `get_task`, `set_task_best` from Plans 1+2).
- Frontend: React 18 + TypeScript + Vite. Entry `packages/awp-ui/frontend/src/App.tsx`. Zustand store at `src/stores/workflowStore.ts`. Recharts already installed and used in `OptimizerPanel/charts/LossCurve.tsx`.
- Existing SessionSidebar at `src/components/SessionSidebar/SessionSidebar.tsx` — will coexist; Plan 5 adds a sibling `ExperimentSidebar`.
- `runs.loss REAL` column exists (Plan 1 Task 6 migration).
- `tasks.best_run_id` + `tasks.best_reason` exist and are populated by the post-run hook (Plans 2, 4).

---

## File structure

**Created (backend):**
- `packages/awp-ui/server/tests/test_experiment_routes.py` — new route tests.
- `packages/awp-ui/server/api/experiments.py` — new APIRouter sub-module with experiment/task routes (keeps `routes.py` from growing further).

**Modified (backend):**
- `packages/awp-ui/server/api/routes.py` — mount the new sub-router.
- `packages/awp-ui/server/services/store.py` — add `get_experiment`, `list_runs_for_task`, `get_task_loss_series`, `get_experiment_loss_curve`.

**Created (frontend):**
- `packages/awp-ui/frontend/src/components/ExperimentSidebar/ExperimentSidebar.tsx`
- `packages/awp-ui/frontend/src/components/ExperimentSidebar/useExperimentTree.ts` (data-loading hook)
- `packages/awp-ui/frontend/src/views/ExperimentDetailView.tsx`
- `packages/awp-ui/frontend/src/views/TaskDetailView.tsx`
- `packages/awp-ui/frontend/src/components/Charts/LossCurveGeneric.tsx`
- `packages/awp-ui/frontend/src/api/experiments.ts` (thin fetch wrappers)

**Modified (frontend):**
- `packages/awp-ui/frontend/src/stores/workflowStore.ts` — experiments/tasks slices + selectors.
- `packages/awp-ui/frontend/src/App.tsx` — add sidebar-mode toggle (Sessions | Experiments) + new view routes.

---

## Task 1: Backend — store methods

**Files:**
- Modify: `packages/awp-ui/server/services/store.py`
- Test: `packages/awp-ui/server/tests/test_experiment_routes.py`

- [ ] **Step 1: Write failing tests**

Create `packages/awp-ui/server/tests/test_experiment_routes.py` (backend-route tests use `httpx.AsyncClient` against the FastAPI app — see existing pattern in `server/tests/`). Start with store-only tests:

```python
"""Plan 5 — backend route + store tests for experiment/task hierarchy."""

from __future__ import annotations

from pathlib import Path

import pytest
import pytest_asyncio

from server.services.store import StoreService


@pytest_asyncio.fixture
async def store(tmp_path: Path) -> StoreService:
    s = StoreService(db_path=tmp_path / "test.db")
    await s.init_db()
    yield s
    await s.close()


@pytest.mark.asyncio
async def test_list_runs_for_task_ordered_by_created_at(store: StoreService) -> None:
    await store.create_experiment("exp_a", "E", "", "/tmp/a", 1.0)
    await store.create_task(
        "exp_a:001-s", "exp_a", 1, "s", "seed", "p", None, "[]", 1.0,
    )
    await store.upsert_run_for_task("r1", "exp_a", "exp_a:001-s", "seed", 0.5, "complete", "t", "m")
    await store.upsert_run_for_task("r2", "exp_a", "exp_a:001-s", "refine_iter", 0.3, "complete", "t", "m")
    await store.upsert_run_for_task("r3", "exp_a", "exp_a:001-s", "seed", 0.4, "complete", "t", "m")
    rows = await store.list_runs_for_task("exp_a:001-s")
    assert [r["id"] for r in rows] == ["r1", "r2", "r3"]
    roles = {r["id"]: r["run_role"] for r in rows}
    assert roles == {"r1": "seed", "r2": "refine_iter", "r3": "seed"}


@pytest.mark.asyncio
async def test_get_task_loss_series(store: StoreService) -> None:
    await store.create_experiment("exp_a", "E", "", "/tmp/a", 1.0)
    await store.create_task(
        "exp_a:001-s", "exp_a", 1, "s", "seed", "p", None, "[]", 1.0,
    )
    await store.upsert_run_for_task("r1", "exp_a", "exp_a:001-s", "seed", 0.5, "complete", "t", "m")
    await store.upsert_run_for_task("r2", "exp_a", "exp_a:001-s", "refine_iter", 0.3, "complete", "t", "m")
    series = await store.get_task_loss_series("exp_a:001-s")
    assert len(series) == 2
    assert series[0]["loss"] == pytest.approx(0.5)
    assert series[1]["loss"] == pytest.approx(0.3)
    assert series[0]["run_role"] == "seed"
    assert series[1]["run_role"] == "refine_iter"


@pytest.mark.asyncio
async def test_get_experiment_loss_curve(store: StoreService) -> None:
    """One point per task: (task_number, best_loss)."""
    await store.create_experiment("exp_a", "E", "", "/tmp/a", 1.0)
    await store.create_task(
        "exp_a:001-s", "exp_a", 1, "s", "seed", "p", None, "[]", 1.0,
    )
    await store.create_task(
        "exp_a:002-t", "exp_a", 2, "t", "seed", "p", None, "[]", 2.0,
    )
    await store.upsert_run_for_task("r1", "exp_a", "exp_a:001-s", "seed", 0.5, "complete", "t", "m")
    await store.upsert_run_for_task("r2", "exp_a", "exp_a:002-t", "seed", 0.2, "complete", "t", "m")
    await store.set_task_best("exp_a:001-s", "r1", "auto_loss")
    await store.set_task_best("exp_a:002-t", "r2", "auto_loss")
    curve = await store.get_experiment_loss_curve("exp_a")
    assert curve == [
        {"task_number": 1, "task_id": "exp_a:001-s", "best_loss": pytest.approx(0.5)},
        {"task_number": 2, "task_id": "exp_a:002-t", "best_loss": pytest.approx(0.2)},
    ]
```

- [ ] **Step 2: Run — expect `AttributeError` on new methods**

```
pytest packages/awp-ui/server/tests/test_experiment_routes.py -v
```

- [ ] **Step 3: Add store methods**

In `packages/awp-ui/server/services/store.py` `StoreService`, append:

```python
    async def list_runs_for_task(self, task_id_key: str) -> list[dict]:
        cur = await self.db.execute(
            "SELECT id, run_role, loss, status, created_at, completed_at "
            "FROM runs WHERE task_id = ? ORDER BY created_at ASC",
            (task_id_key,),
        )
        return [dict(r) for r in await cur.fetchall()]

    async def get_task_loss_series(self, task_id_key: str) -> list[dict]:
        """Loss per run in a task, ordered by created_at."""
        cur = await self.db.execute(
            "SELECT id AS run_id, run_role, loss, status, created_at "
            "FROM runs WHERE task_id = ? AND loss IS NOT NULL "
            "ORDER BY created_at ASC",
            (task_id_key,),
        )
        return [dict(r) for r in await cur.fetchall()]

    async def get_experiment_loss_curve(self, experiment_id: str) -> list[dict]:
        """One point per task: (task_number, best_loss). Only tasks with a best_run_id."""
        cur = await self.db.execute(
            """
            SELECT t.task_number, t.id AS task_id, r.loss AS best_loss
            FROM tasks t
            LEFT JOIN runs r ON r.id = t.best_run_id
            WHERE t.experiment_id = ?
            ORDER BY t.task_number ASC
            """,
            (experiment_id,),
        )
        return [dict(r) for r in await cur.fetchall()]
```

- [ ] **Step 4: Verify + commit**

```
pytest packages/awp-ui/server/tests/test_experiment_routes.py -v
git add packages/awp-ui/server/services/store.py packages/awp-ui/server/tests/test_experiment_routes.py
git commit -m "feat(ui-store): list_runs_for_task + get_task_loss_series + get_experiment_loss_curve"
```

---

## Task 2: Backend — new API sub-router

**Files:**
- Create: `packages/awp-ui/server/api/experiments.py`
- Modify: `packages/awp-ui/server/api/routes.py` — mount the sub-router
- Test: extend `test_experiment_routes.py` with route-level tests

- [ ] **Step 1: Append failing route tests**

Extend `packages/awp-ui/server/tests/test_experiment_routes.py` with:

```python
from httpx import ASGITransport, AsyncClient


@pytest_asyncio.fixture
async def client(tmp_path: Path, monkeypatch) -> AsyncClient:
    """FastAPI test client backed by an isolated tmp_path DB."""
    monkeypatch.setenv("AWP_UI_DB_PATH", str(tmp_path / "test.db"))
    # Force the store + app singletons to rebuild with this path.
    from server import app as app_mod
    import importlib
    importlib.reload(app_mod)
    transport = ASGITransport(app=app_mod.app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_list_experiments_route(client: AsyncClient) -> None:
    r = await client.post("/api/experiments", json={"name": "E", "goal": "G"})
    assert r.status_code == 200
    exp = r.json()
    r = await client.get("/api/experiments")
    assert r.status_code == 200
    assert any(e["id"] == exp["id"] for e in r.json())


@pytest.mark.asyncio
async def test_experiment_detail_includes_tasks(client: AsyncClient) -> None:
    r = await client.post("/api/experiments", json={"name": "E", "goal": "G"})
    exp_id = r.json()["id"]
    r = await client.post(
        f"/api/experiments/{exp_id}/tasks",
        json={"user_prompt": "Write a paper"},
    )
    assert r.status_code == 200
    r = await client.get(f"/api/experiments/{exp_id}")
    assert r.status_code == 200
    detail = r.json()
    assert detail["id"] == exp_id
    assert len(detail["tasks"]) == 1
    assert detail["tasks"][0]["mode"] == "seed"


@pytest.mark.asyncio
async def test_set_best_route(client: AsyncClient) -> None:
    r = await client.post("/api/experiments", json={"name": "E"})
    exp_id = r.json()["id"]
    r = await client.post(
        f"/api/experiments/{exp_id}/tasks", json={"user_prompt": "t"},
    )
    task_id = r.json()["id"]
    # Seed a run row + call set-best
    from server.services.store import StoreService
    import os
    s = StoreService(db_path=os.environ["AWP_UI_DB_PATH"])
    await s.init_db()
    await s.upsert_run_for_task("rX", exp_id, task_id, "seed", 0.4, "complete", "t", "m")
    await s.close()
    r = await client.post(f"/api/tasks/{task_id}/best", json={"run_id": "rX"})
    assert r.status_code == 200
    assert r.json()["best_run_id"] == "rX"


@pytest.mark.asyncio
async def test_experiment_loss_curve_route(client: AsyncClient) -> None:
    r = await client.post("/api/experiments", json={"name": "E"})
    exp_id = r.json()["id"]
    r = await client.get(f"/api/experiments/{exp_id}/loss-curve")
    assert r.status_code == 200
    # Empty curve for fresh experiment
    assert r.json() == []


@pytest.mark.asyncio
async def test_task_loss_series_route(client: AsyncClient) -> None:
    r = await client.post("/api/experiments", json={"name": "E"})
    exp_id = r.json()["id"]
    r = await client.post(
        f"/api/experiments/{exp_id}/tasks", json={"user_prompt": "t"},
    )
    task_id = r.json()["id"]
    r = await client.get(f"/api/tasks/{task_id}/loss-series")
    assert r.status_code == 200
    assert r.json() == []
```

- [ ] **Step 2: Run — expect 404s**

```
pytest packages/awp-ui/server/tests/test_experiment_routes.py -v
```

- [ ] **Step 3: Create the sub-router**

Create `packages/awp-ui/server/api/experiments.py`:

```python
"""Plan 5 — API routes for the experiment/task hierarchy."""

from __future__ import annotations

import time
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api", tags=["experiments"])


class ExperimentCreateRequest(BaseModel):
    name: str
    goal: str = ""


class TaskCreateRequest(BaseModel):
    user_prompt: Optional[str] = None
    user_feedback: Optional[str] = None
    continuation: bool = False
    from_task: Optional[str] = None
    primary: Optional[str] = "BEST/"
    reference: list[str] = []


class SetBestRequest(BaseModel):
    run_id: str


def _get_store():
    from server.app import store
    return store


@router.post("/experiments")
async def create_experiment(req: ExperimentCreateRequest) -> dict:
    import uuid
    from awp.models.experiment import ExperimentManifest
    from awp.experiment.disk import write_experiment_manifest
    from awp.experiment.paths import experiment_dir

    manifest = ExperimentManifest.new(name=req.name, goal=req.goal)
    write_experiment_manifest(manifest)
    store = _get_store()
    await store.create_experiment(
        experiment_id=manifest.experiment_id,
        name=manifest.name,
        goal=manifest.goal,
        base_dir=str(experiment_dir(manifest.experiment_id)),
        created_at=time.time(),
    )
    return {"id": manifest.experiment_id, "name": manifest.name, "goal": manifest.goal}


@router.get("/experiments")
async def list_experiments() -> list[dict]:
    store = _get_store()
    return await store.list_experiments()


@router.get("/experiments/{experiment_id}")
async def get_experiment_detail(experiment_id: str) -> dict:
    store = _get_store()
    row = await store.get_experiment(experiment_id)
    if row is None:
        raise HTTPException(status_code=404, detail="experiment not found")
    tasks = await store.list_tasks(experiment_id)
    return {**row, "tasks": tasks}


@router.post("/experiments/{experiment_id}/tasks")
async def create_task(experiment_id: str, req: TaskCreateRequest) -> dict:
    """Simplified task creation — seed only for Plan 5 UI.

    Continuation tasks are created from the CLI; the UI wizard for continuation
    with input selection is out of scope for this plan.
    """
    from datetime import datetime, timezone
    from awp.experiment.disk import (
        append_task_to_order, read_experiment_manifest, write_task_manifest,
    )
    from awp.experiment.paths import slug_from_prompt, task_id_for
    from awp.models.task import TaskManifest, TaskMode

    if req.continuation:
        raise HTTPException(
            status_code=400,
            detail="continuation task creation via UI is not supported in Plan 5 — "
                   "use `awp task create --continuation` from the CLI",
        )
    if not req.user_prompt:
        raise HTTPException(status_code=400, detail="user_prompt is required")

    manifest_exp = read_experiment_manifest(experiment_id)
    number = len(manifest_exp.task_order) + 1
    slug = slug_from_prompt(req.user_prompt)
    tid = task_id_for(number, slug)
    task = TaskManifest(
        task_id=tid,
        experiment_id=experiment_id,
        task_number=number,
        mode=TaskMode.SEED,
        user_prompt=req.user_prompt,
        user_feedback=None,
        inputs=[],
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    write_task_manifest(experiment_id, task)
    append_task_to_order(experiment_id, tid)

    store = _get_store()
    import json as _json
    await store.create_task(
        task_id_key=f"{experiment_id}:{tid}",
        experiment_id=experiment_id,
        task_number=number,
        slug=slug,
        mode="seed",
        user_prompt=req.user_prompt,
        user_feedback=None,
        inputs_json="[]",
        created_at=time.time(),
    )
    return {
        "id": f"{experiment_id}:{tid}", "task_id": tid,
        "experiment_id": experiment_id, "mode": "seed",
        "task_number": number,
    }


@router.get("/experiments/{experiment_id}/loss-curve")
async def get_experiment_loss_curve(experiment_id: str) -> list[dict]:
    store = _get_store()
    return await store.get_experiment_loss_curve(experiment_id)


@router.get("/tasks/{task_id_key:path}")
async def get_task_detail(task_id_key: str) -> dict:
    store = _get_store()
    row = await store.get_task(task_id_key)
    if row is None:
        raise HTTPException(status_code=404, detail="task not found")
    runs = await store.list_runs_for_task(task_id_key)
    return {**row, "runs": runs}


@router.get("/tasks/{task_id_key:path}/loss-series")
async def task_loss_series(task_id_key: str) -> list[dict]:
    store = _get_store()
    return await store.get_task_loss_series(task_id_key)


@router.post("/tasks/{task_id_key:path}/best")
async def set_task_best(task_id_key: str, req: SetBestRequest) -> dict:
    store = _get_store()
    task = await store.get_task(task_id_key)
    if task is None:
        raise HTTPException(status_code=404, detail="task not found")
    # Verify the run exists + is terminal
    cur = await store.db.execute(
        "SELECT status FROM runs WHERE id = ? AND task_id = ?",
        (req.run_id, task_id_key),
    )
    row = await cur.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="run not found for this task")
    if row["status"] not in ("complete", "partial"):
        raise HTTPException(status_code=400, detail="run is not terminal")
    await store.set_task_best(task_id_key, req.run_id, "user_override")
    return {"best_run_id": req.run_id, "reason": "user_override"}
```

**Note on `task_id_key:path`.** The task-id-key `<exp>:<task>` contains a colon. FastAPI's default path converter stops at `/` so colons are fine, but we use `:path` out of abundance of caution to allow any string.

- [ ] **Step 4: Mount the sub-router**

In `packages/awp-ui/server/api/routes.py`, near the top where other routers are mounted / at the bottom where the main router is exported:

```python
from server.api.experiments import router as experiments_router
```

And in whichever file does `app.include_router(...)` (likely `server/app.py`):

```python
from server.api.experiments import router as experiments_router
app.include_router(experiments_router)
```

Verify by grepping:
```
grep -n "include_router\|APIRouter" packages/awp-ui/server/app.py | head -10
```

- [ ] **Step 5: Verify + commit**

```
pytest packages/awp-ui/server/tests/test_experiment_routes.py -v
git add packages/awp-ui/server/api/experiments.py packages/awp-ui/server/app.py packages/awp-ui/server/api/routes.py
git commit -m "feat(ui-api): experiment + task + BEST-override routes"
```

---

## Task 3: Frontend — store slices + API client

**Files:**
- Create: `packages/awp-ui/frontend/src/api/experiments.ts`
- Modify: `packages/awp-ui/frontend/src/stores/workflowStore.ts`

- [ ] **Step 1: Create the thin API client**

Create `packages/awp-ui/frontend/src/api/experiments.ts`:

```typescript
export interface Experiment {
  id: string;
  name: string;
  goal: string;
  base_dir: string;
  created_at: number;
  archived_at: number | null;
}

export interface Task {
  id: string;                    // "<exp_id>:<task_id>"
  experiment_id: string;
  task_number: number;
  slug: string;
  mode: "seed" | "continuation";
  user_prompt: string | null;
  user_feedback: string | null;
  inputs_json: string;
  best_run_id: string | null;
  best_reason: "auto_loss" | "user_override" | null;
  created_at: number;
}

export interface ExperimentDetail extends Experiment {
  tasks: Task[];
}

export interface TaskRun {
  id: string;
  run_role: "seed" | "refine_iter" | "optimize_epoch_run";
  loss: number | null;
  status: string;
  created_at: string;
  completed_at: string | null;
}

export interface TaskDetail extends Task {
  runs: TaskRun[];
}

export interface LossPoint {
  task_number?: number;
  task_id?: string;
  best_loss?: number;
  run_id?: string;
  run_role?: string;
  loss?: number;
  status?: string;
  created_at?: string;
}

async function apiGet<T>(path: string): Promise<T> {
  const r = await fetch(path);
  if (!r.ok) throw new Error(`GET ${path} → ${r.status}`);
  return r.json() as Promise<T>;
}

async function apiPost<T>(path: string, body: unknown): Promise<T> {
  const r = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`POST ${path} → ${r.status}`);
  return r.json() as Promise<T>;
}

export const experimentApi = {
  list: () => apiGet<Experiment[]>("/api/experiments"),
  create: (name: string, goal: string) =>
    apiPost<Experiment>("/api/experiments", { name, goal }),
  detail: (experimentId: string) =>
    apiGet<ExperimentDetail>(`/api/experiments/${experimentId}`),
  lossCurve: (experimentId: string) =>
    apiGet<LossPoint[]>(`/api/experiments/${experimentId}/loss-curve`),
  createTask: (experimentId: string, userPrompt: string) =>
    apiPost<Task>(`/api/experiments/${experimentId}/tasks`, {
      user_prompt: userPrompt,
    }),
};

export const taskApi = {
  detail: (taskIdKey: string) => apiGet<TaskDetail>(`/api/tasks/${taskIdKey}`),
  lossSeries: (taskIdKey: string) =>
    apiGet<LossPoint[]>(`/api/tasks/${taskIdKey}/loss-series`),
  setBest: (taskIdKey: string, runId: string) =>
    apiPost<{ best_run_id: string; reason: string }>(
      `/api/tasks/${taskIdKey}/best`,
      { run_id: runId }
    ),
};
```

- [ ] **Step 2: Add store slices**

In `packages/awp-ui/frontend/src/stores/workflowStore.ts`, add state + actions. Look at the existing Zustand store pattern (likely `create<State>()(immer(set => ...))`) and add within the same store:

```typescript
// --- Experiment/Task hierarchy (Plan 5) ---

import { experimentApi, taskApi, Experiment, ExperimentDetail, TaskDetail } from "../api/experiments";

// In the state shape:
experiments: Experiment[];
experimentDetails: Record<string, ExperimentDetail>;   // cached by id
taskDetails: Record<string, TaskDetail>;                // cached by task_id_key
selectedExperimentId: string | null;
selectedTaskId: string | null;                         // full key "exp:task"
sidebarMode: "sessions" | "experiments";               // toggle in App.tsx

// In the actions:
loadExperiments: async () => {
  const items = await experimentApi.list();
  set((state) => { state.experiments = items; });
},
loadExperimentDetail: async (experimentId: string) => {
  const detail = await experimentApi.detail(experimentId);
  set((state) => { state.experimentDetails[experimentId] = detail; });
},
loadTaskDetail: async (taskIdKey: string) => {
  const detail = await taskApi.detail(taskIdKey);
  set((state) => { state.taskDetails[taskIdKey] = detail; });
},
setSelectedExperiment: (id: string | null) => set((state) => { state.selectedExperimentId = id; }),
setSelectedTask: (key: string | null) => set((state) => { state.selectedTaskId = key; }),
setSidebarMode: (mode: "sessions" | "experiments") => set((state) => { state.sidebarMode = mode; }),
overrideTaskBest: async (taskIdKey: string, runId: string) => {
  await taskApi.setBest(taskIdKey, runId);
  // refresh the task detail to reflect new best_run_id + reason
  const detail = await taskApi.detail(taskIdKey);
  set((state) => { state.taskDetails[taskIdKey] = detail; });
},
```

Initial values: `experiments: []`, `experimentDetails: {}`, `taskDetails: {}`, `selectedExperimentId: null`, `selectedTaskId: null`, `sidebarMode: "sessions"`.

- [ ] **Step 3: TypeScript check + commit**

```
cd packages/awp-ui/frontend && npm run build 2>&1 | tail -20
```

Must build cleanly (no TypeScript errors). If errors about Zustand/Immer syntax, adapt to match the existing store's actual pattern — do NOT introduce new state-management libraries.

```
git add packages/awp-ui/frontend/src/api/experiments.ts packages/awp-ui/frontend/src/stores/workflowStore.ts
git commit -m "feat(ui-frontend): experiment/task store slices + api client"
```

---

## Task 4: Frontend — `LossCurveGeneric` reusable chart

**Files:**
- Create: `packages/awp-ui/frontend/src/components/Charts/LossCurveGeneric.tsx`

- [ ] **Step 1: Implement the component**

Create the file:

```typescript
import React from "react";
import {
  CartesianGrid, Legend, Line, LineChart, ResponsiveContainer,
  Tooltip, XAxis, YAxis,
} from "recharts";

export interface LossPoint {
  x: number | string;
  loss: number | null;
  label?: string;
  variant?: "seed" | "refine" | "optimize" | "update" | "rollback";
  run_id?: string;
}

const VARIANT_COLOR: Record<NonNullable<LossPoint["variant"]>, string> = {
  seed:     "#8b5cf6",
  refine:   "#f59e0b",
  optimize: "#3b82f6",
  update:   "#10b981",
  rollback: "#ef4444",
};

export function LossCurveGeneric({
  points, xAxisLabel, title,
}: {
  points: LossPoint[];
  xAxisLabel: string;
  title: string;
}): React.ReactElement {
  // Filter out null losses for charting — they're legitimately unknown.
  const data = points
    .filter((p) => p.loss !== null)
    .map((p) => ({ ...p, loss: p.loss as number }));

  return (
    <div className="w-full h-64 bg-white rounded shadow p-3">
      <div className="text-sm font-semibold text-slate-700 mb-2">{title}</div>
      {data.length === 0 ? (
        <div className="flex items-center justify-center h-48 text-slate-400 text-xs">
          No runs with a loss yet
        </div>
      ) : (
        <ResponsiveContainer width="100%" height={200}>
          <LineChart data={data}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="x" label={{ value: xAxisLabel, position: "insideBottom", offset: -5 }} />
            <YAxis domain={[0, 1]} label={{ value: "loss", angle: -90, position: "insideLeft" }} />
            <Tooltip formatter={(v: number) => v.toFixed(3)} />
            <Legend />
            <Line
              type="monotone"
              dataKey="loss"
              stroke="#3b82f6"
              strokeWidth={2}
              dot={({ cx, cy, payload }) => {
                const key = `${payload.run_id ?? payload.x}-dot`;
                const color = payload.variant ? VARIANT_COLOR[payload.variant] : "#3b82f6";
                return <circle key={key} cx={cx} cy={cy} r={4} fill={color} />;
              }}
            />
          </LineChart>
        </ResponsiveContainer>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Build-check + commit**

```
cd packages/awp-ui/frontend && npm run build 2>&1 | tail -10
git add packages/awp-ui/frontend/src/components/Charts/LossCurveGeneric.tsx
git commit -m "feat(ui-frontend): LossCurveGeneric reusable Recharts wrapper"
```

---

## Task 5: Frontend — `ExperimentSidebar` tree component

**Files:**
- Create: `packages/awp-ui/frontend/src/components/ExperimentSidebar/ExperimentSidebar.tsx`
- Create: `packages/awp-ui/frontend/src/components/ExperimentSidebar/useExperimentTree.ts`

- [ ] **Step 1: Implement the tree hook**

Create `packages/awp-ui/frontend/src/components/ExperimentSidebar/useExperimentTree.ts`:

```typescript
import { useEffect, useState } from "react";
import { Experiment, ExperimentDetail, experimentApi } from "../../api/experiments";

export interface ExperimentTreeState {
  experiments: Experiment[];
  expandedIds: Set<string>;
  detailCache: Record<string, ExperimentDetail>;
  loadingIds: Set<string>;
  error: string | null;
}

export function useExperimentTree() {
  const [state, setState] = useState<ExperimentTreeState>({
    experiments: [],
    expandedIds: new Set(),
    detailCache: {},
    loadingIds: new Set(),
    error: null,
  });

  const refresh = async () => {
    try {
      const list = await experimentApi.list();
      setState((s) => ({ ...s, experiments: list, error: null }));
    } catch (e: unknown) {
      setState((s) => ({ ...s, error: String(e) }));
    }
  };

  useEffect(() => {
    void refresh();
  }, []);

  const toggle = async (experimentId: string) => {
    setState((s) => {
      const expanded = new Set(s.expandedIds);
      if (expanded.has(experimentId)) expanded.delete(experimentId);
      else expanded.add(experimentId);
      return { ...s, expandedIds: expanded };
    });
    if (!state.detailCache[experimentId]) {
      setState((s) => ({ ...s, loadingIds: new Set(s.loadingIds).add(experimentId) }));
      try {
        const detail = await experimentApi.detail(experimentId);
        setState((s) => {
          const loading = new Set(s.loadingIds); loading.delete(experimentId);
          return { ...s, detailCache: { ...s.detailCache, [experimentId]: detail }, loadingIds: loading };
        });
      } catch (e: unknown) {
        setState((s) => ({ ...s, error: String(e) }));
      }
    }
  };

  return { ...state, refresh, toggle };
}
```

- [ ] **Step 2: Implement the tree component**

Create `packages/awp-ui/frontend/src/components/ExperimentSidebar/ExperimentSidebar.tsx`:

```typescript
import React from "react";
import { ChevronDown, ChevronRight, FlaskConical, Target } from "lucide-react";
import { useExperimentTree } from "./useExperimentTree";

interface Props {
  selectedExperimentId: string | null;
  selectedTaskId: string | null;
  onSelectExperiment: (id: string) => void;
  onSelectTask: (key: string) => void;
}

export function ExperimentSidebar({
  selectedExperimentId, selectedTaskId, onSelectExperiment, onSelectTask,
}: Props): React.ReactElement {
  const { experiments, expandedIds, detailCache, loadingIds, error, toggle } = useExperimentTree();

  return (
    <div className="flex flex-col gap-1 p-2 text-sm text-slate-700">
      {error && <div className="text-red-500 text-xs">Error: {error}</div>}
      {experiments.length === 0 && (
        <div className="text-slate-400 text-xs italic px-2 py-1">
          No experiments yet. Create one with{" "}
          <code className="text-xs">awp experiment create</code>.
        </div>
      )}
      {experiments.map((exp) => {
        const expanded = expandedIds.has(exp.id);
        const loading = loadingIds.has(exp.id);
        const detail = detailCache[exp.id];
        const selected = selectedExperimentId === exp.id && !selectedTaskId;
        return (
          <div key={exp.id} className="flex flex-col">
            <button
              onClick={() => { void toggle(exp.id); onSelectExperiment(exp.id); }}
              className={`flex items-center gap-1 px-2 py-1 rounded hover:bg-slate-100 text-left ${selected ? "bg-violet-100" : ""}`}
            >
              {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
              <FlaskConical size={14} className="text-violet-500" />
              <span className="truncate flex-1">{exp.name}</span>
            </button>
            {expanded && (
              <div className="ml-5 flex flex-col gap-0.5">
                {loading && <div className="text-xs text-slate-400 px-2">Loading…</div>}
                {detail?.tasks.map((t) => {
                  const fullKey = t.id;
                  const taskSelected = selectedTaskId === fullKey;
                  return (
                    <button
                      key={fullKey}
                      onClick={() => onSelectTask(fullKey)}
                      className={`flex items-center gap-1 px-2 py-0.5 rounded hover:bg-slate-100 text-left ${taskSelected ? "bg-amber-100" : ""}`}
                    >
                      <Target size={12} className={t.mode === "continuation" ? "text-amber-500" : "text-slate-500"} />
                      <span className="text-xs font-mono text-slate-500">
                        {String(t.task_number).padStart(3, "0")}
                      </span>
                      <span className="truncate flex-1 text-xs">{t.slug}</span>
                      {t.best_run_id && (
                        <span className="text-[10px] text-emerald-600">★</span>
                      )}
                    </button>
                  );
                })}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
```

- [ ] **Step 3: Build-check + commit**

```
cd packages/awp-ui/frontend && npm run build 2>&1 | tail -10
git add packages/awp-ui/frontend/src/components/ExperimentSidebar/
git commit -m "feat(ui-frontend): ExperimentSidebar tree (Experiment → Task)"
```

---

## Task 6: Frontend — `ExperimentDetailView`

**Files:**
- Create: `packages/awp-ui/frontend/src/views/ExperimentDetailView.tsx`

- [ ] **Step 1: Implement**

```typescript
import React, { useEffect, useState } from "react";
import {
  ExperimentDetail, experimentApi, LossPoint,
} from "../api/experiments";
import { LossCurveGeneric } from "../components/Charts/LossCurveGeneric";

interface Props {
  experimentId: string;
  onSelectTask: (taskIdKey: string) => void;
}

export function ExperimentDetailView({ experimentId, onSelectTask }: Props): React.ReactElement {
  const [detail, setDetail] = useState<ExperimentDetail | null>(null);
  const [lossCurve, setLossCurve] = useState<LossPoint[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void (async () => {
      try {
        const [d, lc] = await Promise.all([
          experimentApi.detail(experimentId),
          experimentApi.lossCurve(experimentId),
        ]);
        setDetail(d);
        setLossCurve(lc);
      } catch (e: unknown) {
        setError(String(e));
      }
    })();
  }, [experimentId]);

  if (error) return <div className="p-4 text-red-500">Error: {error}</div>;
  if (!detail) return <div className="p-4 text-slate-400">Loading…</div>;

  const lossPoints = lossCurve.map((p) => ({
    x: p.task_number ?? 0,
    loss: p.best_loss ?? null,
    variant: "seed" as const,
  }));

  return (
    <div className="p-6 flex flex-col gap-4 overflow-y-auto">
      <div>
        <h1 className="text-2xl font-bold text-slate-800">{detail.name}</h1>
        {detail.goal && <p className="text-slate-600 mt-1">{detail.goal}</p>}
        <div className="text-xs text-slate-400 mt-1">
          {detail.tasks.length} task{detail.tasks.length === 1 ? "" : "s"} · ID: <code>{detail.id}</code>
        </div>
      </div>

      <LossCurveGeneric
        points={lossPoints}
        xAxisLabel="task number"
        title="Best loss per task (experiment trajectory)"
      />

      <div className="bg-white rounded shadow overflow-hidden">
        <div className="px-4 py-2 text-sm font-semibold text-slate-700 border-b">Tasks</div>
        <table className="w-full text-xs">
          <thead className="bg-slate-50 text-slate-500">
            <tr>
              <th className="px-3 py-2 text-left">#</th>
              <th className="px-3 py-2 text-left">Mode</th>
              <th className="px-3 py-2 text-left">Slug</th>
              <th className="px-3 py-2 text-left">Prompt / Feedback</th>
              <th className="px-3 py-2 text-left">Best</th>
            </tr>
          </thead>
          <tbody>
            {detail.tasks.map((t) => (
              <tr
                key={t.id}
                onClick={() => onSelectTask(t.id)}
                className="border-t cursor-pointer hover:bg-slate-50"
              >
                <td className="px-3 py-2 font-mono">{String(t.task_number).padStart(3, "0")}</td>
                <td className="px-3 py-2">
                  <span className={`px-2 py-0.5 rounded text-[10px] ${t.mode === "continuation" ? "bg-amber-100 text-amber-700" : "bg-slate-100 text-slate-600"}`}>
                    {t.mode}
                  </span>
                </td>
                <td className="px-3 py-2 font-mono text-slate-500">{t.slug}</td>
                <td className="px-3 py-2 truncate max-w-xs">{t.user_prompt ?? t.user_feedback ?? ""}</td>
                <td className="px-3 py-2">
                  {t.best_run_id ? (
                    <span className="text-emerald-600 font-mono text-[10px]">{t.best_run_id.slice(0, 8)}</span>
                  ) : (
                    <span className="text-slate-300">—</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Build-check + commit**

```
cd packages/awp-ui/frontend && npm run build 2>&1 | tail -10
git add packages/awp-ui/frontend/src/views/ExperimentDetailView.tsx
git commit -m "feat(ui-frontend): ExperimentDetailView (header + loss curve + task table)"
```

---

## Task 7: Frontend — `TaskDetailView` with BEST override

**Files:**
- Create: `packages/awp-ui/frontend/src/views/TaskDetailView.tsx`

- [ ] **Step 1: Implement**

```typescript
import React, { useEffect, useState } from "react";
import { TaskDetail, taskApi, LossPoint } from "../api/experiments";
import { LossCurveGeneric } from "../components/Charts/LossCurveGeneric";

interface Props {
  taskIdKey: string;
}

export function TaskDetailView({ taskIdKey }: Props): React.ReactElement {
  const [detail, setDetail] = useState<TaskDetail | null>(null);
  const [series, setSeries] = useState<LossPoint[]>([]);
  const [overriding, setOverriding] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    try {
      const [d, s] = await Promise.all([
        taskApi.detail(taskIdKey),
        taskApi.lossSeries(taskIdKey),
      ]);
      setDetail(d);
      setSeries(s);
    } catch (e: unknown) { setError(String(e)); }
  };

  useEffect(() => { void load(); }, [taskIdKey]);

  const handleOverride = async () => {
    if (!overriding || !detail) return;
    try {
      await taskApi.setBest(taskIdKey, overriding);
      setOverriding(null);
      await load();
    } catch (e: unknown) { setError(String(e)); }
  };

  if (error) return <div className="p-4 text-red-500">Error: {error}</div>;
  if (!detail) return <div className="p-4 text-slate-400">Loading…</div>;

  const variantForRole: Record<string, "seed" | "refine" | "optimize"> = {
    seed: "seed",
    refine_iter: "refine",
    optimize_epoch_run: "optimize",
  };

  const lossPoints: LossPoint[] = series.map((p, i) => ({
    x: i + 1,
    loss: p.loss ?? null,
    run_id: p.run_id,
    variant: variantForRole[p.run_role ?? "seed"] ?? "seed",
  }));

  return (
    <div className="p-6 flex flex-col gap-4 overflow-y-auto">
      <div>
        <h1 className="text-2xl font-bold text-slate-800">
          Task {String(detail.task_number).padStart(3, "0")} · {detail.slug}
        </h1>
        <div className="flex gap-2 mt-1">
          <span className={`px-2 py-0.5 rounded text-[10px] ${detail.mode === "continuation" ? "bg-amber-100 text-amber-700" : "bg-slate-100 text-slate-600"}`}>
            {detail.mode}
          </span>
          {detail.best_run_id && detail.best_reason && (
            <span className={`px-2 py-0.5 rounded text-[10px] ${detail.best_reason === "user_override" ? "bg-violet-100 text-violet-700" : "bg-emerald-100 text-emerald-700"}`}>
              BEST: {detail.best_reason}
            </span>
          )}
        </div>
        {detail.user_prompt && (
          <pre className="mt-2 text-xs bg-slate-50 rounded p-2 whitespace-pre-wrap">{detail.user_prompt}</pre>
        )}
        {detail.user_feedback && (
          <pre className="mt-2 text-xs bg-amber-50 rounded p-2 whitespace-pre-wrap border-l-4 border-amber-300">
            <span className="font-semibold">user_feedback: </span>{detail.user_feedback}
          </pre>
        )}
      </div>

      <LossCurveGeneric
        points={lossPoints}
        xAxisLabel="run sequence"
        title="Loss per run (seed → refine → optimize)"
      />

      <div className="bg-white rounded shadow overflow-hidden">
        <div className="px-4 py-2 text-sm font-semibold text-slate-700 border-b flex justify-between items-center">
          <span>Runs ({detail.runs.length})</span>
          {overriding ? (
            <div className="flex gap-2">
              <button
                onClick={() => void handleOverride()}
                className="text-xs bg-violet-500 text-white px-3 py-1 rounded hover:bg-violet-600"
              >
                Override BEST → {overriding.slice(0, 8)}
              </button>
              <button
                onClick={() => setOverriding(null)}
                className="text-xs bg-slate-200 text-slate-700 px-3 py-1 rounded hover:bg-slate-300"
              >
                Cancel
              </button>
            </div>
          ) : null}
        </div>
        <table className="w-full text-xs">
          <thead className="bg-slate-50 text-slate-500">
            <tr>
              <th className="px-3 py-2 text-left">Run</th>
              <th className="px-3 py-2 text-left">Role</th>
              <th className="px-3 py-2 text-left">Status</th>
              <th className="px-3 py-2 text-left">Loss</th>
              <th className="px-3 py-2 text-left">BEST</th>
              <th className="px-3 py-2 text-left"></th>
            </tr>
          </thead>
          <tbody>
            {detail.runs.map((r) => {
              const isBest = r.id === detail.best_run_id;
              return (
                <tr key={r.id} className={`border-t ${isBest ? "bg-emerald-50" : ""}`}>
                  <td className="px-3 py-2 font-mono">{r.id.slice(0, 12)}</td>
                  <td className="px-3 py-2">{r.run_role}</td>
                  <td className="px-3 py-2">{r.status}</td>
                  <td className="px-3 py-2 font-mono">{r.loss !== null ? r.loss.toFixed(3) : "—"}</td>
                  <td className="px-3 py-2">{isBest ? "★" : ""}</td>
                  <td className="px-3 py-2">
                    {!isBest && r.status === "complete" && (
                      <button
                        onClick={() => setOverriding(r.id)}
                        className="text-[10px] text-violet-600 hover:underline"
                      >
                        Pin as BEST
                      </button>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Build-check + commit**

```
cd packages/awp-ui/frontend && npm run build 2>&1 | tail -10
git add packages/awp-ui/frontend/src/views/TaskDetailView.tsx
git commit -m "feat(ui-frontend): TaskDetailView with loss curve + BEST override"
```

---

## Task 8: `App.tsx` — wire sidebar mode toggle + route views

**Files:**
- Modify: `packages/awp-ui/frontend/src/App.tsx`

**Important.** `App.tsx` is very large (~80 KB). The change MUST be **additive and localised**:
- Add a new state `sidebarMode: "sessions" | "experiments"` to the component (or use the store slice from Task 3).
- Add a **small toggle** (two buttons) near the top of the sidebar column.
- When mode = "experiments", render `<ExperimentSidebar>` INSTEAD of `<SessionSidebar>`.
- When an experiment OR task is selected, render `<ExperimentDetailView>` / `<TaskDetailView>` in the main column INSTEAD of the default run-centric panel.
- When a run is then selected, fall back to the existing run-detail rendering.

**DO NOT** refactor `App.tsx`. **DO NOT** extract panels. **DO NOT** change any existing rendering logic. Only conditionally swap two components based on the new state.

- [ ] **Step 1: Read a representative slice of App.tsx**

```
wc -l packages/awp-ui/frontend/src/App.tsx
grep -n "SessionSidebar\|<Routes\|<Switch\|viewingRun\|selectedSession" packages/awp-ui/frontend/src/App.tsx | head -15
```

- [ ] **Step 2: Add the sidebar-mode toggle**

At the top of the sidebar column (wherever `<SessionSidebar .../>` is rendered), insert a two-button toggle:

```tsx
<div className="flex gap-1 p-2 border-b">
  <button
    onClick={() => setSidebarMode("sessions")}
    className={`text-xs px-2 py-1 rounded ${sidebarMode === "sessions" ? "bg-slate-800 text-white" : "text-slate-500 hover:bg-slate-100"}`}
  >
    Sessions
  </button>
  <button
    onClick={() => setSidebarMode("experiments")}
    className={`text-xs px-2 py-1 rounded ${sidebarMode === "experiments" ? "bg-slate-800 text-white" : "text-slate-500 hover:bg-slate-100"}`}
  >
    Experiments
  </button>
</div>
{sidebarMode === "sessions" ? <SessionSidebar /> : (
  <ExperimentSidebar
    selectedExperimentId={selectedExperimentId}
    selectedTaskId={selectedTaskId}
    onSelectExperiment={setSelectedExperimentId}
    onSelectTask={setSelectedTaskId}
  />
)}
```

- [ ] **Step 3: Add the main-column routing**

Find where the main content area renders (likely after the sidebar, inside a flex/grid). Wrap the default render with:

```tsx
{sidebarMode === "experiments" && selectedTaskId ? (
  <TaskDetailView taskIdKey={selectedTaskId} />
) : sidebarMode === "experiments" && selectedExperimentId ? (
  <ExperimentDetailView
    experimentId={selectedExperimentId}
    onSelectTask={setSelectedTaskId}
  />
) : (
  /* existing rendering stays here unchanged */
)}
```

**Note.** If the existing App.tsx has its own state like `selectedRunId` / `viewingRun`, Plan 5 does NOT remove those — both state machines coexist.

- [ ] **Step 4: Build-check + commit**

```
cd packages/awp-ui/frontend && npm run build 2>&1 | tail -10
```

Expected: build succeeds with no TypeScript errors. If there are errors, they indicate a mismatch with the actual App.tsx structure — adapt the wiring without touching unrelated code.

```
git add packages/awp-ui/frontend/src/App.tsx
git commit -m "feat(ui-frontend): App.tsx sidebar-mode toggle + experiment/task view routes"
```

---

## Task 9: Docs + CLAUDE.md append

**Files:**
- Modify: `CLAUDE.md` — append, do NOT restructure (Plan 4's gutting lesson)
- Modify: `spec/versions/1.0/spec.md` if it mentions the UI (otherwise skip)

- [ ] **Step 1: Append to CLAUDE.md**

Find the `## UI` section or add one after `## Development Commands`:

```markdown
## UI — Experiment/Task Hierarchy (Plan 5)

The web UI (`packages/awp-ui/`) exposes the three-level hierarchy built by Plans 1-4:

- **ExperimentSidebar** (`packages/awp-ui/frontend/src/components/ExperimentSidebar/`) — tree view of `Experiment → Task → Run`. Toggle with the Sessions/Experiments buttons at the top of the sidebar.
- **ExperimentDetailView** (`packages/awp-ui/frontend/src/views/ExperimentDetailView.tsx`) — header, best-loss-per-task curve, task table.
- **TaskDetailView** (`packages/awp-ui/frontend/src/views/TaskDetailView.tsx`) — mode + user_prompt/user_feedback, loss-per-run curve (seed/refine/optimize series), BEST-override action.
- **LossCurveGeneric** (`packages/awp-ui/frontend/src/components/Charts/LossCurveGeneric.tsx`) — reusable Recharts wrapper used by both views.
- Backend routes live in `packages/awp-ui/server/api/experiments.py` — `GET /api/experiments[/{id}[/tasks]]`, `POST /api/experiments/{id}/tasks`, `GET /api/tasks/{key}`, `GET /api/tasks/{key}/loss-series`, `POST /api/tasks/{key}/best`.

Toggling "Experiments" in the sidebar shows the hierarchy; "Sessions" keeps the legacy flat-run view. Both coexist in Plan 5.
```

- [ ] **Step 2: Drift gates**

```
python scripts/check_docs_drift.py && echo DRIFT_OK
python scripts/check_sync_coverage.py && echo SYNC_OK
```

- [ ] **Step 3: Commit**

```
git add CLAUDE.md
git commit -m "docs: UI section for experiment/task hierarchy (Plan 5)"
```

---

## Task 10: Backend-route smoke test (no browser)

**Files:**
- Create: `packages/awp-ui/server/tests/test_experiment_routes_smoke.py` (end-to-end pipeline)

- [ ] **Step 1: Implement**

```python
"""Smoke test for the full experiment/task UI backend pipeline (no browser)."""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient


@pytest_asyncio.fixture
async def client(tmp_path: Path, monkeypatch) -> AsyncClient:
    monkeypatch.setenv("AWP_UI_DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("AWP_EXPERIMENTS_ROOT", str(tmp_path / "awp-exp"))
    from server import app as app_mod
    importlib.reload(app_mod)
    transport = ASGITransport(app=app_mod.app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_full_experiment_task_hierarchy_via_api(
    client: AsyncClient, tmp_path: Path,
) -> None:
    # 1. Create experiment
    r = await client.post("/api/experiments", json={"name": "Smoke", "goal": "G"})
    assert r.status_code == 200
    exp_id = r.json()["id"]

    # 2. Create task
    r = await client.post(f"/api/experiments/{exp_id}/tasks", json={"user_prompt": "P"})
    assert r.status_code == 200
    task_key = r.json()["id"]

    # 3. Seed two runs in the DB (bypass runtime — we're testing the UI API)
    from server.services.store import StoreService
    import os
    s = StoreService(db_path=os.environ["AWP_UI_DB_PATH"])
    await s.init_db()
    await s.upsert_run_for_task("r1", exp_id, task_key, "seed", 0.5, "complete", "P", "m")
    await s.upsert_run_for_task("r2", exp_id, task_key, "refine_iter", 0.3, "complete", "P", "m")
    await s.set_task_best(task_key, "r2", "auto_loss")
    await s.close()

    # 4. Experiment detail
    r = await client.get(f"/api/experiments/{exp_id}")
    assert r.status_code == 200
    assert len(r.json()["tasks"]) == 1

    # 5. Experiment loss curve
    r = await client.get(f"/api/experiments/{exp_id}/loss-curve")
    assert r.status_code == 200
    curve = r.json()
    assert len(curve) == 1
    assert curve[0]["best_loss"] == pytest.approx(0.3)

    # 6. Task detail with runs
    r = await client.get(f"/api/tasks/{task_key}")
    assert r.status_code == 200
    task = r.json()
    assert len(task["runs"]) == 2
    assert task["best_run_id"] == "r2"

    # 7. Task loss series
    r = await client.get(f"/api/tasks/{task_key}/loss-series")
    assert r.status_code == 200
    series = r.json()
    assert len(series) == 2
    assert series[1]["loss"] == pytest.approx(0.3)

    # 8. Override BEST to the worse run
    r = await client.post(f"/api/tasks/{task_key}/best", json={"run_id": "r1"})
    assert r.status_code == 200
    assert r.json()["reason"] == "user_override"

    # 9. Verify override sticks
    r = await client.get(f"/api/tasks/{task_key}")
    assert r.json()["best_run_id"] == "r1"
    assert r.json()["best_reason"] == "user_override"
```

- [ ] **Step 2: Run + commit**

```
pytest packages/awp-ui/server/tests/test_experiment_routes_smoke.py -v
git add packages/awp-ui/server/tests/test_experiment_routes_smoke.py
git commit -m "test(ui): full experiment/task API pipeline smoke test"
```

---

## Task 11: Mirror sync + full regression

- [ ] **Step 1: Full regression**

```
pytest packages/awp-core/tests/ packages/awp-runtime/tests/ -k "not e2e" 2>&1 | tail -5
pytest packages/awp-ui/server/tests/ -v 2>&1 | tail -10
```

Expected: all green.

- [ ] **Step 2: Frontend build**

```
cd packages/awp-ui/frontend && npm run build 2>&1 | tail -10
```

Expected: clean build.

- [ ] **Step 3: Mirror sync**

```
rsync -a packages/awp-core/src/awp/ reference/python/src/awp/
rsync -a packages/awp-runtime/src/awp/ reference/python/src/awp/
rsync -a packages/awp-ui/server/ reference/python/src/server/
```

Frontend is NOT mirrored at the Python level; it lives under `packages/awp-ui/frontend/` only. No action needed there.

- [ ] **Step 4: Drift gates**

```
python scripts/check_mirror_drift.py && echo MIRROR_OK
python scripts/check_docs_drift.py && echo DOCS_OK
python scripts/check_sync_coverage.py && echo SYNC_OK
```

- [ ] **Step 5: Commit**

```bash
git add reference/python/src/
git commit -m "chore(mirror): sync reference/python/src with Plan 5 (UI hierarchy)"
```

---

## Self-review

- Sidebar toggles between Sessions and Experiments.
- `<ExperimentSidebar>` renders a tree (Experiment → Task) with correct expand/collapse and "★" on tasks that have a best_run_id.
- `<ExperimentDetailView>` shows the best-loss-per-task Recharts line.
- `<TaskDetailView>` shows a loss curve over runs with role-colored dots and a BEST-override button that actually posts + refreshes.
- `/api/experiments`, `/api/experiments/{id}`, `/api/experiments/{id}/tasks`, `/api/experiments/{id}/loss-curve`, `/api/tasks/{key}`, `/api/tasks/{key}/loss-series`, `/api/tasks/{key}/best` all exist and return sane shapes.
- `npm run build` clean. Backend suite green.
- No structural refactor of `App.tsx` — only additive state + two conditional renders.
- No modification of CLAUDE.md beyond the single section append.

## Handoff to Plan 6

Plan 6 lands:
- `awp experiment purge-legacy` — deletes flat-layout experiments + orphan `runs` rows.
- Final doc sweep (refinement.md, outer-loop.md, continuation.md cross-linking).
- Full-regression E2E including a UI click-through with Playwright (or deferred to a later iteration).
- Outer-loop-history tab in the experiment detail view, wired to `<experiment>/outer_loop.db`.
