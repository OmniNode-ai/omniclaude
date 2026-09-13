#!/bin/bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# ensure-plugin-venv.sh — Build plugin venv in CLAUDE_PLUGIN_DATA
#
# Invoked manually, NOT registered in hooks.json: scripts/repair-plugin-venv.sh
# delegates here, and the onboarding skill documents running it by hand
# (plugins/onex/skills/onboarding/SKILL.md). Builds a Python venv in the
# persistent CLAUDE_PLUGIN_DATA directory (survives plugin updates). Skips if
# the venv already exists and the marker matches current plugin version +
# lockfile hash.
#
# [OMN-10500]

set -euo pipefail

# Load ~/.omnibase/.env so OMNI_HOME and other platform vars are available
# even when not exported by the parent shell.
_GLOBAL_ENV="${HOME}/.omnibase/.env"
if [[ -f "$_GLOBAL_ENV" ]]; then
    set -a
    # shellcheck disable=SC1090
    if ! source "$_GLOBAL_ENV" 2>/dev/null; then
        echo "[onex] warning: failed to load ${_GLOBAL_ENV}; continuing with current environment" >&2
    fi
    set +a
fi
unset _GLOBAL_ENV

VENV_DIR="${CLAUDE_PLUGIN_DATA:?CLAUDE_PLUGIN_DATA must be set}/.venv"
PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:?CLAUDE_PLUGIN_ROOT must be set}"
BREW_PY="${ONEX_BREW_PYTHON:-}"
if [[ -n "$BREW_PY" ]]; then
    case "$BREW_PY" in
        /opt/homebrew/bin/python3.13|/usr/local/bin/python3.13) ;;
        *)
            echo "[onex] ERROR: unsupported Brew Python path: ${BREW_PY}" >&2
            exit 1
            ;;
    esac
else
    for candidate in /opt/homebrew/bin/python3.13 /usr/local/bin/python3.13; do
        if [[ -x "$candidate" ]]; then
            BREW_PY="$candidate"
            break
        fi
    done
fi
MARKER="${VENV_DIR}/.built-from"
PROJECT_ROOT="${OMNI_HOME:?OMNI_HOME must be set}/omniclaude"
LOCKFILE="${VENV_DIR}.lock"

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

venv_is_fresh() {
    [[ "${ONEX_FORCE_PLUGIN_VENV_REBUILD:-}" != "1" ]] || return 1
    [[ -x "${VENV_DIR}/bin/python3" ]] || return 1
    [[ -f "$MARKER" ]] || return 1
    [[ "$(cat "$MARKER" 2>/dev/null)" == "$EXPECTED_MARKER" ]] || return 1
    "${VENV_DIR}/bin/python3" - "$BREW_PY" <<'PY'
from pathlib import Path
import sys

raise SystemExit(Path(sys.executable).resolve() != Path(sys.argv[1]).resolve())
PY
}

case "${1:-}" in
    "") ;;
    --verify)
        if venv_is_fresh; then
            exit 0
        fi
        echo "[onex] ERROR: plugin venv is missing, stale, or not Brew-backed" >&2
        exit 1
        ;;
    *)
        echo "Usage: $0 [--verify]" >&2
        exit 2
        ;;
esac

if [[ "${ONEX_PLUGIN_VENV_LOCK_HELD:-}" != "1" ]]; then
    if [[ ! -x "$BREW_PY" ]]; then
        echo "[onex] ERROR: ${BREW_PY} not found. Install: brew install python@3.13" >&2
        exit 1
    fi
    mkdir -p "$(dirname "$VENV_DIR")"
    # macOS does not provide flock(1). The existing hook journal uses the
    # standard-library fcntl.flock primitive, which the kernel releases on
    # process death. Pass the locked descriptor to the child so an abrupt
    # wrapper exit cannot overlap an orphaned build.
    exec "$BREW_PY" - "$LOCKFILE" "$0" "$@" <<'PY'
import errno
import fcntl
import os
from pathlib import Path
import subprocess
import sys

lock_path = Path(sys.argv[1])
script = sys.argv[2]
arguments = sys.argv[3:]
with lock_path.open("a+") as lock_file:
    try:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        if exc.errno in (errno.EACCES, errno.EAGAIN):
            raise SystemExit(75)
        raise
    environment = os.environ | {
        "ONEX_PLUGIN_VENV_LOCK_HELD": "1",
        "ONEX_PLUGIN_VENV_LOCK_FD": str(lock_file.fileno()),
    }
    completed = subprocess.run(
        ["bash", script, *arguments],
        env=environment,
        pass_fds=(lock_file.fileno(),),
        check=False,
    )
raise SystemExit(completed.returncode)
PY
fi

if [[ ! "${ONEX_PLUGIN_VENV_LOCK_FD:-}" =~ ^[0-9]+$ || ! -e "/dev/fd/${ONEX_PLUGIN_VENV_LOCK_FD}" ]] || ! "$BREW_PY" - "$LOCKFILE" "${ONEX_PLUGIN_VENV_LOCK_FD}" <<'PY'
import fcntl
import os
from pathlib import Path
import sys

lock_path = Path(sys.argv[1])
lock_fd = int(sys.argv[2])
try:
    same_lock = os.fstat(lock_fd)[:2] == lock_path.stat()[:2]
    if not same_lock:
        raise SystemExit(1)
    fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
except OSError:
    raise SystemExit(1)
PY
then
    echo "[onex] ERROR: plugin venv build requires the inherited advisory lock." >&2
    exit 1
fi

if venv_is_fresh; then
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

PREVIOUS_VENV="${VENV_DIR}.previous"
had_previous=0

# A process killed after moving the old venv aside leaves this recoverable
# backup. The inherited fcntl lock remains held while this child mutates it.
if [[ ! -e "$VENV_DIR" && -e "$PREVIOUS_VENV" ]]; then
    mv "$PREVIOUS_VENV" "$VENV_DIR"
fi

# A different builder may have completed between the initial freshness check
# and acquiring the lock.
if venv_is_fresh; then
    exit 0
fi

cleanup() {
    local exit_code=$?
    if [[ $exit_code -ne 0 ]]; then
        echo "[onex] venv build failed, restoring prior state" >&2
        rm -rf "$VENV_DIR"
        if [[ "$had_previous" == "1" && -e "$PREVIOUS_VENV" ]]; then
            mv "$PREVIOUS_VENV" "$VENV_DIR"
        fi
    else
        rm -rf "$PREVIOUS_VENV"
    fi
}
trap cleanup EXIT

mkdir -p "$(dirname "$VENV_DIR")"
if [[ -e "$VENV_DIR" ]]; then
    if [[ -e "$PREVIOUS_VENV" ]]; then
        echo "[onex] ERROR: prior venv backup exists; refusing ambiguous replacement" >&2
        exit 1
    fi
    mv "$VENV_DIR" "$PREVIOUS_VENV"
    had_previous=1
fi

uv venv --python "$BREW_PY" "$VENV_DIR" 2>&1 | tail -1 >&2
UV_PROJECT_ENVIRONMENT="$VENV_DIR" uv sync --frozen --no-dev --directory "$PROJECT_ROOT" 2>&1 | tail -3 >&2

if ! "${VENV_DIR}/bin/python3" -c "import omniclaude" 2>/dev/null; then
    echo "[onex] ERROR: venv built but omniclaude import failed" >&2
    exit 1
fi

echo "$EXPECTED_MARKER" > "$MARKER"
echo "[onex] plugin venv ready (${EXPECTED_VERSION})" >&2
