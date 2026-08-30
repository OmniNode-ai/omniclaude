#!/bin/bash
# SPDX-FileCopyrightText: 2026 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# SessionStart Bus-Mirror Hook (OMN-16162)
#
# Direct-dispatches node_event_emit_effect (omnimarket) with a
# session-started event, backgrounded so this hook never waits on a Kafka
# round-trip -- the emit node's own file-spool durability owns the actual
# publish; this hook's job is a fast, best-effort hand-off.
#
# Fail-open per the OMN-13244 baseline's own reasoning: a dead bus, a
# missing Python binary, or malformed stdin must never break or slow the
# user's session. This hook exits 0 unconditionally.
#
# Deliberately minimal and separate from session-start.sh (which remains
# disabled per the OMN-13244 baseline): this hook does not start any
# daemon, inject context, or duplicate session-start.sh's other
# responsibilities.

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

# shellcheck source=onex-paths.sh
source "$(dirname "${BASH_SOURCE[0]}")/onex-paths.sh" 2>/dev/null || true
LOG_FILE="${ONEX_STATE_DIR:-/tmp}/hooks/logs/hook-session-start-bus-mirror.log"
mkdir -p "$(dirname "$LOG_FILE")" 2>/dev/null || true

# Detect project root (same convention as session-start.sh).
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
onex_hook_gate SESSION_START || {
    cat >/dev/null 2>/dev/null || true
    exit 0
}

INPUT="$(cat)"

if ! command -v jq >/dev/null 2>&1; then
    # No jq: cannot safely build a JSON payload. Fail-open, no emission.
    exit 0
fi
if ! echo "$INPUT" | jq -e . >/dev/null 2>&1; then
    INPUT='{}'
fi

SESSION_ID=$(echo "$INPUT" | jq -r '.session_id // .sessionId // ""' 2>/dev/null) || SESSION_ID=""
CWD=$(echo "$INPUT" | jq -r '.cwd // ""' 2>/dev/null) || CWD=""
[[ -z "$CWD" ]] && CWD="$(pwd)"
WORKING_DIRECTORY="$(basename "$CWD")"

PAYLOAD=$(jq -nc \
    --arg session_id "$SESSION_ID" \
    --arg working_directory "$WORKING_DIRECTORY" \
    '{
        session_id: $session_id,
        working_directory: $working_directory,
        hook_source: "startup"
    }' 2>/dev/null) || PAYLOAD='{}'
[[ -z "$PAYLOAD" || "$PAYLOAD" == "null" ]] && PAYLOAD='{}'

_EMIT_DISPATCH_PY="${HOOKS_LIB}/node_event_emit_effect_dispatch.py"
if [[ -n "${PYTHON_CMD:-}" && -f "$_EMIT_DISPATCH_PY" ]]; then
    (
        "$PYTHON_CMD" "$_EMIT_DISPATCH_PY" \
            --event-type "onex.evt.omniclaude.session-started.v1" \
            --payload "$PAYLOAD" \
            --correlation-id "${SESSION_ID:-unknown}" \
            >>"$LOG_FILE" 2>&1
    ) &
    disown 2>/dev/null || true
fi

exit 0
