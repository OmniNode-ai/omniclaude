#!/bin/bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# repair-plugin-venv.sh — Force-rebuild plugin venv in CLAUDE_PLUGIN_DATA
#
# Manual escape hatch for when the SessionStart hook can't run or the venv
# is corrupted. Delegates to ensure-plugin-venv.sh after clearing the marker
# so a rebuild is forced.
#
# Usage:
#   bash scripts/repair-plugin-venv.sh
#
# [OMN-7101] [OMN-10112] [OMN-10500]

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

: "${OMNI_HOME:=$(cd "${REPO_ROOT}/.." && pwd)}"
: "${CLAUDE_PLUGIN_DATA:=${HOME}/.claude/plugins/data/onex-omninode-tools}"
: "${CLAUDE_PLUGIN_ROOT:=${REPO_ROOT}/plugins/onex}"

export OMNI_HOME CLAUDE_PLUGIN_DATA CLAUDE_PLUGIN_ROOT

VENV_DIR="${CLAUDE_PLUGIN_DATA}/.venv"

echo "Forcing plugin venv rebuild..."
echo "  CLAUDE_PLUGIN_DATA: ${CLAUDE_PLUGIN_DATA}"
echo "  OMNI_HOME: ${OMNI_HOME}"

rm -f "${VENV_DIR}/.built-from"

if bash "${REPO_ROOT}/plugins/onex/hooks/scripts/ensure-plugin-venv.sh"; then
    echo -e "${GREEN}Plugin venv rebuilt successfully at ${VENV_DIR}${NC}"
    "${VENV_DIR}/bin/python3" -c "import omniclaude; print(f'omniclaude {omniclaude.__version__}')"
else
    echo -e "${RED}Plugin venv rebuild failed.${NC}" >&2
    exit 1
fi
