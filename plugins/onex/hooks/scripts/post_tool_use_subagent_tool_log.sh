#!/bin/bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
# PostToolUse: append JSONL tool-call record when the tool fires inside a
# subagent dispatch (OMN-9084). Skips when not inside a dispatch.
# Event: PostToolUse | Matcher: .* | Ticket: OMN-9084
set -euo pipefail
HOOK_EVENT=$(cat)
printf '%s\n' "$HOOK_EVENT"
[[ "${OMNICLAUDE_HOOKS_DISABLED:-0}" == "1" ]] && exit 0
command -v jq >/dev/null 2>&1 || exit 0
AGENT_ID="${ONEX_AGENT_ID:-$(printf '%s' "$HOOK_EVENT" | jq -r '.agent_id // .agent_name // ""' 2>/dev/null)}"
[[ -z "$AGENT_ID" || "$AGENT_ID" == "null" ]] && exit 0
[[ ! "$AGENT_ID" =~ ^[A-Za-z0-9._-]+$ ]] && exit 0
source "$(dirname "${BASH_SOURCE[0]}")/onex-paths.sh"
DISPATCH_DIR="${ONEX_STATE_DIR}/dispatches/${AGENT_ID}"
mkdir -p "$DISPATCH_DIR" 2>/dev/null || exit 0
TOOL_NAME=$(printf '%s' "$HOOK_EVENT" | jq -r '.tool_name // "unknown"')
DECISION=$(printf '%s' "$HOOK_EVENT" | jq -r '.tool_response.decision // "allow"')
DURATION=$(printf '%s' "$HOOK_EVENT" | jq -r '.tool_response.duration_ms // 0')
ERROR=$(printf '%s' "$HOOK_EVENT" | jq -r '.tool_response.error // null' | tr -d '\n')
TS=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
jq -cn --arg ts "$TS" --arg aid "$AGENT_ID" --arg tn "$TOOL_NAME" \
    --arg dec "$DECISION" --argjson dur "${DURATION:-0}" --arg err "$ERROR" \
    '{ts:$ts, agent_id:$aid, tool_name:$tn, decision:$dec, duration_ms:$dur, error:(if $err=="null" then null else $err end)}' \
    >> "${DISPATCH_DIR}/tool-calls.jsonl" 2>/dev/null || true
exit 0
