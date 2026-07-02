#!/bin/bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# PreToolUse Changeset Guard Hook
# Warns when broad staging commands (git add -A, git add .) are detected.
# Warning-only Phase 1 — does not block, only injects advisory context.
#
# Event:   PreToolUse
# Matcher: Bash
# Ticket:  OMN-6524

set -euo pipefail

# -----------------------------------------------------------------------
# Kill switches
# -----------------------------------------------------------------------
if [[ "${OMNICLAUDE_HOOKS_DISABLED:-0}" == "1" ]]; then
    cat  # drain stdin
    exit 0
fi
source "$(dirname "${BASH_SOURCE[0]}")/hook-gate.sh" 2>/dev/null || true
onex_hook_gate CHANGESET_GUARD_PRE || exit 0

# -----------------------------------------------------------------------
# Read stdin (Claude Code PreToolUse JSON)
# -----------------------------------------------------------------------
TOOL_INFO=$(cat)

# Guard: jq is required
if ! command -v jq >/dev/null 2>&1; then
    printf '%s\n' "$TOOL_INFO"
    exit 0
fi

# Extract the Bash command from tool input
TOOL_CMD=$(printf '%s' "$TOOL_INFO" | jq -r '.tool_input.command // ""' 2>/dev/null) || TOOL_CMD=""

# -----------------------------------------------------------------------
# Gate: detect broad staging patterns
# -----------------------------------------------------------------------
BROAD_STAGING=false

# Match broad staging only: git add -A, git add --all, git add .
# The trailing ([[:space:]]|$) anchor makes the '.' match ONLY when it is the
# whole pathspec argument. Without it the unanchored '\.' matched a literal dot
# anywhere after 'git add ', flagging specific-file stages like
# 'git add .gitignore', 'git add .env', or 'git add ./src/x.py' (~72% false
# positives). Anchoring keeps genuine broad staging and drops the dotfile noise
# (OMN-13848).
if echo "$TOOL_CMD" | grep -qE 'git\s+add\s+(-A|--all|\.)([[:space:]]|$)'; then
    BROAD_STAGING=true
fi

if [[ "$BROAD_STAGING" != "true" ]]; then
    printf '%s\n' "$TOOL_INFO"
    exit 0
fi

# -----------------------------------------------------------------------
# Emit warning via hookSpecificOutput
# -----------------------------------------------------------------------
WARNING="[Changeset Guard] WARNING: Broad staging detected (git add -A / git add .). Prefer adding specific files by name to avoid committing secrets, unrelated changes, or large binaries. If intentional, proceed — this is a warning, not a block."

# Record the event on the OBSERVABLE friction registry (OMN-13848).
# The previous sink appended to ~/.claude/changeset-guard-events/events.jsonl --
# a path no tool reads and one that violates the "never write state under
# ~/.claude" doctrine, so the signal was dead. Route the event to
# ${ONEX_STATE_DIR}/friction/changeset_guard/ instead, matching the sibling
# shell hooks (permission_denied_logger.sh, kafka_poison guard) whose friction
# drop-files the friction tooling (/onex:friction_triage, friction observer)
# scans. Skip silently when the caller did not supply ONEX_STATE_DIR (infra
# failure -> never fabricate a $HOME/.onex_state fallback).
_INPUT_ONEX_STATE_DIR="${ONEX_STATE_DIR:-}"
source "$(dirname "${BASH_SOURCE[0]}")/onex-paths.sh" 2>/dev/null || true
if [[ -n "${_INPUT_ONEX_STATE_DIR}" ]]; then
    _cg_sanitize() { printf '%s' "$1" | tr -d '\n\r' | sed 's/"/\\"/g'; }
    CG_SESSION_ID=$(printf '%s' "$TOOL_INFO" | jq -r '.session_id // .sessionId // "unknown"' 2>/dev/null || printf 'unknown')
    CG_SESSION_ID=$(_cg_sanitize "$CG_SESSION_ID")
    CG_CMD_EXCERPT=$(_cg_sanitize "$(printf '%s' "$TOOL_CMD" | head -c 200)")
    CG_DATE=$(date -u +%Y-%m-%d)
    CG_TS_NS=$(date -u +%s%N 2>/dev/null || date -u +%s)
    CG_FRICTION_DIR="${ONEX_STATE_DIR}/friction/changeset_guard"
    mkdir -p "$CG_FRICTION_DIR" 2>/dev/null || true
    cat > "${CG_FRICTION_DIR}/${CG_DATE}-broad-staging-${CG_TS_NS}.yaml" <<YAML || true
id: changeset-broad-staging-${CG_SESSION_ID:0:8}-${CG_TS_NS}
date: ${CG_DATE}
severity: P3
surface: changeset_guard
category: changeset
title: "Broad git staging detected (git add -A / --all / .)"
summary: >
  PreToolUse changeset guard observed a broad staging command. Prefer staging
  specific files by name to avoid committing secrets, unrelated changes, or
  large binaries.
impact: >
  Broad staging risks committing secrets, unrelated changes, or large binaries.
  A chronic pattern crosses the friction threshold and escalates for review.
root_cause: >
  Broad staging command issued: ${CG_CMD_EXCERPT}
command: "${CG_CMD_EXCERPT}"
session_id: "${CG_SESSION_ID}"
linear_ticket: OMN-6524
YAML
    unset -f _cg_sanitize
fi

# Inject the warning into the output
MODIFIED=$(printf '%s' "$TOOL_INFO" | jq \
    --arg warning "$WARNING" \
    '.hookSpecificOutput = (.hookSpecificOutput // {}) |
     .hookSpecificOutput.hookEventName = "PreToolUse" |
     .hookSpecificOutput.additionalContext = (
       ((.hookSpecificOutput.additionalContext // "") + "\n\n" + $warning)
       | ltrimstr("\n\n")
     )' 2>/dev/null)

if [[ -n "$MODIFIED" && "$MODIFIED" != "null" ]]; then
    printf '%s\n' "$MODIFIED"
else
    printf '%s\n' "$TOOL_INFO"
fi

exit 0
