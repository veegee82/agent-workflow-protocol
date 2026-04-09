"""Unit tests for the sibling-coordination Blackboard."""

from __future__ import annotations

import multiprocessing
import time
from pathlib import Path

import pytest

from awp.runtime.blackboard import Blackboard


def test_post_read_roundtrip(tmp_path: Path) -> None:
    bb = Blackboard(workspace=tmp_path, manager_run_id="run1")
    entry_id = bb.post("findings", {"x": 1}, worker_id="w1")
    assert isinstance(entry_id, str) and entry_id

    entries = bb.read()
    assert len(entries) == 1
    e = entries[0]
    assert e["topic"] == "findings"
    assert e["worker_id"] == "w1"
    assert e["payload"] == {"x": 1}
    assert e["id"] == entry_id


def test_topic_filter(tmp_path: Path) -> None:
    bb = Blackboard(workspace=tmp_path, manager_run_id="run2")
    bb.post("a", {"n": 1}, worker_id="w1")
    bb.post("b", {"n": 2}, worker_id="w1")
    bb.post("a", {"n": 3}, worker_id="w2")

    a_entries = bb.read(topic="a")
    b_entries = bb.read(topic="b")
    assert [e["payload"]["n"] for e in a_entries] == [1, 3]
    assert [e["payload"]["n"] for e in b_entries] == [2]


def test_since_filter(tmp_path: Path) -> None:
    bb = Blackboard(workspace=tmp_path, manager_run_id="run3")
    # Blackboard guarantees strictly monotonic ts per process, so
    # sequential posts yield strictly increasing timestamps without
    # needing wall-clock sleeps.
    first = bb.post("t", {"i": 1}, worker_id="w")
    bb.post("t", {"i": 2}, worker_id="w")
    bb.post("t", {"i": 3}, worker_id="w")

    new = bb.read(since=first)
    assert [e["payload"]["i"] for e in new] == [2, 3]


def test_empty_read(tmp_path: Path) -> None:
    bb = Blackboard(workspace=tmp_path, manager_run_id="run4")
    assert bb.read() == []
    assert bb.read(topic="nope") == []
    assert bb.read(since="9999999999.0") == []


def _worker_posts(workspace_str: str, run_id: str, prefix: str, n: int) -> None:
    bb = Blackboard(workspace=Path(workspace_str), manager_run_id=run_id)
    for i in range(n):
        bb.post("concurrent", {"prefix": prefix, "i": i}, worker_id=prefix)


def test_concurrent_posts_no_corruption(tmp_path: Path) -> None:
    run_id = "run_concurrent"
    n = 50
    procs = [
        multiprocessing.Process(
            target=_worker_posts,
            args=(str(tmp_path), run_id, f"p{k}", n),
        )
        for k in range(2)
    ]
    for p in procs:
        p.start()
    for p in procs:
        p.join(timeout=30)
        assert p.exitcode == 0

    bb = Blackboard(workspace=tmp_path, manager_run_id=run_id)
    entries = bb.read()
    # Every line must parse — no partial / corrupted lines.
    assert len(entries) == 2 * n
    # Each entry must have all required fields.
    for e in entries:
        assert set(["id", "ts", "topic", "worker_id", "payload"]).issubset(e.keys())
        assert e["topic"] == "concurrent"

    # And the raw file must have exactly 2*n newline-terminated lines.
    raw = (tmp_path / "blackboard" / f"{run_id}.jsonl").read_text()
    assert raw.count("\n") == 2 * n


def test_submanager_gets_separate_board(tmp_path: Path) -> None:
    parent = Blackboard(workspace=tmp_path, manager_run_id="parent")
    child = Blackboard(workspace=tmp_path, manager_run_id="child")
    parent.post("p", {"k": "parent"}, worker_id="pw")
    child.post("c", {"k": "child"}, worker_id="cw")

    assert [e["payload"]["k"] for e in parent.read()] == ["parent"]
    assert [e["payload"]["k"] for e in child.read()] == ["child"]
