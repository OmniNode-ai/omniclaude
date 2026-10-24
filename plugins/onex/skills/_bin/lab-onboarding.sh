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
#   0 Preflight          reads the machine, and runs the onex your shell already has; every
#                        question is asked here: what an earlier setup left (set aside, or
#                        stop), your models and their keys, Docker, and the Mac password.
#                        Changes nothing unless you agree to set leftovers aside
#   1 Base tools         Xcode command-line tools, Homebrew, gh, jq, python@3.13, uv
#   2 Workspace          the clones at this script's anchor (one omnibase_infra commit), OMNIBASE_PATH, PATH
#   3 onex + models      dispatch venv, onex, local identity, then each model you chose set up
#                        with `onex models add` and tested with one delegation pinned to it
#   4 Docker             optional: only if you said yes; Docker Desktop installed, or started
#                        if stopped, then the local stack on your keys
#   5 Claude Code        the customer plugin, onex@omninode-tools: one skill, /onex:delegate.
#                        With --developer: the full onex plugin from your omniclaude clone,
#                        and omni and onex-overlays when this login can read the private plugin repository
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
#   --provider LIST      one or more of gemini, openrouter, openai, ollama, local,
#                        comma-separated (default: asked up front). Gemini, OpenRouter and
#                        OpenAI take your own key, asked for one at a time; Ollama runs a
#                        model on this Mac, no key; local is a model server you already run
#                        (LM Studio, llama.cpp, vLLM, MLX) that speaks the OpenAI API, by its
#                        URL and model name, no key. Delegation chooses among the ones set up
#   --ollama-model NAME  the model Ollama downloads (default: asked, from the models this Mac has
#                        the memory for; with no terminal, the one sized to it)
#   --local-url URL      the local model server's base URL, such as http://127.0.0.1:1234
#                        (default: asked when local is chosen)
#   --local-model NAME   the model that server runs, as it names it (default: asked)
#   --workspace DIR      the workspace (default: $OMNIBASE_PATH, else ~/Code/omnibase). A directory
#                        that already holds clones this setup did not create is refused
#   --set-aside          answer yes in advance to setting aside what an earlier setup left
#                        (an onex alias, old variables in your profile, a published onex,
#                        a local-model routes file, clones holding work); each is moved or
#                        commented out, never deleted
#   --developer          install the full developer plugin set in phase 5 instead of
#                        the customer plugin (every /onex: skill and guard hook, and omni)
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
# OMNIBASE_PATH is the workspace variable, and the only one. OMNI_HOME
# names the operator's private orchestration workspace: it is never read, never
# written to a profile and never exported, and it is unset here so no child
# (the onex wrapper prefers an inherited one over its own location) can reach it.
DEFAULT_WORKSPACE="$HOME/Code/omnibase"
if [ -n "${OMNIBASE_PATH:-}" ]; then
  WORKSPACE="$OMNIBASE_PATH"; WORKSPACE_FROM="from OMNIBASE_PATH"
else
  WORKSPACE="$DEFAULT_WORKSPACE"; WORKSPACE_FROM="the default; OMNIBASE_PATH is not set"
fi
# What an earlier setup leaves in the environment silently redirects onex: a
# workspace or internal clone, a lab tenant, a state directory, an event bus, a
# routing overlay. This run and everything it starts inherit none of it, on
# every run including a resumed one; the names are kept for preflight's report.
INHERITED_ENV=""
for _v in $(compgen -e); do
  case "$_v" in
    OMNI_HOME|OMNIBASE_*|ONEX_*|BIFROST_*|KAFKA_*|DELEGATION_ROUTING_TIERS_PATH|DELEGATION_ROUTING_OVERLAY_PATH|POSTGRES_PASSWORD|VALKEY_PASSWORD|PYTHONPATH)
      INHERITED_ENV="${INHERITED_ENV}${INHERITED_ENV:+ }$_v"; unset "$_v" ;;
  esac
done
unset OMNI_HOME
RESTART=0; DEVELOPER=0
SET_ASIDE_FLAG=0
OLLAMA_MODEL=""; LOCAL_URL=""; LOCAL_MODEL=""

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
    --local-url) shift; LOCAL_URL="${1:-}" ;;
    --local-model) shift; LOCAL_MODEL="${1:-}" ;;
    --workspace) shift; WORKSPACE="${1:-}"; WORKSPACE_FROM="from --workspace" ;;
    --workspace=*) WORKSPACE="${1#*=}"; WORKSPACE_FROM="from --workspace" ;;
    --restart) RESTART=1 ;; --developer) DEVELOPER=1 ;;
    --set-aside) SET_ASIDE_FLAG=1 ;;
    -h|--help) usage; exit 0 ;;
    *) printf 'omninode-dev-setup: unknown option: %s (see --help)\n' "$1" >&2; exit 2 ;;
  esac
  shift
done
for _p in $(printf '%s' "$PROVIDER" | tr ',' ' '); do
  case "$_p" in openrouter|gemini|openai|ollama|local) ;; *)
    printf 'omninode-dev-setup: --provider must be gemini, openrouter, openai, ollama or local (or a comma-separated list of them)\n' >&2; exit 2 ;;
  esac
done
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

# Every question is asked in the terminal, and all of them in preflight, before
# anything installs, so they never interleave with the progress that follows.
# The desktop is used only for the notification when a phase ends.
PROMPT_TTY=$IS_TTY

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
# A resumed run picks up at the phase that failed. A phase an earlier run passed is
# checked, not redone; when it does run again, the run says why instead of
# silently starting it over.
rerun_note() { # phase why
  say "  Phase $1 passed in an earlier run, but $2, so it runs again."
}

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
# Privilege and secrets, asked in the terminal. A value is held only in a shell
# variable and handed over on stdin.
# ---------------------------------------------------------------------------
SUDO_KEEPALIVE_PID=""
ensure_sudo() {
  sudo -n true 2>/dev/null && return 0
  if [ "$PROMPT_TTY" -eq 1 ]; then
    say "  Installing needs your Mac administrator password (asked once, by sudo)."
    sudo -v || return 1
  else
    say "  Administrator access is needed and there is no terminal to ask on."
    return 1
  fi
  if [ -z "$SUDO_KEEPALIVE_PID" ]; then
    ( while kill -0 "$$" 2>/dev/null; do sudo -n true 2>/dev/null; sleep 50; done ) &
    SUDO_KEEPALIVE_PID=$!
  fi
  return 0
}

# Whether the phases ahead install something that needs the administrator
# password, so preflight asks for it once, with the other questions.
needs_admin() {
  if [ -n "${ONBOARD_TEST_NEEDS_ADMIN:-}" ]; then [ "$ONBOARD_TEST_NEEDS_ADMIN" = "1" ]; return; fi
  xcode-select -p >/dev/null 2>&1 || return 0
  [ -n "$(brew_bin)" ] || return 0
  [ "$MODE2_OK" -eq 1 ] && [ "$(docker_state)" = "not installed" ] && return 0
  return 1
}

# The developer chose to stop. Only offered before anything installs, so it is
# true that nothing was installed.
quit_setup() {
  clear_keys; SECRET=""
  say ""
  say "  Nothing was installed. Run onboarding again when you're ready."
  printf 'phase=0 name="Preflight" result=QUIT\n' >>"$STATUS"
  notify "Setup stopped" "Nothing was installed. Run onboarding again when you're ready."
  exit 4
}

read_secret() { # prompt -> SECRET, read hidden from the terminal; empty at end of input
  SECRET=""
  printf '%s ' "$1"
  IFS= read -r -s SECRET || SECRET=""
  printf '\n'
}

cleanup() {
  [ -n "$SUDO_KEEPALIVE_PID" ] && kill "$SUDO_KEEPALIVE_PID" 2>/dev/null
  SECRET=""; CAPTURED=""; clear_keys
  return 0
}
trap cleanup EXIT

ask_docker() { # note -> 0 yes, 1 no, 2 quit. Asked in the terminal; never a flag.
  local a=""
  say ""
  say "  One optional extra: running the stack on this Mac"
  say ""
  say "  $1" | fold -s -w 84 | sed '2,$s/^/  /'
  say ""
  say "  You're already covered: onex runs your delegations natively on this Mac, on the"
  say "  models you chose."
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
    IFS= read -r a || a=""
  else
    say "  No terminal to ask on, so the stack is not run locally (--containers adds it)."
  fi
  case "$a" in y|Y|yes|YES) return 0 ;; q|Q|quit|QUIT) return 2 ;; *) return 1 ;; esac
}

# ---------------------------------------------------------------------------
# Your models: any combination of Gemini, OpenRouter, OpenAI, Ollama and a
# local model server by URL, at least one. For each key and for Ollama the developer picks
# the models, in order (see the bootstrap handler); delegation chooses among them for each
# task, so the developer never picks one per run. Settled in preflight, before anything installs, so the run
# never stops mid-way to ask. Each key is held only in this process (never
# exported, logged or written) until phase 3 hands it to `onex models add` on
# stdin.
# ---------------------------------------------------------------------------
ALL_MODELS="gemini openrouter openai ollama local"
MODELS=""     # the chosen models, in menu order, space-separated
SKIPPED=""    # chosen, then skipped at the key prompt
STORED=""     # providers an earlier run already stored a key for
KEY_GEMINI=""; KEY_OPENROUTER=""; KEY_OPENAI=""

pending_key() { case "$1" in gemini) printf '%s' "$KEY_GEMINI" ;; openrouter) printf '%s' "$KEY_OPENROUTER" ;; openai) printf '%s' "$KEY_OPENAI" ;; esac; }
set_pending_key() { case "$1" in gemini) KEY_GEMINI="$2" ;; openrouter) KEY_OPENROUTER="$2" ;; openai) KEY_OPENAI="$2" ;; esac; }
clear_keys() { KEY_GEMINI=""; KEY_OPENROUTER=""; KEY_OPENAI=""; }

uses_key() { case "$1" in gemini|openrouter|openai) return 0 ;; *) return 1 ;; esac; }
in_list() { case " $2 " in *" $1 "*) return 0 ;; *) return 1 ;; esac; } # word list
has_model() { in_list "$1" "$MODELS"; }
is_stored() { in_list "$1" "$STORED"; }
drop_model() { local p out=""; for p in $MODELS; do [ "$p" = "$1" ] || out="$out $p"; done; MODELS="${out# }"; }
keyed_models() { local p out=""; for p in $MODELS; do uses_key "$p" && out="$out $p"; done; echo "${out# }"; }
count_words() { set -- $1; echo $#; }
in_menu_order() { local p out=""; for p in $ALL_MODELS; do in_list "$p" "$1" && out="$out $p"; done; echo "${out# }"; }

provider_label() {
  case "$1" in
    gemini) echo "Gemini" ;;
    openrouter) echo "OpenRouter" ;;
    openai) echo "OpenAI" ;;
    ollama) echo "Ollama" ;; local) echo "Local URL" ;;
    anthropic) echo "Anthropic (Claude)" ;;
    *) echo "$1" ;;
  esac
}
labels() { local p out=""; for p in $1; do out="$out, $(provider_label "$p")"; done; echo "${out#, }"; }
a_an() { case "$1" in [AEIOUaeiou]*) echo "an" ;; *) echo "a" ;; esac; }
key_page() { case "$1" in gemini) echo "aistudio.google.com/apikey" ;; openrouter) echo "openrouter.ai/keys" ;; openai) echo "platform.openai.com/api-keys" ;; esac; }

# The provider whose keys start like this one, most specific prefix first (an
# OpenRouter or Anthropic key also starts with sk-); empty when unknown.
key_looks_like() {
  case "$1" in
    sk-or-*) echo openrouter ;;
    sk-ant-*) echo anthropic ;;
    AIza*) echo gemini ;;
    sk-*) echo openai ;;
  esac
}

stored_key_providers() { # every provider an earlier run already stored a key for, one per line
  [ -x "$HOME/.local/bin/onex" ] || return 1
  local p list found=1
  list="$(env -u PYTHONPATH "$HOME/.local/bin/onex" secret list 2>/dev/null)" || return 1
  for p in gemini openrouter openai; do
    printf '%s\n' "$list" | grep -qE "^[[:space:]]+llm\.$p\.api_key[[:space:]]" && { echo "$p"; found=0; }
  done
  return "$found"
}

# With no terminal there is nobody to ask: --provider names the models, else
# every stored key (and Ollama, when an earlier run set it up) is used. A model
# that needs a key and has none stops the run before anything installs.
settle_models_unattended() {
  local p missing=""
  if [ -z "$MODELS" ]; then
    MODELS="$STORED"
    ollama_overrides_ours && MODELS="$MODELS ollama"
    MODELS="$(in_menu_order "$MODELS")"
  fi
  for p in $(keyed_models); do is_stored "$p" || missing="$missing $p"; done
  if [ -z "$MODELS" ] || [ -n "$missing" ]; then
    FAILED_STEP="choose your models"
    if [ -n "$missing" ]; then LAST_ERR="no key is stored for$missing, and there is no terminal to ask for one on"
    else LAST_ERR="no model was chosen, and there is no terminal to ask on"; fi
    phase_fail "run this in Terminal, or pass --provider with models whose keys are stored, or ollama. Nothing was installed"
  fi
  say "  No terminal to ask on, so these models are used: $(labels "$MODELS")."
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
  [ -n "$CHOSEN_OLLAMA" ] && OLLAMA_MODEL="${CHOSEN_OLLAMA%% *}"
  [ -n "$OLLAMA_MODEL" ] || OLLAMA_MODEL="$(sed -n 's/^    model_name: "\(.*\)"$/\1/p' "$HOME/$OVERRIDES_FILE_REL" 2>/dev/null | head -n 1)"
  if [ -n "$CHOSEN_OLLAMA" ]; then
    say "  Models: Ollama on this Mac, no key. Your models, first tried first: $(comma_list "$CHOSEN_OLLAMA")."
  elif [ -n "$OLLAMA_MODEL" ]; then
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

# The node's bootstrap handler runs on stock macOS Bash before Python exists.
# Prefer the checkout beside this entrypoint; downloaded copies fetch the same
# checksum-pinned handler into the run directory. Never source unchecked bytes.
#
# A downloaded copy fetches the handler from a commit on dev, and checks it
# against download_digest. A pull request that changes the handler cannot name
# a dev commit that holds its new bytes (the merge queue squashes, so no branch
# commit reaches dev), so for that one change the two digests differ and a
# downloaded copy keeps the handler already on dev; the next pull request names
# the merge commit and sets download_digest back to digest.
load_onboarding_preflight() {
  local rel="src/omniclaude/nodes/node_skill_omninode_dev_setup_orchestrator/handler_onboarding_preflight.sh"
  local digest="3978:63fc:a74a:14dd:47de:a7bb:f730:d9dc:9a39:309d:3ce1:92eb:8d56:1240:9e75:36a9" root candidate \
    download_digest="7f96:7d1b:ba3c:aae3:d4ed:d234:a933:964d:b5bf:2f75:5ae9:23b4:e9ca:939c:8387:3cba"
  digest="${digest//:/}"; download_digest="${download_digest//:/}"
  root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." 2>/dev/null && pwd)"
  for candidate in "$root/$rel" "$PWD/$rel" "$WORKSPACE/omniclaude/$rel"; do
    [ -f "$candidate" ] || continue
    if printf '%s  %s\n' "$digest" "$candidate" | shasum -a 256 -c - >/dev/null 2>&1; then
      . "$candidate"
      return 0
    fi
  done
  candidate="$RUN_DIR/handler_onboarding_preflight.sh"
  if ! curl -fsSL --retry 3 -o "$candidate" "https://raw.githubusercontent.com/OmniNode-ai/omniclaude/ad32c82a0a9274c6506b9016aae40fd87590e620/$rel" ||
     ! printf '%s  %s\n' "$download_digest" "$candidate" | shasum -a 256 -c - >/dev/null 2>&1; then
    printf 'omninode-dev-setup: cannot load the checksum-pinned onboarding preflight handler\n' >&2
    return 1
  fi
  . "$candidate"
}
load_onboarding_preflight || exit 1

phase0() {
  phase_start 0 "Preflight (reads this Mac; changes nothing you have not agreed to)" "under a minute"
  local mv major cpus ram disk vm="physical Mac" p busy="" dstate m2disk a
  mv="$(macos_version)"; major="${mv%%.*}"
  case "$major" in ''|*[!0-9]*) major=0 ;; esac
  cpus="$(cpu_count)"; ram="$(ram_gb)"; disk="$(disk_free_gb)"
  is_vm && vm="virtual machine"
  dstate="$(docker_state)"
  m2disk=$M2_DISK_GB
  [ "$dstate" != "not installed" ] && m2disk=$M2_DISK_GB_DOCKER_PRESENT

  say "  Log file: $LOG"
  say "  Workspace: $WORKSPACE ($WORKSPACE_FROM)"
  resume_banner
  refuse_foreign_workspace
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

  # Before anything installs: what an earlier setup left, run as your shell runs it.
  survey_leftovers
  report_leftovers

  MODE1_WHY="${MODE1_WHY%;}"; MODE2_WHY="${MODE2_WHY%;}"
  if [ "$MODE1_OK" -eq 0 ]; then
    say "✘ This Mac is below the minimum requirements:$MODE1_WHY"
    say "  Nothing was installed. Use $VM_SPEC, and run this command inside it."
    printf 'phase=0 name="Preflight" result=BELOW_MINIMUM why="%s"\n' "$MODE1_WHY" >>"$STATUS"
    notify "Below minimum requirements" "Nothing was installed. See the terminal for the recommended VM."
    exit 3
  fi

  # Every question is asked here, before anything installs: the models come
  # first (every run needs at least one), then Docker, asked only when this Mac
  # can run it (the flags answer it in advance), then its licence terms, then
  # the administrator password.
  settle_leftovers
  if [ "$PREFLIGHT_ONLY" -eq 0 ] && is_vm; then vm_notice; fi
  [ "$PREFLIGHT_ONLY" -eq 1 ] || settle_models

  local docker_note
  case "$dstate" in
    running) docker_note="We found Docker Desktop on this Mac, and it's running. Do you want to use it to run the stack locally too?" ;;
    "installed, not running") docker_note="We found Docker Desktop on this Mac, but it isn't running. If you want the stack, we'll start it for you." ;;
    *) docker_note="Docker Desktop isn't installed on this Mac. If you want the stack, we'll install it for you (it may ask you to accept Docker's terms)." ;;
  esac
  if [ "$MODE2_OK" -eq 1 ] && [ -z "$WANT_CONTAINERS" ] && [ "$RESUMING" -eq 1 ] && [ -n "$(saved_choice containers)" ]; then
    WANT_CONTAINERS="$(saved_choice containers)"
    if [ "$WANT_CONTAINERS" = 1 ]; then say "  Docker: yes, as in your last run (--no-containers changes it)."
    else say "  Docker: no, as in your last run (--containers changes it)."; NO_CONTAINERS_WHY="you said no in your last run"; fi
  fi
  if [ "$MODE2_OK" -eq 1 ]; then
    case "$WANT_CONTAINERS" in
      1) ;;
      0) MODE2_OK=0; MODE2_WHY=" ${NO_CONTAINERS_WHY:---no-containers was passed}" ;;
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
  if [ "$PREFLIGHT_ONLY" -eq 0 ] && [ "$MODE2_OK" -eq 1 ] && [ "$dstate" = "not installed" ]; then ask_docker_terms; fi
  if [ "$PREFLIGHT_ONLY" -eq 0 ] && needs_admin; then
    say ""
    ensure_sudo || { FAILED_STEP="administrator password"; LAST_ERR="sudo was not given the password"
      phase_fail "run this again and enter your Mac password when asked. Nothing was installed"; }
  fi
  [ "$PREFLIGHT_ONLY" -eq 1 ] || set_aside_leftovers
  say ""
  say "  Will set up: $SELECTED"
  [ "$PREFLIGHT_ONLY" -eq 1 ] || say "  Models: $(labels "$MODELS")"
  say "  Everything from here runs without questions."
  phase_pass "$SELECTED"
}


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
  is_done 1 && rerun_note 1 "the base tools it installed (Xcode tools, Homebrew, uv, gh, jq, python@3.13) are no longer all present"

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
    # The routing overlay the handler writes (write_routing_overlay) is bound here too.
    printf 'export ONEX_WORKSPACE_CONFIG_ROOT="%s"\nexport DELEGATION_ROUTING_OVERLAY_PATH="%s"\n' "$WORKSPACE_CONFIG_ROOT" "$ROUTING_OVERLAY_FILE"
    # shellcheck disable=SC2016  # written literally; expands in the user's shell
    printf 'eval "$(%s shellenv)"\n' "$(brew_bin)"
    # shellcheck disable=SC2016
    printf 'case ":$PATH:" in *":$HOME/.local/bin:"*) ;; *) export PATH="$HOME/.local/bin:$PATH" ;; esac\n'
    printf '%s\n' "$PROFILE_END"
  } >>"$tmp"
  cat "$tmp" >"$f" && rm -f "$tmp"
}

# A workspace this setup created carries this marker, written before its first
# clone. Phase 2 checks out the proven pin in every clone, which would detach a
# developer's own clones, so a workspace holding clones without the marker is
# refused. A V1 workspace (no marker yet) is recognised by the runtime config
# V1 wrote there after cloning, and is adopted.
WORKSPACE_MARKER="$WORKSPACE/.omninode-dev-setup"

foreign_clones() { # -> the repos present in the workspace that this setup did not create
  local r found=""
  [ -f "$WORKSPACE_MARKER" ] && return 0
  workspace_runtime_config_present && return 0
  for r in $REPOS; do
    [ -e "$WORKSPACE/$r" ] && found="${found}${found:+ }$r"
  done
  printf '%s' "$found"
}

refuse_foreign_workspace() {
  local found; found="$(foreign_clones)"
  [ -z "$found" ] && return 0
  FAILED_STEP="check the workspace"
  LAST_ERR="$WORKSPACE holds clones this setup did not create: $found"
  say "  $WORKSPACE holds clones this setup did not create ($found)."
  say "  They are left untouched: setup would check each one out at its proven commit."
  phase_fail "choose an empty or new directory with --workspace DIR (or set OMNIBASE_PATH to one); nothing was changed in $WORKSPACE"
}

# Clone or fetch only; the commit each clone is checked out at is decided by anchored_commit.
sync_clone() { # repo
  local d="$WORKSPACE/$1"
  if [ -e "$d/.git" ]; then
    git -C "$d" fetch --quiet origin
    return
  fi
  # Something that is not a clone stands where one goes: moved aside, never deleted.
  if [ -e "$d" ] && [ -n "$(ls -A "$d" 2>/dev/null)" ]; then
    mkdir -p "$WORKSPACE/.set-aside" && mv "$d" "$WORKSPACE/.set-aside/$1.$STAMP" || return 1
    echo "moved $d (not a clone) to $WORKSPACE/.set-aside/$1.$STAMP"
  fi
  rm -rf "$d"   # an empty directory, or what a failed clone attempt left
  git clone --quiet --filter=blob:none "$GITHUB_ORG_URL/$1.git" "$d"
}

clone_default_branch() { # repo -> origin's default branch, as last fetched
  local def
  def="$(git -C "$WORKSPACE/$1" symbolic-ref --quiet --short refs/remotes/origin/HEAD 2>/dev/null)"
  def="${def#origin/}"
  if [ -z "$def" ]; then
    for def in dev main master; do
      git -C "$WORKSPACE/$1" rev-parse --verify --quiet "refs/remotes/origin/$def" >/dev/null && break
      def=""
    done
  fi
  printf '%s' "$def"
}

# clone_state repo -> one line describing the clone, measured against origin as
# last fetched: "missing", or "<where>|<changed>|<behind>|<unique>|<default>",
# where <where> is a branch name or "detached", <changed> counts tracked files
# changed or deleted (untracked files never block a checkout of a clean tree),
# <behind> is how far HEAD is behind origin's default branch, and <unique> counts
# commits at HEAD that origin does not have.
clone_state() { # repo
  local d="$WORKSPACE/$1" def where changed behind=0 unique=0
  [ -d "$d/.git" ] || [ -f "$d/.git" ] || { printf 'missing'; return 0; }
  def="$(clone_default_branch "$1")"
  where="$(git -C "$d" symbolic-ref --quiet --short HEAD 2>/dev/null || echo detached)"
  changed="$(git -C "$d" status --porcelain --untracked-files=no 2>/dev/null | wc -l | tr -d ' ')"
  if [ -n "$def" ]; then
    behind="$(git -C "$d" rev-list --count "HEAD..origin/$def" 2>/dev/null || echo 0)"
    unique="$(git -C "$d" rev-list --count "origin/$def..HEAD" 2>/dev/null || echo 0)"
  fi
  printf '%s|%s|%s|%s|%s' "$where" "$changed" "$behind" "$unique" "$def"
}

# clone_problem repo state -> empty when setup can bring the clone current by
# itself; else what is wrong with it, in words. Setup never discards work: tracked
# changes and commits origin does not have are the developer's.
clone_problem() { # repo state
  local where changed behind unique def
  IFS='|' read -r where changed behind unique def <<EOF
$2
EOF
  local why="" diverged=0
  [ "${changed:-0}" -gt 0 ] && why="$changed tracked file(s) changed or deleted"
  [ "${unique:-0}" -gt 0 ] && why="${why}${why:+; }$unique commit(s) that origin does not have"
  # A default branch holding commits origin lacks is the developer's work, even
  # with the clone off it, so it is named here, before any clone moves.
  if [ -n "$def" ] && [ "$where" != "$def" ] &&
     git -C "$WORKSPACE/$1" rev-parse --verify --quiet "refs/heads/$def" >/dev/null; then
    diverged="$(git -C "$WORKSPACE/$1" rev-list --count "origin/$def..refs/heads/$def" 2>/dev/null || echo 0)"
  fi
  [ "${diverged:-0}" -gt 0 ] &&
    why="${why}${why:+; }its $def branch has $diverged commit(s) that origin does not have, so it cannot fast-forward"
  [ -n "$why" ] || return 0
  printf '%s (%s, %s commit(s) behind origin/%s)' "$why" "$(clone_where "$where")" "${behind:-0}" "${def:-?}"
}

clone_where() { case "$1" in detached) echo "detached HEAD" ;; *) echo "on branch $1" ;; esac; }

commits_behind() { # n -> "1 commit" or "n commits"
  if [ "$1" = 1 ]; then echo "1 commit"; else echo "$1 commits"; fi
}

# What an old clone lacks is named for what it is: a clone behind origin, never a
# file to restore. Empty when the clone is current.
clone_behind_note() { # repo state
  local where changed behind unique def note
  IFS='|' read -r where changed behind unique def <<EOF
$2
EOF
  [ "${behind:-0}" -gt 0 ] || return 0
  note="clone is $(commits_behind "$behind") behind origin/${def:-?}"
  [ "$1" = omnibase_infra ] && [ ! -f "$WORKSPACE/omnibase_infra/.github/sibling-pins.yaml" ] &&
    note="$note and predates .github/sibling-pins.yaml, which origin has"
  printf '%s' "$note"
}

# The command that clears clone_problem without losing anything: the clone moves
# aside whole, and the next run clones it fresh.
clone_fix() { # repo
  printf 'mkdir -p "%s" && mv "%s" "%s"' "$WORKSPACE/.set-aside" "$WORKSPACE/$1" "$WORKSPACE/.set-aside/$1.$STAMP"
}

# ---------------------------------------------------------------------------
# The anchor.
#
# This script is emailed pinned by commit and sha256, and the code it installs
# is pinned here, by one omnibase_infra commit. Phase 2 checks omnibase_infra
# out at INFRA_ANCHOR, never at its branch tip, so the sibling pins it reads
# (.github/sibling-pins.yaml) and the commits they name are the anchor's. A repo
# the pins file does not name is checked out at the last commit of origin's
# default branch at or before the anchor's commit time. Nothing then depends on
# where any `dev` has moved since: the same email installs the same commits.
# A participant gets a fix only through a new email that pins a script naming a
# newer anchor. ONBOARD_TEST_INFRA_ANCHOR exists for the tests' fixture repos.
INFRA_ANCHOR="${ONBOARD_TEST_INFRA_ANCHOR:-aa81312c2c405424d4c947d61c7763d38e67b3a1}"

# ---------------------------------------------------------------------------
# The workspace's tier-1 runtime config.
#
# Phase 2 binds OMNIBASE_PATH to the workspace root, and a bound root is a
# registry workspace: its transport comes from its OWN tier-1 config and is
# never answered with the shipped default, because reaching the in-memory bus
# by silent fallback is how a workspace's delegation evidence stranded in local
# storage once before. A bound root with no config is REFUSED, so without this
# file every default `onex delegate` on a freshly set-up machine fails --
# including the delegate skill in Claude Code.
#
# WHY THE FILE IS GENERATED, NEVER COPIED. The canonical internal workspace
# carries its own tier-1 config naming a lab lane. Copying it would put a lab
# address on a developer machine, which this script must never do. A developer
# install runs entirely on this Mac, so the in-memory bus IS the correct
# transport here, and what is forbidden is reaching it by fallback rather than
# by declaration -- the refusal itself names selecting a transport explicitly as
# the sanctioned route. This file is that choice, recorded once, instead of
# every developer having to know `--bus inmemory`.
#
# The container stack declares its own transport through its compose lane; this
# file is the native answer and the CLI's default.
WORKSPACE_CONFIG_ROOT="$WORKSPACE/.onex/workspace-config"
WORKSPACE_RUNTIME_CONFIG_REL="config/onex/runtime/runtime_config.yaml"
WORKSPACE_RUNTIME_CONFIG_MARK="# Written by omninode-dev-setup."

write_workspace_runtime_config() {
  local f="$WORKSPACE_CONFIG_ROOT/$WORKSPACE_RUNTIME_CONFIG_REL"
  mkdir -p "$(dirname "$f")" || return 1
  cat >"$f" <<YAML
$WORKSPACE_RUNTIME_CONFIG_MARK
# The tier-1 runtime configuration of this developer workspace. The workspace
# root is bound through OMNIBASE_PATH, so its transport is declared here rather
# than inherited. It names no lab address, deliberately.
# Anchor: omnibase_infra $INFRA_ANCHOR
description: "Developer workspace tier-1 runtime configuration: in-memory bus, local profile"
input_topic: "requests"
output_topic: "responses"
group_id: "onex-runtime"
event_bus:
  type: "inmemory"
  profile: "local"
  environment: "local"
  max_history: 1000
  circuit_breaker_threshold: 5
YAML
}

# The materialiser reads the config from git (origin/main of the config root), and
# warns "Could not locate runtime config repository" on every delegation when the
# root is a plain directory. So the root is a repository whose main, and the local
# ref origin/main beside it, carry the file. It has no remote and never pushes.
#
# The commit the materialiser reports is the anchor's: one root
# commit whose file names INFRA_ANCHOR, dated at the anchor's commit time, with a
# fixed identity and message. Its sha is then a function of the anchor alone,
# the same on every Mac and every run, and it moves only when the anchor does.
config_git() { # git in the workspace config root, with an identity of its own
  git -C "$WORKSPACE_CONFIG_ROOT" -c user.name=omninode-dev-setup \
    -c user.email=dev-setup@omninode.invalid -c commit.gpgsign=false "$@"
}

commit_workspace_runtime_config() {
  local when tree commit
  if [ ! -d "$WORKSPACE_CONFIG_ROOT/.git" ]; then
    config_git init --quiet && config_git symbolic-ref HEAD refs/heads/main || return 1
  fi
  when="$(anchor_time)"
  [ -n "$when" ] || return 1
  config_git add "$WORKSPACE_RUNTIME_CONFIG_REL" || return 1
  tree="$(config_git write-tree)" || return 1
  commit="$(GIT_AUTHOR_DATE="$when" GIT_COMMITTER_DATE="$when" config_git commit-tree "$tree" \
    -m "workspace runtime config for omnibase_infra $INFRA_ANCHOR (omninode-dev-setup)")" || return 1
  config_git update-ref refs/heads/main "$commit" &&
    config_git update-ref refs/remotes/origin/main "$commit"
}

workspace_runtime_config_anchored() {
  git -C "$WORKSPACE_CONFIG_ROOT" show "origin/main:$WORKSPACE_RUNTIME_CONFIG_REL" 2>/dev/null |
    grep -qxF "# Anchor: omnibase_infra $INFRA_ANCHOR"
}

# Bound for every run, not inside phase 2 alone: a resumed run skips phase 2,
# and its later phases must still run against this workspace.
bind_workspace_env() {
  export OMNIBASE_PATH="$WORKSPACE" ONEX_WORKSPACE_CONFIG_ROOT="$WORKSPACE_CONFIG_ROOT"
  # A bound overlay that does not exist refuses every delegation, so only a written one is bound.
  [ ! -f "${ROUTING_OVERLAY_FILE:-}" ] || export DELEGATION_ROUTING_OVERLAY_PATH="$ROUTING_OVERLAY_FILE"
}

workspace_runtime_config_present() {
  grep -qF "$WORKSPACE_RUNTIME_CONFIG_MARK" \
    "$WORKSPACE_CONFIG_ROOT/$WORKSPACE_RUNTIME_CONFIG_REL" 2>/dev/null
}

phase2_verified() {
  local r
  [ -d "$WORKSPACE/omnibase_infra/.git" ] && clone_at_anchor omnibase_infra || return 1
  [ -f "$WORKSPACE/omnibase_infra/.github/sibling-pins.yaml" ] || return 1
  for r in $REPOS; do
    [ -d "$WORKSPACE/$r/.git" ] || return 1
    clone_at_anchor "$r" || return 1
  done
  workspace_runtime_config_present || return 1
  workspace_runtime_config_anchored || return 1
  [ -f "$WORKSPACE_MARKER" ] && routing_overlay_in_place || return 1
  grep -qF "$PROFILE_BEGIN" "$HOME/.zshrc" 2>/dev/null || return 1
  # A V1 block still exports OMNI_HOME: redo the phase so the block is rewritten.
  ! profile_block_names_legacy_home "$HOME/.zshrc" && ! profile_block_names_legacy_home "$HOME/.bash_profile"
}

profile_block_names_legacy_home() { # file
  [ -f "$1" ] || return 1
  awk -v b="$PROFILE_BEGIN" -v e="$PROFILE_END" \
    '$0==b{in_block=1} in_block && /OMNI_HOME/{found=1} $0==e{in_block=0} END{exit !found}' "$1"
}

phase2() {
  phase_start 2 "Workspace ($WORKSPACE)" "2-5 minutes"
  if is_done 2 && phase2_verified; then phase_pass "already in place"; return; fi
  is_done 2 && rerun_note 2 "the workspace no longer checks out (every clone at its anchored commit, the pins file, the runtime config, the routing overlay and the profile block)"
  refuse_foreign_workspace
  mkdir -p "$WORKSPACE" || { FAILED_STEP="create $WORKSPACE"; phase_fail "choose another directory with --workspace"; }
  [ -f "$WORKSPACE_MARKER" ] || printf 'This workspace was created by omninode-dev-setup.\n' >"$WORKSPACE_MARKER" ||
    { FAILED_STEP="mark the workspace"; phase_fail "could not write $WORKSPACE_MARKER; check the directory is writable"; }
  local r pin want default_repos="" problem problems="" state note seen=""
  for r in $REPOS; do
    if [ -e "$WORKSPACE/$r/.git" ]; then say "  $r: present, fetching"; else say "  $r: cloning"; fi
    retry "clone or fetch $r" sync_clone "$r" || phase_fail "check that github.com is reachable, then run this again"
  done
  # Every clone is measured against origin before any of them moves, so one stop
  # names every clone that holds work, with how far behind it is and the command
  # that moves it aside. Nothing is changed in any clone when one is named.
  for r in $REPOS; do
    state="$(clone_state "$r")"
    problem="$(clone_problem "$r" "$state")"
    [ -n "$problem" ] || continue
    say "  ✗ $r: $problem"
    note="$(clone_behind_note "$r" "$state")"
    [ -n "$note" ] && say "      $r: $note"
    say "      to move it aside: $(clone_fix "$r")"
    problems="${problems}${problems:+ }$r"
  done
  if [ -n "$problems" ]; then
    FAILED_STEP="bring the clones up to date with origin"
    LAST_ERR="these clones hold work setup will not move: $problems"
    phase_fail "commit or stash that work, or move each clone aside with the command under it (the next run clones it fresh), then run this again"
  fi
  # omnibase_infra goes first, at the anchor: the pins file every other clone is
  # checked out from is the anchor's, never the one on origin's branch tip.
  for r in omnibase_infra $REPOS; do
    case " $seen " in *" $r "*) continue ;; esac
    seen="${seen}${seen:+ }$r"
    want="$(anchored_commit "$r")"
    [ -n "$want" ] ||
      { FAILED_STEP="find the commit of $r at the anchor"
        LAST_ERR="origin/$(clone_default_branch "$r") of $r has no commit at or before omnibase_infra ${INFRA_ANCHOR:0:12}"
        phase_fail "check that github.com is reachable and run this again; if it repeats, report it with the log"; }
    # An old clone is named as behind before it moves, never as missing a file.
    if [ "$(git -C "$WORKSPACE/$r" rev-parse HEAD 2>/dev/null)" != "$want" ]; then
      note="$(clone_behind_note "$r" "$(clone_state "$r")")"
      [ -n "$note" ] && say "  $r: $note; checking out its anchored commit"
    fi
    checkout_anchored "$r" "$want" ||
      { FAILED_STEP="check out the anchored commit of $r"
        phase_fail "check that origin has commit $want in $r ('git -C $WORKSPACE/$r fetch origin'), then run this again"; }
    pin=""
    [ "$r" = omnibase_infra ] || pin="$(proven_pin "$r")"
    if [ "$r" = omnibase_infra ]; then
      say "  $r: anchor ${want:0:12}"
      [ -f "$WORKSPACE/omnibase_infra/.github/sibling-pins.yaml" ] ||
        { FAILED_STEP="read the proven set (omnibase_infra/.github/sibling-pins.yaml)"
          LAST_ERR="omnibase_infra at the anchor ${INFRA_ANCHOR:0:12} has no .github/sibling-pins.yaml"
          phase_fail "nothing on this Mac is wrong: this script's anchor lacks its proven set; report it"; }
    elif [ -n "$pin" ]; then
      say "  $r: proven ${want:0:12}"
    else
      default_repos="${default_repos}${default_repos:+ }$r"
      say "  $r: ${want:0:12} (origin/$(clone_default_branch "$r") at the anchor's time)"
    fi
  done
  say "  Anchor: omnibase_infra ${INFRA_ANCHOR:0:12}; no proven pin, taken at the anchor's time: ${default_repos:-none}"
  # write_routing_overlay (the handler) declares the tier your own keys answer on.
  write_workspace_runtime_config && write_routing_overlay ||
    { FAILED_STEP="declare the workspace runtime config and routing overlay"
      phase_fail "could not write $WORKSPACE_CONFIG_ROOT/$WORKSPACE_RUNTIME_CONFIG_REL or $ROUTING_OVERLAY_FILE; check the directories are writable"; }
  step "commit the workspace runtime config" commit_workspace_runtime_config ||
    phase_fail "see the log; $WORKSPACE_CONFIG_ROOT must be a git repository holding the config"
  say "  Workspace transport declared in $WORKSPACE_RUNTIME_CONFIG_REL (in-memory: everything runs on this Mac)."
  write_profile_block "$HOME/.zshrc"
  case "${SHELL:-}" in */bash) write_profile_block "$HOME/.bash_profile" ;; esac
  bind_workspace_env
  say "  OMNIBASE_PATH, Homebrew and ~/.local/bin are set in your shell profile (new terminals pick them up)."
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

# receipt_field JSON KEY -> the first value of KEY anywhere in the receipt JSON
receipt_field() { printf '%s' "$1" | jq -r --arg k "$2" '[.. | objects | .[$k]? // empty] | first // empty' 2>/dev/null; }

delegate_hello() { # -> stdout: the run's receipt.json (it names the endpoint and model)
  # The floor does not exist until this run passes; the wrapper would refuse
  # delegation. Prove the dispatch venv through its own entrypoint first.
  # NO TRANSPORT FLAG, deliberately. Phase 2 declares the workspace's transport
  # in its tier-1 runtime config, so this check resolves the same transport as
  # the developer's own command instead of selecting the in-memory bus itself.
  local out line receipt
  # stderr too: the "delegate artifacts:" line naming receipt.json is printed there.
  out="$(cd "$HOME" && env -u PYTHONPATH "$WORKSPACE/.onex-dispatch-venv/bin/onex" delegate --json "Reply with exactly one word: hello" 2>&1)" ||
    { printf '%s\n' "$out" >>"$LOG"; return 1; }
  line="$(printf '%s\n' "$out" | grep -E '^\{' | tail -n 1)"
  [ "$(receipt_field "$line" status)" = "success" ] || { printf '%s\n' "$out" >>"$LOG"; return 1; }
  receipt="$(printf '%s\n' "$out" | tr ' ' '\n' | grep -E '/receipt\.json$' | tail -n 1)"
  [ -f "$receipt" ] || { echo "the delegation named no receipt.json" >&2; return 1; }
  cat "$receipt"
}

# The floor moves only after a run passed on these commits. A failed run leaves
# it untouched; stamp from the dispatch venv that answered, never clone HEAD.
stamp_proven_floor() {
  local -a sites
  sites=( "$WORKSPACE"/.onex-dispatch-venv/lib/python*/site-packages )
  [ "${#sites[@]}" -eq 1 ] && [ -d "${sites[0]}" ] || return 1
  "$WORKSPACE/.onex-dispatch-venv/bin/python" "$WORKSPACE/omnibase_infra/scripts/reconcile_verify_movement.py" \
    floor-from-venv --site-packages "${sites[0]}" \
    --lock "$WORKSPACE/omnibase_infra/uv.lock" --omni-home "$WORKSPACE" \
    --output "$WORKSPACE/.onex-workspace-floor.json"
}

# A resumed phase 3 does not rebuild a dispatch venv that already holds the
# proven set: the reconciler's --check mutates nothing and exits 0 when it does.
dispatch_venv_current() {
  [ -x "$WORKSPACE/.onex-dispatch-venv/bin/onex" ] || return 1
  env -u PYTHONPATH bash "$WORKSPACE/omnibase_infra/scripts/reconcile-workspace-venvs.sh" --omni-home "$WORKSPACE" --check
}

# Phase 3 hands each key to `onex models add` on stdin and tests the rest with
# `onex models test`: both run one delegation pinned to that model's backend,
# and a pin answered by any other backend fails. Through the dispatch venv's
# own entrypoint, like delegate_hello: the wrapper refuses until the floor is
# stamped, after this phase.
models_cmd() { (cd "$HOME" && env -u PYTHONPATH "$WORKSPACE/.onex-dispatch-venv/bin/onex" models "$@"); }

RES_GEMINI=""; RES_OPENROUTER=""; RES_OPENAI=""; RES_OLLAMA=""; RES_LOCAL=""
set_result() { case "$1" in gemini) RES_GEMINI="$2" ;; openrouter) RES_OPENROUTER="$2" ;; openai) RES_OPENAI="$2" ;; ollama) RES_OLLAMA="$2" ;; local) RES_LOCAL="$2" ;; esac; }
result_of() { case "$1" in gemini) echo "$RES_GEMINI" ;; openrouter) echo "$RES_OPENROUTER" ;; openai) echo "$RES_OPENAI" ;; ollama) echo "$RES_OLLAMA" ;; local) echo "$RES_LOCAL" ;; esac; }
passed_models() { local p out=""; for p in $MODELS; do case "$(result_of "$p")" in pass*) out="$out $p" ;; esac; done; echo "${out# }"; }

record_model_status() { # provider
  local r verdict
  r="$(result_of "$1")"
  case "$r" in pass:*) verdict=PASS ;; fail:*) verdict=FAIL ;; *) verdict=SKIPPED ;; esac
  printf 'model=%s result=%s detail="%s"\n' "$1" "$verdict" "$(printf '%s' "${r#*:}" | tr '"' "'")" >>"$STATUS"
}

# cause_of < text -> the line that says why a delegation failed: the last
# "Error: ..." line, else the last refusal, else nothing. A summary such as "the
# test delegation exited with status 1" is never the whole message on its own.
cause_of() {
  awk '/^Error: /{e=substr($0, 8)} /REFUSED|refused/{r=$0} END{if (e != "") print e; else if (r != "") print r}' |
    cut -c1-300
}

phase3() {
  phase_start 3 "onex, local identity and your models" "3-10 minutes, more when Ollama downloads a model"
  local p passed line
  is_done 3 && rerun_note 3 "its model tests are not kept between runs and the later phases need them; it rebuilds nothing that is current"

  if dispatch_venv_current >>"$LOG" 2>&1; then
    say "  The workspace dispatch environment (onex) already holds the proven set; not rebuilt."
  else
    say "  Building the workspace dispatch environment (onex)…"
    retry "build the dispatch venv" nice -n 10 bash "$WORKSPACE/omnibase_infra/scripts/reconcile-workspace-venvs.sh" --omni-home "$WORKSPACE" --proven ||
      phase_fail "see the log; the script names the exact command to run by hand"
  fi
  step "point ~/.local/bin/onex at the workspace wrapper" link_onex ||
    phase_fail "remove ~/.local/bin/onex by hand, then run this again"
  ONEX="$HOME/.local/bin/onex"
  step "onex --version" onex_run --version || phase_fail "run 'onex --version' to see why it does not start"
  say "  $(onex_run --version 2>/dev/null | tail -n 1)"
  step "onex models is available" models_cmd --help ||
    phase_fail "this onex has no 'onex models' command yet; update the omnimarket clone, then run this again"

  if onex_run local identity >/dev/null 2>&1; then
    say "  Local identity: present"
  else
    step "onex local init" onex_run local init || phase_fail "run 'onex local init' to see the error"
    say "  Local identity: minted"
  fi

  # Ollama's routes are written before any test: a keyless local model routes
  # first, so it must be in place for the unpinned check below.
  if has_model ollama; then
    if ! setup_ollama; then
      set_result ollama "fail:$FAILED_STEP: ${LAST_ERR:-see the log}"
      FAILED_STEP=""; LAST_ERR=""
    fi
  else
    retire_lab_model_overrides
  fi
  if has_model local; then prepare_local_url; fi

  say ""
  for p in $MODELS; do
    if [ -n "$(result_of "$p")" ]; then :; else
      say "  Setting up $(provider_label "$p") and running one delegation on it…"
      setup_model "$p"
    fi
    result_line "$p" | while IFS= read -r line; do say "  $line"; done
  done
  for p in $SKIPPED; do say "  $(result_line "$p")"; done
  for p in $MODELS $SKIPPED; do record_model_status "$p"; done


  passed="$(passed_models)"
  if [ -z "$passed" ]; then
    FAILED_STEP="set up at least one model"
    LAST_ERR="none of your models answered its test delegation (the lines above say why)"
    phase_fail "fix what the lines above name, then run this again, or add a model later with 'onex models add <provider>'"
  fi

  # One delegation with no pin: delegation chooses the model, as it will for the
  # developer's own work.
  say "  Running one delegation without choosing a model…"
  retry_capture "one onex delegate" delegate_hello ||
    { LAST_ERR="$(tail -n 60 "$LOG" | cause_of)"; LAST_ERR="${LAST_ERR:-$(last_log_lines)}"
      phase_fail "run 'onex delegate \"Reply with exactly one word: hello\"' in a new terminal to see the whole error"; }
  say "  Delegation chose $(receipt_field "$CAPTURED" model) ($(receipt_field "$CAPTURED" backend_id))."
  CAPTURED=""
  [ "$OLLAMA_HEADLESS" -eq 1 ] && say "  Ollama is running without its app here; after a restart, start it with 'ollama serve'."
  step "stamp the proven workspace floor" stamp_proven_floor ||
    phase_fail "see the log; the proven floor could not be written from the dispatch venv"
  phase_pass "$(count_words "$passed") of $(count_words "$MODELS $SKIPPED") models ready: $(labels "$passed")"
}

# Ollama installed and started, its model downloaded and onex's local routes
# pointed at it. 1 with FAILED_STEP and LAST_ERR set when a step fails, so a
# failure here costs Ollama alone and the run goes on with the other models.
setup_ollama() {
  step "read the Ollama settings from the workspace's model config" load_ollama_config || {
    LAST_ERR="the omnimarket clone's model config declares no ollama block; update it"; return 1; }
  local need=$((M1_DISK_GB + OLLAMA_DOWNLOAD_GB))
  if ! ollama_has_model "$OLLAMA_MODEL" 2>/dev/null && [ "$(disk_free_gb)" -lt "$need" ]; then
    FAILED_STEP="free disk for $OLLAMA_MODEL"
    LAST_ERR="$(disk_free_gb) GB free; $OLLAMA_MODEL needs about $OLLAMA_DOWNLOAD_GB GB more ($need GB in all)"
    return 1
  fi
  if [ -z "$(ollama_bin)" ]; then
    say "  Installing Ollama (the app; it carries the ollama command)…"
    retry "install Ollama" install_ollama || { LAST_ERR="install it from ollama.com/download"; return 1; }
    [ -n "$(ollama_bin)" ] || { FAILED_STEP="find Ollama after installing it"; LAST_ERR="install it from ollama.com/download"; return 1; }
  else
    say "  Ollama: present"
  fi
  step "start Ollama" start_ollama || { LAST_ERR="open the Ollama app once"; return 1; }
  local m
  for m in ${CHOSEN_OLLAMA:-$OLLAMA_MODEL}; do  # every model the developer chose, in order
    if ollama_has_model "$m"; then
      say "  Model $m: present"
    else
      say "  Downloading $m$([ "$m" = "$OLLAMA_MODEL" ] && echo " (about $OLLAMA_DOWNLOAD_GB GB)")…"
      retry "download $m" "$(ollama_bin)" pull "$m" || {
        LAST_ERR="run 'ollama pull $m' to see the error"; return 1; }
    fi
  done
  step "point onex's local routes at Ollama" write_ollama_overrides "$OLLAMA_MODEL" || {
    LAST_ERR="$HOME/$OVERRIDES_FILE_REL was not written"; return 1; }
}

# accepted_backend JSON -> the backend id of the attempt whose answer was accepted
accepted_backend() {
  printf '%s' "$1" | jq -r '[.. | objects | select(.backend_id? != null and .acceptance_decision? == "accept") | .backend_id] | first // empty' 2>/dev/null
}

# The boot thresholds are an OR: either reading can stop the stack. The message
# and the remedy therefore name ONLY the clause that failed. Naming both reports
# a passing reading as a cause, which sends the developer after resources they
# already have -- a run stopped on 3 GB of memory once said "and 276 GB disk
# free (needs 15)" in the same breath.
BOOT_SHORT=""
BOOT_REMEDY=""
boot_resources_ok() { # 0 when the stack may boot; else BOOT_SHORT/BOOT_REMEDY say why
  local free disk
  free="$(avail_mem_gb)"; disk="$(disk_free_gb)"
  BOOT_SHORT=""; BOOT_REMEDY=""
  if [ "$free" -lt "$BOOT_FREE_MEM_GB" ]; then
    BOOT_SHORT="${free} GB memory available (needs $BOOT_FREE_MEM_GB)"
    BOOT_REMEDY="close other apps"
  fi
  if [ "$disk" -lt "$BOOT_FREE_DISK_GB" ]; then
    if [ -n "$BOOT_SHORT" ]; then
      BOOT_SHORT="$BOOT_SHORT and "; BOOT_REMEDY="$BOOT_REMEDY and "
    fi
    BOOT_SHORT="${BOOT_SHORT}${disk} GB disk free (needs $BOOT_FREE_DISK_GB)"
    BOOT_REMEDY="${BOOT_REMEDY}free disk space"
  fi
  [ -z "$BOOT_SHORT" ]
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

# Asked in preflight with the other questions, so the install in phase 4 never
# stops to ask. Docker Desktop's own window asks again later if this is no.
DOCKER_TERMS=""
ask_docker_terms() {
  local a=""
  say ""
  say "  Docker Desktop requires accepting the Docker Subscription Service Agreement:"
  say "    https://www.docker.com/legal/docker-subscription-service-agreement"
  if [ "$PROMPT_TTY" -eq 1 ]; then
    printf '  Accept it now? [y/N] (if not, Docker Desktop shows its terms when it starts) '
    IFS= read -r a || a=""
  fi
  case "$a" in y|Y|yes|YES) DOCKER_TERMS=y ;; *) DOCKER_TERMS=n ;; esac
}

accept_docker_terms() { # fresh install only, and only with the developer's yes from preflight
  # shellcheck disable=SC2024  # the log is the user's own file; only install needs root
  case "$DOCKER_TERMS" in
    y) sudo -n /Applications/Docker.app/Contents/MacOS/install --accept-license --user "$(id -un)" >>"$LOG" 2>&1 ;;
    *) say "  Docker's terms were not accepted in preflight; Docker Desktop will show them when it starts." ;;
  esac
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
  is_done 4 && rerun_note 4 "Docker is not running with a healthy local stack"

  local host_ram mem_gb mem
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

  if ! boot_resources_ok; then
    FAILED_STEP="resources at boot time"
    LAST_ERR="$BOOT_SHORT"
    phase_fail "$BOOT_REMEDY, then run this again"
  fi

  # Launching Docker restarts a stack that was already there (restart policies).
  local_stack_running && STACK_RUNNING=1
  if [ "$STACK_RUNNING" -eq 1 ]; then
    say "  The local stack is already there; checking it instead of rebuilding it."
  else
    step "make local-env" make -C "$WORKSPACE/omnibase_infra" local-env || phase_fail "see the log for make local-env's message"
    if in_list ollama "$(passed_models)"; then
      step "point the stack's local model at Ollama" point_bundle_model "http://host.docker.internal:$OLLAMA_PORT$OLLAMA_CHAT_PATH" "$OLLAMA_MODEL" ||
        phase_fail "set model_endpoint and served_model_id in ~/.omnibase/local.bifrost.yaml by hand, then run this again"
    elif in_list local "$(passed_models)"; then point_stack_at_local_url
    fi
  fi
  # The key path: the stack serves a tenant of its own and holds your keys for
  # it. Only keys that answered their test in phase 3 go to the stack.
  local keyed p
  keyed="$(for p in $(passed_models); do uses_key "$p" && printf '%s ' "$p"; done)"; keyed="${keyed% }"
  if [ -n "$keyed" ]; then
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
  if [ -n "$keyed" ]; then
    for p in $keyed; do
      step "register your $(provider_label "$p") key in the stack's own store" register_key_in_stack "$p" ||
        phase_fail "run 'make secret-local PROVIDER=$p' in omnibase_infra and paste the key, then run this again"
    done
    sleep 10   # the tenant credentials projection turns each registration into your route
  fi
  retry_capture "one delegation through the stack" stack_delegate ||
    phase_fail "the stack is up but the delegation failed; see the log"
  local served; served="$(accepted_backend "$CAPTURED")"; CAPTURED=""
  if [ -n "$keyed" ]; then
    # With a tenant, the stack answers only on that tenant's keys. A delegation
    # that falls through to another route still reports success, so the
    # accepted backend is what proves one of your keys was used.
    local ok=0
    for p in $keyed; do case "$served" in "byok-$p"*) ok=1 ;; esac; done
    if [ "$ok" -eq 1 ]; then say "  Answered by one of your keys ($served)."; else
      FAILED_STEP="check the delegation went to one of your keys"
      LAST_ERR="the answer came from ${served:-no backend}, not byok-<one of: $keyed>"
      phase_fail "the keys are registered but did not route; see 'make status-local' and the runtime logs"
    fi
  else
    case "$served" in
      local-*) say "  Answered by your local model ($served)." ;;
      *) FAILED_STEP="check the stack's delegation went to Ollama"
         LAST_ERR="the answer came from ${served:-no backend}, not a local route"
         phase_fail "check that your local model (Ollama, or the server at your URL) is running and ~/.omnibase/local.bifrost.yaml names it" ;;
    esac
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

# The customer plugin set is the public quickstart's: one plugin, one skill
# (/onex:delegate), from the customer marketplace entry. --developer installs the
# full onex tree (every /onex: skill and guard hook) and, with access, omni.
CUSTOMER_MARKETPLACE="OmniNode-ai/omniclaude"; WANT_PLUGIN=onex@omninode-tools; OTHER_PLUGIN=onex@omninode-tools-dev
[ "$DEVELOPER" -eq 1 ] && { WANT_PLUGIN=onex@omninode-tools-dev; OTHER_PLUGIN=onex@omninode-tools; }
phase5() {
  local claude p note="start a new Claude Code session to load them" want="$WANT_PLUGIN"
  phase_start 5 "Claude Code plugin ($want)" "1-2 minutes"
  is_done 5 && rerun_note 5 "the plugins are checked on every run; only what is missing is installed"
  if ! command -v claude >/dev/null 2>&1 && [ ! -x "$HOME/.local/bin/claude" ]; then
    say "  Installing Claude Code…"
    retry "install Claude Code" install_claude_code || phase_fail "install Claude Code from claude.com/claude-code, then run this again"
  fi
  claude="$(claude_bin)"
  if plugin_installed "$want"; then say "  $want: installed"
  elif [ "$DEVELOPER" -eq 1 ]; then
    # The full onex tree is a directory marketplace in the omniclaude clone, so it moves with that clone.
    "$claude" plugin marketplace list 2>/dev/null | grep -q 'omninode-tools-dev' ||
      step "add the onex dev marketplace from your omniclaude clone" \
        "$claude" plugin marketplace add "$WORKSPACE/omniclaude/plugins/"*-dev-marketplace ||
      phase_fail "could not add the onex dev marketplace from your omniclaude clone; check the log for the error"
    step "install $want" "$claude" plugin install "$want" || phase_fail "run 'claude plugin install $want' to see the error"
  else
    "$claude" plugin marketplace list 2>/dev/null | grep -Eq 'omninode-tools($|[^-])' ||
      retry "add the $CUSTOMER_MARKETPLACE marketplace" "$claude" plugin marketplace add "$CUSTOMER_MARKETPLACE" ||
      phase_fail "run 'claude plugin marketplace add $CUSTOMER_MARKETPLACE' to see the error"
    retry "install $want" "$claude" plugin install "$want" || phase_fail "run 'claude plugin install $want' to see the error"
  fi
  plugin_installed "$OTHER_PLUGIN" && say "  ⚠ $OTHER_PLUGIN is also installed; remove it with 'claude plugin uninstall $OTHER_PLUGIN' so each /onex: skill appears once."
  if [ "$DEVELOPER" -eq 0 ]; then
    note="$note; the developer plugins (the full onex tree, omni) are installed only with --developer"
  elif internal_plugins_reachable; then
    "$claude" plugin marketplace list 2>/dev/null | grep -q 'omninode-internal' ||
      retry "add the omniclaude-internal marketplace" "$claude" plugin marketplace add OmniNode-ai/omniclaude-internal ||
      phase_fail "run 'claude plugin marketplace add OmniNode-ai/omniclaude-internal' to see the error"
    for p in omni onex-overlays; do
      plugin_installed "$p@omninode-internal" && { say "  $p@omninode-internal: installed"; continue; }
      retry "install $p@omninode-internal" "$claude" plugin install "$p@omninode-internal" ||
        phase_fail "run 'claude plugin install $p@omninode-internal' to see the error"
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

# The workspace floor the onex wrapper enforces before any --lane command. Phase 3
# stamped it after its own delegation passed. This asks the wrapper itself, the way
# a developer's own `onex delegate` will, and never reconciles: a reconcile here
# would move the clones and the dispatch venv to dev head and restamp the floor
# with commits no run has passed on.
workspace_floor() {
  local out line
  out="$(cd "$HOME" && onex_run delegate --json "Reply with exactly one word: hello" 2>&1)" ||
    { printf '%s\n' "$out"; return 1; }
  line="$(printf '%s\n' "$out" | grep -E '^\{' | tail -n 1)"
  [ "$(receipt_field "$line" status)" = "success" ] || { printf '%s\n' "$out"; return 1; }
}

phase6() {
  phase_start 6 "Verify" "about a minute"
  [ -n "$ONEX" ] || ONEX="$HOME/.local/bin/onex"
  check "onex starts ($(onex_run --version 2>/dev/null | tail -n 1))" onex_run --version
  check "local identity minted" onex_run local identity
  check "onex is the workspace wrapper, not a PyPI copy" no_shadow
  check "a new terminal runs the workspace onex (no alias, function or other install)" shell_runs_workspace_onex
  check "workspace floor proven (the onex wrapper delegates)" retry "delegate through the workspace wrapper" workspace_floor
  check "a delegation row in the local store" sqlite_rows
  check "onex metering reads it" onex_run metering
  if in_list ollama "$(passed_models)"; then
    check "Ollama answers on this Mac" ollama_up
    check "Ollama has $OLLAMA_MODEL" ollama_has_model "$OLLAMA_MODEL"
  fi
  in_list local "$(passed_models)" && check "the local model server answers at $LOCAL_URL" local_url_answers "$LOCAL_URL"
  check "the Claude Code plugin $WANT_PLUGIN installed" plugin_installed "$WANT_PLUGIN"
  if [ "$MODE2_OK" -eq 1 ]; then check "local stack healthy" stack_healthy; fi
  if [ "$CHECKS_FAILED" -gt 0 ]; then
    FAILED_STEP="$CHECKS_FAILED check(s) failed"
    phase_fail "the ✘ lines above name what is wrong; fix them and run this again"
  fi
  phase_pass
}

# ===========================================================================
main() {
  local p line
  say "OmniNode developer onboarding (local runtime). Status file: $STATUS"
  [ "$RESTART" -eq 1 ] && rm -f "$DONE_FILE"
  bind_workspace_env
  phase0
  [ "$PREFLIGHT_ONLY" -eq 1 ] && { say "Preflight only: nothing was changed."; exit 0; }
  save_choices
  phase1
  phase2
  phase3
  phase4
  phase5
  phase6
  hr
  say "Done. Set up: $SELECTED."
  say "Your models:"
  for p in $MODELS $SKIPPED; do result_line "$p" | while IFS= read -r line; do say "  $line"; done; done
  say "$(count_words "$(passed_models)") of $(count_words "$MODELS $SKIPPED") models ready. Delegation chooses among them for each task."
  say "Add or fix one any time: onex models add <gemini|openrouter|openai|local>; see them all: onex models list"
  say "Next:"
  say "  1. Open a new terminal (or run 'exec zsh') so OMNIBASE_PATH and PATH take effect."
  say "  2. Open Claude Code (run 'claude') and sign in with your Anthropic account the first"
  say "     time it asks. /onex:delegate is installed$([ "$DEVELOPER" -eq 1 ] && echo ', with every other onex skill')."
  notify "Onboarding complete" "Every phase passed"
  printf 'result=COMPLETE\n' >>"$STATUS"
}

main
