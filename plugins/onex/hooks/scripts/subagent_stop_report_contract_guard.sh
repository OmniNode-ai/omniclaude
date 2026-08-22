#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# SubagentStop — golden-chain report-contract guard [OMN-15213].
#
# Reads the SubagentStop stdin JSON, extracts the final assistant message,
# runs plugins/onex/hooks/lib/subagent_report_contract_guard.py against it,
# and emits a Claude Code blocking envelope when the return matches the
# clobber signature.
#
# Block condition (decision=block, exit 2):
#   - The subagent's final return is bare-Done-class: a bare completion
#     phrase, an echo of the end-of-turn hook notification, or a return
#     that cites no concrete evidence (file paths, ticket/PR ids,
#     commands+output, explicit verdict). Forces the agent to re-emit the
#     real report instead of the acknowledgement that clobbered it.
#
# Silent-pass condition (NO stdout at all, exit 0):
#   - A contract-satisfying or schema-bound return, or nothing extractable.
#     Emitting anything on the pass path would make THIS hook the
#     end-of-turn notification agents reply to — the exact mechanism
#     OMN-15213 exists to remove. Do not add a "clean" message here.
#
# Fail-OPEN condition (silent exit 0):
#   - The guard module itself cannot run. This is a report-quality gate,
#     not a security control: unlike the sibling OMN-15062 secret-leak
#     guard, a degraded checker here must not block every subagent turn
#     across every repo. The failure is logged to $ONEX_HOOK_LOG.
#
# Refs: OMN-15213.

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

# shellcheck source=/dev/null
source "${PLUGIN_ROOT}/hooks/scripts/common.sh"

STDIN_JSON="$(cat || true)"

set +e
OUTPUT="$(printf '%s' "${STDIN_JSON}" | "${PYTHON_CMD}" "${PLUGIN_ROOT}/hooks/lib/subagent_report_contract_guard.py" 2>>"${LOG_FILE}")"
rc=$?
set -e

case "${rc}" in
    0)
        # Silent pass. Deliberately no stdout — see the header.
        exit 0
        ;;
    2)
        # A rc=2 with empty/non-JSON stdout is an interpreter-level crash
        # that happens to share our block exit code, not a verdict. Fail
        # open rather than emitting a blank/invalid blocking envelope.
        if [[ -z "${OUTPUT}" || "${OUTPUT}" != '{'* ]]; then
            log "subagent_stop_report_contract_guard: empty/invalid guard output (rc=2), failing open"
            exit 0
        fi
        printf '%s\n' "${OUTPUT}"
        exit 2
        ;;
    *)
        log "subagent_stop_report_contract_guard: python exited rc=${rc}, failing open"
        exit 0
        ;;
esac
