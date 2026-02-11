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
  NOW=$(date +%s)
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

      TAB_NUM=0
      while IFS='|' read -r tab_pos repo ticket iterm_guid project_path; do
        [ -z "$tab_pos" ] && continue
        TAB_NUM=$((TAB_NUM + 1))
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
            ticket=$(echo "$live_branch" | grep -oiE 'omn-[0-9]+' | head -1 | tr '[:lower:]' '[:upper:]')
          fi
        fi

        # Read tab activity (active skill/command, written by hooks)
        tab_activity=""
        activity_file="${TAB_REGISTRY_DIR}/${entry_guid}.activity"
        if [ -f "$activity_file" ]; then
          tab_activity=$(cat "$activity_file" 2>/dev/null)
        fi

        # Build label: T{n}·{repo}[·{ticket}][·{activity}]
        # Sequential numbering (sorted by iTerm position for spatial consistency)
        label="T${TAB_NUM}·${repo}"
        [ -n "$ticket" ] && label="${label}·${ticket}"

        # Highlight current tab (match by iTerm GUID)
        if [ -n "$CURRENT_ITERM" ] && [ "$entry_guid" = "$CURRENT_ITERM" ]; then
          # Current tab: black text on cyan background, activity in yellow
          if [ -n "$tab_activity" ]; then
            LINE2="${LINE2}\033[30;46m ${label} \033[33;46m${tab_activity} \033[0m "
          else
            LINE2="${LINE2}\033[30;46m ${label} \033[0m "
          fi
        else
          if [ -n "$tab_activity" ]; then
            # Active skill: white text with yellow activity suffix
            LINE2="${LINE2}\033[37m${label}·\033[33m${tab_activity}\033[0m "
          else
            # Inactive tabs: gray text
            LINE2="${LINE2}\033[37m${label}\033[0m "
          fi
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
