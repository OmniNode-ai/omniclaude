#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# SubagentStop wrapper for the shared skip-token surface guard.

set -eo pipefail

: "${CLAUDE_PLUGIN_ROOT:?CLAUDE_PLUGIN_ROOT must be set}"

export OMNICLAUDE_SKIP_TOKEN_HOOK_EVENT="SubagentStop"
exec "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/skip_token_surface_guard.sh"
