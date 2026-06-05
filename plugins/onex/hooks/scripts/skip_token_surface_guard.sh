#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# Stop/SubagentStop guard for unauthorized agent-surfaced [skip-*] bypass tokens.

set -eo pipefail

_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "${_SCRIPT_DIR}/../.." && pwd)}"
PROJECT_ROOT="${CLAUDE_PROJECT_DIR:-$(cd "${PLUGIN_ROOT}/../.." 2>/dev/null && pwd || pwd)}"
HOOKS_DIR="${PLUGIN_ROOT}/hooks"
export PLUGIN_ROOT PROJECT_ROOT HOOKS_DIR

# shellcheck source=/dev/null
source "${HOOKS_DIR}/scripts/common.sh"

HOOK_EVENT_NAME="${OMNICLAUDE_SKIP_TOKEN_HOOK_EVENT:-Stop}"
STDIN_JSON="$(cat || true)"

set +e
OUTPUT="$(printf '%s' "${STDIN_JSON}" | "${PYTHON_CMD}" "${PLUGIN_ROOT}/hooks/lib/skip_token_surface_guard.py" \
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
