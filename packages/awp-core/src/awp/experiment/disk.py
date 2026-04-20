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
