#!/bin/bash
# SPDX-FileCopyrightText: 2026 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# PreToolUse Background-Agent Model Guard (OMN-17499)
# ===================================================
# Refuses a `Workflow` dispatch whose `agent()` calls do not each name an
# allowed background model, and an `Agent` dispatch with no allowed model.
#
# Why a hook and not a validator
# ------------------------------
# On 2026-09-01 one session dispatched 41 workflow scripts whose `agent()`
# calls omitted `model:`; every one inherited the parent session's model, which
# was banned for background work. The control in place was a memory entry. It
# failed 41 times, silently, in a single session.
#
# The scripts live under ~/.claude/projects/<project>/workflows/scripts/ and are
# in NO repository, so a pre-commit hook or a repo CI validator never sees them
# at author time. The dispatch seam is the only place the omission is
# observable before the cost is paid. So this is the same primitive as
# pre_tool_use_worktree_guard.sh: it REFUSES the tool call.
#
# Fail-closed / fail-open boundary, stated deliberately
# ----------------------------------------------------
#   * A tool other than Workflow/Agent, or a non-OmniNode repo, is passed
#     through untouched. A bug here can never brick unrelated traffic, and an
#     external user of this plugin never sees an ONEX rule fire.
#   * A Workflow or Agent call this guard cannot evaluate — unparseable hook
#     JSON, a missing decision core, an unreadable `scriptPath`, an
#     unresolvable interpreter, an unreadable allowlist — is BLOCKED. A model
#     choice that cannot be verified is refused, never assumed. The blast
#     radius of that decision is exactly two tool names.
#
# Silence on the allow path is deliberate: the Workflow payload carries the
# entire script body, and re-emitting it would copy every prompt into the hook
# output stream for no benefit. A clean dispatch produces no output at all.
#
# Gating: the PRE_TOOL_AGENT_DISPATCH_GATE bit, whose contract description is
# "Validates dispatch envelope before any Agent() call is made" — exactly this
# control. A brand-new bit is not available: EnumHookBit lives in
# omnibase_core, all 60 default-mask bit positions are allocated (bits 60-62
# are the disabled-by-default trio and 63 is bash's sign bit), so minting one
# is a cross-repo release chain. That is the same constraint and the same
# resolution pre_tool_use_pr_ownership_guard.sh recorded for BASH_GUARD, and
# like that case the borrowed bit's own script (pre_tool_use_agent_dispatch_gate.sh)
# is unregistered under the OMN-13244 baseline, so nothing else is gated by it.
#   Disable with: onex hooks disable PRE_TOOL_AGENT_DISPATCH_GATE
#
# Registration follows the OMN-14330 worktree-guard carve-out precedent, and is
# ordered AHEAD of pre_tool_use_lane_open.sh so a refused dispatch does not
# first write a phantom OPEN lane record.

set -euo pipefail
_OMNICLAUDE_HOOK_NAME="$(basename "${BASH_SOURCE[0]}")"

_OMNICLAUDE_CALLER_CWD="${CLAUDE_PROJECT_DIR:-$PWD}"
# shellcheck source=../lib/repo_guard.sh
. "$(dirname "${BASH_SOURCE[0]}")/../lib/repo_guard.sh" 2>/dev/null || true
if declare -F is_omninode_repo >/dev/null 2>&1; then
    CLAUDE_PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$_OMNICLAUDE_CALLER_CWD}" \
        is_omninode_repo || {
        cat >/dev/null
        trap - EXIT 2>/dev/null || true
        exit 0
    }
fi

# error-guard.sh also sources hook-gate.sh, which supplies onex_hook_gate
# without common.sh. common.sh is deliberately NOT sourced: its find_python()
# hard-fails with `exit 1` when no venv is present, and the error-guard EXIT
# trap would convert that into `exit 0` — a silent fail-OPEN, which is the
# OMN-8928 shape this plugin's own canary harness exists to catch. The decision
# core is standard-library-only precisely so this guard can resolve an
# interpreter itself and refuse when it cannot.
# shellcheck source=./error-guard.sh
source "$(dirname "${BASH_SOURCE[0]}")/error-guard.sh" 2>/dev/null || true

# Resolve this script's own location BEFORE any `cd`. BASH_SOURCE[0] may be
# relative, and resolving it afterwards lands in the wrong tree.
_SELF="$(realpath "${BASH_SOURCE[0]}" 2>/dev/null \
    || python3 -c "import os,sys; print(os.path.realpath(sys.argv[1]))" "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(cd "$(dirname "${_SELF}")" && pwd)"
PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "${SCRIPT_DIR}/../.." && pwd)}"
GUARD_PY="${SCRIPT_DIR}/../lib/workflow_model_guard.py"
unset _SELF

# Stable CWD before any Python invocation: the session CWD may live on an
# external volume that disconnects, and CPython aborts at startup when
# os.getcwd() fails.
cd "$HOME" 2>/dev/null || cd /tmp || true

# shellcheck source=./onex-paths.sh
source "${SCRIPT_DIR}/onex-paths.sh" 2>/dev/null || true
LOG_FILE="${ONEX_HOOK_LOG:-${HOME}/.claude/onex-hooks.log}"
mkdir -p "$(dirname "$LOG_FILE")" 2>/dev/null || true

onex_hook_gate PRE_TOOL_AGENT_DISPATCH_GATE || exit 0

_log() {
    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] agent-model-guard: $*" >> "$LOG_FILE" 2>/dev/null || true
}

_block() {
    _hook_status "BLOCKED" "$1" "0" 2>/dev/null || true
    _log "BLOCKED: $1"
    jq -n --arg reason "$2" '{"decision": "block", "reason": $reason}'
    trap - EXIT
    exit 2
}

TOOL_INFO=$(cat)

if ! TOOL_NAME=$(echo "$TOOL_INFO" | jq -er '.tool_name // empty' 2>/dev/null); then
    # Only Workflow and Agent reach this hook, so refusing an unreadable
    # payload cannot strand any other tool. An unverifiable dispatch is
    # refused, never assumed clean.
    _block "unparseable hook JSON" \
        "BLOCKED: the PreToolUse payload for this dispatch is not readable JSON, so the background agent's model cannot be verified (OMN-17499). An unverifiable dispatch is refused, never assumed clean. To disable this guard: onex hooks disable PRE_TOOL_AGENT_DISPATCH_GATE"
fi

if [[ "$TOOL_NAME" != "Workflow" && "$TOOL_NAME" != "Agent" ]]; then
    _hook_status "PASS" "not Workflow/Agent ($TOOL_NAME)" "0" 2>/dev/null || true
    exit 0
fi

if [[ ! -f "$GUARD_PY" ]]; then
    _block "decision core missing" \
        "BLOCKED: the OMN-17499 background-agent model guard is missing at ${GUARD_PY}, so the model of this dispatch cannot be checked. Repair the plugin install, or disable the guard deliberately: onex hooks disable PRE_TOOL_AGENT_DISPATCH_GATE"
fi

# Interpreter resolution. The decision core imports only the standard library,
# so any CPython 3.11+ can run it; the chain still prefers the plugin's own
# interpreters so behaviour matches every other hook, and refuses rather than
# guessing when none exists.
_resolve_python() {
    if [[ -n "${PLUGIN_PYTHON_BIN:-}" && -x "${PLUGIN_PYTHON_BIN}" ]]; then
        echo "${PLUGIN_PYTHON_BIN}"
        return 0
    fi
    if [[ -n "${CLAUDE_PLUGIN_DATA:-}" && -x "${CLAUDE_PLUGIN_DATA}/.venv/bin/python3" ]]; then
        echo "${CLAUDE_PLUGIN_DATA}/.venv/bin/python3"
        return 0
    fi
    local repo_venv
    repo_venv="$(cd "${PLUGIN_ROOT}/../.." 2>/dev/null && pwd)/.venv/bin/python3"
    if [[ -x "$repo_venv" ]]; then
        echo "$repo_venv"
        return 0
    fi
    local brew_py
    for brew_py in /opt/homebrew/bin/python3.13 /usr/local/bin/python3.13; do
        if [[ -x "$brew_py" ]]; then
            echo "$brew_py"
            return 0
        fi
    done
    if command -v python3 >/dev/null 2>&1; then
        command -v python3
        return 0
    fi
    return 1
}

if ! GUARD_PYTHON="$(_resolve_python)"; then
    _block "no python interpreter" \
        "BLOCKED: no Python interpreter could be resolved to run the OMN-17499 background-agent model guard, so this dispatch's model cannot be verified. Repair the plugin install, or disable the guard deliberately: onex hooks disable PRE_TOOL_AGENT_DISPATCH_GATE"
fi

set +e
GUARD_OUT=$(printf '%s' "$TOOL_INFO" | env -u PYTHONPATH "$GUARD_PYTHON" "$GUARD_PY" 2>&1)
GUARD_RC=$?
set -e

if [[ $GUARD_RC -eq 0 ]]; then
    _hook_status "PASS" "explicit background model on every agent call" "0" 2>/dev/null || true
    exit 0
fi

if [[ $GUARD_RC -eq 3 ]]; then
    REASON=$(printf '%s' "$GUARD_OUT" | jq -r '.reason // empty' 2>/dev/null || true)
    if [[ -z "$REASON" ]]; then
        REASON="BLOCKED: background agent model not chosen explicitly (OMN-17499), and the guard's own detail payload was unreadable."
    fi
    _block "background model not chosen explicitly" "$REASON"
fi

_block "guard evaluation failed (rc=${GUARD_RC})" \
    "BLOCKED: the OMN-17499 background-agent model guard could not evaluate this ${TOOL_NAME} dispatch (exit ${GUARD_RC}), so its model is unverified and the dispatch is refused. Detail: $(printf '%s' "$GUARD_OUT" | head -c 400). To disable this guard deliberately: onex hooks disable PRE_TOOL_AGENT_DISPATCH_GATE"
