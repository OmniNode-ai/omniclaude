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

# Extract the command that was run
TOOL_INPUT=$(echo "$INPUT" | jq -r '.tool_input.command // empty' 2>/dev/null)

# Only fire if the command contained "git commit"
if [[ -z "$TOOL_INPUT" ]] || ! echo "$TOOL_INPUT" | grep -q 'git commit'; then
  exit 0
fi

# Check if the tool use succeeded or failed
TOOL_ERROR=$(echo "$INPUT" | jq -r '.tool_error // empty' 2>/dev/null)

if [[ -n "$TOOL_ERROR" ]]; then
  # Commit command errored -- inject verification reminder
  cat <<'VERIFY'
{"decision": "allow", "message": "COMMIT VERIFICATION: The git commit command failed. Before proceeding, run `git log -1 --oneline && git status` to confirm the working tree state. Do NOT assume the commit landed."}
VERIFY
else
  # Commit command succeeded -- still inject verification as a safety measure
  cat <<'VERIFY'
{"decision": "allow", "message": "COMMIT VERIFICATION: Run `git log -1 --oneline && git status` to confirm the commit landed and no files remain staged/unstaged."}
VERIFY
fi
