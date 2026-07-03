#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# Done-flip durable-evidence guard [OMN-13856] — L1 of the layered Done-flip
# gate. PreToolUse hook on mcp__linear-server__{save,update}_issue.
#
# Restored as the MINIMAL Option A carve-out into the otherwise-empty
# OMN-13244 measurement baseline: this is the SINGLE hook re-registered, guarding
# the single most dangerous mutation class (a fabricated Done). The guard MERGES
# the merged-PR (linear_done_verify) and receipt-PASS (dod_completion) semantics
# into one fail-closed decision and mechanizes the receipt check on the
# DETERMINISTIC LOCAL dod_verify path (no Kafka). See done_flip_guard.py.
#
# Exit codes:
#   0 — allow the tool call
#   2 — block the tool call (JSON decision on stderr)

set -eo pipefail

_OMNICLAUDE_CALLER_CWD="${CLAUDE_PROJECT_DIR:-$PWD}"
# shellcheck source=../lib/repo_guard.sh
. "$(dirname "${BASH_SOURCE[0]}")/../lib/repo_guard.sh" 2>/dev/null || true
if declare -F is_omninode_repo >/dev/null 2>&1; then
    CLAUDE_PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$_OMNICLAUDE_CALLER_CWD}" \
        is_omninode_repo || {
        _OMNICLAUDE_PASSTHROUGH=$(cat)
        echo "$_OMNICLAUDE_PASSTHROUGH"
        trap - EXIT 2>/dev/null || true
        exit 0
    }
fi

# Lite mode guard [OMN-5398]
_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
_MODE_SH="${_SCRIPT_DIR}/../../lib/mode.sh"
if [[ -f "$_MODE_SH" ]]; then
    source "$_MODE_SH"
    [[ "$(omniclaude_mode)" == "lite" ]] && exit 0
fi

PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "${_SCRIPT_DIR}/../.." && pwd)}"
LIB_PY="${PLUGIN_ROOT}/hooks/lib/done_flip_guard.py"

# common.sh provides PYTHON_CMD resolution and shared helpers used by all hooks
# that invoke Python. Sourced here to satisfy the hooks-source-common invariant.
# shellcheck source=/dev/null
source "${PLUGIN_ROOT}/hooks/scripts/common.sh"
onex_hook_gate DONE_FLIP_GUARD || exit 0
unset _SCRIPT_DIR _MODE_SH

if [[ ! -f "$LIB_PY" ]]; then
    # Library missing — fail open so we never block on our own bug.
    cat >/dev/null
    exit 0
fi

PYTHON_BIN="${PYTHON_CMD:-python3}"
# Only exit code 2 (blocking decision) should propagate. Any other non-zero
# exit is a Python runtime error in the hook itself — fail open to avoid
# blocking legitimate tool calls on a hook bug (never blocks on our own defect).
set +e
"$PYTHON_BIN" "$LIB_PY"
rc=$?
set -e
if [[ "$rc" -eq 2 ]]; then
    exit 2
fi
exit 0
