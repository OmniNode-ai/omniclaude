#!/bin/bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# ONEX Status Line - 3-line layout:
#   Line 1: Repo context + model + token usage + thinking status
#   Line 2: Rate limit usage bars (current period / weekly / extra billing)
#   Line 3: Tab bar of all active Claude Code sessions
#
# This script reads JSON from stdin (provided by Claude Code) and always
# emits exactly 3 lines. It never blocks Claude Code, even if external
# commands fail. No set -e.

set -f  # disable globbing

###############################################################################
# Section A: Preamble — colors, constants, fallbacks, tool detection
###############################################################################

RESET=$'\033[0m'
GREEN=$'\033[32m'
YELLOW=$'\033[33m'
DIM=$'\033[2m'
CYAN=$'\033[36m'
WHITE=$'\033[97m'
RED=$'\033[31m'
GRAY=$'\033[90m'
SEP=" ${DIM}|${RESET} "

# Fallbacks — always set before any work so we can exit safely at any point
LINE1="[unknown] | Claude | 0 / 200k | 0% used 0 | 100% remain 200,000 | thinking: ?${RESET}"
LINE2="current: ? | weekly: ? | extra: ?${RESET}"
LINE3="(no tabs)${RESET}"

NOW=$(date +%s)

# Tool detection
HAS_JQ=0; command -v jq >/dev/null 2>&1 && HAS_JQ=1
HAS_CURL=0; command -v curl >/dev/null 2>&1 && HAS_CURL=1
HAS_GIT=0; command -v git >/dev/null 2>&1 && HAS_GIT=1

# Read stdin (Claude Code JSON)
INPUT=$(cat)

###############################################################################
# Section B: Line 1 — repo context + model + tokens + thinking
###############################################################################

if [ "$HAS_JQ" -eq 1 ]; then
  PROJECT_DIR=$(printf '%s' "$INPUT" | jq -r '.workspace.project_dir // .workspace.current_dir // "."' 2>/dev/null) || PROJECT_DIR="."
  FOLDER_NAME=$(basename "$PROJECT_DIR" 2>/dev/null) || FOLDER_NAME="unknown"

  # Git info
  GIT_BRANCH=""
  DIRTY=""
  UNPUSHED=""
  if [ "$HAS_GIT" -eq 1 ] && git -C "$PROJECT_DIR" rev-parse --git-dir >/dev/null 2>&1; then
    GIT_BRANCH=$(git -C "$PROJECT_DIR" branch --show-current 2>/dev/null)
    [ -z "$GIT_BRANCH" ] && GIT_BRANCH=$(git -C "$PROJECT_DIR" rev-parse --short HEAD 2>/dev/null)

    if [ -n "$(git -C "$PROJECT_DIR" status --porcelain 2>/dev/null)" ]; then
      DIRTY=" ${YELLOW}●${RESET}"
    fi

    if [ -n "$GIT_BRANCH" ]; then
      AHEAD=$(git -C "$PROJECT_DIR" rev-list --count "@{upstream}..HEAD" 2>/dev/null)
      if [ -n "$AHEAD" ] && [ "$AHEAD" -gt 0 ] 2>/dev/null; then
        UNPUSHED=" ${RED}↑${AHEAD}${RESET}"
      fi
    fi
  fi

  # Model info
  MODEL_ID=$(printf '%s' "$INPUT" | jq -r '.model.id // ""' 2>/dev/null) || MODEL_ID=""
  MODEL_DISPLAY=$(printf '%s' "$INPUT" | jq -r '.model.display_name // "Claude"' 2>/dev/null) || MODEL_DISPLAY="Claude"

  # Extract version from model.id: "claude-opus-4-6" -> "4.6", "claude-sonnet-4-5-20250514" -> "4.5"
  MODEL_VERSION=""
  if [ -n "$MODEL_ID" ]; then
    # Strip "claude-" prefix and known model family names, then take first two numbers
    MODEL_VERSION=$(printf '%s' "$MODEL_ID" | sed -E 's/^claude-[a-z]+-//; s/-[0-9]{8}$//; s/-/./g' | grep -oE '^[0-9]+\.[0-9]+' 2>/dev/null) || MODEL_VERSION=""
  fi
  if [ -n "$MODEL_VERSION" ]; then
    MODEL_LABEL="${MODEL_DISPLAY} ${MODEL_VERSION}"
  else
    MODEL_LABEL="${MODEL_DISPLAY}"
  fi

  # Token usage
  INPUT_TOKENS=$(printf '%s' "$INPUT" | jq -r '.context_window.current_usage.input_tokens // 0' 2>/dev/null) || INPUT_TOKENS=0
  CACHE_READ=$(printf '%s' "$INPUT" | jq -r '.context_window.current_usage.cache_read_input_tokens // 0' 2>/dev/null) || CACHE_READ=0
  CTX_SIZE=$(printf '%s' "$INPUT" | jq -r '.context_window.context_window_size // 200000' 2>/dev/null) || CTX_SIZE=200000
  USED_PCT=$(printf '%s' "$INPUT" | jq -r '.context_window.used_percentage // 0' 2>/dev/null) || USED_PCT=0
  REMAIN_PCT=$(printf '%s' "$INPUT" | jq -r '.context_window.remaining_percentage // 100' 2>/dev/null) || REMAIN_PCT=100

  # Compute used tokens = input_tokens + cache_read_input_tokens
  USED_TOKENS=$((INPUT_TOKENS + CACHE_READ))
  REMAIN_TOKENS=$((CTX_SIZE - USED_TOKENS))
  [ "$REMAIN_TOKENS" -lt 0 ] 2>/dev/null && REMAIN_TOKENS=0

  # Format with commas
  fmt_number() {
    printf "%'d" "$1" 2>/dev/null || printf "%d" "$1" 2>/dev/null
  }
  USED_FMT=$(fmt_number "$USED_TOKENS")
  REMAIN_FMT=$(fmt_number "$REMAIN_TOKENS")
  CTX_K=$((CTX_SIZE / 1000))
  CTX_LABEL="${CTX_K}k"

  # Thinking status
  THINKING="Off"
  if printf '%s' "$MODEL_ID" | grep -qi "thinking" 2>/dev/null; then
    THINKING="On"
  fi

  # Build Line 1
  if [ -n "$GIT_BRANCH" ]; then
    L1_REPO="[${CYAN}${FOLDER_NAME}${RESET}] ${GREEN}${GIT_BRANCH}${RESET}${DIRTY}${UNPUSHED}"
  else
    L1_REPO="[${CYAN}${FOLDER_NAME}${RESET}]"
  fi

  LINE1="${L1_REPO}${SEP}${WHITE}${MODEL_LABEL}${RESET}${SEP}${USED_FMT} / ${CTX_LABEL}${SEP}${USED_PCT}% used ${USED_FMT}${SEP}${REMAIN_PCT}% remain ${REMAIN_FMT}${SEP}thinking: ${THINKING}${RESET}"

else
  # No jq — minimal fallback
  PROJECT_DIR="."
  FOLDER_NAME="unknown"
  LINE1="[unknown] | Claude | 0 / 200k | 0% used 0 | 100% remain 200,000 | thinking: ?${RESET}"
fi

###############################################################################
# Section C: Line 2 — OAuth token fetch, cache management, usage bars
###############################################################################

USAGE_CACHE="/tmp/omniclaude-usage-cache.json"
USAGE_API_URL="${CLAUDE_USAGE_API_URL:-https://api.anthropic.com/v1/usage}"

# Build a progress bar: filled dots + empty dots, 10 chars wide
# Usage: build_bar <percentage>
build_bar() {
  local pct="${1:-0}"
  # Clamp to 0-100
  [ "$pct" -lt 0 ] 2>/dev/null && pct=0
  [ "$pct" -gt 100 ] 2>/dev/null && pct=100
  local filled=$(( (pct + 5) / 10 ))  # round to nearest 10%
  [ "$pct" -gt 0 ] && [ "$filled" -lt 1 ] && filled=1
  [ "$filled" -gt 10 ] && filled=10
  local empty=$((10 - filled))
  local bar=""
  local i
  for ((i=0; i<filled; i++)); do bar="${bar}●"; done
  for ((i=0; i<empty; i++)); do bar="${bar}○"; done
  printf '%s' "$bar"
}

if [ "$HAS_JQ" -eq 1 ]; then
  # Try to get OAuth token from macOS Keychain
  OAUTH_TOKEN=""
  if [ "$(uname)" = "Darwin" ]; then
    KEYCHAIN_JSON=$(security find-generic-password -s "Claude Code-credentials" -a "$(whoami)" -w 2>/dev/null) || KEYCHAIN_JSON=""
    if [ -n "$KEYCHAIN_JSON" ]; then
      OAUTH_TOKEN=$(printf '%s' "$KEYCHAIN_JSON" | jq -r '.claudeAiOauth.accessToken // empty' 2>/dev/null) || OAUTH_TOKEN=""
    fi
  fi

  # Cache management: check staleness
  CACHE_FRESH=0
  CACHE_DATA=""
  if [ -f "$USAGE_CACHE" ]; then
    CACHE_MTIME=$(stat -f %m "$USAGE_CACHE" 2>/dev/null || stat -c %Y "$USAGE_CACHE" 2>/dev/null || echo "0")
    if [ -n "$CACHE_MTIME" ] && [[ "$CACHE_MTIME" =~ ^[0-9]+$ ]]; then
      CACHE_AGE=$((NOW - CACHE_MTIME))
      if [ "$CACHE_AGE" -le 60 ] 2>/dev/null; then
        CACHE_FRESH=1
      fi
    fi
    CACHE_DATA=$(cat "$USAGE_CACHE" 2>/dev/null) || CACHE_DATA=""
  fi

  # Attempt API refresh if cache is stale and we have a token + curl
  if [ "$CACHE_FRESH" -eq 0 ] && [ -n "$OAUTH_TOKEN" ] && [ "$HAS_CURL" -eq 1 ]; then
    API_RESPONSE=$(curl -s --connect-timeout 1 --max-time 2 \
      -H "Authorization: Bearer ${OAUTH_TOKEN}" \
      -H "Content-Type: application/json" \
      "${USAGE_API_URL}" 2>/dev/null) || API_RESPONSE=""

    # Validate response is JSON with expected structure
    if [ -n "$API_RESPONSE" ]; then
      VALID=$(printf '%s' "$API_RESPONSE" | jq -e 'type == "object"' 2>/dev/null) || VALID=""
      if [ "$VALID" = "true" ]; then
        # Atomic write: temp file then mv
        CACHE_TMP="${USAGE_CACHE}.tmp.$$"
        printf '%s' "$API_RESPONSE" > "$CACHE_TMP" 2>/dev/null && \
          mv -f "$CACHE_TMP" "$USAGE_CACHE" 2>/dev/null
        CACHE_DATA="$API_RESPONSE"
        CACHE_FRESH=1
      fi
    fi
  fi

  # Parse cached data to extract usage metrics
  CURRENT_PCT=""
  CURRENT_RESET=""
  WEEKLY_PCT=""
  WEEKLY_RESET=""
  EXTRA_USED=""
  EXTRA_LIMIT=""
  EXTRA_RESET=""

  if [ -n "$CACHE_DATA" ]; then
    # Try known field names — the exact schema is TBD, so we try common patterns
    CURRENT_PCT=$(printf '%s' "$CACHE_DATA" | jq -r '
      .current_period.usage_percentage //
      .current.percentage //
      .currentPeriod.usagePercentage //
      empty' 2>/dev/null) || CURRENT_PCT=""

    CURRENT_RESET=$(printf '%s' "$CACHE_DATA" | jq -r '
      .current_period.reset_time //
      .current.resetTime //
      .currentPeriod.resetTime //
      .current_period.resets_at //
      empty' 2>/dev/null) || CURRENT_RESET=""

    WEEKLY_PCT=$(printf '%s' "$CACHE_DATA" | jq -r '
      .weekly.usage_percentage //
      .weekly.percentage //
      .weekly.usagePercentage //
      empty' 2>/dev/null) || WEEKLY_PCT=""

    WEEKLY_RESET=$(printf '%s' "$CACHE_DATA" | jq -r '
      .weekly.reset_time //
      .weekly.resetTime //
      .weekly.resets_at //
      empty' 2>/dev/null) || WEEKLY_RESET=""

    EXTRA_USED=$(printf '%s' "$CACHE_DATA" | jq -r '
      .extra.used //
      .extra.amount_used //
      .extra.amountUsed //
      .extraBilling.used //
      empty' 2>/dev/null) || EXTRA_USED=""

    EXTRA_LIMIT=$(printf '%s' "$CACHE_DATA" | jq -r '
      .extra.limit //
      .extra.amount_limit //
      .extra.amountLimit //
      .extraBilling.limit //
      empty' 2>/dev/null) || EXTRA_LIMIT=""

    EXTRA_RESET=$(printf '%s' "$CACHE_DATA" | jq -r '
      .extra.reset_time //
      .extra.resetTime //
      .extra.resets_at //
      .extraBilling.resetTime //
      empty' 2>/dev/null) || EXTRA_RESET=""
  fi

  # Format reset times: try to make them human-readable
  # Input could be ISO 8601, epoch, or already formatted
  format_reset() {
    local raw="$1"
    [ -z "$raw" ] && return
    # If it's an epoch number, convert
    if [[ "$raw" =~ ^[0-9]+$ ]]; then
      if [ "$(uname)" = "Darwin" ]; then
        date -r "$raw" "+%-I:%M%p" 2>/dev/null | tr '[:upper:]' '[:lower:]'
      else
        date -d "@$raw" "+%-I:%M%p" 2>/dev/null | tr '[:upper:]' '[:lower:]'
      fi
      return
    fi
    # If ISO 8601 (e.g. 2026-03-04T11:00:00Z), try to parse
    if printf '%s' "$raw" | grep -qE '^[0-9]{4}-[0-9]{2}-[0-9]{2}T' 2>/dev/null; then
      if [ "$(uname)" = "Darwin" ]; then
        date -jf "%Y-%m-%dT%H:%M:%S" "$(printf '%s' "$raw" | sed 's/Z$//' | sed 's/[+-][0-9][0-9]:[0-9][0-9]$//')" "+%b %-d, %-I:%M%p" 2>/dev/null | tr '[:upper:]' '[:lower:]'
      else
        date -d "$raw" "+%b %-d, %-I:%M%p" 2>/dev/null | tr '[:upper:]' '[:lower:]'
      fi
      return
    fi
    # Already formatted or unknown — pass through
    printf '%s' "$raw"
  }

  # Build Line 2
  # Current period
  if [ -n "$CURRENT_PCT" ] && [[ "$CURRENT_PCT" =~ ^[0-9]+$ ]]; then
    CURRENT_BAR=$(build_bar "$CURRENT_PCT")
    CURRENT_RESET_FMT=$(format_reset "$CURRENT_RESET")
    L2_CURRENT="current: ${CURRENT_BAR} ${CURRENT_PCT}%"
    [ -n "$CURRENT_RESET_FMT" ] && L2_CURRENT="${L2_CURRENT} resets ${CURRENT_RESET_FMT}"
  else
    L2_CURRENT="current: ?"
  fi

  # Weekly
  if [ -n "$WEEKLY_PCT" ] && [[ "$WEEKLY_PCT" =~ ^[0-9]+$ ]]; then
    WEEKLY_BAR=$(build_bar "$WEEKLY_PCT")
    WEEKLY_RESET_FMT=$(format_reset "$WEEKLY_RESET")
    L2_WEEKLY="weekly: ${WEEKLY_BAR} ${WEEKLY_PCT}%"
    [ -n "$WEEKLY_RESET_FMT" ] && L2_WEEKLY="${L2_WEEKLY} resets ${WEEKLY_RESET_FMT}"
  else
    L2_WEEKLY="weekly: ?"
  fi

  # Extra billing
  if [ -n "$EXTRA_USED" ] && [ -n "$EXTRA_LIMIT" ]; then
    # Calculate percentage for bar
    EXTRA_PCT=0
    if [[ "$EXTRA_LIMIT" =~ ^[0-9]+\.?[0-9]*$ ]] && [ "$(printf '%s' "$EXTRA_LIMIT" | awk '{printf "%d", $1 * 100}')" -gt 0 ] 2>/dev/null; then
      EXTRA_PCT=$(awk "BEGIN { printf \"%.0f\", (${EXTRA_USED} / ${EXTRA_LIMIT}) * 100 }" 2>/dev/null) || EXTRA_PCT=0
    fi
    EXTRA_BAR=$(build_bar "$EXTRA_PCT")
    EXTRA_RESET_FMT=$(format_reset "$EXTRA_RESET")
    # Format as currency if numeric
    if [[ "$EXTRA_USED" =~ ^[0-9]+\.?[0-9]*$ ]]; then
      EXTRA_USED_FMT=$(printf '$%.2f' "$EXTRA_USED" 2>/dev/null) || EXTRA_USED_FMT="\$${EXTRA_USED}"
    else
      EXTRA_USED_FMT="${EXTRA_USED}"
    fi
    if [[ "$EXTRA_LIMIT" =~ ^[0-9]+\.?[0-9]*$ ]]; then
      EXTRA_LIMIT_FMT=$(printf '$%.2f' "$EXTRA_LIMIT" 2>/dev/null) || EXTRA_LIMIT_FMT="\$${EXTRA_LIMIT}"
    else
      EXTRA_LIMIT_FMT="${EXTRA_LIMIT}"
    fi
    L2_EXTRA="extra: ${EXTRA_BAR} ${EXTRA_USED_FMT}/${EXTRA_LIMIT_FMT}"
    [ -n "$EXTRA_RESET_FMT" ] && L2_EXTRA="${L2_EXTRA} resets ${EXTRA_RESET_FMT}"
  else
    L2_EXTRA="extra: ?"
  fi

  LINE2="${L2_CURRENT} | ${L2_WEEKLY} | ${L2_EXTRA}${RESET}"

fi  # HAS_JQ for Section C

###############################################################################
# Section D: Line 3 — Tab bar (from current statusline, stable/tested)
###############################################################################

TAB_REGISTRY_DIR="/tmp/omniclaude-tabs"

if [ "$HAS_JQ" -eq 1 ]; then
  mkdir -p "$TAB_REGISTRY_DIR" 2>/dev/null

  # Determine current tab's iTerm GUID for highlighting
  # ITERM_SESSION_ID format: w{W}t{T}p{P}:{GUID} - extract just the GUID
  CURRENT_ITERM=""
  if [ -n "${ITERM_SESSION_ID:-}" ]; then
    CURRENT_ITERM="${ITERM_SESSION_ID#*:}"  # Strip prefix up to colon = GUID only
  fi

  # Query live tab positions from iTerm2 via single AppleScript call.
  # Returns "pos|GUID" per line. Used to:
  #   1. Show current visual positions (not stale registration-time positions)
  #   2. Filter out entries for closed tabs (GUID has no live match)
  LIVE_POSITIONS=""
  if [ "$(uname)" = "Darwin" ] && command -v osascript >/dev/null 2>&1; then
    LIVE_POSITIONS=$(osascript 2>/dev/null <<'APPLESCRIPT'
tell application "iTerm2"
    tell current window
        set output to ""
        repeat with i from 1 to count of tabs
            tell tab i
                repeat with s in sessions
                    set uid to unique ID of s
                    set output to output & i & "|" & uid & linefeed
                end repeat
            end tell
        end repeat
        return output
    end tell
end tell
APPLESCRIPT
    ) || LIVE_POSITIONS=""
  fi

  # Self-register/update: ensure this tab's registry entry matches the current project.
  # Handles: new sessions, resumed sessions, same tab switching repos.
  # Keyed by GUID so each iTerm tab has exactly one entry.
  if [ -n "$CURRENT_ITERM" ]; then
    NEEDS_UPDATE=0
    EXISTING=$(grep -rl "$CURRENT_ITERM" "$TAB_REGISTRY_DIR"/ 2>/dev/null | head -1)
    if [ -z "$EXISTING" ]; then
      NEEDS_UPDATE=1
    elif [ -n "$FOLDER_NAME" ]; then
      # Check if repo changed (same tab, different session)
      EXISTING_REPO=$(jq -r '.repo // ""' "$EXISTING" 2>/dev/null)
      [ "$EXISTING_REPO" != "$FOLDER_NAME" ] && NEEDS_UPDATE=1
    fi
    if [ "$NEEDS_UPDATE" -eq 1 ]; then
      # Remove old entry for this GUID if it exists under a different session ID
      [ -n "$EXISTING" ] && rm -f "$EXISTING" 2>/dev/null
      ( "$HOME/.claude/register-tab.sh" "auto-${CURRENT_ITERM}" "$PROJECT_DIR" >/dev/null 2>&1 ) &
    elif [ -n "$EXISTING" ]; then
      # Keep mtime fresh to prevent staleness eviction
      touch "$EXISTING" 2>/dev/null
    fi
  fi

  # Stale threshold: skip entries older than 24 hours (86400 seconds)
  # Only applied when live position data is unavailable (non-macOS/non-iTerm).
  # When live data IS available, GUID matching filters dead entries instead.
  STALE_THRESHOLD=$((NOW - 86400))

  # Read all registry files, parse with single jq invocation
  # Output: tab_pos|repo|ticket|iterm_guid|project_path (one per line, sorted by tab_pos)
  ENTRIES=""
  for f in "$TAB_REGISTRY_DIR"/*.json; do
    [ -f "$f" ] || continue
    # Skip stale files only when we lack live position data to verify liveness
    if [ -z "$LIVE_POSITIONS" ]; then
      FILE_MTIME=$(stat -f %m "$f" 2>/dev/null || stat -c %Y "$f" 2>/dev/null || echo "0")
      [ "$FILE_MTIME" -lt "$STALE_THRESHOLD" ] && continue
    fi
    ENTRIES="${ENTRIES}$(cat "$f" 2>/dev/null)
"
  done

  TAB_LINE=""
  if [ -n "$ENTRIES" ]; then
    # Single jq call: parse all entries, sort by tab_pos, output pipe-delimited
    # Includes project_path so we can read live branch from git
    FORMATTED=$(echo "$ENTRIES" | jq -sr '
      [.[] | select(.repo != null)] |
      sort_by(.tab_pos // 999) |
      .[] | "\(.tab_pos // "?")|\(.repo // "?")|\(.ticket // "-")|\(.iterm_guid // "-")|\(.project_path // "-")"
    ' 2>/dev/null)

    if [ -n "$FORMATTED" ]; then
      # Apply live tab positions and filter closed tabs BEFORE rendering.
      # This ensures correct sort order after tab moves.
      if [ -n "$LIVE_POSITIONS" ]; then
        RESOLVED=""
        while IFS='|' read -r tab_pos repo ticket iterm_guid project_path; do
          [ -z "$tab_pos" ] && continue
          entry_guid="${iterm_guid#*:}"
          live_pos=$(echo "$LIVE_POSITIONS" | grep -F "$entry_guid" | head -1 | cut -d'|' -f1)
          if [ -n "$live_pos" ]; then
            RESOLVED="${RESOLVED}${live_pos}|${repo}|${ticket}|${iterm_guid}|${project_path}
"
          fi
          # No live match -> tab closed since registration, skip
        done <<< "$FORMATTED"
        FORMATTED=$(echo "$RESOLVED" | sort -t'|' -k1 -n)
      fi

      # Pre-scan: detect tabs sharing the same WORKTREE (collision warning)
      # Only flag paths under omni_worktrees -- multiple tabs in omni_home is expected.
      DUPE_PATHS=""
      _paths=$(echo "$FORMATTED" | awk -F'|' '$5 != "" && $5 != "-" && $5 ~ /omni_worktrees/ {print $5}' | sort)
      [ -n "$_paths" ] && DUPE_PATHS=$(echo "$_paths" | uniq -d)

      # Pre-scan: detect same (ticket + mode) pair across multiple tabs -- true collision.
      # Same ticket in different modes (e.g. planning vs pr-review) is intentional, not a dupe.
      DUPE_TICKET_MODES=""
      _ticket_mode_pairs=""
      while IFS='|' read -r _p _r _tkt _guid _path; do
        [ -z "$_p" ] && continue
        [ "$_tkt" = "-" ] && continue; [ -z "$_tkt" ] && continue
        _eg="${_guid#*:}"
        _mf="${TAB_REGISTRY_DIR}/${_eg}.mode"
        _m=""; [ -f "$_mf" ] && _m=$(cat "$_mf" 2>/dev/null | tr -d '\n\r\t')
        [ -z "$_m" ] && continue
        _ticket_mode_pairs="${_ticket_mode_pairs}${_tkt}|${_m}"$'\n'
      done <<< "$FORMATTED"
      [ -n "$_ticket_mode_pairs" ] && DUPE_TICKET_MODES=$(printf '%s' "$_ticket_mode_pairs" | sort | uniq -d)

      TAB_NUM=0
      while IFS='|' read -r tab_pos repo ticket iterm_guid project_path; do
        [ -z "$tab_pos" ] && continue
        TAB_NUM=$((TAB_NUM + 1))
        [ "$TAB_NUM" -gt 1 ] && TAB_LINE="${TAB_LINE}${GRAY}|  ${RESET}"
        # Convert placeholders back to empty
        [ "$ticket" = "-" ] && ticket=""
        [ "$iterm_guid" = "-" ] && iterm_guid=""
        [ "$project_path" = "-" ] && project_path=""

        # Normalize GUID: strip "w{W}t{T}p{P}:" prefix if present
        entry_guid="${iterm_guid#*:}"

        # Read live branch from git if project_path is available (keeps ticket current after merges)
        if [ -n "$project_path" ] && [ -d "$project_path" ]; then
          live_branch=$(git -C "$project_path" branch --show-current 2>/dev/null || echo "")
          if [ -n "$live_branch" ]; then
            # Match known Linear team prefixes (add new prefixes here as teams are created)
            ticket=$(echo "$live_branch" | grep -oiE '(omn|eng|dev|inf|ops|dash)-[0-9]+' | head -1 | tr '[:lower:]' '[:upper:]')
          fi
        fi

        # Read .mode file (written by post-tool-use hook on Skill calls)
        mode=""
        mode_file="${TAB_REGISTRY_DIR}/${entry_guid}.mode"
        [ -f "$mode_file" ] && mode=$(cat "$mode_file" 2>/dev/null | tr -d '\n\r\t')

        # Read .ticket file (written by session-start for omni_home tabs without a git branch)
        if [ -z "$ticket" ] && [ -n "$entry_guid" ]; then
          ticket_file="${TAB_REGISTRY_DIR}/${entry_guid}.ticket"
          [ -f "$ticket_file" ] && ticket=$(cat "$ticket_file" 2>/dev/null | tr -d '\n\r\t')
        fi

        # Read tab activity color (ANSI 256-color code written by hooks)
        activity_color=""
        activity_file="${TAB_REGISTRY_DIR}/${entry_guid}.activity"
        if [ -f "$activity_file" ]; then
          activity_color=$(cat "$activity_file" 2>/dev/null | tr -d '[:cntrl:][:space:]')
          # Validate: must be a number (ANSI 256-color code)
          [[ "$activity_color" =~ ^[0-9]+$ ]] || activity_color=""
        fi

        # Build label: T{n}·{ticket|repo}[·{mode}]
        # mode present  -> show ticket (or repo fallback) + mode; branch is dropped (mode is more useful)
        # no mode       -> fall back to repo[·ticket] (legacy behavior for tabs with no skill history)
        if [ -n "$mode" ]; then
          if [ -n "$ticket" ]; then
            label="T${TAB_NUM}·${ticket}·${mode}"
          else
            label="T${TAB_NUM}·${repo}·${mode}"
          fi
        else
          label="T${TAB_NUM}·${repo}"
          [ -n "$ticket" ] && label="${label}·${ticket}"
        fi

        # Collision detection: same project_path OR same (ticket + mode) pair.
        # Same ticket in different modes = intentional parallel work, no warning.
        is_dupe=0
        if [ -n "$DUPE_PATHS" ] && [ -n "$project_path" ] && [ "$project_path" != "-" ]; then
          echo "$DUPE_PATHS" | grep -qxF "$project_path" && is_dupe=1
        fi
        if [ "$is_dupe" -eq 0 ] && [ -n "$DUPE_TICKET_MODES" ] && [ -n "$ticket" ] && [ -n "$mode" ]; then
          echo "$DUPE_TICKET_MODES" | grep -qxF "${ticket}|${mode}" && is_dupe=1
        fi

        # Activity indicator: colored dot per-skill (color from activity file)
        activity_dot=""
        [ -n "$activity_color" ] && activity_dot="\033[38;5;${activity_color}m●\033[0m"

        # Highlight current tab (match by iTerm GUID)
        if [ -n "$CURRENT_ITERM" ] && [ "$entry_guid" = "$CURRENT_ITERM" ]; then
          if [ "$is_dupe" -eq 1 ]; then
            # DUPLICATE FOLDER: bright white on red bg -- unmissable collision warning
            TAB_LINE="${TAB_LINE}\033[97;41m !! ${label} \033[0m${activity_dot} "
          else
            # Current tab: black text on cyan background
            TAB_LINE="${TAB_LINE}\033[30;46m ${label} \033[0m${activity_dot} "
          fi
        else
          if [ "$is_dupe" -eq 1 ]; then
            # DUPLICATE FOLDER: bright red text -- collision warning
            TAB_LINE="${TAB_LINE}\033[91m!! ${label}\033[0m${activity_dot} "
          else
            # Other tabs: white text
            TAB_LINE="${TAB_LINE}\033[37m${label}\033[0m${activity_dot} "
          fi
        fi
      done <<< "$FORMATTED"
    fi
  fi

  [ -n "$TAB_LINE" ] && LINE3="${TAB_LINE}${RESET}" || LINE3="(no tabs)${RESET}"
fi  # HAS_JQ for Section D

###############################################################################
# Section E: Output — always exactly 3 lines
###############################################################################

printf '%b\n' "$LINE1" "$LINE2" "$LINE3"
exit 0
