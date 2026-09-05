#!/bin/bash
# SPDX-FileCopyrightText: 2026 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# PreToolUse Ticket-Creation Admission Gate (OMN-17942)
# =====================================================
# Refuses a Linear issue CREATE (`mcp__linear-server__save_issue` with no `id`)
# that is not bound to a commitment: no parent and no epic declaration, no
# project, no `Gate:` binding line, or a residual-shaped title with no
# live-gate-defect binding. An UPDATE (`save_issue` with an `id`) is never
# gated.
#
# Why a hook and not a validator
# ------------------------------
# Measured over Linear 2026-08-22..2026-09-04: 1553 tickets created in fourteen
# days -- about 111 a day -- against roughly 35 a day closed. 1537 of the 1553
# were created under the single API identity every dispatched lane writes as,
# so this is lanes minting tickets, not a person filing them. 398 have never
# been touched since filing, 779 have never left Backlog, 343 are unclassifiable
# by title, and net +571 landed in the NEXT sprint's project with +269 in no
# project at all.
#
# The control in place was prose -- omni_home's CLAUDE.md and every dispatch
# brief say not to file follow-up tickets for residuals, and the standing
# three-closure-chain WIP limit says not to open new chains. A ticket is created
# by an MCP tool call from a session, so no pre-commit hook and no repo CI job
# ever sees it; the tool seam is the only place the omission is observable
# before the ticket exists. That is the same argument, and the same primitive,
# as pre_tool_use_agent_model_guard.sh (OMN-17499): it REFUSES the tool call.
#
# Fail-closed / fail-open boundary, stated deliberately
# -----------------------------------------------------
#   * A tool other than the Linear write surface, or a non-OmniNode repo, is
#     passed through untouched. A bug here can never brick unrelated traffic,
#     and an external user of this plugin never sees an ONEX rule fire.
#   * A save_issue call this guard cannot evaluate -- unparseable hook JSON, a
#     missing decision core, an unresolvable interpreter, an unreadable policy,
#     a body filled in server-side from a `template` the guard never sees -- is
#     BLOCKED. A create whose binding cannot be verified is refused, never
#     assumed clean. The blast radius of that decision is exactly one tool name.
#
# Gating: the LINEAR_DONE_VERIFY bit (0x80000000000). A brand-new bit is not
# available: EnumHookBit lives in omnibase_core, all 60 default-mask ordinals
# are allocated (60-62 are the disabled-by-default trio, 63 is the sign bit of a
# signed 64-bit integer and is forbidden outright by knowledge-base-internal
# reference/hook-bitmask-bit-governance.md rule 7), so minting one is a
# cross-repo release chain plus an architecture review. That is the same
# constraint and the same resolution pre_tool_use_agent_model_guard.sh recorded
# for PRE_TOOL_AGENT_DISPATCH_GATE and pre_tool_use_pr_ownership_guard.sh
# recorded for BASH_GUARD.
#
# LINEAR_DONE_VERIFY is the right borrow and not an arbitrary one: it is the
# only Linear-scoped bit in the enum, and its namesake script
# (pre_tool_use_linear_done_verify.sh) is on disk and UNREGISTERED under the
# OMN-13244 baseline -- its merged-PR semantics were folded into
# pre_tool_use_done_flip_guard.sh by OMN-13856 -- so
# `onex hooks disable LINEAR_DONE_VERIFY` disables exactly this guard and
# nothing else that is live. The sibling on this same matcher,
# pre_tool_use_done_flip_guard.sh, gates on a bit name hook_bits.sh does not
# define, so that gate can never fire and its bit is not a switch at all --
# borrowing it would have produced a guard with no working disable. (That bit's
# name is deliberately NOT spelled here: hook_inventory.py reads this file's
# gate call with a regex over the whole script, so naming a second bit in prose
# makes the inventory report the wrong disable surface. The same class of defect
# as omni_home CLAUDE.md rule 15, one file over -- found by that validator on
# this very script.) tests/hooks/test_ticket_creation_guard.py pins the borrow:
# re-registering pre_tool_use_linear_done_verify.sh turns the suite red rather
# than silently putting two controls behind one switch.
#   Disable with: onex hooks disable LINEAR_DONE_VERIFY
#
# A disabled run is LOGGED, not silent. The OMN-13244 history is a hook going
# dark with no repo-visible signal for months; a bare `|| exit 0` here would
# reproduce that one mask edit at a time.
#
# Registration follows the OMN-14330 worktree-guard carve-out precedent, and is
# ordered AFTER pre_tool_use_done_flip_guard.sh on the same matcher: that guard
# owns the Done-flip half of this surface and only ever inspects updates, so the
# two never contend for the same call.

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
# trap would convert that into `exit 0` -- a silent fail-OPEN, which is the
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
GUARD_PY="${SCRIPT_DIR}/../lib/ticket_creation_guard.py"
unset _SELF

# Stable CWD before any Python invocation: the session CWD may live on an
# external volume that disconnects, and CPython aborts at startup when
# os.getcwd() fails.
cd "$HOME" 2>/dev/null || cd /tmp || true

# shellcheck source=./onex-paths.sh
source "${SCRIPT_DIR}/onex-paths.sh" 2>/dev/null || true
LOG_FILE="${ONEX_HOOK_LOG:-${HOME}/.claude/onex-hooks.log}"
mkdir -p "$(dirname "$LOG_FILE")" 2>/dev/null || true

_log() {
    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] ticket-creation-gate: $*" >> "$LOG_FILE" 2>/dev/null || true
}

if ! onex_hook_gate LINEAR_DONE_VERIFY; then
    _log "DISABLED: LINEAR_DONE_VERIFY is cleared in ONEX_HOOKS_MASK, so this create was not evaluated. Re-enable with: onex hooks enable LINEAR_DONE_VERIFY"
    exit 0
fi

_block() {
    _hook_status "BLOCKED" "$1" "0" 2>/dev/null || true
    _log "BLOCKED: $1"
    jq -n --arg reason "$2" '{"decision": "block", "reason": $reason}'
    trap - EXIT
    exit 2
}

TOOL_INFO=$(cat)

if ! TOOL_NAME=$(echo "$TOOL_INFO" | jq -er '.tool_name // empty' 2>/dev/null); then
    # Only the Linear write surface reaches this hook, so refusing an unreadable
    # payload cannot strand any other tool. An unverifiable create is refused,
    # never assumed clean.
    _block "unparseable hook JSON" \
        "BLOCKED: the PreToolUse payload for this Linear write is not readable JSON, so the guard cannot tell whether it creates a ticket or updates one (OMN-17942). An unverifiable create is refused, never assumed clean. To disable this guard: onex hooks disable LINEAR_DONE_VERIFY"
fi

case "$TOOL_NAME" in
    *save_issue*) ;;
    *)
        _hook_status "PASS" "not a Linear issue write ($TOOL_NAME)" "0" 2>/dev/null || true
        exit 0
        ;;
esac

if [[ ! -f "$GUARD_PY" ]]; then
    _block "decision core missing" \
        "BLOCKED: the OMN-17942 ticket-creation admission gate is missing at ${GUARD_PY}, so this issue create cannot be checked. Repair the plugin install, or disable the guard deliberately: onex hooks disable LINEAR_DONE_VERIFY"
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
        "BLOCKED: no Python interpreter could be resolved to run the OMN-17942 ticket-creation admission gate, so this issue create cannot be checked. Repair the plugin install, or disable the guard deliberately: onex hooks disable LINEAR_DONE_VERIFY"
fi

set +e
GUARD_OUT=$(printf '%s' "$TOOL_INFO" | env -u PYTHONPATH "$GUARD_PYTHON" "$GUARD_PY" 2>&1)
GUARD_RC=$?
set -e

if [[ $GUARD_RC -eq 0 ]]; then
    _hook_status "PASS" "issue create is bound, or this is an update" "0" 2>/dev/null || true
    exit 0
fi

if [[ $GUARD_RC -eq 3 ]]; then
    REASON=$(printf '%s' "$GUARD_OUT" | jq -r '.reason // empty' 2>/dev/null || true)
    if [[ -z "$REASON" ]]; then
        REASON="BLOCKED: this Linear issue create is not bound to a commitment (OMN-17942), and the guard's own detail payload was unreadable."
    fi
    _block "issue create not bound to a commitment" "$REASON"
fi

_block "guard evaluation failed (rc=${GUARD_RC})" \
    "BLOCKED: the OMN-17942 ticket-creation admission gate could not evaluate this ${TOOL_NAME} call (exit ${GUARD_RC}), so its binding is unverified and the create is refused. Detail: $(printf '%s' "$GUARD_OUT" | head -c 400). To disable this guard deliberately: onex hooks disable LINEAR_DONE_VERIFY"
