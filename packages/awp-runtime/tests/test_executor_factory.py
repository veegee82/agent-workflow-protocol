"""Tests for the executor factory, sandbox type routing, and pip.install tool."""

import pytest

from awp.models.capabilities import SandboxConfig
from awp.runtime.base_executor import BaseExecutor
from awp.runtime.code_executor import CodeExecutor
from awp.runtime.executor_factory import create_executor
from awp.runtime.persistent_executor import PersistentExecutor
from awp.runtime.tools import ToolRegistry


class TestExecutorFactory:
    def test_default_returns_base_executor(self):
        executor = create_executor()
        assert isinstance(executor, BaseExecutor)

    def test_subprocess_returns_persistent_executor(self):
        config = SandboxConfig(type="subprocess")
        executor = create_executor(config)
        assert isinstance(executor, (PersistentExecutor, CodeExecutor))

    def test_none_type_returns_executor(self):
        config = SandboxConfig(type="none")
        executor = create_executor(config)
        assert isinstance(executor, BaseExecutor)

    def test_unknown_type_falls_back_to_subprocess(self):
        config = SandboxConfig(type="wasm")
        executor = create_executor(config)
        assert isinstance(executor, BaseExecutor)

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

    def test_pip_install_default_true(self):
        config = SandboxConfig()
        assert config.pip_install is True


class TestPipInstallTool:
    def test_pip_install_registered_after_set_code_executor(self):
        registry = ToolRegistry()
        assert "pip.install" not in registry.tool_names
        executor = CodeExecutor()
        registry.set_code_executor(executor)
        assert "pip.install" in registry.tool_names

    def test_pip_install_without_executor(self):
        registry = ToolRegistry()
        # Force-register to test the handler without an executor
        registry.set_code_executor(None)
        result = registry.call("pip.install", {"packages": ["numpy"]})
        assert result["ok"] is False
        assert result["status"] == 503

    def test_pip_install_calls_executor(self, tmp_path):
        registry = ToolRegistry()
        executor = CodeExecutor()
        registry.set_code_executor(executor)
        # Install an empty list — fast, no network needed
        result = registry.call("pip.install", {"packages": []})
        assert result["ok"] is True
        assert result["data"]["installed"] == []

    def test_pip_install_definition_schema(self):
        registry = ToolRegistry()
        registry.set_code_executor(CodeExecutor())
        defs = registry.get_definitions(allowed=["pip.install"])
        assert len(defs) == 1
        func_def = defs[0]["function"]
        assert func_def["name"] == "pip.install"
        assert "packages" in func_def["parameters"]["properties"]
