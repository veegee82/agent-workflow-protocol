"""Tests for the executor factory and sandbox type routing."""

import pytest

from awp.models.capabilities import SandboxConfig
from awp.runtime.base_executor import BaseExecutor
from awp.runtime.code_executor import CodeExecutor
from awp.runtime.executor_factory import create_executor


class TestExecutorFactory:
    def test_default_returns_code_executor(self):
        executor = create_executor()
        assert isinstance(executor, CodeExecutor)

    def test_subprocess_returns_code_executor(self):
        config = SandboxConfig(type="subprocess")
        executor = create_executor(config)
        assert isinstance(executor, CodeExecutor)

    def test_none_type_returns_code_executor(self):
        config = SandboxConfig(type="none")
        executor = create_executor(config)
        assert isinstance(executor, CodeExecutor)

    def test_unknown_type_falls_back_to_subprocess(self):
        config = SandboxConfig(type="wasm")
        executor = create_executor(config)
        assert isinstance(executor, CodeExecutor)

    def test_venv_returns_venv_executor(self, tmp_path):
        config = SandboxConfig(type="venv", packages=[])
        executor = create_executor(config, working_dir=tmp_path)
        from awp.runtime.venv_executor import VenvExecutor
        assert isinstance(executor, VenvExecutor)
        executor.cleanup()

    def test_docker_without_docker_raises(self, monkeypatch):
        """If Docker is not installed, DockerExecutor should raise."""
        import shutil
        monkeypatch.setattr(shutil, "which", lambda x: None)
        config = SandboxConfig(type="docker")
        with pytest.raises(RuntimeError, match="Docker is not installed"):
            create_executor(config)

    def test_all_executors_are_base_executor(self, tmp_path):
        # subprocess
        config = SandboxConfig(type="subprocess")
        executor = create_executor(config)
        assert isinstance(executor, BaseExecutor)

        # venv
        config = SandboxConfig(type="venv", packages=[])
        executor = create_executor(config, working_dir=tmp_path)
        assert isinstance(executor, BaseExecutor)
        executor.cleanup()

    def test_config_passthrough(self, tmp_path):
        config = SandboxConfig(type="subprocess", timeout=15, max_output_bytes=512)
        executor = create_executor(config)
        assert executor._max_timeout == 15
        assert executor._max_output == 512
