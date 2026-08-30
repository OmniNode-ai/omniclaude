#!/bin/bash
# SPDX-FileCopyrightText: 2026 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# PostToolUse Bus-Mirror Hook (OMN-16162 S1)
#
# Direct-dispatches node_event_emit_effect (omnimarket) with a
# tool-executed event, backgrounded so this hook never waits on a Kafka
# round-trip -- the emit node's own file-spool durability owns the actual
# publish; this hook's job is a fast, best-effort hand-off. Follows the
# exact same direct-dispatch convention as session_start_bus_mirror.sh /
# session_end_bus_mirror.sh (OMN-16162 S0).
#
# Deliberately separate from post_tool_use_secret_redact_guard.sh (which
# stays registered, unmodified, matcher "Bash" only, and owns rewriting
# tool_response text via its own output-replacement envelope). This hook
# is matcher ".*" (every tool), never touches or rewrites the tool's
# output, and emits NOTHING on stdout -- plain PostToolUse stdout is
# debug-log-only (see CLAUDE.md "silence-on-pass discipline"), so this
# hook only writes to its own log file and the backgrounded dispatch
# process.
#
# Privacy invariant (CLAUDE.md "Kafka Topics & Event Schemas"): only
# preview-safe data goes to onex.evt.* topics -- tool_input/tool_response
# CONTENT is never included, only the tool name and coarse outcome/timing
# metadata.
#
# Fail-open per the OMN-13244 baseline's own reasoning: a dead bus, a
# missing Python binary, or malformed stdin must never break or slow the
# user's session. This hook exits 0 unconditionally.

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
LOG_FILE="${ONEX_STATE_DIR:-/tmp}/hooks/logs/hook-post-tool-use-bus-mirror.log"
mkdir -p "$(dirname "$LOG_FILE")" 2>/dev/null || true

# Detect project root (same convention as session_start_bus_mirror.sh).
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
onex_hook_gate POST_TOOL_USE_BUS_MIRROR || {
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
TOOL_NAME=$(echo "$INPUT" | jq -r '.tool_name // "unknown"' 2>/dev/null) || TOOL_NAME="unknown"
DURATION_MS=$(echo "$INPUT" | jq -r '.duration_ms // 0' 2>/dev/null) || DURATION_MS=0
[[ "$DURATION_MS" =~ ^[0-9]+$ ]] || DURATION_MS=0
INTERRUPTED=$(echo "$INPUT" | jq -r '.tool_response.interrupted // false' 2>/dev/null) || INTERRUPTED="false"
[[ "$INTERRUPTED" == "true" ]] || INTERRUPTED="false"

PAYLOAD=$(jq -nc \
    --arg session_id "$SESSION_ID" \
    --arg working_directory "$WORKING_DIRECTORY" \
    --arg tool_name "$TOOL_NAME" \
    --argjson duration_ms "$DURATION_MS" \
    --argjson interrupted "$INTERRUPTED" \
    '{
        session_id: $session_id,
        working_directory: $working_directory,
        tool_name: $tool_name,
        duration_ms: $duration_ms,
        interrupted: $interrupted,
        hook_source: "post_tool_use"
    }' 2>/dev/null) || PAYLOAD='{}'
[[ -z "$PAYLOAD" || "$PAYLOAD" == "null" ]] && PAYLOAD='{}'

# OMN-17224: fast-path append. This used to invoke
# node_event_emit_effect_dispatch.py, which imported the omnimarket
# handler stack and published to Kafka inline -- 31.08s of a 31.65s
# handle() was a lazily-imported omnibase_infra chain building ~2,497
# Pydantic classes. One such process per tool call produced 14
# concurrent emitters at ~270% CPU on the operator Mac. The hook now
# only appends to the local journal (stdlib only, sub-100ms); the
# singleton drainer (launchd ai.omninode.hook-emit-drainer) pays that
# import once and publishes the backlog.
_EMIT_DISPATCH_PY="${HOOKS_LIB}/hook_emit_append.py"
if [[ -n "${PYTHON_CMD:-}" && -f "$_EMIT_DISPATCH_PY" ]]; then
    (
        "$PYTHON_CMD" "$_EMIT_DISPATCH_PY" \
            --event-type "onex.evt.omniclaude.tool-executed.v1" \
            --payload "$PAYLOAD" \
            --correlation-id "${SESSION_ID:-unknown}" \
            >>"$LOG_FILE" 2>&1
    ) &
    disown 2>/dev/null || true
fi

exit 0
