#!/bin/bash
# ONEX Status Line - Shows folder, git branch, and PR number
# Part of the onex plugin for Claude Code

input=$(cat)
PROJECT_DIR=$(echo "$input" | jq -r '.workspace.project_dir // .workspace.current_dir // "."')
FOLDER_NAME=$(basename "$PROJECT_DIR")

# Get git branch if in a repo
GIT_BRANCH=""
PR_NUM=""
if git -C "$PROJECT_DIR" rev-parse --git-dir >/dev/null 2>&1; then
  GIT_BRANCH=$(git -C "$PROJECT_DIR" branch --show-current 2>/dev/null)
  [ -z "$GIT_BRANCH" ] && GIT_BRANCH=$(git -C "$PROJECT_DIR" rev-parse --short HEAD 2>/dev/null)

  # Cache PR number by repo+branch (5 min TTL)
  if [ -n "$GIT_BRANCH" ] && command -v gh >/dev/null 2>&1; then
    CACHE_DIR="$HOME/.claude/cache/pr-numbers"
    mkdir -p "$CACHE_DIR" 2>/dev/null

    # Create cache key from repo path + branch (sanitized)
    CACHE_KEY=$(echo "${PROJECT_DIR}:${GIT_BRANCH}" | sed 's/[^a-zA-Z0-9]/_/g')
    CACHE_FILE="$CACHE_DIR/$CACHE_KEY"

    # Check if cache exists and is fresh (< 5 minutes old)
    CACHE_FRESH=0
    if [ -f "$CACHE_FILE" ]; then
      CACHE_AGE=$(( $(date +%s) - $(stat -f %m "$CACHE_FILE" 2>/dev/null || stat -c %Y "$CACHE_FILE" 2>/dev/null || echo 0) ))
      [ "$CACHE_AGE" -lt 300 ] && CACHE_FRESH=1
    fi

    if [ "$CACHE_FRESH" -eq 1 ]; then
      # Use cached value
      PR_NUM=$(cat "$CACHE_FILE" 2>/dev/null)
    else
      # Fetch in background, update cache
      (
        REMOTE_URL=$(git -C "$PROJECT_DIR" remote get-url origin 2>/dev/null)
        NEW_PR=$(gh pr view "$GIT_BRANCH" --json number -q '.number' -R "$REMOTE_URL" 2>/dev/null)
        echo "$NEW_PR" > "$CACHE_FILE" 2>/dev/null
      ) &
      # Use stale cache if available
      [ -f "$CACHE_FILE" ] && PR_NUM=$(cat "$CACHE_FILE" 2>/dev/null)
    fi
  fi
fi

# Colors: cyan for folder, green for branch, magenta for PR
if [ -n "$GIT_BRANCH" ]; then
  if [ -n "$PR_NUM" ]; then
    echo -e "[\033[36m${FOLDER_NAME}\033[0m] \033[32m${GIT_BRANCH}\033[0m \033[35m#${PR_NUM}\033[0m"
  else
    echo -e "[\033[36m${FOLDER_NAME}\033[0m] \033[32m${GIT_BRANCH}\033[0m"
  fi
else
  echo -e "[\033[36m${FOLDER_NAME}\033[0m]"
fi
