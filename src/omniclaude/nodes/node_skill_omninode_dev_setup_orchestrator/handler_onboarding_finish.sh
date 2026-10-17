#!/bin/bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
# Bash finish-step handler for node_skill_omninode_dev_setup_orchestrator.
# Sourced by lab-onboarding.sh, after sha256 verification, only when
# ONEX_SKILL_OVERLAY_ROOTS was set. The caller supplies FINISH_OVERLAY_ROOTS
# (read before it unsets the inherited ONEX_* variables), IS_TTY, RUN_DIR,
# WORKSPACE, say, os_name and brew_bin, and calls finish_step prepare in
# preflight, finish_step start after phase 1 and finish_step play last.
#
# Off unless the onboarding node's deployment overlay turns it on: the first
# <root>/node_onboarding/overlay.yaml under the roots ONEX_SKILL_OVERLAY_ROOTS
# lists (colon separated), with
#   finish_greeting_enabled: "true"
# An absent variable, file or field, or "false", leaves it off; any other value
# is named in a preflight note and leaves it off. Off, it asks nothing, builds
# nothing and plays nothing. On, and only on macOS in an interactive terminal on
# this Mac (not over SSH): preflight finds the first name (from the account,
# else the home directory's name when it reads as a name, else asked once with
# the other questions), a clip is built in the background once phase 1 has
# installed Python, and it plays once after the completion lines. Any failure
# skips it silently; it never fails onboarding. macOS's say is called by its
# path, because the caller's own say() prints to the terminal.
#
# The two recorded clips sit in the plugin beside the entrypoint. A copy without
# them fetches each from a pinned commit and checks its sha256, the way the
# entrypoint fetches its handlers; the values are written in groups and joined.
# TODO: FINISH_ASSETS_COMMIT names the branch commit that added the clips; at
# landing it must move to the merge commit on dev.
FINISH_OVERLAY_NODE="node_onboarding"
FINISH_OVERLAY_FIELD="finish_greeting_enabled"
FINISH_ASSETS_REL="plugins/onex/skills/_bin/assets/finish"
FINISH_ASSETS_COMMIT="7145:9d39:1143:7307:dde4:dedf:734e:ee71:ecda:da8e"
FINISH_WELCOME_SHA256="099b:47c4:ab85:13a1:45b5:6754:2c5f:39b4:e171:85c4:021b:9c30:26d9:8660:744a:0fd0"
FINISH_CLOSE_SHA256="2173:614d:c1e3:4c37:f800:96f9:2172:327b:e8f7:afd4:54bc:f3f3:9196:55b3:27fc:f2bb"
FINISH_ASSETS_COMMIT="${FINISH_ASSETS_COMMIT//:/}"
FINISH_WELCOME_SHA256="${FINISH_WELCOME_SHA256//:/}"
FINISH_CLOSE_SHA256="${FINISH_CLOSE_SHA256//:/}"
FINISH_HANDLER_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd)"
FINISH_NAME=""
FINISH_WORK=""
FINISH_PID=""

finish_overlay_file() { # -> the first <root>/node_onboarding/overlay.yaml, in root order
  local rest="${FINISH_OVERLAY_ROOTS:-}" root
  while [ -n "$rest" ]; do
    root="${rest%%:*}"
    if [ "$root" = "$rest" ]; then rest=""; else rest="${rest#*:}"; fi
    if [ -n "$root" ] && [ -f "$root/$FINISH_OVERLAY_NODE/overlay.yaml" ]; then
      printf '%s\n' "$root/$FINISH_OVERLAY_NODE/overlay.yaml"
      return 0
    fi
  done
  return 1
}

finish_enabled() {
  local file line value
  file="$(finish_overlay_file)" || return 1
  line="$(grep -E "^$FINISH_OVERLAY_FIELD:" "$file" 2>/dev/null | tail -n 1)"
  [ -n "$line" ] || return 1
  value="${line#"$FINISH_OVERLAY_FIELD":}"
  value="$(printf '%s' "${value%%#*}" | tr -d "[:space:]\"'" | tr '[:upper:]' '[:lower:]')"
  case "$value" in
    true) return 0 ;;
    false) return 1 ;;
    *) say "  Note: $file: $FINISH_OVERLAY_FIELD must be \"true\" or \"false\", not '$value'; leaving it off."; return 1 ;;
  esac
}

finish_terminal_ok() {
  [ "$(os_name)" = "Darwin" ] && [ "$IS_TTY" -eq 1 ] &&
    [ -z "${SSH_CONNECTION:-}${SSH_CLIENT:-}${SSH_TTY:-}" ] &&
    [ -x /usr/bin/say ] && [ -x /usr/bin/afplay ]
}

finish_name_like() {
  case "$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]')" in
    ""|admin|administrator|user|users|mac|macbook|macuser|test|guest|root|dev|developer|owner|me|home|runner|ci|build|staff|default|shared) return 1 ;;
  esac
  printf '%s' "$1" | grep -Eq "^[A-Za-z][A-Za-z'-]{1,19}$"
}

finish_prepare() { # preflight: the name, asked only when the account does not give one
  finish_enabled && finish_terminal_ok || return 0
  local candidate
  candidate="$(id -F 2>/dev/null | awk '{print $1}')"
  finish_name_like "$candidate" || candidate="$(basename "$HOME")"
  if ! finish_name_like "$candidate"; then
    say ""
    printf '  What should we call you? '
    IFS= read -r candidate || candidate=""
    candidate="$(printf '%s' "$candidate" | awk '{print $1}')"
    finish_name_like "$candidate" || return 0
  fi
  FINISH_NAME="$(printf '%s' "${candidate:0:1}" | tr '[:lower:]' '[:upper:]')${candidate:1}"
}

finish_asset() { # file sha256 -> stdout: a copy with that digest
  local candidate
  for candidate in "$FINISH_HANDLER_DIR/../../../../$FINISH_ASSETS_REL/$1" "$(dirname "$0")/assets/finish/$1" \
    "$WORKSPACE/omniclaude/$FINISH_ASSETS_REL/$1"; do
    [ -f "$candidate" ] || continue
    if printf '%s  %s\n' "$2" "$candidate" | shasum -a 256 -c - >/dev/null 2>&1; then
      printf '%s\n' "$candidate"; return 0
    fi
  done
  candidate="$FINISH_WORK/$1"
  curl -fsSL --retry 3 --max-time 60 -o "$candidate" \
    "https://raw.githubusercontent.com/OmniNode-ai/omniclaude/$FINISH_ASSETS_COMMIT/$FINISH_ASSETS_REL/$1" &&
    printf '%s  %s\n' "$2" "$candidate" | shasum -a 256 -c - >/dev/null 2>&1 &&
    printf '%s\n' "$candidate"
}

finish_python() { # Homebrew's, else the command-line tools' (never the stub that opens an installer)
  local p prefix
  prefix="$(brew_bin)"; prefix="${prefix%/brew}"
  if [ -n "$prefix" ]; then
    for p in "$prefix/python3.13" "$prefix/python3"; do
      [ -x "$p" ] && { printf '%s\n' "$p"; return 0; }
    done
  fi
  xcode-select -p >/dev/null 2>&1 && [ -x /usr/bin/python3 ] && printf '%s\n' /usr/bin/python3
}

# One clip (recorded welcome, the name in the Fred voice, recorded close), each
# trimmed with 0.04 s between them, so it plays in a single afplay: each afplay
# adds about a second of silence, so playing the pieces one by one leaves gaps.
finish_build() {
  local welcome close py
  welcome="$(finish_asset welcome.wav "$FINISH_WELCOME_SHA256")" || return 1
  close="$(finish_asset to-omninode.wav "$FINISH_CLOSE_SHA256")" || return 1
  py="$(finish_python)" || return 1
  /usr/bin/say -v Fred --file-format=WAVE --data-format=LEI16@22050 -o "$FINISH_WORK/name.wav" "$FINISH_NAME" || return 1
  "$py" - "$welcome" "$FINISH_WORK/name.wav" "$close" "$FINISH_WORK/finish.part.wav" <<'PY' || return 1
import array, sys, wave
*parts, out = sys.argv[1:]
rate, samples = None, array.array("h")
for i, path in enumerate(parts):
    with wave.open(path) as w:
        rate = rate or w.getframerate()
        a = array.array("h", w.readframes(w.getnframes()))
    loud = [j for j, s in enumerate(a) if abs(s) > 500] or [0, len(a) - 1]
    pad = rate // 100
    samples.extend(a[max(loud[0] - pad, 0): loud[-1] + pad])
    if i < len(parts) - 1:
        samples.extend([0] * int(rate * 0.04))
with wave.open(out, "wb") as o:
    o.setnchannels(1); o.setsampwidth(2); o.setframerate(rate); o.writeframes(samples.tobytes())
PY
  mv "$FINISH_WORK/finish.part.wav" "$FINISH_WORK/finish.wav"
}

finish_start() { # after phase 1, in the background; a run that stopped earlier left its clip here
  [ -n "$FINISH_NAME" ] || return 0
  rm -rf "$RUN_DIR"/finish.*
  FINISH_WORK="$(mktemp -d "$RUN_DIR/finish.XXXXXX" 2>/dev/null)" || { FINISH_WORK=""; return 0; }
  finish_build </dev/null >/dev/null 2>&1 &
  FINISH_PID=$!
}

finish_play() { # once, at the very end
  [ -n "$FINISH_PID" ] || return 0
  local n=0
  while kill -0 "$FINISH_PID" 2>/dev/null && [ "$n" -lt 20 ]; do sleep 0.5; n=$((n + 1)); done
  if [ -f "$FINISH_WORK/finish.wav" ] && finish_terminal_ok; then
    /usr/bin/afplay "$FINISH_WORK/finish.wav" >/dev/null 2>&1
  fi
  rm -rf "$FINISH_WORK"
}

finish_step() { # prepare | start | play
  case "$1" in
    prepare) finish_prepare ;;
    start) finish_start ;;
    play) finish_play ;;
  esac
  return 0
}
