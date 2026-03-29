"""Tests for the subprocess-based code executor."""

from unittest.mock import patch

from awp.runtime.code_executor import CodeExecutor


class TestCodeExecutor:
    def test_simple_execution(self):
        executor = CodeExecutor()
        result = executor.execute("print('hello world')")
        assert result["ok"] is True
        assert "hello world" in result["data"]["stdout"]
        assert result["data"]["returncode"] == 0

    def test_math_computation(self):
        executor = CodeExecutor()
        result = executor.execute("print(2 + 3)")
        assert result["ok"] is True
        assert "5" in result["data"]["stdout"]

    def test_multi_line_code(self):
        code = """
import json
data = {"mean": 42.5, "std": 3.14}
print(json.dumps(data))
"""
        executor = CodeExecutor()
        result = executor.execute(code)
        assert result["ok"] is True
        import json

        output = json.loads(result["data"]["stdout"].strip())
        assert output["mean"] == 42.5

    def test_error_returns_stderr(self):
        executor = CodeExecutor()
        result = executor.execute("raise ValueError('test error')")
        assert result["ok"] is False
        assert result["status"] == 500
        assert "test error" in result["data"]["stderr"]

    def test_syntax_error(self):
        executor = CodeExecutor()
        result = executor.execute("def:")
        assert result["ok"] is False
        assert result["data"]["returncode"] != 0

    def test_timeout(self):
        executor = CodeExecutor(max_timeout=1)
        result = executor.execute("import time; time.sleep(10)", timeout=1)
        assert result["ok"] is False
        assert result["status"] == 408
        assert "timed out" in result["error"]

    def test_timeout_cap(self):
        executor = CodeExecutor(max_timeout=2)
        # Requesting 100s but capped at 2s
        result = executor.execute("import time; time.sleep(10)", timeout=100)
        assert result["ok"] is False
        assert result["status"] == 408

    def test_output_capture(self):
        code = """
import sys
print("stdout line")
print("stderr line", file=sys.stderr)
"""
        executor = CodeExecutor()
        result = executor.execute(code)
        assert result["ok"] is True
        assert "stdout line" in result["data"]["stdout"]
        assert "stderr line" in result["data"]["stderr"]

    def test_install_runtime_packages_empty(self):
        executor = CodeExecutor()
        result = executor.install_runtime_packages([])
        assert result["ok"] is True
        assert result["data"]["installed"] == []

    def test_install_runtime_packages_success(self):
        executor = CodeExecutor()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = None
            result = executor.install_runtime_packages(["some-pkg"])
        assert result["ok"] is True
        assert result["data"]["installed"] == ["some-pkg"]

    def test_install_runtime_packages_failure(self):
        import subprocess

        executor = CodeExecutor()
        with patch("subprocess.run", side_effect=subprocess.CalledProcessError(1, "pip", stderr="not found")):
            result = executor.install_runtime_packages(["nonexistent-pkg-xyz"])
        assert result["ok"] is False
        assert result["status"] == 500
