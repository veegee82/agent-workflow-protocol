"""AWP Code Executor -- Subprocess-based Python sandbox.

Runs Python code in a subprocess with timeout and output capture.
This is the reference implementation; production deployments can use
Docker, WASM, or V8 Isolate sandboxes.
"""

from __future__ import annotations

import ast
import logging
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Optional

from .base_executor import BaseExecutor

logger = logging.getLogger(__name__)


class CodeExecutor(BaseExecutor):
    """Subprocess-based Python code sandbox.

    Args:
        max_timeout: Maximum allowed timeout in seconds.
        max_output_bytes: Maximum stdout/stderr size in bytes.
        working_dir: Working directory for code execution.
    """

    def __init__(
        self,
        max_timeout: int = 30,
        max_output_bytes: int = 1_048_576,
        working_dir: Optional[Path] = None,
    ) -> None:
        self._max_timeout = max_timeout
        self._max_output = max_output_bytes
        self._cwd = working_dir

    def execute(
        self,
        code: str,
        timeout: Optional[int] = None,
    ) -> dict[str, Any]:
        """Execute Python code in a sandboxed subprocess.

        Args:
            code: Python source code to execute.
            timeout: Timeout in seconds (capped by max_timeout).

        Returns:
            Standard AWP result format with stdout, stderr, returncode.
        """
        effective_timeout = min(timeout or self._max_timeout, self._max_timeout)

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False, encoding="utf-8",
        ) as tmp:
            tmp.write(code)
            tmp_path = tmp.name

        try:
            result = subprocess.run(
                [sys.executable, tmp_path],
                capture_output=True,
                text=True,
                timeout=effective_timeout,
                cwd=str(self._cwd) if self._cwd else None,
            )

            stdout = result.stdout[:self._max_output]
            stderr = result.stderr[:self._max_output]

            if result.returncode == 0:
                return {
                    "ok": True,
                    "status": 200,
                    "data": {
                        "stdout": stdout,
                        "stderr": stderr,
                        "returncode": result.returncode,
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
                        "returncode": result.returncode,
                    },
                    "error": stderr[:500] if stderr else f"Exit code {result.returncode}",
                }

        except subprocess.TimeoutExpired:
            return {
                "ok": False,
                "status": 408,
                "data": {},
                "error": f"Code execution timed out after {effective_timeout}s",
            }
        except Exception as exc:
            return {
                "ok": False,
                "status": 500,
                "data": {},
                "error": str(exc),
            }
        finally:
            try:
                Path(tmp_path).unlink(missing_ok=True)
            except Exception:
                pass

    def validate_code(self, code: str) -> dict[str, Any]:
        """Validate Python code via AST parsing without execution.

        Args:
            code: Python source code to validate.

        Returns:
            Standard AWP result format with validation status.
        """
        try:
            ast.parse(code)
            return {
                "ok": True,
                "status": 200,
                "data": {"valid": True},
                "error": None,
            }
        except SyntaxError as e:
            return {
                "ok": False,
                "status": 400,
                "data": {"valid": False},
                "error": f"Syntax error: {e}",
            }
