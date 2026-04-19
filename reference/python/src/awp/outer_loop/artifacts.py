"""Versioned prompt-artifact registry for the outer loop (A5).

Phase A1 introduces a single type — :class:`ArtifactRegistry` — that serves
named prompt artifacts by version. Version 0 is ALWAYS the hardcoded default
bundled under :mod:`awp.outer_loop.defaults`; it is synthetic and never
persisted. Versions >= 1 live in a SQLite database.

Design invariants:

* No import-time filesystem I/O. The SQLite database is opened lazily on
  the first call that requires it.
* If ``db_path`` is ``None`` or the containing directory is not writable,
  the registry operates in read-only v0 fallback mode and any write call
  raises :class:`RuntimeError`.
* The database is opened with ``check_same_thread=False`` and guarded by a
  lock so the registry is safe to share across the runtime's threads.
"""

from __future__ import annotations

import datetime as _dt
import threading
from dataclasses import dataclass
from typing import Optional

from .defaults import DEFAULTS


@dataclass(frozen=True)
class ArtifactVersion:
    """A single immutable version of a prompt artifact."""

    artifact_name: str
    version: int
    content: str
    parent_version: Optional[int]
    created_at: str
    epoch_id: Optional[str]


@dataclass(frozen=True)
class Artifact:
    """Lightweight descriptor for a registered artifact name."""

    name: str
    default_content: str


def _utcnow_iso() -> str:
    # Use timezone-aware UTC and format with 'Z' suffix (ISO 8601).
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class ArtifactRegistry:
    """Serves versioned prompt artifacts with a v0 fallback.

    The registry has two modes:

    * **Read-only fallback** (``db_path is None``) — only v0 defaults are
      served; any write call raises :class:`RuntimeError`.
    * **Read/write** (``db_path`` is a string path) — versions >= 1 live
      in SQLite. The DB is opened lazily on first access.
    """

    def __init__(self, db_path: Optional[str] = None) -> None:
        self._db_path = db_path
        self._lock = threading.Lock()
        self._store = None  # type: ignore[assignment]  # lazy

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def list_artifacts(self) -> list[str]:
        """Return the sorted list of registered artifact names."""
        return sorted(DEFAULTS.keys())

    def _default_version(self, name: str) -> ArtifactVersion:
        if name not in DEFAULTS:
            raise KeyError(f"Unknown artifact: {name!r}")
        return ArtifactVersion(
            artifact_name=name,
            version=0,
            content=DEFAULTS[name],
            parent_version=None,
            # v0 is synthetic; created_at is a fixed sentinel so callers can
            # distinguish it from a real DB row if they care.
            created_at="1970-01-01T00:00:00Z",
            epoch_id=None,
        )

    # ------------------------------------------------------------------
    # Store access (lazy)
    # ------------------------------------------------------------------

    def _get_store(self):
        """Open the SQLite store lazily. Returns ``None`` in fallback mode."""
        if self._db_path is None:
            return None
        if self._store is not None:
            return self._store
        with self._lock:
            if self._store is not None:
                return self._store
            # Import lazily so that ``import awp.outer_loop`` never touches
            # the filesystem.
            from .store import SqliteArtifactStore

            try:
                self._store = SqliteArtifactStore(self._db_path)
            except OSError:
                # Directory not writable or other filesystem failure → stay
                # in fallback mode, mark store as unavailable.
                self._store = None
                self._db_path = None
                return None
            return self._store

    # ------------------------------------------------------------------
    # Read API
    # ------------------------------------------------------------------

    def get(self, name: str, version: Optional[int] = None) -> ArtifactVersion:
        """Return a specific version, or the active version if ``version`` is None.

        ``version == 0`` always returns the synthetic v0 default.
        """
        if name not in DEFAULTS:
            raise KeyError(f"Unknown artifact: {name!r}")
        if version == 0:
            return self._default_version(name)
        if version is None:
            return self.get_active(name)
        store = self._get_store()
        if store is None:
            raise KeyError(f"Version {version} of {name!r} not available (no DB configured)")
        row = store.get_version(name, version)
        if row is None:
            raise KeyError(f"Version {version} of {name!r} not found")
        return row

    def get_active(self, name: str) -> ArtifactVersion:
        """Return the active version of ``name``, falling back to v0."""
        if name not in DEFAULTS:
            raise KeyError(f"Unknown artifact: {name!r}")
        store = self._get_store()
        if store is None:
            return self._default_version(name)
        row = store.get_active(name)
        if row is None:
            return self._default_version(name)
        return row

    def list_versions(self, name: str) -> list[ArtifactVersion]:
        """Return all versions (including synthetic v0) of ``name`` ordered ascending."""
        if name not in DEFAULTS:
            raise KeyError(f"Unknown artifact: {name!r}")
        versions: list[ArtifactVersion] = [self._default_version(name)]
        store = self._get_store()
        if store is not None:
            versions.extend(store.list_versions(name))
        return versions

    # ------------------------------------------------------------------
    # Write API
    # ------------------------------------------------------------------

    def _require_store(self):
        store = self._get_store()
        if store is None:
            raise RuntimeError(
                "ArtifactRegistry is in read-only fallback mode — writes require a DB path"
            )
        return store

    def put_version(
        self,
        name: str,
        content: str,
        parent_version: Optional[int],
        epoch_id: Optional[str] = None,
    ) -> ArtifactVersion:
        """Append a new version (>= 1). Returns the created version."""
        if name not in DEFAULTS:
            raise KeyError(f"Unknown artifact: {name!r}")
        store = self._require_store()
        created_at = _utcnow_iso()
        return store.put_version(
            artifact_name=name,
            content=content,
            parent_version=parent_version,
            created_at=created_at,
            epoch_id=epoch_id,
        )

    def set_active(self, name: str, version: int) -> None:
        """Mark ``version`` of ``name`` as the active version.

        ``version == 0`` is accepted as a shorthand for "clear any DB active
        row so v0 is served again" and is equivalent to :meth:`rollback_to`.
        """
        if name not in DEFAULTS:
            raise KeyError(f"Unknown artifact: {name!r}")
        if version == 0:
            self.rollback_to(name, 0)
            return
        store = self._require_store()
        store.set_active(name, version)

    def rollback_to(self, name: str, version: int) -> None:
        """Roll back the active pointer to ``version``.

        Passing ``0`` clears the DB active row; subsequent reads return the
        synthetic v0 default.
        """
        if name not in DEFAULTS:
            raise KeyError(f"Unknown artifact: {name!r}")
        store = self._require_store()
        if version == 0:
            store.clear_active(name)
        else:
            store.set_active(name, version)
