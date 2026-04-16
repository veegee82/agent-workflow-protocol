#!/usr/bin/env bash
# PreToolUse hook for Bash: blocks `git commit` if doc checks fail.
#
# Enforces CLAUDE.md §2 "Doc Sync as Definition-of-Done" mechanically.
# Runs two checks before any commit:
#   1. Drift detector — stale paths + missing symbols + wrong counts
#   2. Sync coverage — code changes without corresponding MD updates
#
# Exit codes:
#   0 — not a commit, or all checks passed
#   2 — drift or sync gap detected, BLOCK the commit

set -euo pipefail

INPUT=$(cat)

# Extract the command from tool_input (Bash tool passes { "command": "..." })
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // empty' 2>/dev/null)

# Only gate on git commit commands
if ! echo "$COMMAND" | grep -qE '^\s*git\s+commit'; then
  exit 0
fi

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}"
ISSUES=""

# --- Gate 1: Drift detector (hard block) ---
DRIFT_SCRIPT="$PROJECT_DIR/scripts/check_docs_drift.py"
if [[ -f "$DRIFT_SCRIPT" ]]; then
  DRIFT_OUTPUT=$(python "$DRIFT_SCRIPT" 2>&1) || {
    ISSUES="${ISSUES}\n=== DRIFT CHECK FAILED (blocking) ===\n${DRIFT_OUTPUT}\n"
  }
fi

# --- Gate 2: Sync coverage (hard block) ---
SYNC_SCRIPT="$PROJECT_DIR/scripts/check_sync_coverage.py"
if [[ -f "$SYNC_SCRIPT" ]]; then
  SYNC_OUTPUT=$(python "$SYNC_SCRIPT" 2>&1) || {
    ISSUES="${ISSUES}\n=== SYNC COVERAGE GAPS (blocking) ===\n${SYNC_OUTPUT}\n"
  }
fi

# --- Gate 3: Mirror drift packages/ ↔ reference/python/src/ (hard block) ---
MIRROR_SCRIPT="$PROJECT_DIR/scripts/check_mirror_drift.py"
if [[ -f "$MIRROR_SCRIPT" ]]; then
  MIRROR_OUTPUT=$(python "$MIRROR_SCRIPT" 2>&1) || {
    ISSUES="${ISSUES}\n=== MIRROR DRIFT (blocking) ===\n${MIRROR_OUTPUT}\n"
  }
fi

if [[ -n "$ISSUES" ]]; then
  echo -e "BLOCKED: Doc sync issues detected — cannot commit.\n$ISSUES"
  echo "Fix these before committing. See CLAUDE.md §2."
  exit 2
fi

# All checks passed
exit 0