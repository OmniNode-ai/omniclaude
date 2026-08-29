#!/bin/bash
# PreToolUse PR Ownership Guard Hook (OMN-16485)
#
# Refuses a destructive GitHub mutation when this lane cannot prove it owns the
# target. Every lane on this host shares ONE `gh` identity, so GitHub records
# the same actor for all of them and per-command attribution is INDETERMINATE.
# Between 2026-08-21 and 2026-08-24, >=5 PRs were closed unmerged under that
# shared identity, including omniclaude#2019 (authored by andywu42, closed as
# jonahgabriel). A duplicate concurrent workflow_dispatch fired ~19s after a
# peer lane's on 2026-08-20T00:52Z for the same reason: neither lane could see
# the other.
#
# Guarded verbs and their verdicts (full table in pr_ownership_guard.py):
#   gh pr close | gh pr reopen | gh api -X PATCH .../pulls/<n> state=closed
#       -> ownership class, FAIL-CLOSED. Absent/expired/unreadable/lane-less
#          claim refuses. "Unclaimed" is never read as "free to take."
#   gh workflow run | gh run cancel
#       -> exclusivity class, first-writer-wins. An active peer claim refuses;
#          otherwise the claim is recorded so the racing peer refuses.
#
# Read-only verbs (gh pr view/list/checks, gh run view/list/watch, and a
# `gh api` call with no mutating method) are never refused. Two layers make
# that true, and only the second is authoritative:
#   * this script's grep pre-filter is a cheap over-matcher — it fires on a
#     bare `gh api` regardless of HTTP method, and on quoted text that merely
#     names a verb (`printf 'gh api ...'`). It decides nothing.
#   * pr_ownership_guard.py parses the command and is the authority. It treats
#     a `gh api` with no `-X/--method PATCH|POST|PUT|DELETE` as no mutation at
#     all and returns ALLOW before touching any ownership surface, and it does
#     not read quoted text as a command (OMN-16983).
#
# Fail-open / fail-closed boundary, stated deliberately:
#   * A command containing no guarded verb never invokes Python at all — a bug
#     in this guard cannot brick unrelated Bash traffic.
#   * A command the PARSER resolves to a genuine mutation, whose evaluation
#     then errors, is BLOCKED, not allowed. Ownership that cannot be
#     established fails closed.
#   * A command that only trips the grep pre-filter is NOT in that category:
#     the parser finds no mutation and the guard allows it. Before OMN-16983
#     the two were conflated, and an ImportError in the decision core refused
#     every `gh api` read on the host.
#
# Gating: the BASH_GUARD bit. A dedicated bit would require a new EnumHookBit
# member in omnibase_core plus a regenerated hook_bits.sh (cross-repo release
# chain), and all 60 default-mask bits are already allocated. BASH_GUARD is the
# faithful home: pre_tool_use_bash_guard.sh is unregistered under the OMN-13244
# baseline and its own header records that `gh pr merge` blocking was
# historically part of its scope.
#   Disable with: onex hooks disable BASH_GUARD
#
# Registration follows the OMN-14330 worktree-guard carve-out precedent.

set -euo pipefail

_OMNICLAUDE_CALLER_CWD="${CLAUDE_PROJECT_DIR:-$PWD}"
# shellcheck source=../lib/repo_guard.sh
. "$(dirname "${BASH_SOURCE[0]}")/../lib/repo_guard.sh" 2>/dev/null || true
if declare -F is_omninode_repo >/dev/null 2>&1; then
    CLAUDE_PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$_OMNICLAUDE_CALLER_CWD}" \
        is_omninode_repo || {
        _OMNICLAUDE_PASSTHROUGH=$(cat)
        echo "$_OMNICLAUDE_PASSTHROUGH"
        trap - EXIT 2>/dev/null || true
        exit 0
    }
fi
source "$(dirname "${BASH_SOURCE[0]}")/error-guard.sh" 2>/dev/null || true
HOOK_ORIGINAL_CWD="$(pwd -P 2>/dev/null || pwd)"

# Resolve this script's own location BEFORE changing directory. BASH_SOURCE[0]
# may be relative, so resolving it after a `cd` yields a path under the wrong
# tree (observed while testing: it resolved into an unrelated worktree).
_SELF="$(realpath "${BASH_SOURCE[0]}" 2>/dev/null \
    || python3 -c "import os,sys; print(os.path.realpath(sys.argv[1]))" "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(cd "$(dirname "${_SELF}")" && pwd)"
PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "${SCRIPT_DIR}/../.." && pwd)}"
unset _SELF
HOOKS_DIR="${PLUGIN_ROOT}/hooks"

# Stable CWD before any Python invocation: the session CWD may live on an
# external volume that disconnects, and CPython's <frozen getpath> aborts at
# startup when os.getcwd() fails.
cd "$HOME" 2>/dev/null || cd /tmp || true
source "$(dirname "${BASH_SOURCE[0]}")/onex-paths.sh" 2>/dev/null || true
LOG_FILE="${ONEX_HOOK_LOG:-${HOME}/.claude/onex-hooks.log}"
mkdir -p "$(dirname "$LOG_FILE")"

source "${HOOKS_DIR}/scripts/common.sh"
onex_hook_gate BASH_GUARD || exit 0

_log() {
    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] pr-ownership-guard: $*" >> "$LOG_FILE"
}

_block() {
    _hook_status "BLOCKED" "$1" "0" 2>/dev/null || true
    jq -n --arg reason "$2" '{"decision": "block", "reason": $reason}'
    trap - EXIT
    exit 2
}

TOOL_INFO=$(cat)
if ! TOOL_NAME=$(echo "$TOOL_INFO" | jq -er '.tool_name // empty' 2>>"$LOG_FILE"); then
    _log "ERROR: invalid hook JSON; passing through"
    echo "$TOOL_INFO"
    exit 0
fi

if [[ "$TOOL_NAME" != "Bash" ]]; then
    _hook_status "PASS" "not Bash ($TOOL_NAME)" "0" 2>/dev/null || true
    echo "$TOOL_INFO"
    exit 0
fi

CMD=$(echo "$TOOL_INFO" | jq -er '.tool_input.command // empty' 2>/dev/null || true)

# Cheap pre-filter: only pay for Python when a guarded verb could be present.
# Deliberately over-matches (it ignores quoting); the Python parser is the
# authority on whether a match is a real command.
if ! printf '%s' "$CMD" | grep -qE 'gh[[:space:]]+(pr[[:space:]]+(close|reopen)|run[[:space:]]+cancel|workflow[[:space:]]+run|api)'; then
    _hook_status "PASS" "no guarded gh mutation verb" "0" 2>/dev/null || true
    echo "$TOOL_INFO"
    exit 0
fi

_log "candidate mutation verb detected; evaluating ownership"

# Repository implied by the caller's cwd, used only when --repo is omitted.
DEFAULT_REPO="$(git -C "$HOOK_ORIGINAL_CWD" remote get-url origin 2>/dev/null || true)"

CMD_FILE="$(mktemp -t onex-pr-ownership.XXXXXX)"
cleanup() { rm -f "$CMD_FILE"; }
trap cleanup EXIT
printf '%s' "$CMD" > "$CMD_FILE"

GUARD_PY="${PLUGIN_ROOT}/hooks/lib/pr_ownership_guard.py"
if [[ ! -f "$GUARD_PY" ]]; then
    _log "ERROR: guard module missing at $GUARD_PY — failing closed"
    _block "guard module missing" \
        "BLOCKED: the OMN-16485 lane-ownership guard module is missing at ${GUARD_PY}, so ownership of this GitHub mutation cannot be checked. Unverifiable ownership fails closed. Repair the plugin install, or disable the guard deliberately: onex hooks disable BASH_GUARD"
fi

# OMN-16983: run the decision core as a plain script from its own directory.
# The previous form did `cd "$PLUGIN_ROOT/../.."` with a matching PYTHONPATH so
# the module could `import plugins.onex.hooks.lib.*` — an assumption that only
# holds in the SOURCE tree (<omniclaude>/plugins/onex). Claude Code loads hooks
# from the plugin CACHE (~/.claude/plugins/cache/<mp>/onex/<ver>), where `../..`
# is the marketplace dir and no `plugins` package exists: the import raised
# ModuleNotFoundError, the core exited 1, and the fail-closed branch below
# refused every matching command — read-only `gh api` GETs included. The core
# now resolves its siblings from its own lib/ directory, so no PYTHONPATH or cwd
# contract is needed. PYTHONPATH is cleared so an ambient value cannot shadow a
# sibling module with a same-named one from another tree.
set +e
GUARD_OUT=$(cd "$PLUGIN_ROOT" 2>/dev/null || cd "$HOME"; \
    env -u PYTHONPATH "${PYTHON_CMD:-python3}" "$GUARD_PY" \
    --command-file "$CMD_FILE" \
    --cwd "$HOOK_ORIGINAL_CWD" \
    --default-repo "$DEFAULT_REPO" 2>&1)
GUARD_RC=$?
set -e

if [[ $GUARD_RC -eq 3 ]]; then
    REASON=$(printf '%s' "$GUARD_OUT" | jq -r '.reason // empty' 2>/dev/null || true)
    [[ -z "$REASON" ]] && REASON="BLOCKED: cross-lane GitHub mutation refused (OMN-16485)."
    _log "BLOCKED: $(printf '%s' "$GUARD_OUT" | jq -c '[.decisions[]?|select(.allowed==false)|.reason_code]' 2>/dev/null || echo '?')"
    _block "cross-lane or unattributable gh mutation" "$REASON"
fi

if [[ $GUARD_RC -ne 0 ]]; then
    # A guarded verb IS present and evaluation failed — fail closed.
    _log "ERROR rc=$GUARD_RC out=$(printf '%s' "$GUARD_OUT" | head -c 400)"
    _block "ownership evaluation failed" \
        "BLOCKED: the OMN-16485 lane-ownership guard could not evaluate this GitHub mutation (exit ${GUARD_RC}). Ownership that cannot be established fails closed — it is never assumed. Detail: $(printf '%s' "$GUARD_OUT" | head -c 400)"
fi

_log "ALLOWED: $(printf '%s' "$GUARD_OUT" | jq -c '[.decisions[]?|.reason_code]' 2>/dev/null || echo 'ok')"
_hook_status "PASS" "lane ownership verified" "0" 2>/dev/null || true
echo "$TOOL_INFO"
exit 0
