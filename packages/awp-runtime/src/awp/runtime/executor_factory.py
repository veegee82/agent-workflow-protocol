"""AWP Executor Factory -- Creates the right executor based on sandbox config.

Reads ``SandboxConfig.type`` and returns the appropriate executor instance.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from awp.models.capabilities import SandboxConfig
from .base_executor import BaseExecutor

logger = logging.getLogger(__name__)


def create_executor(
    config: Optional[SandboxConfig] = None,
    working_dir: Optional[Path] = None,
) -> BaseExecutor:
    """Create an executor instance based on sandbox configuration.

    Args:
        config: Sandbox configuration. Defaults to subprocess if None.
        working_dir: Working directory for code execution.

    Returns:
        A BaseExecutor instance matching the configured sandbox type.

    Raises:
        RuntimeError: If Docker is required but not available.
    """
    if config is None:
        config = SandboxConfig()

    sandbox_type = config.type

    if sandbox_type == "docker":
        from .docker_executor import DockerExecutor

        logger.info(
            "Creating Docker executor (image=%s, packages=%s)",
            config.image,
            config.packages,
        )
        return DockerExecutor(
            image=config.image,
            max_timeout=config.timeout,
            max_output_bytes=config.max_output_bytes,
            working_dir=working_dir,
            network_access=config.network_access,
            max_memory_mb=config.max_memory_mb,
            packages=config.packages,
            pip_install=config.pip_install,
        )

    elif sandbox_type == "venv":
        from .venv_executor import VenvExecutor

        logger.info(
            "Creating Venv executor (packages=%s)",
            config.packages,
        )
        return VenvExecutor(
            max_timeout=config.timeout,
            max_output_bytes=config.max_output_bytes,
            working_dir=working_dir,
            packages=config.packages,
            pip_install=config.pip_install,
        )

    else:
        # Default: subprocess-based executor
        from .code_executor import CodeExecutor

        if sandbox_type not in ("subprocess", "none"):
            logger.warning(
                "Sandbox type '%s' is not implemented, falling back to subprocess",
                sandbox_type,
            )
        return CodeExecutor(
            max_timeout=config.timeout,
            max_output_bytes=config.max_output_bytes,
            working_dir=working_dir,
        )
