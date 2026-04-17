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
source "$(dirname "${BASH_SOURCE[0]}")/onex-paths.sh"
# Slug-constrain AGENT_ID before path interpolation. Excludes '.' to block '..'
# traversal and '/' / '\' separators; caps length at 64 chars. On reject,
# emit a friction record and passthrough (exit 0) so the hook never blocks
# the tool result from reaching the model.
if [[ ! "$AGENT_ID" =~ ^[a-zA-Z0-9_-]{1,64}$ ]]; then
    FRICTION_DIR="${ONEX_STATE_DIR}/friction/agent_id_reject"
    mkdir -p "$FRICTION_DIR" 2>/dev/null || exit 0
    TS_NS=$(date -u +%s%N 2>/dev/null || date -u +%s)
    DATE_PREFIX=$(date -u +%Y-%m-%d)
    AGENT_ID_PREVIEW=$(printf '%s' "$AGENT_ID" | head -c 200 | tr -d '\n\r' | sed 's/"/\\"/g')
    cat > "${FRICTION_DIR}/${DATE_PREFIX}-reject-${TS_NS}.yaml" <<___AGENT_ID_REJECT_EOF___ || true
id: agent-id-reject-${TS_NS}
date: ${DATE_PREFIX}
severity: MAJOR
surface: agent_id_reject
category: hook_security
title: "Rejected non-slug AGENT_ID in subagent tool-log hook"
summary: >
  post_tool_use_subagent_tool_log.sh received an AGENT_ID that failed the
  slug regex ^[a-zA-Z0-9_-]{1,64}$ and was rejected before path interpolation
  to prevent traversal outside dispatches/.
agent_id_preview: "${AGENT_ID_PREVIEW}"
linear_ticket: OMN-9084
___AGENT_ID_REJECT_EOF___
    exit 0
fi
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
