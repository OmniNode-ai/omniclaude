#!/bin/bash
# Tab Registry - Register this Claude Code session for statusline tab bar
# Called from SessionStart hooks. Runs in background (caller invokes with &).
# Creates /tmp/omniclaude-tabs/{session_id}.json with tab position, repo, and ticket.

SESSION_ID="${1:-}"
PROJECT_PATH="${2:-$(pwd)}"

[ -z "$SESSION_ID" ] && exit 0

TAB_REGISTRY_DIR="/tmp/omniclaude-tabs"
mkdir -p "$TAB_REGISTRY_DIR" 2>/dev/null || exit 0

# Get visual tab position via AppleScript (accurate, macOS only)
TAB_POS=""
if [ "$(uname)" = "Darwin" ] && command -v osascript >/dev/null 2>&1; then
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

# Fallback: extract from ITERM_SESSION_ID (creation order, less accurate)
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
TICKET_ID=$(echo "$TAB_GIT_BRANCH" | grep -oiE 'omn-[0-9]+' | head -1 | tr '[:lower:]' '[:upper:]')

# Write registry entry (atomic: temp file + mv)
command -v jq >/dev/null 2>&1 || exit 0
jq -n \
    --arg repo "$REPO_NAME" \
    --arg branch "$TAB_GIT_BRANCH" \
    --arg ticket "${TICKET_ID:-}" \
    --argjson tab_pos "${TAB_POS:-null}" \
    --arg session_id "$SESSION_ID" \
    --arg iterm_guid "${ITERM_SESSION_ID:-}" \
    '{repo: $repo, branch: $branch, ticket: $ticket, tab_pos: $tab_pos, session_id: $session_id, iterm_guid: $iterm_guid}' \
    > "${TAB_REGISTRY_DIR}/${SESSION_ID}.json.tmp" 2>/dev/null \
&& mv "${TAB_REGISTRY_DIR}/${SESSION_ID}.json.tmp" "${TAB_REGISTRY_DIR}/${SESSION_ID}.json" 2>/dev/null

exit 0
