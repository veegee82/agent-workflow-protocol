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

    def cleanup(self) -> None:
        """Clean up sandbox resources. Called at workflow completion."""
