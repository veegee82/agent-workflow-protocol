"""AWP Persistent Code Executor -- Warm subprocess pool for fast code execution.

Keeps a Python subprocess alive between ``code.execute`` calls so that
heavy imports (numpy, pandas, matplotlib) are loaded once and reused.
Falls back to the standard cold-start ``CodeExecutor`` if the persistent
process dies.
"""

from __future__ import annotations

import json
import logging
import os
import select
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path
from typing import Any, Optional

from .base_executor import BaseExecutor

logger = logging.getLogger(__name__)

# Protocol: the warm subprocess reads JSON commands from stdin and writes
# JSON results to stdout, using a sentinel line to delimit responses.
_SENTINEL = "__AWP_EXEC_DONE__"

# History cap for warm-state replay on auto-restart (Fix α-1-extra).
# These are implementation details, not user-facing hyperparameters.
_HISTORY_MAX_ENTRIES = 100
_HISTORY_MAX_BYTES = 1_048_576  # 1 MB of code text total

# Framework-Fix δ3: hard cap on per-call stdout/stderr captured inside the
# warm subprocess. A multi-MB write into a pipe whose parent is briefly busy
# can still stall even with merged stderr/stdout and select-based reads —
# the Linux pipe buffer is ~64 KB. Capping at 2 MB in the CHILD, before the
# pipe write, makes a deadlock structurally impossible. Truncation is
# explicitly marked so the caller can tell the difference between "no
# output" and "output discarded". Constant, not a config flag, because it
# is a safety floor — the caller never has a legitimate reason to want
# unbounded child stdout.
_CHILD_OUTPUT_CAP_BYTES = 2 * 1024 * 1024  # 2 MB per stream

# Framework-Fix δ2: grace period after the cooperative deadline before the
# parent forcibly SIGKILLs the warm subprocess. The select-based read in
# ``_send_and_read`` is the first line of defense; this Timer is the
# structural backstop for the edge case where the read thread itself is
# stuck inside ``os.read`` (some pipe configurations do not wake a pending
# read even when select() has timed out on the same fd in a different call
# path). 5 s is enough slack for select/kill/wait to clean up under load
# without making hang detection meaningfully slower.
_HARD_KILL_GRACE_SECONDS = 5

_WORKER_SCRIPT = textwrap.dedent(f"""\
    import json, sys, traceback, io, os

    SENTINEL = "{_SENTINEL}"
    # δ3: hard cap on per-stream captured output BEFORE it crosses the pipe.
    OUTPUT_CAP = {_CHILD_OUTPUT_CAP_BYTES}

    # Fix Z1: a single persistent namespace reused across every exec() call,
    # so imports, helpers, and data defined in earlier calls remain visible
    # in later ones. This is the whole point of a warm executor.
    _ns = {{"__name__": "__main__"}}

    def _cap(text):
        # Cap a string's UTF-8 byte length at OUTPUT_CAP. If we had to drop
        # anything, append a truncation marker so the caller sees the signal
        # rather than a silent cutoff. Measurement is on bytes because the
        # pipe is byte-oriented; cutting on characters can still leave a
        # multi-MB byte string if the input is mostly multi-byte chars.
        if not text:
            return text
        b = text.encode("utf-8", errors="replace")
        n = len(b)
        if n <= OUTPUT_CAP:
            return text
        head = b[:OUTPUT_CAP].decode("utf-8", errors="replace")
        return head + "\\n...[truncated: original {{}} bytes]".format(n)

    while True:
        try:
            line = sys.stdin.readline()
            if not line:
                break
            cmd = json.loads(line)
            code = cmd.get("code", "")
            cwd = cmd.get("cwd")
            if cwd:
                os.chdir(cwd)

            # Capture stdout/stderr
            old_out, old_err = sys.stdout, sys.stderr
            buf_out, buf_err = io.StringIO(), io.StringIO()
            sys.stdout, sys.stderr = buf_out, buf_err
            returncode = 0
            try:
                exec(code, _ns)
            except SystemExit as e:
                returncode = int(e.code) if e.code else 0
            except Exception:
                traceback.print_exc(file=buf_err)
                returncode = 1
            finally:
                sys.stdout, sys.stderr = old_out, old_err

            # δ3: cap both streams before serializing the JSON reply so a
            # runaway print() in the child can never stall the parent.
            stdout_capped = _cap(buf_out.getvalue())
            stderr_capped = _cap(buf_err.getvalue())

            result = {{
                "ok": returncode == 0,
                "stdout": stdout_capped,
                "stderr": stderr_capped,
                "returncode": returncode,
            }}
            old_out.write(json.dumps(result) + "\\n")
            old_out.write(SENTINEL + "\\n")
            old_out.flush()
        except Exception as exc:
            sys.stdout.write(json.dumps({{
                "ok": False,
                "stdout": "",
                "stderr": str(exc),
                "returncode": 1,
            }}) + "\\n")
            sys.stdout.write(SENTINEL + "\\n")
            sys.stdout.flush()
""")


class PersistentExecutor(BaseExecutor):
    """Warm-subprocess executor that keeps Python imports cached.

    On first ``execute()`` call, spawns a long-running Python subprocess.
    Subsequent calls reuse the same process — imports like numpy, pandas,
    and matplotlib stay loaded, cutting ~1-3s per call.

    Falls back to cold subprocess.run() if the persistent process is
    unavailable or crashes.
    """

    def __init__(
        self,
        max_timeout: int = 30,
        max_output_bytes: int = 1_048_576,
        working_dir: Optional[Path] = None,
        packages: list[str] | None = None,
        pip_install: bool = False,
    ) -> None:
        self._max_timeout = max_timeout
        self._max_output = max_output_bytes
        self._cwd = working_dir
        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()
        # Leftover bytes read past the sentinel during the previous call.
        # These are consumed first on the next read before touching the pipe
        # (avoids a blocking BufferedReader.peek on an empty pipe).
        self._read_residual: bytes = b""
        # Fix α-1-extra: history of successfully executed code blocks, used
        # to re-prime a freshly spawned subprocess after a crash so warm
        # state (imports, variables, helper functions) is restored.
        self._history: list[str] = []
        self._history_bytes: int = 0
        self._replaying: bool = False
        # Flipped to True whenever a live process is killed (either by a
        # detected crash or an explicit _kill_process()). The next call to
        # _ensure_process() will spawn a fresh subprocess and replay the
        # recorded history before returning it to the caller.
        self._needs_replay: bool = False
        # Framework-Fix δ2: set by ``_hard_kill_from_watchdog`` when the
        # Timer-based backstop had to SIGKILL the warm subprocess because
        # the cooperative select-based deadline did not fire. The main
        # thread in ``execute()`` checks this flag on return from the warm
        # path and falls through to ``_execute_cold`` so the caller still
        # sees a structured response instead of a raw exception.
        self._hard_killed: bool = False

        if packages and (pip_install or packages):
            self.install_runtime_packages(packages)

    def _ensure_process(self) -> subprocess.Popen:
        """Start the persistent subprocess if not already running.

        If the previous process died, spawn a new one and replay the
        recorded history so the caller sees a warm namespace.
        """
        if self._proc is not None and self._proc.poll() is None:
            return self._proc

        # Process is either never-started or dead. If it died while we
        # weren't looking (e.g. OOM crash between calls), mark replay.
        if self._proc is not None:
            self._needs_replay = True
            # Process exited; clean up handle before spawning replacement.
            self._kill_process()

        logger.debug("Starting persistent Python subprocess")
        # Fix Z2: merge stderr into stdout so a chatty child process cannot
        # deadlock on a full 64 KB stderr pipe that nobody drains. Real
        # crashes still surface because the child writes tracebacks to its
        # in-process buf_err and returns them in the JSON result; anything
        # that escapes that (e.g. interpreter-level import errors before
        # the worker loop starts) appears on the merged stdout stream and
        # is reported as "Persistent subprocess died unexpectedly".
        # Binary mode (text=False) on the pipes: we implement our own byte
        # buffer so select() and timeouts behave predictably. A text-mode
        # TextIOWrapper would silently pre-fetch bytes into an internal
        # buffer that select() cannot see, defeating the deadline logic.
        self._proc = subprocess.Popen(
            [sys.executable, "-u", "-c", _WORKER_SCRIPT],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=False,
            cwd=str(self._cwd) if self._cwd else None,
        )
        # Fresh process — any leftover bytes from a previous incarnation
        # are meaningless and must not contaminate the new pipe.
        self._read_residual = b""

        # After a restart, re-prime the new subprocess by silently replaying
        # the recorded history. We guard with _replaying so history is not
        # re-appended during replay. Replay failures are logged but do not
        # clear the history — a future call can try again.
        if self._needs_replay and self._history and not self._replaying:
            self._replay_history()
            # Replay attempted (success or partial); clear the flag so we
            # don't replay twice. If replay raised and left the process
            # dead, a subsequent call will re-enter here and try again.
            if self._proc is not None and self._proc.poll() is None:
                self._needs_replay = False

        return self._proc

    def _replay_history(self) -> None:
        """Silently replay recorded history into the freshly spawned subprocess."""
        self._replaying = True
        try:
            for entry in list(self._history):
                try:
                    # Use a generous, bounded timeout per replay entry; we do
                    # not want a pathological old entry to hang forever, but
                    # a fresh import (numpy etc.) may legitimately take a few
                    # seconds. Cap at the executor's max_timeout.
                    self._send_and_read(entry, timeout=self._max_timeout)
                except Exception as exc:
                    logger.warning(
                        "Persistent executor history replay failed on entry"
                        " (%d bytes): %s — aborting replay, history retained.",
                        len(entry),
                        exc,
                    )
                    break
        finally:
            self._replaying = False

    def _record_history(self, code: str) -> None:
        """Append a successful code entry to history, evicting oldest if needed."""
        if self._replaying:
            return
        self._history.append(code)
        self._history_bytes += len(code)
        # Evict oldest entries until caps are satisfied.
        while self._history and (
            len(self._history) > _HISTORY_MAX_ENTRIES
            or self._history_bytes > _HISTORY_MAX_BYTES
        ):
            dropped = self._history.pop(0)
            self._history_bytes -= len(dropped)

    def _hard_kill_from_watchdog(self) -> None:
        """Framework-Fix δ2: forcibly terminate the warm subprocess.

        Called by a ``threading.Timer`` armed in ``execute()`` with a
        ``effective_timeout + _HARD_KILL_GRACE_SECONDS`` delay. If the
        cooperative select-based deadline in ``_send_and_read`` fires on
        schedule, it calls ``_kill_process()`` itself and the Timer will
        find no live process here — that is the expected happy path.
        This function is the backstop for the edge case where the read
        thread is wedged inside ``os.read`` and the deadline never
        materializes.

        The method is invoked from a Timer thread, not from the main
        thread holding ``self._lock``. Mutating ``self._proc`` from a
        second thread is safe because Popen.kill / Popen.wait are
        thread-safe and the main thread's subsequent read will surface
        either EOF or the cached residual — both are already handled.
        """
        proc = self._proc
        if proc is None:
            return
        try:
            if proc.poll() is None:
                logger.warning(
                    "δ2 watchdog: warm subprocess pid=%s exceeded deadline"
                    " + %ds grace — SIGKILL",
                    proc.pid,
                    _HARD_KILL_GRACE_SECONDS,
                )
                proc.kill()
                try:
                    proc.wait(timeout=2)
                except Exception:  # noqa: BLE001
                    pass
                self._hard_killed = True
                # Best-effort: null out the handle so the main thread's
                # residual read either sees EOF or a closed pipe.
                self._proc = None
                self._read_residual = b""
                self._needs_replay = True
        except Exception:  # noqa: BLE001
            logger.debug("δ2 watchdog: kill raised (non-fatal)", exc_info=True)

    def execute(
        self,
        code: str,
        timeout: Optional[int] = None,
    ) -> dict[str, Any]:
        """Execute code in the warm subprocess."""
        effective_timeout = min(timeout or self._max_timeout, self._max_timeout)

        with self._lock:
            # Framework-Fix δ2: arm the hard-kill Timer BEFORE entering
            # _execute_warm. The Timer is our structural backstop in case
            # the cooperative select-based deadline in _send_and_read does
            # not fire (e.g. read thread stuck inside os.read). On a normal
            # return we cancel it; on a hard-kill fire we detect via the
            # _hard_killed flag and fall through to the cold executor so
            # the caller still sees a structured response.
            self._hard_killed = False
            kill_timer = threading.Timer(
                effective_timeout + _HARD_KILL_GRACE_SECONDS,
                self._hard_kill_from_watchdog,
            )
            kill_timer.daemon = True
            kill_timer.start()
            try:
                warm_result: dict[str, Any] | None = None
                warm_error: Exception | None = None
                try:
                    warm_result = self._execute_warm(code, effective_timeout)
                except Exception as exc:  # noqa: BLE001
                    warm_error = exc

                # Framework-Fix δ2: if the backstop Timer fired, the warm
                # path is not trustworthy regardless of whether it raised
                # or returned. Per the δ2 contract we fall through to
                # ``_execute_cold`` so the caller still gets a structured
                # response instead of a raw exception or partial data.
                if self._hard_killed:
                    logger.warning(
                        "δ2 watchdog: hard-kill during execute(code_len=%d,"
                        " timeout=%ds) — cold fallback",
                        len(code),
                        effective_timeout,
                    )
                    # History NOT recorded: a call that got killed may have
                    # mutated shared state in an unrepeatable way; replaying
                    # it on restart could wedge the new subprocess too.
                    return self._execute_cold(code, effective_timeout)

                if warm_error is not None:
                    logger.warning(
                        "Persistent executor failed (%s), falling back to cold start",
                        warm_error,
                    )
                    # Kill broken process; history is preserved so the next call
                    # can try warm again and replay state into a fresh subprocess.
                    self._kill_process()
                    return self._execute_cold(code, effective_timeout)

                assert warm_result is not None  # reachable only on clean return
                # Fix α-1-extra: record every call that produced a structured
                # result (ok or not) so the consumer's code is replayed on
                # restart. Errors are still recorded — consumers may rely on
                # them for diagnostic flows. Timeouts are NOT recorded (status
                # 408) because replaying a hang would deadlock the restart.
                if warm_result.get("status") != 408:
                    self._record_history(code)
                return warm_result
            finally:
                kill_timer.cancel()

    def _send_and_read(self, code: str, timeout: int) -> dict[str, Any]:
        """Send one command to the warm subprocess and read its reply.

        Shared between normal execute and silent history replay. Raises on
        protocol-level failure; returns the parsed result dict on success.
        """
        proc = self._ensure_process()
        assert proc.stdin is not None and proc.stdout is not None

        cmd = json.dumps({
            "code": code,
            "cwd": str(self._cwd) if self._cwd else None,
        })
        proc.stdin.write((cmd + "\n").encode("utf-8"))
        proc.stdin.flush()

        # Fix Z3: non-blocking read with proper deadline enforcement.
        # We operate directly on the raw pipe fd with os.read() and a
        # private byte buffer, splitting lines ourselves. This avoids
        # Python's TextIOWrapper/BufferedReader pre-fetching bytes into
        # an internal buffer that select() cannot see — the bug that
        # previously made the deadline check never fire.
        lines: list[str] = []
        deadline = time.monotonic() + timeout
        fd = proc.stdout.fileno()
        buffer = self._read_residual
        self._read_residual = b""
        sentinel_bytes = _SENTINEL.encode("utf-8")

        def _pop_line() -> bytes | None:
            nonlocal buffer
            idx = buffer.find(b"\n")
            if idx < 0:
                return None
            line = buffer[:idx]
            buffer = buffer[idx + 1:]
            return line

        done = False
        while not done:
            # 1) Drain any complete lines already in our private buffer.
            while True:
                line = _pop_line()
                if line is None:
                    break
                if line == sentinel_bytes:
                    done = True
                    break
                lines.append(line.decode("utf-8", errors="replace"))
            if done:
                break

            # 2) No complete line available: wait on the fd with the
            # remaining deadline, then read a chunk.
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self._kill_process()
                return {
                    "ok": False,
                    "status": 408,
                    "data": {},
                    "error": f"Code execution timed out after {timeout}s",
                }

            ready, _, _ = select.select([fd], [], [], remaining)
            if not ready:
                # select itself timed out — child is hung.
                self._kill_process()
                return {
                    "ok": False,
                    "status": 408,
                    "data": {},
                    "error": f"Code execution timed out after {timeout}s",
                }

            try:
                chunk = os.read(fd, 65536)
            except OSError as exc:
                self._kill_process()
                raise RuntimeError(
                    f"Persistent subprocess pipe read failed: {exc}"
                ) from exc
            if not chunk:
                # EOF: process died.
                self._kill_process()
                raise RuntimeError("Persistent subprocess died unexpectedly")
            buffer += chunk

        # Preserve any bytes that arrived after the sentinel for next call.
        self._read_residual = buffer

        if not lines:
            raise RuntimeError("Empty response from persistent subprocess")

        result = json.loads(lines[0])
        stdout = result.get("stdout", "")[: self._max_output]
        stderr = result.get("stderr", "")[: self._max_output]

        if result.get("ok"):
            return {
                "ok": True,
                "status": 200,
                "data": {
                    "stdout": stdout,
                    "stderr": stderr,
                    "returncode": result.get("returncode", 0),
                },
                "error": None,
            }
        return {
            "ok": False,
            "status": 500,
            "data": {
                "stdout": stdout,
                "stderr": stderr,
                "returncode": result.get("returncode", 1),
            },
            "error": stderr[:2000] if stderr else f"Exit code {result.get('returncode', 1)}",
        }

    def _execute_warm(self, code: str, timeout: int) -> dict[str, Any]:
        """Send code to warm subprocess and read result."""
        return self._send_and_read(code, timeout)

    def _execute_cold(self, code: str, timeout: int) -> dict[str, Any]:
        """Fallback: execute in a fresh subprocess (same as CodeExecutor)."""
        import tempfile

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False, encoding="utf-8"
        ) as tmp:
            tmp.write(code)
            tmp_path = tmp.name

        try:
            result = subprocess.run(
                [sys.executable, tmp_path],
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=str(self._cwd) if self._cwd else None,
            )
            stdout = result.stdout[: self._max_output]
            stderr = result.stderr[: self._max_output]
            if result.returncode == 0:
                return {
                    "ok": True,
                    "status": 200,
                    "data": {"stdout": stdout, "stderr": stderr, "returncode": 0},
                    "error": None,
                }
            return {
                "ok": False,
                "status": 500,
                "data": {"stdout": stdout, "stderr": stderr, "returncode": result.returncode},
                "error": stderr[:2000] or f"Exit code {result.returncode}",
            }
        except subprocess.TimeoutExpired:
            return {
                "ok": False,
                "status": 408,
                "data": {},
                "error": f"Code execution timed out after {timeout}s",
            }
        finally:
            try:
                Path(tmp_path).unlink(missing_ok=True)
            except Exception:
                pass

    def _kill_process(self) -> None:
        """Kill the persistent subprocess.

        If the child produced output on the merged stdout+stderr stream that
        we never consumed (e.g. a fatal import error before the worker loop
        started), try to drain and log it so the root cause is visible.
        """
        if self._proc is not None:
            # Mark that the next spawn should replay recorded history so
            # the caller sees a warm namespace again. We do this whether
            # the process is still alive (we're killing it) or already
            # dead (we're just cleaning up): in both cases the *next*
            # subprocess is fresh and needs re-priming.
            self._needs_replay = True
            try:
                self._proc.kill()
                self._proc.wait(timeout=2)
            except Exception:
                pass
            # Best-effort drain of merged stdout+stderr so an interpreter-
            # level crash message is logged rather than silently discarded.
            try:
                stdout = self._proc.stdout
                if stdout is not None:
                    try:
                        fd = stdout.fileno()
                        ready, _, _ = select.select([fd], [], [], 0)
                        if ready:
                            leftover = os.read(fd, 65536)
                            if leftover:
                                logger.debug(
                                    "Persistent subprocess leftover output on kill:"
                                    " %s",
                                    leftover[:2000],
                                )
                    except Exception:
                        pass
            finally:
                self._proc = None
                self._read_residual = b""

    def cleanup(self) -> None:
        """Shut down the persistent subprocess."""
        self._kill_process()

    def __del__(self) -> None:
        self.cleanup()
