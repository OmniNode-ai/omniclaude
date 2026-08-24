#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# PreToolUse (Task|Agent|Workflow) — lane dispatch recorder [OMN-16471].
#
# Writes a durable OPEN record for every dispatched agent lane, so a lane
# that later dies before reaching SubagentStop is still visible. Without a
# dispatch record, absence of output is indistinguishable from absence of
# dispatch — which is precisely how friction F-09's zero-token deaths were
# read as completed stages.
#
# This is an OBSERVER, never a gate:
#   - it always exits 0, so it can never refuse or delay a dispatch;
#   - it always emits nothing on stdout, because PreToolUse stdout is
#     injected as context into the launching turn, and paying that cost on
#     every lane launch is not worth a bookkeeping message.
#
# The paired terminal record is written by
# subagent_stop_lane_termination_guard.sh; `onex-lane-reconcile` fails on
# any lane that has the first record and not the second.
#
# Refs: OMN-16471; friction F-09.

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
printf '%s' "${STDIN_JSON}" \
    | "${PYTHON_CMD}" "${PLUGIN_ROOT}/hooks/lib/lane_registry.py" \
        >/dev/null 2>>"${LOG_FILE}"
rc=$?
set -e

if [[ "${rc}" -ne 0 ]]; then
    log "pre_tool_use_lane_open: recorder exited rc=${rc}, dispatch unaffected"
fi

exit 0
