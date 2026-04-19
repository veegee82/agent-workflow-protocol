"""UI read-only access to the outer-loop artifact/epoch/suite SQLite store.

The outer-loop DB (``~/.awp/outer_loop.db`` by default, overridable via
``$AWP_OUTER_LOOP_DB``) is a *separate* database from the UI's
``~/.awp/awp_ui.db`` — this service is the one-way bridge that lets the
graph visualisation and the Suites tab read optimizer state without
touching the runtime's write paths.

Design invariants:

* This module only *reads* from the outer-loop DB. Suites, epochs, and
  epoch_runs are written by :mod:`awp.outer_loop.runner` — never here.
* If the DB does not exist or is unreadable, every function returns a
  benign empty result (``None``, ``[]``) so the UI degrades gracefully
  when the optimizer has not been used yet.
* We never duplicate schema knowledge — all DB access goes through
  :class:`awp.outer_loop.store.SqliteArtifactStore`, which is the
  authoritative schema owner.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# DB path resolution
# ---------------------------------------------------------------------------


def _resolve_db_path() -> str:
    """Resolve the outer-loop DB path with the same precedence as the CLI.

    Precedence: ``$AWP_OUTER_LOOP_DB`` > ``~/.awp/outer_loop.db``.
    Mirrors :func:`awp.cli._resolve_outer_loop_db_path` — kept local so the
    service has no new dependency on the CLI layer.
    """
    env = os.environ.get("AWP_OUTER_LOOP_DB")
    if env:
        return env
    return str(Path.home() / ".awp" / "outer_loop.db")


def _open_store() -> Any | None:
    """Open the outer-loop store if the DB exists; otherwise return ``None``.

    We intentionally do NOT create an empty DB from the UI side — that would
    masquerade as "optimizer initialised" when the user has never run
    ``awp optimize``. An absent DB is a legitimate state that the UI must
    represent as "no suites yet".
    """
    db_path = _resolve_db_path()
    if not os.path.isfile(db_path):
        return None
    try:
        # Import lazily so that `import server.services.outer_loop_service`
        # has no side effects if awp-runtime is not installed in the env.
        from awp.outer_loop.store import SqliteArtifactStore
    except ImportError:
        logger.warning("awp.outer_loop.store not importable — outer-loop UI disabled")
        return None
    try:
        return SqliteArtifactStore(db_path)
    except OSError as exc:
        logger.warning("Cannot open outer-loop DB at %s: %s", db_path, exc)
        return None


# ---------------------------------------------------------------------------
# Artifact-version helpers
# ---------------------------------------------------------------------------


def _parse_artifact_map(blob: str | None) -> dict[str, int]:
    """Parse a suite / epoch ``*_artifacts_json`` blob into ``{name: version}``.

    The runtime persists these as JSON objects keyed by artifact name with
    integer version values. We are tolerant of three shapes:

    * **A2 legacy**: ``{"worker_pitfalls": 1, ...}`` — flat map.
    * **A3 richer**: ``{"artifacts": {"worker_pitfalls": 1, ...},
      "events": [...]}`` — the update record persisted by
      :meth:`awp.outer_loop.runner.SuiteRunner.optimize`.
    * **Nested legacy**: ``{"name": {"version": 1}}``.
    """
    if not blob:
        return {}
    try:
        parsed = json.loads(blob)
    except (json.JSONDecodeError, TypeError):
        return {}
    if not isinstance(parsed, dict):
        return {}
    # A3 richer wrapper — unwrap to the nested "artifacts" map.
    if "artifacts" in parsed and isinstance(parsed["artifacts"], dict):
        parsed = parsed["artifacts"]
    out: dict[str, int] = {}
    for name, val in parsed.items():
        if isinstance(val, int):
            out[str(name)] = val
        elif isinstance(val, dict):
            v = val.get("version", val.get("v"))
            if isinstance(v, int):
                out[str(name)] = v
    return out


def _parse_artifact_events(blob: str | None) -> list[dict]:
    """Return the ``events`` list from an A3-era ``child_artifacts_json`` blob.

    Legacy A2 blobs are a flat ``{name: version}`` map with no events — we
    return ``[]`` in that case so callers can treat the field uniformly.
    """
    if not blob:
        return []
    try:
        parsed = json.loads(blob)
    except (json.JSONDecodeError, TypeError):
        return []
    if not isinstance(parsed, dict):
        return []
    events = parsed.get("events")
    if not isinstance(events, list):
        return []
    return [e for e in events if isinstance(e, dict)]


def _parse_scores(blob: str | None) -> dict:
    if not blob:
        return {}
    try:
        parsed = json.loads(blob)
    except (json.JSONDecodeError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_run_epoch(run_id: str) -> dict | None:
    """Return epoch context for ``run_id`` or ``None`` if it is not an epoch run.

    The shape matches the public API contract of
    ``GET /api/runs/{run_id}/epoch``::

        {
          "epoch_id": str,
          "suite_id": str,
          "epoch_num": int,
          "parent_artifacts": {name: version, ...},
          "child_artifacts": {name: version, ...},
          "mean_loss": float | None,
        }
    """
    store = _open_store()
    if store is None:
        return None
    try:
        # Direct query against the underlying connection — we deliberately
        # piggy-back on the store's lock/connection instead of opening a
        # second connection from the UI layer.
        with store._lock:  # noqa: SLF001 — reusing the store's lock is the safe path
            cur = store._conn.execute(  # noqa: SLF001
                "SELECT epoch_id FROM epoch_runs WHERE run_id = ? LIMIT 1",
                (run_id,),
            )
            row = cur.fetchone()
        if row is None:
            return None
        epoch_id = row["epoch_id"]

        with store._lock:  # noqa: SLF001
            cur = store._conn.execute(  # noqa: SLF001
                "SELECT * FROM epochs WHERE id = ? LIMIT 1",
                (epoch_id,),
            )
            epoch = cur.fetchone()
        if epoch is None:
            return None
        return {
            "epoch_id": epoch_id,
            "suite_id": epoch["suite_id"],
            "epoch_num": int(epoch["epoch_num"]),
            "parent_artifacts": _parse_artifact_map(epoch["parent_artifacts_json"]),
            "child_artifacts": _parse_artifact_map(epoch["child_artifacts_json"]),
            "mean_loss": (
                float(epoch["mean_loss"]) if epoch["mean_loss"] is not None else None
            ),
        }
    finally:
        store.close()


def list_suites() -> list[dict]:
    """Return suite summaries, newest first.

    Each entry: ``{id, name, epoch_count, latest_epoch, latest_mean_loss,
    created_at}``. Returns ``[]`` if the outer-loop DB does not exist yet.
    """
    store = _open_store()
    if store is None:
        return []
    try:
        with store._lock:  # noqa: SLF001
            cur = store._conn.execute(  # noqa: SLF001
                "SELECT id, name, created_at FROM task_suites "
                "ORDER BY created_at DESC"
            )
            suites = [dict(r) for r in cur.fetchall()]

        result: list[dict] = []
        for suite in suites:
            epochs = store.list_epochs(suite["id"])
            latest_epoch = epochs[-1] if epochs else None
            result.append(
                {
                    "id": suite["id"],
                    "name": suite["name"],
                    "epoch_count": len(epochs),
                    "latest_epoch": (
                        int(latest_epoch["epoch_num"]) if latest_epoch else None
                    ),
                    "latest_mean_loss": (
                        float(latest_epoch["mean_loss"])
                        if latest_epoch and latest_epoch.get("mean_loss") is not None
                        else None
                    ),
                    "created_at": suite["created_at"],
                }
            )
        return result
    finally:
        store.close()


def get_suite_graph_runs(suite_id: str) -> list[dict]:
    """Return ordered runs across all epochs of ``suite_id``.

    Each entry::

        {
          "epoch_id": str,
          "epoch_num": int,
          "run_id": str,
          "task_name": str,
          "loss": float | None,
          "parent_artifacts": {name: version},
          "child_artifacts": {name: version},
          "mean_loss": float | None,
          "started_at": str,
        }

    Ordering is ``(epoch_num ASC, run_id ASC)`` so the caller can chain
    runs vertically in visualisation order without re-sorting.
    """
    store = _open_store()
    if store is None:
        return []
    try:
        epochs = store.list_epochs(suite_id)
        out: list[dict] = []
        for epoch in epochs:
            parent_map = _parse_artifact_map(epoch.get("parent_artifacts_json"))
            child_map = _parse_artifact_map(epoch.get("child_artifacts_json"))
            mean_loss = epoch.get("mean_loss")
            runs = store.list_epoch_runs(epoch["id"])
            for run in runs:
                out.append(
                    {
                        "epoch_id": epoch["id"],
                        "epoch_num": int(epoch["epoch_num"]),
                        "run_id": run["run_id"],
                        "task_name": run["task_name"],
                        "loss": (
                            float(run["loss"])
                            if run.get("loss") is not None
                            else None
                        ),
                        "parent_artifacts": parent_map,
                        "child_artifacts": child_map,
                        "mean_loss": (
                            float(mean_loss) if mean_loss is not None else None
                        ),
                        "started_at": epoch.get("started_at", ""),
                    }
                )
        return out
    finally:
        store.close()


def get_suite_meta(suite_id: str) -> dict | None:
    """Return the suite's ``{id, name, created_at}`` row or ``None``."""
    store = _open_store()
    if store is None:
        return None
    try:
        suite = store.get_task_suite(suite_id)
        if not suite:
            return None
        return {
            "id": suite["id"],
            "name": suite["name"],
            "created_at": suite["created_at"],
        }
    finally:
        store.close()


def list_suite_epochs(suite_id: str) -> list[dict] | None:
    """Return detailed epochs for ``suite_id`` or ``None`` if the suite is unknown.

    Each entry::

        {
          "epoch_id": str,
          "epoch_num": int,
          "started_at": str,
          "completed_at": str | None,
          "mean_loss": float | None,
          "parent_artifacts": {name: version},
          "child_artifacts": {name: version},
          "events": [{"type": "update"|"rollback", "artifact": ...,
                      "from_version": int, "to_version": int, ...}, ...],
          "per_task_losses": [
            {"run_id": str, "task_name": str, "loss": float | None,
             "scores": dict}, ...
          ]
        }

    The suite resolution is intentionally lenient: if the outer-loop DB is
    absent entirely, we degrade to ``None`` too so the REST layer can return
    a single 404 regardless of cause (no DB vs no suite).
    """
    store = _open_store()
    if store is None:
        return None
    try:
        suite = store.get_task_suite(suite_id)
        if not suite:
            return None
        epochs = store.list_epochs(suite_id)
        out: list[dict] = []
        for epoch in epochs:
            runs = store.list_epoch_runs(epoch["id"])
            per_task: list[dict] = []
            for run in runs:
                per_task.append(
                    {
                        "run_id": run["run_id"],
                        "task_name": run["task_name"],
                        "loss": (
                            float(run["loss"])
                            if run.get("loss") is not None
                            else None
                        ),
                        "scores": _parse_scores(run.get("scores_json")),
                    }
                )
            out.append(
                {
                    "epoch_id": epoch["id"],
                    "epoch_num": int(epoch["epoch_num"]),
                    "started_at": epoch.get("started_at", ""),
                    "completed_at": epoch.get("completed_at"),
                    "mean_loss": (
                        float(epoch["mean_loss"])
                        if epoch.get("mean_loss") is not None
                        else None
                    ),
                    "parent_artifacts": _parse_artifact_map(
                        epoch.get("parent_artifacts_json")
                    ),
                    "child_artifacts": _parse_artifact_map(
                        epoch.get("child_artifacts_json")
                    ),
                    "events": _parse_artifact_events(
                        epoch.get("child_artifacts_json")
                    ),
                    "per_task_losses": per_task,
                }
            )
        return out
    finally:
        store.close()


def list_artifact_versions(name: str) -> list[dict] | None:
    """Return every version (including synthetic v0) of ``name``.

    Each entry::

        {
          "version": int,
          "content": str,
          "parent_version": int | None,
          "created_at": str,
          "is_active": bool,
        }

    ``None`` is returned if the artifact name is unknown. Versions are
    ordered ascending. Even when no DB exists, v0 is always present
    because it is the synthetic default bundled in
    :mod:`awp.outer_loop.defaults`.
    """
    try:
        from awp.outer_loop.artifacts import ArtifactRegistry
        from awp.outer_loop.defaults import DEFAULTS
    except ImportError:
        logger.warning("awp.outer_loop not importable — artifact endpoint disabled")
        return None
    if name not in DEFAULTS:
        return None

    db_path = _resolve_db_path()
    # Instantiate the registry — ArtifactRegistry silently falls back to
    # read-only v0 mode if the DB path is missing or unwritable, which is
    # exactly what we want for a UI read path.
    db_arg = db_path if os.path.isfile(db_path) else None
    registry = ArtifactRegistry(db_path=db_arg)
    versions = registry.list_versions(name)

    # Determine which version is active. In fallback mode (no DB) the
    # synthetic v0 default is active by definition.
    active_version = 0
    if db_arg is not None:
        try:
            active = registry.get_active(name)
            active_version = int(active.version)
        except Exception:
            active_version = 0

    out: list[dict] = []
    for v in versions:
        out.append(
            {
                "version": int(v.version),
                "content": v.content,
                "parent_version": (
                    int(v.parent_version) if v.parent_version is not None else None
                ),
                "created_at": v.created_at,
                "is_active": int(v.version) == active_version,
            }
        )
    return out
