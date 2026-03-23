#!/bin/bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# PreToolUse Convention Injector Hook
# Injects domain-specific convention context based on the file being edited.
# Non-blocking: exits 0 on any failure.

set -euo pipefail
_OMNICLAUDE_HOOK_NAME="$(basename "${BASH_SOURCE[0]}")"
source "$(dirname "${BASH_SOURCE[0]}")/scripts/error-guard.sh" 2>/dev/null || true

# --- Lite mode guard [OMN-5398] ---
_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
_MODE_SH="${_SCRIPT_DIR}/../lib/mode.sh"
if [[ -f "$_MODE_SH" ]]; then source "$_MODE_SH"; [[ "$(omniclaude_mode)" == "lite" ]] && exit 0; fi
unset _SCRIPT_DIR _MODE_SH

# Stable CWD
cd "$HOME" 2>/dev/null || cd /tmp || true

# Resolve paths
_SELF="$(realpath "${BASH_SOURCE[0]}" 2>/dev/null \
    || python3 -c "import os,sys; print(os.path.realpath(sys.argv[1]))" "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(cd "$(dirname "${_SELF}")" && pwd)"
PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "${SCRIPT_DIR}/.." && pwd)}"
unset _SELF SCRIPT_DIR
HOOKS_DIR="${PLUGIN_ROOT}/hooks"
HOOKS_LIB="${HOOKS_DIR}/lib"

# Detect project root
PROJECT_ROOT="${PLUGIN_ROOT}/../.."
if [[ -f "${PROJECT_ROOT}/.env" ]]; then
    PROJECT_ROOT="$(cd "${PROJECT_ROOT}" && pwd)"
elif [[ -n "${CLAUDE_PROJECT_DIR:-}" ]]; then
    PROJECT_ROOT="${CLAUDE_PROJECT_DIR}"
else
    PROJECT_ROOT="$(pwd)"
fi

export PYTHONPATH="${PROJECT_ROOT}:${PLUGIN_ROOT}/lib:${HOOKS_LIB}:${PYTHONPATH:-}"

# Source shared functions (provides PYTHON_CMD, KAFKA_ENABLED)
source "${HOOKS_DIR}/scripts/common.sh"

PYTHON_CMD="$(find_python)"
if [[ -z "$PYTHON_CMD" ]]; then
    exit 0  # Non-blocking: no Python available
fi

# Read stdin (tool input JSON)
INPUT="$(cat)"
if [[ -z "$INPUT" ]]; then
    exit 0
fi

# Extract file_path from tool_input
FILE_PATH="$(echo "$INPUT" | "$PYTHON_CMD" -c "
import sys, json
try:
    data = json.load(sys.stdin)
    fp = data.get('tool_input', {}).get('file_path', '')
    print(fp)
except Exception:
    pass
" 2>/dev/null)" || FILE_PATH=""

if [[ -z "$FILE_PATH" ]]; then
    exit 0
fi

# Call the Python router
ROUTER_OUTPUT="$("$PYTHON_CMD" "${HOOKS_LIB}/file_path_router.py" "$FILE_PATH" 2>/dev/null)" || ROUTER_OUTPUT=""

if [[ -z "$ROUTER_OUTPUT" ]]; then
    exit 0
fi

# Extract convention name for event emission
CONVENTION_NAME="$("$PYTHON_CMD" -c "
import sys, os
sys.path.insert(0, '${HOOKS_LIB}')
from file_path_router import match_file_path
name, _ = match_file_path(sys.argv[1])
print(name)
" "$FILE_PATH" 2>/dev/null)" || CONVENTION_NAME="unknown"

# Emit context.utilization event (backgrounded, non-blocking)
if [[ "${KAFKA_ENABLED:-false}" == "true" ]]; then
    SESSION_ID="${CLAUDE_SESSION_ID:-unknown}"
    "$PYTHON_CMD" -c "
import sys, os, json, datetime, uuid
sys.path.insert(0, '${HOOKS_LIB}')
from emit_client_wrapper import emit_event
emit_event(
    event_type='context.utilization',
    payload={
        'session_id': os.environ.get('CLAUDE_SESSION_ID', 'unknown'),
        'entity_id': 'urn:onex:session:' + os.environ.get('CLAUDE_SESSION_ID', 'unknown'),
        'correlation_id': str(uuid.uuid4()),
        'causation_id': str(uuid.uuid4()),
        'emitted_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'cohort': 'convention_injection',
        'injection_occurred': True,
        'agent_name': None,
        'user_visible_latency_ms': None,
        'cache_hit': False,
        'patterns_count': 1,
        'utilization_score': 0.0,
        'method': 'file_path_convention',
        'injected_count': 1,
        'reused_count': 0,
        'detection_duration_ms': 0,
        'convention_name': '${CONVENTION_NAME}',
        'file_path': sys.argv[1],
    },
    timeout_ms=50,
)
" "$FILE_PATH" &>/dev/null &
fi

# Output the convention content -- this gets injected into Claude's context
echo "$ROUTER_OUTPUT"
