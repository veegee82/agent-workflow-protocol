#!/usr/bin/env bash
# Pre-Edit/Write hook: blocks edits if no *.md files were read in the session.
#
# Rationale: CLAUDE.md §1 requires reading relevant MDs before any work.
# This hook enforces that mechanically — at least one .md Read must appear
# in the transcript before the first Edit/Write is allowed.
#
# Exit codes:
#   0 — at least one .md was read, proceed
#   2 — no .md read yet, BLOCK the edit

set -euo pipefail

# Read JSON from stdin (Claude Code passes session info)
INPUT=$(cat)
TRANSCRIPT=$(echo "$INPUT" | jq -r '.transcript_path // empty')

if [[ -z "$TRANSCRIPT" || ! -f "$TRANSCRIPT" ]]; then
  # No transcript available — allow (first tool call, or non-standard invocation)
  exit 0
fi

# Check if any Read tool call targeted a .md file in the transcript so far.
# Transcript is JSONL; each line is a JSON object.
# We look for Read tool_use entries where the file_path ends in .md
MD_READ_COUNT=$(grep -c '"file_path".*\.md"' "$TRANSCRIPT" 2>/dev/null || true)

if [[ "$MD_READ_COUNT" -gt 0 ]]; then
  exit 0
fi

# Also check if CLAUDE.md was auto-loaded (appears as system context, not a Read call).
# If the transcript contains any reference to reading markdown content, allow it.
CLAUDE_MD_REF=$(grep -c 'CLAUDE\.md\|README\.md\|SKILL\.md' "$TRANSCRIPT" 2>/dev/null || true)

if [[ "$CLAUDE_MD_REF" -gt 0 ]]; then
  exit 0
fi

# No evidence of MD reading — block
cat <<'REASON'
BLOCKED: Session Start Protocol violation.

CLAUDE.md §1 requires reading relevant *.md files before any code changes.
No .md file reads detected in this session yet.

Read the relevant markdown files first (at minimum CLAUDE.md), then retry.
See the "Required Reading by Task Type" table in CLAUDE.md §1 for guidance.
REASON

exit 2