#!/bin/bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# ONEX Status Line - Shows folder, git branch, dirty state, unpushed commits,
# and a tab bar of all active Claude Code sessions.
# Part of the onex plugin for Claude Code
#
# Note: This script intentionally continues on errors (no set -e) because
# status line display should never block Claude Code, even if git fails.

input=$(cat)
PROJECT_DIR=$(echo "$input" | jq -r '.workspace.project_dir // .workspace.current_dir // "."')
FOLDER_NAME=$(basename "$PROJECT_DIR")

# ANSI color variables and timestamp for ONEX statusline rows
green='\033[32m'
yellow='\033[33m'
dim='\033[2m'
reset='\033[0m'
cyan='\033[36m'
white='\033[97m'
blue='\033[34m'
sep="  \033[2m|\033[0m  "
now=$(date +%s)

# Get git info if in a repo
GIT_BRANCH=""
DIRTY=""
UNPUSHED=""
if git -C "$PROJECT_DIR" rev-parse --git-dir >/dev/null 2>&1; then
  GIT_BRANCH=$(git -C "$PROJECT_DIR" branch --show-current 2>/dev/null)
  [ -z "$GIT_BRANCH" ] && GIT_BRANCH=$(git -C "$PROJECT_DIR" rev-parse --short HEAD 2>/dev/null)

  # Dirty indicator: uncommitted changes (staged or unstaged)
  if [ -n "$(git -C "$PROJECT_DIR" status --porcelain 2>/dev/null)" ]; then
    DIRTY=" \033[33m●\033[0m"
  fi

  # Unpushed indicator: commits ahead of remote
  if [ -n "$GIT_BRANCH" ]; then
    AHEAD=$(git -C "$PROJECT_DIR" rev-list --count "@{upstream}..HEAD" 2>/dev/null)
    if [ -n "$AHEAD" ] && [ "$AHEAD" -gt 0 ]; then
      UNPUSHED=" \033[31m↑${AHEAD}\033[0m"
    fi
  fi
fi

# Row 1: folder + branch + indicators
if [ -n "$GIT_BRANCH" ]; then
  LINE1="[\033[36m${FOLDER_NAME}\033[0m] \033[32m${GIT_BRANCH}\033[0m${DIRTY}${UNPUSHED}"
else
  LINE1="[\033[36m${FOLDER_NAME}\033[0m]"
fi

# ONEX Tier Badge: read ~/.claude/.onex_capabilities, append to Row 1
onex_tier=""
capabilities_file="$HOME/.claude/.onex_capabilities"
if [ -f "$capabilities_file" ] && command -v jq >/dev/null 2>&1; then
    tier=$(jq -r '.tier // empty' "$capabilities_file" 2>/dev/null | tr '[:upper:]' '[:lower:]')
    case "$tier" in
        full_onex)  onex_tier="${green}FULL_ONEX${reset}" ;;
        event_bus)  onex_tier="${yellow}EVENT_BUS${reset}" ;;
        standalone) onex_tier="${dim}STANDALONE${reset}" ;;
        *)          [ -n "$tier" ] && onex_tier="${dim}ONEX${reset}" ;;
    esac
fi
[ -n "$onex_tier" ] && LINE1+=" ${dim}|${reset} ${onex_tier}"

# Row 2: Tab bar showing all active Claude Code sessions
TAB_REGISTRY_DIR="/tmp/omniclaude-tabs"
LINE2=""

if command -v jq >/dev/null 2>&1; then
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
  NOW=$now
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
          # No live match → tab closed since registration, skip
        done <<< "$FORMATTED"
        FORMATTED=$(echo "$RESOLVED" | sort -t'|' -k1 -n)
      fi

      # Pre-scan: detect tabs sharing the same WORKTREE (collision warning)
      # Only flag paths under omni_worktrees — multiple tabs in omni_home is expected.
      DUPE_PATHS=""
      _paths=$(echo "$FORMATTED" | awk -F'|' '$5 != "" && $5 != "-" && $5 ~ /omni_worktrees/ {print $5}' | sort)
      [ -n "$_paths" ] && DUPE_PATHS=$(echo "$_paths" | uniq -d)

      # Pre-scan: detect same (ticket + mode) pair across multiple tabs — true collision.
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
        [ "$TAB_NUM" -gt 1 ] && LINE2="${LINE2}\033[90m|  \033[0m"
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
        # mode present  → show ticket (or repo fallback) + mode; branch is dropped (mode is more useful)
        # no mode        → fall back to repo[·ticket] (legacy behavior for tabs with no skill history)
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
            # DUPLICATE FOLDER: bright white on red bg — unmissable collision warning
            LINE2="${LINE2}\033[97;41m ⚠ ${label} \033[0m${activity_dot} "
          else
            # Current tab: black text on cyan background
            LINE2="${LINE2}\033[30;46m ${label} \033[0m${activity_dot} "
          fi
        else
          if [ "$is_dupe" -eq 1 ]; then
            # DUPLICATE FOLDER: bright red text — collision warning
            LINE2="${LINE2}\033[91m⚠ ${label}\033[0m${activity_dot} "
          else
            # Other tabs: white text
            LINE2="${LINE2}\033[37m${label}\033[0m${activity_dot} "
          fi
        fi
      done <<< "$FORMATTED"
    fi
  fi
fi

# Row 3: Active pipeline state (only emitted when an active pipeline entry exists)
ledger="$HOME/.claude/pipelines/ledger.json"
pipeline_line=""
active_ticket=""

if [ -f "$ledger" ] && command -v jq >/dev/null 2>&1; then
    ledger_mtime=$(stat -f %m "$ledger" 2>/dev/null || stat -c %Y "$ledger" 2>/dev/null)
    if [[ "$ledger_mtime" =~ ^[0-9]+$ ]]; then
        ledger_age=$(( now - ledger_mtime ))
        active_raw=$(jq -r '
          to_entries
          | map(select(.value.completed_at == null and (.value.terminal // false) != true))
          | sort_by(.value.started_at // "")
          | last
          | if . then "\(.key)\t\(.value.phase // "")\t\(.value.pr_number // "")" else "" end
        ' "$ledger" 2>/dev/null)

        if [ -n "$active_raw" ]; then
            active_ticket=$(printf '%s' "$active_raw" | cut -f1)
            active_phase=$(printf '%s'  "$active_raw" | cut -f2)
            active_pr=$(printf '%s'     "$active_raw" | cut -f3)

            if [ "$ledger_age" -gt 600 ]; then
                pipeline_line="${dim}${active_ticket} · stale${reset}"
            else
                pipeline_line="${cyan}${active_ticket}${reset}"
                [ -n "$active_phase" ] && pipeline_line+=" ${dim}·${reset} ${white}${active_phase}${reset}"
                [[ "$active_pr" =~ ^[0-9]+$ ]] && \
                    pipeline_line+=" ${dim}·${reset} ${blue}PR#${active_pr}${reset}"
            fi
        fi
    fi
fi

# Routing agent + confidence (/tmp/omniclaude-session-*.json)
agent_line=""
session_file=$(ls -t /tmp/omniclaude-session-*.json 2>/dev/null | head -1)

if [ -n "$session_file" ] && [ -f "$session_file" ]; then
    file_mtime=$(stat -f %m "$session_file" 2>/dev/null || stat -c %Y "$session_file" 2>/dev/null)
    if [[ "$file_mtime" =~ ^[0-9]+$ ]] && [ $(( now - file_mtime )) -le 300 ]; then
        agent=$(jq -r '.agent_selected // empty' "$session_file" 2>/dev/null)
        raw_conf=$(jq -r '.routing_confidence // empty' "$session_file" 2>/dev/null)

        if [ -n "$agent" ]; then
            agent_line="${dim}last routing:${reset} ${white}${agent}${reset}"
            if [[ "$raw_conf" =~ ^[0-9]*\.?[0-9]+$ ]]; then
                conf_pct=$(awk "BEGIN {
                    v = $raw_conf + 0
                    if (v <= 1) v = v * 100
                    if (v > 100) v = 100
                    printf \"%.0f\", v
                }")
                [ "$conf_pct" -gt 0 ] 2>/dev/null && agent_line+=" ${dim}(${conf_pct}%)${reset}"
            fi
        fi
    fi
fi

# Rate limit warning (/tmp/omniclaude-blocked-rate-limits.json)
rate_warn=""
rate_limit_file="/tmp/omniclaude-blocked-rate-limits.json"

if [ -f "$rate_limit_file" ]; then
    rl_mtime=$(stat -f %m "$rate_limit_file" 2>/dev/null || stat -c %Y "$rate_limit_file" 2>/dev/null)
    if [[ "$rl_mtime" =~ ^[0-9]+$ ]] && [ $(( now - rl_mtime )) -le 600 ]; then
        blocked_count=$(jq 'if type == "object" then length else 0 end' \
                        "$rate_limit_file" 2>/dev/null)
        if [[ "$blocked_count" =~ ^[0-9]+$ ]] && [ "$blocked_count" -gt 0 ]; then
            rate_warn="${yellow}⚠ ${blocked_count} rate-limited${reset}"
        fi
    fi
fi

# Assemble LINE3 (only when active pipeline exists)
LINE3=""
if [ -n "$pipeline_line" ]; then
    LINE3="$pipeline_line"
    [ -n "$agent_line" ] && LINE3+="${sep}${agent_line}"
    [ -n "$rate_warn" ]  && LINE3+="${sep}${rate_warn}"
fi

# Output: row 1 always, row 2 if tabs registered, row 3 if pipeline active
if [ -n "$LINE2" ] && [ -n "$LINE3" ]; then
  echo -e "${LINE1}\n${LINE2}\n${LINE3}"
elif [ -n "$LINE2" ]; then
  echo -e "${LINE1}\n${LINE2}"
elif [ -n "$LINE3" ]; then
  echo -e "${LINE1}\n${LINE3}"
else
  echo -e "${LINE1}"
fi
