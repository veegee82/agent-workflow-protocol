"""AWP Persistent Code Executor -- Warm subprocess pool for fast code execution.

Keeps a Python subprocess alive between ``code.execute`` calls so that
heavy imports (numpy, pandas, matplotlib) are loaded once and reused.
Falls back to the standard cold-start ``CodeExecutor`` if the persistent
process dies.
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
import textwrap
import threading
from pathlib import Path
from typing import Any, Optional

from .base_executor import BaseExecutor

logger = logging.getLogger(__name__)

# Protocol: the warm subprocess reads JSON commands from stdin and writes
# JSON results to stdout, using a sentinel line to delimit responses.
_SENTINEL = "__AWP_EXEC_DONE__"

_WORKER_SCRIPT = textwrap.dedent(f"""\
    import json, sys, traceback, io, os

    SENTINEL = "{_SENTINEL}"

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
                exec(code, {{"__name__": "__main__"}})
            except SystemExit as e:
                returncode = int(e.code) if e.code else 0
            except Exception:
                traceback.print_exc(file=buf_err)
                returncode = 1
            finally:
                sys.stdout, sys.stderr = old_out, old_err

            result = {{
                "ok": returncode == 0,
                "stdout": buf_out.getvalue(),
                "stderr": buf_err.getvalue(),
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

        if packages and (pip_install or packages):
            self.install_runtime_packages(packages)

    def _ensure_process(self) -> subprocess.Popen:
        """Start the persistent subprocess if not already running."""
        if self._proc is not None and self._proc.poll() is None:
            return self._proc
        logger.debug("Starting persistent Python subprocess")
        self._proc = subprocess.Popen(
            [sys.executable, "-u", "-c", _WORKER_SCRIPT],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=str(self._cwd) if self._cwd else None,
        )
        return self._proc

    def execute(
        self,
        code: str,
        timeout: Optional[int] = None,
    ) -> dict[str, Any]:
        """Execute code in the warm subprocess."""
        effective_timeout = min(timeout or self._max_timeout, self._max_timeout)

        with self._lock:
            try:
                return self._execute_warm(code, effective_timeout)
            except Exception as exc:
                logger.warning(
                    "Persistent executor failed (%s), falling back to cold start",
                    exc,
                )
                # Kill broken process
                self._kill_process()
                return self._execute_cold(code, effective_timeout)

    def _execute_warm(self, code: str, timeout: int) -> dict[str, Any]:
        """Send code to warm subprocess and read result."""
        proc = self._ensure_process()
        assert proc.stdin is not None and proc.stdout is not None

        cmd = json.dumps({
            "code": code,
            "cwd": str(self._cwd) if self._cwd else None,
        })
        proc.stdin.write(cmd + "\n")
        proc.stdin.flush()

        # Read response until sentinel
        lines: list[str] = []
        import select
        import time

        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self._kill_process()
                return {
                    "ok": False,
                    "status": 408,
                    "data": {},
                    "error": f"Code execution timed out after {timeout}s",
                }

            line = proc.stdout.readline()
            if not line:
                # Process died
                self._kill_process()
                raise RuntimeError("Persistent subprocess died unexpectedly")

            stripped = line.rstrip("\n")
            if stripped == _SENTINEL:
                break
            lines.append(stripped)

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
        else:
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
        """Kill the persistent subprocess."""
        if self._proc is not None:
            try:
                self._proc.kill()
                self._proc.wait(timeout=2)
            except Exception:
                pass
            self._proc = None

    def cleanup(self) -> None:
        """Shut down the persistent subprocess."""
        self._kill_process()

    def __del__(self) -> None:
        self.cleanup()
