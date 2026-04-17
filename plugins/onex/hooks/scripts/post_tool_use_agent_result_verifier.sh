#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# PostToolUse Agent-Result Verifier (OMN-9055 — Task 4 scaffold)
#
# Extracts structured claims (pr_merged, thread_resolved, linear_state)
# from Agent turn output and verifies each against ground truth via
# agent_result_verifier_runner. On fabricated-claim detection the runner
# prints a structured JSON diff; this wrapper surfaces that diff to stderr
# so the user sees the block message inline.
#
# NOTE on exit codes: per the repo invariant (error-guard.sh), every hook
# exits 0 — non-zero exits are swallowed to protect Claude Code from
# infrastructure failures freezing the UI. The signal to the user is the
# stderr output, not the exit code. Blocking semantics are surfaced via
# text, not status. Python-layer tests assert the true exit-2 path.
#
# Scaffold scope — 3 claim kinds, basic `gh pr view` check only. Maturity
# (≥6 kinds + real resolver-backed verification via a dedicated omnimarket
# claim-resolver node) ships under a follow-up ticket. Do NOT extend the
# inline `gh` path here; it is deliberately minimal so the bridge point
# is obvious when the follow-up lands.

set -euo pipefail
_OMNICLAUDE_HOOK_NAME="$(basename "${BASH_SOURCE[0]}")"
source "$(dirname "${BASH_SOURCE[0]}")/error-guard.sh" 2>/dev/null || true

# --- Lite mode guard (OMN-5398) -------------------------------------------
_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
_MODE_SH="${_SCRIPT_DIR}/../../lib/mode.sh"
if [[ -f "$_MODE_SH" ]]; then
    source "$_MODE_SH"
    [[ "$(omniclaude_mode)" == "lite" ]] && exit 0
fi
unset _SCRIPT_DIR _MODE_SH

# --- Disable switch (per-session escape hatch) ----------------------------
if [[ "${OMN_9055_AGENT_VERIFIER_DISABLED:-0}" == "1" ]]; then
    cat
    exit 0
fi

# Ensure stable CWD before any Python invocation.
cd "$HOME" 2>/dev/null || cd /tmp || true

# Portable plugin root resolution.
_SELF="$(realpath "${BASH_SOURCE[0]}" 2>/dev/null \
    || python3 -c "import os,sys; print(os.path.realpath(sys.argv[1]))" "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(cd "$(dirname "${_SELF}")" && pwd)"
PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "${SCRIPT_DIR}/../.." && pwd)}"
unset _SELF SCRIPT_DIR

# --- Log path -------------------------------------------------------------
if [[ -z "${ONEX_STATE_DIR:-}" ]]; then
    echo "[$(date -u +%FT%TZ)] ERROR: ONEX_STATE_DIR unset; agent-result verifier cannot write log." \
        >> /tmp/onex-hook-error.log
    cat
    exit 0
fi
LOG_FILE="${ONEX_STATE_DIR}/hooks/logs/agent-result-verifier.log"
mkdir -p "$(dirname "$LOG_FILE")"

_log() { echo "[$(date -u +%FT%TZ)] $*" >> "$LOG_FILE" 2>/dev/null || true; }

# --- Dependency guards ----------------------------------------------------
if ! command -v jq >/dev/null 2>&1; then
    _log "SKIP: jq not found; passing through"
    cat
    exit 0
fi

# --- Read hook event ------------------------------------------------------
HOOK_EVENT="$(cat)"

if ! printf '%s\n' "$HOOK_EVENT" | jq -e . >/dev/null 2>>"$LOG_FILE"; then
    _log "SKIP: malformed JSON on stdin"
    printf '%s\n' "$HOOK_EVENT"
    exit 0
fi

TOOL_NAME="$(printf '%s\n' "$HOOK_EVENT" | jq -r '.tool_name // "unknown"')"

# Only inspect Agent turn completions. Claude Code fires this hook under
# matcher `Agent`; guard defensively in case a future runtime change broadens
# the fan-out.
if [[ "$TOOL_NAME" != "Agent" ]]; then
    printf '%s\n' "$HOOK_EVENT"
    exit 0
fi

# Agent turn body: the text the subagent produced. Claude Code delivers this
# under `.tool_response.content` (string) or `.tool_response.output` depending
# on runtime version; union-select the first non-empty string field.
TURN_BODY="$(printf '%s\n' "$HOOK_EVENT" \
    | jq -r '(.tool_response.content // .tool_response.output // "") | tostring')"

if [[ -z "$TURN_BODY" ]]; then
    _log "SKIP: empty turn body"
    printf '%s\n' "$HOOK_EVENT"
    exit 0
fi

# Repo hint: derived from session cwd if available. Falls back to "" (no hint);
# the extractor emits bare `#N` refs in that case and the resolver must resolve
# from context.
REPO_HINT="$(printf '%s\n' "$HOOK_EVENT" | jq -r '.cwd // ""' | awk -F/ '{print $NF}')"

# --- Invoke extractor + resolver bridge ----------------------------------
# Deliberately avoid sourcing common.sh — it requires PROJECT_ROOT (set by
# the plugin loader) and carries a large transitive surface. This hook
# only needs python3 + jq.
PYTHON_BIN="${PLUGIN_PYTHON_BIN:-python3}"
# PLUGIN_ROOT is plugins/onex; repo root is plugins/onex/../.. so that
# `plugins.onex.hooks.lib.<mod>` resolves under PYTHONPATH.
REPO_ROOT_FOR_PYTHONPATH="$(cd "${PLUGIN_ROOT}/../.." && pwd)"

set +e
VERIFIER_RESULT="$(
    PYTHONPATH="${REPO_ROOT_FOR_PYTHONPATH}${PYTHONPATH:+:${PYTHONPATH}}" \
    REPO_HINT="$REPO_HINT" \
    "$PYTHON_BIN" -m plugins.onex.hooks.lib.agent_result_verifier_runner \
    <<< "$TURN_BODY" 2>&1
)"
VERIFIER_EXIT=$?
set -e

if [[ "$VERIFIER_EXIT" == "2" ]]; then
    _log "BLOCK: agent turn made fabricated claim(s): $VERIFIER_RESULT"
    # Emit structured block message. Claude Code reads stderr on non-zero
    # exit to show the user why the hook blocked.
    cat >&2 <<EOF
BLOCKED: post_tool_use_agent_result_verifier detected fabricated claim(s) in
the agent turn output. The claim(s) below cannot be verified against ground
truth — either the side effect never happened or the claim references a
non-existent resource.

$VERIFIER_RESULT

To override for a single turn (use sparingly, log friction), export
OMN_9055_AGENT_VERIFIER_DISABLED=1 before re-running.
EOF
    # Pass through original event so downstream hooks still see it.
    printf '%s\n' "$HOOK_EVENT"
    exit 2
fi

# Fail-open path (verifier exit 0 whether because all claims verified or
# because no claims / resolver unreachable).
if [[ -n "$VERIFIER_RESULT" ]]; then
    _log "NOTE: $VERIFIER_RESULT"
fi
printf '%s\n' "$HOOK_EVENT"
exit 0
