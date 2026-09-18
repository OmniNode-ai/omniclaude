#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# onex-lane-pair-reconcile — one-shot repair for agent-id-mangled lane
# pairs [OMN-18690].
#
# Before OMN-18690 the SubagentStop guard closed a lane under the harness's
# agent id (`a` + lane name + `-` + 16 hex) rather than its dispatch-time
# name, so each death was written to a synthetic `unattributed-*` record
# while the real dispatch record aged into died_no_terminal — one lane
# reported as two failures, neither carrying its tickets.
#
# This pairs the records already on disk and closes each pair by APPENDING
# a resolution line to the journal that `onex-lane-reconcile` reads as an
# overlay. It NEVER edits a lane record: they are governed evidence, and a
# repair that rewrote them would be indistinguishable from the corruption.
#
# DRY RUN BY DEFAULT. Pass --execute to append.
#
# Usage:
#   onex-lane-pair-reconcile.sh              # dry run, prints the pair count
#   onex-lane-pair-reconcile.sh --json
#   onex-lane-pair-reconcile.sh --execute
#
# Refs: OMN-18690; parent OMN-18130; OMN-16471.

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

exec "${PYTHON_CMD}" "${PLUGIN_ROOT}/hooks/lib/lane_pair_reconcile.py" "$@"
