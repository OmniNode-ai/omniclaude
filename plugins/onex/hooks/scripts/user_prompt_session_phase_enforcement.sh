#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# UserPromptSubmit hook — Session phase enforcement [OMN-11233].
#
# Reads .onex_state/session/phase_state.yaml and injects enforcement
# directives when phase budget is exhausted, halt is required, or a
# budget warning threshold has been crossed.
#
# No network calls. Graceful no-op if state file is missing.
#
# Exit codes:
#   0 — always (hooks must never block; only inject directives)

set -eo pipefail

# Consume stdin
PROMPT_INFO="$(cat)"

# Resolve plugin root → Python interpreter
_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
_FIND_PYTHON="${_SCRIPT_DIR}/../lib/find_python.sh"

if [[ -f "$_FIND_PYTHON" ]]; then
    # shellcheck source=/dev/null
    source "$_FIND_PYTHON"
    PYTHON="$(find_python 2>/dev/null)" || PYTHON=""
else
    PYTHON="${PLUGIN_PYTHON_BIN:-}"
fi

if [[ -z "$PYTHON" ]]; then
    # No Python found — pass through silently
    printf '%s\n' "$PROMPT_INFO"
    exit 0
fi

# Call Python hook to get directive (empty string = no-op)
DIRECTIVE="$("$PYTHON" -c "
import sys, os
# Add src to path so omniclaude package is importable
plugin_root = os.path.dirname(os.path.dirname(os.path.abspath('${_SCRIPT_DIR}')))
src_path = os.path.join(plugin_root, 'src')
if os.path.isdir(src_path):
    sys.path.insert(0, src_path)
from omniclaude.hooks.session_phase_enforcement import build_enforcement_directive
print(build_enforcement_directive(), end='')
" 2>/dev/null)" || DIRECTIVE=""

if [[ -z "$DIRECTIVE" ]]; then
    # No enforcement needed — pass through
    printf '%s\n' "$PROMPT_INFO"
    exit 0
fi

# Inject directive into additionalContext
if command -v jq >/dev/null 2>&1; then
    MODIFIED="$(printf '%s' "$PROMPT_INFO" | jq \
        --arg directive "$DIRECTIVE" \
        '.hookSpecificOutput = (.hookSpecificOutput // {}) |
         .hookSpecificOutput.hookEventName = "UserPromptSubmit" |
         .hookSpecificOutput.additionalContext = (
           ((.hookSpecificOutput.additionalContext // "") + "\n\n" + $directive)
           | ltrimstr("\n\n")
         )' 2>/dev/null)"
    if [[ -n "$MODIFIED" && "$MODIFIED" != "null" ]]; then
        printf '%s\n' "$MODIFIED"
    else
        printf '%s\n' "$PROMPT_INFO"
    fi
else
    # Fallback: emit minimal JSON with directive
    jq_safe="$(printf '%s' "$DIRECTIVE" | sed 's/"/\\"/g')"
    printf '{"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": "%s"}}\n' "$jq_safe"
fi

exit 0
