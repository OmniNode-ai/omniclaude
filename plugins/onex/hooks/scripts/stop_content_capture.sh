#!/bin/bash
# SPDX-FileCopyrightText: 2026 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Stop content-capture hook (OMN-19551).
#
# Journals the assistant reply of the turn that just ended as a
# content.captured record, through the capture-redaction contract, for the
# full-content capture the operator ruled on 2026-09-25 (ledger RULING row
# 2026-09-25T11:23:30Z). The reply is read from the harness's own
# last_assistant_message when it sends one, else from the tail of
# transcript_path, polled briefly because Stop can fire before the transcript
# is flushed. All of that happens in the backgrounded Python process, so this
# hook returns at once.
#
# An observer: it never blocks the stop, never prints on stdout (a Stop hook
# that prints becomes a message the model answers), and exits 0 on every path.
# The boilerplate below is session_end_bus_mirror.sh's, unchanged apart from
# the log name and the gate name.

set -uo pipefail

_OMNICLAUDE_HOOK_NAME="$(basename "${BASH_SOURCE[0]}")"

_OMNICLAUDE_CALLER_CWD="${CLAUDE_PROJECT_DIR:-$PWD}"
# shellcheck source=../lib/repo_guard.sh
. "$(dirname "${BASH_SOURCE[0]}")/../lib/repo_guard.sh" 2>/dev/null || true
if declare -F is_omninode_repo >/dev/null 2>&1; then
    CLAUDE_PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$_OMNICLAUDE_CALLER_CWD}" \
        is_omninode_repo || {
        cat >/dev/null 2>/dev/null || true
        exit 0
    }
fi

# Lite mode: no bus mirroring in lite mode (generic dev tooling only).
_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
_MODE_SH="${_SCRIPT_DIR}/../../lib/mode.sh"
if [[ -f "$_MODE_SH" ]]; then
    # shellcheck disable=SC1090
    source "$_MODE_SH"
    if [[ "$(omniclaude_mode)" == "lite" ]]; then
        cat >/dev/null 2>/dev/null || true
        exit 0
    fi
fi
unset _MODE_SH

PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "${_SCRIPT_DIR}/../.." && pwd)}"
HOOKS_DIR="${PLUGIN_ROOT}/hooks"
HOOKS_LIB="${HOOKS_DIR}/lib"

# OMN-18704: which agent host is invoking this hook. Declared by the
# registration the host resolved -- the Codex hooks.json passes
# `--actor codex` -- and never sniffed, because a Codex hook process inherits
# its parent's environment and a Codex session started from a Claude Code
# session runs with CLAUDECODE=1 set. The allowlist lives in
# hooks/lib/hook_actor.py; this only lifts the raw value out of argv.
# shellcheck source=../lib/hook_actor.sh
source "${HOOKS_LIB}/hook_actor.sh" 2>/dev/null || true
if declare -F onex_hook_actor_arg >/dev/null 2>&1; then
    HOOK_ACTOR_ARG="$(onex_hook_actor_arg "$@")"
else
    HOOK_ACTOR_ARG="${ONEX_HOOK_ACTOR:-}"
fi

# shellcheck source=onex-paths.sh
source "$(dirname "${BASH_SOURCE[0]}")/onex-paths.sh" 2>/dev/null || true
LOG_FILE="${ONEX_STATE_DIR:-/tmp}/hooks/logs/hook-stop-content-capture.log"
# OMN-19519: this log is appended on every event it mirrors and had no
# rotation; the helper from onex-paths.sh bounds it (sampled, never fails).
if declare -F onex_maybe_rotate_log >/dev/null 2>&1; then
    onex_maybe_rotate_log "$LOG_FILE"
fi
mkdir -p "$(dirname "$LOG_FILE")" 2>/dev/null || true

# Detect project root (same convention as session-end.sh).
PROJECT_ROOT="${PLUGIN_ROOT}/../.."
if [[ -f "${PROJECT_ROOT}/.env" ]]; then
    PROJECT_ROOT="$(cd "${PROJECT_ROOT}" && pwd)"
elif [[ -n "${CLAUDE_PROJECT_DIR:-}" ]]; then
    PROJECT_ROOT="${CLAUDE_PROJECT_DIR}"
else
    PROJECT_ROOT="$(pwd)"
fi

# Load .env BEFORE common.sh so the KAFKA_BOOTSTRAP_SERVERS contract
# overlay (OMN-16167) is available to the backgrounded dispatch process.
# Never hardcode a broker endpoint here -- the emit node's own handler
# resolves the target from this env var.
if [[ -f "$PROJECT_ROOT/.env" ]]; then
    set -a
    source "$PROJECT_ROOT/.env" 2>/dev/null || true
    set +a
fi

# OMN-16162: advisory criticality -- a missing Python interpreter must
# degrade gracefully (exit 0), not hard-fail. See common.sh's advisory
# allowlist.
export OMNICLAUDE_HOOK_CRITICALITY="advisory"

# shellcheck source=common.sh
source "${HOOKS_DIR}/scripts/common.sh" 2>/dev/null || {
    cat >/dev/null 2>/dev/null || true
    exit 0
}

# OMN-17204: apply the declared hook-edge lane AFTER common.sh.
# common.sh sources ~/.omnibase/.env and $PROJECT_ROOT/.env under `set -a`, so
# before this ticket the publish lane was whatever those files happened to say
# last -- racing ~/.claude/settings.json, which says a different lane. The
# contract (hooks/contracts/hook_edge_lane.yaml) is now the authority and this
# line is where it wins. Order is enforced by
# scripts/validation/validate_hook_edge_lane.py, not left to convention.
# shellcheck source=hook_edge_lane.sh
source "$(dirname "${BASH_SOURCE[0]}")/hook_edge_lane.sh" 2>/dev/null || true
onex_hook_gate STOP_CONTENT_CAPTURE || {
    cat >/dev/null 2>/dev/null || true
    exit 0
}


INPUT="$(cat)"

if ! command -v jq >/dev/null 2>&1; then
    exit 0
fi
if ! echo "$INPUT" | jq -e . >/dev/null 2>&1; then
    exit 0
fi

SESSION_ID=$(echo "$INPUT" | jq -r '.session_id // .sessionId // ""' 2>/dev/null) || SESSION_ID=""
AGENT_ID=$(echo "$INPUT" | jq -r '.agent_id // .agentId // ""' 2>/dev/null) || AGENT_ID=""
TRANSCRIPT_PATH=$(echo "$INPUT" | jq -r '.transcript_path // .transcriptPath // ""' 2>/dev/null) || TRANSCRIPT_PATH=""
CWD=$(echo "$INPUT" | jq -r '.cwd // ""' 2>/dev/null) || CWD=""
[[ -z "$CWD" ]] && CWD="$(pwd)"
TURN_ID=$(echo "$INPUT" | jq -r '.turn_id // ""' 2>/dev/null) || TURN_ID=""

_CONTENT_CAPTURE_PY="${HOOKS_LIB}/hook_content_capture.py"
if [[ -n "${PYTHON_CMD:-}" && -f "$_CONTENT_CAPTURE_PY" ]]; then
    (
        printf '%s' "$INPUT" | "$PYTHON_CMD" "$_CONTENT_CAPTURE_PY" \
            --kind stop \
            --correlation-id "${SESSION_ID:-unknown}" \
            --agent-id "$AGENT_ID" \
            --transcript-path "$TRANSCRIPT_PATH" \
            --session-id "$SESSION_ID" \
            --cwd "$CWD" \
            --actor "$HOOK_ACTOR_ARG" \
            --turn-id "$TURN_ID" \
            >>"$LOG_FILE" 2>&1
    # The whole subshell's descriptors go to the log. With two commands in it,
    # bash keeps the subshell alive, and an inherited stdout or stderr pipe
    # would hold the hook's caller until both finished (OMN-19551).
    ) >>"$LOG_FILE" 2>&1 </dev/null &
    disown 2>/dev/null || true
fi

exit 0
