#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# install-hook-emit-drainer.sh — install the hook-emit journal drainer
# KeepAlive LaunchAgent (OMN-17224).
#
# This is the *operator's deploy step* — it is NOT run by the worker that
# ships the code PR. The worker ships the plist + drainer; the operator runs
# this on the Mac to load the resident daemon.
#
# Context: before OMN-17224 every Claude Code tool call forked a Python that
# imported the omnimarket handler stack and published to Kafka inline —
# 31.08s of a 31.65s handle() was a lazily-imported omnibase_infra chain
# building ~2,497 Pydantic classes. Fourteen ran concurrently at ~270% CPU.
# The hook now appends to a local journal in sub-100ms; this daemon pays the
# import once and drains it.
#
# The shipped plist declares Disabled=true so it is inert until this
# installer renders it (expanding __OMNI_HOME__ / __HOME__ / __PYTHON__),
# flips Disabled=false, and loads it via launchctl bootstrap.
#
# Usage:
#   bash omniclaude/scripts/install-hook-emit-drainer.sh            # install + load
#   bash omniclaude/scripts/install-hook-emit-drainer.sh --uninstall
#   bash omniclaude/scripts/install-hook-emit-drainer.sh --status
#   bash omniclaude/scripts/install-hook-emit-drainer.sh --dry-run  # render only

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
OMNICLAUDE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
OMNI_HOME_RESOLVED="${OMNI_HOME:-$(cd "${OMNICLAUDE_ROOT}/.." && pwd)}"
LABEL="ai.omninode.hook-emit-drainer"
SRC_PLIST="${SCRIPT_DIR}/launchd/${LABEL}.plist"
LAUNCH_AGENTS="${HOME}/Library/LaunchAgents"
DST_PLIST="${LAUNCH_AGENTS}/${LABEL}.plist"
UID_GUI="$(id -u)"

# CLAUDE.md rule 11: the literal brew interpreter path. launchd runs with a
# restricted PATH so $(brew --prefix) is unavailable, and the macOS Local
# Network grant is per-binary — a uv-managed interpreter silently
# EHOSTUNREACHes on the LAN publish to the .201 broker.
if [[ -x "/opt/homebrew/bin/python3.13" ]]; then
  BREW_PYTHON="/opt/homebrew/bin/python3.13"   # local-path-ok: rule 11 literal (ARM)
elif [[ -x "/usr/local/bin/python3.13" ]]; then
  BREW_PYTHON="/usr/local/bin/python3.13"      # local-path-ok: rule 11 literal (Intel)
else
  echo "ERROR: brew python3.13 not found at either rule-11 path." >&2
  echo "       Install it (brew install python@3.13) before loading this agent." >&2
  exit 1
fi

if [[ "${1:-}" == "--uninstall" ]]; then
  echo "Uninstalling ${LABEL} LaunchAgent..."
  launchctl bootout "gui/${UID_GUI}/${LABEL}" 2>/dev/null || true
  launchctl unload "${DST_PLIST}" 2>/dev/null || true
  rm -f "${DST_PLIST}"
  echo "Done. ${LABEL} uninstalled."
  echo "NOTE: hooks keep appending to the journal. It is bounded (oldest"
  echo "      dropped and counted), so nothing grows without limit, but"
  echo "      nothing publishes until a drainer runs again."
  exit 0
fi

if [[ "${1:-}" == "--status" ]]; then
  echo "Label:   ${LABEL}"
  echo "Plist:   ${DST_PLIST}"
  launchctl print "gui/${UID_GUI}/${LABEL}" 2>/dev/null | sed -n '1,12p' \
    || echo "state:   NOT LOADED"
  JOURNAL="${ONEX_STATE_DIR:-${OMNI_HOME_RESOLVED}/.onex_state}/hook_emit_journal"
  echo "Journal: ${JOURNAL}"
  shopt -s nullglob
  pending=("${JOURNAL}"/*.json)
  echo "Pending: ${#pending[@]}"
  shopt -u nullglob
  exit 0
fi

echo "Rendering ${LABEL} plist..."
echo "  OMNI_HOME:   ${OMNI_HOME_RESOLVED}"
echo "  interpreter: ${BREW_PYTHON}"

RENDERED="$(mktemp)"
trap 'rm -f "${RENDERED}"' EXIT

sed -e "s|__OMNI_HOME__|${OMNI_HOME_RESOLVED}|g" \
    -e "s|__HOME__|${HOME}|g" \
    -e "s|__PYTHON__|${BREW_PYTHON}|g" \
    "${SRC_PLIST}" \
  | sed -e 's|<key>Disabled</key>|<key>Disabled</key>|' \
  | python3 -c "
import sys
s = sys.stdin.read()
# Flip the shipped Disabled=true to false. Anchored on the Disabled key so a
# stray <true/> elsewhere in the plist (KeepAlive, RunAtLoad) is untouched.
s = s.replace('<key>Disabled</key>\n  <true/>', '<key>Disabled</key>\n  <false/>', 1)
sys.stdout.write(s)
" > "${RENDERED}"

if ! grep -q '<key>Disabled</key>' "${RENDERED}"; then
  echo "ERROR: rendered plist lost its Disabled key — refusing to install." >&2
  exit 1
fi
if grep -q '__OMNI_HOME__\|__HOME__\|__PYTHON__' "${RENDERED}"; then
  echo "ERROR: rendered plist still contains unexpanded tokens." >&2
  exit 1
fi
if ! plutil -lint "${RENDERED}" >/dev/null; then
  echo "ERROR: rendered plist is not valid." >&2
  exit 1
fi

if [[ "${1:-}" == "--dry-run" ]]; then
  echo "--- rendered plist (not installed) ---"
  cat "${RENDERED}"
  exit 0
fi

mkdir -p "${LAUNCH_AGENTS}"
mkdir -p "${OMNI_HOME_RESOLVED}/.onex_state/hooks/logs"

# Bootout any previous instance so this is idempotent and never leaves two.
launchctl bootout "gui/${UID_GUI}/${LABEL}" 2>/dev/null || true

cp "${RENDERED}" "${DST_PLIST}"
launchctl bootstrap "gui/${UID_GUI}" "${DST_PLIST}"
launchctl enable "gui/${UID_GUI}/${LABEL}"

echo "Loaded ${LABEL}."
echo
echo "Verify:"
echo "  bash omniclaude/scripts/install-hook-emit-drainer.sh --status"
echo "  tail -f ${OMNI_HOME_RESOLVED}/.onex_state/hooks/logs/hook-emit-drainer.log"
echo
echo "Expect at most ONE hook_emit_drainer.py process:"
echo "  pgrep -fl hook_emit_drainer.py"
