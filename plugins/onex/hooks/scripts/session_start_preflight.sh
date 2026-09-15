#!/bin/bash
# SPDX-FileCopyrightText: 2026 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# SessionStart preflight hook (OMN-18368)
#
# Runs the session preflight runner (plugins/onex/scripts/session_preflight.py)
# under the FIXED `--intent quiet` argument at every session start, and prints
# whatever it prints: nothing when every check passes, one line per blocker
# with its own fix command otherwise, or a single REFUSED line naming a
# configuration problem (most commonly: no overlay declared on this machine).
#
# The `--intent quiet` argument is fixed, not resolved from the session's own
# intent. The runner's own quiet mode already IS the volume control this hook
# needs -- silent when clean, one line per blocker otherwise -- so there is
# nothing left for a second silencing layer to add. A person who wants the
# fuller `normal` picture asks for it explicitly via
# `/onex:preflight --intent normal`; that path is unaffected by this hook.
#
# NEVER BLOCKS. The runner's own exit status (0 clean, 1 blocked, 2 refused)
# is discarded: this hook always exits 0. A configuration problem or a failed
# environment check is something the session should be told about, not
# something that stops it from starting -- the whole design principle this
# repo's SessionStart hooks share (see the file header of
# session_start_goal_surface.sh for the fuller statement of that contract).
#
# Lite mode: an external contributor using this plugin in an unrelated repo
# has no preflight overlay and never will -- the OmniNode-specific overlay is
# deliberately parked as private content (2026-09-14 public-plugin ruling;
# knowledge-base-internal marketplace-internal/skills/session_preflight/), so
# every lite-mode run would print nothing but a REFUSED line, forever. That is
# exactly the class of noise the mode gate exists to remove.
#
# Interpreter resolution follows the same accepted pattern as
# session_start_hook_parity.sh: source common.sh for PYTHON_CMD with a `|| true`
# fallback to bare `python3` rather than adding this hook to common.sh's
# advisory-criticality allowlist. That is a deliberate precedent match, not an
# oversight -- see this repo's CLAUDE.md "Failure Modes" section for the
# critical-vs-advisory Python resolution split.

set -uo pipefail

# SessionStart delivers a JSON payload on stdin. Nothing here needs it, but an
# unread stdin can hand the caller an EPIPE, so drain it unconditionally.
cat >/dev/null 2>&1 || true

_PREFIX="[preflight]"
say() { printf '%s %s\n' "$_PREFIX" "$*"; }

_SELF="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd)" || _SELF="."
PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "${_SELF}/../.." 2>/dev/null && pwd)}"

# Lite mode: no OmniNode-specific preflight content in an unrelated repo.
_MODE_SH="${PLUGIN_ROOT}/lib/mode.sh"
if [[ -f "$_MODE_SH" ]]; then
    # shellcheck disable=SC1090
    source "$_MODE_SH" 2>/dev/null || true
    if declare -F omniclaude_mode >/dev/null 2>&1 && [[ "$(omniclaude_mode)" == "lite" ]]; then
        exit 0
    fi
fi

_RUNNER="${PLUGIN_ROOT}/scripts/session_preflight.py"
if [[ ! -f "$_RUNNER" ]]; then
    # Runner missing (incomplete deploy): nothing to run, never block.
    exit 0
fi

# shellcheck source=/dev/null
source "${PLUGIN_ROOT}/hooks/scripts/common.sh" 2>/dev/null || true
_PY="${PYTHON_CMD:-python3}"

_TIMEOUT_BIN=""
if command -v timeout >/dev/null 2>&1; then
    _TIMEOUT_BIN="timeout"
elif command -v gtimeout >/dev/null 2>&1; then
    _TIMEOUT_BIN="gtimeout"
fi

if [[ -n "$_TIMEOUT_BIN" ]]; then
    _OUTPUT="$("$_TIMEOUT_BIN" 20s "$_PY" "$_RUNNER" --intent quiet 2>&1)"
else
    _OUTPUT="$("$_PY" "$_RUNNER" --intent quiet 2>&1)"
fi

if [[ -n "$_OUTPUT" ]]; then
    while IFS= read -r _line || [[ -n "$_line" ]]; do
        say "$_line"
    done <<<"$_OUTPUT"
fi

exit 0
