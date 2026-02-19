#!/bin/bash
# Tab Registry - Register this Claude Code session for statusline tab bar
# Called from SessionStart hooks across all plugin versions.
# Runs in background (caller should invoke with &).
# Creates /tmp/omniclaude-tabs/{session_id}.json

SESSION_ID="${1:-}"
PROJECT_PATH="${2:-$(pwd)}"

[ -z "$SESSION_ID" ] && exit 0

TAB_REGISTRY_DIR="/tmp/omniclaude-tabs"
mkdir -p "$TAB_REGISTRY_DIR" 2>/dev/null || exit 0

# Get visual tab position via AppleScript (macOS only)
# Strategy: look up the tab containing our session by GUID, not "current tab",
# because this script may run in the background when another tab is focused.
TAB_POS=""
if [ "$(uname)" = "Darwin" ] && command -v osascript >/dev/null 2>&1; then
    # Extract GUID from ITERM_SESSION_ID (format: w{W}t{T}p{P}:{GUID} or plain {GUID})
    ITERM_GUID=""
    case "${ITERM_SESSION_ID:-}" in
        *:*) ITERM_GUID="${ITERM_SESSION_ID##*:}" ;;
        ?*)  ITERM_GUID="$ITERM_SESSION_ID" ;;
    esac

    if [ -n "$ITERM_GUID" ]; then
        # Find tab by matching session GUID (works even when tab isn't focused)
        TAB_POS=$(osascript 2>/dev/null <<APPLESCRIPT
tell application "iTerm2"
    tell current window
        repeat with i from 1 to count of tabs
            tell tab i
                repeat with s in sessions
                    if unique ID of s contains "$ITERM_GUID" then return i
                end repeat
            end tell
        end repeat
    end tell
end tell
APPLESCRIPT
        ) || TAB_POS=""
    fi

    # Fallback: current tab (correct during SessionStart when this tab IS focused)
    if [ -z "$TAB_POS" ]; then
        TAB_POS=$(osascript -e '
            tell application "iTerm2"
                tell current window
                    repeat with i from 1 to count of tabs
                        if tab i is current tab then return i
                    end repeat
                end tell
            end tell
        ' 2>/dev/null) || TAB_POS=""
    fi
fi

# Last resort fallback: extract from ITERM_SESSION_ID (creation order, less accurate)
if [ -z "$TAB_POS" ] && [ -n "${ITERM_SESSION_ID:-}" ]; then
    TAB_POS=$(echo "$ITERM_SESSION_ID" | sed -n 's/.*t\([0-9]*\)p.*/\1/p')
    [ -n "$TAB_POS" ] && TAB_POS=$((TAB_POS + 1))
fi

# Get repo name and ticket from branch
REPO_NAME=$(basename "${PROJECT_PATH:-unknown}")
TAB_GIT_BRANCH=""
if command -v git >/dev/null 2>&1; then
    TAB_GIT_BRANCH=$(git -C "${PROJECT_PATH:-.}" branch --show-current 2>/dev/null || echo "")
fi
TICKET_ID=$(echo "$TAB_GIT_BRANCH" | grep -oiE 'omn-[0-9]+' | head -1 | grep -oE '[0-9]+')

# Write registry entry (atomic: temp file + mv)
command -v jq >/dev/null 2>&1 || exit 0
jq -n \
    --arg repo "$REPO_NAME" \
    --arg branch "$TAB_GIT_BRANCH" \
    --arg ticket "${TICKET_ID:-}" \
    --argjson tab_pos "${TAB_POS:-null}" \
    --arg session_id "$SESSION_ID" \
    --arg iterm_guid "${ITERM_SESSION_ID:-}" \
    --arg project_path "$PROJECT_PATH" \
    '{repo: $repo, branch: $branch, ticket: $ticket, tab_pos: $tab_pos, session_id: $session_id, iterm_guid: $iterm_guid, project_path: $project_path}' \
    > "${TAB_REGISTRY_DIR}/${SESSION_ID}.json.tmp" 2>/dev/null \
&& mv "${TAB_REGISTRY_DIR}/${SESSION_ID}.json.tmp" "${TAB_REGISTRY_DIR}/${SESSION_ID}.json" 2>/dev/null

exit 0
