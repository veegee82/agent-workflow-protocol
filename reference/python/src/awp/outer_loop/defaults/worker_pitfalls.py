"""v0 default for the ``worker_pitfalls`` artifact.

This is the hard-won pitfall section injected into every worker system prompt.
The exact string was extracted from ``awp.data.prompts.WORKER_PITFALLS`` and
MUST remain byte-identical to preserve prompt behavior.
"""

from __future__ import annotations

CONTENT = """## Critical Pitfalls (Read Before Writing Code)

### `code.execute` is STATELESS between calls
Each `code.execute` invocation runs in a **fresh subprocess**. Variables,
imports, and helper functions defined in one call DO NOT exist in the next
call. If you see `NameError: name 'foo' is not defined`, the cause is almost
certainly that `foo` was defined in an earlier `code.execute` call.

Rules:
- Every `code.execute` call must be **fully self-contained**: re-import
  modules, re-load files, re-define helpers.
- Persist intermediate data via `_workspace_dir` files (CSV / Parquet /
  JSON / .npy) and reload from disk in the next call.
- If an earlier worker already produced a data file under `_workspace_dir`,
  **load it from disk** instead of re-fetching it from the network.

### Pandas / data common bugs
- `df.loc[int_slice, col]` on a `DatetimeIndex` raises
  `cannot do slice indexing on DatetimeIndex`. Use `df.iloc[start:stop]`
  for positional access, or pass actual `Timestamp` values to `.loc`.
- `yfinance.download(...)` may return columns as a **MultiIndex**. Always
  flatten before selecting:
  `df.columns = df.columns.get_level_values(0)`
  Then `df.reset_index()` so the `Date`/`Datetime` column is preserved
  when you write to CSV.
- Never write a numpy array into a single CSV cell. Convert to a scalar
  (`arr.max()`, `arr.mean()`) or expand to multiple columns.
- Validate every CSV before declaring it a deliverable: no NaN in
  mandatory metric columns, no stringified arrays, expected row counts.

### Domain code (cBot, SQL, Solidity, etc.)
- Do **not** invent APIs. If you don't know the exact method signature,
  state that explicitly in your result rather than producing hallucinated
  code that won't compile.

### Python syntax: common LLM-emitted breaks to AVOID
Before running any Python via `code.execute`, the runtime deterministically
parses your source with `ast.parse`. A broken source is rejected with a
structured `syntax_error` block (line, column, offending line) — no cycles are
wasted. To avoid the most common rejections:

- **No `return` outside a function.** A top-level `return` is a hard syntax
  error. Use a plain expression, assign to a variable, or wrap your code in a
  `def main(): ...` and call it.
- **Regex patterns: use raw strings.** Write `re.compile(r"\\s+")`, NOT
  `re.compile("\\s+")`. Non-raw `\\s`, `\\d`, `\\w`, `\\b` inside a string
  literal is a warning at best and a silent bug at worst.
- **Do not embed literal `\\n` characters inside regex patterns.** Use a raw
  string: `re.compile(r"a\\nb")`. A literal newline in a non-raw string is
  almost never what you want.
- **Never put escaped quotes inside regex patterns without a raw string.**
  Prefer `r'"[^"]*"'` over `"\\"[^\\"]*\\""`.
- **Close every string literal.** Unterminated triple-quoted blocks are the
  second-most-common syntax break; keep triple-quoted strings on a single
  line (`\"\"\"text\"\"\"`) or place the closing triple-quote on its own
  line.

### Diagnose stderr; do not resubmit identical broken code
If a previous `code.execute` call failed, READ the stderr / traceback
in the tool result before issuing the next call. Change the specific
line(s) the traceback points at. Re-running the same code is wasted
budget.
"""
