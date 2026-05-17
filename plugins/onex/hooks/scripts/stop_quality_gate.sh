#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# Stop hook — changed-file lint/type/test gate.

set -euo pipefail
_OMNICLAUDE_HOOK_NAME="$(basename "${BASH_SOURCE[0]}")"
_OMNICLAUDE_CALLER_CWD="${CLAUDE_PROJECT_DIR:-$PWD}"
source "$(dirname "${BASH_SOURCE[0]}")/error-guard.sh" 2>/dev/null || true

# Lite mode guard [OMN-5398]
_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
_MODE_SH="${_SCRIPT_DIR}/../../lib/mode.sh"
if [[ -f "$_MODE_SH" ]]; then
    source "$_MODE_SH"
    if [[ "$(omniclaude_mode)" == "lite" ]]; then
        cat >/dev/null
        exit 0
    fi
fi

# Stabilize CWD before Python startup.
cd "$HOME" 2>/dev/null || cd /tmp || true

_SELF="$(realpath "${BASH_SOURCE[0]}" 2>/dev/null \
    || python3 -c "import os,sys; print(os.path.realpath(sys.argv[1]))" "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(cd "$(dirname "${_SELF}")" && pwd)"
PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "${SCRIPT_DIR}/../.." && pwd)}"
unset _SELF _SCRIPT_DIR _MODE_SH
HOOKS_DIR="${PLUGIN_ROOT}/hooks"
HOOKS_LIB="${HOOKS_DIR}/lib"

PROJECT_ROOT="$_OMNICLAUDE_CALLER_CWD"

source "${HOOKS_DIR}/scripts/common.sh"
source "${HOOKS_DIR}/scripts/onex-paths.sh"

LOG_FILE="${ONEX_STATE_DIR}/hooks/logs/stop-quality-gate.log"
mkdir -p "$(dirname "$LOG_FILE")"

STOP_INFO="$(cat)"

if declare -F hook_bits_bit_for_name >/dev/null 2>&1; then
    _STOP_GATE_BIT="$(hook_bits_bit_for_name STOP_QUALITY_GATE 2>/dev/null || true)"
else
    _STOP_GATE_BIT=""
fi
if [[ -n "$_STOP_GATE_BIT" ]]; then
    if ! onex_hook_gate STOP_QUALITY_GATE; then
        echo "[$(date -u +%FT%TZ)] STOP_QUALITY_GATE skipped: gate disabled" >> "$LOG_FILE"
        printf '%s' "$STOP_INFO"
        exit 0
    fi
fi
unset _STOP_GATE_BIT

set +e
RESULT="$("$PYTHON_CMD" "${HOOKS_DIR}/scripts/stop_quality_gate.py" \
    --project-root "$PROJECT_ROOT" 2>>"$LOG_FILE")"
EXIT_CODE=$?
set -e

printf '[%s] stop_quality_gate exit=%s result=%s\n' \
    "$(date -u +%FT%TZ)" "$EXIT_CODE" "$RESULT" >> "$LOG_FILE"

if [[ "$EXIT_CODE" -eq 2 ]]; then
    printf '%s\n' "$RESULT"
    trap - EXIT 2>/dev/null || true
    exit 2
fi

echo "$STOP_INFO"
exit 0
