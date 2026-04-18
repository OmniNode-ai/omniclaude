#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# SubagentStop — Agent-claim verification gate [OMN-9086].
#
# Reads the SubagentStop stdin JSON, extracts the final assistant message,
# runs plugins/onex/hooks/lib/subagent_claim_verifier.py against it, and
# emits a Claude Code hookSpecificOutput envelope per OMN-9072.
#
# Block conditions (decision=block):
#   - No json-report fence in the final assistant message
#   - Malformed JSON or schema failure inside the fence
#   - kind=pr_ship with PR state mismatch or PR not found on GitHub
#   - Linear ticket state mismatch vs the claimed state
#
# Fail-open conditions (decision=allow with friction in additionalContext):
#   - gh not installed or rate-limited
#   - Linear auth failure or endpoint unreachable (Task 8 semantics)
#
# Refs:
#   - Plan: docs/plans/2026-04-17-unused-hooks-applications.md Task 2
#   - OMN-9063 ModelWorkerReport schema (fallback until canonical lands)
#   - OMN-9055 node_evidence_bundle.resolve() integration (inline probes
#     until resolver lands; TODO in the lib)
#   - OMN-9072 hookSpecificOutput.hookEventName requirement

set -eo pipefail

_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_ROOT="$(cd "${_SCRIPT_DIR}/../.." && pwd)"
PROJECT_ROOT="$(cd "${PLUGIN_ROOT}/../.." 2>/dev/null && pwd || echo "")"
export PLUGIN_ROOT PROJECT_ROOT

# shellcheck source=/dev/null
source "${PLUGIN_ROOT}/hooks/scripts/onex-paths.sh"
LOG_FILE="${ONEX_HOOK_LOG}"
mkdir -p "$(dirname "${LOG_FILE}")" 2>/dev/null || true
export LOG_FILE

# Lite mode: hooks may run without the repo venv; common.sh handles Python
# resolution and hard-fails with actionable errors when no interpreter is
# available.
# shellcheck source=/dev/null
source "${PLUGIN_ROOT}/hooks/scripts/common.sh"

STDIN_JSON="$(cat || true)"

# Fail-open envelope when the verifier module isn't importable (e.g. degraded
# install). We still emit a structured hookSpecificOutput so OMN-9072
# validation passes; additionalContext records why we punted.
_fail_open_allow() {
    local reason="$1"
    printf '{"hookSpecificOutput":{"hookEventName":"SubagentStop","decision":"allow","additionalContext":"SubagentStop verifier degraded: %s"}}\n' "$reason"
    exit 0
}

if ! "${PYTHON_CMD}" -c "import importlib.util, sys; sys.exit(0 if importlib.util.find_spec('pydantic') else 1)" 2>/dev/null; then
    _fail_open_allow "pydantic_unavailable"
fi

# Hand stdin to the Python CLI. Exit 2 signals block; 0 signals allow.
# Disable errexit across the call so we can capture the real return code;
# `set -e` plus `$(...)` otherwise masks non-zero exits into the outer shell.
set +e
OUTPUT="$(printf '%s' "${STDIN_JSON}" | "${PYTHON_CMD}" "${PLUGIN_ROOT}/hooks/lib/subagent_claim_verifier.py" 2>>"${LOG_FILE}")"
rc=$?
set -e

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
        log "subagent_stop_claim_verifier: python exited rc=${rc}"
        _fail_open_allow "verifier_crash_rc_${rc}"
        ;;
esac
