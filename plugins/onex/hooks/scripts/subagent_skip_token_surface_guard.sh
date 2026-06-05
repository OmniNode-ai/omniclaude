#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# SubagentStop wrapper for the shared skip-token surface guard.

set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export OMNICLAUDE_SKIP_TOKEN_HOOK_EVENT="SubagentStop"
exec "${SCRIPT_DIR}/skip_token_surface_guard.sh"
