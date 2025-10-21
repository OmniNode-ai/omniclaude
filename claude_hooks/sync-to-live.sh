#!/bin/bash
# Sync changes from repository to live hooks directory
# Usage: ./sync-to-live.sh [--dry-run]

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIVE_DIR="$HOME/.claude/hooks"

# Color output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}╔══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║         Sync Repository to Live Hooks Directory             ║${NC}"
echo -e "${BLUE}╚══════════════════════════════════════════════════════════════╝${NC}"
echo ""

# Check if dry-run mode
DRY_RUN=false
if [[ "${1:-}" == "--dry-run" ]]; then
    DRY_RUN=true
    echo -e "${YELLOW}Running in DRY-RUN mode (no changes will be made)${NC}"
    echo ""
fi

# Verify source directory
if [[ ! -d "$REPO_DIR" ]]; then
    echo -e "${RED}Error: Repository directory not found: $REPO_DIR${NC}"
    exit 1
fi

# Create live directory if it doesn't exist
if [[ ! -d "$LIVE_DIR" ]]; then
    echo -e "${YELLOW}Live directory doesn't exist. Creating: $LIVE_DIR${NC}"
    if [[ "$DRY_RUN" == false ]]; then
        mkdir -p "$LIVE_DIR"
    fi
fi

echo -e "${BLUE}Source:${NC} $REPO_DIR"
echo -e "${BLUE}Target:${NC} $LIVE_DIR"
echo ""

# Exclude patterns (don't sync these)
EXCLUDE_PATTERNS=(
    ".git"
    ".cache"
    "__pycache__"
    "*.pyc"
    ".pytest_cache"
    "logs/*.log"
    "logs/*.jsonl"
    ".DS_Store"
    "sync-to-live.sh"
    "sync-from-live.sh"
)

# Build rsync exclude arguments
EXCLUDE_ARGS=()
for pattern in "${EXCLUDE_PATTERNS[@]}"; do
    EXCLUDE_ARGS+=(--exclude="$pattern")
done

echo -e "${BLUE}Files to sync:${NC}"
echo "----------------------------------------"

# Show what will be synced (dry-run first for display)
rsync -av --dry-run "${EXCLUDE_ARGS[@]}" \
    "$REPO_DIR/" "$LIVE_DIR/" \
    | grep -v '^sending incremental file list$' \
    | grep -v '^sent\|total size' \
    | head -30

echo "----------------------------------------"
echo ""

# Count files to sync
FILE_COUNT=$(rsync -av --dry-run "${EXCLUDE_ARGS[@]}" \
    "$REPO_DIR/" "$LIVE_DIR/" \
    | grep -v '^sending incremental file list$' \
    | grep -v '^sent\|total size' \
    | grep -v '/$' \
    | wc -l | tr -d ' ')

echo -e "${GREEN}Total files to sync: $FILE_COUNT${NC}"
echo ""

if [[ "$DRY_RUN" == true ]]; then
    echo -e "${YELLOW}DRY-RUN complete. Run without --dry-run to apply changes.${NC}"
    exit 0
fi

# Confirm before syncing
read -p "Proceed with sync? (y/N) " -n 1 -r
echo ""
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo -e "${YELLOW}Sync cancelled.${NC}"
    exit 0
fi

echo -e "${BLUE}Syncing files...${NC}"

# Perform actual sync
if rsync -av "${EXCLUDE_ARGS[@]}" \
    --itemize-changes \
    "$REPO_DIR/" "$LIVE_DIR/"; then
    echo ""
    echo -e "${GREEN}✓ Sync complete!${NC}"
    echo ""
    echo -e "${BLUE}Next steps:${NC}"
    echo "  1. Test the changes in Claude Code"
    echo "  2. Check logs: tail -f ~/.claude/hooks/logs/quality_enforcer.log"
    echo "  3. If working, commit changes in repository"
else
    echo ""
    echo -e "${RED}✗ Sync failed!${NC}"
    exit 1
fi
