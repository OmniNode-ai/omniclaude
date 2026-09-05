#!/bin/bash
# SPDX-FileCopyrightText: 2026 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# PreToolUse Credential-Rotation Admission Gate (OMN-17957)
# ==========================================================
# Refuses a Bash command that rotates, re-issues or revokes a credential unless
# it carries an explicit citation
#
#   ROTATION-CONSENT: docs/tracking/ROLLING_WORK_LEDGER.md:<line>
#
# resolving to an OPERATOR-CONSENT row (omni_home CLAUDE.md rule 18, extended by
# rule 22 with approved_by=<operator|jake>) whose APPROVED SCOPE names the
# credential the command names and which carries an OUT OF SCOPE list.
#
# Why a hook and not a validator
# ------------------------------
# Operator ruling, 2026-09-05, firm: credential rotations keep being performed
# because an agent decided that a value it saw in its own transcript -- a value
# that never left the computer -- was a leak. On 2026-08-30 a lane rotated the
# Infisical operator-k8s org-admin client secret on exactly that reasoning: the
# finding was that a lower-privileged in-cluster identity could READ the pair at
# the same path, and nothing in the ticket claims the value was pushed to a
# remote, posted publicly, printed into CI, or handed outside. That rotation
# rewrote the two Secrets the InfisicalSecret operator's CRs authenticate with,
# restarted the three application Deployments but not the operator itself, and
# fourteen hours later every onex-dev CR began failing 401. Secret sync stayed
# frozen cluster-wide for five days.
#
# The control in place was prose. A rotation is a command typed in a session, so
# no pre-commit hook and no repo CI job ever sees it; the tool seam is the only
# place it is observable before the credential is already gone. That is the same
# argument, and the same primitive, as pre_tool_use_agent_model_guard.sh
# (OMN-17499) and pre_tool_use_ticket_creation_gate.sh (OMN-17942): it REFUSES
# the tool call.
#
# Reads are never gated -- and they are not allowlisted either, they simply
# match no configured shape, because every shape names only mutating
# subcommands. `kubectl get/describe`, `-o name`, `aws secretsmanager
# get-secret-value/describe-secret/list-secrets`, `gh secret list`, `kcadm get`
# and a `curl` with no mutating method are outside the vocabulary. `kubectl
# rollout restart` is outside it deliberately: it is the consumer-restart half
# of the remedy the ruling requires -- the half the 2026-08-30 rotation omitted
# for the Infisical operator Deployment -- and a gate that made the correct
# repair harder than the mistake would be routed around.
#
# Fail-open / fail-closed boundary, stated deliberately
# -----------------------------------------------------
#   * A command carrying none of the rotation vocabulary never invokes Python at
#     all. The grep below is a cheap OVER-matcher that decides nothing; it fires
#     on any command mentioning a secret, an access key, kcadm, or ALTER
#     ROLE/USER, including quoted text that merely names one. A bug in this
#     guard can never brick unrelated Bash traffic.
#   * A payload that DOES carry the vocabulary and cannot then be evaluated --
#     unparseable hook JSON, a missing decision core, an unresolvable
#     interpreter, an unreadable policy, an untokenisable command -- is BLOCKED.
#     An unverifiable rotation is refused, never assumed clean.
#   * credential_rotation_guard.py is the authority, not the grep. It tokenises
#     each shell segment and matches by program plus tokens, so `echo 'aws
#     secretsmanager rotate-secret'` and a grep for the vocabulary trip the
#     pre-filter and are then ALLOWED. Conflating the two layers is the
#     OMN-16983 defect that refused every `gh api` read on this host.
#
# What this cannot do, stated rather than implied
# -----------------------------------------------
# No file can prove a human said the words. This gate does not establish
# operator authenticity; it establishes that a durable, citable, correctly
# shaped row naming the credential and an authorised approver exists in the one
# append-only coordination surface BEFORE the rotation runs, so the
# authorisation is resolvable after the session that granted it is gone. It
# converts a silent rotation into one that must leave an auditable artifact.
# That is the same honest limit omni_home CLAUDE.md records for the
# staging-namespace gate: what is enforced is blast radius and evidence, not
# authenticity.
#
# Gating: the PRE_TOOL_AUTHORIZATION_SHIM bit (0x200000000). A dedicated bit is
# unavailable -- EnumHookBit lives in omnibase_core, all 60 default-mask
# ordinals are allocated (60-62 are the disabled-by-default trio, and
# knowledge-base-internal reference/hook-bitmask-bit-governance.md rule 7
# forbids ordinal 63 outright), so minting one is a cross-repo release chain
# plus an architecture review. Same constraint and same resolution
# pre_tool_use_pr_ownership_guard.sh recorded for BASH_GUARD and
# pre_tool_use_ticket_creation_gate.sh recorded for LINEAR_DONE_VERIFY.
#
# PRE_TOOL_AUTHORIZATION_SHIM is the faithful borrow and not an arbitrary one:
# its namesake script is the plugin's PreToolUse AUTHORIZATION gate, it is on
# disk and UNREGISTERED under the OMN-13244 baseline, and no other registered
# script gates on it -- so `onex hooks disable PRE_TOOL_AUTHORIZATION_SHIM`
# disables exactly this guard and nothing else that is live. BASH_GUARD was NOT
# a candidate even though this is a Bash-matcher guard: pre_tool_use_pr_
# ownership_guard.sh already borrows it, and putting two independent controls
# behind one switch means disabling either one silently disables both.
# tests/hooks/test_credential_rotation_guard.py pins the borrow: re-registering
# the namesake turns the suite red rather than quietly sharing the switch.
#   Disable with: onex hooks disable PRE_TOOL_AUTHORIZATION_SHIM
#
# A disabled run is LOGGED, not silent. The OMN-13244 history is a hook going
# dark with no repo-visible signal for months; a bare `|| exit 0` here would
# reproduce that one mask edit at a time.
#
# Registration follows the OMN-14330 worktree-guard carve-out precedent, and is
# ordered AFTER pre_tool_use_pr_ownership_guard.sh on the Bash matcher: that
# guard owns GitHub-mutation ownership and never inspects a credential shape, so
# the two never contend for the same call.

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
GUARD_PY="${SCRIPT_DIR}/../lib/credential_rotation_guard.py"
unset _SELF

# Stable CWD before any Python invocation: the session CWD may live on an
# external volume that disconnects, and CPython aborts at startup when
# os.getcwd() fails.
cd "$HOME" 2>/dev/null || cd /tmp || true

# onex-paths.sh EXPORTS ONEX_HOOK_LOG unconditionally, clobbering a value the
# caller set. Capture the caller's first and prefer it: an explicitly supplied
# log path is a deliberate instruction, and a harness that cannot redirect this
# log cannot assert that a disabled run leaves a trace -- which is the whole
# point of logging the disable rather than exiting silently.
_CALLER_HOOK_LOG="${ONEX_HOOK_LOG:-}"
# shellcheck source=./onex-paths.sh
source "${SCRIPT_DIR}/onex-paths.sh" 2>/dev/null || true
LOG_FILE="${_CALLER_HOOK_LOG:-${ONEX_HOOK_LOG:-${HOME}/.claude/onex-hooks.log}}"
unset _CALLER_HOOK_LOG
mkdir -p "$(dirname "$LOG_FILE")" 2>/dev/null || true

_log() {
    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] credential-rotation-guard: $*" >> "$LOG_FILE" 2>/dev/null || true
}

if ! onex_hook_gate PRE_TOOL_AUTHORIZATION_SHIM; then
    _log "DISABLED: PRE_TOOL_AUTHORIZATION_SHIM is cleared in ONEX_HOOKS_MASK, so this command was not evaluated for a credential rotation. Re-enable with: onex hooks enable PRE_TOOL_AUTHORIZATION_SHIM"
    cat >/dev/null
    exit 0
fi

_block() {
    _hook_status "BLOCKED" "$1" "0" 2>/dev/null || true
    _log "BLOCKED: $1"
    jq -n --arg reason "$2" '{"decision": "block", "reason": $reason}' 2>/dev/null \
        || printf '{"decision": "block", "reason": %s}\n' "$(printf '%s' "$2" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')"
    trap - EXIT
    exit 2
}

TOOL_INFO=$(cat)

# Cheap OVER-matching pre-filter. It decides nothing: anything it lets through
# is decided by credential_rotation_guard.py, which tokenises the command. A
# command with none of this vocabulary cannot be any configured rotation shape,
# so it never pays for an interpreter start.
if ! printf '%s' "$TOOL_INFO" | grep -Eqi 'secret|access-key|access_key|kcadm|alter[[:space:]]+(role|user)'; then
    _hook_status "PASS" "no credential-rotation vocabulary" "0" 2>/dev/null || true
    exit 0
fi

if ! TOOL_NAME=$(echo "$TOOL_INFO" | jq -er '.tool_name // empty' 2>/dev/null); then
    _block "unparseable hook JSON carrying credential-rotation vocabulary" \
        "BLOCKED: the PreToolUse payload for this Bash call names a credential surface but is not readable JSON, so the guard cannot tell whether it rotates, re-issues or revokes one (OMN-17957). An unverifiable rotation is refused, never assumed clean. To disable this guard: onex hooks disable PRE_TOOL_AUTHORIZATION_SHIM"
fi

if [[ "$TOOL_NAME" != "Bash" ]]; then
    _hook_status "PASS" "not a Bash call ($TOOL_NAME)" "0" 2>/dev/null || true
    exit 0
fi

if [[ ! -f "$GUARD_PY" ]]; then
    _block "decision core missing" \
        "BLOCKED: the OMN-17957 credential-rotation admission gate is missing at ${GUARD_PY}, so this command cannot be checked for a credential rotation. Repair the plugin install, or disable the guard deliberately: onex hooks disable PRE_TOOL_AUTHORIZATION_SHIM"
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
        "BLOCKED: no Python interpreter could be resolved to run the OMN-17957 credential-rotation admission gate, so this command cannot be checked. Repair the plugin install, or disable the guard deliberately: onex hooks disable PRE_TOOL_AUTHORIZATION_SHIM"
fi

set +e
GUARD_OUT=$(printf '%s' "$TOOL_INFO" | env -u PYTHONPATH "$GUARD_PYTHON" "$GUARD_PY" 2>&1)
GUARD_RC=$?
set -e

if [[ $GUARD_RC -eq 0 ]]; then
    _hook_status "PASS" "no unauthorised credential rotation in this command" "0" 2>/dev/null || true
    exit 0
fi

if [[ $GUARD_RC -eq 3 ]]; then
    REASON=$(printf '%s' "$GUARD_OUT" | jq -r '.reason // empty' 2>/dev/null || true)
    if [[ -z "$REASON" ]]; then
        REASON="BLOCKED: this command rotates, re-issues or revokes a credential without an authorised ROTATION-CONSENT citation (OMN-17957), and the guard's own detail payload was unreadable."
    fi
    _block "unauthorised credential rotation" "$REASON"
fi

_block "guard evaluation failed (rc=${GUARD_RC})" \
    "BLOCKED: the OMN-17957 credential-rotation admission gate could not evaluate this Bash command (exit ${GUARD_RC}), so whether it rotates a credential is unverified and the command is refused. Detail: $(printf '%s' "$GUARD_OUT" | head -c 400). To disable this guard deliberately: onex hooks disable PRE_TOOL_AUTHORIZATION_SHIM"
