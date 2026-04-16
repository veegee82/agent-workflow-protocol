"""Unit test for the E2E harness watcher final-drain fix.

Reproduces the Session-3 residual: the watcher exited before the terminal
``run.complete`` event was persisted because ``stop()`` was signalled
right after ``wf.run()`` returned but before the poll loop noticed
``run_completion.json`` on disk.

The fix is an unconditional ``_final_drain()`` call in ``watch()``'s
``finally`` block. This test asserts the drain persists ``run.complete``
even when completion lands at (or just after) stop signal time.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import threading
import time
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Locate and import the harness module without requiring it to be on
# sys.path at collection time (the tests/ directory is in awp-runtime; the
# harness lives under examples/e2e/).
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[3]
_HARNESS_PATH = _REPO_ROOT / "examples" / "e2e" / "_harness.py"


def _load_harness():
    if not _HARNESS_PATH.is_file():
        pytest.skip(f"harness not found at {_HARNESS_PATH}")
    spec = importlib.util.spec_from_file_location(
        "e2e_harness_under_test", _HARNESS_PATH
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["e2e_harness_under_test"] = module
    spec.loader.exec_module(module)
    return module


def _install_fake_persist(watcher, sink: list[tuple[str, dict]]) -> None:
    """Replace ``_persist_event`` to avoid SQLite I/O in the unit test."""

    def _fake(event_type: str, data: dict) -> None:
        sink.append((event_type, data))

    watcher._persist_event = _fake  # type: ignore[method-assign]


def _make_run_dir(workspace: Path) -> Path:
    """Materialize the directory structure _find_run_dir() expects."""
    runs_dir = workspace / "workspace" / "runs"
    run_dir = runs_dir / "20260414-000000-run01"
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def test_final_drain_persists_run_complete_after_stop(tmp_path: Path) -> None:
    """Drop run_completion.json right as stop() fires — drain must persist it."""
    harness = _load_harness()
    workspace = tmp_path / "experiment"
    workspace.mkdir()
    # Pre-existing-dirs snapshot happens at __init__; make sure the fresh
    # run dir will be considered "new".
    (workspace / "workspace" / "runs").mkdir(parents=True)

    watcher = harness._E2ERunDirWatcher(
        run_id="test-run-0001",
        workspace_dir=workspace,
    )
    sink: list[tuple[str, dict]] = []
    _install_fake_persist(watcher, sink)

    run_dir = _make_run_dir(workspace)

    thread = threading.Thread(target=watcher.watch, daemon=True)
    thread.start()

    # Let the watcher spin up and pin the run dir.
    time.sleep(0.5)

    # Write run_manifest.json + run_completion.json then stop() almost
    # immediately. The race we're protecting against: stop() signal
    # arrives before the poll loop observed run_completion.json.
    (run_dir / "run_manifest.json").write_text(
        json.dumps({"task": "t", "models": {"manager": "m"}}),
        encoding="utf-8",
    )
    (run_dir / "run_completion.json").write_text(
        json.dumps({
            "status": "complete",
            "termination_reason": "done",
            "iterations_completed": 1,
        }),
        encoding="utf-8",
    )
    watcher.stop()
    thread.join(timeout=10)

    assert not thread.is_alive(), "watcher thread did not exit"
    event_types = [ev for ev, _ in sink]
    assert "run.complete" in event_types, (
        f"run.complete not persisted post-join; sink={event_types}"
    )
    # Sanity — the completion payload round-tripped.
    complete_payloads = [d for ev, d in sink if ev == "run.complete"]
    assert complete_payloads, "no run.complete payload"
    assert complete_payloads[-1].get("status") == "complete"


def test_final_drain_runs_even_when_completion_missing(tmp_path: Path) -> None:
    """Aborted runs: drain must not raise; partial events still reach sink."""
    harness = _load_harness()
    workspace = tmp_path / "experiment"
    workspace.mkdir()
    (workspace / "workspace" / "runs").mkdir(parents=True)

    watcher = harness._E2ERunDirWatcher(
        run_id="test-run-0002",
        workspace_dir=workspace,
    )
    sink: list[tuple[str, dict]] = []
    _install_fake_persist(watcher, sink)

    run_dir = _make_run_dir(workspace)

    thread = threading.Thread(target=watcher.watch, daemon=True)
    thread.start()
    time.sleep(0.4)

    # Only the manifest is written — no run_completion.json. Simulates
    # SIGKILL / crash before finalizer runs.
    (run_dir / "run_manifest.json").write_text(
        json.dumps({"task": "t", "models": {"manager": "m"}}),
        encoding="utf-8",
    )
    watcher.stop()
    thread.join(timeout=15)

    assert not thread.is_alive()
    # No run.complete expected — but run.start must have been persisted,
    # and the drain must not have raised.
    event_types = [ev for ev, _ in sink]
    assert "run.start" in event_types
    assert "run.complete" not in event_types
