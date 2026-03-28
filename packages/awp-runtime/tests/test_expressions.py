"""Tests for the safe expression evaluator."""

import pytest
from awp.runtime.expressions import safe_eval


class TestSafeEval:
    """Test safe_eval with various expression types."""

    def test_simple_comparison(self):
        assert safe_eval("x > 3", {"x": 5}) is True
        assert safe_eval("x > 3", {"x": 2}) is False

    def test_nested_attribute_access(self):
        ctx = {"state": {"analyst": {"risk_score": 0.7}}}
        assert safe_eval("state.analyst.risk_score > 0.3", ctx) is True
        assert safe_eval("state.analyst.risk_score > 0.9", ctx) is False

    def test_equality(self):
        ctx = {"state": {"agent": {"decision": "proceed"}}}
        assert safe_eval("state.agent.decision == 'proceed'", ctx) is True
        assert safe_eval("state.agent.decision != 'proceed'", ctx) is False

    def test_boolean_and(self):
        ctx = {"a": 5, "b": 10}
        assert safe_eval("a > 3 and b > 5", ctx) is True
        assert safe_eval("a > 3 and b > 15", ctx) is False

    def test_boolean_or(self):
        ctx = {"a": 1, "b": 10}
        assert safe_eval("a > 5 or b > 5", ctx) is True
        assert safe_eval("a > 5 or b > 15", ctx) is False

    def test_boolean_not(self):
        assert safe_eval("not x", {"x": False}) is True
        assert safe_eval("not x", {"x": True}) is False

    def test_arithmetic(self):
        assert safe_eval("a + b", {"a": 3, "b": 4}) == 7
        assert safe_eval("a - b", {"a": 10, "b": 3}) == 7
        assert safe_eval("a * b", {"a": 3, "b": 4}) == 12
        assert safe_eval("a / b", {"a": 10, "b": 2}) == 5.0

    def test_unary_minus(self):
        assert safe_eval("-x", {"x": 5}) == -5

    def test_chained_comparison(self):
        assert safe_eval("0 < x < 10", {"x": 5}) is True
        assert safe_eval("0 < x < 10", {"x": 15}) is False

    def test_subscript_access(self):
        ctx = {"data": {"items": [1, 2, 3]}}
        assert safe_eval("data['items']", ctx) == [1, 2, 3]

    def test_constant_values(self):
        assert safe_eval("True", {}) is True
        assert safe_eval("False", {}) is False
        assert safe_eval("None", {}) is None
        assert safe_eval("42", {}) == 42
        assert safe_eval("'hello'", {}) == "hello"

    def test_in_operator(self):
        ctx = {"x": 3, "items": [1, 2, 3, 4]}
        assert safe_eval("x in items", ctx) is True
        assert safe_eval("5 in items", ctx) is False

    def test_enterprise_workflow_condition(self):
        """Test the actual condition from the enterprise workflow."""
        state = {
            "analyst": {"risk_score": 0.75, "confidence": 0.9},
            "data_collector": {"raw_data": {}, "confidence": 0.8},
        }
        assert safe_eval("state.analyst.risk_score > 0.3", {"state": state}) is True
        assert safe_eval("state.analyst.risk_score > 0.9", {"state": state}) is False

    def test_dict_attribute_access_returns_none_for_missing(self):
        ctx = {"state": {"analyst": {}}}
        result = safe_eval("state.analyst.risk_score", ctx)
        assert result is None


class TestSafeEvalSecurity:
    """Test that dangerous constructs are rejected."""

    def test_rejects_function_call(self):
        with pytest.raises(ValueError, match="Disallowed"):
            safe_eval("print('hello')", {})

    def test_rejects_import(self):
        with pytest.raises(ValueError, match="Disallowed"):
            safe_eval("__import__('os')", {})

    def test_rejects_lambda(self):
        with pytest.raises(ValueError, match="Disallowed"):
            safe_eval("(lambda: 1)()", {})

    def test_rejects_comprehension(self):
        with pytest.raises(ValueError, match="Disallowed"):
            safe_eval("[x for x in range(10)]", {})

    def test_undefined_variable(self):
        with pytest.raises(ValueError, match="Undefined"):
            safe_eval("unknown_var > 0", {})

    def test_invalid_syntax(self):
        with pytest.raises(ValueError, match="syntax"):
            safe_eval("if x:", {"x": 1})
