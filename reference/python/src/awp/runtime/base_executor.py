"""AWP Base Executor -- Abstract interface for code execution sandboxes.

All executor implementations (subprocess, Docker, venv) implement this
interface so that the rest of the runtime can treat them interchangeably.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional


class BaseExecutor(ABC):
    """Abstract base class for AWP code execution sandboxes.

    Every executor must implement ``execute()`` and ``cleanup()``.
    ``validate_code()`` has a default AST-based implementation that
    subclasses may override.
    """

    @abstractmethod
    def execute(
        self,
        code: str,
        timeout: Optional[int] = None,
    ) -> dict[str, Any]:
        """Execute Python code in the sandbox.

        Args:
            code: Python source code to execute.
            timeout: Timeout in seconds (capped by implementation limits).

        Returns:
            Standard AWP result format::

                {
                    "ok": bool,
                    "status": int,
                    "data": {"stdout": str, "stderr": str, "returncode": int},
                    "error": str | None,
                }
        """

    def validate_code(self, code: str) -> dict[str, Any]:
        """Validate Python code via AST parsing without execution.

        Args:
            code: Python source code to validate.

        Returns:
            Standard AWP result format with validation status.
        """
        import ast

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

    def install_runtime_packages(self, packages: list[str]) -> dict[str, Any]:
        """Install additional pip packages at runtime.

        The default implementation uses the current Python's pip.
        Subclasses may override for sandbox-specific installation.

        Args:
            packages: List of pip package specifiers to install.

        Returns:
            Standard AWP result format.
        """
        import subprocess
        import sys

        if not packages:
            return {
                "ok": True,
                "status": 200,
                "data": {"installed": []},
                "error": None,
            }
        try:
            subprocess.run(
                [sys.executable, "-m", "pip", "install", "--quiet"] + packages,
                check=True,
                capture_output=True,
                text=True,
                timeout=300,
            )
            return {
                "ok": True,
                "status": 200,
                "data": {"installed": packages},
                "error": None,
            }
        except subprocess.CalledProcessError as exc:
            return {
                "ok": False,
                "status": 500,
                "data": {},
                "error": f"pip install failed: {exc.stderr[:500] if exc.stderr else str(exc)}",
            }
        except subprocess.TimeoutExpired:
            return {
                "ok": False,
                "status": 408,
                "data": {},
                "error": "pip install timed out after 300s",
            }

    def cleanup(self) -> None:
        """Clean up sandbox resources. Called at workflow completion."""
