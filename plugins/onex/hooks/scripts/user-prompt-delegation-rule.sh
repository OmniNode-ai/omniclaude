#!/bin/bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# UserPromptSubmit: Delegation Rule Injector
#
# On every user prompt:
#   1. Resets per-turn work-tool counter and state flags
#   2. Injects a hard delegation rule into Claude's context

set -euo pipefail
_OMNICLAUDE_HOOK_NAME="$(basename "${BASH_SOURCE[0]}")"
# Resolve script dir before cd $HOME (relative paths break after cwd change)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/error-guard.sh" 2>/dev/null || true
# shellcheck source=hook-runtime-client.sh
source "${SCRIPT_DIR}/hook-runtime-client.sh" 2>/dev/null || true

# --- Lite mode guard [OMN-5398] ---
_MODE_SH="${SCRIPT_DIR}/../../lib/mode.sh"
if [[ -f "$_MODE_SH" ]]; then source "$_MODE_SH"; [[ "$(omniclaude_mode)" == "lite" ]] && exit 0; fi
unset _MODE_SH

cd "$HOME" 2>/dev/null || cd /tmp || true

_log "started"

if ! command -v jq >/dev/null 2>&1; then
    _log "WARN" "jq not found, exiting"
    cat 2>/dev/null || true  # drain stdin if any
    exit 0
fi

# Read stdin with timeout — stdin may already be consumed by user-prompt-submit.sh
# (both hooks are in separate groups; first group drains stdin)
TOOL_INFO=""
if read -r -t 2 TOOL_INFO 2>/dev/null; then
    _log "read stdin"
else
    _log "WARN" "stdin empty or timed out, using fallback session detection"
fi
SESSION_ID=""
if [[ -n "$TOOL_INFO" ]]; then
    SESSION_ID=$(echo "$TOOL_INFO" | jq -r '.sessionId // .session_id // ""' 2>/dev/null) || SESSION_ID=""
fi
# Fallback: find session from existing state files
if [[ -z "$SESSION_ID" ]]; then
    # Look for the most recent write-count file to extract session ID
    SESSION_ID=$(ls -t /tmp/omniclaude-write-count-* 2>/dev/null | head -1 | sed 's|.*/omniclaude-write-count-||' || true)
    if [[ -n "$SESSION_ID" ]]; then
        _log "recovered session from state files: ${SESSION_ID:0:12}..."
    fi
fi

# Reset per-turn delegation state: notify daemon (authoritative) + clear shell fallback files
if [[ -n "$SESSION_ID" ]]; then
    # Notify daemon to reset session counters [OMN-5308]
    _hrt_request "{\"action\":\"reset_session\",\"session_id\":\"${SESSION_ID}\",\"payload\":{}}" > /dev/null 2>&1 || true
    # Bug fix: was resetting "work-count" but counter reads "write-count"
    echo "0" > "/tmp/omniclaude-write-count-${SESSION_ID}" 2>/dev/null || true
    echo "0" > "/tmp/omniclaude-read-count-${SESSION_ID}" 2>/dev/null || true
    rm -f "/tmp/omniclaude-delegated-${SESSION_ID}" \
          "/tmp/omniclaude-write-warned-${SESSION_ID}" \
          "/tmp/omniclaude-read-warned-${SESSION_ID}" \
          "/tmp/omniclaude-skill-loaded-${SESSION_ID}" \
          2>/dev/null || true
    # Clean up legacy state file name (transitional — can be removed after one deploy cycle)
    rm -f "/tmp/omniclaude-work-count-${SESSION_ID}" \
          "/tmp/omniclaude-warned-${SESSION_ID}" \
          2>/dev/null || true
fi

# Source config reader for threshold value (resilient — fallback to default on any failure)
RULE_THRESHOLD="2"
if source "${SCRIPT_DIR}/delegation-config.sh" 2>/dev/null; then
    RULE_THRESHOLD=$(_dc_read '.delegation_rule_tool_threshold' '2') || RULE_THRESHOLD="2"

# Build the rule text via a variable to avoid jq escaping issues
RULE_TEXT="DELEGATION RULE: For any task requiring more than ${RULE_THRESHOLD} tool calls, delegate as your FIRST action — before any reads, writes, or bash calls:
• Multiple independent subtasks (check N repos, run N tests, scan N files) → Skill('onex:parallel-solve')
• Single coherent task or workflow → Agent(subagent_type='onex:polymorphic-agent', prompt='...', description='...')
Conversational responses are exempt."

_log "emitting JSON output (threshold=${RULE_THRESHOLD})"

jq -n --arg msg "$RULE_TEXT" '{
    hookSpecificOutput: {
        additionalContext: $msg
    }
}'

_log "completed successfully"
exit 0
