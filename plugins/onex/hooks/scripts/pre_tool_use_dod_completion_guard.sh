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

case "$POLICY_MODE" in
    hard)
        # Block the tool call
        echo "{\"decision\": \"block\", \"reason\": \"$REASON\"}" >&2
        exit 2
        ;;
    soft)
        # Allow but inject warning
        echo "{\"decision\": \"allow\", \"reason\": \"WARNING: $REASON\"}" >&2
        exit 0
        ;;
    *)
        # Advisory: log and allow
        echo "[dod-guard] advisory: $REASON" >&2
        exit 0
        ;;
esac
