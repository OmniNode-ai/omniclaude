#!/bin/bash
# deploy-local-plugin: Sync local plugin to Claude Code cache
#
# Usage:
#   ./deploy.sh [--execute] [--no-version-bump]
#
# Default: Dry run (preview only)
# --execute: Actually perform deployment
# --no-version-bump: Skip patch version increment

set -euo pipefail

# Check required dependencies
for cmd in jq rsync; do
    if ! command -v "$cmd" &>/dev/null; then
        echo "Error: Required command '$cmd' not found"
        exit 1
    fi
done

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Parse arguments
EXECUTE=false
NO_VERSION_BUMP=false

for arg in "$@"; do
    case $arg in
        --execute)
            EXECUTE=true
            shift
            ;;
        --no-version-bump)
            NO_VERSION_BUMP=true
            shift
            ;;
        --help|-h)
            echo "Usage: deploy.sh [--execute] [--no-version-bump]"
            echo ""
            echo "Options:"
            echo "  --execute         Actually perform deployment (default: dry run)"
            echo "  --no-version-bump Skip auto-incrementing patch version"
            echo "  --help            Show this help message"
            exit 0
            ;;
        *)
            echo "Unknown argument: $arg"
            echo "Use --help for usage"
            exit 1
            ;;
    esac
done

# Determine source directory
# Try CLAUDE_PLUGIN_ROOT first, then fall back to script location
if [[ -n "${CLAUDE_PLUGIN_ROOT:-}" ]]; then
    SOURCE_ROOT="$CLAUDE_PLUGIN_ROOT"
else
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    SOURCE_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
fi

PLUGIN_JSON="${SOURCE_ROOT}/.claude-plugin/plugin.json"
CACHE_BASE="$HOME/.claude/plugins/cache/omninode-tools/onex"
REGISTRY="$HOME/.claude/plugins/installed_plugins.json"

# Verify source exists
if [[ ! -f "$PLUGIN_JSON" ]]; then
    echo -e "${RED}Error: plugin.json not found at $PLUGIN_JSON${NC}"
    exit 1
fi

# Read current version
CURRENT_VERSION=$(jq -r '.version' "$PLUGIN_JSON")

if [[ -z "$CURRENT_VERSION" || "$CURRENT_VERSION" == "null" ]]; then
    echo -e "${RED}Error: Could not read version from plugin.json${NC}"
    exit 1
fi

# Validate version format (must be X.Y.Z semver)
if ! [[ "$CURRENT_VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    echo -e "${RED}Error: Version '$CURRENT_VERSION' is not valid semver (X.Y.Z)${NC}"
    exit 1
fi

# Calculate new version
if [[ "$NO_VERSION_BUMP" == "true" ]]; then
    NEW_VERSION="$CURRENT_VERSION"
else
    IFS='.' read -r MAJOR MINOR PATCH <<< "$CURRENT_VERSION"
    NEW_PATCH=$((PATCH + 1))
    NEW_VERSION="${MAJOR}.${MINOR}.${NEW_PATCH}"
fi

TARGET="${CACHE_BASE}/${NEW_VERSION}"

# Count files in each component
count_commands() {
    ls -1 "${SOURCE_ROOT}/commands/"*.md 2>/dev/null | wc -l | tr -d ' '
}

count_skills() {
    ls -1d "${SOURCE_ROOT}/skills"/*/ 2>/dev/null | wc -l | tr -d ' '
}

count_agents() {
    ls -1 "${SOURCE_ROOT}/agents/configs/"*.yaml 2>/dev/null | wc -l | tr -d ' '
}

count_hooks() {
    ls -1 "${SOURCE_ROOT}/hooks/" 2>/dev/null | wc -l | tr -d ' '
}

# Print header
echo ""
if [[ "$EXECUTE" == "true" ]]; then
    echo -e "${GREEN}=== Plugin Deployment ===${NC}"
else
    echo -e "${YELLOW}=== Plugin Deployment Preview (DRY RUN) ===${NC}"
fi
echo ""

# Print version info
if [[ "$NO_VERSION_BUMP" == "true" ]]; then
    echo -e "Version: ${BLUE}${CURRENT_VERSION}${NC} (no bump)"
else
    echo -e "Version: ${BLUE}${CURRENT_VERSION}${NC} -> ${GREEN}${NEW_VERSION}${NC}"
fi
echo ""

# Print paths
echo "Source:  ${SOURCE_ROOT}"
echo "Target:  ${TARGET}"
echo ""

# Print component counts
echo "Components to sync:"
echo "  commands/:      $(count_commands) files"
echo "  skills/:        $(count_skills) directories"
echo "  agents/configs: $(count_agents) files"
echo "  hooks/:         $(count_hooks) items"
echo "  .claude-plugin: plugin.json + metadata"
echo ""

# Check if target exists
if [[ -d "$TARGET" ]]; then
    echo -e "${YELLOW}Warning: Target directory exists, will overwrite${NC}"
    echo ""
fi

# Execute or show instruction
if [[ "$EXECUTE" == "true" ]]; then
    echo "Deploying..."
    echo ""

    # Update version in source plugin.json first (if bumping)
    if [[ "$NO_VERSION_BUMP" != "true" ]]; then
        jq --arg v "$NEW_VERSION" '.version = $v' "$PLUGIN_JSON" > "${PLUGIN_JSON}.tmp"
        mv "${PLUGIN_JSON}.tmp" "$PLUGIN_JSON"
        echo -e "${GREEN}  Updated plugin.json version to ${NEW_VERSION}${NC}"
    fi

    # Create target directory
    mkdir -p "$TARGET"
    echo -e "${GREEN}  Created target directory${NC}"

    # Sync components
    echo "  Syncing commands..."
    rsync -a --delete "${SOURCE_ROOT}/commands/" "${TARGET}/commands/"

    echo "  Syncing skills..."
    rsync -a --delete "${SOURCE_ROOT}/skills/" "${TARGET}/skills/"

    echo "  Syncing agents..."
    rsync -a --delete "${SOURCE_ROOT}/agents/" "${TARGET}/agents/"

    echo "  Syncing hooks..."
    rsync -a --delete "${SOURCE_ROOT}/hooks/" "${TARGET}/hooks/"

    echo "  Syncing .claude-plugin..."
    rsync -a --delete "${SOURCE_ROOT}/.claude-plugin/" "${TARGET}/.claude-plugin/"

    # Copy additional files (ignore errors if not present)
    [[ -f "${SOURCE_ROOT}/.env.example" ]] && cp "${SOURCE_ROOT}/.env.example" "${TARGET}/"
    [[ -f "${SOURCE_ROOT}/README.md" ]] && cp "${SOURCE_ROOT}/README.md" "${TARGET}/"
    [[ -f "${SOURCE_ROOT}/ENVIRONMENT_VARIABLES.md" ]] && cp "${SOURCE_ROOT}/ENVIRONMENT_VARIABLES.md" "${TARGET}/"

    # Create .claude directory if it exists in source
    [[ -d "${SOURCE_ROOT}/.claude" ]] && rsync -a --delete "${SOURCE_ROOT}/.claude/" "${TARGET}/.claude/"

    echo ""

    # Update registry
    if [[ -f "$REGISTRY" ]]; then
        # Verify expected structure exists before updating
        if jq -e '.plugins["onex@omninode-tools"][0]' "$REGISTRY" >/dev/null 2>&1; then
            TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%S.000Z")

            jq --arg ts "$TIMESTAMP" --arg v "$NEW_VERSION" --arg p "$TARGET" '
                .plugins["onex@omninode-tools"][0].lastUpdated = $ts |
                .plugins["onex@omninode-tools"][0].version = $v |
                .plugins["onex@omninode-tools"][0].installPath = $p
            ' "$REGISTRY" > "${REGISTRY}.tmp" && mv "${REGISTRY}.tmp" "$REGISTRY"

            echo -e "${GREEN}  Updated installed_plugins.json${NC}"
        else
            echo -e "${YELLOW}  Warning: Plugin entry not found in registry (skipping update)${NC}"
        fi
    else
        echo -e "${YELLOW}  Warning: Registry not found at ${REGISTRY}${NC}"
    fi

    echo ""
    echo -e "${GREEN}Deployment complete!${NC}"
    echo ""
    echo "Restart Claude Code to load the new version."
else
    echo -e "${YELLOW}This is a dry run. Use --execute to apply changes.${NC}"
fi

echo ""
