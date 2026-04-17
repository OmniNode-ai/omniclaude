#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# tick-bundle-install.sh — idempotent launchd installer for the OMN-9036 tick bundle.
#
# Installs 5 plists under ~/Library/LaunchAgents:
#   ai.omninode.merge-sweep       (5m)
#   ai.omninode.dispatch-engine   (10m)
#   ai.omninode.overseer-verify   (15m)
#   ai.omninode.contract-verify   (15m)
#   ai.omninode.idle-watchdog     (15m)
#
# Source templates under scripts/launchd/ contain __OMNI_HOME__ / __HOME__ placeholders;
# this script expands them at install time so the deployed plists are absolute-path correct
# while the repo itself keeps no hardcoded user-specific paths.
#
# Running the script twice is a no-op: each plist is diffed against the already-installed
# version; identical plists are left alone, changed plists are re-loaded.
#
# Usage:
#   bash omniclaude/scripts/tick-bundle-install.sh
#   bash omniclaude/scripts/tick-bundle-install.sh --dry-run

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
OMNICLAUDE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
OMNI_HOME_RESOLVED="${OMNI_HOME:-$(cd "${OMNICLAUDE_ROOT}/.." && pwd)}"
LAUNCHD_SRC="${SCRIPT_DIR}/launchd"
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

echo "=== tick-bundle-install [OMN-9036] ==="
echo "OMNI_HOME:      ${OMNI_HOME_RESOLVED}"
echo "LaunchAgents:   ${LAUNCH_AGENTS}"
echo "Dry run:        ${DRY_RUN}"
echo ""

if [[ ! -d "${LAUNCHD_SRC}" ]]; then
  echo "ERROR: missing source dir: ${LAUNCHD_SRC}" >&2
  exit 1
fi

mkdir -p "${LAUNCH_AGENTS}"

UID_GUI="$(id -u)"
CHANGED=0
UNCHANGED=0

render_plist() {
  # Expand __OMNI_HOME__ and __HOME__ placeholders in a template plist and print
  # the rendered content to stdout. Uses sed with pipe delimiter so path slashes
  # do not collide.
  local src="$1"
  sed \
    -e "s|__OMNI_HOME__|${OMNI_HOME_RESOLVED}|g" \
    -e "s|__HOME__|${HOME}|g" \
    "${src}"
}

install_one() {
  local label="$1"
  local src="${LAUNCHD_SRC}/${label}.plist"
  local dst="${LAUNCH_AGENTS}/${label}.plist"

  if [[ ! -f "${src}" ]]; then
    echo "  [${label}] SKIP — template missing: ${src}"
    return
  fi

  local rendered
  rendered="$(render_plist "${src}")"

  if [[ -f "${dst}" ]]; then
    if diff -q <(echo "${rendered}") "${dst}" >/dev/null 2>&1; then
      echo "  [${label}] unchanged"
      UNCHANGED=$((UNCHANGED + 1))
      return
    fi
  fi

  if [[ "${DRY_RUN}" == "true" ]]; then
    echo "  [${label}] WOULD install → ${dst}"
    CHANGED=$((CHANGED + 1))
    return
  fi

  # Unload existing (best-effort) before rewriting; ignore if not currently loaded.
  launchctl bootout "gui/${UID_GUI}/${label}" 2>/dev/null || true

  printf '%s\n' "${rendered}" > "${dst}"

  # Load the new plist. bootstrap is the modern equivalent of `launchctl load`.
  # If both paths fail we return 1 so the installer exits non-zero rather than
  # silently marking a broken deployment as "installed".
  if launchctl bootstrap "gui/${UID_GUI}" "${dst}" 2>/dev/null; then
    echo "  [${label}] installed + loaded"
    CHANGED=$((CHANGED + 1))
    return 0
  fi

  # Fallback for older launchctl — try the legacy load command.
  if launchctl load "${dst}" 2>/dev/null; then
    echo "  [${label}] installed + loaded (legacy)"
    CHANGED=$((CHANGED + 1))
    return 0
  fi

  # If the agent is already loaded (bootstrap returns EEXIST-style failure),
  # launchctl print will succeed. Treat that as OK; anything else is a hard error.
  if launchctl print "gui/${UID_GUI}/${label}" >/dev/null 2>&1; then
    echo "  [${label}] installed (already loaded)"
    CHANGED=$((CHANGED + 1))
    return 0
  fi

  echo "  [${label}] ERROR — plist written but failed to load" >&2
  return 1
}

FAILED=0
# `set -e` aborts the script on the first nonzero return from install_one, so we
# disable it here to report every failure and still produce a full summary, then
# exit non-zero at the end if any tick failed to load.
set +e
for label in "${TICKS[@]}"; do
  install_one "${label}" || FAILED=$((FAILED + 1))
done
set -e

echo ""
echo "--- summary ---"
echo "  changed:   ${CHANGED}"
echo "  unchanged: ${UNCHANGED}"
echo "  failed:    ${FAILED}"
echo ""

if [[ "${DRY_RUN}" == "true" ]]; then
  echo "[DRY RUN] complete."
  exit 0
fi

echo "--- launchctl list (ai.omninode.*) ---"
launchctl list | grep ai.omninode || echo "  (none found)"

if [[ ${FAILED} -gt 0 ]]; then
  echo "" >&2
  echo "ERROR: ${FAILED} tick(s) failed to load. Plists were written to ${LAUNCH_AGENTS} but are not running." >&2
  exit 1
fi
