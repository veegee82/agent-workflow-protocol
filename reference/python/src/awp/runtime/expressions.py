"""Safe expression evaluator for AWP ``when`` conditions.

Uses ``ast.parse`` with a strict whitelist of node types -- no ``eval()``,
no function calls, no imports.  Supports comparisons, boolean operators,
arithmetic, attribute access, and subscript access against a context dict.

Examples::

    safe_eval("state.analyst.risk_score > 0.3", {"state": {"analyst": {"risk_score": 0.7}}})
    # => True
"""

from __future__ import annotations

import ast
import operator
from typing import Any

# Allowed AST node types (whitelist)
_ALLOWED_NODES = frozenset({
    ast.Expression,
    ast.Compare,
    ast.BoolOp,
    ast.BinOp,
    ast.UnaryOp,
    ast.Attribute,
    ast.Subscript,
    ast.Name,
    ast.Constant,
    ast.Load,
    ast.And,
    ast.Or,
    ast.Not,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.FloorDiv,
    ast.Mod,
    ast.Eq,
    ast.NotEq,
    ast.Lt,
    ast.LtE,
    ast.Gt,
    ast.GtE,
    ast.Is,
    ast.IsNot,
    ast.In,
    ast.NotIn,
    ast.USub,
    ast.UAdd,
    ast.Tuple,
    ast.List,
})

_CMP_OPS = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
    ast.Is: operator.is_,
    ast.IsNot: operator.is_not,
    ast.In: lambda a, b: a in b,
    ast.NotIn: lambda a, b: a not in b,
}

_BIN_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
}

_UNARY_OPS = {
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
    ast.Not: operator.not_,
}


def safe_eval(expr: str, context: dict[str, Any]) -> Any:
    """Evaluate a restricted expression against a context dict.

    Args:
        expr: Expression string (e.g. ``"state.analyst.risk_score > 0.3"``).
        context: Dict of available names (e.g. ``{"state": {...}}``).

    Returns:
        The result of the expression.

    Raises:
        ValueError: If the expression contains disallowed constructs.
    """
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as exc:
        raise ValueError(f"Invalid expression syntax: {exc}") from exc

    _validate_tree(tree)
    return _eval_node(tree.body, context)


def _validate_tree(tree: ast.AST) -> None:
    """Walk the AST and reject any node not in the whitelist."""
    for node in ast.walk(tree):
        if type(node) not in _ALLOWED_NODES:
            raise ValueError(
                f"Disallowed expression construct: {type(node).__name__}"
            )


def _eval_node(node: ast.AST, ctx: dict[str, Any]) -> Any:
    """Recursively evaluate an AST node."""
    if isinstance(node, ast.Constant):
        return node.value

    if isinstance(node, ast.Name):
        if node.id not in ctx:
            raise ValueError(f"Undefined variable: {node.id}")
        return ctx[node.id]

    if isinstance(node, ast.Attribute):
        obj = _eval_node(node.value, ctx)
        if isinstance(obj, dict):
            return obj.get(node.attr)
        return getattr(obj, node.attr)

    if isinstance(node, ast.Subscript):
        obj = _eval_node(node.value, ctx)
        key = _eval_node(node.slice, ctx)
        return obj[key]

    if isinstance(node, ast.Compare):
        left = _eval_node(node.left, ctx)
        for op, comparator in zip(node.ops, node.comparators):
            right = _eval_node(comparator, ctx)
            op_func = _CMP_OPS.get(type(op))
            if op_func is None:
                raise ValueError(f"Unsupported comparison: {type(op).__name__}")
            if not op_func(left, right):
                return False
            left = right
        return True

    if isinstance(node, ast.BoolOp):
        if isinstance(node.op, ast.And):
            return all(_eval_node(v, ctx) for v in node.values)
        if isinstance(node.op, ast.Or):
            return any(_eval_node(v, ctx) for v in node.values)

    if isinstance(node, ast.BinOp):
        left = _eval_node(node.left, ctx)
        right = _eval_node(node.right, ctx)
        op_func = _BIN_OPS.get(type(node.op))
        if op_func is None:
            raise ValueError(f"Unsupported binary op: {type(node.op).__name__}")
        return op_func(left, right)

    if isinstance(node, ast.UnaryOp):
        operand = _eval_node(node.operand, ctx)
        op_func = _UNARY_OPS.get(type(node.op))
        if op_func is None:
            raise ValueError(f"Unsupported unary op: {type(node.op).__name__}")
        return op_func(operand)

    if isinstance(node, (ast.Tuple, ast.List)):
        return [_eval_node(elt, ctx) for elt in node.elts]

    raise ValueError(f"Cannot evaluate node type: {type(node).__name__}")
