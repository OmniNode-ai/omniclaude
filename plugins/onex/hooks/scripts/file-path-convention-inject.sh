#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# file-path-convention-inject.sh
# PreToolUse hook: injects domain conventions based on file path [OMN-6157]
#
# Patterson-style routing — reads the file_path from tool_input, resolves
# repo-relative path, matches against routes.yaml, and prints matched
# convention snippets to stdout for context injection.
#
# Exit codes:
#   0 — always (informational injection, never blocks)

set -eo pipefail

PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$0")/../.." && pwd)}"
HOOKS_DIR="${PLUGIN_ROOT}/hooks"

TOOL_INPUT=$(cat)
FILE_PATH=$(echo "$TOOL_INPUT" | jq -r '.tool_input.file_path // empty')

if [[ -z "$FILE_PATH" ]]; then
    exit 0
fi

CONVENTIONS=$(python3 "${HOOKS_DIR}/lib/file_path_router.py" "$FILE_PATH" 2>/dev/null)

if [[ -n "$CONVENTIONS" ]]; then
    echo "$CONVENTIONS"
fi
exit 0
