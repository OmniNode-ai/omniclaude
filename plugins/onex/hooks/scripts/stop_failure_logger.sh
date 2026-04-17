#!/bin/bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# StopFailure Hook — write P1 friction YAML when a turn ends due to API error [OMN-8873]
#
# Input (stdin):
# {
#   "session_id": "abc123",
#   "agent_name": "worker-1",
#   "reason": "API error: 529",
#   "turn_count": 12
# }
#
# Output (stdout): {}

set -euo pipefail
_OMNICLAUDE_HOOK_NAME="$(basename "${BASH_SOURCE[0]}")"

# Resolve absolute script dir BEFORE any cd (relative dirname breaks after cd)
_resolve_self() {
    local src="$1"
    realpath "$src" 2>/dev/null && return 0
    if command -v python3 >/dev/null 2>&1; then
        python3 -c "import os,sys; print(os.path.realpath(sys.argv[1]))" "$src" && return 0
    fi
    if command -v python >/dev/null 2>&1; then
        python -c "import os,sys; print(os.path.realpath(sys.argv[1]))" "$src" && return 0
    fi
    return 1
}
_SELF="$(_resolve_self "${BASH_SOURCE[0]}")"
_SCRIPT_DIR="$(cd "$(dirname "${_SELF}")" && pwd)"
unset _SELF
unset -f _resolve_self

source "${_SCRIPT_DIR}/error-guard.sh" 2>/dev/null || true

cd "$HOME" 2>/dev/null || cd /tmp || true

# Preserve whether the caller actually supplied ONEX_STATE_DIR.
_INPUT_ONEX_STATE_DIR="${ONEX_STATE_DIR:-}"

# Resolve ONEX_STATE_DIR
source "${_SCRIPT_DIR}/onex-paths.sh" 2>/dev/null || true

if [[ -z "${_INPUT_ONEX_STATE_DIR}" ]]; then
    # Drain stdin before fail-open so upstream writer is not blocked
    cat > /dev/null
    echo "{}"
    exit 0
fi

EVENT_JSON=$(cat)

REASON=$(echo "$EVENT_JSON" | jq -r '.reason // .error // ""' 2>/dev/null || echo "")
AGENT_NAME=$(echo "$EVENT_JSON" | jq -r '.agent_name // .agentName // "unknown"' 2>/dev/null || echo "unknown")
SESSION_ID=$(echo "$EVENT_JSON" | jq -r '.session_id // .sessionId // "unknown"' 2>/dev/null || echo "unknown")
TURN_COUNT=$(echo "$EVENT_JSON" | jq -r '(.turn_count // .turnCount) | numbers // empty' 2>/dev/null || echo "")

# Sanitize string fields: strip newlines and escape double-quotes to prevent YAML injection
_sanitize() { printf '%s' "$1" | tr -d '\n\r' | sed 's/"/\\"/g'; }
REASON=$(_sanitize "$REASON")
AGENT_NAME=$(_sanitize "$AGENT_NAME")
SESSION_ID=$(_sanitize "$SESSION_ID")

DATE_PREFIX=$(date -u +%Y-%m-%d)
TS_NS=$(date -u +%s%N 2>/dev/null || date -u +%s)
# Sanitize agent name for filename
SAFE_AGENT=$(printf '%s' "$AGENT_NAME" | tr -cd 'a-zA-Z0-9_-' | tr '[:upper:]' '[:lower:]')
[[ -z "$SAFE_AGENT" ]] && SAFE_AGENT="unknown"

FRICTION_DIR="${ONEX_STATE_DIR}/friction"
mkdir -p "$FRICTION_DIR" 2>/dev/null || true

# Include nanosecond timestamp so concurrent events don't overwrite each other
FRICTION_FILE="${FRICTION_DIR}/${DATE_PREFIX}-stop-failure-${SAFE_AGENT}-${TS_NS}.yaml"

# Write friction YAML (P1 — API errors cause lost work and are more serious than denials)
# Fail-open: full disk or unwritable dir must not block the hook
cat > "$FRICTION_FILE" <<YAML || true
id: stop-failure-${SAFE_AGENT}-${SESSION_ID:0:8}
date: ${DATE_PREFIX}
severity: P1
category: api_error
title: "Turn ended due to API error (agent: ${AGENT_NAME})"
summary: >
  Agent '${AGENT_NAME}' had its turn terminated by an API error during session ${SESSION_ID}.
  ${REASON:+Reason: ${REASON}}
  ${TURN_COUNT:+Turn count at failure: ${TURN_COUNT}}
impact: >
  In-progress work was lost. If pattern repeats, indicates API instability or
  session context overflow requiring investigation.
root_cause: >
  ${REASON:-API error caused turn termination (no reason provided).}
agent_name: "${AGENT_NAME}"
session_id: "${SESSION_ID}"
turn_count: ${TURN_COUNT}
linear_ticket: OMN-8873
YAML

echo "{}"
exit 0
