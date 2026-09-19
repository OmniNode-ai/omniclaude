#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# OMN-13536: Detect omnimarket version/commit drift in dispatch venvs.
#
# Skills dispatch ONEX nodes from the *installed* omnimarket package. When the
# installed commit differs from the expected one, skills may execute
# unreviewed or stale node bytes (old stubs, renamed/deleted handlers). This
# gate converts silent runtime drift into a caught regression.
#
# Two drift surfaces checked:
#   1. uv.lock pin — is the pinned omnimarket git SHA == expected dispatch SHA?
#   2. live daemon venv — is the installed omnimarket commit_id == expected?
#      (No-ops when no live venv is present — the expected CI state.)
#
# Hard-fail, no warn-only (CLAUDE.md Rule #5 enforcement-not-detection).
#
# OMN-18752 / OMN-18753: the expected commit is the canonical clone's
# CHECKED-OUT head, and where no clone exists (CI) it is this repo's uv.lock,
# which follows that clone through sibling-lock-refresh.yml. It is NOT
# omnimarket's `main`. That was this gate's baseline until OMN-18752 and it
# made the gate answer to a different ref from the OMN-18675 venv guard, which
# resolves the clone: main is release-synced, so it lags the clone's `dev` and
# the two demanded different commits at every moment except the instant main
# caught up. The script no longer consults a remote branch at all, and
# tests/test_venv_gate_registration.py reads its source to keep it that way —
# this gate is registered in .pre-commit-config.yaml on the strength of that,
# so a reintroduced remote probe would block every commit on the host.
#
# On fire, read the script's own printed remedy and follow THAT. Do not reach
# for `uv lock --upgrade-package omnimarket`, which this header used to
# prescribe: the pin is an immutable git rev, `--upgrade-package` cannot move
# an immutable rev, and hand-editing it instead is the act that desynchronises
# the lock from the clone and takes `onex delegate` down for every lane on
# this host. The sanctioned advance is sibling-lock-refresh.yml on
# workflow_dispatch, reviewed as a bot PR.

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
    PYTHON_CMD=("$REPO_ROOT/.venv/bin/python3")
elif command -v uv >/dev/null 2>&1; then
    PYTHON_CMD=(uv run python)
else
    PYTHON_CMD=(python3)
fi

exec "${PYTHON_CMD[@]}" "$SCRIPT" "$@"
