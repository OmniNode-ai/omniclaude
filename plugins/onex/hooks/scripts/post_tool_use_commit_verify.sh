#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Post-tool-use hook: verify git commit landed [OMN-6933]
#
# Fires after Bash tool use. If the command contained "git commit",
# inject a reminder to verify the commit landed via git log + git status.
# This catches false-completion where the commit was attempted but failed
# (e.g., pre-commit hook failure) and the agent proceeds as if it succeeded.

set -euo pipefail

# Read tool input from stdin
INPUT=$(cat)

# Guard: jq required for JSON processing
if ! command -v jq >/dev/null 2>&1; then
  printf '%s\n' "$INPUT"
  exit 0
fi

# Extract the command that was run
TOOL_INPUT=$(echo "$INPUT" | jq -r '.tool_input.command // empty' 2>/dev/null)

# Only fire if the command contained "git commit"
if [[ -z "$TOOL_INPUT" ]] || ! echo "$TOOL_INPUT" | grep -q 'git commit'; then
  printf '%s\n' "$INPUT"
  exit 0
fi

# Check if the tool use succeeded or failed
TOOL_ERROR=$(echo "$INPUT" | jq -r '.tool_error // empty' 2>/dev/null)

if [[ -n "$TOOL_ERROR" ]]; then
  MSG="COMMIT VERIFICATION: The git commit command failed. Before proceeding, run \`git log -1 --oneline && git status\` to confirm the working tree state. Do NOT assume the commit landed."
else
  MSG="COMMIT VERIFICATION: Run \`git log -1 --oneline && git status\` to confirm the commit landed and no files remain staged/unstaged."
fi

# PostToolUse hooks must output the original tool JSON (passthrough).
# Inject the verification reminder into hookSpecificOutput so Claude sees it.
echo "$INPUT" | jq --arg msg "$MSG" '
  .hookSpecificOutput = (.hookSpecificOutput // {}) |
  .hookSpecificOutput.message = (
    [(.hookSpecificOutput.message // ""), $msg]
    | map(select(length > 0))
    | join("\n\n")
  )'
