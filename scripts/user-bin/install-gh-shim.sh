#!/bin/bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# Install the gh user shim (OMN-19479, OMN-19856) into a lanes-only directory.
#
# Usage: install-gh-shim.sh [--bin-dir DIR] [--check]
#   --bin-dir DIR  override the default lanes-only directory:
#                  ${ONEX_LANE_BIN_DIR:-${XDG_DATA_HOME:-$HOME/.local/share}/omni/lane-bin}
#   --check        verify only; install or retire nothing
#
# Only lane environments put the default directory on PATH; the installing
# shell need not do so. A successful default install retires a legacy shim
# and its router from $HOME/.local/bin, which CI may put on PATH.
# With explicit --bin-dir, refuses (exit 2) unless DIR is on PATH ahead of the
# real gh. All installs require a real gh on PATH (exit 2), and refuse (exit 3)
# to overwrite a gh in DIR that is not a copy of this shim.
#
# Stale copies (OMN-22447): a shim copy anywhere on PATH that lacks the CI pass-through
# (OMN-19856: GITHUB_ACTIONS exactly true execs the real gh) refuses a CI job's own
# PR-body read; deploy-gate on the cloud repo PR 2013 failed that way (job 126037381765).
# An install refreshes each such copy in place from this source (and its router when
# one sits beside it). --check names each one and exits 4. A copy in a directory that
# cannot be written is named and the install exits 4.
#
# This file is on the canonical-file-shape baseline: its code lines may not grow, so the
# body below is written compactly (a comment line does not count).

set -euo pipefail

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="$SRC_DIR/gh"
ROUTER_SRC="$SRC_DIR/gh_route.py"
BIN_DIR="${ONEX_LANE_BIN_DIR:-${XDG_DATA_HOME:-$HOME/.local/share}/omni/lane-bin}"
EXPLICIT_BIN_DIR=0
CHECK_ONLY=0
die() { echo "install-gh-shim: $2" >&2; exit "$1"; }
while [ $# -gt 0 ]; do
  case "$1" in
    --bin-dir) BIN_DIR="$2"; EXPLICIT_BIN_DIR=1; shift 2 ;;
    --check) CHECK_ONLY=1; shift ;;
    *) die 64 "unknown argument: $1" ;;
  esac
done

[ -f "$SRC" ] || die 1 "shim source missing: $SRC"
[ -f "$ROUTER_SRC" ] || die 1 "router source missing: $ROUTER_SRC"

# Not `head | grep -q` under pipefail: grep -q can exit before head finishes,
# and head's SIGPIPE status would then read as "not a shim".
is_shim() { local h; h="$(head -c 512 "$1" 2>/dev/null | LC_ALL=C tr -d '\000')"; case "$h" in *ONEX_GH_USER_SHIM*) return 0 ;; esac; return 1; }
# The CI pass-through is the shim's test of GITHUB_ACTIONS against exactly true. Fixed-string
# match on the source line, so false, 1 and TRUE never count. A missing file is not a stale copy.
PT='"${GITHUB_ACTIONS:-}" = "true"'
stale_copy() { is_shim "$1" && ! grep -qF "$PT" "$1"; }
# Install one file atomically with mode 0755.
put() { cp "$1" "$2.tmp.$$" && chmod 0755 "$2.tmp.$$" && mv -f "$2.tmp.$$" "$2"; }

# Position of BIN_DIR and of the first directory holding a real (non-shim) gh; every
# shim copy on PATH without the CI pass-through is collected in $stale, one per line.
bin_pos=-1; real_pos=-1; real_path=""; i=0; stale=""
# Split by parameter expansion, not `read <<< "$PATH"`: under Homebrew bash
# 5.3.9 that read hung this installer twice at 2026-09-25T14:52Z (load average
# 72); it did not reproduce at 15:05Z. This form needs no here-string at all.
rest="$PATH:"
while [ -n "$rest" ]; do
  d="${rest%%:*}"; rest="${rest#*:}"; i=$((i + 1))
  [ -n "$d" ] || continue
  if [ "$bin_pos" -lt 0 ] && [ "$d" -ef "$BIN_DIR" ]; then bin_pos=$i; fi
  c="$d/gh"
  if [ -f "$c" ] && stale_copy "$c"; then stale="$stale$c"$'\n'; fi
  if [ "$real_pos" -lt 0 ] && [ -f "$c" ] && [ -x "$c" ] && ! is_shim "$c"; then real_pos=$i; real_path="$c"; fi
done

[ "$real_pos" -ge 0 ] || die 2 "REFUSED: no real gh on PATH"
if [ "$EXPLICIT_BIN_DIR" -eq 1 ]; then
  [ "$bin_pos" -ge 0 ] || die 2 "REFUSED: $BIN_DIR is not on PATH; the shim would never run"
  [ "$bin_pos" -le "$real_pos" ] || die 2 "REFUSED: $BIN_DIR (PATH position $bin_pos) comes after the real gh $real_path (position $real_pos); the shim would never run"
fi

DEST="$BIN_DIR/gh"; ROUTER_DEST="$BIN_DIR/gh_route.py"
LEGACY_GH="$HOME/.local/bin/gh"; LEGACY_ROUTER="$HOME/.local/bin/gh_route.py"
if [ -e "$DEST" ] && ! is_shim "$DEST"; then die 3 "REFUSED: $DEST exists and is not the gh shim; not overwriting it"; fi
if [ -f "$DEST" ] && stale_copy "$DEST"; then stale="$stale$DEST"$'\n'; fi

if [ "$CHECK_ONLY" -eq 1 ]; then
  if [ "$EXPLICIT_BIN_DIR" -eq 0 ] && [ -e "$LEGACY_GH" ] && is_shim "$LEGACY_GH"; then echo "install-gh-shim: CHECK: legacy shim $LEGACY_GH is present"; fi
  if [ ! -f "$ROUTER_DEST" ]; then s="is missing"; elif cmp -s "$ROUTER_SRC" "$ROUTER_DEST"; then s="is present and identical to source"; else s="differs from source"; fi
  echo "install-gh-shim: CHECK: $ROUTER_DEST $s"
  if [ -n "$stale" ]; then
    printf '%s' "$stale" | sort -u | while IFS= read -r c; do echo "install-gh-shim: STALE: $c is a gh shim copy without the CI pass-through (OMN-22447)" >&2; done
    exit 4
  fi
  if [ "$EXPLICIT_BIN_DIR" -eq 1 ]; then echo "install-gh-shim: OK (check only): $BIN_DIR at PATH position $bin_pos is ahead of $real_path at $real_pos"; else echo "install-gh-shim: OK (check only): lanes-only directory $BIN_DIR; real gh is $real_path"; fi
  exit 0
fi

mkdir -p "$BIN_DIR"; put "$SRC" "$DEST"; put "$ROUTER_SRC" "$ROUTER_DEST"
if [ "$EXPLICIT_BIN_DIR" -eq 1 ]; then
  echo "install-gh-shim: installed $DEST and $ROUTER_DEST (ahead of $real_path); real gh resolves by walking PATH past the shim"
else
  echo "install-gh-shim: installed $DEST and $ROUTER_DEST (lanes-only); real gh is $real_path"
  # An override may name the legacy directory itself; never retire this install.
  if [ -e "$LEGACY_GH" ] && [ ! "$LEGACY_GH" -ef "$DEST" ] && is_shim "$LEGACY_GH"; then
    rm "$LEGACY_GH"; retired="$LEGACY_GH"
    if [ -e "$LEGACY_ROUTER" ] || [ -L "$LEGACY_ROUTER" ]; then rm -f "$LEGACY_ROUTER"; retired="$retired and $LEGACY_ROUTER"; fi
    echo "install-gh-shim: retired legacy $retired"
  fi
fi

# Refresh, in place, every other shim copy on PATH that still lacks the CI pass-through
# (a retired legacy copy, the install target and a second name for one file no longer match).
rc=0; set -f; IFS=$'\n'
for c in $stale; do
  stale_copy "$c" || continue
  if [ -w "${c%/*}" ] && put "$SRC" "$c"; then
    if [ -f "${c%/*}/gh_route.py" ]; then put "$ROUTER_SRC" "${c%/*}/gh_route.py"; fi
    echo "install-gh-shim: refreshed stale copy $c (it lacked the CI pass-through, OMN-22447)"
  else
    echo "install-gh-shim: STALE: $c lacks the CI pass-through and cannot be refreshed; refresh it as its owner (OMN-22447)" >&2; rc=4
  fi
done
exit "$rc"
