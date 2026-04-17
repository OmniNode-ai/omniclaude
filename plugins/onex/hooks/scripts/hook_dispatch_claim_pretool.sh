#!/bin/bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# PreToolUse Dispatch Claim Gate (OMN-8928)
#
# Extracts a deterministic blocker_id from Agent/Bash tool input using
# rule-based regex patterns. If a live claim exists by another agent:
# emits permissionDenied. If no claim: atomically acquires and passes.
# If no rule matches: passes through unchanged.
#
# Extraction rules (precedence):
#   1. Explicit blocker_id: <sha1> frontmatter
#   2. ssh ... 192.168.86.201  -> kind=ssh_201  # onex-allow-internal-ip
#   3. rpk topic produce ... rebuild  -> kind=deploy_rebuild
#   4. fix containers on 192.168.86.201  -> kind=fix_containers  # onex-allow-internal-ip
#   5. OMN-XXXX in prompt  -> kind=ticket_dispatch
#   6. gh pr merge --repo OmniNode-ai/... N  -> kind=pr_merge
#
# Hook registration: hooks.json PreToolUse, matcher "^(Agent|Bash)$"
# Ticket: OMN-8928

set -euo pipefail
_OMNICLAUDE_HOOK_NAME="$(basename "${BASH_SOURCE[0]}")"
source "$(dirname "${BASH_SOURCE[0]}")/error-guard.sh" 2>/dev/null || true

cd "$HOME" 2>/dev/null || cd /tmp || true

_SELF="$(realpath "${BASH_SOURCE[0]}" 2>/dev/null \
    || python3 -c "import os,sys; print(os.path.realpath(sys.argv[1]))" "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(cd "$(dirname "${_SELF}")" && pwd)"
PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "${SCRIPT_DIR}/../.." && pwd)}"
unset _SELF SCRIPT_DIR
HOOKS_DIR="${PLUGIN_ROOT}/hooks"
HOOKS_LIB="${HOOKS_DIR}/lib"
source "$(dirname "${BASH_SOURCE[0]}")/onex-paths.sh" || { echo "FATAL: ONEX_STATE_DIR not set" >&2; exit 1; }
LOG_FILE="${ONEX_HOOK_LOG}"

mkdir -p "$(dirname "$LOG_FILE")"

# Kill switch
if [[ "${DISPATCH_CLAIM_GATE_DISABLED:-0}" == "1" ]]; then
    cat
    exit 0
fi

TOOL_INFO=$(cat)

# Fast path: only care about Agent and Bash tools
TOOL_NAME=$(echo "$TOOL_INFO" | jq -er '.tool_name // empty' 2>/dev/null) || {
    echo "$TOOL_INFO"
    exit 0
}

if [[ "$TOOL_NAME" != "Agent" ]] && [[ "$TOOL_NAME" != "Bash" ]]; then
    echo "$TOOL_INFO"
    exit 0
fi

AGENT_ID="${CLAUDE_AGENT_ID:-session}"
CLAIMS_DIR="${ONEX_STATE_DIR}/dispatch_claims"
mkdir -p "$CLAIMS_DIR"

# Extract tool input text for pattern matching
if [[ "$TOOL_NAME" == "Agent" ]]; then
    TOOL_TEXT=$(echo "$TOOL_INFO" | jq -r '.tool_input.prompt // .tool_input.description // ""' 2>/dev/null) || TOOL_TEXT=""
else
    TOOL_TEXT=$(echo "$TOOL_INFO" | jq -r '.tool_input.command // ""' 2>/dev/null) || TOOL_TEXT=""
fi

if [[ -z "$TOOL_TEXT" ]]; then
    echo "$TOOL_INFO"
    exit 0
fi

# Locate Python
source "${HOOKS_DIR}/scripts/common.sh"

set +e
RESULT=$(echo "$TOOL_TEXT" | \
    $PYTHON_CMD -c "
import sys
import os
sys.path.insert(0, '${HOOKS_LIB}')
from dispatch_claim_gate import check_and_acquire
from pathlib import Path
import json

text = sys.stdin.read()
claims_dir = Path('${CLAIMS_DIR}')
claimant = '${AGENT_ID}'

result = check_and_acquire(text, claimant, claims_dir)
print(json.dumps(result))
" 2>>"$LOG_FILE")
EXIT_CODE=$?
set -e

if [[ $EXIT_CODE -ne 0 ]] || [[ -z "$RESULT" ]]; then
    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] [$_OMNICLAUDE_HOOK_NAME] claim gate failed (exit=$EXIT_CODE); failing open" >> "$LOG_FILE"
    echo "$TOOL_INFO"
    exit 0
fi

ACTION=$(echo "$RESULT" | jq -r '.action // "pass"' 2>/dev/null) || ACTION="pass"

case "$ACTION" in
    pass)
        echo "$TOOL_INFO"
        exit 0
        ;;
    acquired)
        BLOCKER_ID=$(echo "$RESULT" | jq -r '.blocker_id // ""' 2>/dev/null)
        echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] [$_OMNICLAUDE_HOOK_NAME] ACQUIRED blocker=${BLOCKER_ID} claimant=${AGENT_ID}" >> "$LOG_FILE"
        echo "$TOOL_INFO"
        exit 0
        ;;
    blocked)
        BLOCKER_ID=$(echo "$RESULT" | jq -r '.blocker_id // ""' 2>/dev/null)
        HELD_BY=$(echo "$RESULT" | jq -r '.held_by // "unknown"' 2>/dev/null)
        TTL_REM=$(echo "$RESULT" | jq -r '.ttl_remaining // 0' 2>/dev/null)
        KIND=$(echo "$RESULT" | jq -r '.kind // ""' 2>/dev/null)
        echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] [$_OMNICLAUDE_HOOK_NAME] BLOCKED blocker=${BLOCKER_ID} kind=${KIND} held_by=${HELD_BY} ttl_rem=${TTL_REM}s" >> "$LOG_FILE"
        MSG="Dispatch claim blocked: kind=${KIND} is already claimed by ${HELD_BY} (${TTL_REM}s remaining). blocker_id=${BLOCKER_ID} [OMN-8921]"
        printf '{"type":"permissionDenied","message":"%s"}' "$MSG"
        exit 2
        ;;
    *)
        echo "$TOOL_INFO"
        exit 0
        ;;
esac
