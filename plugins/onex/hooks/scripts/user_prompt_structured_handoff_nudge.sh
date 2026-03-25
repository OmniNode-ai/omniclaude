#!/bin/bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# UserPromptSubmit Structured Handoff Nudge Hook
# Detects free-form complex task requests and prepends a gentle nudge
# toward structured format. Fires once per session on the first
# unstructured complex request. Soft gate — informational, not blocking.
#
# Event:   UserPromptSubmit
# Ticket:  OMN-6526

set -euo pipefail

# -----------------------------------------------------------------------
# Kill switches
# -----------------------------------------------------------------------
if [[ "${OMNICLAUDE_HOOKS_DISABLED:-0}" == "1" ]]; then
    cat  # drain stdin
    exit 0
fi
if [[ "${OMNICLAUDE_HOOK_HANDOFF_NUDGE:-1}" == "0" ]]; then
    cat  # drain stdin
    exit 0
fi

# -----------------------------------------------------------------------
# Read stdin (Claude Code UserPromptSubmit JSON)
# -----------------------------------------------------------------------
PROMPT_INFO=$(cat)

# Guard: jq is required
if ! command -v jq >/dev/null 2>&1; then
    printf '%s\n' "$PROMPT_INFO"
    exit 0
fi

# -----------------------------------------------------------------------
# Once-per-session gate: check if we already nudged
# -----------------------------------------------------------------------
SESSION_ID=$(printf '%s' "$PROMPT_INFO" | jq -r '.sessionId // "unknown"' 2>/dev/null) || SESSION_ID="unknown"
NUDGE_FLAG="${HOME}/.claude/.handoff-nudge-fired-${SESSION_ID}"

if [[ -f "$NUDGE_FLAG" ]]; then
    # Already nudged this session — pass through
    printf '%s\n' "$PROMPT_INFO"
    exit 0
fi

# -----------------------------------------------------------------------
# Detect unstructured complex requests
# -----------------------------------------------------------------------
PROMPT_TEXT=$(printf '%s' "$PROMPT_INFO" | jq -r '.prompt // ""' 2>/dev/null) || PROMPT_TEXT=""
PROMPT_LEN=${#PROMPT_TEXT}

# Short prompts are not complex requests — skip
if [[ "$PROMPT_LEN" -lt 50 ]]; then
    printf '%s\n' "$PROMPT_INFO"
    exit 0
fi

# Check for structured fields — if present, this is already structured
HAS_STRUCTURE=false
if echo "$PROMPT_TEXT" | grep -qiE '(^|\n)\s*(Task:|Scope:|Constraints:|Done when:|Workflow:|Requirements:|Files:)'; then
    HAS_STRUCTURE=true
fi

# Check for skill invocations — these are already dispatched
if echo "$PROMPT_TEXT" | grep -qE '^/[a-z]'; then
    HAS_STRUCTURE=true
fi

if [[ "$HAS_STRUCTURE" == "true" ]]; then
    printf '%s\n' "$PROMPT_INFO"
    exit 0
fi

# -----------------------------------------------------------------------
# Fire the nudge (once per session)
# -----------------------------------------------------------------------
mkdir -p "$(dirname "$NUDGE_FLAG")" 2>/dev/null || true
touch "$NUDGE_FLAG" 2>/dev/null || true

NUDGE="[Handoff Tip] For complex tasks, structure your request for better results:
  Task: [one sentence description]
  Scope: [repos/files involved]
  Workflow: [which skill to use, e.g., /ticket-pipeline, /epic-team]
  Constraints: [what NOT to do]
  Done when: [acceptance criteria]
This is a one-time suggestion for this session."

# Inject the nudge into the output
MODIFIED=$(printf '%s' "$PROMPT_INFO" | jq \
    --arg nudge "$NUDGE" \
    '.hookSpecificOutput = (.hookSpecificOutput // {}) |
     .hookSpecificOutput.additionalContext = (
       ((.hookSpecificOutput.additionalContext // "") + "\n\n" + $nudge)
       | ltrimstr("\n\n")
     )' 2>/dev/null)

if [[ -n "$MODIFIED" && "$MODIFIED" != "null" ]]; then
    printf '%s\n' "$MODIFIED"
else
    printf '%s\n' "$PROMPT_INFO"
fi

exit 0
