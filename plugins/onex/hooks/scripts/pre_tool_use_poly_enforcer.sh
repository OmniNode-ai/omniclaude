#!/bin/bash
# PreToolUse Polymorphic Agent Enforcer Hook
# Intercepts Task and Agent tool calls and blocks any that don't use
# an onex:-prefixed subagent_type. This ensures all automated workflows
# go through the polymorphic agent layer for ONEX capabilities,
# intelligence integration, and observability.
#
# After prefix validation passes, the script invokes the Python audit
# dispatch validator (OMN-5236) to check contract binding for agents
# that declare a context_integrity subcontract.

set -euo pipefail
_OMNICLAUDE_HOOK_NAME="$(basename "${BASH_SOURCE[0]}")"
source "$(dirname "${BASH_SOURCE[0]}")/error-guard.sh" 2>/dev/null || true

# --- Lite mode guard [OMN-5398] ---
_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
_MODE_SH="${_SCRIPT_DIR}/../../lib/mode.sh"
if [[ -f "$_MODE_SH" ]]; then source "$_MODE_SH"; [[ "$(omniclaude_mode)" == "lite" ]] && exit 0; fi
unset _SCRIPT_DIR _MODE_SH

# Ensure stable CWD before any processing.
cd "$HOME" 2>/dev/null || cd /tmp || true

# Portable Plugin Configuration
_SELF="$(realpath "${BASH_SOURCE[0]}" 2>/dev/null \
    || python3 -c "import os,sys; print(os.path.realpath(sys.argv[1]))" "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(cd "$(dirname "${_SELF}")" && pwd)"
PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "${SCRIPT_DIR}/../.." && pwd)}"
unset _SELF SCRIPT_DIR
HOOKS_DIR="${PLUGIN_ROOT}/hooks"
source "$(dirname "${BASH_SOURCE[0]}")/onex-paths.sh" || { echo "ONEX_STATE_DIR not set" >&2; exit 1; }
LOG_FILE="${ONEX_HOOK_LOG}"

# Ensure log directory exists
mkdir -p "$(dirname "$LOG_FILE")"

# Read stdin
TOOL_INFO=$(cat)
if ! TOOL_NAME=$(echo "$TOOL_INFO" | jq -er '.tool_name // empty' 2>/dev/null); then
    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] [$_OMNICLAUDE_HOOK_NAME] ERROR: invalid hook JSON; failing open" >> "$LOG_FILE"
    echo "$TOOL_INFO"
    exit 0
fi

# Only intercept Task and Agent tool invocations
if [[ ! "$TOOL_NAME" =~ ^(Task|Agent)$ ]]; then
    echo "$TOOL_INFO"
    exit 0
fi

echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] [$_OMNICLAUDE_HOOK_NAME] Checking $TOOL_NAME for onex: subagent_type" >> "$LOG_FILE"

# Extract subagent_type from tool_input
SUBAGENT_TYPE=$(echo "$TOOL_INFO" | jq -r '.tool_input.subagent_type // ""' 2>/dev/null) || SUBAGENT_TYPE=""

# Block: subagent_type is missing or does not have onex: prefix
if [[ ! "$SUBAGENT_TYPE" == onex:* ]]; then
    if [[ -z "$SUBAGENT_TYPE" ]]; then
        BLOCK_DETAIL="subagent_type is missing"
    else
        BLOCK_DETAIL="subagent_type=\"$SUBAGENT_TYPE\" does not have the required onex: prefix"
    fi

    BLOCK_REASON="$TOOL_NAME call blocked: $BLOCK_DETAIL. All Task/Agent calls must use subagent_type=\"onex:polymorphic-agent\" (or another onex:-prefixed type) to ensure ONEX capabilities, intelligence integration, and observability are active. Fix: set subagent_type=\"onex:polymorphic-agent\" in your $TOOL_NAME call."

    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] [$_OMNICLAUDE_HOOK_NAME] BLOCKED: $TOOL_NAME ($BLOCK_DETAIL)" >> "$LOG_FILE"

    # Output block decision JSON and exit 2 to deny the tool call.
    # Clear the error-guard EXIT trap first -- exit 2 is an intentional block,
    # not a crash. The error guard would swallow it and exit 0 instead.
    jq -n --arg reason "$BLOCK_REASON" '{"decision": "block", "reason": $reason}'
    trap - EXIT
    exit 2
fi

# Prefix validation passed. Run the Python audit dispatch validator to check
# contract binding for agents with a context_integrity subcontract (OMN-5236).
# The validator is kept thin: it only runs after prefix validation, never blocks
# on import errors or missing config, and exits 0 (allow) or 2 (block).
#
# Pass the resolved PLUGIN_ROOT as CLAUDE_PLUGIN_ROOT so the Python module
# can locate agent YAML configs and wrappers without guessing paths.
_AUDIT_VALIDATOR_EXIT=0
_AUDIT_VALIDATOR_OUTPUT=""
_AUDIT_VALIDATOR_OUTPUT=$(CLAUDE_PLUGIN_ROOT="$PLUGIN_ROOT" python3 -m omniclaude.hooks.handlers.audit_dispatch_validator \
    --subagent-type "$SUBAGENT_TYPE" \
    2>>"$LOG_FILE") || _AUDIT_VALIDATOR_EXIT=$?

if [[ "$_AUDIT_VALIDATOR_EXIT" -eq 2 ]]; then
    # Python validator issued a hard block (contract binding misconfiguration).
    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] [$_OMNICLAUDE_HOOK_NAME] BLOCKED by audit_dispatch_validator: $TOOL_NAME subagent_type=$SUBAGENT_TYPE" >> "$LOG_FILE"
    # Pass the block JSON output from the validator directly to the caller.
    if [[ -n "$_AUDIT_VALIDATOR_OUTPUT" ]]; then
        echo "$_AUDIT_VALIDATOR_OUTPUT"
    else
        jq -n --arg reason "Contract binding validation failed for $SUBAGENT_TYPE. Check $LOG_FILE for details." \
            '{"decision": "block", "reason": $reason}'
    fi
    trap - EXIT
    exit 2
fi

# Both prefix validation and contract binding validation passed.
echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] [$_OMNICLAUDE_HOOK_NAME] ALLOWED: $TOOL_NAME with subagent_type=$SUBAGENT_TYPE" >> "$LOG_FILE"
echo "$TOOL_INFO"
exit 0
