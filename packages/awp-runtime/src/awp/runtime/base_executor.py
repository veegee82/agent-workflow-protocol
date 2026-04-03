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

        # Sanitize package names to prevent command injection
        sanitized = []
        for pkg in packages:
            # Strip any shell metacharacters; allow only safe pip specifiers
            clean = pkg.strip()
            if clean and not any(c in clean for c in (";", "&", "|", "`", "$", "\n")):
                sanitized.append(clean)
        if not sanitized:
            return {
                "ok": False,
                "status": 400,
                "data": {},
                "error": "No valid package names provided after sanitization",
            }

        try:
            result = subprocess.run(
                [sys.executable, "-m", "pip", "install", "--quiet"] + sanitized,
                check=True,
                capture_output=True,
                text=True,
                timeout=300,
            )
            return {
                "ok": True,
                "status": 200,
                "data": {
                    "installed": sanitized,
                    "stderr": result.stderr[:500] if result.stderr else "",
                },
                "error": None,
            }
        except subprocess.CalledProcessError as exc:
            stderr = exc.stderr[:500] if exc.stderr else str(exc)
            stdout = exc.stdout[:500] if exc.stdout else ""
            return {
                "ok": False,
                "status": 500,
                "data": {"stdout": stdout, "stderr": stderr},
                "error": f"pip install failed: {stderr}",
            }
        except subprocess.TimeoutExpired:
            return {
                "ok": False,
                "status": 408,
                "data": {},
                "error": "pip install timed out after 300s",
            }
        except FileNotFoundError:
            return {
                "ok": False,
                "status": 500,
                "data": {},
                "error": (
                    f"Python executable not found: {sys.executable}. "
                    f"pip cannot be invoked."
                ),
            }

    def cleanup(self) -> None:
        """Clean up sandbox resources. Called at workflow completion."""
