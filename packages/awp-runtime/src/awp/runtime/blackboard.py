"""Blackboard channel for sibling worker coordination.

This module provides a minimal, file-backed append-only message bus that
lets ephemeral workers spawned by the same manager signal each other
within a single delegation run.

The blackboard is deliberately narrow in scope:

* One blackboard instance per manager run (keyed by ``manager_run_id``).
* Backed by a single JSONL file at
  ``<workspace>/blackboard/<manager_run_id>.jsonl``.
* Append-only, process-safe via :func:`fcntl.flock` on POSIX.
* Submanagers get their OWN blackboard (different ``run_id``). Parents
  never see child signals, children never see parent signals.
* No cross-run leakage: the two builtin tools ``board.post`` and
  ``board.read`` are bound (via a contextvar) to the blackboard of the
  currently-executing manager run.

It is intentionally tiny: no topics DAG, no retention, no ACLs. Just a
fast append-and-tail log so sibling workers can broadcast partial
findings ("I already fetched X", "this path is a dead end") to the next
round of the manager loop.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from contextvars import ContextVar
from pathlib import Path
from typing import Any, Iterable, Optional

logger = logging.getLogger(__name__)

# fcntl is POSIX-only. On non-POSIX we fall back to a thread lock; the
# blackboard is still safe within one process.
try:
    import fcntl  # type: ignore

    _HAS_FCNTL = True
except ImportError:  # pragma: no cover - Windows fallback
    _HAS_FCNTL = False


# Current-run binding used by the ``board.post`` / ``board.read`` tools.
# The runner sets this for the duration of each manager run so the shared
# ToolRegistry instance can serve per-run Blackboards without mixing
# state between parallel sub-runs.
current_blackboard: ContextVar[Optional["Blackboard"]] = ContextVar(
    "current_blackboard", default=None
)


class Blackboard:
    """Append-only JSONL blackboard scoped to one manager run.

    Entries have the shape::

        {"id": "<ts>-<counter>", "ts": <float>, "topic": "<str>",
         "worker_id": "<str>", "payload": {...}}

    Entry ids are monotonic within a single process (``<ts>-<counter>``
    where counter increments per post). Across processes, the wall-clock
    ``ts`` prefix still yields a usable total order for ``since``
    filtering even if the counter resets.
    """

    def __init__(self, workspace: Path, manager_run_id: str) -> None:
        self._manager_run_id = manager_run_id
        self._dir = Path(workspace) / "blackboard"
        self._dir.mkdir(parents=True, exist_ok=True)
        self._path = self._dir / f"{manager_run_id}.jsonl"
        # Touch file so readers see it even with no posts yet.
        self._path.touch(exist_ok=True)
        self._counter = 0
        self._last_ts = 0.0
        self._lock = threading.Lock()

    @property
    def manager_run_id(self) -> str:
        return self._manager_run_id

    @property
    def path(self) -> Path:
        return self._path

    # -- Write path ---------------------------------------------------

    def post(self, topic: str, payload: dict, worker_id: str) -> str:
        """Append an entry for ``topic`` and return its id.

        ``payload`` must be JSON-serialisable. Non-serialisable values
        are coerced via ``str`` so a misbehaving worker cannot poison
        the board.
        """
        if not isinstance(topic, str) or not topic:
            raise ValueError("topic must be a non-empty string")
        if not isinstance(payload, dict):
            raise ValueError("payload must be a dict")

        with self._lock:
            self._counter += 1
            # Strictly monotonic ts within a single process so that
            # `since` filtering by timestamp is deterministic even when
            # the system clock has coarse resolution (the wall-clock
            # may otherwise return identical values for back-to-back
            # posts). We bump by 1 microsecond past the previous ts
            # whenever the wall-clock has not advanced.
            now = time.time()
            if now <= self._last_ts:
                now = self._last_ts + 1e-6
            self._last_ts = now
            # Round ts to 6 decimal places so the string representation
            # in the entry id is an exact round-trip of the stored float.
            # Without rounding, float repr can have more digits than the
            # id string format, causing since-filtering precision errors.
            ts = round(now, 6)
            entry_id = f"{ts:.6f}-{self._counter}-{os.getpid()}"
            entry = {
                "id": entry_id,
                "ts": ts,
                "topic": topic,
                "worker_id": str(worker_id or ""),
                "payload": payload,
            }
            line = json.dumps(entry, default=str, ensure_ascii=False) + "\n"

            # Append with a cross-process advisory lock so concurrent
            # writers cannot interleave partial lines.
            with open(self._path, "ab") as fh:
                if _HAS_FCNTL:
                    try:
                        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
                    except OSError:
                        pass
                try:
                    fh.write(line.encode("utf-8"))
                    fh.flush()
                    try:
                        os.fsync(fh.fileno())
                    except OSError:
                        pass
                finally:
                    if _HAS_FCNTL:
                        try:
                            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
                        except OSError:
                            pass
            return entry_id

    # -- Read path ----------------------------------------------------

    def read(
        self,
        topic: Optional[str] = None,
        since: Optional[str] = None,
    ) -> list[dict]:
        """Return entries (optionally) filtered by ``topic`` and ``since``.

        ``since`` may be either a previously returned entry id or a
        numeric timestamp (string or float). Only entries strictly
        newer than ``since`` are returned. Corrupted lines are skipped
        silently — the blackboard must never crash the manager loop.
        """
        if not self._path.exists():
            return []

        since_ts: Optional[float] = None
        if since is not None:
            since_ts = _extract_ts(since)

        out: list[dict] = []
        with open(self._path, "rb") as fh:
            if _HAS_FCNTL:
                try:
                    fcntl.flock(fh.fileno(), fcntl.LOCK_SH)
                except OSError:
                    pass
            try:
                raw = fh.read().decode("utf-8", errors="replace")
            finally:
                if _HAS_FCNTL:
                    try:
                        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
                    except OSError:
                        pass

        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(entry, dict):
                continue
            if topic is not None and entry.get("topic") != topic:
                continue
            if since_ts is not None:
                ts_val = entry.get("ts")
                try:
                    if ts_val is None or float(ts_val) <= since_ts:
                        continue
                except (TypeError, ValueError):
                    continue
            out.append(entry)
        return out

    # -- Helpers ------------------------------------------------------

    def latest_id(self, entries: Optional[Iterable[dict]] = None) -> Optional[str]:
        """Return the id of the last entry (for ``since`` bookkeeping)."""
        if entries is None:
            entries = self.read()
        last: Optional[str] = None
        for e in entries:
            eid = e.get("id")
            if isinstance(eid, str):
                last = eid
        return last


def _extract_ts(since: str) -> Optional[float]:
    """Best-effort conversion of ``since`` to a float timestamp.

    Accepts both raw floats ("1712345678.123") and entry-id strings
    ("1712345678.123456-4-1234"). Returns ``None`` if nothing usable
    could be parsed; callers then treat ``since`` as "include all".
    """
    if since is None:
        return None
    s = str(since).strip()
    if not s:
        return None
    # Try float first.
    try:
        return float(s)
    except ValueError:
        pass
    # Try the "<ts>-<counter>-<pid>" entry id form.
    head = s.split("-", 1)[0]
    try:
        return float(head)
    except ValueError:
        return None


__all__ = ["Blackboard", "current_blackboard"]
