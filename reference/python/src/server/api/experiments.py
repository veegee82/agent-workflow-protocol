"""Plan 5 — API routes for the experiment/task hierarchy."""

from __future__ import annotations

import time
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(tags=["experiments"])


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
