#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# OMN-13536: Detect omnimarket version/commit drift in dispatch venvs.
#
# Skills dispatch ONEX nodes from the *installed* omnimarket package. When the
# installed commit differs from the approved release-lane baseline, skills may
# execute unreviewed or stale node bytes (old stubs, renamed/deleted handlers).
# This gate converts silent runtime drift into a caught regression.
#
# Two drift surfaces checked:
#   1. uv.lock pin — is the pinned omnimarket git SHA == expected dispatch SHA?
#   2. live daemon venv — is the installed omnimarket commit_id == expected?
#      (No-ops when no live venv is present — the expected CI state.)
#
# Hard-fail, no warn-only (CLAUDE.md Rule #5 enforcement-not-detection).
# On fire, fix the pin:
#   uv lock --upgrade-package omnimarket
# Or rebuild the live daemon venv:
#   bash scripts/repair-plugin-venv.sh
#
# CI behaviour: OMNIMARKET_EXPECTED_SHA may be injected by the workflow. Without
# it the script falls back to canonical-main resolution via git ls-remote
# (requires network) or the local canonical clone at $OMNI_HOME/omnimarket.

set -euo pipefail

if REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" && [[ -n "$REPO_ROOT" ]]; then
    :
else
    REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
fi

SCRIPT="$REPO_ROOT/scripts/check_omnimarket_dispatch_drift.py"

if [[ ! -f "$SCRIPT" ]]; then
    echo "ERROR: guard script not found at $SCRIPT" >&2
    exit 1
fi

# Prefer the uv-managed python inside the repo venv if present; fall back to
# whatever python3 is on PATH.  Do NOT use a uv-managed interpreter for the
# *live daemon venv* check (LAN-grant requirement, Rule 11), but this script
# itself only reads dist-info metadata — no network calls from the script side.
if [[ -x "$REPO_ROOT/.venv/bin/python3" ]]; then
    PYTHON="$REPO_ROOT/.venv/bin/python3"
elif command -v uv >/dev/null 2>&1; then
    PYTHON="uv run python"
else
    PYTHON="python3"
fi

exec $PYTHON "$SCRIPT" "$@"
