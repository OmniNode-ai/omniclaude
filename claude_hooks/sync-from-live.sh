#!/bin/bash
# Sync changes from live hooks directory back to repository
# Useful for capturing quick fixes made in the live directory
# Usage: ./sync-from-live.sh [--dry-run]

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
echo -e "${BLUE}║         Sync Live Hooks Directory to Repository             ║${NC}"
echo -e "${BLUE}╚══════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "${YELLOW}⚠️  This syncs FROM live TO repository (reverse direction)${NC}"
echo ""

# Check if dry-run mode
DRY_RUN=false
if [[ "${1:-}" == "--dry-run" ]]; then
    DRY_RUN=true
    echo -e "${YELLOW}Running in DRY-RUN mode (no changes will be made)${NC}"
    echo ""
fi

# Verify directories
if [[ ! -d "$LIVE_DIR" ]]; then
    echo -e "${RED}Error: Live directory not found: $LIVE_DIR${NC}"
    exit 1
fi

if [[ ! -d "$REPO_DIR" ]]; then
    echo -e "${RED}Error: Repository directory not found: $REPO_DIR${NC}"
    exit 1
fi

echo -e "${BLUE}Source:${NC} $LIVE_DIR"
echo -e "${BLUE}Target:${NC} $REPO_DIR"
echo ""

# Exclude patterns
EXCLUDE_PATTERNS=(
    ".cache"
    "__pycache__"
    "*.pyc"
    ".pytest_cache"
    "logs/*.log"
    "logs/*.jsonl"
    ".DS_Store"
)

# Build rsync exclude arguments
EXCLUDE_ARGS=()
for pattern in "${EXCLUDE_PATTERNS[@]}"; do
    EXCLUDE_ARGS+=(--exclude="$pattern")
done

echo -e "${BLUE}Files that would be synced:${NC}"
echo "----------------------------------------"

# Show what will be synced
rsync -av --dry-run "${EXCLUDE_ARGS[@]}" \
    "$LIVE_DIR/" "$REPO_DIR/" \
    | grep -v '^sending incremental file list$' \
    | grep -v '^sent\|total size' \
    | head -30

echo "----------------------------------------"
echo ""

# Count files
FILE_COUNT=$(rsync -av --dry-run "${EXCLUDE_ARGS[@]}" \
    "$LIVE_DIR/" "$REPO_DIR/" \
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

# Warn about overwriting
echo -e "${YELLOW}⚠️  Warning: This will overwrite files in the repository!${NC}"
read -p "Proceed with sync? (y/N) " -n 1 -r
echo ""
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo -e "${YELLOW}Sync cancelled.${NC}"
    exit 0
fi

echo -e "${BLUE}Syncing files...${NC}"

# Perform sync
if rsync -av "${EXCLUDE_ARGS[@]}" \
    --itemize-changes \
    "$LIVE_DIR/" "$REPO_DIR/"; then
    echo ""
    echo -e "${GREEN}✓ Sync complete!${NC}"
    echo ""
    echo -e "${BLUE}Next steps:${NC}"
    echo "  1. Review changes: git diff"
    echo "  2. Test if needed"
    echo "  3. Commit: git add . && git commit -m 'sync: update from live hooks'"
else
    echo ""
    echo -e "${RED}✗ Sync failed!${NC}"
    exit 1
fi
