#!/bin/bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# ensure-plugin-venv.sh — Build plugin venv in CLAUDE_PLUGIN_DATA on first session
#
# Runs as a SessionStart hook. Builds a Python venv in the persistent
# CLAUDE_PLUGIN_DATA directory (survives plugin updates). Skips if the venv
# already exists and the marker matches current plugin version + lockfile hash.
#
# [OMN-10500]

set -euo pipefail

VENV_DIR="${CLAUDE_PLUGIN_DATA:?CLAUDE_PLUGIN_DATA must be set}/.venv"
PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:?CLAUDE_PLUGIN_ROOT must be set}"
BREW_PY="/opt/homebrew/bin/python3.13"
MARKER="${VENV_DIR}/.built-from"
PROJECT_ROOT="${OMNI_HOME:?OMNI_HOME must be set}/omniclaude"

plugin_version() {
    grep -o '"version"[[:space:]]*:[[:space:]]*"[^"]*"' "${PLUGIN_ROOT}/.claude-plugin/plugin.json" 2>/dev/null \
        | head -1 | sed 's/.*"version"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/'
}

lockfile_hash() {
    if [[ -f "${PROJECT_ROOT}/uv.lock" ]]; then
        shasum -a 256 "${PROJECT_ROOT}/uv.lock" | cut -d' ' -f1
    else
        echo "no-lockfile"
    fi
}

EXPECTED_VERSION="$(plugin_version)"
EXPECTED_LOCK="$(lockfile_hash)"
EXPECTED_MARKER="${EXPECTED_VERSION}:${EXPECTED_LOCK}:3.13"

if [[ -x "${VENV_DIR}/bin/python3" && -f "$MARKER" && "$(cat "$MARKER" 2>/dev/null)" == "$EXPECTED_MARKER" ]]; then
    exit 0
fi

echo "[onex] building plugin venv in ${VENV_DIR}..." >&2
echo "[onex] using python: ${BREW_PY}, project: ${PROJECT_ROOT}" >&2

if [[ ! -x "$BREW_PY" ]]; then
    echo "[onex] ERROR: ${BREW_PY} not found. Install: brew install python@3.13" >&2
    exit 1
fi

if [[ ! -f "${PROJECT_ROOT}/pyproject.toml" ]]; then
    echo "[onex] ERROR: ${PROJECT_ROOT}/pyproject.toml not found. Is OMNI_HOME correct?" >&2
    exit 1
fi

if ! command -v uv &>/dev/null; then
    echo "[onex] ERROR: uv not found. Install: https://docs.astral.sh/uv/getting-started/installation/" >&2
    exit 1
fi

LOCKFILE="${VENV_DIR}.lock"
if ! mkdir "$LOCKFILE" 2>/dev/null; then
    echo "[onex] another venv build in progress, skipping" >&2
    exit 0
fi

cleanup() {
    local exit_code=$?
    if [[ $exit_code -ne 0 ]]; then
        echo "[onex] venv build failed, cleaning up broken state" >&2
        rm -rf "$VENV_DIR"
        rm -f "$MARKER"
    fi
    rmdir "$LOCKFILE" 2>/dev/null || true
}
trap cleanup EXIT

rm -rf "$VENV_DIR"
mkdir -p "$(dirname "$VENV_DIR")"

uv venv --python "$BREW_PY" "$VENV_DIR" 2>&1 | tail -1 >&2
UV_PROJECT_ENVIRONMENT="$VENV_DIR" uv sync --frozen --no-dev --directory "$PROJECT_ROOT" 2>&1 | tail -3 >&2

if ! "${VENV_DIR}/bin/python3" -c "import omniclaude" 2>/dev/null; then
    echo "[onex] ERROR: venv built but omniclaude import failed" >&2
    exit 1
fi

echo "$EXPECTED_MARKER" > "$MARKER"
echo "[onex] plugin venv ready (${EXPECTED_VERSION})" >&2
