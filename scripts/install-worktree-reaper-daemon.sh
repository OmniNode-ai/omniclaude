#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# install-worktree-reaper-daemon.sh — install the Mac worktree-reaper KeepAlive
# LaunchAgent (OMN-13228, T4 of OMN-13008).
#
# This is the *orchestrator's deploy step* — it is NOT run by the worker that ships
# the code PR. The worker ships the plist + daemon launcher; the operator runs this
# on the Mac to load the resident KeepAlive daemon.
#
# The shipped plist (scripts/launchd/ai.omninode.worktree-reaper.plist) declares
# Disabled=true so it is inert until this installer renders it (expanding the
# __OMNI_HOME__/__HOME__ tokens), flips Disabled=false, and loads it via launchctl
# bootstrap. KeepAlive=true keeps the reaper resident (the durable replacement for
# the non-firing periodic launchd path on this Mac).
#
# Usage:
#   bash omniclaude/scripts/install-worktree-reaper-daemon.sh            # install + load
#   bash omniclaude/scripts/install-worktree-reaper-daemon.sh --uninstall
#   bash omniclaude/scripts/install-worktree-reaper-daemon.sh --status
#   bash omniclaude/scripts/install-worktree-reaper-daemon.sh --dry-run  # render only
#
# Prerequisites:
#   - ONEX_PROJECTION_URL set in ~/.omnibase/.env (the .201 LAN projection API base URL)
#   - OMNI_HOME resolvable (defaults to the parent of this omniclaude clone)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
OMNICLAUDE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
OMNI_HOME_RESOLVED="${OMNI_HOME:-$(cd "${OMNICLAUDE_ROOT}/.." && pwd)}"
LABEL="ai.omninode.worktree-reaper"
SRC_PLIST="${SCRIPT_DIR}/launchd/${LABEL}.plist"
LAUNCH_AGENTS="${HOME}/Library/LaunchAgents"
DST_PLIST="${LAUNCH_AGENTS}/${LABEL}.plist"
UID_GUI="$(id -u)"

if [[ "${1:-}" == "--uninstall" ]]; then
  echo "Uninstalling ${LABEL} LaunchAgent..."
  launchctl bootout "gui/${UID_GUI}/${LABEL}" 2>/dev/null || true
  launchctl unload "${DST_PLIST}" 2>/dev/null || true
  rm -f "${DST_PLIST}"
  echo "Done. ${LABEL} uninstalled."
  exit 0
fi

if [[ "${1:-}" == "--status" ]]; then
  echo "--- launchctl list (${LABEL}) ---"
  launchctl list | grep "${LABEL}" || echo "  (not loaded)"
  echo ""
  echo "--- recent stderr log ---"
  tail -n 30 "${HOME}/.local/log/onex/worktree-reaper-stderr.log" 2>/dev/null \
    || echo "  (no log yet)"
  exit 0
fi

DRY_RUN=false
[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=true

if [[ ! -f "${SRC_PLIST}" ]]; then
  echo "ERROR: missing source plist: ${SRC_PLIST}" >&2
  exit 1
fi

# Render: expand path tokens AND flip Disabled=true -> false so the daemon loads.
render() {
  sed \
    -e "s|__OMNI_HOME__|${OMNI_HOME_RESOLVED}|g" \
    -e "s|__HOME__|${HOME}|g" \
    "${SRC_PLIST}" \
  | awk '
      /<key>Disabled<\/key>/ { print; getline; sub(/<true\/>/, "<false/>"); print; next }
      { print }
    '
}

RENDERED="$(render)"

echo "=== install-worktree-reaper-daemon [OMN-13228] ==="
echo "OMNI_HOME:    ${OMNI_HOME_RESOLVED}"
echo "LaunchAgents: ${LAUNCH_AGENTS}"
echo "Dry run:      ${DRY_RUN}"
echo ""

if [[ "${DRY_RUN}" == true ]]; then
  echo "--- rendered ${LABEL}.plist ---"
  echo "${RENDERED}"
  exit 0
fi

mkdir -p "${LAUNCH_AGENTS}" "${HOME}/.local/log/onex"
chmod +x "${SCRIPT_DIR}/worktree-reaper-daemon.sh" "${SCRIPT_DIR}/worktree_reaper.py" 2>/dev/null || true

echo "${RENDERED}" > "${DST_PLIST}"

# Reload: bootout the old instance, then bootstrap the new one.
launchctl bootout "gui/${UID_GUI}/${LABEL}" 2>/dev/null || true
if launchctl bootstrap "gui/${UID_GUI}" "${DST_PLIST}" 2>/dev/null; then
  echo "  loaded via launchctl bootstrap"
elif launchctl load "${DST_PLIST}" 2>/dev/null; then
  echo "  loaded via launchctl load (legacy)"
elif launchctl print "gui/${UID_GUI}/${LABEL}" >/dev/null 2>&1; then
  echo "  already loaded"
else
  echo "ERROR: plist written but failed to load" >&2
  exit 1
fi

echo ""
echo "Done. ${LABEL} installed and running (KeepAlive daemon)."
echo "  Plist: ${DST_PLIST}"
echo ""
echo "Check:      launchctl list | grep ${LABEL}"
echo "Logs:       tail -f ${HOME}/.local/log/onex/worktree-reaper-stderr.log"
echo "Uninstall:  bash omniclaude/scripts/install-worktree-reaper-daemon.sh --uninstall"
echo ""
echo "NOTE: requires ONEX_PROJECTION_URL in ~/.omnibase/.env (the .201 LAN projection API base URL)."
