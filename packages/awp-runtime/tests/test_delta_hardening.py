"""Framework-Fix δ hardening tests (δ1 watchdog, δ2 hard-kill, δ3 output cap).

These pin the three coupled cures for Run 4's 9 h 50 min hang inside a
``code.execute`` call in the German-translation worker. The hang was the
combined result of:

* (a) the main thread stuck inside a ``futex_wait`` / blocking ``os.read``
  on a pipe the child process had filled past the 64 KB kernel buffer,
  and
* (b) the cooperative budget check in ``BudgetSnapshot.can_continue``
  only firing between manager iterations — which never came — so
  ``max_wall_time = 28_800s`` (8 h) never triggered.

δ1 = preemptive wall-time watchdog thread in ``DelegationLoopRunner``.
δ2 = hard-kill ``threading.Timer`` in ``PersistentExecutor.execute``.
δ3 = 2 MB output cap inside the warm-subprocess worker script before
     the result ever reaches the pipe.

All three are regression tests at the layer of the root cause, not the
symptom (CLAUDE.md §3 "Debugging Discipline").
"""

from __future__ import annotations

import os
import signal
import threading
import time
from types import SimpleNamespace

import pytest

from awp.runtime.delegation_loop_runner import DelegationLoopRunner
from awp.runtime.persistent_executor import (
    _CHILD_OUTPUT_CAP_BYTES,
    _HARD_KILL_GRACE_SECONDS,
    PersistentExecutor,
)


# ---------------------------------------------------------------------------
# δ1 — preemptive wall-time watchdog
# ---------------------------------------------------------------------------


class _FakeBudget:
    """Minimal BudgetSnapshot stand-in for δ1 tests.

    Exposes ``max_wall_time`` and ``wall_time_elapsed`` — the only two
    attributes the watchdog reads. Clock starts at construction time so
    wall-time elapses naturally; use ``fast_forward`` to simulate a
    long-running run without waiting in real time.
    """

    def __init__(self, max_wall_time: float) -> None:
        self.max_wall_time = max_wall_time
        self._start = time.monotonic()
        self._offset = 0.0

    @property
    def wall_time_elapsed(self) -> float:
        return (time.monotonic() - self._start) + self._offset

    def fast_forward(self, seconds: float) -> None:
        self._offset += seconds


def _make_runner_stub(budget: _FakeBudget) -> SimpleNamespace:
    """Construct the minimum state the watchdog helper needs.

    We deliberately avoid instantiating a full ``DelegationLoopRunner``
    because that would require workflow_dir, config, tool registry, etc.
    The watchdog is a pure method that only reads ``self._depth``,
    ``self._budget``, and ``self._run_id`` — so a SimpleNamespace with
    the helper methods attached via ``__get__`` is sufficient.
    """
    stub = SimpleNamespace()
    stub._depth = 0
    stub._budget = budget
    stub._run_id = "test_delta1"
    stub._wall_time_watchdog_stop = None
    stub._wall_time_watchdog_thread = None
    # Bind the helpers as bound methods on the stub via __get__.
    stub._start_walltime_watchdog = (
        DelegationLoopRunner._start_walltime_watchdog.__get__(stub)
    )
    stub._stop_walltime_watchdog = (
        DelegationLoopRunner._stop_walltime_watchdog.__get__(stub)
    )
    return stub


def test_walltime_watchdog_kills_stuck_run(monkeypatch: pytest.MonkeyPatch) -> None:
    """δ1: on wall-time breach, the watchdog must send SIGTERM within one poll cycle.

    Uses dependency injection via ``kill_fn`` so the test captures the
    kill intent instead of actually SIGTERMing pytest's process. To
    avoid waiting the full 30 s default poll interval, we shorten the
    watchdog's poll/escalate constants via monkeypatch.
    """
    # Shorten the watchdog's polling cadence so the test finishes in
    # seconds rather than minutes. The constants are class attributes
    # so monkeypatching them affects any instance read after this point.
    monkeypatch.setattr(
        DelegationLoopRunner, "_WALLTIME_WATCHDOG_POLL_SECONDS", 1
    )
    monkeypatch.setattr(
        DelegationLoopRunner, "_WALLTIME_WATCHDOG_ESCALATE_SECONDS", 1
    )

    budget = _FakeBudget(max_wall_time=2)
    stub = _make_runner_stub(budget)

    kills: list[tuple[int, int]] = []
    kill_event = threading.Event()

    def _capture_kill(pid: int, sig: int) -> None:
        kills.append((pid, sig))
        kill_event.set()

    thread = stub._start_walltime_watchdog(kill_fn=_capture_kill)
    assert thread is not None
    assert thread.is_alive()
    assert thread.daemon is True
    assert thread.name == "awp-walltime-watchdog"

    try:
        # Fast-forward past the budget so the next poll sees a breach.
        budget.fast_forward(3)

        # The watchdog should send SIGTERM within the shortened poll
        # window (1 s) + generous scheduling slack.
        assert kill_event.wait(
            timeout=5
        ), "watchdog did not fire within 5s of wall-time breach"
        assert kills, "watchdog fired but did not record any kill"
        first_pid, first_sig = kills[0]
        assert first_pid == os.getpid()
        assert first_sig == signal.SIGTERM
    finally:
        stub._stop_walltime_watchdog()
        thread.join(timeout=5)
        assert not thread.is_alive(), "watchdog thread did not stop after join"


def test_walltime_watchdog_does_not_fire_within_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """δ1: no kill is issued while wall-time stays under max_wall_time."""
    monkeypatch.setattr(
        DelegationLoopRunner, "_WALLTIME_WATCHDOG_POLL_SECONDS", 1
    )
    budget = _FakeBudget(max_wall_time=60)  # far above elapsed
    stub = _make_runner_stub(budget)

    kills: list[tuple[int, int]] = []

    def _capture_kill(pid: int, sig: int) -> None:
        kills.append((pid, sig))

    thread = stub._start_walltime_watchdog(kill_fn=_capture_kill)
    assert thread is not None
    try:
        # Wait several poll cycles and assert no kill was issued.
        time.sleep(3)
        assert kills == [], f"watchdog fired spuriously: {kills}"
    finally:
        stub._stop_walltime_watchdog()
        thread.join(timeout=5)


def test_walltime_watchdog_skipped_for_nested_depth() -> None:
    """δ1: submanagers (depth > 0) must not arm their own watchdog."""
    budget = _FakeBudget(max_wall_time=1)
    stub = _make_runner_stub(budget)
    stub._depth = 2  # non-root

    thread = stub._start_walltime_watchdog(kill_fn=lambda *_: None)
    assert thread is None, "nested-depth runner must not arm watchdog"


def test_walltime_watchdog_escalates_to_sigkill(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """δ1: if SIGTERM does not exit the process, the watchdog escalates to SIGKILL.

    Simulated via ``kill_fn`` that only records the signals. The stop
    event is NOT set between SIGTERM and SIGKILL, so the watchdog's
    ``stop_event.wait(escalate_after)`` returns False and falls through
    to the SIGKILL branch.
    """
    monkeypatch.setattr(
        DelegationLoopRunner, "_WALLTIME_WATCHDOG_POLL_SECONDS", 1
    )
    monkeypatch.setattr(
        DelegationLoopRunner, "_WALLTIME_WATCHDOG_ESCALATE_SECONDS", 1
    )

    budget = _FakeBudget(max_wall_time=1)
    stub = _make_runner_stub(budget)

    kills: list[int] = []
    second_kill = threading.Event()

    def _capture_kill(_pid: int, sig: int) -> None:
        kills.append(sig)
        if sig == signal.SIGKILL:
            second_kill.set()

    thread = stub._start_walltime_watchdog(kill_fn=_capture_kill)
    assert thread is not None
    try:
        budget.fast_forward(2)
        assert second_kill.wait(timeout=6), (
            "watchdog did not escalate to SIGKILL: %r" % (kills,)
        )
        assert signal.SIGTERM in kills
        assert signal.SIGKILL in kills
        assert kills.index(signal.SIGTERM) < kills.index(signal.SIGKILL)
    finally:
        stub._stop_walltime_watchdog()
        thread.join(timeout=5)


def test_walltime_watchdog_survives_main_thread_crash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """δ1: the watchdog must fire even if its starter thread has died.

    This is the whole point of δ1 — Run 4's main thread was wedged in
    ``futex_wait`` and never reached the cooperative budget check. The
    watchdog is a separate daemon thread and must keep polling.
    """
    monkeypatch.setattr(
        DelegationLoopRunner, "_WALLTIME_WATCHDOG_POLL_SECONDS", 1
    )

    budget = _FakeBudget(max_wall_time=1)
    stub = _make_runner_stub(budget)
    kill_event = threading.Event()

    def _capture_kill(_pid: int, sig: int) -> None:
        if sig == signal.SIGTERM:
            kill_event.set()

    # Start the watchdog from a worker thread that then exits — so the
    # thread that created the watchdog is GONE by the time the budget
    # is breached. The watchdog must not depend on its creator surviving.
    started: list[threading.Thread | None] = []

    def _starter() -> None:
        started.append(stub._start_walltime_watchdog(kill_fn=_capture_kill))

    starter = threading.Thread(target=_starter)
    starter.start()
    starter.join()
    assert not starter.is_alive()

    try:
        assert started and started[0] is not None
        budget.fast_forward(2)
        assert kill_event.wait(
            timeout=5
        ), "watchdog did not fire after its starter thread exited"
    finally:
        stub._stop_walltime_watchdog()
        if started and started[0] is not None:
            started[0].join(timeout=5)


# ---------------------------------------------------------------------------
# δ2 — hard-kill Timer in PersistentExecutor
# ---------------------------------------------------------------------------


def test_hard_executor_timeout_kills_runaway_code() -> None:
    """δ2: a ``while True: pass`` must be killed within timeout + grace + slack.

    The cooperative select-based deadline in ``_send_and_read`` already
    catches this in the normal case (see the existing α-fix-1 test
    ``test_timeout_respected_for_hanging_code``). δ2 is the structural
    backstop for the edge case where the read thread itself never wakes;
    here we just verify that the combined system returns within the
    expected envelope and sets the hard-kill flag if the Timer had to
    act.
    """
    ex = PersistentExecutor(max_timeout=10)
    try:
        start = time.monotonic()
        result = ex.execute("while True: pass", timeout=2)
        elapsed = time.monotonic() - start

        # Must terminate cleanly within timeout + grace + generous slack.
        # Budget:
        #   cooperative timeout  : 2 s
        #   δ2 grace             : 5 s
        #   cold-fallback worst  : ~2 s to spawn + run again (and re-hang
        #                          until the cold timeout of 2 s fires)
        #   slack                : 1 s
        # The cold fallback is ONLY used if δ2 fired; if the cooperative
        # path returned cleanly within 6 s (see α-fix-1 test) we never
        # reach the cold path. Either way we must be done in <= 14 s.
        assert elapsed < 14, (
            f"runaway code not killed within budget: elapsed={elapsed:.2f}s"
        )
        # Result must be a dict with timeout indication on either path.
        assert isinstance(result, dict)
        assert not result["ok"]
        assert result["status"] == 408
        err = (result.get("error") or "").lower()
        assert "timed out" in err or "hard-killed" in err, (
            f"missing timeout indication in error: {result}"
        )
    finally:
        ex.cleanup()


def test_hard_kill_watchdog_flag_set_on_manual_fire() -> None:
    """δ2: a direct call to ``_hard_kill_from_watchdog`` must kill the child.

    Exercises the kill path in isolation without waiting for the Timer.
    Verifies that ``_hard_killed`` is set and the process handle is
    cleared so the next call will spawn a fresh subprocess.
    """
    ex = PersistentExecutor(max_timeout=30)
    try:
        # Warm up so self._proc exists.
        r1 = ex.execute("x = 1")
        assert r1["ok"], r1
        assert ex._proc is not None
        proc_before = ex._proc

        # Fire the hard-kill directly; it is the same code path the
        # Timer invokes from its own thread.
        ex._hard_kill_from_watchdog()
        assert ex._hard_killed is True
        assert ex._proc is None
        # Process must actually be dead.
        poll = proc_before.poll()
        assert poll is not None, "hard-kill did not terminate the child process"

        # Follow-up call transparently spawns a fresh subprocess + replays.
        r2 = ex.execute("print(x + 1)")
        assert r2["ok"], r2
        assert "2" in r2["data"]["stdout"]
    finally:
        ex.cleanup()


# ---------------------------------------------------------------------------
# δ3 — 2 MB output cap in the worker script
# ---------------------------------------------------------------------------


def test_pipe_output_cap_prevents_large_stdout() -> None:
    """δ3: ~5 MB of child stdout must be capped to 2 MB + truncation marker.

    The parent's ``max_output_bytes`` is raised above the 2 MB child cap
    for this test so we can observe the cap and marker that the child
    writes. In production the parent further caps to 1 MB by default,
    which would eat the marker — that is acceptable because δ3's job is
    to keep the pipe from deadlocking, not to preserve the marker all
    the way to the caller.
    """
    # Give the parent enough room to observe the child's 2 MB + marker.
    ex = PersistentExecutor(max_timeout=30, max_output_bytes=4 * 1024 * 1024)
    try:
        result = ex.execute(
            'print("A" * 5_000_000)', timeout=20
        )
        assert result["ok"], result
        stdout = result["data"]["stdout"]
        # Capped at 2 MB + truncation marker (~50 bytes).
        encoded_len = len(stdout.encode("utf-8", errors="replace"))
        assert encoded_len <= _CHILD_OUTPUT_CAP_BYTES + 256, (
            f"stdout not capped: len={encoded_len}"
        )
        assert "[truncated:" in stdout, (
            f"truncation marker missing: tail={stdout[-200:]!r}"
        )
        assert "original" in stdout
    finally:
        ex.cleanup()


def test_pipe_output_cap_noop_for_small_stdout() -> None:
    """δ3: small outputs must pass through unchanged (no spurious marker)."""
    ex = PersistentExecutor(max_timeout=10)
    try:
        result = ex.execute('print("hello world")')
        assert result["ok"], result
        assert result["data"]["stdout"].strip() == "hello world"
        assert "[truncated:" not in result["data"]["stdout"]
    finally:
        ex.cleanup()


# ---------------------------------------------------------------------------
# Module constants — pin them so accidental widening is a failing test.
# ---------------------------------------------------------------------------


def test_delta_constants_are_pinned() -> None:
    """The δ safety constants are code-level floors, not config knobs."""
    assert _CHILD_OUTPUT_CAP_BYTES == 2 * 1024 * 1024
    assert _HARD_KILL_GRACE_SECONDS == 5
    assert DelegationLoopRunner._WALLTIME_WATCHDOG_POLL_SECONDS == 30
    assert DelegationLoopRunner._WALLTIME_WATCHDOG_ESCALATE_SECONDS == 30
