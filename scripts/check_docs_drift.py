#!/usr/bin/env python3
"""Detect drift between CLAUDE.md and the repo.

Scans CLAUDE.md for backtick-quoted file and directory path references
(e.g. ``packages/awp-core/src/awp/``) and verifies each one still exists
on disk. Catches the most common drift symptom: files/directories that
were renamed, moved, or deleted but whose paths still live in the docs.

Exit codes:
    0 — all references resolve.
    1 — at least one stale reference found (printed to stdout).

Intentional non-goals:
    - Prose accuracy. This script does not understand sentences.
    - Command validity. ``awp validate <path>`` is not executed.
    - Symbol existence inside a file (functions, classes).

Those remain the responsibility of the author during doc-sync.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CLAUDE_MD = ROOT / "CLAUDE.md"

# Backtick-quoted tokens that contain a slash and only "path-safe" chars.
# We exclude angle brackets (placeholders like <path>) and spaces.
PATH_RE = re.compile(r"`([A-Za-z0-9_./\-]+)`")

# Prefixes that look like paths but aren't (model IDs, URLs, shell flags).
SKIP_PREFIXES = (
    "http://",
    "https://",
    "sk-",
    "gpt-",
    "o1-",
    "o3",
    "claude-",
    "ollama/",
    "openai/",
    "anthropic/",
    "provider/",
)


def is_path_like(token: str) -> bool:
    if "/" not in token:
        return False
    if token.startswith(SKIP_PREFIXES):
        return False
    # Reject tokens that look like shell flags or env-var references.
    if token.startswith("-") or token.startswith("$"):
        return False
    return True


def resolves(token: str) -> bool:
    clean = token.rstrip("/")
    direct = ROOT / clean
    if direct.exists():
        return True
    # Allow patterns whose parent exists and whose leaf matches at least one entry.
    # (Handles e.g. ``packages/awp-core/tests/test_validator.py::test_function_name`` —
    #  but we strip ``::...`` below, so this branch is mostly a safety net.)
    return False


def normalize(token: str) -> str:
    # Strip pytest-style ::suffix.
    if "::" in token:
        token = token.split("::", 1)[0]
    return token.rstrip("/")


def main() -> int:
    if not CLAUDE_MD.exists():
        print(f"error: {CLAUDE_MD} not found", file=sys.stderr)
        return 2

    text = CLAUDE_MD.read_text(encoding="utf-8")
    candidates = {
        n
        for t in PATH_RE.findall(text)
        if is_path_like(t)
        for n in [normalize(t)]
        if "/" in n  # require ≥2 segments after normalization (drops ``data/`` → ``data``)
    }

    missing = sorted(c for c in candidates if not resolves(c))

    if missing:
        print("Drift detected — paths referenced in CLAUDE.md that no longer exist:")
        for m in missing:
            print(f"  - {m}")
        print()
        print(f"{len(missing)} stale reference(s). Update CLAUDE.md or restore the paths.")
        return 1

    print(f"OK — {len(candidates)} path reference(s) in CLAUDE.md all resolve.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
