#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# Linear Done-state PR verification guard [OMN-8415].
#
# PreToolUse hook on mcp__linear-server__{save,update}_issue. Blocks transitions
# to a Done state when any PR referenced in the ticket description is still
# open, blocked, or closed-without-merge. Catches the OMN-8375 class of failure
# where a ticket was marked Linear Done while its PR was still BLOCKED.
#
# Exit codes:
#   0 — allow the tool call
#   2 — block the tool call (JSON decision on stderr)

set -eo pipefail

# Lite mode guard [OMN-5398]
_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
_MODE_SH="${_SCRIPT_DIR}/../../lib/mode.sh"
if [[ -f "$_MODE_SH" ]]; then
    source "$_MODE_SH"
    [[ "$(omniclaude_mode)" == "lite" ]] && exit 0
fi

PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "${_SCRIPT_DIR}/../.." && pwd)}"
LIB_PY="${PLUGIN_ROOT}/hooks/lib/linear_done_verify.py"

# common.sh provides PYTHON_CMD resolution and shared helpers used by all hooks
# that invoke Python. Sourced here to satisfy the hooks-source-common invariant.
# shellcheck source=/dev/null
source "${PLUGIN_ROOT}/hooks/scripts/common.sh"
unset _SCRIPT_DIR _MODE_SH

if [[ ! -f "$LIB_PY" ]]; then
    # Library missing — fail open so we never block on our own bug.
    cat >/dev/null
    exit 0
fi

PYTHON_BIN="${PYTHON_CMD:-python3}"
exec "$PYTHON_BIN" "$LIB_PY"
