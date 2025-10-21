#!/bin/bash
# Setup symlinks from ~/.claude/hooks to repository for version control
# This ensures all hook changes are tracked in git

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLAUDE_HOOKS_DIR="$HOME/.claude/hooks"
BACKUP_DIR="$HOME/.claude/hooks.backup.$(date +%Y%m%d_%H%M%S)"

# Color output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}╔══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║    Claude Code Hooks - Symlink Setup for Version Control    ║${NC}"
echo -e "${BLUE}╚══════════════════════════════════════════════════════════════╝${NC}"
echo ""

# Check if .env file exists
ENV_FILE="$REPO_DIR/../.env"
if [[ ! -f "$ENV_FILE" ]]; then
    echo -e "${YELLOW}⚠️  Warning: .env file not found at $ENV_FILE${NC}"
    echo -e "${YELLOW}   Hooks require DB_PASSWORD for database logging.${NC}"
    echo -e "${YELLOW}   Please create .env from .env.example:${NC}"
    echo -e "${YELLOW}     cp .env.example .env${NC}"
    echo ""
    read -p "Continue anyway? (y/N) " -n 1 -r
    echo ""
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

echo -e "${BLUE}Repository:${NC} $REPO_DIR"
echo -e "${BLUE}Target:${NC}     $CLAUDE_HOOKS_DIR"
echo ""

# Check if target already exists and is a real directory (not symlink)
if [[ -d "$CLAUDE_HOOKS_DIR" ]] && [[ ! -L "$CLAUDE_HOOKS_DIR" ]]; then
    echo -e "${YELLOW}Existing hooks directory found (not a symlink)${NC}"
    echo -e "${YELLOW}This will be backed up to:${NC} $BACKUP_DIR"
    echo ""
    read -p "Proceed with backup and symlink setup? (y/N) " -n 1 -r
    echo ""
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo -e "${YELLOW}Setup cancelled.${NC}"
        exit 0
    fi

    # Create backup
    echo -e "${BLUE}Creating backup...${NC}"
    cp -r "$CLAUDE_HOOKS_DIR" "$BACKUP_DIR"
    echo -e "${GREEN}✓ Backup created at $BACKUP_DIR${NC}"
    echo ""

    # Remove existing directory
    echo -e "${BLUE}Removing existing hooks directory...${NC}"
    rm -rf "$CLAUDE_HOOKS_DIR"
elif [[ -L "$CLAUDE_HOOKS_DIR" ]]; then
    echo -e "${YELLOW}Existing symlink found. Removing...${NC}"
    rm -f "$CLAUDE_HOOKS_DIR"
fi

# Create parent directory if it doesn't exist
mkdir -p "$(dirname "$CLAUDE_HOOKS_DIR")"

# Create symlink
echo -e "${BLUE}Creating symlink...${NC}"
ln -s "$REPO_DIR" "$CLAUDE_HOOKS_DIR"

if [[ -L "$CLAUDE_HOOKS_DIR" ]]; then
    echo -e "${GREEN}✓ Symlink created successfully!${NC}"
    echo ""

    # Verify symlink
    echo -e "${BLUE}Symlink verification:${NC}"
    ls -l "$CLAUDE_HOOKS_DIR" | head -1
    echo ""

    echo -e "${GREEN}✓ Setup complete!${NC}"
    echo ""
    echo -e "${BLUE}Benefits of symlink approach:${NC}"
    echo "  • All hook changes automatically tracked in git"
    echo "  • No need to sync between directories"
    echo "  • Single source of truth in repository"
    echo "  • Easy rollback via git"
    echo ""
    echo -e "${BLUE}Next steps:${NC}"
    echo "  1. Ensure .env file is set up with DB_PASSWORD"
    echo "  2. Source .env in your shell: source .env"
    echo "  3. Test hooks with Claude Code"
    echo "  4. Changes to hooks are now versioned in git"
    echo ""
    echo -e "${BLUE}To revert (if needed):${NC}"
    if [[ -d "$BACKUP_DIR" ]]; then
        echo "  rm $CLAUDE_HOOKS_DIR"
        echo "  mv $BACKUP_DIR $CLAUDE_HOOKS_DIR"
    else
        echo "  rm $CLAUDE_HOOKS_DIR"
        echo "  mkdir -p $CLAUDE_HOOKS_DIR"
    fi
else
    echo -e "${RED}✗ Failed to create symlink!${NC}"
    exit 1
fi
