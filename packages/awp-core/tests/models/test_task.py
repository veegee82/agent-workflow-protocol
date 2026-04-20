"""Tests for TaskManifest, including R37 enforcement."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from awp.models.task import InputRole, TaskInput, TaskManifest, TaskMode


def _valid_seed_kwargs(**overrides):
    base = dict(
        task_id="001-draft",
        experiment_id="exp_aaaaaaaa",
        task_number=1,
        mode=TaskMode.SEED,
        user_prompt="Write a paper",
        user_feedback=None,
        inputs=[],
        created_at="2026-04-20T00:00:00+00:00",
    )
    base.update(overrides)
    return base


def _valid_cont_kwargs(**overrides):
    base = dict(
        task_id="002-improve",
        experiment_id="exp_aaaaaaaa",
        task_number=2,
        mode=TaskMode.CONTINUATION,
        user_prompt=None,
        user_feedback="make section 3 deeper",
        inputs=[TaskInput(from_task="001-draft", role=InputRole.PRIMARY, bundle="BEST/")],
        created_at="2026-04-20T00:00:00+00:00",
    )
    base.update(overrides)
    return base


def test_seed_valid() -> None:
    manifest = TaskManifest(**_valid_seed_kwargs())
    assert manifest.mode == TaskMode.SEED
    assert manifest.inputs == []


def test_seed_rejects_user_feedback() -> None:
    with pytest.raises(ValidationError, match="must not have user_feedback"):
        TaskManifest(**_valid_seed_kwargs(user_feedback="x"))


def test_seed_rejects_inputs() -> None:
    with pytest.raises(ValidationError, match="must not have inputs"):
        TaskManifest(
            **_valid_seed_kwargs(
                inputs=[TaskInput(from_task="001-x", role=InputRole.PRIMARY, bundle="BEST/")]
            )
        )


def test_seed_requires_user_prompt() -> None:
    with pytest.raises(ValidationError, match="requires user_prompt"):
        TaskManifest(**_valid_seed_kwargs(user_prompt=None))


def test_continuation_valid() -> None:
    manifest = TaskManifest(**_valid_cont_kwargs())
    assert manifest.mode == TaskMode.CONTINUATION
    assert len(manifest.inputs) == 1


def test_continuation_r37_empty_inputs() -> None:
    with pytest.raises(ValidationError, match="R37"):
        TaskManifest(**_valid_cont_kwargs(inputs=[]))


def test_continuation_requires_user_feedback() -> None:
    with pytest.raises(ValidationError, match="requires user_feedback"):
        TaskManifest(**_valid_cont_kwargs(user_feedback=None))


def test_continuation_rejects_user_prompt() -> None:
    with pytest.raises(ValidationError, match="must not have user_prompt"):
        TaskManifest(**_valid_cont_kwargs(user_prompt="x"))


def test_task_input_requires_exactly_one_source() -> None:
    with pytest.raises(ValidationError, match="exactly one"):
        TaskInput(from_task="001", role=InputRole.PRIMARY)  # neither
    with pytest.raises(ValidationError, match="exactly one"):
        TaskInput(from_task="001", role=InputRole.PRIMARY, bundle="BEST/", paths=["a.md"])


def test_task_input_path_traversal_rejected() -> None:
    with pytest.raises(ValidationError, match="traversal"):
        TaskInput(from_task="001", role=InputRole.REFERENCE, paths=["../secrets.txt"])


def test_roundtrip_continuation_json() -> None:
    manifest = TaskManifest(**_valid_cont_kwargs())
    restored = TaskManifest.model_validate_json(manifest.model_dump_json())
    assert restored == manifest
