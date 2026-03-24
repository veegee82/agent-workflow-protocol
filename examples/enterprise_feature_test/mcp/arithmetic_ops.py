"""
Built-in MCP Tools: arithmetic.add, arithmetic.subtract, arithmetic.multiply, arithmetic.divide

Direct Python arithmetic operations.
Auto-generated for tool implementation mode.
"""

from __future__ import annotations

from typing import Any, Dict


class FastMCP:
    def __init__(self, name: str) -> None:
        self.name = name

    def tool(self, _name: str, *, secrets: list[str] | None = None):
        def _decorator(fn):
            fn._awp_secrets = secrets or []
            return fn
        return _decorator


app = FastMCP("arithmetic")


@app.tool("arithmetic.add")
def add(*, a: float, b: float, _secrets: dict = {}) -> Dict[str, Any]:
    """Add two numbers. Returns a + b."""
    return {"ok": True, "status": 200, "data": {"result": a + b}, "error": None}


@app.tool("arithmetic.subtract")
def subtract(*, a: float, b: float, _secrets: dict = {}) -> Dict[str, Any]:
    """Subtract two numbers. Returns a - b."""
    return {"ok": True, "status": 200, "data": {"result": a - b}, "error": None}


@app.tool("arithmetic.multiply")
def multiply(*, a: float, b: float, _secrets: dict = {}) -> Dict[str, Any]:
    """Multiply two numbers. Returns a * b."""
    return {"ok": True, "status": 200, "data": {"result": a * b}, "error": None}


@app.tool("arithmetic.divide")
def divide(*, a: float, b: float, _secrets: dict = {}) -> Dict[str, Any]:
    """Divide two numbers. Returns a / b."""
    if b == 0:
        return {"ok": False, "status": 400, "data": {}, "error": "Division by zero"}
    return {"ok": True, "status": 200, "data": {"result": a / b}, "error": None}
