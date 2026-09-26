#!/bin/bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# Install the gh user shim (OMN-19479) into a user bin directory.
#
# Usage: install-gh-shim.sh [--bin-dir DIR] [--check]
#   --bin-dir DIR  where to install (default: $HOME/.local/bin)
#   --check        verify only; install nothing
#
# Refuses (exit 2) when DIR is not on PATH ahead of the real gh, because the
# shim would then never run and the install would look done while doing
# nothing. Refuses (exit 3) to overwrite a gh in DIR that is not a copy of this
# shim. The PATH checked is the PATH this script runs with: run it from the
# session whose gh calls the shim should see.

set -euo pipefail

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="$SRC_DIR/gh"
ROUTER_SRC="$SRC_DIR/gh_route.py"
BIN_DIR="$HOME/.local/bin"
CHECK_ONLY=0
while [ $# -gt 0 ]; do
  case "$1" in
    --bin-dir) BIN_DIR="$2"; shift 2 ;;
    --check) CHECK_ONLY=1; shift ;;
    *) echo "install-gh-shim: unknown argument: $1" >&2; exit 64 ;;
  esac
done

[ -f "$SRC" ] || { echo "install-gh-shim: shim source missing: $SRC" >&2; exit 1; }
[ -f "$ROUTER_SRC" ] || { echo "install-gh-shim: router source missing: $ROUTER_SRC" >&2; exit 1; }

# Not `head | grep -q` under pipefail: grep -q can exit before head finishes,
# and head's SIGPIPE status would then read as "not a shim".
is_shim() {
  local h
  h="$(head -c 512 "$1" 2>/dev/null | LC_ALL=C tr -d '\000')"
  case "$h" in *ONEX_GH_USER_SHIM*) return 0 ;; esac
  return 1
}

# Position of BIN_DIR and of the first directory holding a real (non-shim) gh.
bin_pos=-1
real_pos=-1
real_path=""
i=0
# Split by parameter expansion, not `read <<< "$PATH"`: under Homebrew bash
# 5.3.9 that read hung this installer twice at 2026-09-25T14:52Z (load average
# 72); it did not reproduce at 15:05Z. This form needs no here-string at all.
rest="$PATH:"
while [ -n "$rest" ]; do
  d="${rest%%:*}"
  rest="${rest#*:}"
  i=$((i + 1))
  [ -n "$d" ] || continue
  if [ "$bin_pos" -lt 0 ] && [ "$d" -ef "$BIN_DIR" ]; then
    bin_pos=$i
  fi
  c="$d/gh"
  if [ "$real_pos" -lt 0 ] && [ -f "$c" ] && [ -x "$c" ] \
     && ! is_shim "$c"; then
    real_pos=$i
    real_path="$c"
  fi
done

if [ "$real_pos" -lt 0 ]; then
  echo "install-gh-shim: REFUSED: no real gh on PATH" >&2
  exit 2
fi
if [ "$bin_pos" -lt 0 ]; then
  echo "install-gh-shim: REFUSED: $BIN_DIR is not on PATH; the shim would never run" >&2
  exit 2
fi
if [ "$bin_pos" -gt "$real_pos" ]; then
  echo "install-gh-shim: REFUSED: $BIN_DIR (PATH position $bin_pos) comes after the real gh $real_path (position $real_pos); the shim would never run" >&2
  exit 2
fi

DEST="$BIN_DIR/gh"
ROUTER_DEST="$BIN_DIR/gh_route.py"
if [ -e "$DEST" ] && ! is_shim "$DEST"; then
  echo "install-gh-shim: REFUSED: $DEST exists and is not the gh shim; not overwriting it" >&2
  exit 3
fi

if [ "$CHECK_ONLY" -eq 1 ]; then
  if [ ! -f "$ROUTER_DEST" ]; then
    echo "install-gh-shim: CHECK: $ROUTER_DEST is missing"
  elif cmp -s "$ROUTER_SRC" "$ROUTER_DEST"; then
    echo "install-gh-shim: CHECK: $ROUTER_DEST is present and identical to source"
  else
    echo "install-gh-shim: CHECK: $ROUTER_DEST differs from source"
  fi
  echo "install-gh-shim: OK (check only): $BIN_DIR at PATH position $bin_pos is ahead of $real_path at $real_pos"
  exit 0
fi

mkdir -p "$BIN_DIR"
tmp="$DEST.tmp.$$"
cp "$SRC" "$tmp"
chmod 0755 "$tmp"
mv -f "$tmp" "$DEST"
router_tmp="$ROUTER_DEST.tmp.$$"
cp "$ROUTER_SRC" "$router_tmp"
chmod 0755 "$router_tmp"
mv -f "$router_tmp" "$ROUTER_DEST"
echo "install-gh-shim: installed $DEST and $ROUTER_DEST (ahead of $real_path); real gh resolves by walking PATH past the shim"
