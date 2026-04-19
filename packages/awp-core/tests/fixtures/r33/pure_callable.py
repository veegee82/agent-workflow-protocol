"""Pure deterministic callable — no LLM imports. R33-compliant."""

from __future__ import annotations

import json
import os
from pathlib import Path


def build(input_path: str = "", output_path: str = "") -> dict:
    """Read a small JSON draft, echo its 'body' into a plain text file.

    This function deliberately has zero LLM-related imports. Used by the
    R33 static-check test as the positive baseline.
    """
    in_p = Path(input_path) if input_path else None
    out_p = Path(output_path) if output_path else None
    if out_p is None:
        return {"error": "missing output_path"}
    out_p.parent.mkdir(parents=True, exist_ok=True)
    body = ""
    if in_p and in_p.exists():
        data = json.loads(in_p.read_text())
        body = str(data.get("body", ""))
    out_p.write_text(body, encoding="utf-8")
    return {"exit_code": 0, "bytes_written": len(body.encode("utf-8"))}


def verify(result: dict) -> bool:
    """Trivial predicate for the python_predicate invariant tests."""
    return bool(result) and result.get("exit_code") == 0


# Reference os so the fixture actually touches something — keeps static
# analyzers from flagging it as unused. This is a real Python module.
_ = os
