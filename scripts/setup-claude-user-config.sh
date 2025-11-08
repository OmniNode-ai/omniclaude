#!/usr/bin/env bash
#
# Setup Claude Code user-level configuration
# Creates symlinks from ~/.claude/ to this repository
#
# Usage: ./scripts/setup-claude-user-config.sh

set -euo pipefail

# Get repository root (script is in scripts/)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo "=========================================="
echo "Claude Code User-Level Configuration Setup"
echo "=========================================="
echo ""
echo "Repository: $REPO_ROOT"
echo "Target: ~/.claude/"
echo ""

# Create ~/.claude if it doesn't exist
if [ ! -d ~/.claude ]; then
    echo -e "${GREEN}Creating ~/.claude/ directory${NC}"
    mkdir -p ~/.claude
fi

# Function to create symlink with backup
create_symlink() {
    local source="$1"
    local target="$2"
    local name="$3"

    if [ -L "$target" ]; then
        # Existing symlink - check if correct
        current_target="$(readlink "$target")"
        if [ "$current_target" = "$source" ]; then
            echo -e "${GREEN}✓${NC} $name (already correct)"
            return 0
        else
            echo -e "${YELLOW}⚠${NC}  $name (points to wrong location, updating...)"
            rm "$target"
        fi
    elif [ -e "$target" ]; then
        # Exists but not a symlink - backup
        backup="${target}.backup.$(date +%Y%m%d_%H%M%S)"
        echo -e "${YELLOW}⚠${NC}  $name (backing up to $(basename "$backup"))"
        mv "$target" "$backup"
    fi

    # Create symlink
    ln -sf "$source" "$target"
    echo -e "${GREEN}✓${NC} $name → $source"
}

# Create all symlinks
echo "Creating symlinks..."
echo ""

create_symlink \
    "$REPO_ROOT/agents/definitions" \
    ~/.claude/agent-definitions \
    "agent-definitions"

create_symlink \
    "$REPO_ROOT/agents" \
    ~/.claude/agents \
    "agents"

create_symlink \
    "$REPO_ROOT/claude_hooks" \
    ~/.claude/hooks \
    "hooks"

create_symlink \
    "$REPO_ROOT/skills" \
    ~/.claude/skills \
    "skills"

create_symlink \
    "$REPO_ROOT/.claude/commands" \
    ~/.claude/commands \
    "commands"

create_symlink \
    "$REPO_ROOT/.env" \
    ~/.claude/.env \
    ".env"

# Optional: CLAUDE.md for global instructions
read -p "Symlink CLAUDE.md for global instructions? (y/N) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    create_symlink \
        "$REPO_ROOT/CLAUDE.md" \
        ~/.claude/CLAUDE.md \
        "CLAUDE.md"
fi

echo ""
echo "=========================================="
echo "Setup Complete!"
echo "=========================================="
echo ""
echo "Verification:"
ls -la ~/.claude/ | grep -E "agent-definitions|agents|hooks|skills|commands|\.env"
echo ""
echo -e "${GREEN}✓${NC} All user-level configuration symlinked to repository"
echo ""
echo "Next steps:"
echo "1. Verify .env has your API keys and credentials"
echo "2. Restart Claude Code to pick up new configuration"
echo "3. Test with: /parallel-solve or any custom command"
echo ""
