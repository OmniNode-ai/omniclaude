#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# Stop hook — Session bootstrap completeness gate [OMN-8845].
#
# Blocks session end (exit 2) if the 3 mandatory crons from CLAUDE.md
# §Session Bootstrap have not been created in this session.
# See: post_tool_use_cron_action_guard.sh for flag creation.
#
# Exit codes:
#   0 — bootstrap flag present; session may end
#   2 — bootstrap flag absent; blocks stop with BLOCKED message

set -eo pipefail

# Lite mode guard [OMN-5398]
_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
_MODE_SH="${_SCRIPT_DIR}/../../lib/mode.sh"
if [[ -f "$_MODE_SH" ]]; then
    source "$_MODE_SH"
    if [[ "$(omniclaude_mode)" == "lite" ]]; then
        cat > /dev/null
        exit 0
    fi
fi
unset _SCRIPT_DIR _MODE_SH

# Consume stdin (Stop hook passes session JSON via stdin)
STOP_INFO="$(cat)"

if [[ -z "${ONEX_STATE_DIR:-}" ]]; then
    # Cannot check — pass through to avoid blocking on infra failure
    echo "$STOP_INFO"
    exit 0
fi

BOOTSTRAP_FLAG="${ONEX_STATE_DIR}/session/cron_bootstrap.flag"

if [[ ! -f "$BOOTSTRAP_FLAG" ]]; then
    echo "BLOCKED: Session bootstrap incomplete. Create the 3 mandatory crons from CLAUDE.md §Session Bootstrap before ending the session." >&2
    echo "  1. */15 * * * * — Overseer tick" >&2
    echo "  2. 23 * * * * — Merge sweep" >&2
    echo "  3. 3 * * * * — .201 health check" >&2
    exit 2
fi

echo "$STOP_INFO"
exit 0
