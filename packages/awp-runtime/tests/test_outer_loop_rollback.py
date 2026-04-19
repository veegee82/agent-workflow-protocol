"""Edge-case tests for :meth:`ArtifactRegistry.rollback_to` (Phase A3).

Rollback semantics:

* ``rollback_to(name, 0)`` clears the DB active pointer → subsequent
  reads serve the synthetic v0 default.
* ``rollback_to(name, v)`` for any stored version flips ``is_active``.
* ``rollback_to(name, v)`` for an unknown version raises :class:`KeyError`.
* Rolling back before any version has been written (DB-backed) → v0.
* Rolling back against a read-only registry (no DB) raises
  :class:`RuntimeError`.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from awp.outer_loop import ArtifactRegistry

ARTIFACT = "worker_pitfalls"


def _fresh(tmp_path: Path) -> ArtifactRegistry:
    return ArtifactRegistry(db_path=str(tmp_path / "outer_loop.db"))


def test_rollback_to_v0_clears_active(tmp_path) -> None:
    reg = _fresh(tmp_path)
    v1 = reg.put_version(ARTIFACT, "content v1", parent_version=0)
    reg.set_active(ARTIFACT, v1.version)
    assert reg.get_active(ARTIFACT).version == 1
    reg.rollback_to(ARTIFACT, 0)
    # Active reverts to synthetic v0 default (not pointing at DB row).
    active = reg.get_active(ARTIFACT)
    assert active.version == 0
    assert active.created_at == "1970-01-01T00:00:00Z"


def test_rollback_to_ancestor(tmp_path) -> None:
    reg = _fresh(tmp_path)
    v1 = reg.put_version(ARTIFACT, "c1", parent_version=0)
    reg.set_active(ARTIFACT, v1.version)
    v2 = reg.put_version(ARTIFACT, "c2", parent_version=v1.version)
    reg.set_active(ARTIFACT, v2.version)
    assert reg.get_active(ARTIFACT).version == 2
    reg.rollback_to(ARTIFACT, v1.version)
    assert reg.get_active(ARTIFACT).version == 1
    # Version 2 is still on disk — it can be rolled FORWARD to again.
    versions = [v.version for v in reg.list_versions(ARTIFACT)]
    assert versions == [0, 1, 2]


def test_rollback_to_nonexistent_version_raises(tmp_path) -> None:
    reg = _fresh(tmp_path)
    with pytest.raises(KeyError):
        reg.rollback_to(ARTIFACT, 99)


def test_rollback_unknown_artifact_raises(tmp_path) -> None:
    reg = _fresh(tmp_path)
    with pytest.raises(KeyError):
        reg.rollback_to("not_a_real_artifact", 0)


def test_rollback_without_db_raises(tmp_path) -> None:
    reg = ArtifactRegistry(db_path=None)  # read-only
    with pytest.raises(RuntimeError):
        reg.rollback_to(ARTIFACT, 0)


def test_rollback_when_no_versions_yet_works(tmp_path) -> None:
    """Rolling back to v0 on a fresh DB is a no-op (always legal)."""
    reg = _fresh(tmp_path)
    reg.rollback_to(ARTIFACT, 0)
    assert reg.get_active(ARTIFACT).version == 0
