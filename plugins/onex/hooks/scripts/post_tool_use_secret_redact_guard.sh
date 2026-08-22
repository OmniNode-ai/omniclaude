#!/bin/bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# PostToolUse — secret-redaction guard [OMN-16277].
#
# Scans EVERY Bash tool_response (stdout + stderr, no size/command-type/
# exit-code gate) with the shared secret_redactor pattern set and replaces
# the Claude-visible tool result via hookSpecificOutput.updatedToolOutput
# (object form — probe OMN-13090, same protocol already proven by
# post_tool_use_output_suppressor.sh) whenever a secret-shaped pattern
# matches. Two-strike fix for the 2026-08-19 kubectl-jsonpath clientSecret
# leak and env|grep-sed-gap Postgres URL leak.
#
# Protocol (probe-verified, CLI 2.1.175):
#   - Passthrough emits NOTHING on stdout (plain stdout is debug-log-only).
#   - Redaction emits exactly ONE JSON object: the hookSpecificOutput
#     envelope (with "hookEventName": "PostToolUse") produced by
#     post_tool_use_secret_redact_guard.py.
#
# Fail-safe posture (deliberate divergence from this repo's usual fail-open
# hook philosophy — same divergence already taken by the SubagentStop
# secret-leak guard, OMN-15062): on a genuine crash of this script itself
# (missing interpreter, etc.) the ORIGINAL output would otherwise reach
# Claude unmodified. Because a masking-only PostToolUse hook has no "block"
# verdict to fall back on, we cannot force safety at the shell layer the
# way the SubagentStop guard does — the fail-safe logic instead lives
# inside the Python guard itself (any scan-time exception AFTER text was
# extracted routes to a withheld-placeholder replacement, never raw
# passthrough). A missing/broken interpreter here is caught by common.sh's
# hard-fail (see below) before this script can silently no-op.
#
# Refs: OMN-16277.

set -eo pipefail

# --- Lite mode guard [OMN-5398], mirrors post_tool_use_output_suppressor.sh ---
_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
_MODE_SH="${_SCRIPT_DIR}/../../lib/mode.sh"
if [[ -f "$_MODE_SH" ]]; then source "$_MODE_SH"; [[ "$(omniclaude_mode)" == "lite" ]] && exit 0; fi
unset _MODE_SH

_SELF="$(realpath "${BASH_SOURCE[0]}" 2>/dev/null \
    || python3 -c "import os,sys; print(os.path.realpath(sys.argv[1]))" "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(cd "$(dirname "${_SELF}")" && pwd)"
PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "${SCRIPT_DIR}/../.." && pwd)}"
unset _SELF _SCRIPT_DIR SCRIPT_DIR
HOOKS_DIR="${PLUGIN_ROOT}/hooks"
HOOKS_LIB="${HOOKS_DIR}/lib"

# common.sh resolves PYTHON_CMD and hard-fails (exit 1, actionable message)
# when no interpreter is available at all — this is the "critical hook"
# exception to the repo's usual fail-open posture (CLAUDE.md "Failure
# Modes"), and is what keeps a silently-broken interpreter from becoming a
# silent passthrough for this security control.
#
# Deliberately NOT gated by ONEX_HOOKS_MASK (unlike most hook wrappers) —
# same precedent as subagent_stop_secret_leak_guard.sh (OMN-15062) and
# pre_tool_use_done_flip_guard.sh (OMN-13856): a security carve-out must
# not be silently disabled by a stale saved mask literal (CLAUDE.md's own
# documented trap — "once a hex literal is saved ... hooks added later are
# OFF for you"). Only the lite-mode short-circuit above applies.
source "${HOOKS_DIR}/scripts/common.sh"

GUARD="${HOOKS_LIB}/post_tool_use_secret_redact_guard.py"
if [[ ! -f "$GUARD" ]]; then
    # Passthrough: emit nothing. No text was ever extracted (the guard
    # module itself is missing), so this is the "nothing to scan" branch,
    # not a scan-time failure.
    exit 0
fi

# Read stdin once.
TOOL_INFO=$(cat)

# Quick check: only process Bash tool calls (avoid Python startup for non-Bash).
TOOL_NAME=$(echo "$TOOL_INFO" | jq -r '.tool_name // ""' 2>/dev/null) || TOOL_NAME=""
if [[ "$TOOL_NAME" != "Bash" ]]; then
    exit 0
fi

RESULT=$(printf '%s' "$TOOL_INFO" | "$PYTHON_CMD" "$GUARD" 2>>"${LOG_FILE:-/dev/null}") || {
    exit 0
}

if [[ -n "$RESULT" ]]; then
    printf '%s\n' "$RESULT"
fi
exit 0
