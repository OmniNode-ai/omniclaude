#!/bin/bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# PreToolUse Plan Existence Gate Hook
# Blocks Edit/Write on ticket-shaped branches (jonah/omn-XXXX-*) when no
# file exists under docs/plans/ in the repository root.
#
# Event:   PreToolUse
# Matcher: ^(Edit|Write)$
# Ticket:  OMN-8417

set -euo pipefail

# -----------------------------------------------------------------------
# Kill switches
# -----------------------------------------------------------------------
if [[ "${OMNICLAUDE_HOOKS_DISABLED:-0}" == "1" ]]; then
    cat  # drain stdin
    exit 0
fi
if [[ "${OMNICLAUDE_HOOK_PLAN_EXISTENCE_GATE:-1}" == "0" ]]; then
    cat  # drain stdin
    exit 0
fi

# -----------------------------------------------------------------------
# Read stdin (Claude Code PreToolUse JSON)
# -----------------------------------------------------------------------
TOOL_INFO=$(cat)

# Guard: jq is required
if ! command -v jq >/dev/null 2>&1; then
    printf '%s\n' "$TOOL_INFO"
    exit 0
fi

# -----------------------------------------------------------------------
# Detect current branch — only fire on ticket-shaped branches
# -----------------------------------------------------------------------
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null) || CURRENT_BRANCH=""

# Pattern: any string containing /omn-NNNN- (case-insensitive ticket slug)
if [[ ! "$CURRENT_BRANCH" =~ /omn-[0-9]+-[a-zA-Z0-9_-]+ ]]; then
    # Not a ticket branch — pass through
    printf '%s\n' "$TOOL_INFO"
    exit 0
fi

# -----------------------------------------------------------------------
# Locate the repo root (where docs/plans/ should live)
# -----------------------------------------------------------------------
REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null) || REPO_ROOT=""

if [[ -z "$REPO_ROOT" ]]; then
    # Cannot determine repo root — pass through
    printf '%s\n' "$TOOL_INFO"
    exit 0
fi

PLANS_DIR="${REPO_ROOT}/docs/plans"

# -----------------------------------------------------------------------
# Check for at least one file in docs/plans/
# -----------------------------------------------------------------------
PLAN_COUNT=0
if [[ -d "$PLANS_DIR" ]]; then
    PLAN_COUNT=$(find "$PLANS_DIR" -maxdepth 3 -type f | wc -l | tr -d ' ')
fi

if [[ "$PLAN_COUNT" -gt 0 ]]; then
    # Plan file exists — pass through
    printf '%s\n' "$TOOL_INFO"
    exit 0
fi

# -----------------------------------------------------------------------
# Block: ticket branch detected, no plan file found
# -----------------------------------------------------------------------
BLOCK_MSG="[Plan Gate] Ticket branch detected (${CURRENT_BRANCH}) but no plan file found in docs/plans/. Create a plan before implementing. To bypass (with explicit reason): set OMNICLAUDE_HOOK_PLAN_EXISTENCE_GATE=0."

# Log the block event
LOG_DIR="${HOME}/.claude/plan-gate-events"
mkdir -p "$LOG_DIR" 2>/dev/null || true
printf '{"timestamp":"%s","event":"plan_missing_block","branch":"%s","repo":"%s"}\n' \
    "$(date -u +"%Y-%m-%dT%H:%M:%SZ")" \
    "$(printf '%s' "$CURRENT_BRANCH" | head -c 200)" \
    "$(printf '%s' "$REPO_ROOT" | head -c 200)" \
    >> "$LOG_DIR/events.jsonl" 2>/dev/null || true

printf '%s' "$TOOL_INFO" | jq \
    --arg msg "$BLOCK_MSG" \
    '{
      "decision": "block",
      "reason": $msg
    }' 2>/dev/null || printf '{"decision":"block","reason":"%s"}' "$BLOCK_MSG"

exit 2
