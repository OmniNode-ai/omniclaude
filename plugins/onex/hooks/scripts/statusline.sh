#!/bin/bash
# ONEX Status Line - Shows folder, git branch, dirty state, and unpushed commits
# Part of the onex plugin for Claude Code
#
# Note: This script intentionally continues on errors (no set -e) because
# status line display should never block Claude Code, even if git fails.

LOG_FILE="${LOG_FILE:-${HOME}/.claude/hooks.log}"

input=$(cat)
PROJECT_DIR=$(echo "$input" | jq -r '.workspace.project_dir // .workspace.current_dir // "."' 2>/dev/null)
if [[ $? -ne 0 || -z "$PROJECT_DIR" || "$PROJECT_DIR" == "null" ]]; then
  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] statusline: failed to parse stdin JSON" >> "$LOG_FILE" 2>/dev/null
  exit 0
fi
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

# Colors: cyan for folder, green for branch, yellow for dirty, red for unpushed
if [ -n "$GIT_BRANCH" ]; then
  echo -e "[\033[36m${FOLDER_NAME}\033[0m] \033[32m${GIT_BRANCH}\033[0m${DIRTY}${UNPUSHED}"
else
  echo -e "[\033[36m${FOLDER_NAME}\033[0m]"
fi

exit 0
