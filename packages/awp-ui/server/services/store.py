"""SQLite persistence layer for AWP UI runs and events."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

import aiosqlite

logger = logging.getLogger(__name__)

_DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "awp_ui.db"

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS runs (
    id          TEXT PRIMARY KEY,
    task        TEXT NOT NULL,
    model       TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'pending',
    config_json TEXT NOT NULL DEFAULT '{}',
    result_json TEXT,
    created_at  TEXT NOT NULL,
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS events (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id    TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    seq       INTEGER NOT NULL,
    type      TEXT NOT NULL,
    data_json TEXT NOT NULL DEFAULT '{}',
    timestamp TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_events_run_id ON events(run_id);
CREATE INDEX IF NOT EXISTS idx_runs_status ON runs(status);
CREATE INDEX IF NOT EXISTS idx_runs_created ON runs(created_at);
"""


class StoreService:
    """Async SQLite store for run history and events."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        self._db_path = str(db_path or _DEFAULT_DB_PATH)
        self._db: aiosqlite.Connection | None = None

    async def init_db(self) -> None:
        """Create tables if they do not exist and open a persistent connection."""
        db_file = Path(self._db_path)
        db_file.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self._db_path)
        self._db.row_factory = aiosqlite.Row
        await self._db.executescript(_SCHEMA_SQL)
        await self._db.commit()
        logger.info("SQLite database initialized at %s", self._db_path)

    async def close(self) -> None:
        """Close the database connection."""
        if self._db:
            await self._db.close()
            self._db = None

    @property
    def db(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError("StoreService not initialized. Call init_db() first.")
        return self._db

    # ------------------------------------------------------------------
    # Runs
    # ------------------------------------------------------------------

    async def save_run(
        self,
        run_id: str,
        task: str,
        model: str,
        config: dict[str, Any],
        status: str = "pending",
    ) -> None:
        """Insert a new run record."""
        now = datetime.utcnow().isoformat()
        await self.db.execute(
            "INSERT INTO runs (id, task, model, status, config_json, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (run_id, task, model, status, json.dumps(config, default=str), now),
        )
        await self.db.commit()

    async def update_run(
        self,
        run_id: str,
        *,
        status: str | None = None,
        result: dict[str, Any] | None = None,
        completed_at: str | None = None,
    ) -> None:
        """Update mutable fields on a run."""
        parts: list[str] = []
        params: list[Any] = []
        if status is not None:
            parts.append("status = ?")
            params.append(status)
        if result is not None:
            parts.append("result_json = ?")
            params.append(json.dumps(result, default=str))
        if completed_at is not None:
            parts.append("completed_at = ?")
            params.append(completed_at)
        if not parts:
            return
        params.append(run_id)
        sql = f"UPDATE runs SET {', '.join(parts)} WHERE id = ?"
        await self.db.execute(sql, params)
        await self.db.commit()

    async def get_run(self, run_id: str) -> dict[str, Any] | None:
        """Fetch a single run by ID."""
        cursor = await self.db.execute("SELECT * FROM runs WHERE id = ?", (run_id,))
        row = await cursor.fetchone()
        if row is None:
            return None
        return self._row_to_run(row)

    async def list_runs(
        self, limit: int = 50, offset: int = 0
    ) -> list[dict[str, Any]]:
        """List runs ordered by creation time descending."""
        cursor = await self.db.execute(
            "SELECT * FROM runs ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        )
        rows = await cursor.fetchall()
        return [self._row_to_run(r) for r in rows]

    async def delete_run(self, run_id: str) -> bool:
        """Delete a run and its events. Returns True if a row was deleted."""
        await self.db.execute("DELETE FROM events WHERE run_id = ?", (run_id,))
        cursor = await self.db.execute("DELETE FROM runs WHERE id = ?", (run_id,))
        await self.db.commit()
        return cursor.rowcount > 0

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    async def save_event(
        self,
        run_id: str,
        seq: int,
        event_type: str,
        data: dict[str, Any],
        timestamp: str | None = None,
    ) -> None:
        """Persist a single event."""
        ts = timestamp or datetime.utcnow().isoformat()
        await self.db.execute(
            "INSERT INTO events (run_id, seq, type, data_json, timestamp) "
            "VALUES (?, ?, ?, ?, ?)",
            (run_id, seq, event_type, json.dumps(data, default=str), ts),
        )
        await self.db.commit()

    async def get_events(
        self, run_id: str, since_seq: int = 0
    ) -> list[dict[str, Any]]:
        """Fetch events for a run, optionally after a sequence number."""
        cursor = await self.db.execute(
            "SELECT * FROM events WHERE run_id = ? AND seq >= ? ORDER BY seq",
            (run_id, since_seq),
        )
        rows = await cursor.fetchall()
        return [self._row_to_event(r) for r in rows]

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_run(row: aiosqlite.Row) -> dict[str, Any]:
        return {
            "run_id": row["id"],
            "task": row["task"],
            "model": row["model"],
            "status": row["status"],
            "config": json.loads(row["config_json"]) if row["config_json"] else {},
            "result": json.loads(row["result_json"]) if row["result_json"] else None,
            "created_at": row["created_at"],
            "completed_at": row["completed_at"],
        }

    @staticmethod
    def _row_to_event(row: aiosqlite.Row) -> dict[str, Any]:
        return {
            "run_id": row["run_id"],
            "seq": row["seq"],
            "type": row["type"],
            "data": json.loads(row["data_json"]) if row["data_json"] else {},
            "timestamp": row["timestamp"],
        }
