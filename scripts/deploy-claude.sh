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
#
# Dependencies:
#   - jq (for JSON manipulation in hook configuration)
#   - bash 4.0+ (for associative arrays and advanced features)
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
# Namespace for this project's artifacts within each artifact type directory
PROJECT_NAMESPACE="omniclaude"

echo "=== OmniClaude Claude Artifacts Deployment ==="
if [[ "$DRY_RUN" == "true" ]]; then
    echo "[DRY RUN MODE - No changes will be made]"
fi
if [[ "$FORCE_MODE" == "true" ]]; then
    echo "[FORCE MODE - Optional source checks relaxed]"
fi
echo "Repo: $REPO_ROOT"
echo "Target: $CLAUDE_DIR/<artifact-type>/$PROJECT_NAMESPACE"
echo ""

# Pre-flight validation: Check all required source paths exist before deployment
# This prevents partial deployment failures
preflight_validation() {
    local missing_paths=()
    local required_sources=(
        "$REPO_ROOT/claude/skills"
        "$REPO_ROOT/claude/commands"
        "$REPO_ROOT/claude/agents"
        "$REPO_ROOT/claude/lib"
        "$REPO_ROOT/claude/plugins"
        "$REPO_ROOT/claude/hooks"
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

# Create artifact type directories with project namespace
# Structure: ~/.claude/<artifact-type>/omniclaude/ -> repo/claude/<artifact-type>/
ARTIFACT_TYPES=("skills" "commands" "agents" "lib" "plugins")
for type in "${ARTIFACT_TYPES[@]}"; do
    type_dir="$CLAUDE_DIR/$type"
    if [[ "$DRY_RUN" == "true" ]]; then
        if [[ ! -d "$type_dir" ]]; then
            echo "[DRY] Would create directory: $type_dir"
        fi
    else
        mkdir -p "$type_dir"
    fi
done

# Also create config directory
if [[ "$DRY_RUN" == "true" ]]; then
    if [[ ! -d "$CLAUDE_DIR/config" ]]; then
        echo "[DRY] Would create directory: $CLAUDE_DIR/config"
    fi
else
    mkdir -p "$CLAUDE_DIR/config"
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

    # Dry-run mode: show what would be done without making changes
    # Check this BEFORE target directory validation since dirs aren't created in dry-run
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

    # Security Check 4: Validate target directory exists
    local target_dir
    target_dir="$(dirname "$target")"
    if [[ ! -d "$target_dir" ]]; then
        echo "  ERROR: Target directory does not exist: $target_dir"
        echo "  Cannot create symlink for: $name"
        exit 1
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

# Create symlinks within each artifact type directory
# Structure: ~/.claude/<type>/omniclaude -> repo/claude/<type>
# NOTE: Hooks are NOT symlinked - settings.json points directly to repo paths
echo "Creating namespaced symlinks..."
create_symlink "$REPO_ROOT/claude/skills" "$CLAUDE_DIR/skills/$PROJECT_NAMESPACE" "skills/$PROJECT_NAMESPACE"
create_symlink "$REPO_ROOT/claude/commands" "$CLAUDE_DIR/commands/$PROJECT_NAMESPACE" "commands/$PROJECT_NAMESPACE"
create_symlink "$REPO_ROOT/claude/agents" "$CLAUDE_DIR/agents/$PROJECT_NAMESPACE" "agents/$PROJECT_NAMESPACE"
create_symlink "$REPO_ROOT/claude/lib" "$CLAUDE_DIR/lib/$PROJECT_NAMESPACE" "lib/$PROJECT_NAMESPACE"
create_symlink "$REPO_ROOT/claude/plugins" "$CLAUDE_DIR/plugins/$PROJECT_NAMESPACE" "plugins/$PROJECT_NAMESPACE"

echo ""
echo "Symlinking shared resources..."
# .env is optional - warn but don't fail if missing
create_symlink "$REPO_ROOT/.env" "$CLAUDE_DIR/.env" ".env" "false"
create_symlink "$REPO_ROOT/config" "$CLAUDE_DIR/config/$PROJECT_NAMESPACE" "config/$PROJECT_NAMESPACE"

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
    # Place venv in lib/omniclaude/.venv for Python import resolution
    create_symlink "$VENV_PATH" "$CLAUDE_DIR/lib/$PROJECT_NAMESPACE/.venv" "lib/$PROJECT_NAMESPACE/.venv" "false"
    echo ""
    echo "Poetry venv linked: $VENV_PATH"
else
    echo ""
    echo "Poetry venv not found. Run 'poetry install' first."
fi

# =============================================================================
# Configure hooks in ~/.claude/settings.json
# =============================================================================

# Function to configure hooks in settings.json
configure_hooks() {
    local settings_file="$CLAUDE_DIR/settings.json"
    local hooks_dir="$REPO_ROOT/claude/hooks"

    echo ""
    echo "Configuring hooks in settings.json..."

    # Validate hooks exist
    local user_prompt_hook="$hooks_dir/user-prompt-submit.sh"
    local post_tool_hook="$hooks_dir/post_tool_use_enforcer.py"
    local session_start_hook="$hooks_dir/session-start.sh"

    local missing_hooks=()
    [[ ! -f "$user_prompt_hook" ]] && missing_hooks+=("$user_prompt_hook")
    [[ ! -f "$post_tool_hook" ]] && missing_hooks+=("$post_tool_hook")
    [[ ! -f "$session_start_hook" ]] && missing_hooks+=("$session_start_hook")

    if [[ ${#missing_hooks[@]} -gt 0 ]]; then
        echo "  ERROR: Missing hook files:"
        for hook in "${missing_hooks[@]}"; do
            echo "    - $hook"
        done
        echo "  Hook configuration skipped."
        return 1
    fi

    # Verify jq is available for JSON manipulation
    if ! command -v jq &> /dev/null; then
        echo "  ERROR: jq is required for hook configuration but not found"
        echo "  Install with: brew install jq"
        return 1
    fi

    # Create hooks JSON structure
    local hooks_json
    hooks_json=$(jq -n \
        --arg user_prompt "$user_prompt_hook" \
        --arg post_tool "$post_tool_hook" \
        --arg session_start "$session_start_hook" \
        '{
            "UserPromptSubmit": [
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": $user_prompt,
                            "timeout": 10
                        }
                    ]
                }
            ],
            "PostToolUse": [
                {
                    "matcher": "*",
                    "hooks": [
                        {
                            "type": "command",
                            "command": $post_tool,
                            "timeout": 5
                        }
                    ]
                }
            ],
            "SessionStart": [
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": $session_start,
                            "timeout": 5
                        }
                    ]
                }
            ]
        }')

    if [[ "$DRY_RUN" == "true" ]]; then
        echo "  [DRY] Would configure hooks in: $settings_file"
        echo "  [DRY] UserPromptSubmit -> $user_prompt_hook"
        echo "  [DRY] PostToolUse (*) -> $post_tool_hook"
        echo "  [DRY] SessionStart -> $session_start_hook"
        return 0
    fi

    # Create settings.json if it doesn't exist
    if [[ ! -f "$settings_file" ]]; then
        echo "  Creating new settings.json..."
        echo '{}' > "$settings_file"
    fi

    # Backup existing settings.json
    if [[ -f "$settings_file" ]]; then
        cp "$settings_file" "${settings_file}.bak"
    fi

    # Merge hooks into existing settings (preserves other settings)
    local updated_settings
    updated_settings=$(jq --argjson hooks "$hooks_json" '.hooks = $hooks' "$settings_file")

    if [[ -z "$updated_settings" ]]; then
        echo "  ERROR: Failed to update settings.json"
        # Restore backup
        [[ -f "${settings_file}.bak" ]] && mv "${settings_file}.bak" "$settings_file"
        return 1
    fi

    # Write updated settings
    echo "$updated_settings" > "$settings_file"

    echo "  + UserPromptSubmit -> $user_prompt_hook"
    echo "  + PostToolUse (*) -> $post_tool_hook"
    echo "  + SessionStart -> $session_start_hook"
    echo "  Hooks configured successfully."

    # Clean up backup on success
    rm -f "${settings_file}.bak"

    return 0
}

# Configure hooks (after symlink creation)
configure_hooks || echo "WARNING: Hook configuration failed (non-fatal)"

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
    echo "    |-- skills/$PROJECT_NAMESPACE/ -> $REPO_ROOT/claude/skills/"
    echo "    |-- commands/$PROJECT_NAMESPACE/ -> $REPO_ROOT/claude/commands/"
    echo "    |-- agents/$PROJECT_NAMESPACE/ -> $REPO_ROOT/claude/agents/"
    echo "    |-- lib/$PROJECT_NAMESPACE/ -> $REPO_ROOT/claude/lib/"
    echo "    |-- plugins/$PROJECT_NAMESPACE/ -> $REPO_ROOT/claude/plugins/"
    echo "    |-- config/$PROJECT_NAMESPACE/ -> $REPO_ROOT/config/"
    echo "    \`-- settings.json (hooks configured)"
    echo ""
    echo "Hooks:"
    echo "  UserPromptSubmit -> $REPO_ROOT/claude/hooks/user-prompt-submit.sh"
    echo "  PostToolUse (*)  -> $REPO_ROOT/claude/hooks/post_tool_use_enforcer.py"
    echo "  SessionStart     -> $REPO_ROOT/claude/hooks/session-start.sh"
    echo ""
    echo "Access pattern: ~/.claude/<type>/$PROJECT_NAMESPACE/<component>"
    echo "Example: ~/.claude/skills/$PROJECT_NAMESPACE/pr-review/collate-issues"
fi
