#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# DoD Completion Guard — PreToolUse hook
#
# Blocks Linear ticket status updates to "Done" unless a fresh, passing
# DoD evidence receipt exists. Reads stdin JSON for the tool invocation,
# checks if it's a Linear save_issue call setting status to Done/Complete.
#
# Policy modes (from DOD_ENFORCEMENT_MODE env var):
#   advisory (default) — log warning, allow
#   soft               — log warning, allow, add system message
#   hard               — block the tool call
#
# Exit codes:
#   0 — allow the tool call
#   2 — block the tool call (hard mode only)

set -eo pipefail

# --- Lite mode guard [OMN-5398] ---
_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
_MODE_SH="${_SCRIPT_DIR}/../../lib/mode.sh"
if [[ -f "$_MODE_SH" ]]; then source "$_MODE_SH"; [[ "$(omniclaude_mode)" == "lite" ]] && exit 0; fi
unset _SCRIPT_DIR _MODE_SH

# Resolve hook infrastructure paths
_SELF="$(realpath "${BASH_SOURCE[0]}" 2>/dev/null \
    || python3 -c "import os,sys; print(os.path.realpath(sys.argv[1]))" "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(cd "$(dirname "${_SELF}")" && pwd)"
PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "${SCRIPT_DIR}/../.." && pwd)}"
unset _SELF SCRIPT_DIR
HOOKS_DIR="${PLUGIN_ROOT}/hooks"
HOOKS_LIB="${HOOKS_DIR}/lib"
PYTHON_CMD="${PYTHON_CMD:-python3}"
LOG_FILE="${LOG_FILE:-$HOME/.claude/hooks.log}"

# Read stdin (tool invocation JSON)
INPUT=$(cat)

# Only intercept Linear save_issue / update_issue calls
TOOL_NAME=$(echo "$INPUT" | python3 -c "
import json, sys
try:
    data = json.load(sys.stdin)
    print(data.get('tool_name', ''))
except Exception:
    print('')
" 2>/dev/null || echo "")

# Early exit for non-Linear tools
case "$TOOL_NAME" in
    mcp__linear-server__save_issue|mcp__linear-server__update_issue)
        ;;
    *)
        exit 0
        ;;
esac

# Check if the status is being set to a completion state
STATUS_INFO=$(echo "$INPUT" | python3 -c "
import json, sys
try:
    data = json.load(sys.stdin)
    params = data.get('tool_input', {})
    state = str(params.get('state', params.get('status', ''))).lower()
    ticket_id = params.get('id', params.get('issueId', ''))
    # Check if this is a completion status
    completion_states = {'done', 'complete', 'completed', 'closed'}
    is_completion = state in completion_states
    print(json.dumps({'is_completion': is_completion, 'state': state, 'ticket_id': ticket_id}))
except Exception:
    print(json.dumps({'is_completion': False, 'state': '', 'ticket_id': ''}))
" 2>/dev/null || echo '{"is_completion": false}')

IS_COMPLETION=$(echo "$STATUS_INFO" | python3 -c "import json,sys; print(json.load(sys.stdin).get('is_completion', False))" 2>/dev/null || echo "False")

if [[ "$IS_COMPLETION" != "True" ]]; then
    exit 0
fi

TICKET_ID=$(echo "$STATUS_INFO" | python3 -c "import json,sys; print(json.load(sys.stdin).get('ticket_id', ''))" 2>/dev/null || echo "")

if [[ -z "$TICKET_ID" ]]; then
    exit 0
fi

# Check for evidence receipt
EVIDENCE_DIR=".evidence/$TICKET_ID"
RECEIPT_PATH="$EVIDENCE_DIR/dod_report.json"

POLICY_MODE="${DOD_ENFORCEMENT_MODE:-advisory}"

# Check if receipt exists and is fresh (< 30 minutes old)
RECEIPT_CHECK=$(python3 -c "
import json, sys, os
from datetime import datetime, timezone, timedelta

receipt_path = '$RECEIPT_PATH'
if not os.path.exists(receipt_path):
    print('missing')
    sys.exit(0)

try:
    with open(receipt_path) as f:
        receipt = json.load(f)

    # Check freshness (30 minute window)
    timestamp = receipt.get('timestamp', '')
    if timestamp:
        receipt_time = datetime.fromisoformat(timestamp)
        age = datetime.now(tz=timezone.utc) - receipt_time
        if age > timedelta(minutes=30):
            print('stale')
            sys.exit(0)

    # Check for failures
    result = receipt.get('result', {})
    if result.get('failed', 0) > 0:
        print('has_failures')
        sys.exit(0)

    print('valid')
except Exception as e:
    print(f'error:{e}')
" 2>/dev/null || echo "error")

case "$RECEIPT_CHECK" in
    valid)
        # Receipt exists, fresh, no failures — allow
        exit 0
        ;;
    missing)
        REASON="No DoD evidence receipt found at $RECEIPT_PATH. Run /dod-verify $TICKET_ID first."
        ;;
    stale)
        REASON="DoD evidence receipt is stale (>30 minutes old). Run /dod-verify $TICKET_ID to refresh."
        ;;
    has_failures)
        REASON="DoD evidence receipt has failed checks. Fix failures and run /dod-verify $TICKET_ID."
        ;;
    *)
        REASON="Could not read DoD evidence receipt: $RECEIPT_CHECK"
        ;;
esac

# --- Emit dod.guard.fired event (non-blocking, backgrounded) ---
# Compute receipt metadata for the event payload
RECEIPT_AGE_SECONDS="null"
RECEIPT_PASS="null"
if [[ -f "$RECEIPT_PATH" ]]; then
    RECEIPT_META=$(python3 -c "
import json, sys, os
from datetime import datetime, timezone
receipt_path = '$RECEIPT_PATH'
try:
    with open(receipt_path) as f:
        receipt = json.load(f)
    ts = receipt.get('timestamp', '')
    if ts:
        receipt_time = datetime.fromisoformat(ts)
        age = (datetime.now(tz=timezone.utc) - receipt_time).total_seconds()
    else:
        age = -1
    result = receipt.get('result', {})
    passed = result.get('failed', 0) == 0
    print(json.dumps({'age': age, 'pass': passed}))
except Exception:
    print(json.dumps({'age': -1, 'pass': False}))
" 2>/dev/null || echo '{"age": -1, "pass": false}')
    RECEIPT_AGE_SECONDS=$(echo "$RECEIPT_META" | python3 -c "import json,sys; print(json.load(sys.stdin).get('age', -1))" 2>/dev/null || echo "-1")
    RECEIPT_PASS=$(echo "$RECEIPT_META" | python3 -c "import json,sys; v=json.load(sys.stdin).get('pass', False); print('true' if v else 'false')" 2>/dev/null || echo "false")
fi

emit_guard_event() {
    local guard_outcome="$1"
    local session_id="${CLAUDE_SESSION_ID:-}"
    local timestamp
    timestamp=$(python3 -c "from datetime import datetime, timezone; print(datetime.now(tz=timezone.utc).isoformat())" 2>/dev/null || date -u +"%Y-%m-%dT%H:%M:%SZ")

    local payload
    payload=$(python3 -c "
import json
print(json.dumps({
    'ticket_id': '$TICKET_ID',
    'session_id': '$session_id',
    'guard_outcome': '$guard_outcome',
    'policy_mode': '$POLICY_MODE',
    'receipt_age_seconds': $RECEIPT_AGE_SECONDS if '$RECEIPT_AGE_SECONDS' != 'null' else None,
    'receipt_pass': $RECEIPT_PASS if '$RECEIPT_PASS' != 'null' else None,
    'timestamp': '$timestamp',
}))
" 2>/dev/null || echo '{}')

    if [[ "$payload" != "{}" ]]; then
        "$PYTHON_CMD" "${HOOKS_LIB}/emit_client_wrapper.py" emit \
            --event-type "dod.guard.fired" --payload "$payload" \
            >> "$LOG_FILE" 2>&1 || true
    fi
}

case "$POLICY_MODE" in
    hard)
        # Block the tool call
        emit_guard_event "blocked" &
        echo "{\"decision\": \"block\", \"reason\": \"$REASON\"}" >&2
        exit 2
        ;;
    soft)
        # Allow but inject warning
        emit_guard_event "warned" &
        echo "{\"decision\": \"allow\", \"reason\": \"WARNING: $REASON\"}" >&2
        exit 0
        ;;
    *)
        # Advisory: log and allow
        emit_guard_event "allowed" &
        echo "[dod-guard] advisory: $REASON" >&2
        exit 0
        ;;
esac
