#!/usr/bin/env python3
"""Detect drift between ``packages/`` sources and the ``reference/python/``
PyPI bundle.

The PyPI meta-package ``awp-agents`` is built from ``reference/python/``,
which vendors code from:

    packages/awp-core/src/awp/**   → reference/python/src/awp/**
    packages/awp-runtime/src/awp/** → reference/python/src/awp/**
    packages/awp-ui/server/**      → reference/python/src/server/**

These directories are NOT symlinked — they are independent copies. A fix
applied only to ``packages/`` but not mirrored produces a PyPI build that
ships the bug, while local E2E runs (which install from ``packages/``) look
green. This script catches that drift before commit.

Exit codes:
    0 — every tracked source file in packages/ has a byte-identical mirror
        under reference/python/src/.
    1 — at least one file is missing in the mirror or has divergent content.

Ignored paths:
    __pycache__, *.pyc, *.egg-info, .mypy_cache, build/, dist/, node_modules
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# (source_root, mirror_root) pairs. Every file under source_root (relative to
# it) must exist identically under mirror_root.
MIRROR_PAIRS: list[tuple[Path, Path]] = [
    (ROOT / "packages/awp-core/src/awp", ROOT / "reference/python/src/awp"),
    (ROOT / "packages/awp-runtime/src/awp", ROOT / "reference/python/src/awp"),
    (ROOT / "packages/awp-ui/server", ROOT / "reference/python/src/server"),
]

SKIP_DIR_NAMES = {
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "build",
    "dist",
    "node_modules",
    "frontend",  # ui frontend bundle lives only in reference/, handled separately
}

SKIP_SUFFIXES = {".pyc", ".pyo"}


def _iter_source_files(root: Path):
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP_DIR_NAMES for part in path.relative_to(root).parts):
            continue
        if path.suffix in SKIP_SUFFIXES:
            continue
        if ".egg-info" in str(path):
            continue
        yield path


def _digest(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def main() -> int:
    issues: list[str] = []

    for source_root, mirror_root in MIRROR_PAIRS:
        if not source_root.exists():
            continue
        if not mirror_root.exists():
            issues.append(f"mirror root missing: {mirror_root.relative_to(ROOT)}")
            continue

        for src_file in _iter_source_files(source_root):
            rel = src_file.relative_to(source_root)
            mirror_file = mirror_root / rel

            if not mirror_file.exists():
                issues.append(
                    f"missing in mirror: {mirror_file.relative_to(ROOT)} "
                    f"(source: {src_file.relative_to(ROOT)})"
                )
                continue

            if _digest(src_file) != _digest(mirror_file):
                issues.append(
                    f"content drift: {src_file.relative_to(ROOT)} "
                    f"!= {mirror_file.relative_to(ROOT)}"
                )

    if issues:
        print("MIRROR DRIFT DETECTED — packages/ and reference/python/src/ diverge.")
        print("Fix: copy the changed files from packages/ into reference/python/src/,")
        print("     or update both in lockstep. See CLAUDE.md 'Source of Truth for Code'.\n")
        for item in issues:
            print(f"  - {item}")
        print(f"\n{len(issues)} drift item(s).")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
