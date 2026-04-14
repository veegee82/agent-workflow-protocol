#!/usr/bin/env python3
"""Detect drift between CLAUDE.md and the repo.

Three tiers of checking, from cheapest to most thorough:

1. **Path check** — backtick-quoted file/directory paths must still exist on disk.
2. **Symbol check** — backtick-quoted Python/TS identifiers (classes, functions,
   fields) must still appear in at least one source file.
3. **Count check** — numeric claims like "18 runnable examples" are verified
   against the actual count on disk.

Exit codes:
    0 — all checks pass.
    1 — at least one drift item found (printed to stdout).

Intentional non-goals:
    - Prose accuracy. This script does not understand sentences.
    - Command validity. ``awp validate <path>`` is not executed.

Those remain the responsibility of the author during doc-sync.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CLAUDE_MD = ROOT / "CLAUDE.md"

# ---------------------------------------------------------------------------
# Tier 1: Path references
# ---------------------------------------------------------------------------

PATH_RE = re.compile(r"`([A-Za-z0-9_./\-]+)`")

SKIP_PREFIXES = (
    "http://", "https://", "sk-", "gpt-", "o1-", "o3",
    "claude-", "ollama/", "openai/", "anthropic/", "provider/",
)


def is_path_like(token: str) -> bool:
    if "/" not in token:
        return False
    if token.startswith(SKIP_PREFIXES):
        return False
    if token.startswith("-") or token.startswith("$"):
        return False
    return True


def resolves(token: str) -> bool:
    clean = token.rstrip("/")
    return (ROOT / clean).exists()


def normalize_path(token: str) -> str:
    if "::" in token:
        token = token.split("::", 1)[0]
    return token.rstrip("/")


def check_paths(text: str) -> list[str]:
    """Return list of stale path references."""
    candidates = {
        n
        for t in PATH_RE.findall(text)
        if is_path_like(t)
        for n in [normalize_path(t)]
        if "/" in n
    }
    return sorted(c for c in candidates if not resolves(c))


# ---------------------------------------------------------------------------
# Tier 2: Symbol references
# ---------------------------------------------------------------------------

# Backtick tokens that look like code identifiers (not paths, not shell commands).
SYMBOL_RE = re.compile(r"`([A-Za-z_][A-Za-z0-9_.]*)`")

# Tokens to skip: too generic, are keywords, env vars, or formatting conventions.
SKIP_SYMBOLS = {
    # Python/generic keywords and conventions
    "snake_case", "PascalCase", "UPPER_SNAKE_CASE", "True", "False", "None",
    "self", "run", "name", "state", "confidence", "result",
    # Markdown/file references (handled by path check)
    "CLAUDE.md", "README.md", "README_NERD.md", "SKILL.md",
    # Environment variables (not code symbols)
    "OPENROUTER_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY",
    # Loop variables / meta
    "K_MAX", "k",
    # File extensions and patterns
    "e2e", "yaml", "json", "md",
}

# Source directories to search for symbols.
SEARCH_DIRS = [
    ROOT / "packages",
    ROOT / "examples",
]

# File extensions to search in.
SEARCH_EXTENSIONS = {".py", ".ts", ".tsx", ".js", ".jsx"}


def is_code_symbol(token: str) -> bool:
    """Return True if token looks like a code identifier worth checking."""
    if token in SKIP_SYMBOLS:
        return False
    if "/" in token:
        return False  # path, not symbol
    if token.startswith("-"):
        return False  # CLI flag
    # Must contain underscore, dot, or be PascalCase to be interesting
    has_underscore = "_" in token
    has_dot = "." in token
    is_pascal = (
        len(token) > 2
        and token[0].isupper()
        and any(c.islower() for c in token)
        and any(c.isupper() for c in token[1:])
    )
    is_all_caps_meaningful = (
        token.isupper()
        and "_" in token
        and len(token) > 4
        and token not in SKIP_SYMBOLS
    )
    return has_underscore or has_dot or is_pascal or is_all_caps_meaningful


def symbol_exists_in_source(symbol: str) -> bool:
    """Check if a symbol appears in any source file under SEARCH_DIRS."""
    # Use the leaf identifier (after last dot) for dotted paths like
    # "delegation_loop.critique" — we check both the full string and the leaf.
    search_terms = [symbol]
    if "." in symbol:
        search_terms.append(symbol.rsplit(".", 1)[-1])

    for search_dir in SEARCH_DIRS:
        if not search_dir.exists():
            continue
        for term in search_terms:
            try:
                result = subprocess.run(
                    ["grep", "-r", "-l", "--include=*.py", "--include=*.ts",
                     "--include=*.tsx", term, str(search_dir)],
                    capture_output=True, text=True, timeout=10,
                )
                if result.returncode == 0 and result.stdout.strip():
                    return True
            except (subprocess.TimeoutExpired, FileNotFoundError):
                continue
    return False


def check_symbols(text: str) -> list[str]:
    """Return list of code symbols referenced in CLAUDE.md but missing from source."""
    candidates = {t for t in SYMBOL_RE.findall(text) if is_code_symbol(t)}
    return sorted(s for s in candidates if not symbol_exists_in_source(s))


# ---------------------------------------------------------------------------
# Tier 3: Count claims
# ---------------------------------------------------------------------------

# Pattern: "N runnable examples" or "N examples" where N is a number.
COUNT_RE = re.compile(r"(\d+)\s+runnable\s+examples")


def check_counts(text: str) -> list[str]:
    """Return list of stale count claims."""
    issues = []
    for match in COUNT_RE.finditer(text):
        claimed = int(match.group(1))
        # Examples live in examples/workflows/ (numbered subdirs)
        examples_dir = ROOT / "examples" / "workflows"
        if not examples_dir.exists():
            examples_dir = ROOT / "examples"
        if examples_dir.exists():
            # Count directories that look like runnable examples
            actual = sum(
                1 for d in examples_dir.iterdir()
                if d.is_dir()
                and not d.name.startswith("_")
                and not d.name.startswith(".")
            )
            if actual != claimed:
                issues.append(
                    f"Claims {claimed} runnable examples, found {actual} "
                    f"example directories in examples/"
                )
    return issues


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    if not CLAUDE_MD.exists():
        print(f"error: {CLAUDE_MD} not found", file=sys.stderr)
        return 2

    text = CLAUDE_MD.read_text(encoding="utf-8")
    all_issues: list[tuple[str, list[str]]] = []

    # Tier 1: paths
    stale_paths = check_paths(text)
    if stale_paths:
        all_issues.append(("Stale path references", stale_paths))

    # Tier 2: symbols
    missing_symbols = check_symbols(text)
    if missing_symbols:
        all_issues.append(("Missing code symbols", missing_symbols))

    # Tier 3: counts
    count_issues = check_counts(text)
    if count_issues:
        all_issues.append(("Stale count claims", count_issues))

    if all_issues:
        print("Drift detected in CLAUDE.md:\n")
        for category, items in all_issues:
            print(f"  {category}:")
            for item in items:
                print(f"    - {item}")
            print()

        total = sum(len(items) for _, items in all_issues)
        print(f"{total} issue(s) total. Update CLAUDE.md or fix the source.")
        return 1

    # Summarize what was checked
    path_count = len({
        n for t in PATH_RE.findall(text) if is_path_like(t)
        for n in [normalize_path(t)] if "/" in n
    })
    symbol_count = len({t for t in SYMBOL_RE.findall(text) if is_code_symbol(t)})
    print(
        f"OK — {path_count} path(s), {symbol_count} symbol(s), "
        f"{len(COUNT_RE.findall(text))} count claim(s) checked. All resolve."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
