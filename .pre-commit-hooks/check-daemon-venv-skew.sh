#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# OMN-13120: Detect shared-package pin drift between the live plugin daemon venv
# (CLAUDE_PLUGIN_DATA/.venv, default ~/.claude/plugins/data/onex-omninode-tools/.venv)
# and the canonical uv.lock pins.
#
# Two drift modes are caught:
#   1. lock drift     — uv.lock changed but the live venv was never rebuilt
#                       (.built-from marker hash != sha256(uv.lock)).
#   2. in-place drift — a shared package in the live venv was mutated in place
#                       to a version the lock does not pin.
#
# Hard-fail, no warn-only (CLAUDE.md Rule #5 enforcement-not-detection). On a
# fired gate the fix is to rebuild the daemon venv off brew python3.13 (Rule 11):
#     bash scripts/repair-plugin-venv.sh
#
# CI behavior: CI runners have no live daemon venv, so the gate runs in
# lock-consistency mode (parse the canonical lock, prove pins resolve). It never
# silently no-ops — an unparseable lock fails the gate.
#
# This wrapper is registered as BOTH a pre-commit hook (.pre-commit-config.yaml)
# and a required CI status check (.github/workflows/daemon-venv-skew-gate.yml).

set -euo pipefail

if REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" && [[ -n "$REPO_ROOT" ]]; then
    :
else
    REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
fi

PY="${PYTHON_BIN:-python3}"
if ! command -v "$PY" >/dev/null 2>&1; then
    echo "ERROR: python3 not found on PATH for daemon-venv-skew gate" >&2
    exit 1
fi

exec "$PY" "${REPO_ROOT}/scripts/check_daemon_venv_skew.py" "$@"
