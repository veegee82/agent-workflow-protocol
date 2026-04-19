"""Impure deterministic callable — imports openai. R33-violating.

The import is wrapped in a try/except so this fixture is importable
without the actual openai package installed (the R33 validator checks
the source text, not runtime availability). The static check must
still reject this file because the literal ``import openai`` statement
appears at the top level.
"""

from __future__ import annotations

try:
    import openai  # noqa: F401 — intentional to trigger R33 rejection
except ImportError:  # pragma: no cover — fixture may run without openai
    openai = None  # type: ignore[assignment]


def build(output_path: str = "") -> dict:
    return {"exit_code": 0, "output_path": output_path}
