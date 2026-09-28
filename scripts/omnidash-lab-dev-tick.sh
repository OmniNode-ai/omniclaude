#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
# Serve the canonical omnidash clone; canonical-clone-sync owns git updates.
set -euo pipefail

: "${OMNI_HOME:?OMNI_HOME must be set}"
CLONE="$OMNI_HOME/omnidash"
STATE_DIR="${ONEX_STATE_DIR:-$OMNI_HOME/.onex_state}/omnidash-lab-dev"
SERVED_HEAD_FILE="$STATE_DIR/served_head"
VITE_COMMAND='vite --host 0.0.0.0 --port 3001 --strictPort'

log() { printf '[%s] %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$*"; }

if [[ ! -e "$CLONE/.git" || ! -f "$CLONE/package.json" ]]; then
  log "missing clone or package.json: $CLONE"
  exit 1
fi

head="$(git -C "$CLONE" rev-parse HEAD)"
served_head=''
if [[ -f "$SERVED_HEAD_FILE" ]]; then
  served_head="$(cat "$SERVED_HEAD_FILE")"
fi
# Match the entire vite argument tail, allowing the node/vite binary prefix.
# Read all input to avoid SIGPIPE with pipefail; never select grep itself.
# Required ps/grep command matching also supplies the process group ID.
# shellcheck disable=SC2009
pgid="$(ps -axo pid,pgid,command | grep -F "$VITE_COMMAND" | grep -v '[g]rep' |
  awk '$2 ~ /^[0-9]+$/ && $0 ~ /(^|[ \/])vite --host 0[.]0[.]0[.]0 --port 3001 --strictPort$/ {if (!found) print $2; found=1}' || true)"

install_dependencies=false
if [[ ! -d "$CLONE/node_modules" ]]; then
  install_dependencies=true
elif [[ -n "$served_head" ]]; then
  if git -C "$CLONE" diff --quiet "$served_head" HEAD -- package-lock.json; then
    :
  else
    diff_status=$?
    # A broken revision must not masquerade as a changed lockfile.
    [[ "$diff_status" -eq 1 ]] || exit "$diff_status"
    install_dependencies=true
  fi
fi
if [[ "$install_dependencies" == true ]]; then
  (cd "$CLONE" && npm ci --prefer-offline --no-audit --no-fund)
fi

if [[ -n "$pgid" && "$head" == "$served_head" ]]; then
  exit 0
fi

reason="not running"
if [[ -n "$pgid" ]]; then
  reason="head moved $served_head->$head"
  kill -TERM -- "-$pgid"
  sleep 2
fi

mkdir -p "$STATE_DIR"
env_file="${OMNIDASH_LAB_DEV_ENV_FILE:-$HOME/.omnibase/omnidash-lab-dev.env}"
if [[ -f "$env_file" ]]; then
  exports_before="$(export -p)"
  set -a
  # shellcheck disable=SC1090
  source "$env_file"
  set +a
  # Compare declarations in memory, but emit only names, including changed
  # values of variables that were already exported by the parent environment.
  exported_names="$(comm -13 <(printf '%s\n' "$exports_before" | LC_ALL=C sort) \
    <(export -p | LC_ALL=C sort) |
    sed -nE 's/^declare -x ([a-zA-Z_][a-zA-Z0-9_]*)(=.*)?$/\1/p' | paste -sd ' ' -)"
  log "exported variables: $exported_names"
fi

cd "$CLONE"
# Job control gives npm/vite a separate process group for the next tick's kill.
set -m
nohup npm run dev -- --host 0.0.0.0 --port 3001 --strictPort > "${OMNIDASH_LAB_DEV_LOG:-/tmp/omnidash-lab-dev-3001.log}" 2>&1 &
disown
printf '%s\n' "$head" > "$SERVED_HEAD_FILE"
log "started: $reason"
