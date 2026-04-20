"""Tests for the continuation bundle loader."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from awp.continuation.bundle_loader import (
    ContinuationBundle,
    ContinuationInputError,
    load_continuation_bundle,
)


def _mk_task_dir(exp_root: Path, exp_id: str, task_id: str) -> Path:
    td = exp_root / exp_id / "tasks" / task_id
    td.mkdir(parents=True, exist_ok=True)
    return td


def _mk_best(task_dir: Path, files: dict[str, str]) -> None:
    best = task_dir / "BEST"
    best.mkdir(parents=True, exist_ok=True)
    (best / "manifest.json").write_text('{"winner_run_id":"dummy"}')
    for relpath, content in files.items():
        p = best / relpath
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)


def _write_task_json(task_dir: Path, content: dict) -> None:
    (task_dir / "task.json").write_text(json.dumps(content))


def test_single_primary_bundle_entry(tmp_path: Path) -> None:
    exp = "exp_aaaaaaaa"
    parent = _mk_task_dir(tmp_path, exp, "001-seed")
    _mk_best(parent, {"paper.md": "draft v1", "analysis/facts.json": '{"x": 1}'})
    cont = _mk_task_dir(tmp_path, exp, "002-improve")
    _write_task_json(cont, {
        "task_id": "002-improve",
        "experiment_id": exp,
        "task_number": 2,
        "mode": "continuation",
        "user_feedback": "deeper section 2",
        "inputs": [
            {"from_task": "001-seed", "role": "primary", "bundle": "BEST/"}
        ],
        "created_at": "2026-04-20T00:00:00+00:00",
    })

    bundle = load_continuation_bundle(
        task_dir=cont, experiment_dir=tmp_path / exp
    )

    assert isinstance(bundle, ContinuationBundle)
    assert len(bundle.primary_materials) == 2
    relpaths = sorted(e.relative_path for e in bundle.primary_materials)
    assert relpaths == ["analysis/facts.json", "paper.md"]
    contents = {e.relative_path: e.content_text for e in bundle.primary_materials}
    assert contents["paper.md"] == "draft v1"
    assert bundle.reference_paths == []
    assert bundle.user_feedback == "deeper section 2"


def test_reference_explicit_paths(tmp_path: Path) -> None:
    exp = "exp_aaaaaaaa"
    parent = _mk_task_dir(tmp_path, exp, "001-seed")
    _mk_best(parent, {"paper.md": "short", "analysis/facts.json": '{"x":1}'})
    cont = _mk_task_dir(tmp_path, exp, "002-x")
    _write_task_json(cont, {
        "task_id": "002-x",
        "experiment_id": exp,
        "task_number": 2,
        "mode": "continuation",
        "user_feedback": "fb",
        "inputs": [
            {"from_task": "001-seed", "role": "primary", "bundle": "BEST/"},
            {"from_task": "001-seed", "role": "reference",
             "paths": ["BEST/analysis/facts.json"]},
        ],
        "created_at": "2026-04-20T00:00:00+00:00",
    })

    bundle = load_continuation_bundle(
        task_dir=cont, experiment_dir=tmp_path / exp
    )

    # Primary still covers BEST/ contents
    assert len(bundle.primary_materials) == 2
    # Reference pointer recorded separately
    assert len(bundle.reference_paths) == 1
    assert bundle.reference_paths[0].source_task == "001-seed"
    assert bundle.reference_paths[0].relative_path == "BEST/analysis/facts.json"
    assert bundle.reference_paths[0].size_bytes > 0


def test_multi_task_inputs_delta(tmp_path: Path) -> None:
    exp = "exp_aaaaaaaa"
    a = _mk_task_dir(tmp_path, exp, "001-a")
    _mk_best(a, {"draft.md": "A draft"})
    b = _mk_task_dir(tmp_path, exp, "002-b")
    _mk_best(b, {"bench.json": '{"score":0.9}'})
    cont = _mk_task_dir(tmp_path, exp, "003-c")
    _write_task_json(cont, {
        "task_id": "003-c",
        "experiment_id": exp,
        "task_number": 3,
        "mode": "continuation",
        "user_feedback": "combine",
        "inputs": [
            {"from_task": "001-a", "role": "primary", "bundle": "BEST/"},
            {"from_task": "002-b", "role": "reference",
             "paths": ["BEST/bench.json"]},
        ],
        "created_at": "2026-04-20T00:00:00+00:00",
    })

    bundle = load_continuation_bundle(
        task_dir=cont, experiment_dir=tmp_path / exp
    )

    assert any(e.source_task == "001-a" for e in bundle.primary_materials)
    assert bundle.reference_paths[0].source_task == "002-b"


def test_missing_from_task_rejected(tmp_path: Path) -> None:
    exp = "exp_aaaaaaaa"
    cont = _mk_task_dir(tmp_path, exp, "002-x")
    _write_task_json(cont, {
        "task_id": "002-x",
        "experiment_id": exp,
        "task_number": 2,
        "mode": "continuation",
        "user_feedback": "fb",
        "inputs": [
            {"from_task": "001-missing", "role": "primary", "bundle": "BEST/"}
        ],
        "created_at": "2026-04-20T00:00:00+00:00",
    })
    with pytest.raises(ContinuationInputError, match="not found"):
        load_continuation_bundle(task_dir=cont, experiment_dir=tmp_path / exp)


def test_from_task_without_best_rejected(tmp_path: Path) -> None:
    exp = "exp_aaaaaaaa"
    parent = _mk_task_dir(tmp_path, exp, "001-seed")
    # No BEST/ — task never completed
    cont = _mk_task_dir(tmp_path, exp, "002-x")
    _write_task_json(cont, {
        "task_id": "002-x",
        "experiment_id": exp,
        "task_number": 2,
        "mode": "continuation",
        "user_feedback": "fb",
        "inputs": [
            {"from_task": "001-seed", "role": "primary", "bundle": "BEST/"}
        ],
        "created_at": "2026-04-20T00:00:00+00:00",
    })
    with pytest.raises(ContinuationInputError, match="BEST"):
        load_continuation_bundle(task_dir=cont, experiment_dir=tmp_path / exp)


def test_seed_task_raises(tmp_path: Path) -> None:
    """Loader is only valid for continuation tasks."""
    exp = "exp_aaaaaaaa"
    cont = _mk_task_dir(tmp_path, exp, "001-s")
    _write_task_json(cont, {
        "task_id": "001-s",
        "experiment_id": exp,
        "task_number": 1,
        "mode": "seed",
        "user_prompt": "p",
        "inputs": [],
        "created_at": "2026-04-20T00:00:00+00:00",
    })
    with pytest.raises(ContinuationInputError, match="not a continuation"):
        load_continuation_bundle(task_dir=cont, experiment_dir=tmp_path / exp)
