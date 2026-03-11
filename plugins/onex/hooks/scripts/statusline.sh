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

  # display_name already contains the full label (e.g. "Opus 4.6"), no need to append version
  MODEL_LABEL="${MODEL_DISPLAY}"

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

  # Color the usage stats
  if [ "$USED_PCT" -ge 90 ] 2>/dev/null; then
    USED_COLOR="${RED}"
  elif [ "$USED_PCT" -ge 70 ] 2>/dev/null; then
    USED_COLOR="${YELLOW}"
  else
    USED_COLOR="${GREEN}"
  fi

  THINKING_COLOR="${DIM}"
  [ "$THINKING" = "On" ] && THINKING_COLOR="${YELLOW}"

  LINE1="${L1_REPO}${SEP}${CYAN}${MODEL_LABEL}${RESET}${SEP}${USED_COLOR}${USED_FMT} / ${CTX_LABEL}${RESET}${SEP}${USED_COLOR}${USED_PCT}% used${RESET} ${YELLOW}${USED_FMT}${RESET}${SEP}${GREEN}${REMAIN_PCT}% remain${RESET} ${CYAN}${REMAIN_FMT}${RESET}${SEP}thinking: ${THINKING_COLOR}${THINKING}${RESET}"

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
USAGE_API_URL="${CLAUDE_USAGE_API_URL:-https://api.anthropic.com/api/oauth/usage}"

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

  # Color based on usage level
  local bar_color
  if [ "$pct" -ge 90 ]; then bar_color="$RED"
  elif [ "$pct" -ge 70 ]; then bar_color="$YELLOW"
  elif [ "$pct" -ge 50 ]; then bar_color="$YELLOW"
  else bar_color="$GREEN"
  fi

  local filled_str="" empty_str=""
  local i
  for ((i=0; i<filled; i++)); do filled_str="${filled_str}●"; done
  for ((i=0; i<empty; i++)); do empty_str="${empty_str}○"; done
  printf '%s' "${bar_color}${filled_str}${DIM}${empty_str}${RESET}"
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
    API_RESPONSE=$(curl -s --connect-timeout 2 --max-time 5 \
      -H "Accept: application/json" \
      -H "Content-Type: application/json" \
      -H "Authorization: Bearer ${OAUTH_TOKEN}" \
      -H "anthropic-beta: oauth-2025-04-20" \
      -H "User-Agent: claude-code/2.1.34" \
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
    # API response uses: five_hour.utilization, seven_day.utilization, extra_usage.*
    CURRENT_PCT=$(printf '%s' "$CACHE_DATA" | jq -r '
      .five_hour.utilization //
      .current_period.usage_percentage //
      empty' 2>/dev/null | awk '{printf "%.0f", $1}') || CURRENT_PCT=""

    CURRENT_RESET=$(printf '%s' "$CACHE_DATA" | jq -r '
      .five_hour.resets_at //
      .current_period.resets_at //
      empty' 2>/dev/null) || CURRENT_RESET=""

    WEEKLY_PCT=$(printf '%s' "$CACHE_DATA" | jq -r '
      .seven_day.utilization //
      .weekly.usage_percentage //
      empty' 2>/dev/null | awk '{printf "%.0f", $1}') || WEEKLY_PCT=""

    WEEKLY_RESET=$(printf '%s' "$CACHE_DATA" | jq -r '
      .seven_day.resets_at //
      .weekly.resets_at //
      empty' 2>/dev/null) || WEEKLY_RESET=""

    EXTRA_ENABLED=$(printf '%s' "$CACHE_DATA" | jq -r '.extra_usage.is_enabled // false' 2>/dev/null) || EXTRA_ENABLED="false"

    if [ "$EXTRA_ENABLED" = "true" ]; then
      # Credits are in cents — convert to dollars
      EXTRA_USED=$(printf '%s' "$CACHE_DATA" | jq -r '.extra_usage.used_credits // 0' 2>/dev/null | awk '{printf "%.2f", $1/100}') || EXTRA_USED=""
      EXTRA_LIMIT=$(printf '%s' "$CACHE_DATA" | jq -r '.extra_usage.monthly_limit // 0' 2>/dev/null | awk '{printf "%.2f", $1/100}') || EXTRA_LIMIT=""
      EXTRA_PCT=$(printf '%s' "$CACHE_DATA" | jq -r '.extra_usage.utilization // 0' 2>/dev/null | awk '{printf "%.0f", $1}') || EXTRA_PCT="0"
    else
      EXTRA_USED=""
      EXTRA_LIMIT=""
    fi
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
    # EXTRA_PCT already pre-computed from extra_usage.utilization (line ~245)
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
# Section D: Line 3 — Service health, bus status, open PRs
# NOTE: All probes are lightweight UI hints for local operator use.
# They are NOT authoritative deployment health semantics and must never
# block prompt flow or be treated as production health indicators.
###############################################################################

# tcp_up HOST PORT — 🟢 if TCP port open within 1s, 🔴 otherwise.
tcp_up() {
  local h="$1" p="$2" rc=1
  if command -v nc >/dev/null 2>&1; then
    nc -z -w 1 "$h" "$p" 2>/dev/null && rc=0
  else
    ( echo >/dev/tcp/"$h"/"$p" ) 2>/dev/null && rc=0
  fi
  [ $rc -eq 0 ] && printf '🟢' || printf '🔴'
}

# http_up URL — 🟢 for 2xx/3xx within 1s, 🔴 otherwise.
http_up() {
  local code
  code=$(curl -s -o /dev/null -w "%{http_code}" \
    --connect-timeout 0.5 --max-time 1 "$1" 2>/dev/null) || code="000"
  [[ "$code" =~ ^[23] ]] && printf '🟢' || printf '🔴'
}

# bus_status — bus:local | bus:cloud(🟢) | bus:cloud(🔴)
bus_status() {
  local bid="${BUS_ID:-local}"
  if [[ "$bid" == "cloud" ]]; then
    local dot; dot=$(tcp_up localhost 29092)  # cloud-bus-ok OMN-4620
    printf "bus:cloud(%s)" "$dot"
  else
    printf "bus:local"
  fi
}

LINE3=""

if [ "$HAS_JQ" -eq 1 ]; then
  # Run all probes in parallel — capture output via temp files
  _TMP_PG=$(mktemp) _TMP_RP=$(mktemp) _TMP_VK=$(mktemp)
  _TMP_RT=$(mktemp) _TMP_IN=$(mktemp) _TMP_PH=$(mktemp) _TMP_BUS=$(mktemp)

  ( tcp_up  localhost 5436  > "$_TMP_PG"  ) &
  ( tcp_up  localhost 19092 > "$_TMP_RP"  ) &
  ( tcp_up  localhost 16379 > "$_TMP_VK"  ) &
  ( http_up http://localhost:8085/health > "$_TMP_RT"  ) &
  ( http_up http://localhost:8053/health > "$_TMP_IN"  ) &
  ( tcp_up  localhost 6006  > "$_TMP_PH"  ) &
  ( bus_status             > "$_TMP_BUS" ) &
  wait

  PG_DOT=$(cat "$_TMP_PG");   RP_DOT=$(cat "$_TMP_RP"); VK_DOT=$(cat "$_TMP_VK")
  RT_DOT=$(cat "$_TMP_RT");   INTEL_DOT=$(cat "$_TMP_IN"); PHX_DOT=$(cat "$_TMP_PH")
  BUS_STR=$(cat "$_TMP_BUS")
  rm -f "$_TMP_PG" "$_TMP_RP" "$_TMP_VK" "$_TMP_RT" "$_TMP_IN" "$_TMP_PH" "$_TMP_BUS"

  # PR cache — populated in background (first run may be empty; subsequent runs use cache).
  # Cache is best-effort: stale/missing/invalid JSON must never break rendering.
  PR_CACHE="/tmp/omniclaude-pr-cache.json"
  PR_FRESH=0
  if [ -f "$PR_CACHE" ]; then
    PR_MTIME=$(stat -f %m "$PR_CACHE" 2>/dev/null || stat -c %Y "$PR_CACHE" 2>/dev/null || echo 0)
    PR_AGE=$((NOW - PR_MTIME))
    [ "$PR_AGE" -le 300 ] && PR_FRESH=1
  fi
  if [ "$PR_FRESH" -eq 0 ] && command -v gh >/dev/null 2>&1; then
    (
      result='{'
      first=1
      for pair in "core:omnibase_core" "infra:omnibase_infra" "spi:omnibase_spi" "claude:omniclaude" "node:omninode_infra"; do
        short="${pair%%:*}"; repo="${pair##*:}"
        cnt=$(gh pr list --repo "OmniNode-ai/${repo}" --state open --json number --jq 'length' 2>/dev/null || echo "0")
        [ "$first" -eq 1 ] || result="${result},"
        result="${result}\"${short}\":${cnt}"
        first=0
      done
      result="${result}}"
      printf '%s' "$result" > "$PR_CACHE" 2>/dev/null
    ) &
  fi

  PR_LINE=""
  if [ -f "$PR_CACHE" ]; then
    PR_DATA=$(cat "$PR_CACHE" 2>/dev/null) || PR_DATA='{}'
    # Guard against invalid JSON in cache file
    if ! printf '%s' "$PR_DATA" | jq empty 2>/dev/null; then
      PR_DATA='{}'
    fi
    PR_PARTS=""
    for short in core infra spi claude node; do
      cnt=$(printf '%s' "$PR_DATA" | jq -r ".${short} // 0" 2>/dev/null) || cnt=0
      [[ "$cnt" =~ ^[1-9] ]] && PR_PARTS="${PR_PARTS}${short}·${cnt} "
    done
    [ -n "$PR_PARTS" ] && PR_LINE="${SEP}${DIM}PRs:${RESET} ${PR_PARTS% }"
  fi

  SVC="${DIM}pg:${RESET}${PG_DOT} ${DIM}rp:${RESET}${RP_DOT} ${DIM}vk:${RESET}${VK_DOT} ${DIM}rt:${RESET}${RT_DOT} ${DIM}intel:${RESET}${INTEL_DOT} ${DIM}phx:${RESET}${PHX_DOT}"
  LINE3="${SVC}${SEP}${BUS_STR}${PR_LINE}${RESET}"
else
  # jq absent: render degraded line rather than bare "(no jq)"
  LINE3="(health unavailable: install jq)${RESET}"
fi  # HAS_JQ for Section D

###############################################################################
# Section E: Output — always exactly 3 lines
###############################################################################

printf '%b\n' "$LINE1" "$LINE2" "$LINE3"
exit 0
