#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
# Serve omnidash dev from a checkout this tick owns; never write the canonical clone.
#
# The tenant-scoped widgets read their tenant from src/config/generated/data-source-defaults.ts,
# built from the gitignored contract.local.yaml overlay. That file is tracked and the hardcoded-LAN
# gate refuses a commit of the built values, so building it inside the canonical clone leaves the
# clone dirty and clone sync resets it. The tick therefore serves a private local clone under its
# state directory: it moves that clone to the canonical clone's origin/dev ref (a local-path fetch,
# no network; canonical-clone-sync owns the canonical clone's git state), copies the overlay files
# in, runs generate:config there and starts vite from it.
set -euo pipefail

: "${OMNI_HOME:?OMNI_HOME must be set}"
CLONE="$OMNI_HOME/omnidash"
STATE_DIR="${ONEX_STATE_DIR:-$OMNI_HOME/.onex_state}/omnidash-lab-dev"
SERVE="$STATE_DIR/serve/omnidash"
SERVED_HEAD_FILE="$STATE_DIR/served_head"
SERVED_OVERLAY_FILE="$STATE_DIR/served_overlay"
SOURCE_REF="${OMNIDASH_LAB_DEV_REF:-refs/remotes/origin/dev}"
# Gitignored files the canonical clone holds and the dev server needs; values are never logged.
OVERLAY_FILES=(contract.local.yaml .env .env.local)
VITE_COMMAND='vite --host 0.0.0.0 --port 3001 --strictPort'

log() { printf '[%s] %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$*"; }

if [[ ! -e "$CLONE/.git" || ! -f "$CLONE/package.json" ]]; then
  log "missing clone or package.json: $CLONE"
  exit 1
fi

head="$(git -C "$CLONE" rev-parse --verify "$SOURCE_REF^{commit}")"
overlay_hash="$(
  for name in "${OVERLAY_FILES[@]}"; do
    if [[ -f "$CLONE/$name" ]]; then
      printf '%s\n' "$name"
      cat "$CLONE/$name"
    fi
  done | shasum -a 256 | cut -d' ' -f1
)"
served_head=''
if [[ -f "$SERVED_HEAD_FILE" ]]; then
  served_head="$(cat "$SERVED_HEAD_FILE")"
fi
served_overlay=''
if [[ -f "$SERVED_OVERLAY_FILE" ]]; then
  served_overlay="$(cat "$SERVED_OVERLAY_FILE")"
fi
# Match the entire vite argument tail, allowing the node/vite binary prefix.
# Read all input to avoid SIGPIPE with pipefail; never select grep itself.
# Required ps/grep command matching also supplies the process group ID.
# shellcheck disable=SC2009
pgid="$(ps -axo pid,pgid,command | grep -F "$VITE_COMMAND" | grep -v '[g]rep' |
  awk '$2 ~ /^[0-9]+$/ && $0 ~ /(^|[ \/])vite --host 0[.]0[.]0[.]0 --port 3001 --strictPort$/ {if (!found) print $2; found=1}' || true)"

if [[ -n "$pgid" && "$head" == "$served_head" && "$overlay_hash" == "$served_overlay" ]]; then
  exit 0
fi

# Everything below writes only to the private checkout and the state directory.
mkdir -p "$STATE_DIR"
if [[ ! -e "$SERVE/.git" ]]; then
  mkdir -p "$(dirname "$SERVE")"
  git clone --quiet --local --no-checkout "$CLONE" "$SERVE"
fi
# Local-path fetch: reads the canonical clone's ref, writes only the private checkout.
git -C "$SERVE" fetch --quiet --no-tags "$CLONE" "+$SOURCE_REF:refs/lab/served"
git -C "$SERVE" checkout --quiet --force --detach "$head"

for name in "${OVERLAY_FILES[@]}"; do
  if [[ -f "$CLONE/$name" ]]; then
    cp -p "$CLONE/$name" "$SERVE/$name"
  else
    rm -f "$SERVE/$name"
  fi
done
# Saved dashboard layouts are ignored runtime data: seed them, never overwrite what was saved here.
if [[ -d "$CLONE/dashboard-layouts" ]]; then
  mkdir -p "$SERVE/dashboard-layouts"
  cp -Rn "$CLONE/dashboard-layouts/." "$SERVE/dashboard-layouts/" 2>/dev/null || true
fi

install_dependencies=false
if [[ ! -d "$SERVE/node_modules" ]]; then
  install_dependencies=true
elif [[ -n "$served_head" ]]; then
  if git -C "$SERVE" diff --quiet "$served_head" "$head" -- package-lock.json; then
    :
  else
    diff_status=$?
    # A broken revision must not masquerade as a changed lockfile.
    [[ "$diff_status" -eq 1 ]] || exit "$diff_status"
    install_dependencies=true
  fi
fi
if [[ "$install_dependencies" == true ]]; then
  (cd "$SERVE" && npm ci --prefer-offline --no-audit --no-fund)
fi

# Build the tenant-bearing defaults before stopping the running server, so a failed build keeps it up.
(cd "$SERVE" && npm run generate:config)

reason="not running"
if [[ -n "$pgid" ]]; then
  if [[ "$head" != "$served_head" ]]; then
    reason="head moved $served_head->$head"
  else
    reason="overlay changed"
  fi
  kill -TERM -- "-$pgid"
  sleep 2
fi

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

cd "$SERVE"
# Job control gives npm/vite a separate process group for the next tick's kill.
set -m
nohup npm run dev -- --host 0.0.0.0 --port 3001 --strictPort > "${OMNIDASH_LAB_DEV_LOG:-/tmp/omnidash-lab-dev-3001.log}" 2>&1 &
disown
printf '%s\n' "$head" > "$SERVED_HEAD_FILE"
printf '%s\n' "$overlay_hash" > "$SERVED_OVERLAY_FILE"
log "started: $reason"
