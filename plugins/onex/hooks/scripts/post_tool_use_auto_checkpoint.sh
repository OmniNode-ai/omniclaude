#!/bin/bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# PostToolUse Auto-Checkpoint Hook
# After a git commit, auto-writes a lightweight checkpoint file to
# ~/.claude/handoffs/ for session recovery. Retention is CHECKPOINT_RETENTION
# (default 200): the original cap of 5 destroyed the entire pre-2026-07-02
# series, which is why the archaeology could recover only 5 files, all from a
# single 8-hour window.
#
# Event:   PostToolUse
# Matcher: Bash
# Ticket:  OMN-6528

set -euo pipefail

# -----------------------------------------------------------------------
# Kill switches
# -----------------------------------------------------------------------
if [[ "${OMNICLAUDE_HOOKS_DISABLED:-0}" == "1" ]]; then
    cat  # drain stdin
    exit 0
fi
source "$(dirname "${BASH_SOURCE[0]}")/hook-gate.sh" 2>/dev/null || true
onex_hook_gate AUTO_CHECKPOINT || exit 0

# -----------------------------------------------------------------------
# Read stdin (Claude Code PostToolUse JSON)
# -----------------------------------------------------------------------
TOOL_INFO=$(cat)

# Guard: jq is required
if ! command -v jq >/dev/null 2>&1; then
    exit 0
fi

# Extract the Bash command from tool input
TOOL_CMD=$(printf '%s' "$TOOL_INFO" | jq -r '.tool_input.command // ""' 2>/dev/null) || TOOL_CMD=""

# -----------------------------------------------------------------------
# Gate: only fire when the command contains "git commit"
# -----------------------------------------------------------------------
if [[ "$TOOL_CMD" != *"git commit"* ]]; then
    exit 0
fi

# -----------------------------------------------------------------------
# Gather checkpoint data (best-effort, fail open)
# -----------------------------------------------------------------------
CHECKPOINT_DIR="${HOME}/.claude/handoffs"
mkdir -p "$CHECKPOINT_DIR" 2>/dev/null || true

TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
TIMESTAMP_FILE=$(date -u +"%Y%m%d-%H%M%S")

# Git info (best-effort)
COMMIT_MSG=$(git log -1 --pretty=format:"%s" 2>/dev/null) || COMMIT_MSG="(unknown)"
COMMIT_HASH=$(git log -1 --pretty=format:"%h" 2>/dev/null) || COMMIT_HASH="(unknown)"
BRANCH=$(git branch --show-current 2>/dev/null) || BRANCH="(unknown)"
FILES_CHANGED=$(git diff --stat HEAD~1 HEAD 2>/dev/null | tail -1) || FILES_CHANGED="(unknown)"

# Active plan file (check common locations)
ACTIVE_PLAN=""
if [[ -f "${HOME}/.claude/scope-manifest.json" ]]; then
    ACTIVE_PLAN=$(jq -r '.plan_file // ""' "${HOME}/.claude/scope-manifest.json" 2>/dev/null) || ACTIVE_PLAN=""
fi

# PR status (best-effort, non-blocking)
PR_STATUS=""
if command -v gh >/dev/null 2>&1; then
    # Bounded: `gh pr view` is a network call on the PostToolUse path. Without the
    # timeout a hung remote stalls the hook (and, pre-OMN-17224, stacks emitters).
    PR_STATUS=$(timeout 5 gh pr view --json number,url,state 2>/dev/null | jq -r '"PR #\(.number) [\(.state)]: \(.url)"' 2>/dev/null) || PR_STATUS=""
fi

# -----------------------------------------------------------------------
# Write checkpoint file
# -----------------------------------------------------------------------
CHECKPOINT_FILE="${CHECKPOINT_DIR}/checkpoint-${TIMESTAMP_FILE}.md"

cat > "$CHECKPOINT_FILE" << CHECKPOINT_EOF
---
type: auto-checkpoint
created_at: ${TIMESTAMP}
commit_hash: ${COMMIT_HASH}
branch: ${BRANCH}
---

## Last Commit

- **Message**: ${COMMIT_MSG}
- **Hash**: ${COMMIT_HASH}
- **Branch**: ${BRANCH}
- **Files**: ${FILES_CHANGED}

## Session State

- **Active plan**: ${ACTIVE_PLAN:-none}
- **PR status**: ${PR_STATUS:-none}

## Recovery Notes

This checkpoint was auto-generated after a git commit.
Use \`/onex:session\` to resume from this point.
CHECKPOINT_EOF

# -----------------------------------------------------------------------
# Retention: keep the last CHECKPOINT_RETENTION checkpoints
# -----------------------------------------------------------------------
CHECKPOINT_COUNT=$(ls -1 "${CHECKPOINT_DIR}"/checkpoint-*.md 2>/dev/null | wc -l | tr -d '[:space:]')
RETENTION="${OMNICLAUDE_CHECKPOINT_RETENTION:-200}"
if [[ "$CHECKPOINT_COUNT" -gt "$RETENTION" ]]; then
    # Delete oldest checkpoints (sorted by name = sorted by timestamp)
    DELETE_COUNT=$((CHECKPOINT_COUNT - RETENTION))
    ls -1 "${CHECKPOINT_DIR}"/checkpoint-*.md 2>/dev/null | head -n "$DELETE_COUNT" | while read -r old_file; do
        rm -f "$old_file" 2>/dev/null || true
    done
fi

# -----------------------------------------------------------------------
# Emit NOTHING. Plain PostToolUse stdout is debug-log-only
# (knowledge-base:reference/claude-code-posttooluse-output-shape.md), and echoing
# $TOOL_INFO back would re-emit the raw tool_response that the OMN-16277
# secret-redaction guard masks on this same Bash matcher. The checkpoint file
# is the only output of this hook.
# -----------------------------------------------------------------------
exit 0
