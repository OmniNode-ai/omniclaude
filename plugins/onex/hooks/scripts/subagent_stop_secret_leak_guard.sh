#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# SubagentStop — secret-leak guard [OMN-15062].
#
# Reads the SubagentStop stdin JSON, extracts the final assistant message,
# runs plugins/onex/hooks/lib/subagent_secret_leak_guard.py against it, and
# emits a Claude Code hookSpecificOutput envelope.
#
# Block condition (decision=block):
#   - The subagent's final message matches a known secret pattern
#     (secret_redactor.py SECRET_PATTERNS) — forces the subagent to redact
#     and finish again before the report propagates further.
#
# Fail-SAFE condition (decision=block, NOT allow — deliberate divergence
# from this repo's usual fail-open hook posture; see module docstring in
# subagent_secret_leak_guard.py "Fail-safe posture"):
#   - The redaction module itself is unavailable/unimportable, or the scan
#     crashes on text we did extract. We cannot prove the text is clean, so
#     we do not let it through.
#
# Fail-open condition (decision=allow):
#   - No final message could be extracted at all (nothing to scan).
#
# Refs: OMN-15062.

set -eo pipefail

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

_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_ROOT="$(cd "${_SCRIPT_DIR}/../.." && pwd)"
PROJECT_ROOT="$(cd "${PLUGIN_ROOT}/../.." 2>/dev/null && pwd || echo "")"
export PLUGIN_ROOT PROJECT_ROOT

# shellcheck source=/dev/null
source "${PLUGIN_ROOT}/hooks/scripts/onex-paths.sh"
LOG_FILE="${ONEX_HOOK_LOG}"
mkdir -p "$(dirname "${LOG_FILE}")" 2>/dev/null || true
export LOG_FILE

# Lite mode: common.sh resolves a Python interpreter and hard-fails with an
# actionable error when none is available.
# shellcheck source=/dev/null
source "${PLUGIN_ROOT}/hooks/scripts/common.sh"

STDIN_JSON="$(cat || true)"

# Fail-SAFE envelope (decision=block, not allow) when the guard module
# itself can't run. This intentionally inverts the fail-open pattern used
# by every other hook in this repo — see the rationale in
# subagent_secret_leak_guard.py's module docstring.
_fail_safe_block() {
    local reason="$1"
    printf '{"hookSpecificOutput":{"hookEventName":"SubagentStop","decision":"block","additionalContext":"SubagentStop secret-leak guard degraded (%s) — cannot prove the final message is clean, blocking rather than passing through unredacted. Retry."}}\n' "$reason"
    exit 2
}

# No further pre-check here: the guard module (subagent_secret_leak_guard.py)
# depends only on the Python stdlib plus its sibling lib modules, and
# common.sh above already hard-fails before this point if no interpreter is
# available at all (CLAUDE.md "Fail-Fast Design"). Any remaining runtime
# failure is caught by the rc handling below and routed to _fail_safe_block.
set +e
OUTPUT="$(printf '%s' "${STDIN_JSON}" | "${PYTHON_CMD}" "${PLUGIN_ROOT}/hooks/lib/subagent_secret_leak_guard.py" 2>>"${LOG_FILE}")"
rc=$?
set -e

# Belt-and-suspenders: an interpreter-level failure (e.g. the script file
# missing) can coincidentally exit with the SAME code we use for a real
# "block" decision, while printing nothing to stdout. Don't trust rc alone
# — a rc=0/2 with empty/non-JSON stdout is a crash we failed to catch, not
# a verdict, and must route through the fail-safe path rather than being
# echoed as-is (which for rc=2 would emit blank/invalid hookSpecificOutput,
# and for rc=0 would silently ALLOW on a crash we didn't detect).
if [[ -z "${OUTPUT}" || "${OUTPUT}" != '{'* ]]; then
    log "subagent_stop_secret_leak_guard: empty/invalid guard output (rc=${rc})"
    _fail_safe_block "guard_output_empty_or_invalid_rc_${rc}"
fi

case "${rc}" in
    0)
        printf '%s\n' "${OUTPUT}"
        exit 0
        ;;
    2)
        printf '%s\n' "${OUTPUT}"
        exit 2
        ;;
    *)
        log "subagent_stop_secret_leak_guard: python exited rc=${rc}"
        _fail_safe_block "guard_crash_rc_${rc}"
        ;;
esac
