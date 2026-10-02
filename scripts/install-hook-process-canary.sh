#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# install-hook-process-canary.sh: install the live hook-process canary (OMN-20109).
#
# macOS: a KeepAlive LaunchAgent (scripts/launchd/ai.omninode.hook-process-canary.plist).
# Linux: a cron entry running the canary once a minute, under timeout(1).
# Either way the scripts are COPIED into a directory the canary owns, so a branch
# switch in a working tree never changes what a running canary executes.
#
# Usage:
#   bash scripts/install-hook-process-canary.sh --state-dir DIR [--ledger FILE] [--ledger-lock SCRIPT]
#   bash scripts/install-hook-process-canary.sh --state-dir DIR --status
#   bash scripts/install-hook-process-canary.sh --state-dir DIR --uninstall
#
# --state-dir is required, no default: it holds the heartbeat, ALERT.json, the log
# and the copied scripts (under DIR/repo-copy). --ledger and --ledger-lock name the
# rolling ledger the ALERT row is appended to and the locked-append script that writes it (a host without one, such as a lab
# host, omits both and relies on the operator notifier alone; the canary then
# reports that channel as not delivered on every alarm rather than pretending).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
LABEL="ai.omninode.hook-process-canary"
ACTION=install
STATE_DIR=""
LEDGER=""
LEDGER_LOCK=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --state-dir) STATE_DIR="${2:?--state-dir needs a value}"; shift 2 ;;
    --ledger) LEDGER="${2:?--ledger needs a value}"; shift 2 ;;
    --ledger-lock) LEDGER_LOCK="${2:?--ledger-lock needs a value}"; shift 2 ;;
    --status) ACTION=status; shift ;;
    --uninstall) ACTION=uninstall; shift ;;
    --dry-run) ACTION=dry-run; shift ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

[[ -n "${STATE_DIR}" ]] || { echo "install-hook-process-canary: --state-dir is required (no default)" >&2; exit 2; }
COPY_ROOT="${STATE_DIR}/repo-copy"
UID_GUI="$(id -u)"
DST_PLIST="${HOME}/Library/LaunchAgents/${LABEL}.plist"
CRON_TAG="# ${LABEL}"

resolve_python() {
  if [[ "$(uname -s)" == "Darwin" ]]; then
    # CLAUDE.md rule 11: the launchd job runs the brew python3.13 by its literal
    # resolved path (launchd has a restricted PATH, so no lookup at run time). The
    # path is resolved HERE, at install time, and written into the plist.
    local prefix found
    prefix="$(brew --prefix 2>/dev/null || true)"
    found="${prefix:+${prefix}/bin/python3.13}"
    [[ -n "${found}" && -x "${found}" ]] || { echo "install-hook-process-canary: no brew python3.13 (looked under \$(brew --prefix)/bin)" >&2; exit 1; }
    echo "${found}"
    return
  fi
  echo /usr/bin/python3
}

copy_scripts() {
  mkdir -p "${COPY_ROOT}/scripts" "${COPY_ROOT}/plugins/onex/hooks/scripts" "${STATE_DIR}"
  for f in hook_process_canary.py hook_canary_notify.sh hook_canary_ledger_append.sh; do
    install -m 0755 "${REPO_ROOT}/scripts/${f}" "${COPY_ROOT}/scripts/${f}"
  done
  install -m 0644 "${REPO_ROOT}/src/omniclaude/handlers/handler_ledger_write_guard.py" \
    "${COPY_ROOT}/scripts/handler_ledger_write_guard.py"
  install -m 0644 "${REPO_ROOT}/plugins/onex/hooks/scripts/alert-channel.sh" \
    "${COPY_ROOT}/plugins/onex/hooks/scripts/alert-channel.sh"
}

render_plist() {
  local python="$1" lock="${LEDGER_LOCK:-${ONEX_LEDGER_LOCK_SCRIPT:-}}" ledger="${LEDGER:-${ONEX_LEDGER_PATH:-}}"
  [[ -n "${lock}" ]] || { echo "install-hook-process-canary: set ONEX_LEDGER_LOCK_SCRIPT or --ledger-lock" >&2; exit 2; }
  [[ -n "${ledger}" ]] || { echo "install-hook-process-canary: set ONEX_LEDGER_PATH or --ledger" >&2; exit 2; }
  sed -e "s|__PYTHON__|${python}|g" -e "s|__ROOT__|${COPY_ROOT}|g" -e "s|__STATE_DIR__|${STATE_DIR}|g" \
      -e "s|__LEDGER_LOCK__|${lock}|g" -e "s|__LEDGER__|${ledger}|g" -e "s|__HOME__|${HOME}|g" \
      "${REPO_ROOT}/scripts/launchd/${LABEL}.plist"
}

cron_line() {
  local python="$1"
  local env_prefix="ONEX_STATE_DIR=${STATE_DIR}"
  [[ -n "${LEDGER}" ]] && env_prefix="${env_prefix} ONEX_LEDGER_PATH=${LEDGER} ONEX_LEDGER_LOCK_SCRIPT=${LEDGER_LOCK:?--ledger-lock is required with --ledger}"
  echo "* * * * * ${env_prefix} timeout 50 ${python} ${COPY_ROOT}/scripts/hook_process_canary.py --once --state-dir ${STATE_DIR} >> ${STATE_DIR}/canary.log 2>&1 ${CRON_TAG}"
}

case "${ACTION}" in
  status)
    if [[ "$(uname -s)" == "Darwin" ]]; then
      launchctl print "gui/${UID_GUI}/${LABEL}" 2>/dev/null | sed -n '1,14p' || echo "state: NOT LOADED"
    else
      crontab -l 2>/dev/null | grep -F "${CRON_TAG}" || echo "state: NOT INSTALLED"
    fi
    echo "heartbeat: $(cat "${STATE_DIR}/heartbeat.json" 2>/dev/null || echo none)"
    echo "alert:     $(cat "${STATE_DIR}/ALERT.json" 2>/dev/null || echo none)"
    ;;
  uninstall)
    if [[ "$(uname -s)" == "Darwin" ]]; then
      launchctl bootout "gui/${UID_GUI}/${LABEL}" 2>/dev/null || true
      rm -f "${DST_PLIST}"
    else
      { crontab -l 2>/dev/null | grep -vF "${CRON_TAG}" || true; } | crontab -
    fi
    echo "uninstalled ${LABEL}; the state directory ${STATE_DIR} is left in place"
    ;;
  dry-run)
    python="$(resolve_python)"
    if [[ "$(uname -s)" == "Darwin" ]]; then render_plist "${python}"; else cron_line "${python}"; fi
    ;;
  install)
    python="$(resolve_python)"
    copy_scripts
    if [[ "$(uname -s)" == "Darwin" ]]; then
      mkdir -p "${HOME}/Library/LaunchAgents"
      render_plist "${python}" > "${DST_PLIST}"
      plutil -lint "${DST_PLIST}" >/dev/null
      launchctl bootout "gui/${UID_GUI}/${LABEL}" 2>/dev/null || true
      # bootout is asynchronous: bootstrapping before the old job is gone fails with
      # "Input/output error" and leaves NOTHING loaded, so wait for it to go.
      for _ in $(seq 1 20); do
        launchctl print "gui/${UID_GUI}/${LABEL}" >/dev/null 2>&1 || break
        sleep 0.5
      done
      launchctl bootstrap "gui/${UID_GUI}" "${DST_PLIST}"
      launchctl kickstart -k "gui/${UID_GUI}/${LABEL}"
      launchctl print "gui/${UID_GUI}/${LABEL}" >/dev/null 2>&1 \
        || { echo "install-hook-process-canary: ${LABEL} is NOT loaded after bootstrap" >&2; exit 1; }
    else
      new_line="$(cron_line "${python}")"
      { crontab -l 2>/dev/null | grep -vF "${CRON_TAG}" || true; echo "${new_line}"; } | crontab -
    fi
    echo "installed ${LABEL}; state ${STATE_DIR}"
    ;;
esac
