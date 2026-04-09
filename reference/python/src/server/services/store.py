"""SQLite persistence layer for AWP UI runs and events."""

from __future__ import annotations

import base64
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiosqlite

logger = logging.getLogger(__name__)

_DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "awp_ui.db"


def _extract_result_answer(result_data: Any) -> str:
    """Extract a human-readable answer from a run result dict.

    Handles nested structures like:
      {"status": "complete", "result": {"delegation_loop": {"answer": "..."}}}
    Falls back to str(result_data) if no answer field is found.
    """
    if not isinstance(result_data, dict):
        return str(result_data) if result_data else ""

    # Direct answer key
    if "answer" in result_data:
        return str(result_data["answer"])

    # Nested: result.delegation_loop.answer (common pattern)
    inner = result_data.get("result", {})
    if isinstance(inner, dict):
        dl = inner.get("delegation_loop", {})
        if isinstance(dl, dict):
            if "answer" in dl:
                return str(dl["answer"])
            # Fallback: final_result
            fr = dl.get("final_result", {})
            if isinstance(fr, dict) and "answer" in fr:
                return str(fr["answer"])

    return str(result_data)

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

CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    hypothesis TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'draft',
    tags TEXT NOT NULL DEFAULT '[]',
    base_dir TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    settings_json TEXT DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS experiment_memory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    run_id TEXT,
    type TEXT NOT NULL DEFAULT 'note',
    content TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'user',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_experiment_memory_session ON experiment_memory(session_id);

CREATE TABLE IF NOT EXISTS session_runs (
    session_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    position INTEGER NOT NULL,
    PRIMARY KEY (session_id, run_id),
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE,
    FOREIGN KEY (run_id) REFERENCES runs(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS secrets (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY DEFAULT 'global',
    data_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_sessions_updated ON sessions(updated_at);
CREATE INDEX IF NOT EXISTS idx_session_runs_session ON session_runs(session_id);
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
        # Migrate existing sessions table to add experiment columns
        await self._migrate_sessions()
        logger.info("SQLite database initialized at %s", self._db_path)

    async def _migrate_sessions(self) -> None:
        """Add experiment columns to existing sessions table if missing."""
        migrations = [
            ("sessions", "description", "TEXT NOT NULL DEFAULT ''"),
            ("sessions", "hypothesis", "TEXT NOT NULL DEFAULT ''"),
            ("sessions", "status", "TEXT NOT NULL DEFAULT 'draft'"),
            ("sessions", "tags", "TEXT NOT NULL DEFAULT '[]'"),
            ("sessions", "base_dir", "TEXT"),
        ]
        for table, column, col_type in migrations:
            try:
                await self.db.execute(
                    f"ALTER TABLE {table} ADD COLUMN {column} {col_type}"
                )
            except Exception:
                pass  # Column already exists
        await self.db.commit()

    async def cleanup_orphan_runs(self) -> int:
        """Mark runs left in 'running' state by a dead process as 'interrupted'.

        When the server is restarted (auto-reload, crash, manual stop) while a
        run is active, the background thread dies and `_persist_result` never
        runs — leaving the row stuck on status='running'. The sidebar then
        shows a permanently pulsing blue dot for those experiments.

        E2E tests running in a **separate process** write a PID lock file
        (``data/run_locks/{run_id}.pid``) while active.  This method checks
        those files and only marks a run as interrupted if no live process
        owns it.  This prevents the server from killing live E2E runs on
        restart.

        Returns the number of rows fixed.
        """
        import os as _os

        lock_dir = Path(self._db_path).parent / "run_locks"
        now = datetime.now(tz=timezone.utc).isoformat()

        cursor = await self.db.execute(
            "SELECT id FROM runs WHERE status = 'running' AND completed_at IS NULL"
        )
        rows = await cursor.fetchall()

        fixed = 0
        for row in rows:
            run_id = row["id"]
            pid_file = lock_dir / f"{run_id}.pid"

            # Check if an external process still owns this run
            if pid_file.is_file():
                try:
                    pid = int(pid_file.read_text(encoding="utf-8").strip())
                    _os.kill(pid, 0)  # signal 0 = existence check
                    # Process is alive — skip this run
                    logger.info(
                        "Run %s owned by live process %d — keeping 'running'",
                        run_id, pid,
                    )
                    continue
                except (ValueError, ProcessLookupError, PermissionError, OSError):
                    # PID file is stale — process is dead
                    try:
                        pid_file.unlink(missing_ok=True)
                    except OSError:
                        pass

            # No live owner — mark as interrupted
            await self.db.execute(
                "UPDATE runs SET status = 'interrupted', completed_at = ? "
                "WHERE id = ?",
                (now, run_id),
            )
            fixed += 1

        if fixed:
            await self.db.commit()
            logger.info("Cleaned up %d orphan 'running' run(s) on startup", fixed)

        return fixed

    async def reconcile_session_status(self) -> int:
        """Derive session status from linked runs and fix inconsistencies.

        A session whose **all** runs have finished (complete/failed/interrupted/
        partial/…) but whose own status is still ``running`` is updated to
        reflect the actual outcome.  This handles the case where a process
        died without calling ``finalize_experiment``.

        Returns the number of sessions fixed.
        """
        # Sessions still marked as running
        cursor = await self.db.execute(
            "SELECT id FROM sessions WHERE status = 'running'"
        )
        sessions = await cursor.fetchall()

        fixed = 0
        for sess in sessions:
            sid = sess["id"]
            # Check if any run in this session is still running
            cur = await self.db.execute(
                "SELECT r.status FROM runs r "
                "JOIN session_runs sr ON sr.run_id = r.id "
                "WHERE sr.session_id = ?",
                (sid,),
            )
            run_rows = await cur.fetchall()
            statuses = [r["status"] for r in run_rows]

            if not statuses:
                # No runs at all — mark as draft
                await self.db.execute(
                    "UPDATE sessions SET status = 'draft', updated_at = ? "
                    "WHERE id = ?",
                    (datetime.now(tz=timezone.utc).isoformat(), sid),
                )
                fixed += 1
                continue

            if "running" in statuses or "pending" in statuses:
                # At least one run is still active — leave as running
                continue

            # All runs finished — pick the "best" terminal status
            if "complete" in statuses:
                new_status = "complete"
            elif "partial" in statuses:
                new_status = "partial"
            else:
                new_status = "failed"

            await self.db.execute(
                "UPDATE sessions SET status = ?, updated_at = ? WHERE id = ?",
                (new_status, datetime.now(tz=timezone.utc).isoformat(), sid),
            )
            fixed += 1
            logger.info(
                "Reconciled session %s: running → %s (runs: %s)",
                sid, new_status, statuses,
            )

        if fixed:
            await self.db.commit()
        return fixed

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
    # Sessions
    # ------------------------------------------------------------------

    async def create_session(
        self,
        session_id: str,
        title: str,
        description: str = "",
        hypothesis: str = "",
        tags: list[str] | None = None,
        base_dir: str | None = None,
    ) -> None:
        """Insert a new session/experiment record."""
        now = datetime.now(tz=timezone.utc).isoformat()
        await self.db.execute(
            "INSERT INTO sessions (id, title, description, hypothesis, status, tags, base_dir, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, 'draft', ?, ?, ?, ?)",
            (session_id, title, description, hypothesis, json.dumps(tags or []), base_dir, now, now),
        )
        await self.db.commit()

    async def update_session(
        self,
        session_id: str,
        title: str | None = None,
        description: str | None = None,
        hypothesis: str | None = None,
        status: str | None = None,
        tags: list[str] | None = None,
        base_dir: str | None = None,
        settings: dict[str, Any] | None = None,
    ) -> None:
        """Update mutable fields on a session/experiment."""
        parts: list[str] = []
        params: list[Any] = []
        if title is not None:
            parts.append("title = ?")
            params.append(title)
        if description is not None:
            parts.append("description = ?")
            params.append(description)
        if hypothesis is not None:
            parts.append("hypothesis = ?")
            params.append(hypothesis)
        if status is not None:
            parts.append("status = ?")
            params.append(status)
        if tags is not None:
            parts.append("tags = ?")
            params.append(json.dumps(tags))
        if base_dir is not None:
            parts.append("base_dir = ?")
            params.append(base_dir)
        if settings is not None:
            parts.append("settings_json = ?")
            params.append(json.dumps(settings, default=str))
        if not parts:
            return
        parts.append("updated_at = ?")
        params.append(datetime.now(tz=timezone.utc).isoformat())
        params.append(session_id)
        sql = f"UPDATE sessions SET {', '.join(parts)} WHERE id = ?"
        await self.db.execute(sql, params)
        await self.db.commit()

    async def get_session(self, session_id: str) -> dict[str, Any] | None:
        """Fetch a single session/experiment by ID, including run count and last run status."""
        cursor = await self.db.execute(
            "SELECT s.*, "
            "  (SELECT COUNT(*) FROM session_runs sr WHERE sr.session_id = s.id) AS run_count, "
            "  (SELECT r.status FROM session_runs sr "
            "   JOIN runs r ON r.id = sr.run_id "
            "   WHERE sr.session_id = s.id "
            "   ORDER BY sr.position DESC LIMIT 1) AS last_run_status "
            "FROM sessions s WHERE s.id = ?",
            (session_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return self._row_to_session(row)

    async def list_sessions(self, limit: int = 50) -> list[dict[str, Any]]:
        """List sessions/experiments ordered by updated_at descending."""
        cursor = await self.db.execute(
            "SELECT s.*, "
            "  (SELECT COUNT(*) FROM session_runs sr WHERE sr.session_id = s.id) AS run_count, "
            "  (SELECT r.status FROM session_runs sr "
            "   JOIN runs r ON r.id = sr.run_id "
            "   WHERE sr.session_id = s.id "
            "   ORDER BY sr.position DESC LIMIT 1) AS last_run_status "
            "FROM sessions s ORDER BY s.updated_at DESC LIMIT ?",
            (limit,),
        )
        rows = await cursor.fetchall()
        return [self._row_to_session(r) for r in rows]

    async def delete_session(self, session_id: str) -> bool:
        """Delete a session and its session_runs links. Returns True if deleted."""
        await self.db.execute(
            "DELETE FROM session_runs WHERE session_id = ?", (session_id,)
        )
        cursor = await self.db.execute(
            "DELETE FROM sessions WHERE id = ?", (session_id,)
        )
        await self.db.commit()
        return cursor.rowcount > 0

    async def add_run_to_session(self, session_id: str, run_id: str) -> None:
        """Link a run to a session, appending it at the end."""
        cursor = await self.db.execute(
            "SELECT COALESCE(MAX(position), -1) + 1 FROM session_runs "
            "WHERE session_id = ?",
            (session_id,),
        )
        row = await cursor.fetchone()
        next_pos = row[0] if row else 0
        await self.db.execute(
            "INSERT OR IGNORE INTO session_runs (session_id, run_id, position) "
            "VALUES (?, ?, ?)",
            (session_id, run_id, next_pos),
        )
        # Touch the session updated_at
        await self.db.execute(
            "UPDATE sessions SET updated_at = ? WHERE id = ?",
            (datetime.now(tz=timezone.utc).isoformat(), session_id),
        )
        await self.db.commit()

    async def get_session_runs(self, session_id: str) -> list[dict[str, Any]]:
        """Return runs belonging to a session, ordered by position."""
        cursor = await self.db.execute(
            "SELECT r.* FROM runs r "
            "JOIN session_runs sr ON sr.run_id = r.id "
            "WHERE sr.session_id = ? ORDER BY sr.position",
            (session_id,),
        )
        rows = await cursor.fetchall()
        return [self._row_to_run(r) for r in rows]

    async def get_session_history(self, session_id: str) -> list[dict[str, Any]]:
        """Return a chat-like history for a session: tasks and results in order."""
        runs = await self.get_session_runs(session_id)
        history: list[dict[str, Any]] = []
        for run in runs:
            # User message (the task)
            history.append({
                "role": "user",
                "content": run["task"],
                "run_id": run["run_id"],
                "timestamp": run["created_at"],
            })
            # Assistant message (the result)
            result_content = ""
            if run.get("result"):
                result_content = _extract_result_answer(run["result"])
            history.append({
                "role": "assistant",
                "content": result_content,
                "run_id": run["run_id"],
                "timestamp": run.get("completed_at") or run["created_at"],
            })
        return history

    # ------------------------------------------------------------------
    # Experiment Memory
    # ------------------------------------------------------------------

    async def save_memory_entry(
        self,
        session_id: str,
        content: str,
        entry_type: str = "note",
        source: str = "user",
        run_id: str | None = None,
    ) -> dict[str, Any]:
        """Insert a new experiment memory entry and return it."""
        now = datetime.now(tz=timezone.utc).isoformat()
        cursor = await self.db.execute(
            "INSERT INTO experiment_memory (session_id, run_id, type, content, source, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (session_id, run_id, entry_type, content, source, now, now),
        )
        await self.db.commit()
        return {
            "id": cursor.lastrowid,
            "session_id": session_id,
            "run_id": run_id,
            "type": entry_type,
            "content": content,
            "source": source,
            "created_at": now,
            "updated_at": now,
        }

    async def get_memory_entries(self, session_id: str) -> list[dict[str, Any]]:
        """List all memory entries for an experiment, newest first."""
        cursor = await self.db.execute(
            "SELECT * FROM experiment_memory WHERE session_id = ? ORDER BY created_at DESC",
            (session_id,),
        )
        rows = await cursor.fetchall()
        return [
            {
                "id": r["id"],
                "session_id": r["session_id"],
                "run_id": r["run_id"],
                "type": r["type"],
                "content": r["content"],
                "source": r["source"],
                "created_at": r["created_at"],
                "updated_at": r["updated_at"],
            }
            for r in rows
        ]

    async def update_memory_entry(self, memory_id: int, content: str) -> bool:
        """Update a memory entry's content. Returns True if updated."""
        now = datetime.now(tz=timezone.utc).isoformat()
        cursor = await self.db.execute(
            "UPDATE experiment_memory SET content = ?, updated_at = ? WHERE id = ?",
            (content, now, memory_id),
        )
        await self.db.commit()
        return cursor.rowcount > 0

    async def delete_memory_entry(self, memory_id: int) -> bool:
        """Delete a memory entry. Returns True if deleted."""
        cursor = await self.db.execute(
            "DELETE FROM experiment_memory WHERE id = ?", (memory_id,)
        )
        await self.db.commit()
        return cursor.rowcount > 0

    # ------------------------------------------------------------------
    # Secrets
    # ------------------------------------------------------------------

    async def save_secret(self, key: str, value: str) -> None:
        """Store a secret. Value is base64-obfuscated for local use."""
        now = datetime.now(tz=timezone.utc).isoformat()
        encoded = base64.b64encode(value.encode("utf-8")).decode("utf-8")
        await self.db.execute(
            "INSERT INTO secrets (key, value, created_at, updated_at) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = ?, updated_at = ?",
            (key, encoded, now, now, encoded, now),
        )
        await self.db.commit()

    async def get_secret(self, key: str) -> str | None:
        """Retrieve a secret value (decoded)."""
        cursor = await self.db.execute(
            "SELECT value FROM secrets WHERE key = ?", (key,)
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return base64.b64decode(row["value"].encode("utf-8")).decode("utf-8")

    async def list_secrets(self) -> list[str]:
        """Return all secret keys (values are never exposed)."""
        cursor = await self.db.execute(
            "SELECT key, created_at, updated_at FROM secrets ORDER BY key"
        )
        rows = await cursor.fetchall()
        return [row["key"] for row in rows]

    async def list_secrets_metadata(self) -> list[dict[str, str]]:
        """Return secret keys with timestamps (values are never exposed)."""
        cursor = await self.db.execute(
            "SELECT key, created_at, updated_at FROM secrets ORDER BY key"
        )
        rows = await cursor.fetchall()
        return [
            {"key": r["key"], "created_at": r["created_at"], "updated_at": r["updated_at"]}
            for r in rows
        ]

    async def delete_secret(self, key: str) -> bool:
        """Delete a secret by key. Returns True if deleted."""
        cursor = await self.db.execute(
            "DELETE FROM secrets WHERE key = ?", (key,)
        )
        await self.db.commit()
        return cursor.rowcount > 0

    # ------------------------------------------------------------------
    # Settings persistence
    # ------------------------------------------------------------------

    async def save_settings(self, data: dict[str, Any]) -> None:
        """Persist global settings to the database."""
        now = datetime.now(tz=timezone.utc).isoformat()
        data_json = json.dumps(data, default=str)
        await self.db.execute(
            "INSERT INTO settings (key, data_json, updated_at) "
            "VALUES ('global', ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET data_json = ?, updated_at = ?",
            (data_json, now, data_json, now),
        )
        await self.db.commit()

    async def get_settings(self) -> dict[str, Any] | None:
        """Load persisted global settings."""
        cursor = await self.db.execute(
            "SELECT data_json FROM settings WHERE key = 'global'"
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return json.loads(row["data_json"])

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

    @staticmethod
    def _row_to_session(row: aiosqlite.Row) -> dict[str, Any]:
        tags_raw = row["tags"] if "tags" in row.keys() else "[]"
        return {
            "id": row["id"],
            "title": row["title"],
            "description": row["description"] if "description" in row.keys() else "",
            "hypothesis": row["hypothesis"] if "hypothesis" in row.keys() else "",
            "status": row["status"] if "status" in row.keys() else "draft",
            "tags": json.loads(tags_raw) if tags_raw else [],
            "base_dir": row["base_dir"] if "base_dir" in row.keys() else None,
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "settings": json.loads(row["settings_json"]) if row["settings_json"] else {},
            "run_count": row["run_count"] if "run_count" in row.keys() else 0,
            "last_run_status": row["last_run_status"] if "last_run_status" in row.keys() else None,
        }
