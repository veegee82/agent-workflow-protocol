"""CLI handlers for ``awp experiment ...`` subcommands."""

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
