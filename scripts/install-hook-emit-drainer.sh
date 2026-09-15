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
PLUGIN_ROOT="${OMNICLAUDE_ROOT}/plugins/onex"
PLUGIN_DATA="${CLAUDE_PLUGIN_DATA:-${HOME}/.claude/plugins/data/onex-omninode-tools}"
DAEMON_PYTHON="${PLUGIN_DATA}/.venv/bin/python3"
LABEL="ai.omninode.hook-emit-drainer"
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

  STATE_DIR="${ONEX_STATE_DIR:-${OMNI_HOME_RESOLVED}/.onex_state}"
  JOURNAL="${STATE_DIR}/hook_emit_journal"
  echo "Journal: ${JOURNAL}"
  shopt -s nullglob
  pending=("${JOURNAL}"/*.json)
  echo "Pending: ${#pending[@]}"

  # OMN-17284: the emit spool is a SECOND backlog with a different cause.
  # omnibase_infra's receipt-mode CLI writes here when the emit daemon's Unix
  # socket is unreachable, so a deep spool means "no emit daemon", which the
  # drainer does not fix and this command used not to mention at all. On the
  # operator Mac 2026-09-15 the journal was full AND 736 records sat here, and
  # only one of the two numbers was visible.
  SPOOL="${STATE_DIR}/emit_spool"
  spooled=("${SPOOL}"/*.json)
  echo "Spool:   ${SPOOL} (emit_spool)"
  echo "Spooled: ${#spooled[@]}"
  shopt -u nullglob

  # Validate the plist this command just named. `launchctl print` reports
  # launchd's IN-MEMORY copy, which can be a previous, good version of a file
  # that has since been overwritten -- exactly the state measured on
  # 2026-09-15, where the service looked healthy for two days while the file on
  # disk was a bare JSON array with no KeepAlive. Liveness is not validity.
  #
  # plistlib rather than `plutil` on purpose: it is stdlib, so this check runs
  # wherever python3 does, which is what gives this path a CI home.
  echo "Plist checks:"
  if ! PLIST_PATH="${DST_PLIST}" python3 - <<'PY'
import os
import plistlib
import sys

path = os.environ["PLIST_PATH"]
try:
    with open(path, "rb") as handle:
        payload = plistlib.load(handle)
except FileNotFoundError:
    print("  MISSING: no plist at this path")
    sys.exit(1)
except Exception as exc:  # plistlib raises several unrelated types
    print(f"  INVALID: {type(exc).__name__}: {exc}")
    sys.exit(1)

if not isinstance(payload, dict):
    print(f"  INVALID: top level is {type(payload).__name__}, expected a dict")
    sys.exit(1)

failures = []
if not payload.get("ProgramArguments"):
    failures.append("  MISSING KEY: ProgramArguments")
# KeepAlive is the property that makes a wedged or exited drainer self-healing.
# Without it launchd never restarts the process and the backlog grows silently.
if payload.get("KeepAlive") is not True:
    failures.append("  MISSING KEY: KeepAlive (drainer is NOT self-healing)")
if payload.get("RunAtLoad") is not True:
    failures.append("  MISSING KEY: RunAtLoad")
if payload.get("Label") != "ai.omninode.hook-emit-drainer":
    failures.append(f"  WRONG Label: {payload.get('Label')!r}")

for failure in failures:
    print(failure)
if failures:
    sys.exit(1)
print("  OK: parses, Label/ProgramArguments/KeepAlive/RunAtLoad all present")
PY
  then
    echo "" >&2
    echo "ERROR: the installed plist is invalid or has lost KeepAlive." >&2
    echo "       Reinstall it:" >&2
    echo "         bash omniclaude/scripts/install-hook-emit-drainer.sh" >&2
    exit 1
  fi
  exit 0
fi

# CLAUDE.md rule 11: the literal brew interpreter path. launchd runs with a
# restricted PATH so $(brew --prefix) is unavailable, and the macOS Local
# Network grant is per-binary — a uv-managed interpreter silently
# EHOSTUNREACHes on the LAN publish to the .201 broker.
#
# Resolved here rather than at the top of the file: --uninstall and --status
# launch nothing, so requiring the interpreter for a read-only query is what
# kept this script's tests off every runner in the fleet (ci.yml ignore list,
# OMN-18357).
if [[ -x "/opt/homebrew/bin/python3.13" ]]; then
  BREW_PYTHON="/opt/homebrew/bin/python3.13"   # local-path-ok: rule 11 literal (ARM)
elif [[ -x "/usr/local/bin/python3.13" ]]; then
  BREW_PYTHON="/usr/local/bin/python3.13"      # local-path-ok: rule 11 literal (Intel)
else
  echo "ERROR: brew python3.13 not found at either rule-11 path." >&2
  echo "       Install it (brew install python@3.13) before loading this agent." >&2
  exit 1
fi

if [[ "${1:-}" != "--dry-run" ]]; then
  export OMNI_HOME="${OMNI_HOME_RESOLVED}"
  export CLAUDE_PLUGIN_DATA="${PLUGIN_DATA}"
  export CLAUDE_PLUGIN_ROOT="${PLUGIN_ROOT}"
  export ONEX_BREW_PYTHON="${BREW_PYTHON}"
  bash "${PLUGIN_ROOT}/hooks/scripts/ensure-plugin-venv.sh"
  if ! bash "${PLUGIN_ROOT}/hooks/scripts/ensure-plugin-venv.sh" --verify; then
    echo "ERROR: lock-built plugin venv failed exact freshness verification." >&2
    exit 1
  fi
fi

echo "Rendering ${LABEL} plist..."
echo "  OMNI_HOME:   ${OMNI_HOME_RESOLVED}"
echo "  interpreter: ${DAEMON_PYTHON} (Brew-backed plugin venv)"

RENDERED="$(mktemp)"
BACKUP_PLIST=""
trap 'rm -f "${RENDERED}" "${BACKUP_PLIST}"' EXIT

sed -e "s|__OMNI_HOME__|${OMNI_HOME_RESOLVED}|g" \
    -e "s|__HOME__|${HOME}|g" \
    -e "s|__PYTHON__|${DAEMON_PYTHON}|g" \
    "${SRC_PLIST}" \
  | sed -e 's|<key>Disabled</key>|<key>Disabled</key>|' \
  | "${BREW_PYTHON}" -c "
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

had_previous_plist=0
if [[ -e "${DST_PLIST}" ]]; then
  BACKUP_PLIST="$(mktemp "${LAUNCH_AGENTS}/.${LABEL}.previous.XXXXXX")"
  if ! cp "${DST_PLIST}" "${BACKUP_PLIST}"; then
    echo "ERROR: could not preserve the current LaunchAgent plist." >&2
    exit 1
  fi
  had_previous_plist=1
fi

was_loaded=0
if launchctl print "gui/${UID_GUI}/${LABEL}" >/dev/null 2>&1; then
  was_loaded=1
fi

# OMN-17284: `launchctl bootout` returns BEFORE the domain has released the
# label. A bootstrap issued immediately after it fails with
# `Bootstrap failed: 5: Input/output error`, the installer rolls back, and the
# rollback's own bootstrap fails for the same reason -- so a reinstall over a
# RUNNING agent left the machine with no loaded drainer and the previous plist
# restored. Measured twice in a row on 2026-09-15 while repairing this exact
# service. A first install, with nothing loaded, never hits it, which is why it
# survived: the failure only appears on the repair path.
wait_for_label_released() {
  local deadline=$((SECONDS + 30))
  while launchctl print "gui/${UID_GUI}/${LABEL}" >/dev/null 2>&1; do
    if (( SECONDS >= deadline )); then
      echo "ERROR: ${LABEL} still loaded 30s after bootout; refusing to race it." >&2
      return 1
    fi
    sleep 1
  done
  return 0
}

restore_previous_service() {
  launchctl bootout "gui/${UID_GUI}/${LABEL}" 2>/dev/null || true
  wait_for_label_released || return 1
  if [[ "${had_previous_plist}" == "1" ]]; then
    cp "${BACKUP_PLIST}" "${DST_PLIST}" || return 1
  else
    rm -f "${DST_PLIST}"
  fi
  if [[ "${was_loaded}" == "1" ]]; then
    launchctl bootstrap "gui/${UID_GUI}" "${DST_PLIST}" || return 1
    launchctl enable "gui/${UID_GUI}/${LABEL}" || return 1
  fi
}

if ! cp "${RENDERED}" "${DST_PLIST}"; then
  echo "ERROR: could not install the rendered LaunchAgent plist; restoring prior plist." >&2
  if [[ "${had_previous_plist}" == "1" ]]; then
    cp "${BACKUP_PLIST}" "${DST_PLIST}" || echo "ERROR: prior plist restoration failed." >&2
  else
    rm -f "${DST_PLIST}"
  fi
  exit 1
fi

# Stop the old instance only after the candidate plist and its rollback copy
# are ready. Any activation error restores the prior plist and loaded service.
launchctl bootout "gui/${UID_GUI}/${LABEL}" 2>/dev/null || true
if ! wait_for_label_released; then
  echo "ERROR: could not unload the running ${LABEL}; restoring prior service." >&2
  restore_previous_service || echo "ERROR: prior LaunchAgent restoration failed." >&2
  exit 1
fi
if ! launchctl bootstrap "gui/${UID_GUI}" "${DST_PLIST}"; then
  echo "ERROR: could not bootstrap ${LABEL}; restoring prior service." >&2
  restore_previous_service || echo "ERROR: prior LaunchAgent restoration failed." >&2
  exit 1
fi
if ! launchctl enable "gui/${UID_GUI}/${LABEL}"; then
  echo "ERROR: could not enable ${LABEL}; restoring prior service." >&2
  restore_previous_service || echo "ERROR: prior LaunchAgent restoration failed." >&2
  exit 1
fi

echo "Loaded ${LABEL}."
echo
echo "Verify:"
echo "  bash omniclaude/scripts/install-hook-emit-drainer.sh --status"
echo "  tail -f ${OMNI_HOME_RESOLVED}/.onex_state/hooks/logs/hook-emit-drainer.log"
echo
echo "Expect at most ONE hook_emit_drainer.py process:"
echo "  pgrep -fl hook_emit_drainer.py"
