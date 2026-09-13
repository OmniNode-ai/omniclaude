#!/bin/bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# repair-plugin-venv.sh — Force-rebuild plugin venv in CLAUDE_PLUGIN_DATA
#
# Manual escape hatch for when the SessionStart hook can't run or the venv
# is corrupted. Delegates to ensure-plugin-venv.sh after clearing the marker
# so a rebuild is forced.
# Refuses repair if the plugin venv bin is missing from PATH or an earlier onex
# shadows its wrapper. A missing wrapper is allowed when the venv bin is already
# ahead of other onex commands, so repair can recreate a corrupted environment.
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
PLUGIN_BIN="${VENV_DIR}/bin"
PLUGIN_ONEX="${PLUGIN_BIN}/onex"
PATH_ONEX="$(type -P onex || true)"
PLUGIN_BIN_ON_PATH=false
PLUGIN_BIN_SEEN=false
PATH_SHADOW_ONEX=""

IFS=: read -r -a PATH_ENTRIES <<< "${PATH}"
for PATH_ENTRY in "${PATH_ENTRIES[@]}"; do
    SEARCH_DIR="${PATH_ENTRY:-.}"
    PATH_ENTRY_TRIMMED="${PATH_ENTRY}"
    PLUGIN_BIN_TRIMMED="${PLUGIN_BIN}"
    while [[ "${PATH_ENTRY_TRIMMED}" == */ && "${PATH_ENTRY_TRIMMED}" != "/" ]]; do
        PATH_ENTRY_TRIMMED="${PATH_ENTRY_TRIMMED%/}"
    done
    while [[ "${PLUGIN_BIN_TRIMMED}" == */ && "${PLUGIN_BIN_TRIMMED}" != "/" ]]; do
        PLUGIN_BIN_TRIMMED="${PLUGIN_BIN_TRIMMED%/}"
    done

    if [[ "${PATH_ENTRY_TRIMMED}" == "${PLUGIN_BIN_TRIMMED}" ]] || {
        [[ -d "${SEARCH_DIR}" && -d "${PLUGIN_BIN}" && "${SEARCH_DIR}" -ef "${PLUGIN_BIN}" ]]
    }; then
        PLUGIN_BIN_ON_PATH=true
        PLUGIN_BIN_SEEN=true
        continue
    fi

    if [[ -z "${PATH_SHADOW_ONEX}" && "${PLUGIN_BIN_SEEN}" != true && -x "${SEARCH_DIR}/onex" ]]; then
        PATH_SHADOW_ONEX="${PATH_ONEX:-${SEARCH_DIR}/onex}"
    fi
done

if [[ "${PLUGIN_BIN_ON_PATH}" != true ]]; then
    if [[ -n "${PATH_ONEX}" ]]; then
        echo "[onex] ERROR: PATH resolves onex to ${PATH_ONEX}, but the canonical plugin venv bin ${PLUGIN_BIN} is missing from PATH. Put it before other onex commands before repairing." >&2
    else
        echo "[onex] ERROR: PATH is missing the canonical plugin venv bin ${PLUGIN_BIN}. Add it before repairing." >&2
    fi
    exit 1
fi

if [[ -n "${PATH_SHADOW_ONEX}" ]]; then
    echo "[onex] ERROR: PATH resolves onex to ${PATH_SHADOW_ONEX}, ahead of the canonical plugin wrapper ${PLUGIN_ONEX}. Put the plugin venv bin directory first in PATH before repairing." >&2
    exit 1
fi

echo "Forcing plugin venv rebuild..."
echo "  CLAUDE_PLUGIN_DATA: ${CLAUDE_PLUGIN_DATA}"
echo "  OMNI_HOME: ${OMNI_HOME}"

rm -f "${VENV_DIR}/.built-from"

if bash "${REPO_ROOT}/plugins/onex/hooks/scripts/ensure-plugin-venv.sh"; then
    if ! PATH_ONEX="$(type -P onex)" || [[ ! -x "${PATH_ONEX}" || ! "${PATH_ONEX}" -ef "${PLUGIN_ONEX}" ]]; then
        echo "[onex] ERROR: after rebuilding, PATH resolves onex to ${PATH_ONEX:-<not found>}, expected the canonical plugin wrapper ${PLUGIN_ONEX}." >&2
        exit 1
    fi
    echo -e "${GREEN}Plugin venv rebuilt successfully at ${VENV_DIR}${NC}"
    "${VENV_DIR}/bin/python3" -c "import omniclaude; print(f'omniclaude {omniclaude.__version__}')"
else
    echo -e "${RED}Plugin venv rebuild failed.${NC}" >&2
    exit 1
fi
