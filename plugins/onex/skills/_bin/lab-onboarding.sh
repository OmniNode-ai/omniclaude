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
#   2 Workspace          the canonical clones, OMNIBASE_PATH, PATH
#   3 onex + models      dispatch venv, onex, local identity, then each model you chose set up
#                        with `onex models add` and tested with one delegation pinned to it
#   4 Docker             optional: only if you said yes; Docker Desktop installed, or started
#                        if stopped, then the local stack on your keys
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
#   --provider LIST      one or more of gemini, openrouter, openai, ollama, comma-separated
#                        (default: asked up front). Gemini, OpenRouter and OpenAI take your
#                        own key, asked for one at a time; Ollama runs a model on this Mac,
#                        no key. Delegation chooses among the ones set up
#   --ollama-model NAME  the model Ollama downloads (default: chosen from this Mac's memory)
#   --workspace DIR      the workspace (default: $OMNIBASE_PATH, else ~/Code/omnibase). A directory
#                        that already holds clones this setup did not create is refused
#   --set-aside          answer yes in advance to setting aside what an earlier setup left
#                        (an onex alias, old variables in your profile, a published onex,
#                        a local-model routes file, clones holding work); each is moved or
#                        commented out, never deleted
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
    OMNI_HOME|OMNIBASE_*|ONEX_*|BIFROST_*|KAFKA_*|DELEGATION_ROUTING_TIERS_PATH|POSTGRES_PASSWORD|VALKEY_PASSWORD|PYTHONPATH)
      INHERITED_ENV="${INHERITED_ENV}${INHERITED_ENV:+ }$_v"; unset "$_v" ;;
  esac
done
unset OMNI_HOME
RESTART=0
SET_ASIDE_FLAG=0
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
    --workspace) shift; WORKSPACE="${1:-}"; WORKSPACE_FROM="from --workspace" ;;
    --workspace=*) WORKSPACE="${1#*=}"; WORKSPACE_FROM="from --workspace" ;;
    --restart) RESTART=1 ;;
    --set-aside) SET_ASIDE_FLAG=1 ;;
    -h|--help) usage; exit 0 ;;
    *) printf 'omninode-dev-setup: unknown option: %s (see --help)\n' "$1" >&2; exit 2 ;;
  esac
  shift
done
for _p in $(printf '%s' "$PROVIDER" | tr ',' ' '); do
  case "$_p" in openrouter|gemini|openai|ollama) ;; *)
    printf 'omninode-dev-setup: --provider must be gemini, openrouter, openai or ollama (or a comma-separated list of them)\n' >&2; exit 2 ;;
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

# A resumed run (after a failure, or with a freshly downloaded script: the record
# lives under $HOME, not beside the script) checks completed phases rather than
# redoing them, and keeps the last run's answers so it asks one question, not all.
CHOICES_FILE="$STATE_DIR/choices"
RESUMING=0
saved_choice() { [ "$RESTART" -eq 0 ] && sed -n "s/^$1=//p" "$CHOICES_FILE" 2>/dev/null | tail -n 1; }
save_choices() {
  mkdir -p "$STATE_DIR" && printf 'models=%s\ncontainers=%s\n' "$MODELS" "$MODE2_OK" >"$CHOICES_FILE"
}
resume_banner() {
  local n done_list="" next=""
  [ "$RESTART" -eq 0 ] && [ -s "$DONE_FILE" ] || return 0
  for n in 1 2 3 4 5 6; do
    if grep -qx "$n" "$DONE_FILE" 2>/dev/null; then done_list="${done_list}${done_list:+, }$n"
    elif [ -z "$next" ]; then next="$n"; fi
  done
  [ -n "$done_list" ] || return 0
  RESUMING=1
  say "  Resuming an earlier run: phase(s) $done_list passed then; each is checked, not redone,"
  if [ -n "$next" ]; then say "  so this run picks up at phase $next. (--restart runs every phase again.)"
  else say "  and every phase passed, so this run only checks them. (--restart runs every phase again.)"; fi
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

# ---------------------------------------------------------------------------
# In a VM: said once, before any question, so no choice is made without knowing.
vm_notice() {
  say ""
  say "  We detected that this Mac is a virtual machine."
  say "  Docker can't run inside a macOS VM, so the local stack isn't offered here."
  say "  Everything else works. A model on this Mac (Ollama) will be slow in a VM;"
  say "  a key (Gemini, OpenRouter or OpenAI) is the better choice."
}

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
# Your models: any combination of Gemini, OpenRouter, OpenAI and Ollama, at
# least one. Delegation chooses among them for each task; the developer never
# picks one per run. Settled in preflight, before anything installs, so the run
# never stops mid-way to ask. Each key is held only in this process (never
# exported, logged or written) until phase 3 hands it to `onex models add` on
# stdin.
# ---------------------------------------------------------------------------
ALL_MODELS="gemini openrouter openai ollama"
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
    ollama) echo "Ollama" ;;
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

# OpenRouter: every OpenRouter key runs the default model the onex overlay
# declares, so onboarding asks no model question and the developer never needs a
# model id. This script names no model: `onex models default-model openrouter`
# reads it from the node_model_setup_effect overlay (setup_model, phase 3). The
# model may be a paid one, so the key needs credit on openrouter.ai. Another
# model is one command later:
# onex models add openrouter --model <id>

stored_key_providers() { # every provider an earlier run already stored a key for, one per line
  [ -x "$HOME/.local/bin/onex" ] || return 1
  local p list found=1
  list="$(env -u PYTHONPATH "$HOME/.local/bin/onex" secret list 2>/dev/null)" || return 1
  for p in gemini openrouter openai; do
    printf '%s\n' "$list" | grep -qE "^[[:space:]]+llm\.$p\.api_key[[:space:]]" && { echo "$p"; found=0; }
  done
  return "$found"
}

# "1,3,4", "1 3 4", "134" and "4,1,3" all choose the same models; repeats are
# ignored. Sets MODELS in menu order; 1 when the answer chooses nothing valid.
parse_model_choice() {
  local a p i=0 picked=""
  a="$(printf '%s' "$1" | tr -d ', ')"
  [ -n "$a" ] || return 1
  case "$a" in *[!1-4]*) return 1 ;; esac
  for p in $ALL_MODELS; do
    i=$((i + 1))
    case "$a" in *"$i"*) picked="$picked $p" ;; esac
  done
  MODELS="${picked# }"
}

ask_models() { # -> MODELS
  local a p i=0 note
  say ""
  say "  Your models"
  say ""
  say "  Choose one or more. Delegation picks among them for each task."
  say ""
  for p in $ALL_MODELS; do
    i=$((i + 1)); note=""
    is_stored "$p" && note="  (key stored)"
    [ "$p" = "ollama" ] && ollama_overrides_ours && note="  (set up)"
    case "$p" in
      gemini)     say "    $i) Gemini      your key, from aistudio.google.com/apikey$note" ;;
      openrouter) say "    $i) OpenRouter  your key, from openrouter.ai/keys (its free models need no credit)$note" ;;
      openai)     say "    $i) OpenAI      your key, from platform.openai.com/api-keys (needs credits)$note" ;;
      ollama)     say "    $i) Ollama      on this Mac, no key. Slower, especially on Intel; it downloads"
                  say "                   a model sized to this Mac$note" ;;
    esac
  done
  say ""
  say "    q) quit setup (nothing has been installed yet)"
  while :; do
    say ""
    printf '  Choose one or more, e.g. 1,3,4: '
    IFS= read -r a || quit_setup
    case "$a" in q|Q|quit|QUIT) quit_setup ;; esac
    parse_model_choice "$a" && break
    say "  Choose at least one, 1 to 4 (for example 1,3), or q to quit."
  done
  say ""
  say "  You chose: $(labels "$MODELS")"
}

# One hidden prompt per chosen model that takes a key, in menu order, each
# naming its provider and "n of m". A key already entered in this run is kept,
# so changing the choice at the summary never asks for it again.
ask_keys() {
  local keyed p n=0 total label value looks a
  keyed="$(keyed_models)"
  total="$(count_words "$keyed")"
  [ "$total" -gt 0 ] || return 0
  say ""
  say "  Your keys stay on this Mac, in onex's key store. They are never shown or logged,"
  say "  and each is only ever sent to its own provider."
  for p in $keyed; do
    n=$((n + 1)); label="$(provider_label "$p")"
    if [ -n "$(pending_key "$p")" ]; then
      say "  $label key ($n of $total): already entered."
      continue
    fi
    while :; do
      say ""
      if is_stored "$p" && [ "$RESUMING" -eq 1 ]; then
        say "  $label key ($n of $total): stored by your last run; kept."
        break
      elif is_stored "$p"; then
        read_secret "  $label key ($n of $total) — stored; press Enter to keep it, or paste a new one (input is hidden):"
        if [ -z "$SECRET" ]; then say "  Keeping your stored $label key."; break; fi
      else
        read_secret "  $label key ($n of $total) — paste it from $(key_page "$p") (input is hidden):"
      fi
      value="$SECRET"; SECRET=""
      if [ -z "$value" ]; then
        printf '  No key entered. Skip %s for now? [Y = skip, n = try again] ' "$label"
        IFS= read -r a || quit_setup
        case "$a" in n|N|no|NO) continue ;; esac
        drop_model "$p"; SKIPPED="${SKIPPED:+$SKIPPED }$p"
        say "  Skipped $label. Add it any time: onex models add $p"
        break
      fi
      looks="$(key_looks_like "$value")"
      if [ -n "$looks" ] && [ "$looks" != "$p" ]; then
        value=""
        say "  ✗ That looks like $(a_an "$(provider_label "$looks")") $(provider_label "$looks") key, not $(a_an "$label") $label key."
        continue
      fi
      set_pending_key "$p" "$value"; value=""
      say "  $label key received."
      [ "$p" = "openrouter" ] && say "  OpenRouter model: the default the onex overlay declares (change it any time: onex models add openrouter --model <model id>)"
      break
    done
  done
}

confirm_models() { # 0 continue, 1 change the choice; q quits
  local p a
  say ""
  say "  Ready to set up:"
  for p in $MODELS; do
    if [ "$p" = "ollama" ]; then
      if ollama_overrides_ours; then say "    Ollama      already set up on this Mac"
      else say "    Ollama      no key; downloads a model sized to this Mac's $(ram_gb) GB of memory"; fi
    elif [ "$p" = "openrouter" ] && [ -n "$(pending_key "$p")" ]; then
      say "    $(printf '%-11s' "$(provider_label "$p")") key received, default model from the overlay"
    elif [ -n "$(pending_key "$p")" ]; then
      say "    $(printf '%-11s' "$(provider_label "$p")") key received"
    else
      say "    $(printf '%-11s' "$(provider_label "$p")") your stored key"
    fi
  done
  for p in $SKIPPED; do say "    $(result_line "$p")"; done
  say ""
  printf '  Continue? [Y = yes, c = change, q = quit] '
  IFS= read -r a || quit_setup
  case "$a" in
    c|C|change|CHANGE) return 1 ;;
    q|Q|quit|QUIT) quit_setup ;;
  esac
  return 0
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

settle_models() {
  STORED="$(stored_key_providers 2>/dev/null | tr '\n' ' ')"; STORED="${STORED% }"
  local models_from="--provider"
  [ -z "$PROVIDER" ] || MODELS="$(in_menu_order "$(printf '%s' "$PROVIDER" | tr ',' ' ')")"
  if [ -z "$MODELS" ] && [ "$RESUMING" -eq 1 ]; then
    MODELS="$(in_menu_order "$(saved_choice models)")"; models_from="your last run"
  fi
  if [ "$PROMPT_TTY" -eq 0 ]; then settle_models_unattended; else
    local asked_by_flag=0
    [ -n "$MODELS" ] && asked_by_flag=1
    while :; do
      if [ "$asked_by_flag" -eq 1 ]; then
        asked_by_flag=0
        say ""
        say "  Your models (from $models_from): $(labels "$MODELS")"
      else
        ask_models
      fi
      SKIPPED=""; set_result openrouter ""
      ask_keys
      if [ -z "$MODELS" ]; then
        say ""
        say "  Every model was skipped. Choose at least one."
        continue
      fi
      confirm_models && break
    done
    # Keys for models dropped at the summary are forgotten here.
    local p
    for p in gemini openrouter openai; do has_model "$p" || set_pending_key "$p" ""; done
  fi
  if has_model ollama; then settle_ollama; fi
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

# ===========================================================================
# What an earlier setup left on this Mac. Preflight runs the
# existing install the way the developer's own shell does, before anything
# installs, and reports one table: the onex the shell runs and its version,
# other onex installs, variables and profile lines, a local-model routes file
# and the workspace's clones. Whatever would interfere is set aside only with the
# developer's yes: moved or commented out, never deleted, each listed with how to
# put it back. The run itself never inherits the variables (see INHERITED_ENV).
# ===========================================================================
LEFTOVERS=""        # one record per line: interferes<TAB>kind<TAB>key<TAB>found<TAB>effect
SET_ASIDE=""        # 1 once the developer said yes (or passed --set-aside)
[ "$SET_ASIDE_FLAG" -eq 1 ] && SET_ASIDE=1
SET_ASIDE_LOG=""
TAB="$(printf '\t')"
PROFILE_FILES=".zshrc .zprofile .zshenv .zlogin .bash_profile .bashrc .profile .aliases .zsh_aliases .bash_aliases"
# A set-aside profile line becomes `: # [set aside ...] <the line>`: the `:` keeps
# an if/then or a loop whose only line it was valid in bash, which refuses an
# empty body where a bare comment would leave one.
SET_ASIDE_MARK=": # [set aside by omninode-dev-setup"
SHELL_ONEX_ELSEWHERE=0   # 1: an onex alias or function is defined in no file this setup reads

leftover() { # interferes kind key found effect
  LEFTOVERS="${LEFTOVERS}$1${TAB}$2${TAB}$3${TAB}$4${TAB}$5
"
}
leftovers_interfering() { printf '%s' "$LEFTOVERS" | grep -c "^1${TAB}" | tr -d ' '; }

user_shell() {
  case "${SHELL:-}" in
    */zsh) echo zsh ;;
    */bash) echo bash ;;
    *) if command -v zsh >/dev/null 2>&1; then echo zsh; else echo bash; fi ;;
  esac
}

# in_user_shell SECONDS COMMAND -> its stdout, run by a new interactive shell of
# the developer's kind, so their profile, aliases and functions apply exactly as
# in their own terminal. Bounded: an old alias may start a long environment sync.
in_user_shell() {
  local t="$1"; shift
  [ "${ONBOARD_TEST_NO_USER_SHELL:-0}" = "1" ] && return 1
  command -v "$(user_shell)" >/dev/null 2>&1 || return 1
  perl -e 'alarm shift; exec @ARGV' "$t" "$(user_shell)" -ic "$*" </dev/null 2>/dev/null
}

# What `onex` is to the developer's shell: alias, function, or the file it runs.
shell_onex_kind() {
  case "$(user_shell)" in
    zsh) in_user_shell 15 'whence -w onex' | sed -n 's/^onex: //p' | head -n 1 ;;
    *) in_user_shell 15 'type -t onex' | head -n 1 ;;
  esac
}
shell_onex_path() {
  case "$(user_shell)" in
    zsh) in_user_shell 15 'whence -p onex' | head -n 1 ;;
    *) in_user_shell 15 'type -P onex' | head -n 1 ;;
  esac
}
shell_onex_version() { # what `onex --version` prints in a new terminal, errors included
  local v
  v="$(in_user_shell 30 'onex --version 2>&1' | grep -v '^[[:space:]]*$' | tail -n 1 | cut -c1-70)"
  printf '%s' "${v:-nothing within 30 seconds}"
}
tilde() { case "$1" in "$HOME"/*) printf '%s/%s' '~' "${1#"$HOME"/}" ;; *) printf '%s' "$1" ;; esac; }
real_path() { # path -> the file it finally names, through every symlink
  local p="$1" l
  while [ -L "$p" ]; do
    l="$(readlink "$p")"
    case "$l" in /*) p="$l" ;; *) p="$(dirname "$p")/$l" ;; esac
  done
  printf '%s' "$p"
}
is_workspace_onex() { [ "$(real_path "$1")" = "$WORKSPACE/omnibase_infra/scripts/onex" ]; }
masked() { printf '%s' "$1" | sed -e 's/^[[:space:]]*//' -e 's/=.*$/=…/' | cut -c1-70; }

# Profile lines outside this setup's own block that redirect onex in the
# developer's shells: a variable an earlier setup exported, an onex alias or
# function, or sourcing the operator env file.
profile_leftover_lines() { # file -> "lineno<TAB>text" for each
  awk -v b="$PROFILE_BEGIN" -v e="$PROFILE_END" -v mark="$SET_ASIDE_MARK" '
    $0 == b { inblock = 1 } $0 == e { inblock = 0; next }
    inblock || index($0, mark) == 1 || $0 ~ /^[[:space:]]*#/ { next }
    $0 ~ /^[[:space:]]*(export[[:space:]]+)?(OMNI_HOME|OMNIBASE_[A-Z_]+|ONEX_[A-Z_]+|BIFROST_[A-Z_]+|KAFKA_[A-Z_]+|DELEGATION_ROUTING_TIERS_PATH|POSTGRES_PASSWORD|VALKEY_PASSWORD)=/ ||
    $0 ~ /^[[:space:]]*alias[[:space:]]+onex=/ ||
    $0 ~ /^[[:space:]]*(function[[:space:]]+onex([[:space:]]|\(|$)|onex[[:space:]]*\(\))/ ||
    $0 ~ /^[[:space:]]*(source|\.)[[:space:]]+.*\.omnibase\/\.env/ { printf "%d\t%s\n", NR, $0 }
  ' "$1" 2>/dev/null
}

uv_tool_dir() { printf '%s' "${UV_TOOL_DIR:-${XDG_DATA_HOME:-$HOME/.local/share}/uv/tools}"; }
pipx_home() { # pipx's home when one exists; empty when pipx has never installed here
  local d
  for d in "${PIPX_HOME:-}" "$HOME/.local/pipx" "${XDG_DATA_HOME:-$HOME/.local/share}/pipx" \
    "$HOME/Library/Application Support/pipx"; do
    [ -n "$d" ] && [ -d "$d/venvs" ] && { printf '%s' "$d"; return 0; }
  done
}

survey_leftovers() {
  local f n text kind path version first="" d r state problem uvb names
  LEFTOVERS=""

  # 1. onex as the developer's shell runs it, and what it answers.
  kind="$(shell_onex_kind)"
  case "$kind" in
    alias|function)
      version="$(shell_onex_version)"
      leftover 1 shell onex "onex is a shell $kind (onex --version: $version)" \
        "shadows the onex this setup installs, in every terminal" ;;
    command|file)
      path="$(shell_onex_path)"
      if [ -n "$path" ] && ! is_workspace_onex "$path"; then
        version="$(shell_onex_version)"
        leftover 0 shell "$path" "your shell runs $(tilde "$path") (onex --version: $version)" \
          "replaced by the workspace onex (see the rows below)"
      fi ;;
  esac

  # 2. Every onex on PATH. ~/.local/bin/onex is replaced in phase 3 (kept as a
  # .pre-onboarding copy); one earlier on PATH than ~/.local/bin shadows it.
  local seen_local=0 ipath
  ipath="$(in_user_shell 15 'printf "%s" "$PATH"')"
  [ -n "$ipath" ] || ipath="$PATH"
  while IFS= read -r d; do
    [ -n "$d" ] || continue
    [ "$d" = "$HOME/.local/bin" ] && seen_local=1
    [ -x "$d/onex" ] && ! is_workspace_onex "$d/onex" || continue
    case " $first " in *" $d/onex "*) continue ;; esac
    first="$first $d/onex"
    if [ "$d" = "$HOME/.local/bin" ]; then
      leftover 0 bin "$d/onex" "$(tilde "$d/onex") (not the workspace onex)" "replaced in phase 3; the old one is kept beside it"
    elif [ "$seen_local" -eq 0 ]; then
      leftover 1 bin "$d/onex" "$(tilde "$d/onex"), ahead of ~/.local/bin on PATH" "shadows the onex this setup installs"
    fi
  done <<EOF
$(printf '%s' "$ipath" | tr ':' '\n')
EOF

  # 3. Tool installs of the packages that carry onex. Each tool is asked only
  # when its tool directory exists: a first `pipx list` creates its own
  # directories under $HOME, and preflight writes nothing there.
  uvb="$(uv_bin)"
  if [ -n "$uvb" ] && [ -d "$(uv_tool_dir)" ]; then
    names="$("$uvb" tool list 2>/dev/null | grep -E '^(omnibase-core|omnimarket|omnibase-infra) ' | cut -d' ' -f1,2)"
    while IFS= read -r n; do
      [ -n "$n" ] || continue
      leftover 1 uvtool "${n%% *}" "$n, installed as a uv tool" "a published onex that outranks the workspace one"
    done <<EOF
$names
EOF
  fi
  if command -v pipx >/dev/null 2>&1 && [ -n "$(pipx_home)" ]; then
    while IFS= read -r n; do
      [ -n "$n" ] || continue
      leftover 1 pipx "${n%% *}" "$n, installed with pipx" "a published onex that outranks the workspace one"
    done <<EOF
$(pipx list --short 2>/dev/null | grep -E '^(omnibase-core|omnimarket|omnibase-infra) ')
EOF
  fi

  # 4. Variables this shell exported (this run ignores them) and the profile
  # lines that set them.
  [ -n "$INHERITED_ENV" ] && leftover 0 env environment "exported in this terminal: $INHERITED_ENV" \
    "ignored by this run; your profile lines below set them in new terminals"
  local onex_defined=0
  for f in $PROFILE_FILES; do
    [ -f "$HOME/$f" ] || continue
    while IFS="$TAB" read -r n text; do
      [ -n "$n" ] || continue
      case "$text" in *"alias onex="*|*"onex()"*|*"onex ()"*|*"function onex"*) onex_defined=1 ;; esac
      leftover 1 profile "$HOME/$f:$n" "$(tilde "$HOME/$f") line $n: $(masked "$text")" "redirects onex in every new terminal"
    done <<EOF
$(profile_leftover_lines "$HOME/$f")
EOF
  done

  SHELL_ONEX_ELSEWHERE=0
  case "$kind" in
    alias|function)
      if [ "$onex_defined" -eq 0 ]; then
        SHELL_ONEX_ELSEWHERE=1
        leftover 1 shell elsewhere "the onex $kind is defined in a file this setup does not read" \
          "remove it there by hand ('$(user_shell) -ic \"type onex\"' names it), then run this again"
      fi ;;
  esac

  # 5. A local-model routes file this setup did not write: routing takes a
  # declared local model before a key, so every key's test would go to it.
  f="$HOME/$OVERRIDES_FILE_REL"
  if [ -f "$f" ]; then
    if head -n 1 "$f" | grep -qE '^# Written by (lab-onboarding|omninode-dev-setup)'; then
      ollama_overrides_ours || leftover 0 routes "$f" "$(tilde "$f") from an earlier run" "moved aside in phase 3 unless you choose Ollama"
    else
      leftover 1 routes "$f" "$(tilde "$f") (not written by this setup)" "sends your keys' delegations to a local model"
    fi
  fi

  # 6. The workspace's clones, as last fetched (phase 2 fetches).
  if [ -d "$WORKSPACE" ]; then
    for r in $REPOS; do
      state="$(clone_state "$r")"
      [ "$state" = missing ] && continue
      problem="$(clone_problem "$r" "$state")"
      if [ -n "$problem" ]; then
        leftover 1 clone "$r" "$(tilde "$WORKSPACE/$r"): $problem" "holds work phase 2 will not move"
      else
        local where behind def
        IFS='|' read -r where _ behind _ def <<EOF
$state
EOF
        [ "${behind:-0}" -gt 0 ] || [ "$where" != "$def" ] || continue
        leftover 0 clone "$r" "$(tilde "$WORKSPACE/$r"): $(clone_where "$where"), $behind commit(s) behind origin/$def" \
          "brought up to date in phase 2"
      fi
    done
  fi
}

report_leftovers() {
  [ -n "$LEFTOVERS" ] || return 0
  local interferes kind key found effect
  say ""
  say "  What an earlier setup left on this Mac"
  say ""
  while IFS="$TAB" read -r interferes kind key found effect; do
    [ -n "$kind" ] || continue
    if [ "$interferes" = 1 ]; then say "  ✗ $found"; else say "  · $found"; fi
    say "      $effect"
  done <<EOF
$LEFTOVERS
EOF
}

# Asked once, before anything installs. With no terminal, --set-aside answers it.
settle_leftovers() {
  local count a
  count="$(leftovers_interfering)"
  [ "$count" -gt 0 ] || return 0
  if [ "$PREFLIGHT_ONLY" -eq 1 ]; then
    say ""
    say "  $count of these (✗) would interfere. A full run asks whether to set them aside."
    return 0
  fi
  if [ "$SHELL_ONEX_ELSEWHERE" -eq 1 ]; then
    FAILED_STEP="find the onex alias or function"
    LAST_ERR="onex is a shell alias or function defined outside the files this setup reads"
    phase_fail "remove it by hand ('$(user_shell) -ic \"type onex\"' names where it is), then run this again. Nothing was installed or changed"
  fi
  if [ "$SET_ASIDE" != 1 ]; then
    if [ "$PROMPT_TTY" -eq 0 ]; then
      FAILED_STEP="set aside what an earlier setup left"
      LAST_ERR="$count item(s) above would interfere, and there is no terminal to ask on"
      phase_fail "run this in Terminal to choose, or pass --set-aside. Nothing was installed or changed"
    fi
    say ""
    say "  The $count marked ✗ would interfere with this setup. Setting one aside moves it or"
    say "  comments it out; nothing is deleted, and each is listed with how to put it back."
    printf '  Set them aside now? [Y = set aside, q = stop here; nothing has been installed] '
    IFS= read -r a || quit_setup
    case "$a" in q|Q|quit|QUIT|n|N|no|NO) quit_setup ;; esac
    SET_ASIDE=1
  fi
}

# profile_comment_out file "lines" -> stdout: the file with each listed line
# (and, for a multi-line onex function, its whole body, by brace depth) behind
# the set-aside marker. Nothing is written.
profile_comment_out() {
  awk -v lines=" $2 " -v mark="$SET_ASIDE_MARK $STAMP] " '
    function braces(t,  o, c) { o = gsub(/\{/, "{", t); c = gsub(/\}/, "}", t); return o - c }
    index(lines, " " NR " ") {
      if (!depth && $0 ~ /^[[:space:]]*(function[[:space:]]+onex|onex[[:space:]]*\(\))/) depth = braces($0)
      if (depth < 0) depth = 0
      print mark $0; next }
    depth > 0 { depth += braces($0); print mark $0; if (depth <= 0) depth = 0; next }
    { print }
  ' "$1"
}

# profile_syntax_ok file -> 0 when the shell that reads it parses it
profile_syntax_ok() {
  local sh=bash
  case "$(basename "$1")" in .z*) sh=zsh ;; esac
  command -v "$sh" >/dev/null 2>&1 || return 0
  "$sh" -n "$1" >/dev/null 2>&1
}

# Every profile edit is made in a copy and parsed before any file is touched,
# so a run that cannot set a line aside safely stops with nothing changed.
PROFILE_EDITS=""   # one "file<TAB>edited copy" per line
prepare_profile_edits() {
  local interferes kind key found effect f lines tmp
  PROFILE_EDITS=""
  for f in $(printf '%s' "$LEFTOVERS" | awk -F "$TAB" '$1 == 1 && $2 == "profile" { sub(/:[0-9]+$/, "", $3); print $3 }' | sort -u); do
    lines="$(printf '%s' "$LEFTOVERS" | awk -F "$TAB" -v f="$f" '$1 == 1 && $2 == "profile" { n = $3; sub(/.*:/, "", n); k = $3; sub(/:[0-9]+$/, "", k); if (k == f) print n }' | tr '\n' ' ')"
    tmp="$(mktemp "$RUN_DIR/profile.XXXXXX")" || return 1
    profile_comment_out "$f" "$lines" >"$tmp" || return 1
    if profile_syntax_ok "$f" && ! profile_syntax_ok "$tmp"; then
      rm -f "$tmp"
      FAILED_STEP="set aside lines in $f"
      LAST_ERR="commenting them out would leave $(tilde "$f") unreadable by its shell"
      return 1
    fi
    PROFILE_EDITS="${PROFILE_EDITS}$f${TAB}$tmp
"
  done
}

# profile_set_aside file: write the checked copy over the file, the original
# copied beside it first. The copy and the marker are how it is put back.
profile_set_aside() {
  local f="$1" tmp
  tmp="$(printf '%s' "$PROFILE_EDITS" | awk -F "$TAB" -v f="$f" '$1 == f { print $2 }')"
  [ -f "$tmp" ] || return 0   # this file's lines were already written
  [ -f "$f.pre-onboarding.$STAMP" ] || cp -p "$f" "$f.pre-onboarding.$STAMP" || return 1
  cat "$tmp" >"$f" && rm -f "$tmp"
}

set_aside_one() { # kind key -> moves or comments out one item; prints where it went
  local kind="$1" key="$2" dest
  case "$kind" in
    profile)
      profile_set_aside "${key%:*}" || return 1
      echo "commented out (copy of the file: ${key%:*}.pre-onboarding.$STAMP; to restore, delete the '$SET_ASIDE_MARK $STAMP] ' prefix)" ;;
    bin|routes)
      dest="$key.pre-onboarding.$STAMP"
      mv "$key" "$dest" || return 1
      echo "moved to $dest (move it back to restore)" ;;
    clone)
      mkdir -p "$WORKSPACE/.set-aside" || return 1
      dest="$WORKSPACE/.set-aside/$key.$STAMP"
      mv "$WORKSPACE/$key" "$dest" || return 1
      echo "moved to $dest (phase 2 clones it fresh; your work is there)" ;;
    uvtool)
      "$(uv_bin)" tool uninstall "$key" >>"$LOG" 2>&1 || return 1
      echo "uninstalled with 'uv tool uninstall $key' (install it again the way you did before)" ;;
    pipx)
      pipx uninstall "$key" >>"$LOG" 2>&1 || return 1
      echo "uninstalled with 'pipx uninstall $key' (install it again the way you did before)" ;;
    *) echo "nothing to move" ;;
  esac
}

set_aside_leftovers() {
  [ "$SET_ASIDE" = 1 ] || return 0
  [ "$(leftovers_interfering)" -gt 0 ] || return 0
  local interferes kind key found effect where failed=""
  mkdir -p "$STATE_DIR" || return 1
  SET_ASIDE_LOG="$STATE_DIR/set-aside.$STAMP.txt"
  prepare_profile_edits ||
    phase_fail "set those lines aside by hand (the table above names each), then run this again. Nothing was installed or changed"
  say ""
  say "  Setting aside what would interfere (listed in $SET_ASIDE_LOG):"
  # The shell's own view is checked last, once the profile lines are out of the way.
  while IFS="$TAB" read -r interferes kind key found effect; do
    [ "$interferes" = 1 ] && [ "$kind" != shell ] || continue
    if where="$(set_aside_one "$kind" "$key")"; then
      say "    ✓ $found: $where"
      printf '%s\t%s\n' "$found" "$where" >>"$SET_ASIDE_LOG"
    else
      say "    ✗ $found: could not be set aside (see the log)"
      failed="$failed; $found"
    fi
  done <<EOF
$LEFTOVERS
EOF
  case "$(shell_onex_kind)" in
    alias|function)
      say "    ✗ onex is still a shell $(shell_onex_kind) in a new terminal: it is defined in a file this"
      say "      setup does not read. '$(user_shell) -ic \"type onex\"' names it; remove it there."
      failed="$failed; the onex shell $(shell_onex_kind)" ;;
  esac
  if [ -n "$failed" ]; then
    FAILED_STEP="set aside what an earlier setup left"; LAST_ERR="${failed#; }"
    phase_fail "set those aside by hand (the lines above say what each is), then run this again. Nothing was installed"
  fi
  say "  This terminal still has the old settings loaded; the run ignores them, and new"
  say "  terminals will not have them."
}

# ===========================================================================
# Phase 0: preflight. Reads only, until you agree to set leftovers aside.
# ===========================================================================
MODE1_OK=1
MODE2_OK=1
MODE2_WHY=""
MODE1_WHY=""

row() { printf '  %-22s %-16s %-14s %s\n' "$1" "$2" "$3" "$4" | tee -a "$LOG"; }

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
SELECTED=""
STACK_RUNNING=0
MODE2_OFFERED=0
NO_CONTAINERS_WHY=""

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
    printf 'export ONEX_WORKSPACE_CONFIG_ROOT="%s"\n' "$WORKSPACE_CONFIG_ROOT"
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

# Clone or fetch only; what an existing clone needs is decided by bring_clone_current.
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
  local why=""
  [ "${changed:-0}" -gt 0 ] && why="$changed tracked file(s) changed or deleted"
  [ "${unique:-0}" -gt 0 ] && why="${why}${why:+; }$unique commit(s) that origin does not have"
  [ -n "$why" ] || return 0
  printf '%s (%s, %s commit(s) behind origin/%s)' "$why" "$(clone_where "$where")" "${behind:-0}" "${def:-?}"
}

clone_where() { case "$1" in detached) echo "detached HEAD" ;; *) echo "on branch $1" ;; esac; }

# The command that clears clone_problem without losing anything: the clone moves
# aside whole, and the next run clones it fresh.
clone_fix() { # repo
  printf 'mkdir -p "%s" && mv "%s" "%s"' "$WORKSPACE/.set-aside" "$WORKSPACE/$1" "$WORKSPACE/.set-aside/$1.$STAMP"
}

# A clean clone is brought to origin's default branch, so a returning machine
# never fails later on a file newer than its checkout. Pinned clones are then
# checked out at their pin by pin_clone_to_proven.
bring_clone_current() { # repo
  local d="$WORKSPACE/$1" def
  def="$(clone_default_branch "$1")"
  [ -n "$def" ] || { echo "origin has no default branch" >&2; return 1; }
  if [ "$(git -C "$d" symbolic-ref --quiet --short HEAD 2>/dev/null)" != "$def" ]; then
    git -C "$d" checkout --quiet "$def" 2>/dev/null ||
      git -C "$d" checkout --quiet -b "$def" "origin/$def" || return 1
  fi
  git -C "$d" merge --ff-only --quiet "origin/$def"
}

proven_pin() { # repo -> the CI-proven commit, empty when the repo has no pin
  local pins="$WORKSPACE/omnibase_infra/.github/sibling-pins.yaml"
  [ -f "$pins" ] || return 0
  sed -n "/^pins:[[:space:]]*$/,/^[^[:space:]]/s/^  $1: \([0-9a-fA-F]\{40\}\)[[:space:]]*$/\1/p" "$pins"
}

pin_clone_to_proven() { # repo
  local d="$WORKSPACE/$1" pin changes
  pin="$(proven_pin "$1")" || return 1
  [ -n "$pin" ] || return 0
  [ "$(git -C "$d" rev-parse HEAD)" = "$pin" ] && return 0
  changes="$(git -C "$d" status --porcelain)" || return 1
  if [ -n "$changes" ]; then
    say "  $1: clone has uncommitted changes; cannot check out the proven commit"
    return 1
  fi
  if ! git -C "$d" cat-file -e "$pin^{commit}" 2>/dev/null; then
    git -C "$d" fetch --quiet origin || return 1
    git -C "$d" cat-file -e "$pin^{commit}" 2>/dev/null || return 1
  fi
  git -C "$d" checkout --quiet --detach "$pin"
}

pin_clone_at_proven() { # repo
  local pin
  pin="$(proven_pin "$1")" || return 1
  [ -n "$pin" ] || return 0
  [ "$(git -C "$WORKSPACE/$1" rev-parse HEAD)" = "$pin" ]
}

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
config_git() { # git in the workspace config root, with an identity of its own
  git -C "$WORKSPACE_CONFIG_ROOT" -c user.name=omninode-dev-setup \
    -c user.email=dev-setup@omninode.invalid -c commit.gpgsign=false "$@"
}

commit_workspace_runtime_config() {
  if [ ! -d "$WORKSPACE_CONFIG_ROOT/.git" ]; then
    config_git init --quiet && config_git symbolic-ref HEAD refs/heads/main || return 1
  fi
  config_git add "$WORKSPACE_RUNTIME_CONFIG_REL" || return 1
  config_git diff --cached --quiet || config_git commit --quiet -m "workspace runtime config (omninode-dev-setup)" || return 1
  config_git update-ref refs/remotes/origin/main HEAD
}

# Bound for every run, not inside phase 2 alone: a resumed run skips phase 2,
# and its later phases must still run against this workspace.
bind_workspace_env() {
  export OMNIBASE_PATH="$WORKSPACE"
  export ONEX_WORKSPACE_CONFIG_ROOT="$WORKSPACE_CONFIG_ROOT"
}

workspace_runtime_config_present() {
  grep -qF "$WORKSPACE_RUNTIME_CONFIG_MARK" \
    "$WORKSPACE_CONFIG_ROOT/$WORKSPACE_RUNTIME_CONFIG_REL" 2>/dev/null
}

phase2_verified() {
  local r
  [ -f "$WORKSPACE/omnibase_infra/.github/sibling-pins.yaml" ] || return 1
  for r in $REPOS; do
    [ -d "$WORKSPACE/$r/.git" ] || return 1
    pin_clone_at_proven "$r" || return 1
  done
  workspace_runtime_config_present || return 1
  git -C "$WORKSPACE_CONFIG_ROOT" rev-parse --verify --quiet "origin/main:$WORKSPACE_RUNTIME_CONFIG_REL" >/dev/null || return 1
  [ -f "$WORKSPACE_MARKER" ] || return 1
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
  refuse_foreign_workspace
  mkdir -p "$WORKSPACE" || { FAILED_STEP="create $WORKSPACE"; phase_fail "choose another directory with --workspace"; }
  [ -f "$WORKSPACE_MARKER" ] || printf 'This workspace was created by omninode-dev-setup.\n' >"$WORKSPACE_MARKER" ||
    { FAILED_STEP="mark the workspace"; phase_fail "could not write $WORKSPACE_MARKER; check the directory is writable"; }
  local r pin default_repos="" problem problems=""
  for r in $REPOS; do
    if [ -e "$WORKSPACE/$r/.git" ]; then say "  $r: present, fetching"; else say "  $r: cloning"; fi
    retry "clone or fetch $r" sync_clone "$r" || phase_fail "check that github.com is reachable, then run this again"
  done
  # Every clone is measured against origin before any of them moves, so one stop
  # names every clone that holds work, with how far behind it is and the command
  # that moves it aside. Nothing is changed in any clone when one is named.
  for r in $REPOS; do
    problem="$(clone_problem "$r" "$(clone_state "$r")")"
    [ -n "$problem" ] || continue
    say "  ✗ $r: $problem"
    say "      to move it aside: $(clone_fix "$r")"
    problems="${problems}${problems:+ }$r"
  done
  if [ -n "$problems" ]; then
    FAILED_STEP="bring the clones up to date with origin"
    LAST_ERR="these clones hold work setup will not move: $problems"
    phase_fail "commit or stash that work, or move each clone aside with the command under it (the next run clones it fresh), then run this again"
  fi
  # The proven set lives in omnibase_infra, so it is brought current first: an old
  # checkout that predates the pins file is updated, never reported as missing one.
  step "bring omnibase_infra up to date with origin" bring_clone_current omnibase_infra ||
    phase_fail "run 'git -C $WORKSPACE/omnibase_infra status' to see why it cannot fast-forward"
  [ -f "$WORKSPACE/omnibase_infra/.github/sibling-pins.yaml" ] ||
    { FAILED_STEP="read the proven set (omnibase_infra/.github/sibling-pins.yaml)"
      LAST_ERR="omnibase_infra is current with origin/$(clone_default_branch omnibase_infra), and origin has no .github/sibling-pins.yaml"
      phase_fail "nothing on this Mac is wrong: origin's omnibase_infra lacks its proven set; report it and run this again once it is restored"; }
  for r in $REPOS; do
    pin="$(proven_pin "$r")"
    if [ -n "$pin" ]; then
      pin_clone_to_proven "$r" ||
        { FAILED_STEP="check out the proven commit of $r"
          phase_fail "check that origin has commit $pin in $r ('git -C $WORKSPACE/$r fetch origin'), then run this again"; }
      say "  $r: proven ${pin:0:12}"
    else
      [ "$r" = omnibase_infra ] ||
        step "bring $r up to date with origin" bring_clone_current "$r" ||
        phase_fail "run 'git -C $WORKSPACE/$r status' to see why it cannot fast-forward"
      default_repos="${default_repos}${default_repos:+ }$r"
    fi
  done
  say "  Default branch (no proven pin): ${default_repos:-none}"
  write_workspace_runtime_config ||
    { FAILED_STEP="declare the workspace runtime config"
      phase_fail "could not write $WORKSPACE_CONFIG_ROOT/$WORKSPACE_RUNTIME_CONFIG_REL; check the directory is writable"; }
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

RES_GEMINI=""; RES_OPENROUTER=""; RES_OPENAI=""; RES_OLLAMA=""
set_result() { case "$1" in gemini) RES_GEMINI="$2" ;; openrouter) RES_OPENROUTER="$2" ;; openai) RES_OPENAI="$2" ;; ollama) RES_OLLAMA="$2" ;; esac; }
result_of() { case "$1" in gemini) echo "$RES_GEMINI" ;; openrouter) echo "$RES_OPENROUTER" ;; openai) echo "$RES_OPENAI" ;; ollama) echo "$RES_OLLAMA" ;; esac; }
passed_models() { local p out=""; for p in $MODELS; do case "$(result_of "$p")" in pass*) out="$out $p" ;; esac; done; echo "${out# }"; }

# result_line provider -> "Gemini  ✓ answered (model)" and the like
result_line() {
  local p="$1" r label
  r="$(result_of "$p")"; label="$(printf '%-11s' "$(provider_label "$p")")"
  case "$r" in
    pass:*) echo "$label ✓ answered (${r#pass:})" ;;
    fail:*) echo "$label ✗ ${r#fail:}" ;;
    *) echo "$label skipped (no key)" ;;
  esac
}

record_model_status() { # provider
  local r verdict
  r="$(result_of "$1")"
  case "$r" in pass:*) verdict=PASS ;; fail:*) verdict=FAIL ;; *) verdict=SKIPPED ;; esac
  printf 'model=%s result=%s detail="%s"\n' "$1" "$verdict" "$(printf '%s' "${r#*:}" | tr '"' "'")" >>"$STATUS"
}

# The OpenRouter default model is a deployment fact kept in the onex-overlays
# plugin, not here. An overlay the developer's ONEX_SKILL_OVERLAY_ROOTS already
# reaches is used as it is; otherwise the one overlay file is read from the
# private repository for this GitHub login, the way phase 5 reaches its plugins.
MODEL_OVERLAY_REPO="OmniNode-ai/omniclaude-internal"
MODEL_OVERLAY_FILE="plugins/onex-overlays/overlays/node_model_setup_effect/overlay.yaml"

fetch_model_overlay() { # -> 0 when $RUN_DIR/overlay-roots holds the overlay
  local dest="$RUN_DIR/overlay-roots/node_model_setup_effect"
  mkdir -p "$dest" || return 1
  gh api "repos/$MODEL_OVERLAY_REPO/contents/$MODEL_OVERLAY_FILE" -H "Accept: application/vnd.github.raw" >"$dest/overlay.yaml" 2>>"$LOG" && [ -s "$dest/overlay.yaml" ] && return 0
  rm -f "$dest/overlay.yaml"
  return 1
}

# stdout: the overlay's model (return 0), or the reason (return 1)
openrouter_default_model() {
  local out roots="${ONEX_SKILL_OVERLAY_ROOTS:-}"
  out="$(models_cmd default-model openrouter 2>&1)" && { printf '%s\n' "$out" | tail -n 1; return 0; }
  if fetch_model_overlay; then
    out="$(export ONEX_SKILL_OVERLAY_ROOTS="$RUN_DIR/overlay-roots${roots:+:$roots}"; models_cmd default-model openrouter 2>&1)" &&
      { printf '%s\n' "$out" | tail -n 1; return 0; }
  fi
  printf '%s\n' "$out" | sed -n 's/^Error: //p' | tail -n 1
  return 1
}

# cause_of < text -> the line that says why a delegation failed: the last
# "Error: ..." line, else the last refusal, else nothing. A summary such as "the
# test delegation exited with status 1" is never the whole message on its own.
cause_of() {
  awk '/^Error: /{e=substr($0, 8)} /REFUSED|refused/{r=$0} END{if (e != "") print e; else if (r != "") print r}' |
    cut -c1-300
}

setup_model() { # provider -> result_of provider is pass:<model> or fail:<reason>
  local p="$1" key out err line status model="" reason cause
  err="$RUN_DIR/models.err"
  key="$(pending_key "$p")"; set_pending_key "$p" ""
  if [ "$p" = "openrouter" ] && [ -n "$key" ]; then
    if ! model="$(openrouter_default_model)"; then
      key=""
      set_result "$p" "fail:$(printf '%s' "${model:-no overlay declares a default OpenRouter model}" | cut -c1-240) Nothing was stored. To choose a model yourself: onex models add openrouter --model <model id>"
      return 0
    fi
  fi
  if [ -n "$key" ]; then
    out="$(printf '%s' "$key" | models_cmd add "$p" --json ${model:+--model "$model"} 2>"$err")"
  else
    out="$(models_cmd test "$p" --json 2>"$err")"
  fi
  key=""
  printf '%s\n' "$out" | grep -vE '^\{' >>"$LOG"
  cat "$err" >>"$LOG" 2>/dev/null
  line="$(printf '%s\n' "$out" | grep -E '^\{' | tail -n 1)"
  status="$(receipt_field "$line" status)"
  cause="$({ printf '%s\n' "$out" | grep -vE '^\{'; cat "$err" 2>/dev/null; } | cause_of)"
  case "$status" in
    passed) set_result "$p" "pass:$(receipt_field "$line" model)" ;;
    failed)
      reason="$(receipt_field "$line" reason | cut -c1-300)"
      case "$reason" in
        ""|*"exited with status"*) [ -n "$cause" ] && reason="${reason:+$reason: }$cause" ;;
      esac
      set_result "$p" "fail:$reason" ;;
    not_set_up) set_result "$p" "fail:no key is stored for it" ;;
    *) set_result "$p" "fail:$cause" ;;
  esac
  [ "$(result_of "$p")" = "fail:" ] && set_result "$p" "fail:onex models gave no result; see the log"
  rm -f "$err"
}

phase3() {
  phase_start 3 "onex, local identity and your models" "3-10 minutes, more when Ollama downloads a model"
  local p passed

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

  say ""
  for p in $MODELS; do
    if [ -n "$(result_of "$p")" ]; then :; else
      say "  Setting up $(provider_label "$p") and running one delegation on it…"
      setup_model "$p"
    fi
    say "  $(result_line "$p")"
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
  if ollama_has_model "$OLLAMA_MODEL"; then
    say "  Model $OLLAMA_MODEL: present"
  else
    say "  Downloading $OLLAMA_MODEL (about $OLLAMA_DOWNLOAD_GB GB)…"
    retry "download $OLLAMA_MODEL" "$(ollama_bin)" pull "$OLLAMA_MODEL" || {
      LAST_ERR="run 'ollama pull $OLLAMA_MODEL' to see the error"; return 1; }
  fi
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
      local-*) say "  Answered by Ollama on this Mac ($served)." ;;
      *) FAILED_STEP="check the stack's delegation went to Ollama"
         LAST_ERR="the answer came from ${served:-no backend}, not a local route"
         phase_fail "check that Ollama is running and ~/.omnibase/local.bifrost.yaml names it" ;;
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
# A new terminal, with the developer's own profile, runs the workspace onex: no
# alias, function or earlier install answers in its place.
shell_runs_workspace_onex() {
  local kind path
  kind="$(shell_onex_kind)"
  case "$kind" in
    command|file) ;;
    *) echo "in a new terminal onex is: ${kind:-not found}"; return 1 ;;
  esac
  path="$(shell_onex_path)"
  is_workspace_onex "$path" || { echo "a new terminal runs $path"; return 1; }
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
  check "the full onex plugin installed in Claude Code" plugin_installed onex@omninode-tools-dev
  if [ "$MODE2_OK" -eq 1 ]; then check "local stack healthy" stack_healthy; fi
  if [ "$CHECKS_FAILED" -gt 0 ]; then
    FAILED_STEP="$CHECKS_FAILED check(s) failed"
    phase_fail "the ✘ lines above name what is wrong; fix them and run this again"
  fi
  phase_pass
}

# ===========================================================================
main() {
  local p
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
  for p in $MODELS $SKIPPED; do say "  $(result_line "$p")"; done
  say "$(count_words "$(passed_models)") of $(count_words "$MODELS $SKIPPED") models ready. Delegation chooses among them for each task."
  say "Add or fix one any time: onex models add <gemini|openrouter|openai>; see them all: onex models list"
  say "Next:"
  say "  1. Open a new terminal (or run 'exec zsh') so OMNIBASE_PATH and PATH take effect."
  say "  2. Open Claude Code (run 'claude') and sign in with your Anthropic account the first"
  say "     time it asks. The onex skills are already installed; /onex:delegate is one of them."
  notify "Onboarding complete" "Every phase passed"
  printf 'result=COMPLETE\n' >>"$STATUS"
}

main
