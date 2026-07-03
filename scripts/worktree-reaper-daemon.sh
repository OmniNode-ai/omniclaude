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
#   OMNI_HOME                    required — locates the omniclaude clone + worktrees roots
#   ONEX_PROJECTION_URL          required — the .201 projection API base URL
#   ONEX_REAPER_INTERVAL         optional — Layer 1 event-poll interval seconds (default 60)
#   ONEX_REAPER_CATCH_UP_INTERVAL optional — Layer 2 catch-up backstop interval
#                                seconds (default 3600 = hourly; 0 disables). The
#                                Mac equivalent of the .201 onex-disk-gc.timer
#                                (OMN-13230, T6). A catch-up sweep also runs once
#                                on daemon start to reconcile downtime gaps.
#
# Manual run (for debugging, Ctrl-C to stop):
#   bash scripts/worktree-reaper-daemon.sh

set -euo pipefail

OMNI_HOME="${OMNI_HOME:?set OMNI_HOME to the omni_home path}"
INTERVAL="${ONEX_REAPER_INTERVAL:-60}"
CATCH_UP_INTERVAL="${ONEX_REAPER_CATCH_UP_INTERVAL:-3600}"
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

echo "[worktree-reaper-daemon] starting loop interpreter=$PYTHON_BIN interval=${INTERVAL}s catch_up_interval=${CATCH_UP_INTERVAL}s" >&2

# exec so launchd KeepAlive supervises the reaper process directly. The reaper's
# --loop handles BOTH layers: the fast event poll every --interval seconds and the
# catch-up backstop every --catch-up-interval seconds (plus once on start). Default
# roots cover all Mac worktree roots.
exec "$PYTHON_BIN" "$REAPER" --execute --loop \
  --interval "$INTERVAL" \
  --catch-up-interval "$CATCH_UP_INTERVAL"
