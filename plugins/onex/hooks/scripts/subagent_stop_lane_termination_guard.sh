#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# SubagentStop — lane-termination guard [OMN-16471].
#
# Reads the SubagentStop stdin JSON, classifies HOW the lane ended from
# transcript evidence (tool-call count, wall duration, death signatures),
# writes a durable terminal lane record, and surfaces a failure so a death
# is never scored as a completed stage.
#
# The defect this closes (friction F-09): workflow wf_49e3ed80-aab's
# `verify-build-drive` lane terminated at 0 tokens / 0 tool calls / 285ms —
# the mandated adversarial verify of a 2.47M-token, 7-agent build drive
# never ran, and the workflow reported the stage as complete. A lane that
# dies produces the same shape as one that finished: silence.
#
# Block condition (decision=block, exit 2):
#   - DIED_ZERO_WORK — sub-threshold duration AND zero tool calls. Blocking
#     forces one continuation turn, which for a lane that did nothing is a
#     free retry. Bounded to a single attempt via `stop_hook_active`.
#
# Surface-but-allow condition (stdout JSON, exit 0):
#   - Every other death class (usage limit, auth failure, API error, an
#     unresumable agent id). The lane is already gone, so blocking cannot
#     help; the durable record plus additionalContext is the signal.
#
# Silent-pass condition (NO stdout at all, exit 0):
#   - COMPLETED. Emitting on the pass path would make THIS hook the
#     end-of-turn notification agents reply to — the exact mechanism
#     OMN-15213 exists to remove. Do not add a "clean" message here.
#
# Fail-OPEN condition (silent exit 0):
#   - The guard module itself cannot run. This is an accounting gate, not a
#     security control: a degraded checker must not block every subagent
#     turn across every repo. The failure is logged to $ONEX_HOOK_LOG.
#
# Refs: OMN-16471. Siblings: OMN-15213 (report contract), OMN-15062 (secret leak).

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
OUTPUT="$(printf '%s' "${STDIN_JSON}" | "${PYTHON_CMD}" "${PLUGIN_ROOT}/hooks/lib/lane_termination_guard.py" 2>>"${LOG_FILE}")"
rc=$?
set -e

case "${rc}" in
    0)
        # COMPLETED emits nothing; a non-blocking death emits its record
        # envelope. Forward only real JSON.
        if [[ -n "${OUTPUT}" && "${OUTPUT}" == '{'* ]]; then
            printf '%s\n' "${OUTPUT}"
        fi
        exit 0
        ;;
    2)
        # A rc=2 with empty/non-JSON stdout is an interpreter-level crash that
        # happens to share our block exit code, not a verdict. Fail open rather
        # than emitting a blank/invalid blocking envelope.
        if [[ -z "${OUTPUT}" || "${OUTPUT}" != '{'* ]]; then
            log "subagent_stop_lane_termination_guard: empty/invalid guard output (rc=2), failing open"
            exit 0
        fi
        printf '%s\n' "${OUTPUT}"
        exit 2
        ;;
    *)
        log "subagent_stop_lane_termination_guard: python exited rc=${rc}, failing open"
        exit 0
        ;;
esac
