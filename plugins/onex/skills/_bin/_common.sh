#!/bin/bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# =============================================================================
# Skill Script Backends - Shared Shell Functions
# =============================================================================
# Resolves paths, sets environment, and invokes the Python backend.
# Same pattern as hooks/scripts/common.sh -> hooks/lib/*.py
#
# Usage (from a thin shell entrypoint):
#   SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
#   source "${SCRIPT_DIR}/_common.sh"
#   invoke_backend "module_name" "$@"
#
# Exports after sourcing:
#   - BIN_DIR:     Path to this _bin/ directory
#   - LIB_DIR:     Path to _bin/_lib/ (Python modules)
#   - PYTHON_CMD:  Resolved Python interpreter
# =============================================================================

set -euo pipefail

BIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIB_DIR="${BIN_DIR}/_lib"

# ---------------------------------------------------------------------------
# Python Resolution
# ---------------------------------------------------------------------------
# Priority chain (same as hooks/scripts/common.sh):
#   1. PLUGIN_PYTHON_BIN env var (explicit override)
#   2. Plugin-bundled venv at PLUGIN_ROOT/lib/.venv
#   3. OMNICLAUDE_PROJECT_ROOT/.venv (dev mode)
#   4. System python3
#   5. Hard failure

_find_python() {
    if [[ -n "${PLUGIN_PYTHON_BIN:-}" && -f "${PLUGIN_PYTHON_BIN}" && -x "${PLUGIN_PYTHON_BIN}" ]]; then
        echo "${PLUGIN_PYTHON_BIN}"
        return
    fi

    # Derive PLUGIN_ROOT: _bin is at plugins/onex/skills/_bin
    local plugin_root="${CLAUDE_PLUGIN_ROOT:-${BIN_DIR}/../..}"
    if [[ -f "${plugin_root}/lib/.venv/bin/python3" && -x "${plugin_root}/lib/.venv/bin/python3" ]]; then
        echo "${plugin_root}/lib/.venv/bin/python3"
        return
    fi

    if [[ -n "${OMNICLAUDE_PROJECT_ROOT:-}" && -f "${OMNICLAUDE_PROJECT_ROOT}/.venv/bin/python3" && -x "${OMNICLAUDE_PROJECT_ROOT}/.venv/bin/python3" ]]; then
        echo "${OMNICLAUDE_PROJECT_ROOT}/.venv/bin/python3"
        return
    fi

    # Fallback to system python3 (scripts have minimal deps: pydantic only)
    if command -v python3 >/dev/null 2>&1; then
        echo "python3"
        return
    fi

    echo ""
}

PYTHON_CMD="$(_find_python)"
if [[ -z "${PYTHON_CMD}" ]]; then
    echo 'STATUS=FAIL LOG= MSG="No valid Python found for skill scripts"' >&2
    exit 1
fi
export PYTHON_CMD

# ---------------------------------------------------------------------------
# Environment Loading
# ---------------------------------------------------------------------------
# Load .env if available (for GH_TOKEN, etc.)
_load_env() {
    local env_file="${HOME}/.omnibase/.env"
    if [[ -f "$env_file" ]]; then
        set -a
        # shellcheck disable=SC1090
        source "$env_file" 2>/dev/null || true
        set +a
    fi
}
_load_env

# ---------------------------------------------------------------------------
# Backend Invocation
# ---------------------------------------------------------------------------
# Invoke a Python backend module from _lib/.
#
# Usage: invoke_backend "pr_scan" "$@"
# This runs: python3 -m _lib.pr_scan "$@" with correct PYTHONPATH.

invoke_backend() {
    local module="$1"
    shift
    PYTHONPATH="${BIN_DIR}:${PYTHONPATH:-}" exec "${PYTHON_CMD}" -m "_lib.${module}" "$@"
}
