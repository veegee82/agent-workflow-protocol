"""Tests for per-sandbox-type import policies in DynamicToolFactory."""

from unittest.mock import MagicMock

from awp.runtime.dynamic_tool_factory import (
    DENIED_IMPORTS,
    IMPORT_POLICIES,
    DynamicToolFactory,
)


class TestImportPolicies:
    def test_backward_compatible_denied_imports(self):
        """DENIED_IMPORTS should equal the subprocess policy."""
        assert DENIED_IMPORTS == IMPORT_POLICIES["subprocess"]

    def test_subprocess_denies_os(self):
        assert "os" in IMPORT_POLICIES["subprocess"]

    def test_subprocess_denies_requests(self):
        assert "requests" in IMPORT_POLICIES["subprocess"]

    def test_docker_allows_os(self):
        assert "os" not in IMPORT_POLICIES["docker"]

    def test_docker_allows_requests(self):
        assert "requests" not in IMPORT_POLICIES["docker"]

    def test_docker_denies_ctypes(self):
        assert "ctypes" in IMPORT_POLICIES["docker"]

    def test_docker_denies_signal(self):
        assert "signal" in IMPORT_POLICIES["docker"]

    def test_venv_denies_os(self):
        assert "os" in IMPORT_POLICIES["venv"]

    def test_venv_allows_pathlib(self):
        assert "pathlib" not in IMPORT_POLICIES["venv"]

    def test_venv_allows_tempfile(self):
        assert "tempfile" not in IMPORT_POLICIES["venv"]

    def test_none_denies_nothing(self):
        assert len(IMPORT_POLICIES["none"]) == 0


class TestDynamicToolFactoryImportValidation:
    """Test that DynamicToolFactory uses the correct policy for its sandbox type."""

    def _make_factory(self, sandbox_type="subprocess"):
        registry = MagicMock()
        registry._tools = {}
        executor = MagicMock()
        config = {"enabled": True, "allowed_namespaces": ["test"]}
        return DynamicToolFactory(
            registry=registry,
            code_executor=executor,
            config=config,
            sandbox_type=sandbox_type,
        )

    def test_subprocess_rejects_os_import(self):
        factory = self._make_factory("subprocess")
        code = "import os\ndef handler(*, x):\n    return {'ok': True, 'status': 200, 'data': x, 'error': None}"
        result = factory.validate_code(code)
        assert result["ok"] is False
        assert "os" in result["error"]

    def test_docker_allows_os_import(self):
        factory = self._make_factory("docker")
        code = "import os\ndef handler(*, x):\n    return {'ok': True, 'status': 200, 'data': x, 'error': None}"
        result = factory.validate_code(code)
        assert result["ok"] is True

    def test_subprocess_rejects_numpy(self):
        """numpy is not in the deny list, so even subprocess allows it at validation
        (it just won't be available at runtime in subprocess sandbox)."""
        factory = self._make_factory("subprocess")
        code = "import numpy\ndef handler(*, x):\n    return {'ok': True, 'status': 200, 'data': x, 'error': None}"
        result = factory.validate_code(code)
        assert result["ok"] is True

    def test_docker_allows_requests_import(self):
        factory = self._make_factory("docker")
        code = "import requests\ndef handler(*, x):\n    return {'ok': True, 'status': 200, 'data': x, 'error': None}"
        result = factory.validate_code(code)
        assert result["ok"] is True

    def test_subprocess_rejects_requests_import(self):
        factory = self._make_factory("subprocess")
        code = "import requests\ndef handler(*, x):\n    return {'ok': True, 'status': 200, 'data': x, 'error': None}"
        result = factory.validate_code(code)
        assert result["ok"] is False

    def test_venv_rejects_subprocess_import(self):
        factory = self._make_factory("venv")
        code = "import subprocess\ndef handler(*, x):\n    return {'ok': True, 'status': 200, 'data': x, 'error': None}"
        result = factory.validate_code(code)
        assert result["ok"] is False

    def test_venv_allows_pathlib_import(self):
        factory = self._make_factory("venv")
        code = "import pathlib\ndef handler(*, x):\n    return {'ok': True, 'status': 200, 'data': x, 'error': None}"
        result = factory.validate_code(code)
        assert result["ok"] is True

    def test_docker_rejects_ctypes_import(self):
        factory = self._make_factory("docker")
        code = "import ctypes\ndef handler(*, x):\n    return {'ok': True, 'status': 200, 'data': x, 'error': None}"
        result = factory.validate_code(code)
        assert result["ok"] is False

    def test_error_message_includes_sandbox_type(self):
        factory = self._make_factory("venv")
        code = "import os\ndef handler(*, x):\n    return {'ok': True, 'status': 200, 'data': x, 'error': None}"
        result = factory.validate_code(code)
        assert "venv" in result["error"]
