#!/bin/bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# lab-onboarding.sh (the omninode_dev_setup skill) -- one command from a bare Mac to a developer machine that
# runs onex locally, on the developer's own model key. It never connects to the
# lab: everything runs on this Mac, natively and optionally in Docker.
#
# The file keeps its old name until the canonical-file-shape check carries a
# renamed file's baseline entry; the skill and command are omninode_dev_setup.
#
# Runs in phases. Each phase reports PASS or FAIL the moment it ends, in the
# terminal, as a macOS notification, and as a line in the status file, so a
# failure is never discovered at the end of a long run.
#
#   0 Preflight          reads the machine; changes nothing; your model key and the Docker question
#   1 Base tools         Xcode command-line tools, Homebrew, gh, jq, python@3.13, uv
#   2 Workspace          the canonical clones, OMNIBASE_PATH (and legacy OMNI_HOME), PATH
#   3 onex + model key   dispatch venv, onex, local identity, your own key, one delegation on it
#   4 Docker             optional: only if you said yes; Docker Desktop installed, or started
#                        if stopped, then the local stack on your key
#   5 Claude Code        the full onex plugin from your omniclaude clone, and omni and
#                        onex-overlays when this GitHub login can read omniclaude-internal
#   6 Verify             the checks for the selected modes, one line each
#
# Compatible with macOS's stock /bin/bash 3.2: no associative arrays, no
# ${var,,}, no mapfile, and no "${arr[@]}" of a possibly-empty array.
#
# Usage:
#   bash lab-onboarding.sh [options]
#
# Options:
#   --preflight-only     run phase 0, print the verdict, exit
#   --containers         answer the Docker question yes in advance
#   --no-containers      answer it no in advance
#                        (neither: the one question is asked after preflight)
#   --provider NAME      gemini | openrouter | openai | ollama   (default: asked up front).
#                        Gemini, OpenRouter and OpenAI take your own key; Ollama runs a
#                        model on this Mac, no key
#   --ollama-model NAME  the model Ollama downloads (default: chosen from this Mac's memory)
#   --workspace DIR      the workspace (default: $OMNIBASE_PATH, else $OMNI_HOME, else ~/code/omni)
#   --restart            forget completed phases and run every phase again
#   -h, --help           this text
#
# Exit codes: 0 all selected phases passed; 1 a phase failed; 2 bad usage;
#             3 this machine is below the minimum requirements (nothing installed);
#             4 the developer chose "Quit setup" before anything installed.

set -uo pipefail

# ---------------------------------------------------------------------------
# Minimum requirements. The single source for what preflight enforces.
# ---------------------------------------------------------------------------
M1_MACOS_MAJOR=14
M1_CPUS=4
M1_RAM_GB=8
M1_DISK_GB=20
M2_CPUS=8
M2_RAM_GB=16
# Disk, measured 2026-09-30 on a Mac running the stack: images 4.7 GB (the runtime
# image alone 3.6 GB), volumes about 6 GB, plus build cache during the first build.
M2_DISK_GB=30                 # free disk when Docker Desktop still has to be installed
M2_DISK_GB_DOCKER_PRESENT=20  # free disk when Docker Desktop is already installed
DOCKER_MEM_GB=10          # the local-dev guide's floor for Docker Desktop
DOCKER_CPUS=4
HOST_RESERVE_GB=6         # Docker Desktop never leaves the host less than this
BOOT_FREE_MEM_GB=4        # available memory required at the moment the stack boots
BOOT_FREE_DISK_GB=15      # free disk required at the moment the stack boots
MODE2_PORTS="5436 19092 16379 8085 8086"
VM_SPEC="a macOS 14 (or newer) VM with 4 vCPU, 8 GB RAM and 40 GB disk, on a host with that much to spare (Tart or UTM on an Apple-silicon Mac, or a hosted Mac such as EC2 Mac)"

REPOS="omnibase_compat omnibase_core omnibase_spi omnibase_infra omnimarket omniclaude omnidash"
GITHUB_ORG_URL="https://github.com/OmniNode-ai"

# At least 3 attempts, 5-10 s apart, for everything that touches the network.
RETRIES="${ONBOARD_RETRIES:-3}"
case "$RETRIES" in ''|*[!0-9]*) RETRIES=3 ;; esac
[ "$RETRIES" -lt 3 ] && RETRIES=3

# ---------------------------------------------------------------------------
# Arguments
# ---------------------------------------------------------------------------
PREFLIGHT_ONLY=0
WANT_CONTAINERS=""        # 1 --containers, 0 --no-containers, empty: ask
PROVIDER=""
# OMNIBASE_PATH is the workspace variable; OMNI_HOME is its legacy name, still
# read by the reconcile scripts this run drives, so both are honoured and set.
WORKSPACE="${OMNIBASE_PATH:-${OMNI_HOME:-$HOME/code/omni}}"
RESTART=0
OLLAMA_MODEL=""

usage() { sed -n '2,/^set -uo pipefail$/p' "$0" | sed -e '$d' -e 's/^# \{0,1\}//'; }

while [ $# -gt 0 ]; do
  case "$1" in
    --preflight-only) PREFLIGHT_ONLY=1 ;;
    --containers) WANT_CONTAINERS=1 ;;
    --no-containers) WANT_CONTAINERS=0 ;;
    --provider) shift; PROVIDER="${1:-}" ;;
    --provider=*) PROVIDER="${1#*=}" ;;
    --ollama-model) shift; OLLAMA_MODEL="${1:-}" ;;
    --ollama-model=*) OLLAMA_MODEL="${1#*=}" ;;
    --workspace) shift; WORKSPACE="${1:-}" ;;
    --workspace=*) WORKSPACE="${1#*=}" ;;
    --restart) RESTART=1 ;;
    -h|--help) usage; exit 0 ;;
    *) printf 'omninode-dev-setup: unknown option: %s (see --help)\n' "$1" >&2; exit 2 ;;
  esac
  shift
done
case "$PROVIDER" in ''|openrouter|gemini|openai|ollama) ;; *)
  printf 'omninode-dev-setup: --provider must be gemini, openrouter, openai or ollama\n' >&2; exit 2 ;;
esac
[ -n "$WORKSPACE" ] || { printf 'omninode-dev-setup: --workspace needs a directory\n' >&2; exit 2; }

# ---------------------------------------------------------------------------
# Run files. The log and status live under TMPDIR, never under $HOME, so a run
# that stops at preflight leaves nothing in the home directory.
# ---------------------------------------------------------------------------
_tmp="${TMPDIR:-/tmp}"
RUN_DIR="${ONBOARD_RUN_DIR:-${_tmp%/}/omninode-onboarding}"
mkdir -p "$RUN_DIR" && chmod 700 "$RUN_DIR"
STAMP="$(date +%Y%m%d-%H%M%S)"
LOG="$RUN_DIR/run-$STAMP.log"
STATUS="$RUN_DIR/status"
: >"$LOG"
: >"$STATUS"
STATE_DIR="$HOME/.omninode/onboarding"
# v2: the phases were renumbered when the lab phases were removed, so a record
# written under the old numbers is not read as completed phases of the new ones.
DONE_FILE="$STATE_DIR/phases.v2.done"

# The system directories first-class on PATH, whatever this was started from:
# an app launched with `open` inherits this PATH, and Docker Desktop's own setup
# runs /sbin/md5 (a stripped PATH fails its licence step with "md5: command not found").
case ":$PATH:" in *":/usr/sbin:"*) ;; *) PATH="$PATH:/usr/sbin" ;; esac
case ":$PATH:" in *":/sbin:"*) ;; *) PATH="$PATH:/sbin" ;; esac
case ":$PATH:" in *":/usr/bin:"*) ;; *) PATH="/usr/bin:$PATH" ;; esac
case ":$PATH:" in *":/bin:"*) ;; *) PATH="/bin:$PATH" ;; esac
# The tools phase 1 installs (Homebrew's prefix, and uv and onex in ~/.local/bin)
# on PATH from the start of every run. Phase 1 adds them only when it installs
# something, so a resumed run that skips it would otherwise send later phases
# (make up-local runs uv) to a PATH without them.
for _d in /usr/local/bin /opt/homebrew/bin "$HOME/.local/bin"; do
  [ -d "$_d" ] || continue
  case ":$PATH:" in *":$_d:"*) ;; *) PATH="$_d:$PATH" ;; esac
done
export PATH

IS_TTY=0
[ -t 0 ] && [ -t 1 ] && IS_TTY=1

# Ambient configuration that silently redirects onex (local-dev guide, section 2).
# This run and everything it starts never inherit it.
unset BIFROST_CONTRACT_PATH BIFROST_OVERLAY_PATH DELEGATION_ROUTING_TIERS_PATH \
  POSTGRES_PASSWORD VALKEY_PASSWORD PYTHONPATH 2>/dev/null || true

# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------
log() { printf '%s %s\n' "$(date +%H:%M:%S)" "$*" >>"$LOG"; }
say() { printf '%s\n' "$*"; log "$*"; }
hr() { say "------------------------------------------------------------------------"; }

GUI_SESSION=0
if command -v launchctl >/dev/null 2>&1 && [ "$(launchctl managername 2>/dev/null)" = "Aqua" ]; then
  GUI_SESSION=1
fi
[ "${ONBOARD_TEST_NO_GUI:-0}" = "1" ] && GUI_SESSION=0   # test seam: no desktop to ask on

# Questions go to dialogs whenever there is a desktop, so they stand apart from
# the progress the terminal is printing. Terminal prompts are for a Mac with no
# desktop (over ssh), or when asked for with ONBOARD_PROMPTS=terminal.
PROMPT_TTY=0
if [ "$IS_TTY" -eq 1 ] && { [ "$GUI_SESSION" -eq 0 ] || [ "${ONBOARD_PROMPTS:-}" = "terminal" ]; }; then
  PROMPT_TTY=1
fi

notify() { # title message
  [ "$GUI_SESSION" -eq 1 ] || return 0
  [ "${ONBOARD_NOTIFY:-1}" = "0" ] && return 0
  /usr/bin/osascript - "$1" "$2" >/dev/null 2>&1 <<'OSA' || true
on run argv
  display notification (item 2 of argv) with title "OmniNode onboarding" subtitle (item 1 of argv)
end run
OSA
}

PHASE_NO=""
PHASE_NAME=""
PHASE_T0=0
FAILED_STEP=""
FAILED_ATTEMPTS=0
LAST_ERR=""
TOTAL_PHASES=6

elapsed() { # seconds -> "Xm Ys"
  local s="$1"
  if [ "$s" -ge 60 ]; then printf '%dm %02ds' $((s / 60)) $((s % 60)); else printf '%ds' "$s"; fi
}

phase_start() { # no name estimate
  PHASE_NO="$1"; PHASE_NAME="$2"; PHASE_T0=$SECONDS
  FAILED_STEP=""; FAILED_ATTEMPTS=0; LAST_ERR=""
  hr
  say "▶ Phase $1/$TOTAL_PHASES: $2${3:+  (usually $3)}"
  printf 'phase=%s name="%s" result=RUNNING\n' "$1" "$2" >>"$STATUS"
}

phase_pass() { # [note]
  local t; t="$(elapsed $((SECONDS - PHASE_T0)))"
  say "✔ Phase $PHASE_NO/$TOTAL_PHASES PASSED: $PHASE_NAME ($t)${1:+ -- $1}"
  printf 'phase=%s name="%s" result=PASS elapsed="%s" note="%s"\n' "$PHASE_NO" "$PHASE_NAME" "$t" "${1:-}" >>"$STATUS"
  notify "Phase $PHASE_NO/$TOTAL_PHASES passed" "$PHASE_NAME ($t)"
  [ "$PHASE_NO" = "0" ] || mark_done "$PHASE_NO"   # preflight always re-runs and writes nothing under $HOME
}

phase_skip() { # reason
  say "⏭ Phase $PHASE_NO/$TOTAL_PHASES SKIPPED: $PHASE_NAME -- $1"
  printf 'phase=%s name="%s" result=SKIPPED note="%s"\n' "$PHASE_NO" "$PHASE_NAME" "$1" >>"$STATUS"
  notify "Phase $PHASE_NO/$TOTAL_PHASES skipped" "$PHASE_NAME: $1"
}

phase_fail() { # next-step
  local t; t="$(elapsed $((SECONDS - PHASE_T0)))"
  say ""
  say "✘ Phase $PHASE_NO/$TOTAL_PHASES FAILED: $PHASE_NAME ($t)"
  if [ -n "$FAILED_STEP" ]; then
    if [ "$FAILED_ATTEMPTS" -gt 0 ]; then say "  Step:      $FAILED_STEP (after $FAILED_ATTEMPTS attempt(s))"
    else say "  Step:      $FAILED_STEP"; fi
  fi
  [ -n "$LAST_ERR" ] && say "  Last error: $LAST_ERR"
  say "  Next:      $1"
  say "  Log:       $LOG"
  say "  Re-run the same command to resume from this phase; completed phases are not redone."
  printf 'phase=%s name="%s" result=FAIL elapsed="%s" step="%s" next="%s"\n' \
    "$PHASE_NO" "$PHASE_NAME" "$t" "$FAILED_STEP" "$1" >>"$STATUS"
  notify "Phase $PHASE_NO/$TOTAL_PHASES FAILED" "$PHASE_NAME: ${FAILED_STEP:-see the terminal}"
  exit 1
}

mark_done() { mkdir -p "$STATE_DIR" && { grep -qx "$1" "$DONE_FILE" 2>/dev/null || echo "$1" >>"$DONE_FILE"; }; }
is_done() { [ "$RESTART" -eq 0 ] && grep -qx "$1" "$DONE_FILE" 2>/dev/null; }

last_log_lines() { tail -n 3 "$LOG" 2>/dev/null | tr '\n' ' ' | sed 's/  */ /g' | cut -c1-300; }

# retry DESC CMD... : run CMD with output to the log, up to RETRIES attempts,
# 5-10 s apart. Returns CMD's status; on failure sets FAILED_STEP/LAST_ERR.
retry() {
  local desc="$1"; shift
  local n=1 rc wait
  while :; do
    log "\$ $desc (attempt $n/$RETRIES)"
    "$@" >>"$LOG" 2>&1
    rc=$?
    [ "$rc" -eq 0 ] && return 0
    LAST_ERR="$(last_log_lines)"
    if [ "$n" -ge "$RETRIES" ]; then
      FAILED_STEP="$desc"; FAILED_ATTEMPTS=$n
      return "$rc"
    fi
    wait=$(( (RANDOM % 6) + 5 ))
    say "  … $desc failed (attempt $n/$RETRIES); retrying in ${wait}s"
    sleep "$wait"
    n=$((n + 1))
  done
}

# retry_capture DESC CMD... : like retry, but CMD's stdout is returned in
# CAPTURED and never written to the log (it may carry a credential).
CAPTURED=""
retry_capture() {
  local desc="$1"; shift
  local n=1 rc wait
  CAPTURED=""
  while :; do
    log "\$ $desc (attempt $n/$RETRIES; output not logged)"
    CAPTURED="$("$@" 2>>"$LOG")"
    rc=$?
    [ "$rc" -eq 0 ] && return 0
    CAPTURED=""
    LAST_ERR="$(last_log_lines)"
    if [ "$n" -ge "$RETRIES" ]; then
      FAILED_STEP="$desc"; FAILED_ATTEMPTS=$n
      return "$rc"
    fi
    wait=$(( (RANDOM % 6) + 5 ))
    say "  … $desc failed (attempt $n/$RETRIES); retrying in ${wait}s"
    sleep "$wait"
    n=$((n + 1))
  done
}

# step DESC CMD... : a local step, run once.
step() {
  local desc="$1"; shift
  log "\$ $desc"
  if "$@" >>"$LOG" 2>&1; then return 0; fi
  FAILED_STEP="$desc"; FAILED_ATTEMPTS=1; LAST_ERR="$(last_log_lines)"
  return 1
}

# wait_until DESC SECONDS INTERVAL CMD... : poll a condition (not a retry of a
# failed action), used for things that come up on their own time.
wait_until() {
  local desc="$1" limit="$2" every="$3"; shift 3
  local t0=$SECONDS
  while [ $((SECONDS - t0)) -lt "$limit" ]; do
    "$@" >>"$LOG" 2>&1 && return 0
    sleep "$every"
  done
  FAILED_STEP="$desc (waited $(elapsed "$limit"))"; LAST_ERR="$(last_log_lines)"
  return 1
}

# ---------------------------------------------------------------------------
# Machine facts (with test seams: ONBOARD_TEST_* overrides a reading)
# ---------------------------------------------------------------------------
os_name() { echo "${ONBOARD_TEST_OS:-$(uname -s)}"; }
macos_version() { echo "${ONBOARD_TEST_MACOS:-$(sw_vers -productVersion 2>/dev/null || echo 0)}"; }
cpu_count() { echo "${ONBOARD_TEST_CPUS:-$(sysctl -n hw.ncpu 2>/dev/null || echo 0)}"; }
ram_gb() {
  if [ -n "${ONBOARD_TEST_RAM_GB:-}" ]; then echo "$ONBOARD_TEST_RAM_GB"; return; fi
  local b; b="$(sysctl -n hw.memsize 2>/dev/null || echo 0)"
  echo $(( (b + 536870912) / 1073741824 ))
}
disk_free_gb() {
  if [ -n "${ONBOARD_TEST_DISK_GB:-}" ]; then echo "$ONBOARD_TEST_DISK_GB"; return; fi
  df -Pk "$HOME" 2>/dev/null | awk 'NR==2 {printf "%d\n", $4/1048576}'
}
is_vm() {
  if [ -n "${ONBOARD_TEST_VM:-}" ]; then [ "$ONBOARD_TEST_VM" = "1" ]; return; fi
  [ "$(sysctl -n kern.hv_vmm_present 2>/dev/null || echo 0)" = "1" ]
}
is_rosetta() { [ "$(sysctl -n sysctl.proc_translated 2>/dev/null || echo 0)" = "1" ]; }
is_admin() {
  if [ -n "${ONBOARD_TEST_ADMIN:-}" ]; then [ "$ONBOARD_TEST_ADMIN" = "1" ]; return; fi
  id -Gn 2>/dev/null | tr ' ' '\n' | grep -qx admin
}
avail_mem_gb() { # free + inactive + speculative pages
  vm_stat 2>/dev/null | awk '
    /page size of/ { ps = $8 }
    /Pages free/ { f = $3 } /Pages inactive/ { i = $3 } /Pages speculative/ { s = $3 }
    END { gsub(/\./, "", f); gsub(/\./, "", i); gsub(/\./, "", s);
          if (ps == 0) ps = 4096; printf "%d\n", (f + i + s) * ps / 1073741824 }'
}
port_busy() {
  # An explicitly empty override means no ports are busy.
  if [ "${ONBOARD_TEST_PORTS_BUSY+x}" = "x" ]; then
    case " $ONBOARD_TEST_PORTS_BUSY " in *" $1 "*) return 0 ;; *) return 1 ;; esac
  fi
  lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1
}

# Docker Desktop's CLI lives inside the app; a fresh install has not put it on PATH yet.
export PATH="$PATH:/Applications/Docker.app/Contents/Resources/bin:$HOME/.docker/bin"
LOCAL_STACK_PROJECT="omnibase-infra-local"
docker_installed() { [ -d /Applications/Docker.app ]; }
docker_ready() { docker info >/dev/null 2>&1; }
docker_state() {
  if [ -n "${ONBOARD_TEST_DOCKER:-}" ]; then echo "$ONBOARD_TEST_DOCKER"; return; fi
  if ! docker_installed; then echo "not installed"
  elif docker_ready; then echo "running"
  else echo "installed, not running"
  fi
}
local_stack_running() { # the local stack's own containers are up (they hold its ports)
  docker_ready && [ -n "$(docker ps -q --filter "label=com.docker.compose.project=$LOCAL_STACK_PROJECT" 2>/dev/null)" ]
}
arch() { uname -m; }

brew_bin() {
  if [ -x /opt/homebrew/bin/brew ]; then echo /opt/homebrew/bin/brew
  elif [ -x /usr/local/bin/brew ]; then echo /usr/local/bin/brew
  fi
}

# ---------------------------------------------------------------------------
# Privilege and secrets. On a terminal these prompt there; without one (a
# Claude Code tool call, an ssh session) they use a macOS dialog. A value is
# held only in a shell variable and handed over on stdin.
# ---------------------------------------------------------------------------
ASKPASS="$RUN_DIR/askpass.sh"
make_askpass() {
  cat >"$ASKPASS" <<'SH'
#!/bin/bash
/usr/bin/osascript -e 'display dialog "OmniNode onboarding needs your Mac administrator password to install developer tools." with title "OmniNode onboarding" default answer "" with hidden answer buttons {"Cancel","OK"} default button "OK"' -e 'text returned of result' 2>/dev/null
SH
  chmod 700 "$ASKPASS"
}

SUDO_KEEPALIVE_PID=""
ensure_sudo() {
  sudo -n true 2>/dev/null && return 0
  if [ "$PROMPT_TTY" -eq 1 ]; then
    say "  The next step needs your Mac administrator password (asked once, by sudo)."
    sudo -v || return 1
  elif [ "$GUI_SESSION" -eq 1 ]; then
    make_askpass
    export SUDO_ASKPASS="$ASKPASS"
    say "  A dialog is asking for your Mac administrator password."
    sudo -A -v || return 1
  else
    say "  Administrator access is needed and there is no terminal or desktop to ask on."
    return 1
  fi
  if [ -z "$SUDO_KEEPALIVE_PID" ]; then
    ( while kill -0 "$$" 2>/dev/null; do sudo -n true 2>/dev/null; sleep 50; done ) &
    SUDO_KEEPALIVE_PID=$!
  fi
  return 0
}

# The developer chose to stop. Only offered before anything installs, so it is
# true that nothing was installed.
quit_setup() {
  PENDING_KEY=""; SECRET=""
  say ""
  say "  Nothing was installed. Run onboarding again when you're ready."
  printf 'phase=0 name="Preflight" result=QUIT\n' >>"$STATUS"
  notify "Setup stopped" "Nothing was installed. Run onboarding again when you're ready."
  exit 4
}

QUIT_REQUESTED=0
read_secret() { # prompt -> SECRET; QUIT_REQUESTED=1 when the developer chose "Quit setup"
  SECRET=""
  if [ "$PROMPT_TTY" -eq 1 ]; then
    printf '%s ' "$1"
    IFS= read -r -s SECRET
    printf '\n'
  elif [ "$GUI_SESSION" -eq 1 ]; then
    # The terminal prompt is indented to line up with the run's output; a dialog is not.
    SECRET="$(/usr/bin/osascript - "$(printf '%s' "$1" | sed 's/^[[:space:]]*//')" 2>/dev/null <<'OSA'
on run argv
  try
    set r to display dialog (item 1 of argv) & return & return & "Your key stays on this Mac, in onex's key store. It is never shown or logged." with title "Your model key" default answer "" with hidden answer buttons {"Quit setup", "Continue"} default button "Continue" cancel button "Quit setup" with icon note
  on error number -128
    return "__ONBOARDING_QUIT__"
  end try
  return text returned of r
end run
OSA
)"
    if [ "$SECRET" = "__ONBOARDING_QUIT__" ]; then SECRET=""; QUIT_REQUESTED=1; fi  # pragma: allowlist secret (a quit marker, not a credential)
  fi
}

cleanup() {
  [ -n "$SUDO_KEEPALIVE_PID" ] && kill "$SUDO_KEEPALIVE_PID" 2>/dev/null
  rm -f "$ASKPASS" 2>/dev/null
  SECRET=""; CAPTURED=""; PENDING_KEY=""
  return 0
}
trap cleanup EXIT

# ---------------------------------------------------------------------------
# In a VM: said once, before any question, so no choice is made without knowing.
vm_notice() {
  local a=""
  say ""
  say "  We detected that this Mac is a virtual machine."
  say "  Docker can't run inside a macOS VM, so the local stack isn't offered here."
  say "  Everything else works. A model on this Mac (Ollama) will be slow in a VM;"
  say "  a key (Gemini, OpenRouter or OpenAI) is the better choice."
  say ""
  if [ "$PROMPT_TTY" -eq 0 ] && [ "$GUI_SESSION" -eq 1 ]; then
    a="$(/usr/bin/osascript 2>/dev/null <<'OSA'
try
  display dialog "We detected that this Mac is a virtual machine." & return & return & "Docker can't run inside a macOS VM, so the local stack isn't offered here. Everything else works." & return & return & "A model on this Mac (Ollama) will be slow in a VM; a key (Gemini, OpenRouter or OpenAI) is the better choice." with title "This is a virtual machine" buttons {"Quit setup", "Continue"} default button "Continue" cancel button "Quit setup" with icon note
on error number -128
  return "q"
end try
return "c"
OSA
)"
    [ "$a" = "q" ] && quit_setup
  fi
}

ask_docker() { # note -> 0 yes, 1 no. On a terminal, else a dialog; never a flag.
  local a=""
  say ""
  say "  One optional extra: running the stack on this Mac"
  say ""
  say "  $1" | fold -s -w 84 | sed '2,$s/^/  /'
  say ""
  say "  You're already covered: onex runs your delegations natively on this Mac, on the"
  say "  model you chose."
  say ""
  say "  If you work on runtime, node or projection code, you can also run your own copy"
  say "  of the stack here in Docker: a database, a message broker and the two runtime"
  say "  kernels, all on this Mac, so you can try changes without touching anything shared."
  say ""
  say "  What it takes:"
  say "    - about ${DOCKER_MEM_GB} GB of memory while it runs"
  say "    - about 15 GB of disk for its images and data"
  say "    - 10-20 minutes the first time, a few minutes after that"
  say ""
  say "  Not sure? Choose no. You can add it any time: run this again with --containers."
  say "  To stop here instead, answer q: nothing has been installed yet."
  say ""
  if [ "$PROMPT_TTY" -eq 1 ]; then
    printf '  Set up the local stack in Docker too? [y/N, q to quit] '
    IFS= read -r a
  elif [ "$GUI_SESSION" -eq 1 ]; then
    a="$(/usr/bin/osascript - "$1" "$DOCKER_MEM_GB" 2>/dev/null <<'OSA'
on run argv
  set msg to (item 1 of argv) & return & return & "You're already covered: onex runs your delegations natively on this Mac, on the model you chose." & return & return & "If you work on runtime, node or projection code, you can also run your own copy of the stack here in Docker (a database, a message broker and the runtime kernels), so you can try changes without touching anything shared." & return & return & "What it takes:" & return & "  • about " & (item 2 of argv) & " GB of memory while it runs" & return & "  • about 15 GB of disk" & return & "  • 10-20 minutes the first time" & return & return & "Not sure? Choose Not now. You can add it any time by running onboarding again with --containers."
  try
    set r to display dialog msg with title "Run the stack locally in Docker?" buttons {"Quit setup", "Not now", "Yes, set it up"} default button "Not now" cancel button "Quit setup" with icon note
  on error number -128
    return "q"
  end try
  if button returned of r is "Yes, set it up" then return "y"
  return "n"
end run
OSA
)"
    say "  Set up the local stack in Docker too? ${a:-n} (answered in a dialog)"
  else
    say "  No terminal or desktop to ask on, so the stack is not run locally (--containers adds it)."
  fi
  case "$a" in y|Y|yes|YES) return 0 ;; q|Q|quit|QUIT) return 2 ;; *) return 1 ;; esac
}

# ---------------------------------------------------------------------------
# The model key. Developers bring their own (OpenRouter or Gemini); there
# is no lab-model fallback. Settled in preflight, before anything installs, so
# the run never stops mid-way to ask. The key is held only in this process
# (never exported, logged or written) until phase 3 stores it in onex.
# ---------------------------------------------------------------------------
PENDING_KEY=""
MODEL_CHOICE=""

provider_home() { case "$1" in openrouter) echo "OpenRouter" ;; gemini) echo "Google" ;; openai) echo "OpenAI" ;; *) echo "$1" ;; esac; }

provider_label() {
  case "$1" in
    openrouter) echo "OpenRouter" ;;
    openai) echo "OpenAI" ;;
    gemini) echo "Gemini (Google AI Studio)" ;;
    ollama) echo "Ollama (on this Mac)" ;;
    *) echo "$1" ;;
  esac
}

stored_key_provider() { # an earlier run's key, if onex is already here
  [ -x "$HOME/.local/bin/onex" ] || return 1
  local p list
  list="$(env -u PYTHONPATH "$HOME/.local/bin/onex" secret list 2>/dev/null)" || return 1
  for p in openrouter gemini openai; do
    printf '%s\n' "$list" | grep -qE "^[[:space:]]+llm\.$p\.api_key[[:space:]]" && { echo "$p"; return 0; }
  done
  return 1
}

ask_provider() { # -> MODEL_CHOICE, or empty when nobody can be asked
  local a=""
  if [ "$PROMPT_TTY" -eq 1 ]; then
    say ""
    say "  Your model"
    say ""
    say "  Delegations run on a model you choose:"
    say "    1) Gemini      - your Google AI Studio key, from aistudio.google.com/apikey"
    say "    2) OpenRouter  - your openrouter.ai key (its free models work with no credit)"
    say "    3) OpenAI      - your platform.openai.com key (it needs credits on the account)"
    say "    4) Ollama      - a model on this Mac, no key. Slower than a key, especially on"
    say "                     Intel, and it downloads a model sized to this Mac"
    say ""
    say "    q) quit setup (nothing has been installed yet)"
    say ""
    printf '  Which one? Choose 1, 2, 3 or 4: '
    IFS= read -r a
    case "$a" in 1) MODEL_CHOICE=gemini ;; 2) MODEL_CHOICE=openrouter ;; 3) MODEL_CHOICE=openai ;; 4) MODEL_CHOICE=ollama ;; q|Q) quit_setup ;; esac
  elif [ "$GUI_SESSION" -eq 1 ]; then
    a="$(/usr/bin/osascript 2>/dev/null <<'OSA'
set r to choose from list {"Gemini (your Google AI Studio key)", "OpenRouter (your key)", "OpenAI (your key; needs credits)", "Ollama (on this Mac, no key)"} with title "Your model" with prompt "Delegations run on a model you choose. Gemini, OpenRouter and OpenAI use your own key. Ollama runs a model on this Mac with no key: slower, especially on Intel, and it downloads a model sized to this Mac." OK button name "Continue" cancel button name "Quit setup"
if r is false then return "QUIT"
return item 1 of r
OSA
)"
    case "$a" in Gemini*) MODEL_CHOICE=gemini ;; OpenRouter*) MODEL_CHOICE=openrouter ;; OpenAI*) MODEL_CHOICE=openai ;; Ollama*) MODEL_CHOICE=ollama ;; QUIT) quit_setup ;; esac
  fi
}

# ---------------------------------------------------------------------------
# Ollama: a model served on this Mac, with no key. onex reaches it through its
# local routes (the same OpenAI-style API), declared in its overrides file.
# ---------------------------------------------------------------------------
# Port, chat path and the default model for each memory size come from the
# `ollama:` block of omnimarket's model config (bifrost_delegation.yaml), read
# from the workspace once it is cloned. This script holds no model name. It
# chooses only the host, which depends on where the call comes from: this Mac,
# or the Docker stack.
OLLAMA_CONFIG_REL="omnimarket/src/omnimarket/configs/bifrost_delegation.yaml"
OVERRIDES_FILE_REL=".omninode/delegation/bifrost_overrides.yaml"
OLLAMA_MARK="# Written by omninode-dev-setup: Ollama on this Mac."
OLLAMA_PORT=""; OLLAMA_CHAT_PATH=""; OLLAMA_DOWNLOAD_GB=""; OLLAMA_URL=""

# ram_gb [model] -> "port chat_path model download_gb": the first `models` entry
# whose min_memory_gb fits this Mac, or the named model (its size when listed,
# else the largest listed).
ollama_config() {
  "$WORKSPACE/.onex-dispatch-venv/bin/python" - "$WORKSPACE/$OLLAMA_CONFIG_REL" "$1" "${2:-}" <<'PYCFG'
import sys
import yaml
block = (yaml.safe_load(open(sys.argv[1])) or {}).get("ollama") or {}
port, path, models = block.get("port"), block.get("chat_path"), block.get("models") or []
if not port or not path or not models:
    sys.exit("the model config has no complete ollama block (port, chat_path, models)")
ram, wanted = int(sys.argv[2]), sys.argv[3]
models = sorted(models, key=lambda m: int(m["min_memory_gb"]), reverse=True)
if wanted:
    size = next((m["download_gb"] for m in models if m["model"] == wanted), max(m["download_gb"] for m in models))
    print(port, path, wanted, size)
else:
    pick = next((m for m in models if int(m["min_memory_gb"]) <= ram), models[-1])
    print(port, path, pick["model"], pick["download_gb"])
PYCFG
}

load_ollama_config() { # -> OLLAMA_PORT OLLAMA_CHAT_PATH OLLAMA_MODEL OLLAMA_DOWNLOAD_GB OLLAMA_URL
  local out
  out="$(ollama_config "$(ram_gb)" "$OLLAMA_MODEL" 2>>"$LOG")" || return 1
  set -- $out
  [ $# -eq 4 ] || return 1
  OLLAMA_PORT="$1"; OLLAMA_CHAT_PATH="$2"; OLLAMA_MODEL="$3"; OLLAMA_DOWNLOAD_GB="$4"
  OLLAMA_URL="http://127.0.0.1:$OLLAMA_PORT"
}

ollama_bin() {
  if command -v ollama >/dev/null 2>&1; then command -v ollama
  elif [ -x /Applications/Ollama.app/Contents/Resources/ollama ]; then echo /Applications/Ollama.app/Contents/Resources/ollama
  fi
}
ollama_up() { curl -fsS -m 3 "$OLLAMA_URL/api/version" >/dev/null 2>&1; }
ollama_has_model() { curl -fsS -m 5 "$OLLAMA_URL/api/tags" 2>/dev/null | grep -qF "\"$1\""; }
ollama_overrides_ours() { head -n 1 "$HOME/$OVERRIDES_FILE_REL" 2>/dev/null | grep -qF "$OLLAMA_MARK"; }

settle_ollama() { # preflight: no key, and an honest word on speed. The model is chosen in phase 3.
  # A re-run keeps the model an earlier run downloaded.
  [ -n "$OLLAMA_MODEL" ] || OLLAMA_MODEL="$(sed -n 's/^    model_name: "\(.*\)"$/\1/p' "$HOME/$OVERRIDES_FILE_REL" 2>/dev/null | head -n 1)"
  if [ -n "$OLLAMA_MODEL" ]; then
    say "  Model: Ollama on this Mac, no key. Model: $OLLAMA_MODEL."
  else
    say "  Model: Ollama on this Mac, no key. The model is chosen for this Mac's $(ram_gb) GB of memory"
    say "    once the workspace is in place, and downloaded then."
  fi
  if is_vm; then
    say "  ⚠ This is a virtual machine: Ollama gets little or no GPU in a VM, so answers are"
    say "    slow. Gemini, OpenRouter or OpenAI (a key) is the better choice here."
  else
    case "$(arch)" in arm64) ;; *) say "  ⚠ This is an Intel Mac: local models run on the CPU here, so answers are slow." ;; esac
  fi
}

# Homebrew remembers a cask whose app was later deleted by hand and then skips
# installing it, so a missing app is reinstalled rather than trusted to be there.
install_ollama() {
  if "$(brew_bin)" list --cask ollama-app >/dev/null 2>&1; then
    HOMEBREW_NO_ENV_HINTS=1 "$(brew_bin)" reinstall --cask ollama-app
  else
    brew_install ollama-app --cask
  fi
}

start_ollama() { # the app when there is a desktop (it starts at login), else the server alone
  ollama_up && return 0
  if [ "$GUI_SESSION" -eq 1 ] && [ -d /Applications/Ollama.app ]; then
    open -g -a Ollama 2>>"$LOG"
    wait_until "Ollama to start" 60 2 ollama_up && return 0
  fi
  nohup "$(ollama_bin)" serve >>"$RUN_DIR/ollama-serve.log" 2>&1 &
  OLLAMA_HEADLESS=1
  wait_until "Ollama to start" 60 2 ollama_up
}
OLLAMA_HEADLESS=0

write_ollama_overrides() { # model: onex's local routes go to Ollama
  local f="$HOME/$OVERRIDES_FILE_REL"
  mkdir -p "$(dirname "$f")"
  if [ -f "$f" ] && ! ollama_overrides_ours; then
    cp -p "$f" "$f.pre-onboarding.$STAMP"
    say "  Saved your earlier $f as $(basename "$f").pre-onboarding.$STAMP"
  fi
  cat >"$f" <<YAML
$OLLAMA_MARK
backends:
  - backend_id: local-coder
    endpoint_url: "$OLLAMA_URL$OLLAMA_CHAT_PATH"
    model_name: "$1"
  - backend_id: local-heavy-reasoning
    endpoint_url: "$OLLAMA_URL$OLLAMA_CHAT_PATH"
    model_name: "$1"
YAML
}

uses_key() { case "$1" in gemini|openrouter|openai) return 0 ;; *) return 1 ;; esac; }

settle_model_key() {
  local stored
  # An earlier run that chose Ollama left its routes in place; they still route first.
  if [ -z "$PROVIDER" ] && ollama_overrides_ours; then PROVIDER=ollama; fi
  if [ "$PROVIDER" = "ollama" ]; then
    MODEL_CHOICE=ollama
    settle_ollama
    return 0
  fi
  if stored="$(stored_key_provider)" && { [ -z "$PROVIDER" ] || [ "$PROVIDER" = "$stored" ]; }; then
    MODEL_CHOICE="$stored"
    say "  Model key: your $stored key is already stored; it will be used."
    return 0
  fi
  MODEL_CHOICE="$PROVIDER"
  [ -n "$MODEL_CHOICE" ] || ask_provider
  if [ -z "$MODEL_CHOICE" ]; then
    FAILED_STEP="choose your model"
    LAST_ERR="no model was chosen, and there is no terminal or desktop to ask on"
    phase_fail "run this in Terminal, or pass --provider gemini|openrouter|openai|ollama. Nothing was installed"
  fi
  if [ "$MODEL_CHOICE" = "ollama" ]; then settle_ollama; return 0; fi
  say ""
  say "  Your key stays on this Mac, in onex's key store. It is never shown or logged,"
  say "  and it is only ever sent to $(provider_home "$MODEL_CHOICE")."
  read_secret "  Paste your $(provider_label "$MODEL_CHOICE") API key (input is hidden):"
  [ "$QUIT_REQUESTED" -eq 1 ] && quit_setup
  PENDING_KEY="$SECRET"; SECRET=""
  if [ -z "$PENDING_KEY" ]; then
    FAILED_STEP="your model key"
    LAST_ERR="no key was given; developers bring their own key and the lab's models are not used"
    phase_fail "get a Google AI Studio, OpenRouter or OpenAI key, or choose Ollama (no key), and run this again. Nothing was installed"
  fi
  say "  Model key: received (held in memory; stored in onex in phase 3)."
}

# ===========================================================================
# Phase 0: preflight. Reads only.
# ===========================================================================
MODE1_OK=1
MODE2_OK=1
MODE2_WHY=""
MODE1_WHY=""

row() { printf '  %-22s %-16s %-14s %s\n' "$1" "$2" "$3" "$4" | tee -a "$LOG"; }

phase0() {
  phase_start 0 "Preflight (reads this Mac; changes nothing)" "under a minute"
  local mv major cpus ram disk vm="physical Mac" p busy="" ambient dstate m2disk a
  mv="$(macos_version)"; major="${mv%%.*}"
  case "$major" in ''|*[!0-9]*) major=0 ;; esac
  cpus="$(cpu_count)"; ram="$(ram_gb)"; disk="$(disk_free_gb)"
  is_vm && vm="virtual machine"
  dstate="$(docker_state)"
  m2disk=$M2_DISK_GB
  [ "$dstate" != "not installed" ] && m2disk=$M2_DISK_GB_DOCKER_PRESENT

  say "  Log file: $LOG"
  say ""
  row "Requirement" "This Mac" "Mode 1 needs" "Mode 2 (containers) needs"
  row "macOS" "$mv" "$M1_MACOS_MAJOR+" "$M1_MACOS_MAJOR+"
  row "CPU cores" "$cpus ($(arch))" "$M1_CPUS" "$M2_CPUS"
  row "RAM" "${ram} GB" "${M1_RAM_GB} GB" "${M2_RAM_GB} GB"
  row "Free disk" "${disk} GB" "${M1_DISK_GB} GB" "${m2disk} GB"
  row "Machine" "$vm" "either" "physical Mac"
  row "Docker Desktop" "$dstate" "not used" "installed or launched for you"
  say ""

  [ "$major" -ge "$M1_MACOS_MAJOR" ] || { MODE1_OK=0; MODE1_WHY="$MODE1_WHY macOS $mv is older than $M1_MACOS_MAJOR;"; }
  [ "$cpus" -ge "$M1_CPUS" ] || { MODE1_OK=0; MODE1_WHY="$MODE1_WHY $cpus CPU cores (needs $M1_CPUS);"; }
  [ "$ram" -ge "$M1_RAM_GB" ] || { MODE1_OK=0; MODE1_WHY="$MODE1_WHY ${ram} GB RAM (needs $M1_RAM_GB);"; }
  [ "$disk" -ge "$M1_DISK_GB" ] || { MODE1_OK=0; MODE1_WHY="$MODE1_WHY ${disk} GB free disk (needs $M1_DISK_GB);"; }

  if [ "$MODE1_OK" -eq 0 ]; then
    MODE2_OK=0
  else
    [ "$cpus" -ge "$M2_CPUS" ] || { MODE2_OK=0; MODE2_WHY="$MODE2_WHY $cpus CPU cores (needs $M2_CPUS);"; }
    [ "$ram" -ge "$M2_RAM_GB" ] || { MODE2_OK=0; MODE2_WHY="$MODE2_WHY ${ram} GB RAM (needs $M2_RAM_GB);"; }
    [ "$disk" -ge "$m2disk" ] || { MODE2_OK=0; MODE2_WHY="$MODE2_WHY ${disk} GB free disk (needs $m2disk);"; }
    is_vm && { MODE2_OK=0; MODE2_WHY="$MODE2_WHY this is a VM, and Docker Desktop cannot run inside a macOS guest;"; }
    if local_stack_running; then
      STACK_RUNNING=1   # its own containers hold the ports: not a conflict
    else
      for p in $MODE2_PORTS; do port_busy "$p" && busy="$busy $p"; done
      [ -n "$busy" ] && { MODE2_OK=0; MODE2_WHY="$MODE2_WHY ports in use by something else:$busy;"; }
    fi
  fi

  # Conditions that are fixable on this machine, not a hardware shortfall.
  if [ "$(os_name)" != "Darwin" ]; then
    FAILED_STEP="operating system check"; LAST_ERR="$(os_name) is not macOS"
    phase_fail "run this on macOS; Linux and Windows are not supported yet"
  fi
  if is_rosetta; then
    FAILED_STEP="native terminal check"; LAST_ERR="this shell is running under Rosetta on Apple silicon"
    phase_fail "open a native (arm64) terminal and run the command again, so Homebrew lands in /opt/homebrew"
  fi
  if ! is_admin; then
    FAILED_STEP="administrator check"; LAST_ERR="$(id -un) is not in the admin group"
    phase_fail "run this from an administrator account, or ask your Mac's administrator to add you to the admin group"
  fi

  ambient="$(grep -nE '^[[:space:]]*(export[[:space:]]+)?(BIFROST_[A-Z_]+|DELEGATION_ROUTING_TIERS_PATH|POSTGRES_PASSWORD|VALKEY_PASSWORD)=|^[[:space:]]*(source|\.)[[:space:]]+.*\.omnibase/\.env' \
    "$HOME/.zshrc" "$HOME/.zprofile" "$HOME/.zshenv" "$HOME/.bash_profile" "$HOME/.bashrc" "$HOME/.profile" 2>/dev/null || true)"
  if [ -n "$ambient" ]; then
    AMBIENT_FOUND="$ambient"
    say "  ⚠ Your shell profile exports configuration that silently redirects onex. This run"
    say "    ignores it, but your own shells will not. Remove these lines:"
    printf '%s\n' "$ambient" | sed 's/=.*$/=…/' | sed 's/^/      /' | tee -a "$LOG"
  fi

  MODE1_WHY="${MODE1_WHY%;}"; MODE2_WHY="${MODE2_WHY%;}"
  if [ "$MODE1_OK" -eq 0 ]; then
    say "✘ This Mac is below the minimum requirements:$MODE1_WHY"
    say "  Nothing was installed. Use $VM_SPEC, and run this command inside it."
    printf 'phase=0 name="Preflight" result=BELOW_MINIMUM why="%s"\n' "$MODE1_WHY" >>"$STATUS"
    notify "Below minimum requirements" "Nothing was installed. See the terminal for the recommended VM."
    exit 3
  fi

  # The model comes first: it is the one choice every run needs. Docker is one
  # question on top of it, asked only when this Mac can run it; the flags answer
  # either in advance.
  if [ "$PREFLIGHT_ONLY" -eq 0 ] && is_vm; then vm_notice; fi
  [ "$PREFLIGHT_ONLY" -eq 1 ] || settle_model_key

  local docker_note
  case "$dstate" in
    running) docker_note="We found Docker Desktop on this Mac, and it's running. Do you want to use it to run the stack locally too?" ;;
    "installed, not running") docker_note="We found Docker Desktop on this Mac, but it isn't running. If you want the stack, we'll start it for you." ;;
    *) docker_note="Docker Desktop isn't installed on this Mac. If you want the stack, we'll install it for you (it may ask you to accept Docker's terms)." ;;
  esac
  if [ "$MODE2_OK" -eq 1 ]; then
    case "$WANT_CONTAINERS" in
      1) ;;
      0) MODE2_OK=0; MODE2_WHY=" --no-containers was passed" ;;
      *)
        if [ "$PREFLIGHT_ONLY" -eq 1 ]; then
          MODE2_OFFERED=1
        else
          local rc=0
          ask_docker "$docker_note" || rc=$?
          [ "$rc" -eq 2 ] && quit_setup
          [ "$rc" -eq 1 ] && { MODE2_OK=0; MODE2_WHY=" you said no"; }
        fi
        ;;
    esac
  else
    say "  Docker is not offered on this Mac:$MODE2_WHY."
    say "  That is fine: onex runs your delegations natively on this Mac."
  fi

  if [ "$MODE2_OK" -eq 1 ] && [ "$MODE2_OFFERED" -eq 1 ]; then
    SELECTED="native onex; Docker can be added (you will be asked)"
  elif [ "$MODE2_OK" -eq 1 ]; then
    SELECTED="native onex, and the stack locally in Docker"
  else
    SELECTED="native onex. No local Docker:$MODE2_WHY"
  fi
  say "  Will set up: $SELECTED"
  uses_key "$MODEL_CHOICE" && say "  Model: your own $(provider_label "$MODEL_CHOICE") key"
  phase_pass "$SELECTED"
}
AMBIENT_FOUND=""
SELECTED=""
STACK_RUNNING=0
MODE2_OFFERED=0

# ===========================================================================
# Phase 1: base tools
# ===========================================================================
install_clt() { # Xcode command-line tools, without the GUI prompt
  local marker=/tmp/.com.apple.dt.CommandLineTools.installondemand.in-progress label
  touch "$marker"
  label="$(softwareupdate -l 2>/dev/null | sed -n 's/^[[:space:]]*\* Label: //p' | grep -E '^Command Line Tools' | sort -V | tail -n 1)"
  if [ -z "$label" ]; then rm -f "$marker"; echo "no Command Line Tools update is offered" >&2; return 1; fi
  sudo -n softwareupdate -i "$label" --verbose
  local rc=$?
  rm -f "$marker"
  return $rc
}

download() { # url dest
  curl -fsSL --connect-timeout 15 --max-time 300 -o "$2" "$1"
}

brew_install() { # formula-or-cask [--cask]
  local b; b="$(brew_bin)"
  if [ "${2:-}" = "--cask" ]; then
    "$b" list --cask "$1" >/dev/null 2>&1 && return 0
    HOMEBREW_NO_ENV_HINTS=1 "$b" install --cask "$1"
  else
    "$b" list --versions "$1" >/dev/null 2>&1 && return 0
    HOMEBREW_NO_ENV_HINTS=1 "$b" install "$1"
  fi
}

uv_bin() {
  if command -v uv >/dev/null 2>&1; then command -v uv
  elif [ -x "$HOME/.local/bin/uv" ]; then echo "$HOME/.local/bin/uv"
  fi
}

phase1_verified() {
  xcode-select -p >/dev/null 2>&1 && [ -n "$(brew_bin)" ] && [ -n "$(uv_bin)" ] &&
    "$(brew_bin)" list --versions gh jq python@3.13 >/dev/null 2>&1
}

phase1() {
  phase_start 1 "Base tools (Xcode tools, Homebrew, gh, jq, python@3.13, uv)" "5-20 minutes on a clean Mac"
  if is_done 1 && phase1_verified; then phase_pass "already installed"; return; fi

  if ! xcode-select -p >/dev/null 2>&1; then
    say "  Installing the Xcode command-line tools…"
    ensure_sudo || { FAILED_STEP="administrator password"; phase_fail "run again and enter your Mac password when asked"; }
    retry "install Xcode command-line tools" install_clt ||
      phase_fail "install them by hand with 'xcode-select --install', then run this again"
  else
    say "  Xcode command-line tools: present"
  fi

  if [ -z "$(brew_bin)" ]; then
    say "  Installing Homebrew…"
    ensure_sudo || { FAILED_STEP="administrator password"; phase_fail "run again and enter your Mac password when asked"; }
    retry "download the Homebrew installer" download https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh "$RUN_DIR/brew-install.sh" ||
      phase_fail "check your internet connection, then run this again"
    retry "install Homebrew" env NONINTERACTIVE=1 /bin/bash "$RUN_DIR/brew-install.sh" ||
      phase_fail "see the log; Homebrew's own message names the problem"
  else
    say "  Homebrew: present ($(brew_bin))"
  fi
  eval "$("$(brew_bin)" shellenv)"

  local f
  for f in gh jq python@3.13; do
    if "$(brew_bin)" list --versions "$f" >/dev/null 2>&1; then
      say "  $f: present"
    else
      say "  Installing ${f}…"
      retry "brew install $f" brew_install "$f" || phase_fail "run 'brew install $f' to see the error, then run this again"
    fi
  done

  if [ -z "$(uv_bin)" ]; then
    # Never 'brew install uv': on Intel there is no bottle and it compiles LLVM.
    say "  Installing uv (Astral installer)…"
    retry "download the uv installer" download https://astral.sh/uv/install.sh "$RUN_DIR/uv-install.sh" ||
      phase_fail "check your internet connection, then run this again"
    retry "install uv" env UV_NO_MODIFY_PATH=1 /bin/sh "$RUN_DIR/uv-install.sh" ||
      phase_fail "see the log for the installer's message"
  else
    say "  uv: present ($(uv_bin))"
  fi
  export PATH="$HOME/.local/bin:$PATH"
  phase_pass
}

# ===========================================================================
# Phase 2: workspace
# ===========================================================================
PROFILE_BEGIN="# >>> omninode onboarding >>>"
PROFILE_END="# <<< omninode onboarding <<<"

write_profile_block() { # file
  local f="$1" tmp
  touch "$f"
  tmp="$(mktemp "$RUN_DIR/profile.XXXXXX")"
  awk -v b="$PROFILE_BEGIN" -v e="$PROFILE_END" '$0==b{skip=1} !skip{print} $0==e{skip=0}' "$f" >"$tmp"
  {
    printf '%s\n' "$PROFILE_BEGIN"
    printf 'export OMNIBASE_PATH="%s"\n' "$WORKSPACE"
    printf 'export OMNI_HOME="%s"   # legacy name, still read by the reconcile scripts\n' "$WORKSPACE"
    # shellcheck disable=SC2016  # written literally; expands in the user's shell
    printf 'eval "$(%s shellenv)"\n' "$(brew_bin)"
    # shellcheck disable=SC2016
    printf 'case ":$PATH:" in *":$HOME/.local/bin:"*) ;; *) export PATH="$HOME/.local/bin:$PATH" ;; esac\n'
    printf '%s\n' "$PROFILE_END"
  } >>"$tmp"
  cat "$tmp" >"$f" && rm -f "$tmp"
}

sync_clone() { # repo
  local d="$WORKSPACE/$1" def
  if [ -d "$d/.git" ]; then
    git -C "$d" fetch --quiet origin || return 1
    def="$(git -C "$d" symbolic-ref --quiet --short refs/remotes/origin/HEAD 2>/dev/null | sed 's#^origin/##')"
    [ -n "$def" ] || return 0
    # A canonical clone is read-only: fast-forward it only when it sits clean
    # on its default branch; anything else is the developer's and is left alone.
    if [ "$(git -C "$d" rev-parse --abbrev-ref HEAD)" = "$def" ] && [ -z "$(git -C "$d" status --porcelain)" ]; then
      git -C "$d" merge --ff-only --quiet "origin/$def" || true
    fi
    return 0
  fi
  rm -rf "$d"
  git clone --quiet --filter=blob:none "$GITHUB_ORG_URL/$1.git" "$d"
}

phase2_verified() {
  local r
  for r in $REPOS; do [ -d "$WORKSPACE/$r/.git" ] || return 1; done
  grep -qF "$PROFILE_BEGIN" "$HOME/.zshrc" 2>/dev/null
}

phase2() {
  phase_start 2 "Workspace ($WORKSPACE)" "2-5 minutes"
  if is_done 2 && phase2_verified; then phase_pass "already in place"; return; fi
  mkdir -p "$WORKSPACE" || { FAILED_STEP="create $WORKSPACE"; phase_fail "choose another directory with --workspace"; }
  local r
  for r in $REPOS; do
    if [ -d "$WORKSPACE/$r/.git" ]; then say "  $r: present, fetching"; else say "  $r: cloning"; fi
    retry "clone or fetch $r" sync_clone "$r" || phase_fail "check that github.com is reachable, then run this again"
  done
  write_profile_block "$HOME/.zshrc"
  case "${SHELL:-}" in */bash) write_profile_block "$HOME/.bash_profile" ;; esac
  export OMNIBASE_PATH="$WORKSPACE" OMNI_HOME="$WORKSPACE"
  say "  OMNIBASE_PATH (and legacy OMNI_HOME), Homebrew and ~/.local/bin are set in your shell profile (new terminals pick them up)."
  phase_pass
}

# ===========================================================================
# Phase 3: onex, the local identity, one model path, one delegation
# ===========================================================================
ONEX=""
onex_run() { env -u PYTHONPATH "$ONEX" "$@"; }

link_onex() {
  local wrapper="$WORKSPACE/omnibase_infra/scripts/onex" link="$HOME/.local/bin/onex" uvb
  mkdir -p "$HOME/.local/bin"
  if [ -L "$link" ] && [ "$(readlink "$link")" = "$wrapper" ]; then return 0; fi
  if [ -e "$link" ] || [ -L "$link" ]; then
    # A PyPI onex here outranks the workspace wrapper and fails the workspace
    # floor (local-dev guide D5). The floor's own remedy is to uninstall it.
    uvb="$(uv_bin)"
    if [ -n "$uvb" ] && "$uvb" tool list 2>/dev/null | grep -q '^omnibase-core '; then
      "$uvb" tool uninstall omnibase-core || return 1
    fi
    if [ -e "$link" ] || [ -L "$link" ]; then mv "$link" "$link.pre-onboarding.$STAMP" || return 1; fi
  fi
  ln -s "$wrapper" "$link"
}

provider_offered() { # slug -> 0 when onex routes a key for it
  "$WORKSPACE/.onex-dispatch-venv/bin/python" - "$1" <<'PY' 2>>"$LOG"
import sys
from omnimarket.routing.byok_provider_backends import resolve_byok_provider_backend
sys.exit(0 if resolve_byok_provider_backend(sys.argv[1]) is not None else 1)
PY
}

provider_endpoints() { # slug -> the endpoint URLs the catalogue routes that provider's keys to (routable plans only)
  "$WORKSPACE/.onex-dispatch-venv/bin/python" - "$1" <<'PY' 2>>"$LOG"
import sys
from importlib.resources import files
import yaml
doc = yaml.safe_load(files("omnimarket").joinpath("configs/byok_provider_backends.v1.yaml").read_text())
urls = set()
def walk(node):
    if isinstance(node, dict):
        if node.get("provider") == sys.argv[1] and node.get("endpoint_url") and node.get("customer_routable", True):
            urls.add(node["endpoint_url"])
        for v in node.values(): walk(v)
    elif isinstance(node, list):
        for v in node: walk(v)
walk(doc)
print(" ".join(sorted(urls)))
PY
}

key_stored() { onex_run secret list 2>/dev/null | grep -qE "^[[:space:]]+llm\.$1\.api_key[[:space:]]"; }

# A lab-model overrides file an earlier version of this script wrote declares a
# local model, and routing takes a declared local model before a registered key,
# so the key would never be used. Moved aside (never deleted). A file the
# developer wrote is left alone and named.
retire_lab_model_overrides() {
  local f="$HOME/.omninode/delegation/bifrost_overrides.yaml"
  [ -f "$f" ] || return 0
  if head -n 1 "$f" | grep -qE '^# Written by (lab-onboarding|omninode-dev-setup)'; then
    mv "$f" "$f.pre-key.$STAMP"
    say "  Moved aside the local-model routes an earlier run wrote, so your key is used."
  else
    say "  ⚠ $f declares a local model; it is used before your key. Remove it if you want the key used."
  fi
}

# The provider's own words from the latest capture log (a delegation that fails on
# the provider is retried and ends in a timeout that names none of them).
provider_error() {
  local c
  # shellcheck disable=SC2012  # onex names its capture files; newest-first is what matters
  c="$(ls -t "$HOME/.onex_state/captures/"*.log 2>/dev/null | head -n 1)"
  [ -n "$c" ] || return 0
  grep -A3 'provider response' "$c" | grep -E '"message"' | tail -n 1 |
    sed -e 's/^[^:]*"message": *"//' -e 's/",\{0,1\} *$//' | cut -c1-300
}

# receipt_field JSON KEY -> the first value of KEY anywhere in the receipt JSON
receipt_field() { printf '%s' "$1" | jq -r --arg k "$2" '[.. | objects | .[$k]? // empty] | first // empty' 2>/dev/null; }

delegate_hello() { # -> stdout: the run's receipt.json (it names the endpoint and model)
  # Mode 1 is the in-process bus. Said explicitly: through the workspace wrapper a
  # bare `onex delegate` treats the workspace as a registry workspace and refuses
  # without a declared runtime config.
  local out line receipt
  # stderr too: the "delegate artifacts:" line naming receipt.json is printed there.
  out="$(cd "$HOME" && onex_run delegate --json --bus inmemory "Reply with exactly one word: hello" 2>&1)" ||
    { printf '%s\n' "$out" >>"$LOG"; return 1; }
  line="$(printf '%s\n' "$out" | grep -E '^\{' | tail -n 1)"
  [ "$(receipt_field "$line" status)" = "success" ] || { printf '%s\n' "$out" >>"$LOG"; return 1; }
  receipt="$(printf '%s\n' "$out" | tr ' ' '\n' | grep -E '/receipt\.json$' | tail -n 1)"
  [ -f "$receipt" ] || { echo "the delegation named no receipt.json" >&2; return 1; }
  cat "$receipt"
}

phase3() {
  phase_start 3 "onex, local identity and your model" "3-10 minutes"
  local endpoint

  say "  Building the workspace dispatch environment (onex)…"
  retry "build the dispatch venv" nice -n 10 bash "$WORKSPACE/omnibase_infra/scripts/reconcile-workspace-venvs.sh" --omni-home "$WORKSPACE" ||
    phase_fail "see the log; the script names the exact command to run by hand"
  step "point ~/.local/bin/onex at the workspace wrapper" link_onex ||
    phase_fail "remove ~/.local/bin/onex by hand, then run this again"
  ONEX="$HOME/.local/bin/onex"
  step "onex --version" onex_run --version || phase_fail "run 'onex --version' to see why it does not start"
  say "  $(onex_run --version 2>/dev/null | tail -n 1)"

  if onex_run local identity >/dev/null 2>&1; then
    say "  Local identity: present"
  else
    step "onex local init" onex_run local init || phase_fail "run 'onex local init' to see the error"
    say "  Local identity: minted"
  fi

  local choice="$MODEL_CHOICE"
  if [ "$choice" = "ollama" ]; then phase3_ollama; return; fi
  # The key settled in preflight. No lab-model fallback: without a routable key
  # the phase fails.
  if ! provider_offered "$choice"; then
    PENDING_KEY=""
    FAILED_STEP="check that onex routes a $choice key"
    LAST_ERR="this onex's provider catalogue does not offer $choice yet; the key was not stored"
    phase_fail "update the omnimarket clone, or run this again with another provider (--provider gemini|openrouter|openai|ollama)"
  fi
  if [ -n "$PENDING_KEY" ]; then
    # The CLI checks the key before storing it and refuses one the catalogue
    # does not allow; its words are shown.
    local refusal
    if refusal="$(printf '%s' "$PENDING_KEY" | onex_run secret set --force "llm.$choice.api_key" 2>&1)"; then
      PENDING_KEY=""
      printf '%s\n' "$refusal" >>"$LOG"
      say "  Stored your $choice key in the onex secret store."
      printf '%s\n' "$refusal" | grep -E '^Model:' | sed 's/^/  /' | tee -a "$LOG"
    else
      PENDING_KEY=""
      printf '%s\n' "$refusal" >>"$LOG"
      FAILED_STEP="store the $choice key"
      LAST_ERR="$(printf '%s\n' "$refusal" | grep -E 'Error|refus|not ' | tail -n 3 | tr '\n' ' ' | cut -c1-400)"
      say "  $LAST_ERR"
      phase_fail "use a key the message above allows, then run this again with --provider $choice"
    fi
  elif key_stored "$choice"; then
    say "  Your $choice key is already stored; keeping it."
  else
    FAILED_STEP="your $choice key"; LAST_ERR="no key is stored and none was given"
    phase_fail "run this again and paste your key when asked"
  fi
  retire_lab_model_overrides

  say "  Running one delegation…"
  if ! retry_capture "one onex delegate" delegate_hello; then
    local perr; perr="$(provider_error)"
    if [ -n "$perr" ]; then
      LAST_ERR="$choice said: $perr"
      phase_fail "fix it on the provider's side (the message above names what), then run this again"
    fi
    phase_fail "run 'onex delegate \"Reply with exactly one word: hello\"' to see the error"
  fi
  endpoint="$(receipt_field "$CAPTURED" endpoint)"
  # Exact URL, not host: one provider can serve several routes from one host. A
  # receipt naming any other endpoint (a lab model included) fails the phase.
  local urls ok=0 p
  urls="$(provider_endpoints "$choice")"
  for p in $urls; do [ "$p" = "$endpoint" ] && ok=1; done
  if [ "$ok" -ne 1 ]; then
    FAILED_STEP="check the delegation went to your $choice key"
    LAST_ERR="the receipt names ${endpoint:-no endpoint}, not a $choice route (${urls:-none declared})"
    phase_fail "the key was stored but did not route; run 'onex secret list' and 'onex delegate --json \"hello\"' to see why"
  fi
  say "  Delegation answered by $(receipt_field "$CAPTURED" model) at ${endpoint:-an endpoint the receipt does not name}"
  CAPTURED=""
  phase_pass "model: your $choice key"
}

phase3_ollama() {
  step "read the Ollama settings from the workspace's model config" load_ollama_config ||
    phase_fail "update the omnimarket clone (its model config declares the ollama block), then run this again"
  local need=$((M1_DISK_GB + OLLAMA_DOWNLOAD_GB))
  if ! ollama_has_model "$OLLAMA_MODEL" 2>/dev/null && [ "$(disk_free_gb)" -lt "$need" ]; then
    FAILED_STEP="free disk for $OLLAMA_MODEL"
    LAST_ERR="$(disk_free_gb) GB free; $OLLAMA_MODEL needs about $OLLAMA_DOWNLOAD_GB GB more ($need GB in all)"
    phase_fail "free some disk, or run this again with --provider gemini, openrouter or openai (a key, no download)"
  fi
  if [ -z "$(ollama_bin)" ]; then
    say "  Installing Ollama (the app; it carries the ollama command)…"
    retry "install Ollama" install_ollama ||
      phase_fail "install Ollama from ollama.com/download, then run this again"
    [ -n "$(ollama_bin)" ] || { FAILED_STEP="find Ollama after installing it"; phase_fail "install Ollama from ollama.com/download, then run this again"; }
  else
    say "  Ollama: present"
  fi
  step "start Ollama" start_ollama || phase_fail "open the Ollama app once, then run this again"
  if ollama_has_model "$OLLAMA_MODEL"; then
    say "  Model $OLLAMA_MODEL: present"
  else
    say "  Downloading $OLLAMA_MODEL (about $OLLAMA_DOWNLOAD_GB GB)…"
    retry "download $OLLAMA_MODEL" "$(ollama_bin)" pull "$OLLAMA_MODEL" ||
      phase_fail "run 'ollama pull $OLLAMA_MODEL' to see the error, then run this again"
  fi
  step "point onex's local routes at Ollama" write_ollama_overrides "$OLLAMA_MODEL" ||
    phase_fail "see the log; $HOME/$OVERRIDES_FILE_REL was not written"

  say "  Running one delegation on $OLLAMA_MODEL (a local model can take a minute)…"
  retry_capture "one onex delegate" delegate_hello ||
    phase_fail "run 'onex delegate \"Reply with exactly one word: hello\"' to see the error"
  local endpoint model
  endpoint="$(receipt_field "$CAPTURED" endpoint)"; model="$(receipt_field "$CAPTURED" model)"
  CAPTURED=""
  if [ "$endpoint" != "$OLLAMA_URL$OLLAMA_CHAT_PATH" ]; then
    FAILED_STEP="check the delegation went to Ollama"
    LAST_ERR="the receipt names ${endpoint:-no endpoint}, not $OLLAMA_URL$OLLAMA_CHAT_PATH"
    phase_fail "a key stored by an earlier run may be routing first; run 'onex delegate --json \"hello\"' to see the route"
  fi
  say "  Delegation answered by $model at $endpoint"
  [ "$OLLAMA_HEADLESS" -eq 1 ] && say "  Ollama is running without its app here; after a restart, start it with 'ollama serve'."
  phase_pass "model: $OLLAMA_MODEL on this Mac (Ollama)"
}

# accepted_backend JSON -> the backend id of the attempt whose answer was accepted
accepted_backend() {
  printf '%s' "$1" | jq -r '[.. | objects | select(.backend_id? != null and .acceptance_decision? == "accept") | .backend_id] | first // empty' 2>/dev/null
}

# ===========================================================================
# Phase 4: containers (optional)
# ===========================================================================
docker_settings_file() {
  local d="$HOME/Library/Group Containers/group.com.docker"
  if [ -f "$d/settings-store.json" ]; then echo "$d/settings-store.json"; else echo "$d/settings.json"; fi
}

size_docker() { # memory MiB, cpus -> 0 changed, 1 error, 2 already enough
  "$(brew_bin | sed 's#/brew$##')/python3.13" - "$(docker_settings_file)" "$1" "$2" <<'PY'
import json, os, sys
path, mem, cpus = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
data = json.load(open(path)) if os.path.exists(path) else {}
mem_key = "MemoryMiB" if "MemoryMiB" in data or path.endswith("settings-store.json") else "memoryMiB"
cpu_key = "Cpus" if "Cpus" in data or path.endswith("settings-store.json") else "cpus"
if int(data.get(mem_key, 0)) >= mem and int(data.get(cpu_key, 0)) >= cpus:
    sys.exit(2)
data[mem_key] = max(mem, int(data.get(mem_key, 0)))
data[cpu_key] = max(cpus, int(data.get(cpu_key, 0)))
if os.path.exists(path):
    os.replace(path, path + ".pre-onboarding")
os.makedirs(os.path.dirname(path), exist_ok=True)
json.dump(data, open(path, "w"), indent=2)
PY
}

docker_awaits_terms() { # Docker Desktop is showing its licence window and will not start until accepted
  pgrep -f 'Docker Desktop.*--name=new-license' >/dev/null 2>&1
}

# Wait for the engine; if Docker Desktop is holding at its licence screen, say so
# (accepting Docker's terms is the developer's decision, never this script's).
wait_for_docker() {
  local t0=$SECONDS told=0
  while [ $((SECONDS - t0)) -lt 600 ]; do
    docker_ready && return 0
    if [ "$told" -eq 0 ] && docker_awaits_terms; then
      say "  Docker Desktop is waiting for you to accept its terms in its own window."
      say "  Accept them there (or quit Docker and run this with --no-containers); waiting up to 10 minutes…"
      notify "Action needed" "Accept Docker Desktop's terms in its window"
      told=1
    fi
    sleep 5
  done
  FAILED_STEP="Docker Desktop to start (waited 10m)"
  if docker_awaits_terms; then LAST_ERR="Docker Desktop is still showing its licence terms"; else LAST_ERR="$(last_log_lines)"; fi
  return 1
}

accept_docker_terms() { # fresh install only, and only with the developer's yes
  local a="n"
  say "  Docker Desktop requires accepting the Docker Subscription Service Agreement:"
  say "    https://www.docker.com/legal/docker-subscription-service-agreement"
  if [ "$PROMPT_TTY" -eq 1 ]; then
    printf '  Accept it now? [y/N] '; IFS= read -r a
  elif [ "$GUI_SESSION" -eq 1 ]; then
    a="$(/usr/bin/osascript 2>/dev/null <<'OSA'
set r to display dialog "Docker Desktop requires accepting the Docker Subscription Service Agreement (docker.com/legal/docker-subscription-service-agreement)." & return & return & "Accept it now? If not, Docker Desktop shows its terms when it starts." with title "Docker's terms" buttons {"Not now", "Accept"} default button "Accept" with icon note
if button returned of r is "Accept" then return "y"
return "n"
OSA
)"
  fi
  # shellcheck disable=SC2024  # the log is the user's own file; only install needs root
  case "$a" in
    y|Y|yes|YES) sudo -n /Applications/Docker.app/Contents/MacOS/install --accept-license --user "$(id -un)" >>"$LOG" 2>&1 ;;
    *) say "  Not accepted here; Docker Desktop will show its terms when it starts." ;;
  esac
  return 0
}

restart_docker() {
  if docker desktop restart >/dev/null 2>&1; then return 0; fi
  /usr/bin/osascript -e 'quit app "Docker"' >/dev/null 2>&1 || true
  sleep 5
  open -g -a Docker
}

compose_ok() { # compose 2.20 or newer
  local v; v="$(docker compose version --short 2>&1 | sed 's/^v//')"
  echo "docker compose version: ${v:-none}"
  case "$v" in [0-9]*) ;; *) return 1 ;; esac
  local major="${v%%.*}" rest="${v#*.}"; local minor="${rest%%.*}"
  [ "$major" -gt 2 ] || { [ "$major" -eq 2 ] && [ "$minor" -ge 20 ]; }
}

stack_healthy() {
  local s; s="$(cd "$WORKSPACE/omnibase_infra" && make -s status-local 2>&1)"
  printf '%s\n' "$s" | grep -q 'migration-gate: healthy' &&
    curl -fsS -m 5 http://localhost:8085/health | grep -q '"healthy"' &&
    curl -fsS -m 5 http://localhost:8086/health | grep -q '"healthy"'
}

sed_inplace() { # sed expressions and file; no backup suffix on either implementation
  if sed --version >/dev/null 2>&1; then
    sed -i "$@"
  else
    sed -i '' "$@"
  fi
}

point_bundle_model() { # url model -> the stack's local-model slot names that server and model
  local f="$HOME/.omnibase/local.bifrost.yaml" url="$1" model="$2"
  [ -f "$f" ] || return 1
  # An overlay the developer already pointed somewhere is theirs; only the
  # untouched template (a model server on this Mac) is rewritten.
  grep -q '&model_endpoint "http://host.docker.internal' "$f" || return 0
  cp -p "$f" "$f.pre-onboarding.$STAMP"
  sed_inplace -e "s#&model_endpoint \"http://host.docker.internal[^\"]*\"#\\&model_endpoint \"$url\"#" \
    -e "s#served_model_id: \"[^\"]*\"#served_model_id: \"$model\"#" "$f"
}

# A tenant on the stack means every delegation runs on a key registered for that
# tenant and nothing else, so the stack only gets one when a key was chosen.
STACK_TENANT_CHANGED=0
ensure_stack_tenant() {
  local out
  out="$(make -s -C "$WORKSPACE/omnibase_infra" tenant-local 2>&1)" || { printf '%s\n' "$out" >>"$LOG"; return 1; }
  printf '%s\n' "$out" >>"$LOG"
  case "$out" in *"Added ONEX_TENANT_ID"*) STACK_TENANT_CHANGED=1 ;; esac
  return 0
}

# Your key goes from your onex store into the stack's own store by a pipe: never
# an argument, an environment variable or a file.
register_key_in_stack() { # provider
  "$WORKSPACE/.onex-dispatch-venv/bin/python" - "$1" <<'PY' | make -s -C "$WORKSPACE/omnibase_infra" secret-local PROVIDER="$1"
import asyncio, sys
from omnimarket.inference.local_byok_credential_adapter import LocalByokCredentialStore
value = asyncio.run(LocalByokCredentialStore().get_secret(f"llm.{sys.argv[1]}.api_key"))
if not value:
    sys.exit(3)
sys.stdout.write(value)
PY
}

stack_delegate() { # -> stdout: the run's JSON; it names the backend that answered
  local out
  out="$(make -s -C "$WORKSPACE/omnibase_infra" delegate-local DELEGATE_FLAGS=--json PROMPT="Reply with exactly one word: hello" 2>>"$LOG")" || return 1
  out="$(printf '%s\n' "$out" | grep -E '^\{' | tail -n 1)"
  [ "$(receipt_field "$out" status)" = "success" ] || { printf '%s\n' "$out" >>"$LOG"; return 1; }
  printf '%s\n' "$out"
}

phase4() {
  phase_start 4 "Docker (optional: the local stack, on your key)" "10-20 minutes the first time"
  if [ "$MODE2_OK" -ne 1 ]; then phase_skip "${MODE2_WHY# }"; return; fi
  if is_done 4 && docker_ready && stack_healthy; then phase_pass "already running"; return; fi

  local host_ram mem_gb mem free disk
  host_ram="$(ram_gb)"
  mem_gb=$DOCKER_MEM_GB
  [ $((host_ram - mem_gb)) -lt "$HOST_RESERVE_GB" ] && mem_gb=$((host_ram - HOST_RESERVE_GB))
  mem=$((mem_gb * 1024))

  if ! docker_installed; then
    say "  Installing Docker Desktop…"
    ensure_sudo || { FAILED_STEP="administrator password"; phase_fail "run again and enter your Mac password when asked"; }
    retry "install Docker Desktop" sh -c "'$(brew_bin)' install --cask docker-desktop || '$(brew_bin)' install --cask docker" ||
      phase_fail "install Docker Desktop from docker.com, then run this again"
    accept_docker_terms
  else
    say "  Docker Desktop: present"
  fi

  size_docker "$mem" "$DOCKER_CPUS"
  case $? in
    0) say "  Docker Desktop set to ${mem_gb} GB and $DOCKER_CPUS CPUs; restarting it…"
       docker_ready && restart_docker >>"$LOG" 2>&1 ;;
    2) say "  Docker Desktop already has at least ${mem_gb} GB and $DOCKER_CPUS CPUs" ;;
    *) FAILED_STEP="size Docker Desktop"; LAST_ERR="$(last_log_lines)"
       phase_fail "set Settings > Resources to ${mem_gb} GB and $DOCKER_CPUS CPUs by hand, then run this again" ;;
  esac
  if ! docker_ready; then
    say "  Starting Docker Desktop…"
    notify "Starting Docker Desktop" "The local stack comes up once Docker is running"
    open -g -a Docker
  fi
  wait_for_docker ||
    phase_fail "open Docker Desktop; if it asks you to accept its terms or to update, do that, then run this again"
  say "  Docker Desktop: running"
  step "docker compose 2.20 or newer" compose_ok || phase_fail "update Docker Desktop, then run this again"

  free="$(avail_mem_gb)"; disk="$(disk_free_gb)"
  if [ "$free" -lt "$BOOT_FREE_MEM_GB" ] || [ "$disk" -lt "$BOOT_FREE_DISK_GB" ]; then
    FAILED_STEP="resources at boot time"
    LAST_ERR="${free} GB memory available (needs $BOOT_FREE_MEM_GB) and ${disk} GB disk free (needs $BOOT_FREE_DISK_GB)"
    phase_fail "close other apps or free disk space, then run this again"
  fi

  # Launching Docker restarts a stack that was already there (restart policies).
  local_stack_running && STACK_RUNNING=1
  if [ "$STACK_RUNNING" -eq 1 ]; then
    say "  The local stack is already there; checking it instead of rebuilding it."
  else
    step "make local-env" make -C "$WORKSPACE/omnibase_infra" local-env || phase_fail "see the log for make local-env's message"
    if [ "$MODEL_CHOICE" = "ollama" ]; then
      step "point the stack's local model at Ollama" point_bundle_model "http://host.docker.internal:$OLLAMA_PORT$OLLAMA_CHAT_PATH" "$OLLAMA_MODEL" ||
        phase_fail "set model_endpoint and served_model_id in ~/.omnibase/local.bifrost.yaml by hand, then run this again"
    fi
  fi
  # The key path: the stack serves a tenant of its own and holds your key for it.
  if uses_key "$MODEL_CHOICE"; then
    step "give the stack a tenant for your key" ensure_stack_tenant ||
      phase_fail "run 'make tenant-local' in omnibase_infra, then run this again"
  fi
  if [ "$STACK_RUNNING" -eq 0 ] || [ "$STACK_TENANT_CHANGED" -eq 1 ]; then
    say "  Building and starting the local stack (make up-local)…"
    retry "make up-local" nice -n 10 make -C "$WORKSPACE/omnibase_infra" up-local ||
      phase_fail "see the log; 'make status-local' from omnibase_infra shows what is not up"
  fi
  say "  Waiting for the stack to report healthy (a cold boot takes several minutes)…"
  wait_until "the local stack to become healthy" 900 15 stack_healthy ||
    phase_fail "run 'make status-local' in omnibase_infra; if the main kernel is still provisioning topics, wait and run this again"
  if uses_key "$MODEL_CHOICE"; then
    step "register your $MODEL_CHOICE key in the stack's own store" register_key_in_stack "$MODEL_CHOICE" ||
      phase_fail "run 'make secret-local PROVIDER=$MODEL_CHOICE' in omnibase_infra and paste the key, then run this again"
    sleep 10   # the tenant credentials projection turns the registration into your route
  fi
  retry_capture "one delegation through the stack" stack_delegate ||
    phase_fail "the stack is up but the delegation failed; see the log"
  local served; served="$(accepted_backend "$CAPTURED")"; CAPTURED=""
  if [ "$MODEL_CHOICE" = "ollama" ]; then
    case "$served" in
      local-*) say "  Answered by Ollama on this Mac ($served)." ;;
      *) FAILED_STEP="check the stack's delegation went to Ollama"
         LAST_ERR="the answer came from ${served:-no backend}, not a local route"
         phase_fail "check that Ollama is running and ~/.omnibase/local.bifrost.yaml names it" ;;
    esac
  elif uses_key "$MODEL_CHOICE"; then
    # A delegation that falls through to another route still reports success, so
    # the accepted backend is what proves the key was used.
    case "$served" in
      "byok-$MODEL_CHOICE"*) say "  Answered by your $MODEL_CHOICE key ($served)." ;;
      *) FAILED_STEP="check the delegation went to your $MODEL_CHOICE key"
         LAST_ERR="the answer came from ${served:-no backend}, not byok-$MODEL_CHOICE"
         phase_fail "the key is registered but did not route; see 'make status-local' and the runtime logs" ;;
    esac
  else
    say "  Answered by ${served:-an unnamed backend}."
  fi
  phase_pass "stack healthy, one delegation answered (stop it with 'make down-local' from the checkout that started it)"
}

# ===========================================================================
# Phase 5: Claude Code plugins
# ===========================================================================
install_claude_code() {
  download https://claude.ai/install.sh "$RUN_DIR/claude-install.sh" && bash "$RUN_DIR/claude-install.sh"
}

claude_bin() { command -v claude || echo "$HOME/.local/bin/claude"; }
plugin_installed() { "$(claude_bin)" plugin list 2>/dev/null | grep -Eq "[[:space:]]$1[[:space:]]*\$"; }

# omni and onex-overlays come from a private repository that the marketplace
# clones over SSH: this GitHub login must read it, and an SSH key must be loaded.
internal_plugins_reachable() {
  gh api repos/OmniNode-ai/omniclaude-internal --silent >>"$LOG" 2>&1 || return 1
  ssh -o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -T git@github.com 2>&1 |
    grep -q 'successfully authenticated'
}

phase5() {
  phase_start 5 "Claude Code plugins (the full onex tree; omni where you have access)" "1-2 minutes"
  if ! command -v claude >/dev/null 2>&1 && [ ! -x "$HOME/.local/bin/claude" ]; then
    say "  Installing Claude Code…"
    retry "install Claude Code" install_claude_code || phase_fail "install Claude Code from claude.com/claude-code, then run this again"
  fi
  local claude; claude="$(claude_bin)"

  # The full onex tree (every /onex: skill and guard hook) is a directory
  # marketplace in the omniclaude clone, so it moves with that clone.
  if plugin_installed onex@omninode-tools-dev; then
    say "  onex@omninode-tools-dev: installed"
  else
    "$claude" plugin marketplace list 2>/dev/null | grep -q 'omninode-tools-dev' ||
      step "add the onex dev marketplace from your omniclaude clone" \
        "$claude" plugin marketplace add "$WORKSPACE/omniclaude/plugins/"*-dev-marketplace ||
      phase_fail "could not add the onex dev marketplace from your omniclaude clone; check the log for the error"
    step "install onex@omninode-tools-dev" "$claude" plugin install onex@omninode-tools-dev ||
      phase_fail "run 'claude plugin install onex@omninode-tools-dev' to see the error"
  fi
  if plugin_installed onex@omninode-tools; then
    say "  ⚠ The public onex@omninode-tools (two skills) is also installed; the full tree includes them."
    say "    Remove it with 'claude plugin uninstall onex@omninode-tools' so each /onex: skill appears once."
  fi

  local note="start a new Claude Code session to load them"
  if internal_plugins_reachable; then
    "$claude" plugin marketplace list 2>/dev/null | grep -q 'omninode-internal' ||
      retry "add the omniclaude-internal marketplace" "$claude" plugin marketplace add OmniNode-ai/omniclaude-internal ||
      phase_fail "run 'claude plugin marketplace add OmniNode-ai/omniclaude-internal' to see the error"
    local p
    for p in omni onex-overlays; do
      if plugin_installed "$p@omninode-internal"; then
        say "  $p@omninode-internal: installed"
      else
        retry "install $p@omninode-internal" "$claude" plugin install "$p@omninode-internal" ||
          phase_fail "run 'claude plugin install $p@omninode-internal' to see the error"
      fi
    done
  else
    say "  omni and onex-overlays: not installed. They come from the private omniclaude-internal"
    say "    repository, which needs read access for your GitHub login and an SSH key loaded"
    say "    for GitHub. With both, run this again."
    note="$note; omni skipped (no access to omniclaude-internal)"
  fi
  phase_pass "$note"
}

# ===========================================================================
# Phase 6: verify
# ===========================================================================
CHECKS_FAILED=0
check() { # label cmd...
  local label="$1"; shift
  if "$@" >>"$LOG" 2>&1; then say "  ✔ $label"; else say "  ✘ $label"; CHECKS_FAILED=$((CHECKS_FAILED + 1)); fi
}
sqlite_rows() {
  [ "$(sqlite3 -readonly "$HOME/.omninode/delegation/delegation.sqlite" 'select count(*) from delegation_events;' 2>/dev/null || echo 0)" -ge 1 ]
}
no_shadow() { [ "$(readlink "$HOME/.local/bin/onex")" = "$WORKSPACE/omnibase_infra/scripts/onex" ]; }

# The workspace floor the onex wrapper enforces before any --lane command. If dev
# moved while this ran, the clones fast-forward here but the dispatch venv built
# in phase 3 is behind; the floor's own remedy is to rebuild it and reconcile again.
reconcile_host() { nice -n 10 bash "$WORKSPACE/omnibase_infra/scripts/reconcile-host.sh" --omni-home "$WORKSPACE"; }
workspace_floor() {
  reconcile_host && return 0
  nice -n 10 bash "$WORKSPACE/omnibase_infra/scripts/reconcile-workspace-venvs.sh" --omni-home "$WORKSPACE" &&
    reconcile_host
}

phase6() {
  phase_start 6 "Verify" "about a minute"
  [ -n "$ONEX" ] || ONEX="$HOME/.local/bin/onex"
  check "onex starts ($(onex_run --version 2>/dev/null | tail -n 1))" onex_run --version
  check "local identity minted" onex_run local identity
  check "onex is the workspace wrapper, not a PyPI copy" no_shadow
  check "workspace floor proven (reconcile-host IN_SYNC)" retry "reconcile the workspace floor" workspace_floor
  check "a delegation row in the local store" sqlite_rows
  check "onex metering reads it" onex_run metering
  if [ "$MODEL_CHOICE" = "ollama" ]; then
    check "Ollama answers on this Mac" ollama_up
    check "Ollama has $OLLAMA_MODEL" ollama_has_model "$OLLAMA_MODEL"
  fi
  check "the full onex plugin installed in Claude Code" plugin_installed onex@omninode-tools-dev
  if [ "$MODE2_OK" -eq 1 ]; then check "local stack healthy" stack_healthy; fi
  if [ -n "$AMBIENT_FOUND" ]; then
    say "  ⚠ Your shell profile still exports settings that redirect onex (listed in phase 0)."
  fi
  if [ "$CHECKS_FAILED" -gt 0 ]; then
    FAILED_STEP="$CHECKS_FAILED check(s) failed"
    phase_fail "the ✘ lines above name what is wrong; fix them and run this again"
  fi
  phase_pass
}

# ===========================================================================
main() {
  say "OmniNode developer onboarding (local runtime). Status file: $STATUS"
  [ "$RESTART" -eq 1 ] && rm -f "$DONE_FILE"
  phase0
  [ "$PREFLIGHT_ONLY" -eq 1 ] && { say "Preflight only: nothing was changed."; exit 0; }
  phase1
  phase2
  phase3
  phase4
  phase5
  phase6
  hr
  say "Done. Set up: $SELECTED."
  if [ "$MODEL_CHOICE" = "ollama" ]; then
    say "Model: $OLLAMA_MODEL on this Mac, through Ollama (no key)."
  else
    say "Model: your own $(provider_label "$MODEL_CHOICE") key."
  fi
  say "Next:"
  say "  1. Open a new terminal (or run 'exec zsh') so OMNIBASE_PATH and PATH take effect."
  say "  2. Open Claude Code (run 'claude') and sign in with your Anthropic account the first"
  say "     time it asks. The onex skills are already installed; /onex:delegate is one of them."
  notify "Onboarding complete" "Every phase passed"
  printf 'result=COMPLETE\n' >>"$STATUS"
}

main
