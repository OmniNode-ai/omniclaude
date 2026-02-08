#!/bin/bash
# ONEX Status Line - Shows folder, git branch, dirty state, unpushed commits,
# and a tab bar of all active Claude Code sessions.
# Part of the onex plugin for Claude Code
#
# Note: This script intentionally continues on errors (no set -e) because
# status line display should never block Claude Code, even if git fails.

input=$(cat)
PROJECT_DIR=$(echo "$input" | jq -r '.workspace.project_dir // .workspace.current_dir // "."')
FOLDER_NAME=$(basename "$PROJECT_DIR")

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
    fi
  fi

  # Stale threshold: skip entries older than 24 hours (86400 seconds)
  NOW=$(date +%s)
  STALE_THRESHOLD=$((NOW - 86400))

  # Read all registry files, parse with single jq invocation
  # Output: tab_pos\trepo\tticket\titerm_guid (one per line, sorted by tab_pos)
  ENTRIES=""
  for f in "$TAB_REGISTRY_DIR"/*.json; do
    [ -f "$f" ] || continue
    # Skip stale files (older than 24h) using file mtime
    if stat -f %m "$f" >/dev/null 2>&1; then
      FILE_MTIME=$(stat -f %m "$f" 2>/dev/null)
    else
      FILE_MTIME=$(stat -c %Y "$f" 2>/dev/null || echo "0")
    fi
    [ "$FILE_MTIME" -lt "$STALE_THRESHOLD" ] && continue
    ENTRIES="${ENTRIES}$(cat "$f" 2>/dev/null)
"
  done

  if [ -n "$ENTRIES" ]; then
    # Single jq call: parse all entries, sort by tab_pos, output tab-delimited
    # Includes project_path so we can read live branch from git
    # Use pipe-delimited output (tab-delimited breaks on empty fields with bash read)
    FORMATTED=$(echo "$ENTRIES" | jq -sr '
      [.[] | select(.repo != null)] |
      sort_by(.tab_pos // 999) |
      .[] | "\(.tab_pos // "?")|\(.repo // "?")|\(.ticket // "-")|\(.iterm_guid // "-")|\(.project_path // "-")"
    ' 2>/dev/null)

    if [ -n "$FORMATTED" ]; then
      while IFS='|' read -r tab_pos repo ticket iterm_guid project_path; do
        [ -z "$tab_pos" ] && continue
        # Convert placeholders back to empty
        [ "$ticket" = "-" ] && ticket=""
        [ "$iterm_guid" = "-" ] && iterm_guid=""
        [ "$project_path" = "-" ] && project_path=""

        # Read live branch from git if project_path is available (keeps ticket current after merges)
        if [ -n "$project_path" ] && [ -d "$project_path" ]; then
          live_branch=$(git -C "$project_path" branch --show-current 2>/dev/null || echo "")
          if [ -n "$live_branch" ]; then
            ticket=$(echo "$live_branch" | grep -oiE 'omn-[0-9]+' | head -1 | tr '[:lower:]' '[:upper:]')
          fi
        fi

        # Build label: T{pos}·{repo} or T{pos}·{repo}·{ticket}
        label="T${tab_pos}·${repo}"
        [ -n "$ticket" ] && label="${label}·${ticket}"

        # Highlight current tab (match by iTerm GUID - handles both full and GUID-only formats)
        entry_guid="${iterm_guid#*:}"  # Strip w{W}t{T}p{P}: prefix if present
        if [ -n "$CURRENT_ITERM" ] && [ "$entry_guid" = "$CURRENT_ITERM" ]; then
          # Current tab: black text on cyan background
          LINE2="${LINE2}\033[30;46m ${label} \033[0m  "
        else
          # Inactive tabs: gray text (bright black = gray on most terminals)
          LINE2="${LINE2}\033[37m${label}\033[0m  "
        fi
      done <<< "$FORMATTED"
    fi
  fi
fi

# Output: row 1 always, row 2 if there are registered tabs
if [ -n "$LINE2" ]; then
  echo -e "${LINE1}\n${LINE2}"
else
  echo -e "${LINE1}"
fi
