#!/bin/bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
# Bash bootstrap handler for node_skill_omninode_dev_setup_orchestrator.
# Sourced by lab-onboarding.sh before Python or the ONEX runtime is installed.
# The caller supplies the platform probes, prompts, clone operations and run state.

# A resumed run (after a failure, or with a freshly downloaded script: the record
# lives under $HOME, not beside the script) checks completed phases rather than
# redoing them, and keeps the last run's answers so it asks one question, not all.
CHOICES_FILE="$STATE_DIR/choices"
RESUMING=0
saved_choice() { [ "$RESTART" -eq 0 ] && sed -n "s/^$1=//p" "$CHOICES_FILE" 2>/dev/null | tail -n 1; }
save_choices() {
  mkdir -p "$STATE_DIR" && {
    printf 'models=%s\ncontainers=%s\n' "$MODELS" "$MODE2_OK"
    # A local model server's URL and model, so a resumed run asks neither again.
    has_model local && printf 'local_url=%s\nlocal_model=%s\n' "$LOCAL_URL" "$LOCAL_MODEL"
  } >"$CHOICES_FILE"
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
# An interactive shell may print its own lines first (Terminal.app's "Restored
# session:" banner), so each answer is printed behind a marker and only the line
# that carries the marker is read (OMN-21466).
shell_onex_answer() { # MARKER COMMAND -> the text the shell printed after MARKER=
  in_user_shell 15 "printf '${1}=%s\\n' \"\$($2)\"" | sed -n "s/^${1}=//p" | head -n 1
}
shell_onex_kind() {
  case "$(user_shell)" in
    zsh) shell_onex_answer ONEX_KIND 'whence -w onex' | sed -n 's/^onex: //p' ;;
    *) shell_onex_answer ONEX_KIND 'type -t onex' ;;
  esac
}
shell_onex_path() {
  case "$(user_shell)" in
    zsh) shell_onex_answer ONEX_PATH 'whence -p onex' ;;
    *) shell_onex_answer ONEX_PATH 'type -P onex' ;;
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

SELECTED=""
STACK_RUNNING=0
MODE2_OFFERED=0
NO_CONTAINERS_WHY=""

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
  is_workspace_onex "$path" || { echo "a new terminal runs \"$path\""; return 1; }
}

# ---------------------------------------------------------------------------
# The models for each key, and for Ollama (OMN-21058). After each key,
# onboarding reads the models that key can use from the provider's own list,
# numbered, and the developer picks one or more in the order to try them; that
# order is the key's routing order in onex (`onex models add --model`,
# repeated, the OMN-21059 path). Nothing is picked for the developer: an empty
# or out-of-range answer asks again. The models onex's provider catalogue
# prefers for the key (its `model_preference`, newest generation of each
# family) are listed first and recommended, so nobody needs to know a model id.
#
# Where the list lives (`models_url`) and the preference are the provider
# catalogue's, the rows `onex models add` checks a choice against. Preflight
# runs before the workspace is cloned, so it reads the catalogue from the
# omnimarket clone when there is one, else from omnimarket's default branch.
# Ollama's list is the model config's `ollama` block: the models this Mac has
# the memory for, the one sized to it recommended.
# ---------------------------------------------------------------------------
CATALOGUE_REL="omnimarket/src/omnimarket/configs/byok_provider_backends.v1.yaml"
CHOSEN_GEMINI=""; CHOSEN_OPENROUTER=""; CHOSEN_OPENAI=""; CHOSEN_OLLAMA=""; REC_BASIS=""
MODEL_LIST=""; MODEL_LIST_ERR=""; RECOMMENDED=""; MODEL_UNAVAILABLE=""; MODEL_THROTTLED=""

chosen_models() { case "$1" in gemini) echo "$CHOSEN_GEMINI" ;; openrouter) echo "$CHOSEN_OPENROUTER" ;; openai) echo "$CHOSEN_OPENAI" ;; ollama) echo "$CHOSEN_OLLAMA" ;; esac; }
set_chosen_models() { case "$1" in gemini) CHOSEN_GEMINI="$2" ;; openrouter) CHOSEN_OPENROUTER="$2" ;; openai) CHOSEN_OPENAI="$2" ;; ollama) CHOSEN_OLLAMA="$2" ;; esac; }
comma_list() { printf '%s' "$1" | sed 's/ /, /g'; }

omnimarket_file() { # rel seam -> the file: the test seam, else the workspace clone, else omnimarket's default branch
  if [ -n "$2" ]; then cat "$2" 2>/dev/null
  elif [ -f "$WORKSPACE/$1" ]; then cat "$WORKSPACE/$1"
  else curl -fsS -m 30 "https://raw.githubusercontent.com/OmniNode-ai/omnimarket/HEAD/${1#omnimarket/}" 2>/dev/null; fi
}

# catalogue_row provider -> "url <models_url>", "endpoint <endpoint_url>" (the chat
# completions URL a probe posts to), then "pattern <regex>" for each
# model_preference entry in order, from the provider's first row
catalogue_row() {
  omnimarket_file "$CATALOGUE_REL" "${ONBOARD_TEST_CATALOGUE:-}" | awk -v want="$1" '
    /^  - provider:/ { if (seen) exit; v = $3; gsub(/["'"'"']/, "", v); row = (v == want); if (row) seen = 1; next }
    !row { next }
    /^    models_url:/ { v = $2; gsub(/["'"'"']/, "", v); print "url " v; next }
    /^    endpoint_url:/ { v = $2; gsub(/["'"'"']/, "", v); print "endpoint " v; next }
    /^      - pattern:/ { v = $0; sub(/^      - pattern: */, "", v); gsub(/^["'"'"']|["'"'"']$/, "", v); print "pattern " v }'
}

# The catalogue's full-match Python regex as an ERE: named and non-capturing
# groups become plain groups.
to_ere() { printf '^(%s)$' "$(printf '%s' "$1" | sed -e 's/(?P<[A-Za-z_]*>/(/g' -e 's/(?:/(/g')"; }

# recommended_order provider -> the routing contract's recommended models for
# it, first tried first, one per line (OMN-21209): a key's catalogue row's
# default_models; for ollama, the catalogue's local model sized to this Mac.
recommended_order() {
  omnimarket_file "$CATALOGUE_REL" "${ONBOARD_TEST_CATALOGUE:-}" | awk -v want="$1" -v ram="$(ram_gb)" '
    function unq(v) { gsub(/^["'"'"']|["'"'"']$/, "", v); return v }
    /^[^ #]/ { top = $1 }
    top == "providers:" && /^  - provider:/ { if (seen) done = 1; row = (unq($3) == want) && !done; if (row) seen = 1; inlist = 0; next }
    top == "providers:" && row && /^    default_models:/ { inlist = 1; next }
    top == "providers:" && row && inlist { if ($0 ~ /^      - /) { print unq($2); next } inlist = 0 }
    want == "ollama" && top == "local:" && /min_memory_gb:/ { mem = $NF }
    want == "ollama" && top == "local:" && /^      model:/ { if (mem + 0 <= ram + 0 && mem + 0 >= best + 0) { best = mem; pick = unq($NF) } }
    END { if (pick != "") print pick }'
}

# recommended_basis -> the record the onboarding order rests on, as the
# catalogue's recommended_order names it (OMN-21209); empty when it names none
recommended_basis() {
  omnimarket_file "$CATALOGUE_REL" "${ONBOARD_TEST_CATALOGUE:-}" | awk '
    function unq(v) { gsub(/^["'"'"']|["'"'"']$/, "", v); return v }
    /^[^ #]/ { top = $1; next }
    top != "recommended_order:" { next }
    /^  onboarding:/ { want = unq($2); next }
    /^    [A-Za-z0-9_]+:$/ { name = $1; sub(/:$/, "", name); next }
    /^      basis:/ { v = $0; sub(/^      basis: */, "", v); basis[name] = unq(v) }
    END { if (want != "" && basis[want] != "") print basis[want] }'
}

# list_in_order ids recommended -> MODEL_LIST (the recommended ids, in order,
# then the rest) and RECOMMENDED (their numbers, comma-separated)
list_in_order() {
  local m i=0
  MODEL_LIST="$2"
  while IFS= read -r m; do
    [ -n "$m" ] || continue
    i=$((i + 1)); RECOMMENDED="${RECOMMENDED}${RECOMMENDED:+,}$i"
  done <<EOF
$2
EOF
  m="$(printf '%s\n' "$1" | grep -vxF "$2" | grep .)"
  [ -n "$m" ] && MODEL_LIST="${MODEL_LIST}${MODEL_LIST:+
}$m"
  return 0
}

offered_models() { # provider < ids -> the chat models worth offering, one per line
  case "$1" in
    openrouter) grep -E ':free$' ;;  # the free ones: no credit needed; the full list runs to hundreds
    gemini) grep -E '^gemini-' | grep -vE 'embedding|tts|image|audio|live|native' ;;
    openai) grep -E '^(gpt-|o[0-9]|chatgpt-)' | grep -vE 'audio|realtime|tts|transcribe|image|search|instruct|embedding|moderation' ;;
    *) cat ;;
  esac
}

# list_recommended_first ids patterns -> MODEL_LIST (the newest match of each
# preferred family in preference order, then the rest sorted) and RECOMMENDED
# (their numbers, comma-separated)
list_recommended_first() {
  local pat m best="" i=0
  while IFS= read -r pat; do
    [ -n "$pat" ] || continue
    m="$(printf '%s\n' "$1" | grep -E "$(to_ere "$pat")" | sort -V -r | head -n 1)"
    [ -n "$m" ] || continue
    printf '%s\n' "$best" | grep -qxF "$m" && continue
    best="${best}${best:+
}$m"
  done <<EOF
$2
EOF
  MODEL_LIST="$best"
  while IFS= read -r m; do
    [ -n "$m" ] || continue
    i=$((i + 1)); RECOMMENDED="${RECOMMENDED}${RECOMMENDED:+,}$i"
  done <<EOF
$best
EOF
  m="$(printf '%s\n' "$1" | grep -vxF "${best:-/}" | grep .)"
  [ -n "$m" ] && MODEL_LIST="${MODEL_LIST}${MODEL_LIST:+
}$m"
  return 0
}

# probe_model endpoint key model -> "ok", "throttled" or "no:<reason>" (OMN-21465).
# One chat completion capped at one token on the developer's own key: a name in
# the provider's list is not proof the key can call it (deprecated and non-chat
# models are listed too). A 429 means the model exists and the key may call it,
# so it is not dropped (OMN-21464). The key travels in a header read from stdin.
probe_model() {
  local f out code body msg
  for f in max_completion_tokens max_tokens; do
    body="$(printf '{"model":"%s","messages":[{"role":"user","content":"Reply with: ok"}],"%s":1}' "$3" "$f")"
    if ! out="$(printf 'Authorization: Bearer %s\n' "$2" | curl -sS -m 20 -H @- -H 'Content-Type: application/json' -d "$body" -w '\n%{http_code}' "$1" 2>&1)"; then
      echo "no:it did not answer ($(printf '%s\n' "$out" | tail -n 1 | sed 's/^curl: ([0-9]*) //' | cut -c1-120))"; return 0
    fi
    code="$(printf '%s\n' "$out" | tail -n 1)"; body="$(printf '%s\n' "$out" | sed '$d')"
    [ "$code" = "400" ] && printf '%s' "$body" | grep -qE 'max_completion_tokens|max_tokens' && continue
    break
  done
  case "$code" in
    200) echo ok ;;
    429) echo throttled ;;
    *) msg="$(printf '%s' "$body" | grep -oE '"message"[[:space:]]*:[[:space:]]*"[^"]*"' | head -n 1 | sed -E 's/^"message"[[:space:]]*:[[:space:]]*"(.*)"$/\1/' | cut -c1-160)"
       echo "no:HTTP $code${msg:+: $msg}" ;;
  esac
}

# probe_listed provider endpoint key -> MODEL_LIST and RECOMMENDED narrowed to
# the models that answered, in their order; MODEL_UNAVAILABLE holds one
# "model: reason" line for each that did not; MODEL_THROTTLED the ids that were
# rate limited (kept). At most ONBOARD_PROBE_MAX models are probed (default 30),
# so a long list costs a bounded number of one-token calls. 1 when none answered.
probe_listed() {
  local m r i=0 j=0 n=0 keep="" rec="" recs
  MODEL_UNAVAILABLE=""; MODEL_THROTTLED=""
  [ -n "$2" ] || return 0
  recs="$(printf '%s' "$RECOMMENDED" | tr ',' ' ')"
  while IFS= read -r m; do
    [ -n "$m" ] || continue
    i=$((i + 1)); n=$((n + 1))
    [ "$n" -le "${ONBOARD_PROBE_MAX:-30}" ] || break
    r="$(probe_model "$2" "$3" "$m")"
    case "$r" in
      ok|throttled)
        j=$((j + 1)); keep="${keep}${keep:+
}$m"
        [ "$r" = "throttled" ] && MODEL_THROTTLED="${MODEL_THROTTLED}${m}
"
        in_list "$i" "$recs" && rec="${rec}${rec:+,}$j" ;;
      *) MODEL_UNAVAILABLE="${MODEL_UNAVAILABLE}${m}: ${r#no:}
" ;;
    esac
  done <<ENDLIST
$MODEL_LIST
ENDLIST
  MODEL_LIST="$keep"; RECOMMENDED="$rec"
  [ -n "$keep" ]
}

# key_models provider key -> MODEL_LIST and RECOMMENDED; 1 with MODEL_LIST_ERR
# (the provider's own words when it gave any) when the list cannot be read or
# offers nothing. The key goes to its provider alone, in a header read from
# stdin, so it never appears in an argument.
key_models() {
  local p="$1" row url endpoint out code body reason ids rec
  MODEL_LIST=""; MODEL_LIST_ERR=""; RECOMMENDED=""; REC_BASIS=""; MODEL_UNAVAILABLE=""; MODEL_THROTTLED=""
  row="$(catalogue_row "$p")"
  url="$(printf '%s\n' "$row" | sed -n 's/^url //p' | head -n 1)"
  endpoint="$(printf '%s\n' "$row" | sed -n 's/^endpoint //p' | head -n 1)"
  if [ -z "$url" ]; then
    MODEL_LIST_ERR="onex's provider catalogue, which names where its model list is, could not be read"
    return 1
  fi
  if ! out="$(printf 'Authorization: Bearer %s\n' "$2" | curl -sS -m 30 -H @- -w '\n%{http_code}' "$url" 2>&1)"; then
    MODEL_LIST_ERR="its model list could not be reached ($(printf '%s\n' "$out" | tail -n 1 | sed 's/^curl: ([0-9]*) //' | cut -c1-200))"
    return 1
  fi
  code="$(printf '%s\n' "$out" | tail -n 1)"
  body="$(printf '%s\n' "$out" | sed '$d')"
  if [ "$code" != "200" ]; then
    reason="$(printf '%s' "$body" | grep -oE '"message"[[:space:]]*:[[:space:]]*"[^"]*"' | head -n 1 | sed -E 's/^"message"[[:space:]]*:[[:space:]]*"(.*)"$/\1/' | cut -c1-200)"
    MODEL_LIST_ERR="its model list answered HTTP $code${reason:+: $reason}"
    return 1
  fi
  ids="$(printf '%s' "$body" | grep -oE '"id"[[:space:]]*:[[:space:]]*"[^"]+"' | sed -E 's/^.*"([^"]+)"$/\1/' | sed 's#^models/##' | offered_models "$p" | sort -u)"
  if [ -z "$ids" ]; then
    if [ "$p" = "openrouter" ]; then MODEL_LIST_ERR="its model list names no free model for this key"
    else MODEL_LIST_ERR="its model list names no chat model for this key"; fi
    return 1
  fi
  # The routing contract's recommended order: the models of it this key lists,
  # in its order (OMN-21209). A key that lists none of them falls back to the
  # catalogue's preferred families.
  rec="$(recommended_order "$p" | grep -xF "$ids")"
  if [ -n "$rec" ]; then list_in_order "$ids" "$rec"; REC_BASIS="$(recommended_basis)"
  else list_recommended_first "$ids" "$(printf '%s\n' "$row" | sed -n 's/^pattern //p')"; fi
  # OMN-21465: only models that answered a one-token call on this key are
  # offered or recommended; the rest are listed as unavailable with the
  # provider's reason. A provider with none left is unusable here, at the menu.
  if ! probe_listed "$p" "$endpoint" "$2"; then
    MODEL_LIST_ERR="none of the $(printf '%s\n' "$MODEL_UNAVAILABLE" | grep -c .) models it lists answered a test call on your key ($(printf '%s' "$MODEL_UNAVAILABLE" | head -n 1 | cut -c1-200))"
    return 1
  fi
}

# ram_gb [model] -> "port chat_path model download_gb": the first `models` entry
# whose min_memory_gb fits this Mac, or the named model (its size when the model
# config or the catalogue's local row lists it, else the largest listed).
ollama_config() {
  "$WORKSPACE/.onex-dispatch-venv/bin/python" - "$WORKSPACE/$OLLAMA_CONFIG_REL" "$1" "${2:-}" "$WORKSPACE/$CATALOGUE_REL" <<'PYCFG'
import os
import sys
import yaml
block = (yaml.safe_load(open(sys.argv[1])) or {}).get("ollama") or {}
port, path, models = block.get("port"), block.get("chat_path"), block.get("models") or []
if not port or not path or not models:
    sys.exit("the model config has no complete ollama block (port, chat_path, models)")
ram, wanted = int(sys.argv[2]), sys.argv[3]
models = sorted(models, key=lambda m: int(m["min_memory_gb"]), reverse=True)
# Onboarding offers the catalogue's local models (OMN-21209), so their sizes count.
local = []
if len(sys.argv) > 4 and os.path.isfile(sys.argv[4]):
    local = ((yaml.safe_load(open(sys.argv[4])) or {}).get("local") or {}).get("memory_classes") or []
if wanted:
    size = next((m["download_gb"] for m in [*models, *local] if m["model"] == wanted), max(m["download_gb"] for m in models))
    print(port, path, wanted, size)
else:
    pick = next((m for m in models if int(m["min_memory_gb"]) <= ram), models[-1])
    print(port, path, pick["model"], pick["download_gb"])
PYCFG
}

# ollama_models -> MODEL_LIST: the catalogue's local models this Mac has the
# memory for, largest first, the first (the one sized to this Mac, the routing
# contract's recommended order for Ollama, OMN-21209) recommended; 1 with
# MODEL_LIST_ERR when there is none.
ollama_models() {
  MODEL_LIST=""; MODEL_LIST_ERR=""; RECOMMENDED=""; REC_BASIS=""
  MODEL_LIST="$(omnimarket_file "$CATALOGUE_REL" "${ONBOARD_TEST_CATALOGUE:-}" | awk -v ram="$(ram_gb)" '
    /^[^ #]/ { top = $1 }
    top != "local:" { next }
    /min_memory_gb:/ { mem = $NF }
    /^      model:/ { m = $NF; gsub(/["'"'"']/, "", m); if (mem + 0 <= ram + 0) print mem "\t" m }' | sort -t "$TAB" -k1,1nr | cut -f2)"
  if [ -z "$MODEL_LIST" ]; then
    MODEL_LIST_ERR="onex's provider catalogue recommends no Ollama model for this Mac's $(ram_gb) GB of memory"
    return 1
  fi
  RECOMMENDED=1; REC_BASIS="$(recommended_basis)"
}

# parse_ordered_choice answer count -> the numbers, in the order given; 1 when
# the answer is empty, out of range, or names a number twice
parse_ordered_choice() {
  local w out=""
  for w in $(printf '%s' "$1" | tr ',' ' '); do
    case "$w" in ''|*[!0-9]*) return 1 ;; esac
    w=$((10#$w))
    { [ "$w" -ge 1 ] && [ "$w" -le "$2" ]; } || return 1
    in_list "$w" "$out" && return 1
    out="$out $w"
  done
  [ -n "$out" ] || return 1
  echo "${out# }"
}

# choose_models provider -> its chosen models from MODEL_LIST, in the order
# given, by number; an empty or out-of-range answer asks again
choose_models() {
  local p="$1" label a n i=0 m nums picked="" what busy
  label="$(provider_label "$p")"
  n="$(printf '%s\n' "$MODEL_LIST" | grep -c .)"
  case "$p" in
    openrouter) what="the $n free models OpenRouter lists for your key" ;;
    ollama) what="the $n models Ollama can run in this Mac's $(ram_gb) GB of memory" ;;
    *) what="the $n chat models $label lists for your key" ;;
  esac
  say ""
  say "  Your $label models: $what."
  say ""
  while IFS= read -r m; do
    i=$((i + 1))
    busy=""; printf '%s\n' "$MODEL_THROTTLED" | grep -qxF "$m" && busy="  (busy just now, HTTP 429)"
    if in_list "$i" "$(printf '%s' "$RECOMMENDED" | tr ',' ' ')"; then say "    $(printf '%2d' "$i")) $m  (recommended)$busy"
    else say "    $(printf '%2d' "$i")) $m$busy"; fi
  done <<EOF
$MODEL_LIST
EOF
  if [ -n "$MODEL_UNAVAILABLE" ]; then
    say ""
    say "  Not offered, your key could not call these:"
    while IFS= read -r m; do [ -n "$m" ] && say "    ✗ $m"; done <<ENDBAD
$MODEL_UNAVAILABLE
ENDBAD
  fi
  say ""
  if [ -n "$REC_BASIS" ] && [ -n "$RECOMMENDED" ]; then
    # OMN-21209: the routing contract's order, and the record it rests on.
    say "  Recommended, in this order: $RECOMMENDED (the routing contract's order for this key; it rests on $REC_BASIS)."
  elif [ -n "$RECOMMENDED" ]; then
    say "  Recommended, in this order: $RECOMMENDED (the models onex prefers for this key)."
  fi
  say "  Pick one or more in the order to try them, first tried first (for example 2,1)."
  # OMN-21209: the recommended order is the pre-selected answer, so a developer
  # with no opinion about model ids presses Enter and types none.
  [ -n "$RECOMMENDED" ] && say "  Press Enter to take the recommended order."
  [ "$p" = "openrouter" ] && say "  A model that uses credits can be added later: onex models add-model openrouter --model <id>"
  while :; do
    say ""
    printf '  Choose your %s models, 1 to %s: ' "$label" "$n"
    IFS= read -r a || quit_setup
    case "$a" in q|Q|quit|QUIT) quit_setup ;; esac
    [ -z "$a" ] && [ -n "$RECOMMENDED" ] && a="$RECOMMENDED"
    nums="$(parse_ordered_choice "$a" "$n")" && break
    say "  Choose one or more numbers, 1 to $n (for example 2,1), or q to quit."
  done
  for i in $nums; do picked="$picked $(printf '%s\n' "$MODEL_LIST" | sed -n "${i}p")"; done
  set_chosen_models "$p" "${picked# }"
  say "  $label models, first tried first: $(comma_list "${picked# }")"
}

# A list that cannot be read is a skip that carries the reason: nothing is
# stored for that model, and the others carry on.
drop_unlisted() { # provider
  drop_model "$1"; SKIPPED="${SKIPPED:+$SKIPPED }$1"
  set_result "$1" "fail:$MODEL_LIST_ERR"
  say "  ✗ $(provider_label "$1"): $MODEL_LIST_ERR. Nothing was stored for it; your other models carry on."
}

ask_ollama_models() {
  [ -n "$CHOSEN_OLLAMA" ] && return 0
  if [ -n "$OLLAMA_MODEL" ]; then CHOSEN_OLLAMA="$OLLAMA_MODEL"; return 0; fi  # --ollama-model
  ollama_overrides_ours && return 0  # set up by an earlier run: kept
  if ollama_models; then choose_models ollama; else drop_unlisted ollama; fi
}

settle_models() {
  STORED="$(stored_key_providers 2>/dev/null | tr '\n' ' ')"; STORED="${STORED% }"
  local models_from="--provider"
  [ -z "$PROVIDER" ] || MODELS="$(in_menu_order "$(printf '%s' "$PROVIDER" | tr ',' ' ')")"
  if [ -z "$MODELS" ] && [ "$RESUMING" -eq 1 ]; then
    MODELS="$(in_menu_order "$(saved_choice models)")"; models_from="your last run"
  fi
  if [ "$PROMPT_TTY" -eq 0 ]; then settle_models_unattended; else
    local asked_by_flag=0 p
    [ -n "$MODELS" ] && asked_by_flag=1
    while :; do
      if [ "$asked_by_flag" -eq 1 ]; then
        asked_by_flag=0
        say ""
        say "  Your models (from $models_from): $(labels "$MODELS")"
      else
        ask_models
      fi
      SKIPPED=""; for p in gemini openrouter openai ollama; do set_result "$p" ""; done
      ask_keys
      if has_model ollama; then ask_ollama_models; fi
      if [ -z "$MODELS" ]; then
        say ""
        say "  Every model was skipped. Choose at least one."
        continue
      fi
      if has_model local; then settle_local_url; fi
      confirm_models && break
    done
    # Keys and models for models dropped at the summary are forgotten here.
    for p in gemini openrouter openai; do has_model "$p" || set_pending_key "$p" ""; done
    for p in gemini openrouter openai ollama; do has_model "$p" || set_chosen_models "$p" ""; done
  fi
  if has_model ollama; then settle_ollama; fi
  if [ "$PROMPT_TTY" -eq 0 ] && has_model local; then settle_local_url; fi
}

# Model selection belongs to the bootstrap handler, alongside settle_models.
# "1,3,4", "1 3 4", "134" and "4,1,3" all choose the same models; repeats are
# ignored. Sets MODELS in menu order; 1 when the answer chooses nothing valid.
parse_model_choice() {
  local a p i=0 picked=""
  a="$(printf '%s' "$1" | tr -d ', ')"
  [ -n "$a" ] || return 1
  case "$a" in *[!1-5]*) return 1 ;; esac
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
      local)      say "    $i) Local URL   a model server you already run (LM Studio, llama.cpp, vLLM, MLX)"
                  say "                   that speaks the OpenAI API: its URL and model name, no key" ;;
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
    say "  Choose at least one, 1 to 5 (for example 1,3), or q to quit."
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
      say "  Asking $label which models your key can use…"
      if key_models "$p" "$(pending_key "$p")"; then choose_models "$p"
      else set_pending_key "$p" ""; drop_unlisted "$p"; fi
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
      if [ -n "$CHOSEN_OLLAMA" ]; then say "    Ollama      no key; models $(comma_list "$CHOSEN_OLLAMA"), downloaded in phase 3"
      elif ollama_overrides_ours; then say "    Ollama      already set up on this Mac"
      else say "    Ollama      no key; downloads a model sized to this Mac's $(ram_gb) GB of memory"; fi
    elif [ "$p" = "local" ]; then
      say "    Local URL   no key; $LOCAL_MODEL on the server at $LOCAL_URL"
    elif [ -n "$(pending_key "$p")" ] && [ -n "$(chosen_models "$p")" ]; then
      say "    $(printf '%-11s' "$(provider_label "$p")") key received, models $(comma_list "$(chosen_models "$p")")"
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

# ---------------------------------------------------------------------------
# A local model server by URL: a server the developer already runs (LM Studio,
# llama.cpp, vLLM, MLX), on this Mac or the network, that speaks the
# OpenAI-compatible API and needs no key. Its URL and model are asked here, in
# preflight; phase 3 hands both to `onex models add local --url --model`
# (omnimarket 0.4.316), which declares it as onex's local-url
# backend and runs one delegation pinned to it. No key is ever asked for.
# ---------------------------------------------------------------------------
LOCAL_URL_MARK="# Written by omninode-dev-setup: a local model server by URL."
LOCAL_URL_OMNIMARKET="0.4.316"   # the first omnimarket release with `onex models add local --url`

local_url_base() { # url -> the base URL, without a trailing / or /v1, as onex stores it
  local b="${1%/}"; b="${b%/v1}"; printf '%s' "${b%/}"
}
local_url_valid() { # an http(s) URL with a host
  case "$1" in http://?*|https://?*) ;; *) return 1 ;; esac
  case "$1" in *[[:space:]]*) return 1 ;; esac
}
# Anything that answers HTTP at the server's address counts. Preflight never calls
# the model API itself (model calls go through delegation): whether it serves a
# model is decided by `onex models add local`, with its one pinned test delegation.
local_url_answers() { curl -sS -m 5 -o /dev/null "$(local_url_base "$1")/" 2>/dev/null; }

local_url_unreachable() { # url: stop before anything installs, naming the URL
  FAILED_STEP="reach the local model server"
  LAST_ERR="nothing answers at $1"
  phase_fail "start the model server at $1 (or name another with --local-url), then run this again. Nothing was installed"
}

settle_local_url() { # preflight: the server's URL and model, never a key
  local a
  [ -n "$LOCAL_URL" ] || LOCAL_URL="$(saved_choice local_url)"
  [ -n "$LOCAL_MODEL" ] || LOCAL_MODEL="$(saved_choice local_model)"
  while :; do
    if [ -z "$LOCAL_URL" ]; then
      if [ "$PROMPT_TTY" -eq 0 ]; then
        FAILED_STEP="choose your models"
        LAST_ERR="a local model server needs its URL, and there is no terminal to ask on"
        phase_fail "pass --local-url URL and --local-model NAME, or run this in Terminal. Nothing was installed"
      fi
      say ""
      say "  Local model server: one you already run (LM Studio, llama.cpp, vLLM, MLX) that"
      say "  speaks the OpenAI API. No key is asked for."
      printf '  Its URL, such as http://127.0.0.1:1234 (q to quit): '
      IFS= read -r a || quit_setup
      case "$a" in q|Q|quit|QUIT) quit_setup ;; esac
      LOCAL_URL="$(printf '%s' "$a" | tr -d '[:space:]')"
    fi
    if ! local_url_valid "$LOCAL_URL"; then
      say "  ✗ '$LOCAL_URL' is not an http(s) URL with a host, such as http://127.0.0.1:1234."
      if [ "$PROMPT_TTY" -eq 0 ]; then
        FAILED_STEP="choose your models"; LAST_ERR="'$LOCAL_URL' is not an http(s) URL"
        phase_fail "pass --local-url with an http(s) URL such as http://127.0.0.1:1234. Nothing was installed"
      fi
      LOCAL_URL=""; continue
    fi
    local_url_answers "$LOCAL_URL" && break
    say "  ✗ Nothing answers at $LOCAL_URL. Start the server there, or check its URL."
    [ "$PROMPT_TTY" -eq 1 ] || local_url_unreachable "$LOCAL_URL"
    LOCAL_URL=""
  done
  case "$LOCAL_MODEL" in *[[:space:]]*)
    say "  ✗ '$LOCAL_MODEL' is not a model name: a model name has no spaces."
    [ "$PROMPT_TTY" -eq 1 ] || { FAILED_STEP="choose your models"; LAST_ERR="'$LOCAL_MODEL' has a space"
      phase_fail "pass --local-model with the name the server lists. Nothing was installed"; }
    LOCAL_MODEL="" ;;
  esac
  while [ -z "$LOCAL_MODEL" ]; do
    if [ "$PROMPT_TTY" -eq 0 ]; then
      FAILED_STEP="choose your models"
      LAST_ERR="the local model server at $LOCAL_URL needs a model name, and there is no terminal to ask on"
      phase_fail "pass --local-model NAME, or run this in Terminal. Nothing was installed"
    fi
    printf '  The model it runs, as the server names it: '
    IFS= read -r a || quit_setup
    LOCAL_MODEL="$(printf '%s' "$a" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
    case "$LOCAL_MODEL" in *[[:space:]]*) say "  ✗ A model name has no spaces; use the name the server lists."; LOCAL_MODEL="" ;; esac
  done
  say "  Model: the local model server at $LOCAL_URL, no key. Model: $LOCAL_MODEL."
}


# The local server takes no key: its URL and model go to `onex models add local`,
# which declares it in the local routes and runs its one pinned test delegation.
local_url_add_args() { # provider -> the add's --url and --model for the local server, else nothing
  [ "$1" = "local" ] && printf '%s\n' --url "$LOCAL_URL" --model "$LOCAL_MODEL"
  return 0
}
# A refusal (no result) means nothing answered as a model server at the URL: the run stops.
stop_local_url_unanswered() {
  FAILED_STEP="set up the local model server at $LOCAL_URL"
  LAST_ERR="$(result_of local | sed 's/^fail://')"
  phase_fail "nothing answered as a model server at $LOCAL_URL; start it there (or name another with --local-url), then run this again"
}

# `onex models add local --url` arrived in omnimarket 0.4.316. A returning Mac's
# floor may name an older omnimarket, which --proven reinstalls first; then the
# floor is set aside (never deleted) and the dispatch venv rebuilt from the
# proven set's pin, which carries it. Phase 3 stamps a new floor when it passes.
local_url_supported() { models_cmd add --help 2>/dev/null | grep -q -- '--url'; }

ensure_local_url_onex() {
  local floor="$WORKSPACE/.onex-workspace-floor.json"
  local_url_supported && return 0
  say "  This onex's omnimarket predates 'onex models add local --url' (omnimarket $LOCAL_URL_OMNIMARKET); installing the proven omnimarket…"
  if [ -f "$floor" ]; then
    mv "$floor" "$floor.pre-local-url.$STAMP" ||
      { FAILED_STEP="set aside the workspace floor"; phase_fail "move $floor aside by hand, then run this again"; }
    say "  Set aside the workspace floor as $(basename "$floor").pre-local-url.$STAMP; this phase stamps a new one."
  fi
  retry "rebuild the dispatch venv with the proven omnimarket" nice -n 10 bash "$WORKSPACE/omnibase_infra/scripts/reconcile-workspace-venvs.sh" --omni-home "$WORKSPACE" --proven ||
    phase_fail "see the log; the script names the exact command to run by hand"
  local_url_supported && return 0
  FAILED_STEP="onex models add local --url is available"
  LAST_ERR="the dispatch venv's omnimarket is older than $LOCAL_URL_OMNIMARKET"
  phase_fail "update the omnimarket clone in $WORKSPACE to $LOCAL_URL_OMNIMARKET or newer, then run this again"
}

# The local routes file carries this setup's mark on its first line, so preflight
# reads it as an earlier run's file, not the developer's. Ollama's file already
# carries one; a file with no mark (the developer's) is left as it is.
mark_local_url_overrides() {
  local f="$HOME/$OVERRIDES_FILE_REL"
  [ -f "$f" ] && return 0
  mkdir -p "$(dirname "$f")" && printf '%s\n' "$LOCAL_URL_MARK" >"$f"
}

# The chat endpoint `onex models add local` declared for the server, read back
# from the local routes, so this script never spells the server's API path.
local_url_endpoint() {
  "$WORKSPACE/.onex-dispatch-venv/bin/python" - "$HOME/$OVERRIDES_FILE_REL" <<'PYEP'
import sys
import yaml
data = yaml.safe_load(open(sys.argv[1])) or {}
for backend in data.get("backends") or []:
    if isinstance(backend, dict) and backend.get("backend_id") == "local-url":
        print(backend["endpoint_url"])
        sys.exit(0)
sys.exit("no local-url backend in " + sys.argv[1])
PYEP
}

# docker_url url -> the same URL as a container reaches it: this Mac's
# loopback is host.docker.internal from inside Docker.
docker_url() {
  local scheme rest host
  scheme="${1%%://*}://"; rest="${1#*://}"; host="${rest%%[:/]*}"
  case "$host" in 127.0.0.1|localhost|0.0.0.0) rest="host.docker.internal${rest#"$host"}" ;; esac
  printf '%s%s' "$scheme" "$rest"
}

point_bundle_at_local_url() { # the stack's local-model slot names the developer's server
  local endpoint
  endpoint="$(local_url_endpoint)" || return 1
  point_bundle_model "$(docker_url "$endpoint")" "$LOCAL_MODEL"
}

# Phase 3, before the models are set up: an onex that has `add local --url`, and
# a routes file that carries this setup's mark.
prepare_local_url() {
  ensure_local_url_onex
  step "mark the local routes file as this setup's" mark_local_url_overrides ||
    phase_fail "could not write $HOME/$OVERRIDES_FILE_REL; check that ~/.omninode is writable"
}

# Phase 4: the stack's local-model slot names the developer's server.
point_stack_at_local_url() {
  step "point the stack's local model at your model server" point_bundle_at_local_url ||
    phase_fail "set model_endpoint and served_model_id in ~/.omnibase/local.bifrost.yaml by hand, then run this again"
}

# ---------------------------------------------------------------------------
# In a VM: said once, before any question, so no choice is made without knowing.
vm_notice() {
  say ""
  say "  We detected that this Mac is a virtual machine."
  say "  Docker can't run inside a macOS VM, so the local stack isn't offered here."
  say "  Everything else works. A model on this Mac (Ollama) will be slow in a VM;"
  say "  a key (Gemini, OpenRouter or OpenAI) is the better choice."
}

# ===========================================================================
# Phase 3: each chosen model registered and tested (OMN-21058). The script's
# phase 3 calls setup_model for each model and prints result_line for it.
# ===========================================================================
# One line per chosen model tested, so each gets its own result line:
# provider|model|pass:<answered model> or provider|model|fail:<reason>
MODEL_RES=""
add_model_res() {
  MODEL_RES="${MODEL_RES}$1|$2|$3
"
}

# result_line provider -> "Gemini  ✓ answered (model)" and the like, one line
# per chosen model when the developer chose several
result_line() {
  local p="$1" r label m n
  r="$(result_of "$p")"; label="$(printf '%-11s' "$(provider_label "$p")")"
  n="$(printf '%s' "$MODEL_RES" | grep -c "^$p|")"
  if [ "$n" -gt 0 ]; then
    printf '%s' "$MODEL_RES" | grep "^$p|" | while IFS='|' read -r _ m r; do
      case "$r" in
        pass:*) echo "$label ✓ answered (${r#pass:})" ;;
        *) if [ "$n" -gt 1 ]; then echo "$label ✗ $m: ${r#fail:}"; else echo "$label ✗ ${r#fail:}"; fi ;;
      esac
    done
    return 0
  fi
  case "$r" in
    pass:*) echo "$label ✓ answered (${r#pass:})" ;;
    fail:*) echo "$label ✗ ${r#fail:}" ;;
    *) echo "$label skipped (no key)" ;;
  esac
}

# model_result out errfile provider -> pass:<model> or fail:<reason>, from one
# `onex models add` or `onex models test` run
model_result() {
  local line status reason cause
  printf '%s\n' "$1" | grep -vE '^\{' >>"$LOG"
  cat "$2" >>"$LOG" 2>/dev/null
  line="$(printf '%s\n' "$1" | grep -E '^\{' | tail -n 1)"
  status="$(receipt_field "$line" status)"
  cause="$({ printf '%s\n' "$1" | grep -vE '^\{'; cat "$2" 2>/dev/null; } | cause_of)"
  case "$status" in
    passed) echo "pass:$(receipt_field "$line" model)" ;;
    failed)
      reason="$(receipt_field "$line" reason | cut -c1-300)"
      case "$reason" in
        ""|*"exited with status"*) [ -n "$cause" ] && reason="${reason:+$reason: }$cause" ;;
      esac
      echo "fail:$reason" ;;
    not_set_up) echo "fail:no key is stored for it" ;;
    *) echo "unknown:$cause" ;;
  esac
}

# put_first provider model chosen -> the provider's routes try model first
put_first() {
  local m others=""
  for m in $3; do [ "$m" = "$2" ] || others="$others $m"; done
  if [ "$1" = "ollama" ]; then write_ollama_overrides "$2"
  else models_cmd reorder "$1" "$2" $others >>"$LOG" 2>&1; fi
}

# onex_order provider -> the provider's models in the order onex holds them
onex_order() {
  models_cmd list --json 2>>"$LOG" | jq -r --arg p "$1" 'select(.provider? == $p) | (.models // []) | join(" ")' 2>/dev/null | tail -n 1
}

setup_model() { # provider -> result_of provider is pass:<model> or fail:<reason>
  local p="$1" key out err r models m first="" passed="" held
  err="$RUN_DIR/models.err"
  key="$(pending_key "$p")"; set_pending_key "$p" ""
  models="$(chosen_models "$p")"
  if [ -n "$key" ] && [ -z "$models" ]; then
    # A key is never handed to onex without a model the developer chose.
    key=""
    set_result "$p" "fail:no $(provider_label "$p") model was chosen, so nothing was stored"
    return 0
  fi
  if [ -n "$key" ] || [ "$p" = "local" ]; then
    # Model ids hold no spaces. Unquoted on purpose: preflight admits a local server's URL and model only without spaces.
    out="$(printf '%s' "$key" | models_cmd add "$p" --json $(for m in $models; do printf -- '--model %s ' "$m"; done) $(local_url_add_args "$p") 2>"$err")"
  else
    [ "$p" = "ollama" ] && [ -n "$models" ] && write_ollama_overrides "${models%% *}"
    out="$(models_cmd test "$p" --json 2>"$err")"
  fi
  key=""
  r="$(model_result "$out" "$err" "$p")"
  case "$r" in unknown:*) r="fail:${r#unknown:}"; [ "$p" = "local" ] && { set_result "$p" "$r"; stop_local_url_unanswered; } ;; esac
  [ "$r" = "fail:" ] && r="fail:onex models gave no result; see the log"
  rm -f "$err"
  if [ -z "$models" ] || [ "$p" = "local" ]; then set_result "$p" "$r"; return 0; fi
  first="${models%% *}"
  add_model_res "$p" "$first" "$r"
  case "$r" in pass:*) passed="$r" ;; esac
  # Each further chosen model gets its own delegation pinned to it: put it
  # first, test, then put the developer's order back.
  if [ "$models" != "$first" ] && { [ "$p" = "ollama" ] || [ -n "$(onex_order "$p")" ]; }; then
    for m in ${models#* }; do
      if put_first "$p" "$m" "$models"; then
        out="$(models_cmd test "$p" --json 2>"$err")"
        r="$(model_result "$out" "$err" "$p")"
        case "$r" in unknown:*|fail:) r="fail:${r#*:}"; [ "$r" = "fail:" ] && r="fail:onex models gave no result; see the log" ;; esac
      else
        r="fail:it could not be put first to test it; see the log"
      fi
      rm -f "$err"
      add_model_res "$p" "$m" "$r"
      [ -z "$passed" ] && case "$r" in pass:*) passed="$r" ;; esac
    done
    put_first "$p" "$first" "$models" || say "  ⚠ Your $(provider_label "$p") order could not be put back; set it with: onex models reorder $p $models"
  fi
  if [ "$p" != "ollama" ]; then
    held="$(onex_order "$p")"
    [ -n "$held" ] && say "  onex holds your $(provider_label "$p") models in this order: $(comma_list "$held")"
  fi
  set_result "$p" "${passed:-$(printf '%s' "$MODEL_RES" | grep "^$p|$first|" | head -n 1 | cut -d'|' -f3-)}"
}

# ---------------------------------------------------------------------------
# The anchor: which commit each clone is checked out at.
#
# lab-onboarding.sh names INFRA_ANCHOR, one omnibase_infra commit. omnibase_infra
# is checked out there; a sibling at the pin that commit's
# .github/sibling-pins.yaml names; a repo with no pin at the last commit of
# origin's default branch at or before the anchor's commit time.
# ---------------------------------------------------------------------------
proven_pin() { # repo -> the CI-proven commit, empty when the repo has no pin
  local pins="$WORKSPACE/omnibase_infra/.github/sibling-pins.yaml"
  [ -f "$pins" ] || return 0
  sed -n "/^pins:[[:space:]]*$/,/^[^[:space:]]/s/^  $1: \([0-9a-fA-F]\{40\}\)[[:space:]]*$/\1/p" "$pins"
}

anchor_time() { # -> the anchor's committer date, ISO 8601
  git -C "$WORKSPACE/omnibase_infra" show -s --format=%cI "$INFRA_ANCHOR" 2>/dev/null
}

# anchored_commit repo -> the commit this setup installs for the repo. It reads
# the pins file in the working tree, so omnibase_infra is checked out first.
anchored_commit() { # repo
  local pin def when
  [ "$1" = omnibase_infra ] && { printf '%s\n' "$INFRA_ANCHOR"; return 0; }
  pin="$(proven_pin "$1")" || return 1
  [ -n "$pin" ] && { printf '%s\n' "$pin"; return 0; }
  def="$(clone_default_branch "$1")"
  when="$(anchor_time)"
  [ -n "$def" ] && [ -n "$when" ] || return 1
  git -C "$WORKSPACE/$1" rev-list -1 --first-parent --before="$when" "origin/$def"
}

checkout_anchored() { # repo commit
  local d="$WORKSPACE/$1" changes
  [ "$(git -C "$d" rev-parse HEAD)" = "$2" ] &&
    ! git -C "$d" symbolic-ref --quiet HEAD >/dev/null 2>&1 && return 0
  changes="$(git -C "$d" status --porcelain --untracked-files=no)" || return 1
  if [ -n "$changes" ]; then
    say "  $1: clone has uncommitted changes; cannot check out its anchored commit"
    return 1
  fi
  if ! git -C "$d" cat-file -e "$2^{commit}" 2>/dev/null; then
    git -C "$d" fetch --quiet origin "$2" 2>/dev/null || git -C "$d" fetch --quiet origin || return 1
    git -C "$d" cat-file -e "$2^{commit}" 2>/dev/null || return 1
  fi
  git -C "$d" checkout --quiet --detach "$2"
}

clone_at_anchor() { # repo
  local want
  want="$(anchored_commit "$1")" && [ -n "$want" ] || return 1
  [ "$(git -C "$WORKSPACE/$1" rev-parse HEAD)" = "$want" ]
}

# The delegation routing overlay this setup declares. Its one entry is the tier
# your own provider keys answer on, right after a local model and before every
# platform rung. Unbound, the overlay is empty: a registered key then joins no
# tier, and a delegation with no pin can be refused on a machine that holds only
# keys. It names no model, key or address; the keys come from `onex secret set`.
# A file this setup did not write is the developer's own: kept, named, still bound.
ROUTING_OVERLAY_FILE="$HOME/.omninode/delegation/routing_overlay.yaml"
ROUTING_OVERLAY_MARK="# Written by omninode-dev-setup: the tier your own keys answer on."

write_routing_overlay() {
  local f="$ROUTING_OVERLAY_FILE"
  if [ -f "$f" ] && ! head -n 1 "$f" | grep -qxF "$ROUTING_OVERLAY_MARK"; then
    say "  $f is your own; it is left as it is and used."
    return 0
  fi
  mkdir -p "$(dirname "$f")" || return 1
  cat >"$f" <<YAML
$ROUTING_OVERLAY_MARK
schema_version: delegation_routing_overlay.v1
registered_byok_tier:
  name: registered_keys
  after_tier: local
  cost_per_1k_tokens: 0.0
YAML
}

# Phase 2 is redone on a machine set up before the overlay existed.
routing_overlay_in_place() {
  [ -f "$ROUTING_OVERLAY_FILE" ] &&
    grep -qF "DELEGATION_ROUTING_OVERLAY_PATH" "$HOME/.zshrc" 2>/dev/null
}

# The finish sound (OMN-21309): plays on every completed run on macOS, over
# ssh too (afplay plays on the Mac's own audio output, so a VM walk hears it).
# The recorded clips come from omnibase at a pinned commit, checked by sha256;
# the name between them is the macOS account's first name, else the home
# folder's name when it reads as one, else the clip plays without a name. It
# never asks and never fails the run. ONBOARD_FINISH_SOUND=0 turns it off.
FINISH_CLIP_BASE="https://raw.githubusercontent.com/OmniNode-ai/omnibase/e8686dabd47179bc5a9dd82a92c8e686683eec94/assets/finish"
FINISH_CLIP_DIGESTS="welcome:099b47c4ab8513a145b567542c5f39b4e17185c4021b9c3026d98660744a0fd0 to-omninode:2173614dc1e34c37f80096f92172327be8f7afd454bcf3f3919655b327fcf2bb"

finish_name_like() {
  case "$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]')" in
    ""|admin|administrator|user|users|mac|macbook|macuser|test|guest|root|dev|developer|owner|me|home|runner|ci|build|staff|default|shared|tart|vagrant|ubuntu) return 1 ;;
  esac
  printf '%s' "$1" | grep -Eq "^[A-Za-z][A-Za-z'-]{1,19}$"
}

finish_sound() {
  [ "${ONBOARD_FINISH_SOUND:-1}" = "0" ] && return 0
  [ "$(os_name)" = "Darwin" ] || return 0
  [ -n "$(type -P afplay)" ] || return 0
  local work entry clip name="" parts=() sayb
  sayb="$(type -P say)"   # the binary: say() above is this script's printer
  work="$(mktemp -d)" || return 0
  for entry in $FINISH_CLIP_DIGESTS; do
    clip="${entry%%:*}"
    curl -fsSL --retry 2 -o "$work/$clip.wav" "$FINISH_CLIP_BASE/$clip.wav" 2>/dev/null &&
      printf '%s  %s\n' "${entry#*:}" "$work/$clip.wav" | shasum -a 256 -c - >/dev/null 2>&1 ||
      { log "finish sound: could not fetch $clip.wav"; rm -rf "$work"; return 0; }
  done
  name="$(id -F 2>/dev/null | awk '{print $1}')"
  finish_name_like "$name" || name="$(basename "$HOME")"
  finish_name_like "$name" || name=""
  parts=("$work/welcome.wav")
  if [ -n "$name" ] && [ -n "$sayb" ]; then
    name="$(printf '%s%s' "$(printf '%s' "${name:0:1}" | tr '[:lower:]' '[:upper:]')" "${name:1}")"
    "$sayb" -v Fred --file-format=WAVE --data-format=LEI16@22050 -o "$work/name.wav" "$name" 2>/dev/null &&
      parts+=("$work/name.wav")
  fi
  parts+=("$work/to-omninode.wav")
  # One joined clip plays without the second of silence each afplay adds.
  if python3 - "${parts[@]}" "$work/finish.wav" >/dev/null 2>&1 <<'PY2'
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
PY2
  then
    afplay "$work/finish.wav" 2>/dev/null || true
  else
    for clip in "${parts[@]}"; do afplay "$clip" 2>/dev/null || true; done
  fi
  rm -rf "$work"
}
