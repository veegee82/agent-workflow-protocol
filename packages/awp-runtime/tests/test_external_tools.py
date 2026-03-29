"""Tests for awp.runtime.external_tools."""

import json
from unittest.mock import patch, MagicMock

import pytest

from awp.runtime.external_tools import (
    ExternalTool,
    ExternalToolSpec,
    normalize_external_tools,
    _extract_parameters,
)


# -- Test fixtures --


def sample_handler(*, query: str, limit: int = 10) -> dict:
    """Search for something."""
    return {"ok": True, "status": 200, "data": {"query": query, "limit": limit}, "error": None}


def bare_handler(**kwargs) -> dict:
    return {"ok": True, "status": 200, "data": kwargs, "error": None}


# -- ExternalTool.from_callable --


class TestFromCallable:
    def test_basic(self):
        spec = ExternalTool.from_callable(sample_handler, name="web.search")

        assert isinstance(spec, ExternalToolSpec)
        assert spec.name == "web.search"
        assert spec.description == "Search for something."
        assert "query" in spec.parameters["properties"]
        assert spec.parameters["properties"]["query"]["type"] == "string"
        assert "limit" in spec.parameters["properties"]
        assert spec.parameters["properties"]["limit"]["default"] == 10
        assert spec.parameters["required"] == ["query"]
        assert spec.secrets == []

    def test_with_secrets(self):
        spec = ExternalTool.from_callable(
            sample_handler, name="web.search", secrets=["API_KEY"]
        )
        assert spec.secrets == ["API_KEY"]

    def test_default_name(self):
        spec = ExternalTool.from_callable(sample_handler)
        assert spec.name == "sample_handler"

    def test_no_docstring(self):
        def no_doc(*, x: int) -> dict:
            return {}

        spec = ExternalTool.from_callable(no_doc, name="test.tool")
        assert spec.description == "test.tool"

    def test_handler_is_callable(self):
        spec = ExternalTool.from_callable(sample_handler, name="test")
        result = spec.handler(query="hello", limit=5)
        assert result["ok"] is True
        assert result["data"]["query"] == "hello"


# -- ExternalTool.from_dict --


class TestFromDict:
    def test_full_dict(self):
        d = {
            "name": "calc.add",
            "description": "Add two numbers",
            "parameters": {
                "type": "object",
                "properties": {
                    "a": {"type": "number"},
                    "b": {"type": "number"},
                },
                "required": ["a", "b"],
            },
            "handler": bare_handler,
            "secrets": ["CALC_KEY"],
        }

        spec = ExternalTool.from_dict(d)

        assert spec.name == "calc.add"
        assert spec.description == "Add two numbers"
        assert spec.secrets == ["CALC_KEY"]
        assert spec.handler is bare_handler

    def test_minimal_dict(self):
        d = {"name": "test.tool", "handler": bare_handler}

        spec = ExternalTool.from_dict(d)

        assert spec.name == "test.tool"
        assert spec.description == "test.tool"
        assert spec.parameters == {"type": "object", "properties": {}}
        assert spec.secrets == []

    def test_missing_name_raises(self):
        with pytest.raises(ValueError, match="Missing required keys"):
            ExternalTool.from_dict({"handler": bare_handler})

    def test_missing_handler_raises(self):
        with pytest.raises(ValueError, match="Missing required keys"):
            ExternalTool.from_dict({"name": "test"})


# -- ExternalTool as decorator --


class TestDecorator:
    def test_decorator_usage(self):
        @ExternalTool(name="sentiment.analyze", secrets=["NLP_KEY"])
        def analyze(*, text: str) -> dict:
            """Analyze sentiment."""
            return {"score": 0.8}

        assert isinstance(analyze, ExternalToolSpec)
        assert analyze.name == "sentiment.analyze"
        assert analyze.secrets == ["NLP_KEY"]
        assert analyze.description == "Analyze sentiment."

    def test_decorator_handler_works(self):
        @ExternalTool(name="test.dec")
        def my_tool(*, value: int) -> dict:
            """A test tool."""
            return {"result": value * 2}

        result = my_tool.handler(value=5)
        assert result == {"result": 10}


# -- ExternalTool.from_mcp --


class TestFromMCP:
    def test_from_mcp_success(self):
        mcp_response = {
            "jsonrpc": "2.0",
            "result": {
                "tools": [
                    {
                        "name": "weather.get",
                        "description": "Get weather for a location",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "city": {"type": "string"},
                            },
                            "required": ["city"],
                        },
                    },
                    {
                        "name": "translate.text",
                        "description": "Translate text",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "text": {"type": "string"},
                                "target_lang": {"type": "string"},
                            },
                        },
                    },
                ]
            },
            "id": 1,
        }

        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(mcp_response).encode()
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_response):
            specs = ExternalTool.from_mcp("http://localhost:8080")

        assert len(specs) == 2
        assert specs[0].name == "weather.get"
        assert specs[0].description == "Get weather for a location"
        assert specs[1].name == "translate.text"

    def test_from_mcp_empty_tools(self):
        mcp_response = {
            "jsonrpc": "2.0",
            "result": {"tools": []},
            "id": 1,
        }

        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(mcp_response).encode()
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_response):
            specs = ExternalTool.from_mcp("http://localhost:8080")

        assert specs == []

    def test_from_mcp_connection_error(self):
        import urllib.error

        with patch(
            "urllib.request.urlopen",
            side_effect=urllib.error.URLError("Connection refused"),
        ):
            with pytest.raises(ConnectionError, match="Cannot connect"):
                ExternalTool.from_mcp("http://localhost:9999")


# -- normalize_external_tools --


class TestNormalize:
    def test_passthrough_spec(self):
        spec = ExternalToolSpec(
            name="test.tool",
            description="A test",
            parameters={"type": "object", "properties": {}},
            handler=bare_handler,
        )
        result = normalize_external_tools([spec])
        assert result == [spec]

    def test_dict_conversion(self):
        d = {"name": "test.tool", "handler": bare_handler}
        result = normalize_external_tools([d])
        assert len(result) == 1
        assert result[0].name == "test.tool"

    def test_callable_conversion(self):
        result = normalize_external_tools([sample_handler])
        assert len(result) == 1
        assert result[0].name == "sample_handler"

    def test_list_flattening(self):
        specs = [
            ExternalToolSpec("a", "Tool A", {}, bare_handler),
            ExternalToolSpec("b", "Tool B", {}, bare_handler),
        ]
        result = normalize_external_tools([specs])
        assert len(result) == 2

    def test_mixed(self):
        spec = ExternalToolSpec("direct", "Direct", {}, bare_handler)
        d = {"name": "from_dict", "handler": bare_handler}

        result = normalize_external_tools([spec, d, sample_handler])
        assert len(result) == 3
        names = [s.name for s in result]
        assert "direct" in names
        assert "from_dict" in names
        assert "sample_handler" in names

    def test_unsupported_type_raises(self):
        with pytest.raises(TypeError, match="Unsupported external tool type"):
            normalize_external_tools([42])


# -- _extract_parameters --


class TestExtractParameters:
    def test_typed_params(self):
        def fn(*, name: str, count: int, ratio: float, active: bool) -> dict:
            return {}

        params = _extract_parameters(fn)

        assert params["properties"]["name"]["type"] == "string"
        assert params["properties"]["count"]["type"] == "integer"
        assert params["properties"]["ratio"]["type"] == "number"
        assert params["properties"]["active"]["type"] == "boolean"
        assert sorted(params["required"]) == ["active", "count", "name", "ratio"]

    def test_default_values(self):
        def fn(*, required_param: str, optional_param: int = 42) -> dict:
            return {}

        params = _extract_parameters(fn)

        assert params["required"] == ["required_param"]
        assert params["properties"]["optional_param"]["default"] == 42

    def test_skips_underscore_params(self):
        def fn(*, visible: str, _secrets: dict = None) -> dict:
            return {}

        params = _extract_parameters(fn)

        assert "visible" in params["properties"]
        assert "_secrets" not in params["properties"]
