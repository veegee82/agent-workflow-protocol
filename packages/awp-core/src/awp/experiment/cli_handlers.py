"""CLI handlers for ``awp experiment ...`` and ``awp task ...`` subcommands."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
import time
from argparse import Namespace
from datetime import datetime, timezone
from pathlib import Path

from awp.experiment.disk import (
    append_task_to_order,
    read_experiment_manifest,
    read_task_manifest,
    write_experiment_manifest,
    write_task_manifest,
)
from awp.experiment.paths import experiment_dir, slug_from_prompt, task_dir, task_id_for
from awp.models.experiment import ExperimentManifest
from awp.models.task import InputRole, TaskInput, TaskManifest, TaskMode


# ---------------------------------------------------------------------------
# Store helpers (optional — awp-ui may not be installed)
# ---------------------------------------------------------------------------

def _ui_db_path() -> Path:
    override = os.environ.get("AWP_UI_DB_PATH")
    if override:
        return Path(override)
    return Path.home() / ".awp" / "awp_ui.db"


async def _with_store(fn):
    """Run *fn(store)* with a live StoreService; return None if awp-ui is absent."""
    try:
        from server.services.store import StoreService  # type: ignore[import]
    except ModuleNotFoundError:
        return None
    store = StoreService(db_path=_ui_db_path())
    await store.init_db()
    try:
        return await fn(store)
    finally:
        await store.close()


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------

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
            {
                "experiment_id": manifest.experiment_id,
                "manifest_path": str(disk_path),
            },
            indent=2,
        )
    )
    return 0


def _exp_list() -> int:
    """List experiments.

    Primary source: StoreService (when awp-ui is installed).
    Fallback: scan EXPERIMENTS_ROOT on disk.
    """
    async def _fetch(store):
        return await store.list_experiments()

    rows = asyncio.run(_with_store(_fetch))

    if rows is not None:
        # StoreService returns dicts with key "id"; normalise to "experiment_id"
        # for a consistent CLI contract.
        normalised = []
        for r in rows:
            entry = dict(r)
            if "id" in entry and "experiment_id" not in entry:
                entry["experiment_id"] = entry.pop("id")
            normalised.append(entry)
        print(json.dumps(normalised, indent=2, default=str))
        return 0

    # Fallback: read from disk when awp-ui is not installed.
    from awp.experiment.paths import EXPERIMENTS_ROOT

    results = []
    if EXPERIMENTS_ROOT.exists():
        for child in sorted(EXPERIMENTS_ROOT.iterdir()):
            manifest_path = child / "experiment.json"
            if manifest_path.exists():
                try:
                    m = ExperimentManifest.model_validate_json(
                        manifest_path.read_text(encoding="utf-8")
                    )
                    results.append(
                        {
                            "experiment_id": m.experiment_id,
                            "name": m.name,
                            "goal": m.goal,
                        }
                    )
                except Exception:
                    pass
    print(json.dumps(results, indent=2, default=str))
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


# ---------------------------------------------------------------------------
# task subcommands
# ---------------------------------------------------------------------------

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
    if not args.from_task:
        print(
            "continuation task requires at least one --from-task (R37)",
            file=sys.stderr,
        )
        return 2

    inputs: list[TaskInput] = []
    for src in args.from_task:
        parent_dir = task_dir(args.experiment_id, src)
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


# ---------------------------------------------------------------------------
# Task validation for `awp run --task`
# ---------------------------------------------------------------------------


def validate_task_key_for_run(task_key: str) -> int:
    """Validate --task argument for `awp run`. Returns 0 on OK, non-zero on error."""
    if ":" not in task_key:
        print(
            "--task must be <experiment_id>:<task_id>",
            file=sys.stderr,
        )
        return 2
    exp_id, tid = task_key.split(":", 1)
    if not experiment_dir(exp_id).exists():
        print(f"experiment not found: {exp_id}", file=sys.stderr)
        return 2
    try:
        manifest = read_task_manifest(exp_id, tid)
    except FileNotFoundError:
        print(f"task not found: {task_key}", file=sys.stderr)
        return 2
    if manifest.mode == TaskMode.CONTINUATION:
        print(
            f"continuation task runs are not yet supported in this build "
            f"(scheduled for Plan 3 — continuation-loader). Task {task_key} "
            f"has mode=continuation.",
            file=sys.stderr,
        )
        return 2
    return 0
