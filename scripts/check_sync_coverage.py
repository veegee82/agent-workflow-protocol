#!/usr/bin/env python3
"""Check whether staged code changes have corresponding MD updates.

Implements the "what changed → what to sync" table from CLAUDE.md §2
as a mechanical gate. Inspects `git diff --cached` (staged changes)
and flags which MDs *should* have been updated but weren't.

Exit codes:
    0 — no sync warnings (all expected MDs were touched, or no code changes).
    1 — at least one MD should have been updated but wasn't.

This is a WARNING gate, not a hard block — prose accuracy can't be
verified mechanically. The output tells you what to review.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# The sync table from CLAUDE.md §2, encoded as rules.
# Each rule: (code_pattern, expected_md_files, description)
# ---------------------------------------------------------------------------

SYNC_RULES: list[tuple[list[str], list[str], str]] = [
    # Model fields changed
    (
        ["packages/awp-core/src/awp/models/"],
        ["CLAUDE.md", "docs/"],
        "Model field change → update CLAUDE.md (Key Protocols) + docs/ layer doc",
    ),
    # Validator / rules changed
    (
        ["packages/awp-core/src/awp/validator/"],
        ["CLAUDE.md", "docs/", "spec/"],
        "Validation rule change → update CLAUDE.md + docs/ + spec/",
    ),
    # CLI changed
    (
        ["packages/awp-core/src/awp/cli.py"],
        ["CLAUDE.md", "README.md"],
        "CLI change → update CLAUDE.md (Development Commands) + README.md",
    ),
    # Runtime / engine behavior
    (
        [
            "packages/awp-runtime/src/awp/runtime/runner.py",
            "packages/awp-runtime/src/awp/runtime/delegation_loop_runner.py",
        ],
        ["CLAUDE.md", "docs/"],
        "Runtime/engine change → update CLAUDE.md (Orchestration Engines) + docs/",
    ),
    # Tool registry
    (
        ["packages/awp-runtime/src/awp/runtime/tools.py"],
        ["CLAUDE.md", "skill/SKILL.md"],
        "Tool change → update CLAUDE.md (if referenced) + skill/SKILL.md",
    ),
    # LLM client / provider routing
    (
        ["packages/awp-runtime/src/awp/runtime/llm.py"],
        ["CLAUDE.md"],
        "LLM/provider change → update CLAUDE.md (Default Model & Provider Routing)",
    ),
    # UI server routes
    (
        ["packages/awp-ui/server/"],
        ["CLAUDE.md"],
        "UI server change → check CLAUDE.md references",
    ),
    # Security models
    (
        ["packages/awp-core/src/awp/models/security.py"],
        ["CLAUDE.md", "skill/SKILL.md"],
        "Security change → update CLAUDE.md (Security) + skill/SKILL.md",
    ),
    # Skill templates
    (
        ["skill/"],
        ["skill/SKILL.md"],
        "Skill template change → update skill/SKILL.md",
    ),
    # Examples added/removed
    (
        ["examples/"],
        ["README.md"],
        "Example change → update README.md example count/list",
    ),
]


def get_staged_files() -> list[str]:
    """Return list of staged file paths (relative to repo root)."""
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        capture_output=True, text=True, cwd=ROOT,
    )
    if result.returncode != 0:
        # Also try unstaged (for pre-commit context where all changes matter)
        result = subprocess.run(
            ["git", "diff", "--name-only", "HEAD"],
            capture_output=True, text=True, cwd=ROOT,
        )
    return [f.strip() for f in result.stdout.strip().splitlines() if f.strip()]


def get_all_changed_files() -> list[str]:
    """Return all changed files (staged + unstaged + untracked modified)."""
    # Staged
    staged = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        capture_output=True, text=True, cwd=ROOT,
    )
    # Unstaged
    unstaged = subprocess.run(
        ["git", "diff", "--name-only"],
        capture_output=True, text=True, cwd=ROOT,
    )
    files = set()
    for r in [staged, unstaged]:
        if r.returncode == 0:
            files.update(f.strip() for f in r.stdout.splitlines() if f.strip())
    return sorted(files)


def file_matches_pattern(filepath: str, pattern: str) -> bool:
    """Check if a filepath starts with or matches a pattern."""
    return filepath.startswith(pattern) or filepath == pattern


def main() -> int:
    changed_files = get_all_changed_files()
    if not changed_files:
        print("No changed files detected.")
        return 0

    # Separate code changes from MD changes
    changed_code = [f for f in changed_files if not f.endswith(".md")]
    changed_mds = {f for f in changed_files if f.endswith(".md")}

    if not changed_code:
        print("Only MD files changed — no sync check needed.")
        return 0

    warnings: list[str] = []

    for code_patterns, expected_mds, description in SYNC_RULES:
        # Check if any changed code file matches this rule's patterns
        triggered = any(
            file_matches_pattern(cf, pat)
            for cf in changed_code
            for pat in code_patterns
        )
        if not triggered:
            continue

        # Check if the expected MDs were also changed
        missing_mds = []
        for expected in expected_mds:
            # Check if any changed MD starts with the expected pattern
            if not any(cm.startswith(expected) or cm == expected for cm in changed_mds):
                missing_mds.append(expected)

        if missing_mds:
            warnings.append(
                f"  {description}\n"
                f"    Code touched: {', '.join(pat for pat in code_patterns if any(file_matches_pattern(cf, pat) for cf in changed_code))}\n"
                f"    Missing MD updates: {', '.join(missing_mds)}"
            )

    if warnings:
        print("Doc sync warnings — these MDs may need updating:\n")
        for w in warnings:
            print(w)
            print()
        print(
            f"{len(warnings)} rule(s) triggered. Review the sync table in "
            f"CLAUDE.md §2 and update the listed MDs if their content is affected."
        )
        return 1

    print(f"OK — {len(changed_code)} code file(s) checked against sync rules. No gaps found.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
