"""Unit tests for iteration workspace preparation."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from awp.refinement.seed import prepare_iteration_workspace


def test_prepare_workspace_creates_input_from_prior_final(tmp_path: Path) -> None:
    prior_final = tmp_path / "seed" / "FINAL"
    prior_final.mkdir(parents=True)
    (prior_final / "paper.md").write_text("# Paper\n", encoding="utf-8")
    (prior_final / "nested").mkdir()
    (prior_final / "nested" / "data.json").write_text("{}", encoding="utf-8")

    workspace = tmp_path / "iter_1"
    prepare_iteration_workspace(workspace_dir=workspace, prior_final_dir=prior_final)

    assert (workspace / "input" / "paper.md").read_text(encoding="utf-8") == "# Paper\n"
    assert (workspace / "input" / "nested" / "data.json").exists()


def test_prepare_workspace_falls_back_to_copy_on_crossdevice(tmp_path: Path) -> None:
    prior_final = tmp_path / "seed" / "FINAL"
    prior_final.mkdir(parents=True)
    (prior_final / "a.txt").write_text("a", encoding="utf-8")

    workspace = tmp_path / "iter_1"

    def fake_link(src, dst, *args, **kwargs):
        raise OSError(18, "Invalid cross-device link")

    with patch("awp.refinement.seed.os.link", side_effect=fake_link):
        prepare_iteration_workspace(workspace_dir=workspace, prior_final_dir=prior_final)

    assert (workspace / "input" / "a.txt").read_text(encoding="utf-8") == "a"


def test_prepare_workspace_raises_when_prior_final_missing(tmp_path: Path) -> None:
    workspace = tmp_path / "iter_1"
    with pytest.raises(FileNotFoundError):
        prepare_iteration_workspace(
            workspace_dir=workspace,
            prior_final_dir=tmp_path / "nonexistent",
        )


def test_prepare_workspace_refuses_nonempty_target(tmp_path: Path) -> None:
    prior_final = tmp_path / "seed" / "FINAL"
    prior_final.mkdir(parents=True)
    (prior_final / "a.txt").write_text("a", encoding="utf-8")

    workspace = tmp_path / "iter_1"
    (workspace / "input").mkdir(parents=True)
    (workspace / "input" / "stale.txt").write_text("old", encoding="utf-8")

    with pytest.raises(FileExistsError):
        prepare_iteration_workspace(workspace_dir=workspace, prior_final_dir=prior_final)
