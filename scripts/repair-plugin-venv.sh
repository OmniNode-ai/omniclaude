#!/bin/bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# repair-plugin-venv.sh — Rebuild plugins/onex/lib/.venv via uv sync
#
# Use when hooks fail with "No valid Python found" or after dependency changes.
# The plugin runs from source (omni_home/omniclaude), so this just rebuilds
# the virtualenv that hooks use at runtime.
#
# Usage:
#   bash scripts/repair-plugin-venv.sh
#
# [OMN-7101]

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m'

# Resolve repo root (this script lives in <repo>/scripts/)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
LIB_DIR="${REPO_ROOT}/plugins/onex/lib"

if [[ ! -d "$LIB_DIR" ]]; then
    echo -e "${RED}Error: lib directory not found at ${LIB_DIR}${NC}" >&2
    exit 1
fi

if ! command -v uv &>/dev/null; then
    echo -e "${RED}Error: uv not found in PATH. Install: https://docs.astral.sh/uv/getting-started/installation/${NC}" >&2
    exit 1
fi

echo "Rebuilding plugin venv at ${LIB_DIR}/.venv ..."
cd "$REPO_ROOT"
UV_PROJECT_ENVIRONMENT="${LIB_DIR}/.venv" uv sync --frozen --no-dev

# Smoke test
if "${LIB_DIR}/.venv/bin/python3" -c "import omniclaude; print('Smoke test: OK')" 2>&1; then
    echo -e "${GREEN}Plugin venv rebuilt successfully.${NC}"
else
    echo -e "${RED}Smoke test failed after venv rebuild.${NC}" >&2
    exit 1
fi
