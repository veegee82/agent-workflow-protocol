"""Fix A — structured AST pre-validation for code.execute.

These tests verify that:
1. Valid Python code proceeds to execution unchanged.
2. Invalid Python is rejected deterministically BEFORE shelling out, with
   a structured ``syntax_error`` payload carrying line / col / msg /
   offending_line / hint.
3. Heuristic warnings (non-raw regex escapes, literal newlines inside
   regex patterns) surface in the structured result.
"""

from __future__ import annotations

from awp.runtime.base_executor import validate_python_source
from awp.runtime.code_executor import CodeExecutor


class TestValidatePythonSource:
    def test_valid_code_parses(self):
        r = validate_python_source("x = 1\nprint(x)\n")
        assert r["ok"] is True
        assert r["data"]["valid"] is True
        assert r["data"]["warnings"] == []

    def test_syntax_error_is_structured(self):
        # `return` outside a function is a hard SyntaxError.
        r = validate_python_source("return 42\n")
        assert r["ok"] is False
        assert r["status"] == 400
        d = r["data"]
        assert d["valid"] is False
        assert d["line"] == 1
        assert d["msg"]  # has a message
        assert d["offending_line"] == "return 42"
        # Hint should suggest moving return into a function
        assert d["hint"] == "move_return_into_function_or_use_plain_expression"

    def test_unterminated_string_hint(self):
        r = validate_python_source('x = "hello\n')
        assert r["ok"] is False
        assert r["data"]["line"] == 1
        # Hint should be set for unterminated strings
        assert r["data"]["hint"] in (
            "close_string_literal_or_use_triple_quotes",
            None,
        )

    def test_warning_nonraw_regex_escape(self):
        code = 'import re\npattern = re.compile("\\s+foo")\n'
        r = validate_python_source(code)
        assert r["ok"] is True  # syntactically valid
        warnings = r["data"]["warnings"]
        # Should emit at least one warning about non-raw regex escape
        assert any(w["hint"] == "use_raw_string" for w in warnings), warnings

    def test_warning_raw_regex_is_fine(self):
        code = 'import re\npattern = re.compile(r"\\s+foo")\n'
        r = validate_python_source(code)
        assert r["ok"] is True
        # No warning about this line (it uses a raw string)
        assert r["data"]["warnings"] == []


class TestCodeExecutorPreValidation:
    def test_executor_runs_valid_code(self):
        ex = CodeExecutor()
        res = ex.execute("print('hello')")
        assert res["ok"] is True
        assert "hello" in res["data"]["stdout"]

    def test_executor_rejects_syntax_error_without_subprocess(self):
        ex = CodeExecutor()
        # This must NOT shell out — it must be blocked by ast.parse.
        res = ex.execute("return 42\n")
        assert res["ok"] is False
        assert res["status"] == 400
        se = res["data"].get("syntax_error")
        assert se is not None, res
        assert se["line"] == 1
        assert se["msg"]
        assert "return 42" in se["offending_line"]

    def test_executor_validate_code_returns_structured_error(self):
        ex = CodeExecutor()
        res = ex.validate_code("return 42\n")
        assert res["ok"] is False
        assert res["data"]["valid"] is False
        assert res["data"]["line"] == 1
