"""External tools — register user-provided tools into the AWP ToolRegistry.

Supports three input formats:
- Dict with OpenAI function calling schema + handler callable
- Decorated Python callable (auto-generates schema from type hints)
- MCP server URL (discovers tools via HTTP)

All formats are normalized to ExternalToolSpec dataclasses.
"""

from __future__ import annotations

import inspect
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, get_type_hints

logger = logging.getLogger(__name__)

# Python type → JSON Schema type mapping
_TYPE_MAP: dict[type, str] = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
    list: "array",
    dict: "object",
}


@dataclass
class ExternalToolSpec:
    """Normalized specification for an external tool."""

    name: str
    description: str
    parameters: dict[str, Any]
    handler: Callable[..., dict[str, Any]]
    secrets: list[str] = field(default_factory=list)


class ExternalTool:
    """Factory and decorator for creating external tool specifications.

    Usage as decorator::

        @ExternalTool(name="sentiment.analyze", secrets=["NLP_API_KEY"])
        def analyze_sentiment(*, text: str, language: str = "en") -> dict:
            \"\"\"Analyze sentiment of text.\"\"\"
            return {"score": 0.8}

    Usage as factory::

        spec = ExternalTool.from_callable(my_func, name="ns.action")
        spec = ExternalTool.from_dict({
            "name": "web.search",
            "description": "Search the web",
            "parameters": {...},
            "handler": search_fn,
        })
        specs = ExternalTool.from_mcp("http://localhost:8080/mcp")
    """

    def __init__(
        self,
        name: str | None = None,
        *,
        secrets: list[str] | None = None,
    ) -> None:
        self._name = name
        self._secrets = secrets or []

    def __call__(self, fn: Callable) -> ExternalToolSpec:
        """Use as decorator: @ExternalTool(name="ns.action")."""
        return ExternalTool.from_callable(
            fn, name=self._name, secrets=self._secrets
        )

    @staticmethod
    def from_callable(
        fn: Callable,
        *,
        name: str | None = None,
        secrets: list[str] | None = None,
    ) -> ExternalToolSpec:
        """Create an ExternalToolSpec from a Python callable.

        Auto-generates JSON Schema parameters from type hints and docstring.

        Args:
            fn: The function to wrap. Must use keyword-only arguments.
            name: Tool FQN (e.g. "sentiment.analyze"). Defaults to fn.__name__.
            secrets: List of secret keys the tool needs.

        Returns:
            ExternalToolSpec ready for registration.
        """
        tool_name = name or fn.__name__
        description = (fn.__doc__ or "").strip().split("\n")[0] or tool_name
        parameters = _extract_parameters(fn)

        return ExternalToolSpec(
            name=tool_name,
            description=description,
            parameters=parameters,
            handler=fn,
            secrets=secrets or [],
        )

    @staticmethod
    def from_dict(d: dict[str, Any]) -> ExternalToolSpec:
        """Create an ExternalToolSpec from an OpenAI function calling dict.

        The dict must contain:
        - name: str
        - description: str
        - parameters: dict (JSON Schema)
        - handler: Callable

        Optional:
        - secrets: list[str]

        Args:
            d: Tool definition dict.

        Returns:
            ExternalToolSpec ready for registration.

        Raises:
            ValueError: If required keys are missing.
        """
        required = ("name", "handler")
        missing = [k for k in required if k not in d]
        if missing:
            raise ValueError(f"Missing required keys in tool dict: {missing}")

        return ExternalToolSpec(
            name=d["name"],
            description=d.get("description", d["name"]),
            parameters=d.get("parameters", {"type": "object", "properties": {}}),
            handler=d["handler"],
            secrets=d.get("secrets", []),
        )

    @staticmethod
    def from_mcp(
        url: str,
        *,
        timeout: int = 30,
        headers: dict[str, str] | None = None,
    ) -> list[ExternalToolSpec]:
        """Discover and create tool specs from an MCP server.

        Connects to the MCP server, lists available tools, and creates
        proxy handlers that forward calls to the server.

        Args:
            url: MCP server base URL (e.g. "http://localhost:8080").
            timeout: HTTP request timeout in seconds.
            headers: Optional HTTP headers for authentication.

        Returns:
            List of ExternalToolSpec objects, one per discovered tool.

        Raises:
            ConnectionError: If the MCP server is unreachable.
            ValueError: If the server response is invalid.
        """
        import urllib.request
        import urllib.error

        base_url = url.rstrip("/")
        req_headers = {"Content-Type": "application/json"}
        if headers:
            req_headers.update(headers)

        # List tools via MCP protocol
        list_payload = json.dumps({
            "jsonrpc": "2.0",
            "method": "tools/list",
            "id": 1,
        }).encode("utf-8")

        req = urllib.request.Request(
            base_url,
            data=list_payload,
            headers=req_headers,
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.URLError as exc:
            raise ConnectionError(f"Cannot connect to MCP server at {url}: {exc}") from exc

        # Parse tool definitions from response
        result = data.get("result", {})
        tools_list = result.get("tools", [])
        if not tools_list:
            logger.warning("MCP server at %s returned no tools", url)
            return []

        specs: list[ExternalToolSpec] = []
        for tool_def in tools_list:
            tool_name = tool_def.get("name", "")
            if not tool_name:
                continue

            description = tool_def.get("description", tool_name)
            input_schema = tool_def.get("inputSchema", {
                "type": "object",
                "properties": {},
            })

            # Create proxy handler that calls the MCP server
            handler = _make_mcp_proxy(
                base_url, tool_name, timeout, req_headers
            )

            specs.append(ExternalToolSpec(
                name=tool_name,
                description=description,
                parameters=input_schema,
                handler=handler,
            ))

        logger.info("Discovered %d tools from MCP server at %s", len(specs), url)
        return specs


def normalize_external_tools(
    tools: list[Any],
) -> list[ExternalToolSpec]:
    """Normalize a mixed list of tool definitions into ExternalToolSpec objects.

    Accepts:
    - ExternalToolSpec instances (passed through)
    - Dicts with handler (converted via from_dict)
    - Callables (converted via from_callable)
    - Lists of ExternalToolSpec (flattened, e.g. from from_mcp)

    Args:
        tools: Mixed list of tool definitions.

    Returns:
        Flat list of ExternalToolSpec objects.
    """
    specs: list[ExternalToolSpec] = []
    for item in tools:
        if isinstance(item, ExternalToolSpec):
            specs.append(item)
        elif isinstance(item, list):
            # from_mcp returns a list
            specs.extend(
                s for s in item if isinstance(s, ExternalToolSpec)
            )
        elif isinstance(item, dict):
            specs.append(ExternalTool.from_dict(item))
        elif callable(item):
            specs.append(ExternalTool.from_callable(item))
        else:
            raise TypeError(
                f"Unsupported external tool type: {type(item).__name__}. "
                "Expected ExternalToolSpec, dict, callable, or list[ExternalToolSpec]."
            )
    return specs


def _extract_parameters(fn: Callable) -> dict[str, Any]:
    """Extract JSON Schema parameters from a function's type hints.

    Args:
        fn: Function with type-annotated keyword-only arguments.

    Returns:
        JSON Schema dict for the function's parameters.
    """
    sig = inspect.signature(fn)
    hints = get_type_hints(fn)

    properties: dict[str, Any] = {}
    required: list[str] = []

    for param_name, param in sig.parameters.items():
        if param_name.startswith("_"):
            continue  # Skip internal params like _secrets

        hint = hints.get(param_name)
        json_type = _TYPE_MAP.get(hint, "string") if hint else "string"

        prop: dict[str, Any] = {"type": json_type}

        if param.default is not inspect.Parameter.empty:
            prop["default"] = param.default
        else:
            required.append(param_name)

        properties[param_name] = prop

    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
    }
    if required:
        schema["required"] = required

    return schema


def _make_mcp_proxy(
    base_url: str,
    tool_name: str,
    timeout: int,
    headers: dict[str, str],
) -> Callable[..., dict[str, Any]]:
    """Create a proxy handler that forwards tool calls to an MCP server.

    Args:
        base_url: MCP server base URL.
        tool_name: Name of the tool on the server.
        timeout: HTTP request timeout.
        headers: HTTP headers.

    Returns:
        Callable that accepts kwargs and returns AWP result format.
    """
    import urllib.request

    def proxy(**kwargs: Any) -> dict[str, Any]:
        # Remove internal kwargs
        kwargs = {k: v for k, v in kwargs.items() if not k.startswith("_")}

        payload = json.dumps({
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": kwargs,
            },
            "id": 1,
        }).encode("utf-8")

        req = urllib.request.Request(
            base_url,
            data=payload,
            headers=headers,
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            return {
                "ok": False,
                "status": 502,
                "data": {},
                "error": f"MCP call to {tool_name} failed: {exc}",
            }

        result = data.get("result", {})
        content = result.get("content", [])

        # Extract text content from MCP response
        text_parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                text_parts.append(block.get("text", ""))

        return {
            "ok": not result.get("isError", False),
            "status": 200 if not result.get("isError", False) else 500,
            "data": "\n".join(text_parts) if text_parts else result,
            "error": None if not result.get("isError", False) else str(result),
        }

    proxy.__name__ = f"mcp_proxy_{tool_name}"
    proxy.__doc__ = f"MCP proxy for {tool_name}"
    return proxy
