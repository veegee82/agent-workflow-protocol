#!/usr/bin/env bash
# PostToolUse hook for Edit/Write: reminds about doc sync when editing .py/.ts files.
#
# Non-blocking (exit 0 always). Outputs a short reminder when code files are
# edited, so the model doesn't forget to sync MDs before committing.

set -euo pipefail

INPUT=$(cat)

# Extract the file path from tool_input
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty' 2>/dev/null)

if [[ -z "$FILE_PATH" ]]; then
  exit 0
fi

# Only trigger for code files, not for MDs or configs
case "$FILE_PATH" in
  *.py|*.ts|*.tsx)
    ;;
  *)
    exit 0
    ;;
esac

# Determine which area was touched and give specific guidance
HINT=""
case "$FILE_PATH" in
  */models/*)
    HINT="Model change — check CLAUDE.md (Key Protocols) + docs/ layer doc"
    ;;
  */validator/*|*/rules.py)
    HINT="Validator change — check CLAUDE.md + docs/ + spec/"
    ;;
  */runtime/runner.py|*/runtime/delegation_loop_runner.py)
    HINT="Engine change — check CLAUDE.md (Orchestration Engines) + docs/"
    ;;
  */runtime/tools.py)
    HINT="Tool change — check CLAUDE.md + skill/SKILL.md"
    ;;
  */runtime/llm.py)
    HINT="LLM/provider change — check CLAUDE.md (Default Model & Provider Routing)"
    ;;
  */cli.py)
    HINT="CLI change — check CLAUDE.md (Development Commands) + README.md"
    ;;
  */server/*|*/services/*)
    HINT="Server change — check CLAUDE.md references"
    ;;
  *skill/*)
    HINT="Skill change — check skill/SKILL.md"
    ;;
  *)
    # Generic code file — no specific hint
    exit 0
    ;;
esac

if [[ -n "$HINT" ]]; then
  echo "Doc sync reminder: $HINT (CLAUDE.md §2)"
fi

exit 0