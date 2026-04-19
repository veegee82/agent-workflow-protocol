"""Unit tests for the outer-loop SuiteRunner (Phase A2).

These tests exercise the full suite → epoch → epoch_runs pipeline with a
**stub workflow factory** that writes a fake ``run_completion.json``
inside the per-task output directory. No LLM calls are made.

The two invariants pinned by this file:

1. ``mean_loss == mean(per-task loss)``.
2. ``child_artifacts == parent_artifacts`` after every epoch (Phase A2 has
   no optimiser; the registry is read-only during ``run_epoch``).
"""

from __future__ import annotations

import json
import math
import textwrap
import uuid
from pathlib import Path

import pytest
from awp.outer_loop import (
    ArtifactRegistry,
    EpochResult,
    SuiteRunner,
    load_suite,
)
from awp.outer_loop.store import SqliteArtifactStore


def _stub_factory(status: str, eval_score: float, critique_score: float):
    """Return a workflow_factory that writes a hand-crafted run_completion."""

    def _factory(task, output_dir: Path) -> tuple[str, Path]:
        run_id = f"run-{task.name}-{uuid.uuid4().hex[:6]}"
        run_dir = output_dir / "runs" / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        rc = {
            "run_id": run_id,
            "status": status,
            "eval": {"score": eval_score},
            "critique": {"score": critique_score},
            "final_budget": {"budget_remaining_pct": 100.0},
            "config_used": {"max_rejected_completions": 2},
        }
        (run_dir / "run_completion.json").write_text(json.dumps(rc), encoding="utf-8")
        # Empty metrics file — the loss falls back to run_completion fields.
        (run_dir / "metrics.jsonl").write_text("", encoding="utf-8")
        return run_id, run_dir

    return _factory


def _per_task_factory(per_task: dict[str, dict]):
    """Stub factory whose output depends on the task name."""

    def _factory(task, output_dir: Path) -> tuple[str, Path]:
        spec = per_task[task.name]
        run_id = f"run-{task.name}-{uuid.uuid4().hex[:6]}"
        run_dir = output_dir / "runs" / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        rc = {
            "run_id": run_id,
            "status": spec["status"],
            "eval": {"score": spec["eval"]},
            "critique": {"score": spec["critique"]},
            "final_budget": {"budget_remaining_pct": 100.0},
            "config_used": {"max_rejected_completions": 2},
        }
        (run_dir / "run_completion.json").write_text(json.dumps(rc), encoding="utf-8")
        (run_dir / "metrics.jsonl").write_text("", encoding="utf-8")
        return run_id, run_dir

    return _factory


def _write_minimal_suite(path: Path, name: str = "test_suite_v1") -> Path:
    path.write_text(
        textwrap.dedent(
            f"""\
            name: {name}
            tasks:
              - name: t_alpha
                task: "first task description"
              - name: t_beta
                task: "second task description"
            """
        ),
        encoding="utf-8",
    )
    return path


def test_suite_loads_runs_and_writes_db_rows(tmp_path: Path) -> None:
    db_path = tmp_path / "outer_loop.db"
    suite_yaml = _write_minimal_suite(tmp_path / "suite.yaml")
    suite = load_suite(suite_yaml)

    registry = ArtifactRegistry(db_path=str(db_path))
    store = SqliteArtifactStore(str(db_path))
    runner = SuiteRunner(
        registry=registry,
        store=store,
        workflow_factory=_stub_factory("complete", 0.8, 0.6),
    )

    parent_artifacts = {n: registry.get_active(n).version for n in registry.list_artifacts()}

    out = tmp_path / "runs"
    result = runner.run_epoch(suite, epoch_num=1, parent_artifacts=parent_artifacts, output_dir=out)

    assert isinstance(result, EpochResult)
    assert result.suite_name == "test_suite_v1"
    assert len(result.task_results) == 2
    for tr in result.task_results:
        assert tr.status == "complete"
        # All-complete + eval=0.8 + crit=0.6 → identical losses.
        assert math.isclose(tr.loss, 0.4 * 0.2 + 0.3 * 0.4, abs_tol=1e-9)

    # DB rows must exist — both epochs and epoch_runs.
    suites = store.find_task_suite_by_name("test_suite_v1")
    assert suites is not None
    epochs = store.list_epochs(suites["id"])
    assert len(epochs) == 1
    epoch_runs = store.list_epoch_runs(epochs[0]["id"])
    assert {r["task_name"] for r in epoch_runs} == {"t_alpha", "t_beta"}
    for r in epoch_runs:
        assert r["loss"] is not None
        scores = json.loads(r["scores_json"])
        assert "eval_score" in scores


def test_mean_loss_equals_mean_of_per_task_losses(tmp_path: Path) -> None:
    db_path = tmp_path / "outer_loop.db"
    suite_yaml = _write_minimal_suite(tmp_path / "suite.yaml", name="mean_check_v1")
    suite = load_suite(suite_yaml)

    registry = ArtifactRegistry(db_path=str(db_path))
    store = SqliteArtifactStore(str(db_path))
    factory = _per_task_factory(
        {
            "t_alpha": {"status": "complete", "eval": 1.0, "critique": 1.0},  # very low loss
            "t_beta": {"status": "failed", "eval": 0.0, "critique": 0.0},  # very high loss
        }
    )
    runner = SuiteRunner(registry=registry, store=store, workflow_factory=factory)

    parent_artifacts = {n: 0 for n in registry.list_artifacts()}
    result = runner.run_epoch(
        suite,
        epoch_num=1,
        parent_artifacts=parent_artifacts,
        output_dir=tmp_path / "runs",
    )
    assert result.mean_loss is not None
    expected_mean = sum(tr.loss for tr in result.task_results) / len(result.task_results)
    assert math.isclose(result.mean_loss, expected_mean, abs_tol=1e-12)

    # Persisted mean must match the in-memory mean.
    suite_row = store.find_task_suite_by_name("mean_check_v1")
    epochs = store.list_epochs(suite_row["id"])
    assert math.isclose(epochs[0]["mean_loss"], expected_mean, abs_tol=1e-12)


def test_child_artifacts_equal_parent_artifacts_a2_invariant(tmp_path: Path) -> None:
    db_path = tmp_path / "outer_loop.db"
    suite_yaml = _write_minimal_suite(tmp_path / "suite.yaml", name="invariant_v1")
    suite = load_suite(suite_yaml)

    registry = ArtifactRegistry(db_path=str(db_path))
    store = SqliteArtifactStore(str(db_path))
    runner = SuiteRunner(
        registry=registry,
        store=store,
        workflow_factory=_stub_factory("complete", 0.7, 0.7),
    )

    parent = {"worker_pitfalls": 3, "manager_planning_preamble": 7}
    result = runner.run_epoch(
        suite,
        epoch_num=1,
        parent_artifacts=parent,
        output_dir=tmp_path / "runs",
    )

    # In-memory invariant.
    assert result.child_artifacts == parent
    assert result.child_artifacts is not parent  # defensive copy

    # Persisted invariant.
    suite_row = store.find_task_suite_by_name("invariant_v1")
    epochs = store.list_epochs(suite_row["id"])
    persisted_child = json.loads(epochs[0]["child_artifacts_json"])
    persisted_parent = json.loads(epochs[0]["parent_artifacts_json"])
    assert persisted_child == persisted_parent == parent


def test_suite_yaml_validation_rejects_duplicate_task_names(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        textwrap.dedent(
            """\
            name: dupe_v1
            tasks:
              - name: t1
                task: "a"
              - name: t1
                task: "b"
            """
        ),
        encoding="utf-8",
    )
    with pytest.raises(Exception):
        load_suite(bad)


def test_suite_yaml_validation_rejects_unknown_top_level_field(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        textwrap.dedent(
            """\
            name: bad_v1
            mystery_field: 42
            tasks:
              - name: t
                task: "x"
            """
        ),
        encoding="utf-8",
    )
    with pytest.raises(Exception):
        load_suite(bad)
