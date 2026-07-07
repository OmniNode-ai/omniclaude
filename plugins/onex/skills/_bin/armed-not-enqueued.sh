#!/bin/bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Armed-not-enqueued detector (<TICKET>)
# Flags PRs where autoMergeRequest != null AND mergeStateStatus CLEAN AND
# no ADDED_TO_MERGE_QUEUE_EVENT newer than the arming timestamp, sustained >30min.
#
# Usage:
#   armed-not-enqueued.sh [--repos <comma-separated-repos>] [--threshold-minutes 30] [--format summary|json]
#
# Defaults to scanning all queue repos:
#   OmniNode-ai/omniclaude,OmniNode-ai/omnibase_core,OmniNode-ai/omnibase_infra,
#   OmniNode-ai/omnibase_compat,OmniNode-ai/omnidash,OmniNode-ai/omnimarket

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/_common.sh"

# This script uses a custom argument layout (--repos plural, --threshold-minutes)
# rather than the standard --repo singular. Invoke the module directly.
PYTHONPATH="${BIN_DIR}:${PYTHONPATH:-}" exec "${PYTHON_CMD}" \
    -m "_lib.run_armed_not_enqueued" "$@"
