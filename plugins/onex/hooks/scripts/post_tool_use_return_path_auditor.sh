#!/bin/bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# PostToolUse Return Path Auditor (OMN-5238)
# Validates return payloads from Task/Agent tool completions against
# context integrity constraints (return_schema.max_tokens / allowed_fields).
#
# Enforcement levels (set via OMNICLAUDE_RETURN_AUDIT_ENFORCEMENT env var):
#   PERMISSIVE - log only, never block
#   WARN       - emit audit event, never block (default)
#   STRICT     - block + emit events on violation
#   PARANOID   - block + emit events + mark task INVALID in correlation manager
#
# Always exits 0 so Claude Code is never blocked by audit infrastructure
# failures.  A non-advisory block (STRICT/PARANOID) is signalled via JSON
# output on stdout which the caller interprets.

set -euo pipefail
_OMNICLAUDE_HOOK_NAME="$(basename "${BASH_SOURCE[0]}")"
source "$(dirname "${BASH_SOURCE[0]}")/error-guard.sh" 2>/dev/null || true

# Ensure stable CWD before any Python invocation.
cd "$HOME" 2>/dev/null || cd /tmp || true

# Portable plugin root resolution
_SELF="$(realpath "${BASH_SOURCE[0]}" 2>/dev/null \
    || python3 -c "import os,sys; print(os.path.realpath(sys.argv[1]))" "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(cd "$(dirname "${_SELF}")" && pwd)"
PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "${SCRIPT_DIR}/../.." && pwd)}"
unset _SELF SCRIPT_DIR
HOOKS_DIR="${PLUGIN_ROOT}/hooks"
LOG_FILE="${HOOKS_DIR}/logs/return-path-audit.log"

mkdir -p "$(dirname "$LOG_FILE")"

# Guard: jq is required for JSON processing
if ! command -v jq >/dev/null 2>&1; then
    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] SKIP: jq not found, return-path-auditor cannot process JSON" >> "$LOG_FILE" 2>/dev/null || true
    cat  # drain stdin
    exit 0
fi

# OMN-3725: Mark as advisory -- exit 0 gracefully if Python is missing
export OMNICLAUDE_HOOK_CRITICALITY="advisory"

# Source shared functions (provides PYTHON_CMD)
source "${HOOKS_DIR}/scripts/common.sh"

# Read hook event from stdin
HOOK_EVENT=$(cat)

if ! printf '%s\n' "$HOOK_EVENT" | jq -e . >/dev/null 2>>"$LOG_FILE"; then
    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] SKIP: malformed JSON on stdin" >> "$LOG_FILE" 2>/dev/null || true
    printf '%s\n' "$HOOK_EVENT"
    exit 0
fi

TOOL_NAME=$(printf '%s\n' "$HOOK_EVENT" | jq -r '.tool_name // "unknown"' 2>/dev/null) || TOOL_NAME="unknown"

# Only audit Task/Agent completions
if [[ "$TOOL_NAME" != "Task" && "$TOOL_NAME" != "Agent" ]]; then
    printf '%s\n' "$HOOK_EVENT"
    exit 0
fi

echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] return-path-auditor: auditing $TOOL_NAME completion" >> "$LOG_FILE"

# Detect project root for Python path
PROJECT_ROOT="${PLUGIN_ROOT}/../.."
if [[ -n "${CLAUDE_PROJECT_DIR:-}" ]]; then
    PROJECT_ROOT="${CLAUDE_PROJECT_DIR}"
fi
export PYTHONPATH="${PROJECT_ROOT}/src:${PLUGIN_ROOT}/lib:${PYTHONPATH:-}"

# Invoke Python auditor
AUDIT_RESULT=""
set +e
AUDIT_RESULT=$(printf '%s\n' "$HOOK_EVENT" \
    | "$PYTHON_CMD" -m omniclaude.hooks.handlers.return_path_auditor \
        2>>"$LOG_FILE")
EXIT_CODE=$?
set -e

if [[ $EXIT_CODE -ne 0 || -z "$AUDIT_RESULT" ]]; then
    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] return-path-auditor: Python handler failed (exit=$EXIT_CODE), passing through" >> "$LOG_FILE"
    printf '%s\n' "$HOOK_EVENT"
    exit 0
fi

# Parse audit result
BLOCKED=$(printf '%s\n' "$AUDIT_RESULT" | jq -r '.blocked // false' 2>/dev/null) || BLOCKED="false"
RETURN_TOKENS=$(printf '%s\n' "$AUDIT_RESULT" | jq -r '.return_tokens // 0' 2>/dev/null) || RETURN_TOKENS="0"
MAX_TOKENS=$(printf '%s\n' "$AUDIT_RESULT" | jq -r '.max_tokens // 0' 2>/dev/null) || MAX_TOKENS="0"
ENFORCEMENT=$(printf '%s\n' "$AUDIT_RESULT" | jq -r '.enforcement_action // "warn"' 2>/dev/null) || ENFORCEMENT="warn"

echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] return-path-auditor: tokens=$RETURN_TOKENS/$MAX_TOKENS blocked=$BLOCKED action=$ENFORCEMENT" >> "$LOG_FILE"

if [[ "$BLOCKED" == "true" ]]; then
    # STRICT/PARANOID: report block via stderr (advisory signal to Claude Code)
    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] [AUDIT BLOCK] Return payload exceeded constraints (tokens=$RETURN_TOKENS > max=$MAX_TOKENS, action=$ENFORCEMENT)" >> "$LOG_FILE"
    # Write block advisory to stderr so it surfaces in Claude Code logs
    echo "[return-path-auditor] BLOCK: return payload exceeded context integrity constraints (tokens=${RETURN_TOKENS}, max=${MAX_TOKENS})" >&2
fi

# Always pass through the original hook event (hooks cannot modify payloads)
printf '%s\n' "$HOOK_EVENT"
exit 0
