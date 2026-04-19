"""Hardening tests for PersistentExecutor.

Covers the three coupled defects Z1/Z2/Z3 and the α-1-extra auto-restart
with warm-state replay. See CLAUDE.md §3 (Debugging Discipline).
"""

from __future__ import annotations

import time

import pytest

from awp.runtime.persistent_executor import PersistentExecutor


@pytest.fixture()
def executor():
    """Fresh warm-executor per test; cleaned up afterwards."""
    ex = PersistentExecutor(max_timeout=10)
    try:
        yield ex
    finally:
        ex.cleanup()


def test_namespace_persists_across_calls(executor: PersistentExecutor) -> None:
    """Z1: plain variables bound in call 1 must be visible in call 2."""
    r1 = executor.execute("x = 5")
    assert r1["ok"], r1
    r2 = executor.execute("print(x + 1)")
    assert r2["ok"], r2
    assert "6" in r2["data"]["stdout"]


def test_import_persists_across_calls(executor: PersistentExecutor) -> None:
    """Z1: imports in call 1 must not re-raise ImportError in call 2."""
    r1 = executor.execute("import json")
    assert r1["ok"], r1
    r2 = executor.execute('print(json.dumps({"a": 1}))')
    assert r2["ok"], r2
    assert '"a"' in r2["data"]["stdout"]
    assert "1" in r2["data"]["stdout"]


def test_large_stderr_does_not_deadlock(executor: PersistentExecutor) -> None:
    """Z2: > 200 KB of stderr output must not deadlock the warm subprocess.

    Under the old code this blew past the 64 KB pipe buffer because the
    parent never drained stderr. Now that the child captures stderr into
    an in-process StringIO and the parent merges the real stderr into
    stdout, the call must complete cleanly within the timeout.
    """
    code = (
        "import sys\n"
        "for _ in range(250):\n"
        "    sys.stderr.write('x' * 1024 + '\\n')\n"
        "print('done')\n"
    )
    start = time.monotonic()
    result = executor.execute(code, timeout=8)
    elapsed = time.monotonic() - start
    assert result["ok"], result
    assert "done" in result["data"]["stdout"]
    assert elapsed < 8, f"execution took {elapsed:.2f}s, suggests deadlock"


def test_timeout_respected_for_hanging_code(executor: PersistentExecutor) -> None:
    """Z3: infinite loop must be killed at the timeout boundary, not hang."""
    start = time.monotonic()
    result = executor.execute("while True: pass", timeout=2)
    elapsed = time.monotonic() - start
    assert not result["ok"]
    assert result["status"] == 408
    # Must terminate in the neighborhood of the timeout; allow generous
    # overhead for select() + kill() + wait() but reject "hangs forever".
    assert elapsed < 6, f"hang not killed in time: elapsed={elapsed:.2f}s"


def test_auto_restart_replays_namespace(executor: PersistentExecutor) -> None:
    """α-1-extra: after a forced kill, history replay must restore state."""
    r1 = executor.execute("a = 10")
    assert r1["ok"], r1

    # Simulate an abrupt death (OOM, SIGKILL, crash, etc.).
    executor._kill_process()
    assert executor._proc is None

    # The next call must transparently spawn a new subprocess, replay the
    # recorded "a = 10", and then execute "print(a + 1)" against the
    # restored namespace.
    r2 = executor.execute("print(a + 1)")
    assert r2["ok"], r2
    assert "11" in r2["data"]["stdout"]
