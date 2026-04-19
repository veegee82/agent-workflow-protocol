"""SQLite persistence backend for the outer-loop artifact registry.

The store owns the ``artifact_versions``, ``task_suites``, ``epochs`` and
``epoch_runs`` tables. Only ``artifact_versions`` is exercised in Phase A1;
the other tables are created up-front so later phases do not require a
migration.

The store is intentionally minimal and thread-safe: a single connection is
shared across threads and guarded by an internal lock. The DB is created on
first write; the parent directory is created (``mkdir -p``) if missing.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
from pathlib import Path
from typing import Optional

from .artifacts import ArtifactVersion

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS artifact_versions (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  artifact_name TEXT NOT NULL,
  version       INTEGER NOT NULL,
  content       TEXT NOT NULL,
  parent_version INTEGER,
  created_at    TEXT NOT NULL,
  epoch_id      TEXT,
  is_active     INTEGER NOT NULL DEFAULT 0,
  UNIQUE(artifact_name, version)
);
CREATE INDEX IF NOT EXISTS idx_art_name_active ON artifact_versions(artifact_name, is_active);

CREATE TABLE IF NOT EXISTS task_suites (
  id                 TEXT PRIMARY KEY,
  name               TEXT NOT NULL,
  tasks_json         TEXT NOT NULL,
  baseline_artifacts_json TEXT NOT NULL,
  created_at         TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS epochs (
  id                 TEXT PRIMARY KEY,
  suite_id           TEXT NOT NULL REFERENCES task_suites(id),
  epoch_num          INTEGER NOT NULL,
  started_at         TEXT NOT NULL,
  completed_at       TEXT,
  mean_loss          REAL,
  parent_artifacts_json TEXT NOT NULL,
  child_artifacts_json  TEXT
);

CREATE TABLE IF NOT EXISTS epoch_runs (
  epoch_id           TEXT NOT NULL REFERENCES epochs(id),
  run_id             TEXT NOT NULL,
  task_name          TEXT NOT NULL,
  loss               REAL,
  scores_json        TEXT,
  PRIMARY KEY (epoch_id, run_id)
);
"""


class SqliteArtifactStore:
    """Thin SQLite wrapper.

    Raises :class:`OSError` if the DB path's directory cannot be created or
    written to — the registry catches this and falls back to read-only mode.
    """

    def __init__(self, db_path: str) -> None:
        self._db_path = Path(db_path)
        # Ensure the parent directory exists and is writable; this is where
        # a filesystem error would surface (e.g. ~/.awp not writable).
        parent = self._db_path.parent
        parent.mkdir(parents=True, exist_ok=True)
        if not os.access(parent, os.W_OK):
            raise OSError(f"Directory {parent} is not writable")
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(
            str(self._db_path), check_same_thread=False, isolation_level=None
        )
        self._conn.row_factory = sqlite3.Row
        try:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.execute("PRAGMA busy_timeout=5000")
        except sqlite3.DatabaseError as e:
            logger.warning("WAL PRAGMAs failed, falling back to defaults: %s", e)
        with self._lock:
            self._conn.executescript(_SCHEMA)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_version(row: sqlite3.Row) -> ArtifactVersion:
        return ArtifactVersion(
            artifact_name=row["artifact_name"],
            version=row["version"],
            content=row["content"],
            parent_version=row["parent_version"],
            created_at=row["created_at"],
            epoch_id=row["epoch_id"],
        )

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get_version(self, name: str, version: int) -> Optional[ArtifactVersion]:
        with self._lock:
            cur = self._conn.execute(
                "SELECT * FROM artifact_versions WHERE artifact_name = ? AND version = ?",
                (name, version),
            )
            row = cur.fetchone()
        return self._row_to_version(row) if row else None

    def get_active(self, name: str) -> Optional[ArtifactVersion]:
        with self._lock:
            cur = self._conn.execute(
                "SELECT * FROM artifact_versions WHERE artifact_name = ? AND is_active = 1 LIMIT 1",
                (name,),
            )
            row = cur.fetchone()
        return self._row_to_version(row) if row else None

    def list_versions(self, name: str) -> list[ArtifactVersion]:
        with self._lock:
            cur = self._conn.execute(
                "SELECT * FROM artifact_versions WHERE artifact_name = ? ORDER BY version ASC",
                (name,),
            )
            rows = cur.fetchall()
        return [self._row_to_version(r) for r in rows]

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def _next_version(self, name: str) -> int:
        cur = self._conn.execute(
            "SELECT COALESCE(MAX(version), 0) AS mx FROM artifact_versions WHERE artifact_name = ?",
            (name,),
        )
        row = cur.fetchone()
        return int(row["mx"]) + 1

    def put_version(
        self,
        artifact_name: str,
        content: str,
        parent_version: Optional[int],
        created_at: str,
        epoch_id: Optional[str],
    ) -> ArtifactVersion:
        with self._lock:
            version = self._next_version(artifact_name)
            self._conn.execute(
                "INSERT INTO artifact_versions "
                "(artifact_name, version, content, parent_version, created_at, "
                "epoch_id, is_active) "
                "VALUES (?, ?, ?, ?, ?, ?, 0)",
                (artifact_name, version, content, parent_version, created_at, epoch_id),
            )
        return ArtifactVersion(
            artifact_name=artifact_name,
            version=version,
            content=content,
            parent_version=parent_version,
            created_at=created_at,
            epoch_id=epoch_id,
        )

    def set_active(self, name: str, version: int) -> None:
        with self._lock:
            # Ensure the target row exists before mutating active flags.
            cur = self._conn.execute(
                "SELECT 1 FROM artifact_versions WHERE artifact_name = ? AND version = ?",
                (name, version),
            )
            if cur.fetchone() is None:
                raise KeyError(f"Cannot activate {name!r} v{version}: version not found")
            self._conn.execute(
                "UPDATE artifact_versions SET is_active = 0 WHERE artifact_name = ?",
                (name,),
            )
            self._conn.execute(
                "UPDATE artifact_versions SET is_active = 1 "
                "WHERE artifact_name = ? AND version = ?",
                (name, version),
            )

    def clear_active(self, name: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE artifact_versions SET is_active = 0 WHERE artifact_name = ?",
                (name,),
            )

    # ------------------------------------------------------------------
    # Suite / epoch / epoch_run write helpers (Phase A2)
    # ------------------------------------------------------------------
    #
    # The suite/epoch tables were declared in Phase A1 but only get written
    # to from Phase A2 onwards. The helpers below are intentionally thin
    # CRUD calls — the orchestration logic lives in
    # :class:`awp.outer_loop.runner.SuiteRunner`.

    def upsert_task_suite(
        self,
        suite_id: str,
        name: str,
        tasks_json: str,
        baseline_artifacts_json: str,
        created_at: str,
    ) -> None:
        """Insert or replace a ``task_suites`` row."""
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO task_suites "
                "(id, name, tasks_json, baseline_artifacts_json, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (suite_id, name, tasks_json, baseline_artifacts_json, created_at),
            )

    def insert_epoch(
        self,
        epoch_id: str,
        suite_id: str,
        epoch_num: int,
        started_at: str,
        parent_artifacts_json: str,
    ) -> None:
        """Insert a new ``epochs`` row at the start of an epoch run."""
        with self._lock:
            self._conn.execute(
                "INSERT INTO epochs "
                "(id, suite_id, epoch_num, started_at, completed_at, "
                "mean_loss, parent_artifacts_json, child_artifacts_json) "
                "VALUES (?, ?, ?, ?, NULL, NULL, ?, NULL)",
                (epoch_id, suite_id, epoch_num, started_at, parent_artifacts_json),
            )

    def finalize_epoch(
        self,
        epoch_id: str,
        completed_at: str,
        mean_loss: float | None,
        child_artifacts_json: str,
    ) -> None:
        """Mark an epoch as finished and persist its mean loss + child artifacts."""
        with self._lock:
            self._conn.execute(
                "UPDATE epochs SET completed_at = ?, mean_loss = ?, "
                "child_artifacts_json = ? WHERE id = ?",
                (completed_at, mean_loss, child_artifacts_json, epoch_id),
            )

    def insert_epoch_run(
        self,
        epoch_id: str,
        run_id: str,
        task_name: str,
        loss: float | None,
        scores_json: str,
    ) -> None:
        """Insert one ``epoch_runs`` row (one task → one run within an epoch)."""
        with self._lock:
            self._conn.execute(
                "INSERT INTO epoch_runs "
                "(epoch_id, run_id, task_name, loss, scores_json) "
                "VALUES (?, ?, ?, ?, ?)",
                (epoch_id, run_id, task_name, loss, scores_json),
            )

    # ------------------------------------------------------------------
    # Suite / epoch / epoch_run read helpers (Phase A2)
    # ------------------------------------------------------------------

    def get_task_suite(self, suite_id: str) -> dict | None:
        with self._lock:
            cur = self._conn.execute("SELECT * FROM task_suites WHERE id = ?", (suite_id,))
            row = cur.fetchone()
        return dict(row) if row else None

    def find_task_suite_by_name(self, name: str) -> dict | None:
        """Return the most recent suite row with the given name (or None)."""
        with self._lock:
            cur = self._conn.execute(
                "SELECT * FROM task_suites WHERE name = ? ORDER BY created_at DESC LIMIT 1",
                (name,),
            )
            row = cur.fetchone()
        return dict(row) if row else None

    def list_epochs(self, suite_id: str) -> list[dict]:
        with self._lock:
            cur = self._conn.execute(
                "SELECT * FROM epochs WHERE suite_id = ? ORDER BY epoch_num ASC, started_at ASC",
                (suite_id,),
            )
            rows = cur.fetchall()
        return [dict(r) for r in rows]

    def list_epoch_runs(self, epoch_id: str) -> list[dict]:
        with self._lock:
            cur = self._conn.execute(
                "SELECT * FROM epoch_runs WHERE epoch_id = ? ORDER BY task_name ASC",
                (epoch_id,),
            )
            rows = cur.fetchall()
        return [dict(r) for r in rows]

    def close(self) -> None:
        with self._lock:
            self._conn.close()
