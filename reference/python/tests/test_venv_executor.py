"""Tests for the venv-based code executor."""

import pytest

from awp.runtime.venv_executor import VenvExecutor


class TestVenvExecutor:
    @pytest.fixture
    def executor(self, tmp_path):
        """Create a VenvExecutor with a temporary venv directory."""
        ex = VenvExecutor(
            max_timeout=10,
            working_dir=tmp_path,
            packages=[],
            venv_dir=tmp_path / ".test-venv",
        )
        yield ex
        ex.cleanup()

    def test_simple_execution(self, executor):
        result = executor.execute("print('hello from venv')")
        assert result["ok"] is True
        assert "hello from venv" in result["data"]["stdout"]

    def test_stdlib_import(self, executor):
        code = "import json; print(json.dumps({'a': 1}))"
        result = executor.execute(code)
        assert result["ok"] is True
        assert '"a": 1' in result["data"]["stdout"]

    def test_error_handling(self, executor):
        result = executor.execute("raise RuntimeError('venv error')")
        assert result["ok"] is False
        assert "venv error" in result["data"]["stderr"]

    def test_timeout(self, tmp_path):
        executor = VenvExecutor(
            max_timeout=1,
            working_dir=tmp_path,
            venv_dir=tmp_path / ".test-venv-timeout",
        )
        result = executor.execute("import time; time.sleep(10)", timeout=1)
        assert result["ok"] is False
        assert result["status"] == 408
        executor.cleanup()

    def test_venv_reuse(self, tmp_path):
        """Creating a second executor with the same venv_dir should reuse it."""
        venv_dir = tmp_path / ".reuse-venv"
        ex1 = VenvExecutor(working_dir=tmp_path, venv_dir=venv_dir)
        result1 = ex1.execute("print('first')")
        assert result1["ok"] is True

        ex2 = VenvExecutor(working_dir=tmp_path, venv_dir=venv_dir)
        result2 = ex2.execute("print('second')")
        assert result2["ok"] is True

        ex1.cleanup()

    def test_runtime_install_enabled_by_default(self, executor):
        """pip_install defaults to True — every agent can install packages."""
        result = executor.install_runtime_packages([])
        assert result["ok"] is True
        assert result["data"]["installed"] == []

    def test_runtime_install_disabled_explicitly(self, tmp_path):
        executor = VenvExecutor(
            working_dir=tmp_path,
            venv_dir=tmp_path / ".nopip-venv",
            pip_install=False,
        )
        result = executor.install_runtime_packages(["some-package"])
        assert result["ok"] is False
        assert result["status"] == 403
        executor.cleanup()

    def test_runtime_install_real_package(self, tmp_path):
        """Actually install a small package and verify it's importable.

        Requires outbound network access to PyPI. If the environment
        is offline (sandboxed CI, air-gapped dev box) we skip rather
        than fail — the test verifies the venv install plumbing, not
        network reachability.
        """
        import socket

        try:
            socket.create_connection(("pypi.org", 443), timeout=3).close()
        except OSError as exc:
            import pytest
            pytest.skip(f"PyPI unreachable, skipping real-install test: {exc}")

        executor = VenvExecutor(
            working_dir=tmp_path,
            venv_dir=tmp_path / ".pip-venv",
            pip_install=True,
        )
        result = executor.install_runtime_packages(["six"])
        assert result["ok"] is True
        assert "six" in result["data"]["installed"]
        # Verify the package is importable in the venv
        run_result = executor.execute("import six; print(six.__version__)")
        assert run_result["ok"] is True
        executor.cleanup()

    def test_cleanup_removes_venv(self, tmp_path):
        venv_dir = tmp_path / ".cleanup-venv"
        executor = VenvExecutor(working_dir=tmp_path, venv_dir=venv_dir)
        assert venv_dir.exists()
        executor.cleanup()
        assert not venv_dir.exists()
