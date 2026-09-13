#!/bin/bash
# SPDX-FileCopyrightText: 2026 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Emits content-free output metadata and never writes hookSpecificOutput.
set -uo pipefail
_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
_MODE_SH="${_SCRIPT_DIR}/../../lib/mode.sh"
if [[ -f "${_MODE_SH}" ]]; then source "${_MODE_SH}"; [[ "$(omniclaude_mode)" == "lite" ]] && exit 0; fi
PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "${_SCRIPT_DIR}/../.." && pwd)}"
HOOKS_DIR="${PLUGIN_ROOT}/hooks"
HOOKS_LIB="${HOOKS_DIR}/lib"
LOG_FILE="${ONEX_STATE_DIR:-/tmp}/hooks/logs/post-tool-use-output-capture-metadata.log"
mkdir -p "$(dirname "${LOG_FILE}")" 2>/dev/null || true
source "${HOOKS_DIR}/scripts/common.sh" 2>/dev/null || { cat >/dev/null; exit 0; }
onex_hook_gate POST_TOOL_OUTPUT_SUPPRESSOR || { cat >/dev/null; exit 0; }
INPUT="$(cat)"
printf '%s' "${INPUT}" | "${PYTHON_CMD}" "${HOOKS_LIB}/tool_output_capture_metadata.py" \
    >/dev/null 2>>"${LOG_FILE}" &
exit 0
