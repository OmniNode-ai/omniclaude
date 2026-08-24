#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# onex-lane-reconcile — agent-lane reconciliation gate [OMN-16471].
#
# Reconciles the durable lane records written at the dispatch seam
# (pre_tool_use_lane_open.sh) and the termination seam
# (subagent_stop_lane_termination_guard.sh).
#
# EXIT 1 when any lane holds a failure terminal state — an observed death,
# or a dispatched lane whose TTL elapsed with no terminal record at all.
# EXIT 0 only when every lane reconciles as completed.
#
# The failing exit code is the whole point: friction F-09's corrective
# action is "treat the absence of a terminal record as a failure, not a
# pending", and per CLAUDE.md rule 5 a check that cannot fail a caller is
# advisory and gets ignored. Call this from a closeout, an overseer tick,
# or a workflow tail.
#
# Usage:
#   onex-lane-reconcile.sh                  # human summary
#   onex-lane-reconcile.sh --json           # machine-readable verdict
#   onex-lane-reconcile.sh --ttl-seconds 900
#   onex-lane-reconcile.sh --prune          # drop reconciled records
#
# Refs: OMN-16471; friction F-09.

set -euo pipefail

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

exec "${PYTHON_CMD}" "${PLUGIN_ROOT}/hooks/lib/lane_reconcile.py" "$@"
