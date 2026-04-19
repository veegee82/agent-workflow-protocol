"""WAL mode + concurrent-writer tests for the outer-loop SQLite store."""

from __future__ import annotations

import threading
from pathlib import Path

from awp.outer_loop.store import SqliteArtifactStore


def test_store_initializes_in_wal_mode(tmp_path: Path) -> None:
    store = SqliteArtifactStore(str(tmp_path / "registry.db"))
    try:
        cur = store._conn.execute("PRAGMA journal_mode")
        mode = cur.fetchone()[0]
        assert mode.lower() == "wal", f"expected WAL mode, got {mode!r}"
    finally:
        store.close()


def test_store_parallel_put_version_is_consistent(tmp_path: Path) -> None:
    store = SqliteArtifactStore(str(tmp_path / "parallel.db"))
    num_threads = 8
    per_thread = 10
    barrier = threading.Barrier(num_threads)

    def worker(i: int) -> None:
        barrier.wait(timeout=10)
        for j in range(per_thread):
            store.put_version(
                artifact_name=f"artifact_{i}",
                content=f"content-{i}-{j}",
                parent_version=None,
                created_at="2026-04-18T00:00:00Z",
                epoch_id=None,
            )

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(num_threads)]
    try:
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        for i in range(num_threads):
            versions = store.list_versions(f"artifact_{i}")
            assert len(versions) == per_thread, (
                f"artifact_{i}: expected {per_thread} versions, got {len(versions)}"
            )
            numbers = sorted(v.version for v in versions)
            assert numbers == list(range(1, per_thread + 1)), (
                f"artifact_{i}: non-contiguous versions {numbers}"
            )
    finally:
        store.close()


def test_store_pragmas_persist_across_reads(tmp_path: Path) -> None:
    """Re-opening an existing DB keeps WAL mode active."""
    db_path = tmp_path / "persist.db"
    first = SqliteArtifactStore(str(db_path))
    first.put_version(
        artifact_name="keep",
        content="hello",
        parent_version=None,
        created_at="2026-04-18T00:00:00Z",
        epoch_id=None,
    )
    first.close()

    second = SqliteArtifactStore(str(db_path))
    try:
        mode = second._conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode.lower() == "wal"
        versions = second.list_versions("keep")
        assert len(versions) == 1
    finally:
        second.close()
