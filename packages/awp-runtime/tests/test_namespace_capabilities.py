"""Tests for per-namespace capability grants in DynamicToolFactory.

Covers:
- NamespaceCapability model
- Per-namespace import policies (compute, network, filesystem)
- ALWAYS_DENIED imports cannot be unlocked
- Backward compatibility with plain string namespaces
- Network allowlist configuration
- _denied_for_capabilities() helper
"""

from unittest.mock import MagicMock

import pytest
from awp.models.manifest import DynamicToolsConfig, NamespaceCapability
from awp.runtime.dynamic_tool_factory import (
    ALWAYS_DENIED,
    DENIED_IMPORTS,
    IMPORT_POLICIES,
    DynamicToolFactory,
    _denied_for_capabilities,
)


def _handler_code(import_stmt: str = "", params: str = "x") -> str:
    """Build a minimal valid handler code string for tests."""
    prefix = f"{import_stmt}\n" if import_stmt else ""
    return (
        f"{prefix}def handler(*, {params}):\n"
        f"    return {{'ok': True, 'status': 200,"
        f" 'data': {{{params}}}, 'error': None}}"
    )


# ---------------------------------------------------------------------------
# NamespaceCapability model tests
# ---------------------------------------------------------------------------


class TestNamespaceCapabilityModel:
    def test_default_capabilities(self):
        ns = NamespaceCapability(name="test")
        assert ns.capabilities == ["compute"]
        assert ns.network_allowlist == []

    def test_network_capability(self):
        ns = NamespaceCapability(
            name="api_client",
            capabilities=["compute", "network"],
            network_allowlist=["api.example.com"],
        )
        assert "network" in ns.capabilities
        assert "api.example.com" in ns.network_allowlist

    def test_filesystem_capability(self):
        ns = NamespaceCapability(
            name="data_proc",
            capabilities=["compute", "filesystem"],
        )
        assert "filesystem" in ns.capabilities

    def test_multiple_capabilities(self):
        ns = NamespaceCapability(
            name="full",
            capabilities=["compute", "network", "filesystem"],
        )
        assert len(ns.capabilities) == 3


# ---------------------------------------------------------------------------
# DynamicToolsConfig tests
# ---------------------------------------------------------------------------


class TestDynamicToolsConfig:
    def test_plain_string_namespaces_backward_compat(self):
        cfg = DynamicToolsConfig(
            enabled=True,
            allowed_namespaces=["scoring", "analysis"],
        )
        assert cfg.get_namespace_names() == ["scoring", "analysis"]

    def test_namespace_capability_objects(self):
        cfg = DynamicToolsConfig(
            enabled=True,
            allowed_namespaces=[
                NamespaceCapability(name="scoring"),
                NamespaceCapability(
                    name="api_client",
                    capabilities=["compute", "network"],
                    network_allowlist=["api.example.com"],
                ),
            ],
        )
        assert cfg.get_namespace_names() == ["scoring", "api_client"]

        scoring = cfg.get_namespace_config("scoring")
        assert scoring.capabilities == ["compute"]

        api = cfg.get_namespace_config("api_client")
        assert "network" in api.capabilities
        assert "api.example.com" in api.network_allowlist

    def test_mixed_string_and_capability(self):
        cfg = DynamicToolsConfig(
            enabled=True,
            allowed_namespaces=[
                "simple",
                NamespaceCapability(name="advanced", capabilities=["compute", "network"]),
            ],
        )
        assert cfg.get_namespace_names() == ["simple", "advanced"]
        simple = cfg.get_namespace_config("simple")
        assert simple.capabilities == ["compute"]

    def test_unknown_namespace_returns_default(self):
        cfg = DynamicToolsConfig(enabled=True, allowed_namespaces=["known"])
        unknown = cfg.get_namespace_config("unknown")
        assert unknown.name == "unknown"
        assert unknown.capabilities == ["compute"]


# ---------------------------------------------------------------------------
# _denied_for_capabilities() unit tests
# ---------------------------------------------------------------------------


class TestDeniedForCapabilities:
    def test_compute_only_matches_subprocess_baseline(self):
        denied = _denied_for_capabilities(["compute"], "subprocess")
        # Should be same as subprocess policy (compute doesn't unlock anything)
        assert denied == IMPORT_POLICIES["subprocess"]

    def test_network_unlocks_network_imports(self):
        denied = _denied_for_capabilities(["compute", "network"], "subprocess")
        for mod in ["requests", "httpx", "urllib", "http"]:
            assert mod not in denied, f"{mod} should be allowed with network capability"

    def test_filesystem_unlocks_filesystem_imports(self):
        denied = _denied_for_capabilities(["compute", "filesystem"], "subprocess")
        for mod in ["pathlib", "glob", "shutil", "tempfile"]:
            assert mod not in denied, f"{mod} should be allowed with filesystem capability"

    def test_always_denied_never_unlocked_by_network(self):
        denied = _denied_for_capabilities(["compute", "network"], "subprocess")
        for mod in ALWAYS_DENIED:
            assert mod in denied, f"{mod} must ALWAYS be denied"

    def test_always_denied_never_unlocked_by_filesystem(self):
        denied = _denied_for_capabilities(["compute", "filesystem"], "subprocess")
        for mod in ALWAYS_DENIED:
            assert mod in denied, f"{mod} must ALWAYS be denied"

    def test_all_capabilities_still_denies_core(self):
        denied = _denied_for_capabilities(
            ["compute", "network", "filesystem"], "subprocess"
        )
        for mod in ALWAYS_DENIED:
            assert mod in denied, f"{mod} must ALWAYS be denied even with all caps"

    def test_docker_baseline_with_network(self):
        denied = _denied_for_capabilities(["compute", "network"], "docker")
        # Docker already allows most things; network cap shouldn't break it
        assert "requests" not in denied
        # But ALWAYS_DENIED still applies
        assert "os" in denied
        assert "subprocess" in denied

    def test_none_sandbox_still_enforces_always_denied(self):
        denied = _denied_for_capabilities(["compute", "network", "filesystem"], "none")
        for mod in ALWAYS_DENIED:
            assert mod in denied, f"{mod} must be denied even with sandbox=none"


# ---------------------------------------------------------------------------
# DynamicToolFactory with namespace capabilities
# ---------------------------------------------------------------------------


class TestFactoryNamespaceCapabilities:
    def _make_factory(self, sandbox_type="subprocess", config=None):
        registry = MagicMock()
        registry._tools = {}
        registry._secrets = {}
        executor = MagicMock()
        if config is None:
            config = {
                "enabled": True,
                "allowed_namespaces": [
                    "scoring",
                    {
                        "name": "api_client",
                        "capabilities": ["compute", "network"],
                        "network_allowlist": ["api.example.com"],
                    },
                    {
                        "name": "data_proc",
                        "capabilities": ["compute", "filesystem"],
                    },
                ],
            }
        return DynamicToolFactory(
            registry=registry,
            code_executor=executor,
            config=config,
            sandbox_type=sandbox_type,
        )

    def test_plain_namespace_uses_global_policy(self):
        factory = self._make_factory()
        code = _handler_code("import requests")
        result = factory.validate_code(code, namespace="scoring")
        assert result["ok"] is False
        assert "requests" in result["error"]

    def test_network_namespace_allows_requests(self):
        factory = self._make_factory()
        code = _handler_code("import requests", "url")
        result = factory.validate_code(code, namespace="api_client")
        assert result["ok"] is True

    def test_network_namespace_allows_httpx(self):
        factory = self._make_factory()
        code = _handler_code("import httpx", "url")
        result = factory.validate_code(code, namespace="api_client")
        assert result["ok"] is True

    def test_network_namespace_still_denies_os(self):
        factory = self._make_factory()
        code = _handler_code("import os")
        result = factory.validate_code(code, namespace="api_client")
        assert result["ok"] is False
        assert "os" in result["error"]

    def test_network_namespace_still_denies_subprocess(self):
        factory = self._make_factory()
        code = _handler_code("import subprocess")
        result = factory.validate_code(code, namespace="api_client")
        assert result["ok"] is False

    def test_filesystem_namespace_allows_pathlib(self):
        factory = self._make_factory()
        code = _handler_code("import pathlib", "path")
        result = factory.validate_code(code, namespace="data_proc")
        assert result["ok"] is True

    def test_filesystem_namespace_allows_shutil(self):
        factory = self._make_factory()
        code = _handler_code("import shutil", "src")
        result = factory.validate_code(code, namespace="data_proc")
        assert result["ok"] is True

    def test_filesystem_namespace_denies_network(self):
        factory = self._make_factory()
        code = _handler_code("import requests")
        result = factory.validate_code(code, namespace="data_proc")
        assert result["ok"] is False

    def test_filesystem_namespace_still_denies_os(self):
        factory = self._make_factory()
        code = _handler_code("import os")
        result = factory.validate_code(code, namespace="data_proc")
        assert result["ok"] is False

    def test_error_message_includes_capabilities(self):
        factory = self._make_factory()
        code = _handler_code("import os")
        result = factory.validate_code(code, namespace="api_client")
        assert "capabilities" in result["error"]

    def test_no_namespace_uses_global_policy(self):
        factory = self._make_factory()
        code = _handler_code("import requests")
        result = factory.validate_code(code)
        assert result["ok"] is False

    def test_get_namespace_capabilities(self):
        factory = self._make_factory()
        assert factory.get_namespace_capabilities("api_client") == ["compute", "network"]
        assert factory.get_namespace_capabilities("scoring") == ["compute"]
        assert factory.get_namespace_capabilities("unknown") == ["compute"]

    def test_get_network_allowlist(self):
        factory = self._make_factory()
        assert factory.get_network_allowlist("api_client") == ["api.example.com"]
        assert factory.get_network_allowlist("data_proc") == []
        assert factory.get_network_allowlist("unknown") == []


# ---------------------------------------------------------------------------
# Factory with NamespaceCapability Pydantic models
# ---------------------------------------------------------------------------


class TestFactoryWithPydanticModels:
    def test_pydantic_namespace_capability_config(self):
        config = DynamicToolsConfig(
            enabled=True,
            allowed_namespaces=[
                NamespaceCapability(
                    name="fetcher",
                    capabilities=["compute", "network"],
                    network_allowlist=["api.github.com"],
                ),
            ],
        )
        registry = MagicMock()
        registry._tools = {}
        registry._secrets = {}
        executor = MagicMock()
        factory = DynamicToolFactory(
            registry=registry,
            code_executor=executor,
            config=config,
            sandbox_type="subprocess",
        )

        # Network namespace should allow requests
        code = _handler_code("import requests", "url")
        result = factory.validate_code(code, namespace="fetcher")
        assert result["ok"] is True

        # But still deny os
        code_os = _handler_code("import os")
        result_os = factory.validate_code(code_os, namespace="fetcher")
        assert result_os["ok"] is False

        assert factory.get_network_allowlist("fetcher") == ["api.github.com"]


# ---------------------------------------------------------------------------
# Backward compatibility: plain string config still works
# ---------------------------------------------------------------------------


class TestBackwardCompatibility:
    def test_string_only_config(self):
        """Old-style config with just string namespaces should work identically."""
        config = {"enabled": True, "allowed_namespaces": ["scoring", "analysis"]}
        registry = MagicMock()
        registry._tools = {}
        executor = MagicMock()
        factory = DynamicToolFactory(
            registry=registry,
            code_executor=executor,
            config=config,
            sandbox_type="subprocess",
        )
        assert factory._allowed_namespaces == ["scoring", "analysis"]
        assert factory._namespace_configs == {}

        # Validation should use global policy (no network)
        code = _handler_code("import requests")
        result = factory.validate_code(code, namespace="scoring")
        assert result["ok"] is False

    def test_denied_imports_alias_unchanged(self):
        """DENIED_IMPORTS backward-compatible alias must still match subprocess."""
        assert DENIED_IMPORTS == IMPORT_POLICIES["subprocess"]


# ---------------------------------------------------------------------------
# ALWAYS_DENIED invariant
# ---------------------------------------------------------------------------


class TestAlwaysDenied:
    """Ensure ALWAYS_DENIED modules cannot be unlocked by any combination."""

    @pytest.mark.parametrize("module", sorted(ALWAYS_DENIED))
    def test_always_denied_with_all_capabilities(self, module):
        denied = _denied_for_capabilities(
            ["compute", "network", "filesystem"], "none"
        )
        assert module in denied, f"{module} must be in ALWAYS_DENIED"

    @pytest.mark.parametrize("module", sorted(ALWAYS_DENIED))
    def test_factory_rejects_always_denied_in_network_namespace(self, module):
        config = {
            "enabled": True,
            "allowed_namespaces": [
                {"name": "test_ns", "capabilities": ["compute", "network", "filesystem"]}
            ],
        }
        registry = MagicMock()
        registry._tools = {}
        executor = MagicMock()
        factory = DynamicToolFactory(
            registry=registry,
            code_executor=executor,
            config=config,
            sandbox_type="subprocess",
        )
        code = _handler_code(f"import {module}")
        result = factory.validate_code(code, namespace="test_ns")
        assert not result["ok"], f"import {module} should be rejected"
