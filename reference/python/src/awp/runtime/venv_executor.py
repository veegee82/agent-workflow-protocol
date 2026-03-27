"""AWP Venv Executor -- Virtual-environment-based Python sandbox.

Runs Python code using a dedicated virtual environment with pre-installed
packages. Lighter weight than Docker but with less isolation.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Optional

from .base_executor import BaseExecutor

logger = logging.getLogger(__name__)


class VenvExecutor(BaseExecutor):
    """Python venv-based code sandbox.

    Creates (or reuses) a virtual environment with specified packages
    and executes code using the venv's Python interpreter.

    Args:
        max_timeout: Maximum allowed timeout in seconds.
        max_output_bytes: Maximum stdout/stderr size in bytes.
        working_dir: Working directory for code execution.
        packages: Pip packages to install in the venv.
        pip_install: Whether runtime pip install is allowed for additional packages.
        venv_dir: Explicit venv directory path (default: working_dir/.awp-venv).
    """

    def __init__(
        self,
        max_timeout: int = 30,
        max_output_bytes: int = 1_048_576,
        working_dir: Optional[Path] = None,
        packages: Optional[list[str]] = None,
        pip_install: bool = False,
        venv_dir: Optional[Path] = None,
    ) -> None:
        self._max_timeout = max_timeout
        self._max_output = max_output_bytes
        self._cwd = working_dir
        self._packages = packages or []
        self._pip_install = pip_install

        # Determine venv location
        if venv_dir:
            self._venv_dir = Path(venv_dir)
        elif working_dir:
            self._venv_dir = Path(working_dir) / ".awp-venv"
        else:
            self._venv_dir = Path(tempfile.mkdtemp(prefix="awp_venv_"))

        self._python_path: Optional[Path] = None
        self._setup_venv()

    def _setup_venv(self) -> None:
        """Create the venv and install packages if needed."""
        venv_python = self._venv_dir / "bin" / "python"

        if not venv_python.exists():
            logger.info("Creating virtual environment at %s", self._venv_dir)
            try:
                subprocess.run(
                    [sys.executable, "-m", "venv", str(self._venv_dir)],
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
            except subprocess.CalledProcessError as exc:
                raise RuntimeError(
                    f"Failed to create venv at {self._venv_dir}: "
                    f"{exc.stderr if exc.stderr else exc}"
                ) from exc

        self._python_path = venv_python

        # Install packages
        if self._packages:
            self._install_packages(self._packages)

    def _install_packages(self, packages: list[str]) -> None:
        """Install pip packages into the venv."""
        pip_path = self._venv_dir / "bin" / "pip"
        logger.info("Installing packages in venv: %s", ", ".join(packages))
        try:
            subprocess.run(
                [str(pip_path), "install", "--quiet"] + packages,
                check=True,
                capture_output=True,
                text=True,
                timeout=300,  # 5 min for large packages
            )
            logger.info("Packages installed successfully")
        except subprocess.CalledProcessError as exc:
            logger.warning(
                "Failed to install packages: %s",
                exc.stderr[:500] if exc.stderr else str(exc),
            )

    def execute(
        self,
        code: str,
        timeout: Optional[int] = None,
    ) -> dict[str, Any]:
        """Execute Python code using the venv's Python interpreter.

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
                [str(self._python_path), tmp_path],
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

    def install_runtime_packages(self, packages: list[str]) -> dict[str, Any]:
        """Install additional packages at runtime (if pip_install is enabled).

        Args:
            packages: List of pip package names to install.

        Returns:
            Standard AWP result format.
        """
        if not self._pip_install:
            return {
                "ok": False,
                "status": 403,
                "data": {},
                "error": "Runtime pip install is not enabled (set pip_install: true)",
            }
        self._install_packages(packages)
        return {
            "ok": True,
            "status": 200,
            "data": {"installed": packages},
            "error": None,
        }

    def cleanup(self) -> None:
        """Remove the virtual environment directory."""
        if self._venv_dir and self._venv_dir.exists():
            logger.info("Cleaning up venv at %s", self._venv_dir)
            shutil.rmtree(self._venv_dir, ignore_errors=True)
