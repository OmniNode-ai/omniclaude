#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# UserPromptSubmit hook — Session cron bootstrap reminder injection [OMN-8845].
#
# If the 3 mandatory crons from CLAUDE.md §Session Bootstrap have NOT yet been
# created in this session, injects a [MANDATORY] warning into additionalContext
# so Claude is reminded before responding to any user prompt.
#
# Exit codes:
#   0 — always (hooks must never block on missing crons; only advise)

set -eo pipefail

# Lite mode guard [OMN-5398]
_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
_MODE_SH="${_SCRIPT_DIR}/../../lib/mode.sh"
if [[ -f "$_MODE_SH" ]]; then
    source "$_MODE_SH"
    [[ "$(omniclaude_mode)" == "lite" ]] && exit 0
fi
unset _SCRIPT_DIR _MODE_SH

# Consume stdin
PROMPT_INFO="$(cat)"

if [[ -z "${ONEX_STATE_DIR:-}" ]]; then
    # No state dir — pass through silently
    exit 0
fi

BOOTSTRAP_FLAG="${ONEX_STATE_DIR}/session/cron_bootstrap.flag"

if [[ -f "$BOOTSTRAP_FLAG" ]]; then
    # Bootstrap complete — no injection needed
    exit 0
fi

# Inject the mandatory warning into additionalContext
INJECTION="[MANDATORY] Session cron bootstrap not complete. Create the 3 required crons from CLAUDE.md §Session Bootstrap before responding to the user's prompt: (1) */15 * * * * Overseer tick, (2) 23 * * * * Merge sweep, (3) 3 * * * * .201 health check."

# Output JSON with hookSpecificOutput.additionalContext per Claude Code hook protocol
if command -v jq >/dev/null 2>&1; then
    jq -n --arg ctx "$INJECTION" \
        '{"hookSpecificOutput": {"additionalContext": $ctx}}'
else
    # Fallback: minimal JSON without jq
    printf '{"hookSpecificOutput": {"additionalContext": "%s"}}\n' \
        "$(echo "$INJECTION" | sed 's/"/\\"/g')"
fi

exit 0
