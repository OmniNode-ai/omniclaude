#!/bin/bash
set -euo pipefail

# =============================================================================
# deploy-claude.sh - OmniClaude Claude Artifacts Deployment
#
# Security Features:
#   - Source path existence validation before symlink creation
#   - Path traversal protection (validates paths within allowed directories)
#   - Symlink target validation (prevents symlink traversal attacks)
#   - Control character rejection in paths
#   - Automatic backup of existing non-symlink targets
#
# Usage:
#   ./deploy-claude.sh [OPTIONS]
#
# Options:
#   --force       Skip existence checks for optional sources (security checks remain)
#   --dry-run     Show what would be done without making changes
#   --help        Show this help message
# =============================================================================

# Parse command line arguments
FORCE_MODE=false
DRY_RUN=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --force)
            FORCE_MODE=true
            shift
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --help|-h)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --force     Skip existence checks for optional sources"
            echo "  --dry-run   Show what would be done without making changes"
            echo "  --help      Show this help message"
            echo ""
            echo "Security: This script validates all source paths exist and are within"
            echo "allowed directories before creating symlinks."
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
CLAUDE_DIR="$HOME/.claude"
ONEX_DIR="$CLAUDE_DIR/onex"

echo "=== OmniClaude Claude Artifacts Deployment ==="
if [[ "$DRY_RUN" == "true" ]]; then
    echo "[DRY RUN MODE - No changes will be made]"
fi
if [[ "$FORCE_MODE" == "true" ]]; then
    echo "[FORCE MODE - Optional source checks relaxed]"
fi
echo "Repo: $REPO_ROOT"
echo "Target: $ONEX_DIR"
echo ""

# Pre-flight validation: Check all required source paths exist before deployment
# This prevents partial deployment failures
preflight_validation() {
    local missing_paths=()
    local required_sources=(
        "$REPO_ROOT/claude/hooks"
        "$REPO_ROOT/claude/skills"
        "$REPO_ROOT/claude/commands"
        "$REPO_ROOT/claude/agents"
        "$REPO_ROOT/claude/lib"
        "$REPO_ROOT/claude/plugins"
        "$REPO_ROOT/config"
    )

    echo "Running pre-flight validation..."

    for source in "${required_sources[@]}"; do
        if [[ ! -e "$source" ]]; then
            missing_paths+=("$source")
        fi
    done

    if [[ ${#missing_paths[@]} -gt 0 ]]; then
        echo ""
        echo "ERROR: Pre-flight validation failed!"
        echo "The following required source paths do not exist:"
        echo ""
        for path in "${missing_paths[@]}"; do
            echo "  - $path"
        done
        echo ""
        echo "Please ensure these directories exist before running deployment."
        echo "You may need to run: mkdir -p $REPO_ROOT/claude/{hooks,skills,commands,agents,lib,plugins}"
        exit 1
    fi

    echo "  All required source paths verified"
    echo ""
}

# Run pre-flight validation (skip in force mode)
if [[ "$FORCE_MODE" != "true" ]]; then
    preflight_validation
fi

# Create onex namespace directory
if [[ "$DRY_RUN" == "true" ]]; then
    if [[ ! -d "$ONEX_DIR" ]]; then
        echo "[DRY] Would create directory: $ONEX_DIR"
    fi
else
    mkdir -p "$ONEX_DIR"
fi

# Security: Validate path is within allowed directories
validate_source_path() {
    local source="$1"
    local resolved_source
    local final_target

    # Resolve to absolute path (handles ..)
    resolved_source="$(cd "$(dirname "$source")" 2>/dev/null && pwd)/$(basename "$source")" || {
        return 1
    }

    # Check initial path is within allowed directories
    if [[ "$resolved_source" != "$REPO_ROOT"* ]] && [[ "$resolved_source" != "$HOME"* ]]; then
        return 1
    fi

    # Security: If source is a symlink, verify final target is also within allowed paths
    # This prevents symlink traversal attacks
    if [[ -L "$resolved_source" ]]; then
        # Use readlink to get the canonical path (follows all symlinks)
        # macOS uses -f flag, which is also supported on GNU coreutils
        final_target="$(readlink -f "$resolved_source" 2>/dev/null)" || {
            # If readlink fails, reject the symlink for safety
            return 1
        }

        # Verify the final target is within allowed directories
        if [[ "$final_target" != "$REPO_ROOT"* ]] && [[ "$final_target" != "$HOME"* ]]; then
            return 1
        fi
    fi

    return 0
}

# Function to create symlink with backup and security validation
create_symlink() {
    local source="$1"
    local target="$2"
    local name="$3"
    local required="${4:-true}"  # Optional: whether source is required (default: true)

    # Convert relative source paths to absolute (security: prevent path confusion)
    if [[ "$source" != /* ]]; then
        source="$(cd "$(dirname "$source")" 2>/dev/null && pwd)/$(basename "$source")" || {
            echo "  ERROR: Cannot resolve relative path: $source"
            exit 1
        }
    fi

    # Security Check 1: Validate source path exists
    if [[ ! -e "$source" ]]; then
        if [[ "$required" == "true" ]]; then
            echo "  ERROR: Source path does not exist: $source"
            echo "  Cannot create symlink for: $name"
            echo "  Hint: Ensure the source directory/file exists before deployment"
            exit 1
        else
            # In force mode, skip warnings for optional sources
            if [[ "$FORCE_MODE" == "true" ]]; then
                echo "  SKIP: $name (source not found, --force enabled)"
                return 0
            fi
            echo "  WARNING: Skipping $name symlink, source does not exist: $source"
            return 0
        fi
    fi

    # Security Check 2: Validate source path is within allowed directories
    if ! validate_source_path "$source"; then
        echo "  ERROR: Source path is outside allowed directories: $source"
        echo "  Allowed: $REPO_ROOT or $HOME"
        echo "  Security: This check cannot be bypassed with --force"
        exit 1
    fi

    # Security Check 3: Validate paths don't contain dangerous characters
    if [[ "$source" =~ [[:cntrl:]] ]] || [[ "$target" =~ [[:cntrl:]] ]]; then
        echo "  ERROR: Path contains control characters: $name"
        echo "  Security: This check cannot be bypassed with --force"
        exit 1
    fi

    # Security Check 4: Validate target directory exists
    local target_dir
    target_dir="$(dirname "$target")"
    if [[ ! -d "$target_dir" ]]; then
        echo "  ERROR: Target directory does not exist: $target_dir"
        echo "  Cannot create symlink for: $name"
        exit 1
    fi

    # Dry-run mode: show what would be done without making changes
    if [[ "$DRY_RUN" == "true" ]]; then
        if [[ -L "$target" ]]; then
            echo "  [DRY] Would replace symlink: $name → $source"
        elif [[ -e "$target" ]]; then
            echo "  [DRY] Would backup and replace: $name → $source"
        else
            echo "  [DRY] Would create: $name → $source"
        fi
        return 0
    fi

    # Handle existing target
    if [[ -L "$target" ]]; then
        # Check if symlink already points to correct source
        local current_target
        current_target="$(readlink "$target")"
        if [[ "$current_target" == "$source" ]]; then
            echo "  = $name (already correct)"
            return 0
        fi
        rm "$target"
    elif [[ -e "$target" ]]; then
        echo "  Backing up existing $name to ${target}.bak"
        # Remove old backup if exists to prevent accumulation
        if [[ -e "${target}.bak" ]]; then
            rm -rf "${target}.bak"
        fi
        mv "$target" "${target}.bak"
    fi

    ln -s "$source" "$target"
    echo "  + $name -> $source"
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
# Check if poetry is installed before attempting to get venv path
if ! command -v poetry >/dev/null 2>&1; then
    echo ""
    echo "WARNING: poetry is not installed. Python virtual environment symlink skipped."
    echo "  Install poetry: curl -sSL https://install.python-poetry.org | python3 -"
    echo "  Then run: poetry install"
    VENV_PATH=""
else
    VENV_PATH=$(cd "$REPO_ROOT" && poetry env info --path 2>/dev/null || echo "")
fi
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
if [[ "$DRY_RUN" == "true" ]]; then
    echo "=== Dry Run Complete ==="
    echo ""
    echo "No changes were made. Run without --dry-run to apply changes."
else
    echo "=== Deployment Complete ==="
    echo ""
    echo "Structure:"
    echo "  ~/.claude/"
    echo "    |-- hooks/      -> $REPO_ROOT/claude/hooks/"
    echo "    |-- skills/     -> $REPO_ROOT/claude/skills/"
    echo "    |-- commands/   -> $REPO_ROOT/claude/commands/"
    echo "    \`-- agent-definitions/ -> $REPO_ROOT/claude/agents/"
    echo ""
    echo "All Python code can now import from 'claude.lib'"
fi
