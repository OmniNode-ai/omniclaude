#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# Stop/SubagentStop guard for unauthorized agent-surfaced [skip-*] bypass tokens.

set -eo pipefail

: "${CLAUDE_PLUGIN_ROOT:?CLAUDE_PLUGIN_ROOT must be set}"
: "${CLAUDE_PROJECT_DIR:?CLAUDE_PROJECT_DIR must be set}"

SKIP_TOKEN_PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT}"
SKIP_TOKEN_PROJECT_ROOT="${CLAUDE_PROJECT_DIR}"

PLUGIN_ROOT="${SKIP_TOKEN_PLUGIN_ROOT}"
PROJECT_ROOT="${SKIP_TOKEN_PROJECT_ROOT}"
HOOKS_DIR="${SKIP_TOKEN_PLUGIN_ROOT}/hooks"
export PLUGIN_ROOT PROJECT_ROOT HOOKS_DIR

# shellcheck source=/dev/null
source "${SKIP_TOKEN_PLUGIN_ROOT}/hooks/scripts/common.sh"

HOOK_EVENT_NAME="${OMNICLAUDE_SKIP_TOKEN_HOOK_EVENT:-Stop}"
STDIN_JSON="$(cat || true)"

set +e
OUTPUT="$(printf '%s' "${STDIN_JSON}" | "${PYTHON_CMD}" "${SKIP_TOKEN_PLUGIN_ROOT}/hooks/lib/skip_token_surface_guard.py" \
    --hook-event "${HOOK_EVENT_NAME}" \
    --scan-session-evidence \
    2>/dev/null)"
rc=$?
set -e

case "${rc}" in
    0)
        exit 0
        ;;
    2)
        printf '%s\n' "${OUTPUT}"
        exit 2
        ;;
    *)
        echo "skip_token_surface_guard: scanner degraded rc=${rc}; allowing ${HOOK_EVENT_NAME} surface" >&2
        exit 0
        ;;
esac
