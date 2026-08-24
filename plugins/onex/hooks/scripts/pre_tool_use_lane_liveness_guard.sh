#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# Lane-liveness guard [OMN-16478] — PreToolUse hook on SendMessage.
#
# Closes friction F-10 (P0, docs/tracking/2026-08-24-system-friction-report.md):
# a team lead declared `supersede-binding-fix` dead and authorized a takeover of
# OMN-16432 while that lane was alive and mid-push. The duplicate takeover was
# stopped only by the worker's own `ps aux` check. The same class fired in both
# directions on 2026-08-17 (occ-6118-close / occ-6118-close-2).
#
# Two rules, both enforced on the outbound message (see lane_liveness_guard.py):
#   A. `to` must be a lane name — a bare harness ref is refused.
#   B. Declaring another lane dead, or authorizing a takeover of its work, is
#      refused unless an independent filesystem probe returns DEAD. UNREACHABLE
#      blocks as hard as ALIVE: a lane you cannot reach may be mid-push.
#
# Narrow carve-out to the OMN-13244 measurement baseline, same class as the
# OMN-13856 Done-flip guard and the OMN-14330 worktree guard: it blocks one
# work-destroying mutation and injects no context.
#
# Exit codes:
#   0 — allow the tool call
#   2 — block the tool call (JSON decision on stderr)

set -eo pipefail

# Deliberately NO is_omninode_repo short-circuit, unlike the Done-flip guard.
# Lane coordination is not repo-scoped: a lane can be declared dead from any
# working directory, and the message that authorizes the takeover is the same
# message either way. Same reasoning the OMN-16277 secret-redaction guard used
# when it dropped the repo gate.
#
# Deliberately NO ONEX_HOOKS_MASK bit either. Per CLAUDE.md, no security-class
# guard participates in the mask — a stale saved mask literal in ~/.omnibase/.env
# must never silently disable a control that prevents work destruction, and a
# bit added today is OFF for every operator carrying an older saved literal.
# The only disable surface is lite mode (the global omniclaude off switch).

# Lite mode guard [OMN-5398]
_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
_MODE_SH="${_SCRIPT_DIR}/../../lib/mode.sh"
if [[ -f "$_MODE_SH" ]]; then
    source "$_MODE_SH"
    [[ "$(omniclaude_mode)" == "lite" ]] && exit 0
fi

PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "${_SCRIPT_DIR}/../.." && pwd)}"
LIB_PY="${PLUGIN_ROOT}/hooks/lib/lane_liveness_guard.py"

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
# Only exit code 2 (blocking decision) should propagate. Any other non-zero
# exit is a Python runtime error in the hook itself — fail open to avoid
# blocking legitimate sends on a hook bug (never blocks on our own defect).
set +e
"$PYTHON_BIN" "$LIB_PY"
rc=$?
set -e
if [[ "$rc" -eq 2 ]]; then
    exit 2
fi
exit 0
