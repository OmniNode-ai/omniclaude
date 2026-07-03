#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# run-hook-bits-drift.sh — Wrapper for the hook-bits-drift pre-commit hook.
#
# Problem: the hook-bits-drift check uses `uv --directory ../omnibase_core`
# which assumes the omni_home layout (omniclaude and omnibase_core are siblings).
# In git worktrees under omni_worktrees/, ../omnibase_core does not exist.
#
# Fix: resolve omnibase_core via $OMNI_HOME when set, otherwise fall back to
# the sibling-directory assumption for the canonical omni_home layout.
#
# Usage in .pre-commit-config.yaml:
#   entry: bash scripts/run-hook-bits-drift.sh
# with:
#   args: [--check, plugins/onex/hooks/lib/hook_bits.sh]

set -euo pipefail

# Resolve the omnibase_core directory.
if [[ -n "${OMNI_HOME:-}" && -d "${OMNI_HOME}/omnibase_core" ]]; then
    OBC_DIR="${OMNI_HOME}/omnibase_core"
elif [[ -d "$(dirname "$0")/../../../omnibase_core" ]]; then
    # Fallback: three levels up from scripts/ reaches the workspace root.
    # Works for omni_home/omniclaude/scripts/ → omni_home/omnibase_core.
    OBC_DIR="$(cd "$(dirname "$0")/../../../omnibase_core" && pwd)"
elif [[ -d "$(pwd)/../omnibase_core" ]]; then
    # Fallback: adjacent sibling (canonical omni_home layout).
    OBC_DIR="$(cd "$(pwd)/../omnibase_core" && pwd)"
else
    echo "ERROR: hook-bits-drift: cannot locate omnibase_core." >&2
    echo "  Set OMNI_HOME or run from omni_home/omniclaude/." >&2
    exit 1
fi

HOOK_BITS_SH="plugins/onex/hooks/lib/hook_bits.sh"

exec uv --directory "${OBC_DIR}" run python scripts/gen_hook_bits.py --check "../omniclaude/${HOOK_BITS_SH}"
