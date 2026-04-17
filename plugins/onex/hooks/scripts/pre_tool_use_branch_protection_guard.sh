#!/bin/bash
# PreToolUse Branch Protection Rollout-Verification Guard
#
# Blocks any `gh api ... --method PUT|PATCH .../branches/<branch>/protection`
# whose inline `required_status_checks.contexts[]` entries are not emitted by
# any workflow on the target repo. The complementary scheduled audit
# (OMN-9034) catches post-mutation drift every 4h. This hook prevents the
# mutation from shipping in the first place — retrospective §7 P0.
#
# Ref: OMN-9038.

set -euo pipefail
_OMNICLAUDE_HOOK_NAME="$(basename "${BASH_SOURCE[0]}")"
source "$(dirname "${BASH_SOURCE[0]}")/error-guard.sh" 2>/dev/null || true

# Stable CWD before any Python invocation (same rationale as other bash guards).
cd "$HOME" 2>/dev/null || cd /tmp || true

_SELF="$(realpath "${BASH_SOURCE[0]}" 2>/dev/null \
    || python3 -c "import os,sys; print(os.path.realpath(sys.argv[1]))" "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(cd "$(dirname "${_SELF}")" && pwd)"
PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "${SCRIPT_DIR}/../.." && pwd)}"
unset _SELF SCRIPT_DIR
HOOKS_DIR="${PLUGIN_ROOT}/hooks"
HOOKS_LIB="${HOOKS_DIR}/lib"
source "$(dirname "${BASH_SOURCE[0]}")/onex-paths.sh" || { echo "ONEX_STATE_DIR not set" >&2; exit 1; }
LOG_FILE="${ONEX_HOOK_LOG}"

mkdir -p "$(dirname "$LOG_FILE")"

# Shared helpers (PYTHON_CMD, _hook_status).
source "${HOOKS_DIR}/scripts/common.sh"

TOOL_INFO=$(cat)

if ! TOOL_NAME=$(echo "$TOOL_INFO" | jq -er '.tool_name // empty' 2>>"$LOG_FILE"); then
    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] ERROR: invalid hook JSON; failing open" >> "$LOG_FILE"
    echo "$TOOL_INFO"
    exit 0
fi

if [[ "$TOOL_NAME" != "Bash" ]]; then
    _hook_status "PASS" "not Bash ($TOOL_NAME)" "0"
    echo "$TOOL_INFO"
    exit 0
fi

set +e
RESULT=$(echo "$TOOL_INFO" | \
    $PYTHON_CMD "${HOOKS_LIB}/branch_protection_verifier.py" 2>>"$LOG_FILE")
EXIT_CODE=$?
set -e

if [ $EXIT_CODE -eq 0 ]; then
    _hook_status "PASS" "bp guard allowed" "0"
    echo "$RESULT"
elif [ $EXIT_CODE -eq 2 ]; then
    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] BP rollout BLOCKED" >> "$LOG_FILE"
    _hook_status "BLOCKED" "bp rollout context mismatch" "0"
    printf '\a' >&2
    echo "$RESULT"
    exit 2
else
    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] ERROR: bp guard failed (exit=$EXIT_CODE), failing open" >> "$LOG_FILE"
    _hook_status "PASS" "bp guard error, failing open (exit=$EXIT_CODE)" "0"
    echo "$TOOL_INFO"
    exit 0
fi
