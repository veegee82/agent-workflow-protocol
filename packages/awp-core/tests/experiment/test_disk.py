"""Tests for on-disk experiment + task persistence."""

from __future__ import annotations

from pathlib import Path

import pytest

from awp.experiment import disk
from awp.experiment.paths import task_id_for, experiment_dir, task_dir
from awp.models.experiment import ExperimentManifest
from awp.models.task import InputRole, TaskInput, TaskManifest, TaskMode


@pytest.fixture
def tmp_root(tmp_path: Path, monkeypatch) -> Path:
    """Mock experiment root to use tmp_path instead of /tmp/awp-experiments."""
    monkeypatch.setenv("AWP_EXPERIMENTS_ROOT", str(tmp_path))
    # Patch the functions at their import site in disk module
    monkeypatch.setattr(disk, "experiment_dir", lambda exp_id: tmp_path / exp_id)
    monkeypatch.setattr(disk, "task_dir", lambda exp_id, task_id: tmp_path / exp_id / "tasks" / task_id)
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
