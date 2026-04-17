#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# Stop hook — Session bootstrap completeness gate [OMN-8845]
# and org-wide backlog completeness gate [OMN-9054 plan Task 5].
#
# Blocks session end (exit 2) when:
#   Bootstrap gate: the 3 mandatory crons from CLAUDE.md §Session Bootstrap
#                   have not been created (flag-file check).
#   Block B:        >5 BLOCKED PRs are open AND no in-flight fixer-agent
#                   dispatch claims exist — ends-with-wedged-backlog guard,
#                   retro §4.6 ("TodoWrite list ignored for entire session").
#
# Block A (TODO pending-items) lives in follow-up OMN-9059 — runtime does not
# currently expose TODO state to Stop hooks (state-source discovery, plan Task 5 Step 2a).
#
# Bypass:
#   STOP_GUARD_ACK=1  Explicit operator override for intentional early stop.
#
# Exit codes:
#   0 — all gates pass (or bypass set); session may end
#   2 — one or more gates blocked stop

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

# Explicit operator bypass — must come BEFORE any gate check.
if [[ "${STOP_GUARD_ACK:-0}" == "1" ]]; then
    echo "$STOP_INFO"
    exit 0
fi

if [[ -z "${ONEX_STATE_DIR:-}" ]]; then
    # Cannot check — pass through to avoid blocking on infra failure
    echo "$STOP_INFO"
    exit 0
fi

# ---- Bootstrap flag gate (OMN-8845) ----
BOOTSTRAP_FLAG="${ONEX_STATE_DIR}/session/cron_bootstrap.flag"

if [[ ! -f "$BOOTSTRAP_FLAG" ]]; then
    echo "BLOCKED: Session bootstrap incomplete. Create the 3 mandatory crons from CLAUDE.md §Session Bootstrap before ending the session." >&2
    echo "  1. */15 * * * * — Overseer tick" >&2
    echo "  2. 23 * * * * — Merge sweep" >&2
    echo "  3. 3 * * * * — .201 health check" >&2
    exit 2
fi

# ---- Block B: backlog + no-fixer gate (OMN-9054) ----
# Count open BLOCKED PRs via gh; if gh is missing or fails, treat as zero
# (infra failure tolerance — hooks never block the UI on tooling outages).
BLOCKED_PR_COUNT=0
if command -v gh >/dev/null 2>&1; then
    BLOCKED_JSON="$(gh pr list --state open --search "is:blocked" --json number 2>/dev/null || echo '[]')"
    BLOCKED_PR_COUNT="$(echo "$BLOCKED_JSON" | jq 'length' 2>/dev/null || echo 0)"
fi

# Count active fixer-agent claims — any file under dispatch_claims/ is a live claim.
CLAIMS_DIR="${ONEX_STATE_DIR}/dispatch_claims"
ACTIVE_FIXERS=0
if [[ -d "$CLAIMS_DIR" ]]; then
    ACTIVE_FIXERS=$(find "$CLAIMS_DIR" -maxdepth 1 -type f 2>/dev/null | wc -l | tr -d ' ')
fi

if [[ "$BLOCKED_PR_COUNT" -gt 5 ]] && [[ "$ACTIVE_FIXERS" -eq 0 ]]; then
    echo "BLOCKED: ${BLOCKED_PR_COUNT} PRs BLOCKED with no fixer agents running. Dispatch workers or set STOP_GUARD_ACK=1 to authorize session-end." >&2
    echo "  See: $CLAIMS_DIR (expected >=1 active claim file)" >&2
    echo "  See: gh pr list --state open --search 'is:blocked'" >&2
    exit 2
fi

echo "$STOP_INFO"
exit 0
