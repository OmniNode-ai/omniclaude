#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# worktree-reaper-daemon.sh — launcher for the Mac worktree-reaper KeepAlive daemon
# (OMN-13228, T4 of OMN-13008).
#
# This is the ProgramArguments target of ai.omninode.worktree-reaper.plist (a
# launchd KeepAlive DAEMON, NOT a periodic job — launchd periodic jobs do not fire
# reliably on this Mac, memory feedback_local_durability). It execs the reaper in
# --loop mode so the resident process polls the pr-merged projection on a short
# interval and drives prune-worktrees.sh on each newly-merged PR.
#
# It is a thin launcher: pick the interpreter (brew python3.13 per CLAUDE.md Rule 11
# if present, else python3 on PATH) and exec the reaper. exec means launchd's
# KeepAlive supervises the reaper process directly.
#
# Env (from the plist / ~/.omnibase/.env):
#   OMNI_HOME             required — locates the omniclaude clone + worktrees roots
#   ONEX_PROJECTION_URL   required — the .201 projection API base URL
#   ONEX_REAPER_INTERVAL  optional — poll interval seconds (default 60)
#
# Manual run (for debugging, Ctrl-C to stop):
#   bash scripts/worktree-reaper-daemon.sh

set -euo pipefail

OMNI_HOME="${OMNI_HOME:?set OMNI_HOME to the omni_home path}"
INTERVAL="${ONEX_REAPER_INTERVAL:-60}"
REAPER="${OMNI_HOME}/omniclaude/scripts/worktree_reaper.py"

if [[ ! -f "$REAPER" ]]; then
  echo "[worktree-reaper-daemon] reaper not found: $REAPER" >&2
  exit 3
fi

# Interpreter selection (Rule 11): prefer the brew python with the LAN grant, but
# the reaper reads over HTTP via the projection API so it does NOT need the grant;
# any python3 works. Pick the first available.
PYTHON_BIN=""
for cand in \
  "${PLUGIN_PYTHON_BIN:-}" \
  "/opt/homebrew/bin/python3.13" \
  "/usr/local/bin/python3.13" \
  "$(command -v python3 2>/dev/null || true)"; do
  if [[ -n "$cand" && -x "$cand" ]]; then
    PYTHON_BIN="$cand"
    break
  fi
done

if [[ -z "$PYTHON_BIN" ]]; then
  echo "[worktree-reaper-daemon] no python3 interpreter found" >&2
  exit 2
fi

echo "[worktree-reaper-daemon] starting loop interpreter=$PYTHON_BIN interval=${INTERVAL}s" >&2

# exec so launchd KeepAlive supervises the reaper process directly. The reaper's
# --loop handles the polling cadence; default roots cover all Mac worktree roots.
exec "$PYTHON_BIN" "$REAPER" --execute --loop --interval "$INTERVAL"
