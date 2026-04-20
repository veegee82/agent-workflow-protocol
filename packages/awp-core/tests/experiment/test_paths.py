"""Tests for experiment path helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from awp.experiment.paths import (
    EXPERIMENTS_ROOT,
    experiment_dir,
    slug_from_prompt,
    task_dir,
    task_id_for,
)


def test_experiments_root_default() -> None:
    assert EXPERIMENTS_ROOT == Path("/tmp/awp-experiments")


def test_experiment_dir() -> None:
    assert experiment_dir("exp_aaaaaaaa") == Path("/tmp/awp-experiments/exp_aaaaaaaa")


def test_task_dir() -> None:
    assert task_dir("exp_aaaaaaaa", "001-draft") == Path(
        "/tmp/awp-experiments/exp_aaaaaaaa/tasks/001-draft"
    )


def test_slug_from_prompt_ascii() -> None:
    assert slug_from_prompt("Write a Paper About AWP!") == "write-a-paper-about-awp"


def test_slug_from_prompt_truncates() -> None:
    slug = slug_from_prompt("a" * 200)
    assert len(slug) <= 50
    assert slug == "a" * 50


def test_slug_from_prompt_empty_fallback() -> None:
    assert slug_from_prompt("") == "task"
    assert slug_from_prompt("!!!") == "task"


@pytest.mark.parametrize(
    "number,slug,expected",
    [
        (1, "draft", "001-draft"),
        (42, "improve-sec3", "042-improve-sec3"),
        (999, "last", "999-last"),
    ],
)
def test_task_id_for(number: int, slug: str, expected: str) -> None:
    assert task_id_for(number, slug) == expected


def test_task_id_for_rejects_overflow() -> None:
    with pytest.raises(ValueError):
        task_id_for(1000, "x")
