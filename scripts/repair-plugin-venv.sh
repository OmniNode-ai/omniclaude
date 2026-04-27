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
# [OMN-7101] [OMN-10112]

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m'

# Pinned interpreter — macOS LAN grant is per-binary; brew python3.13 has the grant;
# uv-managed ad-hoc Pythons do not surface a dialog and cannot be granted.
BREW_PYTHON="/opt/homebrew/bin/python3.13"

if [[ ! -x "$BREW_PYTHON" ]]; then
    echo -e "${RED}Error: $BREW_PYTHON not found or not executable.${NC}" >&2
    echo -e "${RED}Install via: brew install python@3.13${NC}" >&2
    exit 1
fi

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

# Remove hollow or stale .venv before recreating — uv refuses to rebuild over an
# empty directory that was created by a different Python version.
if [[ -e "${LIB_DIR}/.venv" || -L "${LIB_DIR}/.venv" ]]; then
    echo "Removing stale .venv at ${LIB_DIR}/.venv ..."
    rm -rf "${LIB_DIR}/.venv"
fi

echo "Rebuilding plugin venv at ${LIB_DIR}/.venv (python: $BREW_PYTHON) ..."
cd "$REPO_ROOT"
uv venv --python "$BREW_PYTHON" "${LIB_DIR}/.venv"
UV_PROJECT_ENVIRONMENT="${LIB_DIR}/.venv" uv sync --frozen --no-dev

# Smoke test
if "${LIB_DIR}/.venv/bin/python3" -c "import omniclaude; print('Smoke test: OK')" 2>&1; then
    echo -e "${GREEN}Plugin venv rebuilt successfully.${NC}"
else
    echo -e "${RED}Smoke test failed after venv rebuild.${NC}" >&2
    exit 1
fi
