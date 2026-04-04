"""AWP Docker Executor -- Container-based Python sandbox.

Runs Python code inside Docker containers with full package support.
Pre-built images include common data-science packages; optional runtime
pip install for additional packages.
"""

from __future__ import annotations

import base64
import logging
import shlex
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Optional

from .base_executor import BaseExecutor, sanitize_pip_specs

logger = logging.getLogger(__name__)


class DockerExecutor(BaseExecutor):
    """Docker container-based Python code sandbox.

    Executes code inside a disposable Docker container with configurable
    resource limits, network isolation, and file output capture.

    Args:
        image: Docker image name (should have Python + packages pre-installed).
        max_timeout: Maximum allowed timeout in seconds.
        max_output_bytes: Maximum stdout/stderr size in bytes.
        working_dir: Host working directory (mounted read-only for input data).
        network_access: Whether the container has network access.
        max_memory_mb: Container memory limit in MB.
        packages: Additional pip packages to install at runtime.
        pip_install: Whether runtime pip install is allowed.
    """

    def __init__(
        self,
        image: str = "awp-sandbox-python",
        max_timeout: int = 30,
        max_output_bytes: int = 1_048_576,
        working_dir: Optional[Path] = None,
        network_access: bool = False,
        max_memory_mb: int = 256,
        packages: Optional[list[str]] = None,
        pip_install: bool = True,
    ) -> None:
        self._image = image
        self._max_timeout = max_timeout
        self._max_output = max_output_bytes
        self._cwd = working_dir
        self._network_access = network_access
        self._max_memory_mb = max_memory_mb
        self._packages = packages or []
        self._pip_install = pip_install

        # Verify Docker is available
        self._docker_cmd = shutil.which("docker")
        if not self._docker_cmd:
            raise RuntimeError(
                "Docker is not installed or not in PATH. "
                "Install Docker or use sandbox type 'subprocess' or 'venv'."
            )

    def execute(
        self,
        code: str,
        timeout: Optional[int] = None,
    ) -> dict[str, Any]:
        """Execute Python code inside a Docker container.

        Args:
            code: Python source code to execute.
            timeout: Timeout in seconds (capped by max_timeout).

        Returns:
            Standard AWP result format with stdout, stderr, returncode,
            and optional output files.
        """
        effective_timeout = min(timeout or self._max_timeout, self._max_timeout)

        # Create temp directory for code and output
        tmpdir = Path(tempfile.mkdtemp(prefix="awp_docker_"))
        script_path = tmpdir / "script.py"
        output_dir = tmpdir / "output"
        output_dir.mkdir()

        try:
            # Write the script
            script_path.write_text(code, encoding="utf-8")

            # Build docker run command
            cmd = [
                self._docker_cmd,
                "run",
                "--rm",
                f"--memory={self._max_memory_mb}m",
                f"--network={'bridge' if self._network_access else 'none'}",
                "--cpus=1",
                # Mount script and output directory
                "-v",
                f"{tmpdir}:/workspace:rw",
                # Set working directory
                "-w",
                "/workspace",
            ]

            # Build the in-container command
            container_cmd = []

            # Optional runtime pip install (shell-quoted to prevent injection)
            if self._pip_install and self._packages:
                quoted_pkgs = " ".join(shlex.quote(p) for p in self._packages)
                pip_cmd = f"pip install --quiet {quoted_pkgs} && "
                container_cmd.append("sh")
                container_cmd.append("-c")
                container_cmd.append(f"{pip_cmd}python /workspace/script.py")
            else:
                container_cmd.append("python")
                container_cmd.append("/workspace/script.py")

            cmd.append(self._image)
            cmd.extend(container_cmd)

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=effective_timeout + 5,  # Extra buffer for container startup
            )

            stdout = result.stdout[: self._max_output]
            stderr = result.stderr[: self._max_output]

            # Collect output files (plots, CSVs, etc.)
            output_files = self._collect_output_files(output_dir)

            data = {
                "stdout": stdout,
                "stderr": stderr,
                "returncode": result.returncode,
            }
            if output_files:
                data["files"] = output_files

            if result.returncode == 0:
                return {
                    "ok": True,
                    "status": 200,
                    "data": data,
                    "error": None,
                }
            else:
                return {
                    "ok": False,
                    "status": 500,
                    "data": data,
                    "error": stderr[:500]
                    if stderr
                    else f"Exit code {result.returncode}",
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
            # Clean up temp directory
            shutil.rmtree(tmpdir, ignore_errors=True)

    def _collect_output_files(self, output_dir: Path) -> list[dict[str, str]]:
        """Collect files from the output directory.

        Returns a list of dicts with name, type, and base64-encoded content.
        """
        files = []
        if not output_dir.exists():
            return files

        for fpath in sorted(output_dir.iterdir()):
            if not fpath.is_file():
                continue
            try:
                content = fpath.read_bytes()
                files.append(
                    {
                        "name": fpath.name,
                        "size": len(content),
                        "content_base64": base64.b64encode(content).decode("ascii"),
                    }
                )
            except Exception as exc:
                logger.warning("Failed to read output file %s: %s", fpath.name, exc)

        return files

    def install_runtime_packages(self, packages: list[str]) -> dict[str, Any]:
        """Install additional packages by running pip inside a Docker container.

        Args:
            packages: List of pip package specifiers to install.

        Returns:
            Standard AWP result format.
        """
        if not packages:
            return {
                "ok": True,
                "status": 200,
                "data": {"installed": []},
                "error": None,
            }
        # Sanitize before queuing
        sanitized, rejected = sanitize_pip_specs(packages)
        if rejected:
            logger.warning("Rejected pip specs in docker: %s", "; ".join(rejected))
        if not sanitized:
            return {
                "ok": False,
                "status": 400,
                "data": {"rejected": rejected},
                "error": (
                    "No valid package names after sanitization. "
                    f"Rejected: {'; '.join(rejected)}"
                ),
            }
        # Add to the pre-install list so subsequent execute() calls include them.
        # Deduplicate: keep only the last version specifier for each package.
        existing = {p.split(">=")[0].split("==")[0].split("<")[0].strip().lower()
                     for p in self._packages}
        for pkg in sanitized:
            base_name = pkg.split(">=")[0].split("==")[0].split("<")[0].strip().lower()
            if base_name not in existing:
                self._packages.append(pkg)
                existing.add(base_name)
        return {
            "ok": True,
            "status": 200,
            "data": {"installed": packages, "total_queued": len(self._packages)},
            "error": None,
        }

    def cleanup(self) -> None:
        """No persistent state to clean up for Docker executor."""
