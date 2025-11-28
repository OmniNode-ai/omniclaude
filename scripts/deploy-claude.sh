#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
CLAUDE_DIR="$HOME/.claude"
ONEX_DIR="$CLAUDE_DIR/onex"

echo "=== OmniClaude Claude Artifacts Deployment ==="
echo "Repo: $REPO_ROOT"
echo "Target: $ONEX_DIR"
echo ""

# Create onex namespace directory
mkdir -p "$ONEX_DIR"

# Security: Validate path is within allowed directories
validate_source_path() {
    local source="$1"
    local resolved_source

    # Resolve to absolute path (handles .. and symlinks)
    resolved_source="$(cd "$(dirname "$source")" 2>/dev/null && pwd)/$(basename "$source")" || {
        return 1
    }

    # Allow paths within REPO_ROOT or HOME
    if [[ "$resolved_source" == "$REPO_ROOT"* ]] || [[ "$resolved_source" == "$HOME"* ]]; then
        return 0
    fi

    return 1
}

# Function to create symlink with backup and security validation
create_symlink() {
    local source="$1"
    local target="$2"
    local name="$3"
    local required="${4:-true}"  # Optional: whether source is required (default: true)

    # Security Check 1: Validate source path exists
    if [[ ! -e "$source" ]]; then
        if [[ "$required" == "true" ]]; then
            echo "  ERROR: Source path does not exist: $source"
            echo "  Cannot create symlink for: $name"
            exit 1
        else
            echo "  WARNING: Skipping $name symlink, source does not exist: $source"
            return 0
        fi
    fi

    # Security Check 2: Validate source path is within allowed directories
    if ! validate_source_path "$source"; then
        echo "  ERROR: Source path is outside allowed directories: $source"
        echo "  Allowed: $REPO_ROOT or $HOME"
        exit 1
    fi

    # Security Check 3: Validate paths don't contain dangerous characters
    if [[ "$source" =~ [[:cntrl:]] ]] || [[ "$target" =~ [[:cntrl:]] ]]; then
        echo "  ERROR: Path contains control characters: $name"
        exit 1
    fi

    # Handle existing target
    if [[ -L "$target" ]]; then
        rm "$target"
    elif [[ -e "$target" ]]; then
        echo "  Backing up existing $name to ${target}.bak"
        mv "$target" "${target}.bak"
    fi

    ln -s "$source" "$target"
    echo "  ✓ $name → $source"
}

echo "Creating symlinks in $ONEX_DIR/..."
create_symlink "$REPO_ROOT/claude/hooks" "$ONEX_DIR/hooks" "hooks"
create_symlink "$REPO_ROOT/claude/skills" "$ONEX_DIR/skills" "skills"
create_symlink "$REPO_ROOT/claude/commands" "$ONEX_DIR/commands" "commands"
create_symlink "$REPO_ROOT/claude/agents" "$ONEX_DIR/agents" "agents"
create_symlink "$REPO_ROOT/claude/lib" "$ONEX_DIR/lib" "lib"
create_symlink "$REPO_ROOT/claude/plugins" "$ONEX_DIR/plugins" "plugins"

echo ""
echo "Creating top-level Claude symlinks..."
create_symlink "$ONEX_DIR/hooks" "$CLAUDE_DIR/hooks" "hooks"
create_symlink "$ONEX_DIR/skills" "$CLAUDE_DIR/skills" "skills"
create_symlink "$ONEX_DIR/commands" "$CLAUDE_DIR/commands" "commands"
create_symlink "$ONEX_DIR/agents" "$CLAUDE_DIR/agent-definitions" "agent-definitions"

echo ""
echo "Symlinking shared resources..."
# .env is optional - warn but don't fail if missing
create_symlink "$REPO_ROOT/.env" "$CLAUDE_DIR/.env" ".env" "false"
create_symlink "$REPO_ROOT/config" "$ONEX_DIR/config" "config"

# Symlink the poetry venv for Python imports
VENV_PATH=$(cd "$REPO_ROOT" && poetry env info --path 2>/dev/null || echo "")
if [[ -n "$VENV_PATH" && -d "$VENV_PATH" ]]; then
    # Use create_symlink with required=false since venv is optional
    create_symlink "$VENV_PATH" "$ONEX_DIR/.venv" ".venv" "false"
    echo ""
    echo "Poetry venv linked: $VENV_PATH"
else
    echo ""
    echo "Poetry venv not found. Run 'poetry install' first."
fi

echo ""
echo "=== Deployment Complete ==="
echo ""
echo "Structure:"
echo "  ~/.claude/"
echo "    ├── hooks/      → $REPO_ROOT/claude/hooks/"
echo "    ├── skills/     → $REPO_ROOT/claude/skills/"
echo "    ├── commands/   → $REPO_ROOT/claude/commands/"
echo "    └── agent-definitions/ → $REPO_ROOT/claude/agents/"
echo ""
echo "All Python code can now import from 'claude.lib'"
