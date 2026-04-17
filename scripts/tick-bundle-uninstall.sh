#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# tick-bundle-uninstall.sh — idempotent launchd uninstaller for the OMN-9036 tick bundle.
#
# Unloads and removes the 5 tick plists under ~/Library/LaunchAgents. Does NOT touch
# the long-standing ai.omninode.buildloop plist — manage that separately.
#
# Usage:
#   bash omniclaude/scripts/tick-bundle-uninstall.sh
#   bash omniclaude/scripts/tick-bundle-uninstall.sh --dry-run

set -euo pipefail

LAUNCH_AGENTS="${HOME}/Library/LaunchAgents"
DRY_RUN=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN=true; shift ;;
    --help|-h)
      echo "Usage: $0 [--dry-run]"
      exit 0
      ;;
    *) echo "ERROR: Unknown argument: $1" >&2; exit 1 ;;
  esac
done

TICKS=(
  "ai.omninode.merge-sweep"
  "ai.omninode.dispatch-engine"
  "ai.omninode.overseer-verify"
  "ai.omninode.contract-verify"
  "ai.omninode.idle-watchdog"
)

UID_GUI="$(id -u)"
REMOVED=0
ABSENT=0

echo "=== tick-bundle-uninstall [OMN-9036] ==="
echo "LaunchAgents: ${LAUNCH_AGENTS}"
echo "Dry run:      ${DRY_RUN}"
echo ""

for label in "${TICKS[@]}"; do
  dst="${LAUNCH_AGENTS}/${label}.plist"
  if [[ ! -f "${dst}" ]]; then
    echo "  [${label}] absent"
    ABSENT=$((ABSENT + 1))
    continue
  fi

  if [[ "${DRY_RUN}" == "true" ]]; then
    echo "  [${label}] WOULD unload + remove"
    REMOVED=$((REMOVED + 1))
    continue
  fi

  launchctl bootout "gui/${UID_GUI}/${label}" 2>/dev/null || launchctl unload "${dst}" 2>/dev/null || true
  rm -f "${dst}"
  echo "  [${label}] removed"
  REMOVED=$((REMOVED + 1))
done

echo ""
echo "--- summary ---"
echo "  removed: ${REMOVED}"
echo "  absent:  ${ABSENT}"
