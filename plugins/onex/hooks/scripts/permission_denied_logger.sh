#!/bin/bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# PermissionDenied Hook — write P2 friction YAML when auto-mode denies a tool [OMN-8873]
#
# Input (stdin):
# {
#   "session_id": "abc123",
#   "tool_name": "Bash",
#   "reason": "tool not in allowedTools",
#   "agent_name": "worker-1"
# }
#
# Output (stdout): {} (non-blocking — denial is surfaced, not masked)

set -euo pipefail
_OMNICLAUDE_HOOK_NAME="$(basename "${BASH_SOURCE[0]}")"

# Resolve absolute script dir BEFORE any cd (relative dirname breaks after cd)
_SELF="$(realpath "${BASH_SOURCE[0]}" 2>/dev/null \
    || python3 -c "import os,sys; print(os.path.realpath(sys.argv[1]))" "${BASH_SOURCE[0]}")"
_SCRIPT_DIR="$(cd "$(dirname "${_SELF}")" && pwd)"
unset _SELF

source "${_SCRIPT_DIR}/error-guard.sh" 2>/dev/null || true

cd "$HOME" 2>/dev/null || cd /tmp || true

# Resolve ONEX_STATE_DIR
source "${_SCRIPT_DIR}/onex-paths.sh" 2>/dev/null || true

if [[ -z "${ONEX_STATE_DIR:-}" ]]; then
    # Drain stdin before fail-open so upstream writer is not blocked
    cat > /dev/null
    echo "{}"
    exit 0
fi

EVENT_JSON=$(cat)

TOOL_NAME=$(echo "$EVENT_JSON" | jq -r '.tool_name // .toolName // "unknown"' 2>/dev/null || echo "unknown")
REASON=$(echo "$EVENT_JSON" | jq -r '.reason // ""' 2>/dev/null || echo "")
AGENT_NAME=$(echo "$EVENT_JSON" | jq -r '.agent_name // .agentName // ""' 2>/dev/null || echo "")
SESSION_ID=$(echo "$EVENT_JSON" | jq -r '.session_id // .sessionId // "unknown"' 2>/dev/null || echo "unknown")

DATE_PREFIX=$(date -u +%Y-%m-%d)
TS_NS=$(date -u +%s%N 2>/dev/null || date -u +%s)
# Sanitize tool name for filename
SAFE_TOOL=$(printf '%s' "$TOOL_NAME" | tr -cd 'a-zA-Z0-9_-' | tr '[:upper:]' '[:lower:]')
[[ -z "$SAFE_TOOL" ]] && SAFE_TOOL="unknown"

FRICTION_DIR="${ONEX_STATE_DIR}/friction"
mkdir -p "$FRICTION_DIR" 2>/dev/null || true

FRICTION_FILE="${FRICTION_DIR}/${DATE_PREFIX}-permission-denied-${SAFE_TOOL}-${TS_NS}.yaml"

# Write friction YAML (P2 — tool denials are significant but not P1)
# Fail-open: full disk or unwritable dir must not block the hook
cat > "$FRICTION_FILE" <<YAML || true
id: permission-denied-${SAFE_TOOL}-${SESSION_ID:0:8}
date: ${DATE_PREFIX}
severity: P2
category: permission
title: "Tool '${TOOL_NAME}' denied by auto-mode classifier"
summary: >
  Auto-mode denied tool '${TOOL_NAME}' during session ${SESSION_ID}.
  ${REASON:+Reason: ${REASON}}
impact: >
  Agent could not complete its action. If repeated, indicates policy gap or
  mis-scoped agent allowedTools list.
root_cause: >
  ${REASON:-Auto-mode classifier blocked the tool call (no reason provided).}
agent_name: "${AGENT_NAME}"
session_id: "${SESSION_ID}"
linear_ticket: OMN-8873
YAML

# Non-blocking — DO NOT return {retry: true}; we want the denial surfaced
echo "{}"
exit 0
