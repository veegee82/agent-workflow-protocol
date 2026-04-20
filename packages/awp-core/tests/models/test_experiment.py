"""Tests for ExperimentManifest."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from awp.models.experiment import ExperimentManifest


def test_new_assigns_id_and_timestamp() -> None:
    manifest = ExperimentManifest.new(name="AWP Paper", goal="A paper for publication")
    assert manifest.name == "AWP Paper"
    assert manifest.goal == "A paper for publication"
    assert manifest.experiment_id.startswith("exp_")
    assert len(manifest.experiment_id) == len("exp_") + 8
    assert manifest.created_at.endswith("+00:00")
    assert manifest.task_order == []


def test_new_honours_explicit_id() -> None:
    manifest = ExperimentManifest.new(name="X", experiment_id="exp_custom1")
    assert manifest.experiment_id == "exp_custom1"


def test_empty_name_rejected() -> None:
    with pytest.raises(ValidationError):
        ExperimentManifest(
            experiment_id="exp_aaaaaaaa",
            name="",
            goal="",
            created_at="2026-04-20T00:00:00+00:00",
            task_order=[],
        )


def test_roundtrip_json() -> None:
    manifest = ExperimentManifest.new(name="T", goal="G")
    manifest.task_order.append("001-task")
    restored = ExperimentManifest.model_validate_json(manifest.model_dump_json())
    assert restored == manifest
