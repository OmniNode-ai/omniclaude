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
            ;;
        --no-version-bump)
            NO_VERSION_BUMP=true
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

# Read current version (use jq -e to exit non-zero on null/missing rather
# than relying on fragile string comparison with "null")
if ! CURRENT_VERSION=$(jq -re '.version' "$PLUGIN_JSON" 2>/dev/null) || [[ -z "$CURRENT_VERSION" ]]; then
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

# Validate required source directories exist
REQUIRED_DIRS=("commands" "skills" "agents" "hooks" ".claude-plugin")
MISSING_DIRS=()

for dir in "${REQUIRED_DIRS[@]}"; do
    if [[ ! -d "${SOURCE_ROOT}/${dir}" ]]; then
        MISSING_DIRS+=("$dir")
    fi
done

if [[ ${#MISSING_DIRS[@]} -gt 0 ]]; then
    echo -e "${RED}Error: Required source directories missing:${NC}"
    for dir in "${MISSING_DIRS[@]}"; do
        echo -e "${RED}  - ${SOURCE_ROOT}/${dir}${NC}"
    done
    exit 1
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

    # =============================================================================
    # Bundled Python Venv (per-plugin isolation)
    # =============================================================================
    # Creates a self-contained venv with all Python deps at <cache>/lib/.venv/.
    # If any step fails, deploy exits non-zero and the registry is untouched.
    # Note: TARGET dir (synced files) may persist on failure; re-deploy overwrites it.
    # No fallbacks. Either the venv works or the deploy fails.

    echo "Creating bundled Python venv..."

    # The project root is two levels up from SOURCE_ROOT (which points to plugins/onex)
    PROJECT_ROOT_FOR_INSTALL="$(cd "${SOURCE_ROOT}/../.." && pwd)"

    # --- Validate Python >= 3.12 ---
    PYTHON_BIN="python3"
    if ! command -v "$PYTHON_BIN" &>/dev/null; then
        echo -e "${RED}Error: python3 not found in PATH. Python 3.12+ required.${NC}"
        exit 1
    fi
    PY_MAJOR=$("$PYTHON_BIN" -c "import sys; print(sys.version_info.major)")
    PY_MINOR=$("$PYTHON_BIN" -c "import sys; print(sys.version_info.minor)")
    if [[ "${PY_MAJOR}" -lt 3 ]] || { [[ "${PY_MAJOR}" -eq 3 ]] && [[ "${PY_MINOR}" -lt 12 ]]; }; then
        echo -e "${RED}Error: Python ${PY_MAJOR}.${PY_MINOR} found, but >= 3.12 required.${NC}"
        exit 1
    fi
    echo -e "${GREEN}  Python ${PY_MAJOR}.${PY_MINOR} validated${NC}"

    # --- Create venv (clean state) ---
    VENV_DIR="${TARGET}/lib/.venv"
    rm -rf "$VENV_DIR"
    mkdir -p "${TARGET}/lib"
    "$PYTHON_BIN" -m venv "$VENV_DIR"
    echo -e "${GREEN}  Venv created at ${VENV_DIR}${NC}"

    # --- Bootstrap pip toolchain ---
    if ! "$VENV_DIR/bin/python3" -m ensurepip --upgrade 2>&1; then
        echo -e "${RED}Error: ensurepip failed. Python may lack the ensurepip module (common on minimal installs).${NC}"
        rm -rf "$VENV_DIR"
        exit 1
    fi
    "$VENV_DIR/bin/pip" install --upgrade pip wheel --quiet
    echo -e "${GREEN}  pip toolchain bootstrapped${NC}"

    # --- Install project (non-editable, no cache) ---
    echo "  Installing project from ${PROJECT_ROOT_FOR_INSTALL}..."
    if ! "$VENV_DIR/bin/pip" install --no-cache-dir "${PROJECT_ROOT_FOR_INSTALL}" --quiet; then
        echo -e "${RED}Error: pip install failed for ${PROJECT_ROOT_FOR_INSTALL}. Deploy aborted.${NC}"
        rm -rf "$VENV_DIR"
        exit 1
    fi
    echo -e "${GREEN}  Project installed into venv${NC}"

    # --- Write venv manifest ---
    MANIFEST="${TARGET}/lib/venv_manifest.txt"
    {
        echo "# Plugin Venv Manifest"
        echo "# Generated: $(date -u +"%Y-%m-%dT%H:%M:%SZ")"
        echo "# Deploy version: ${NEW_VERSION}"
        echo ""
        echo "python_version: $("$VENV_DIR/bin/python3" --version 2>&1)"
        echo "pip_version: $("$VENV_DIR/bin/pip" --version 2>&1)"
        echo "source_root: ${PROJECT_ROOT_FOR_INSTALL}"
        echo "git_sha: $(cd "${PROJECT_ROOT_FOR_INSTALL}" && git rev-parse HEAD 2>/dev/null || echo 'unknown')"
        echo ""
        echo "# Installed packages:"
        "$VENV_DIR/bin/pip" freeze 2>/dev/null
    } > "$MANIFEST"
    echo -e "${GREEN}  Venv manifest written to ${MANIFEST}${NC}"

    # --- Smoke test ---
    if "$VENV_DIR/bin/python3" -c "import omnibase_spi; import omniclaude; from omniclaude.hooks.topics import TopicBase; print('Smoke test: OK')" 2>&1; then
        echo -e "${GREEN}  Bundled venv smoke test passed${NC}"
    else
        echo -e "${RED}Error: Bundled venv smoke test FAILED. Deploy aborted.${NC}"
        echo "  The following imports must work:"
        echo "    import omnibase_spi"
        echo "    import omniclaude"
        echo "    from omniclaude.hooks.topics import TopicBase"
        rm -rf "$VENV_DIR"  # Clean up failed venv
        rm -f "$MANIFEST"   # Clean up stale manifest
        exit 1
    fi

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

    # Update known_marketplaces.json — point installLocation at the repo root
    # (NOT the cache). Claude Code uses this for plugin/skill discovery via
    # .claude-plugin/marketplace.json. Pointing to cache breaks skill loading.
    KNOWN_MARKETPLACES="$HOME/.claude/plugins/known_marketplaces.json"
    if [[ -f "$KNOWN_MARKETPLACES" ]]; then
        if jq -e '.["omninode-tools"]' "$KNOWN_MARKETPLACES" >/dev/null 2>&1; then
            TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%S.000Z")

            jq --arg p "$PROJECT_ROOT_FOR_INSTALL" --arg ts "$TIMESTAMP" '
                .["omninode-tools"].source.source = "directory" |
                .["omninode-tools"].source.path = $p |
                del(.["omninode-tools"].source.repo) |
                del(.["omninode-tools"].source.ref) |
                .["omninode-tools"].installLocation = $p |
                .["omninode-tools"].lastUpdated = $ts
            ' "$KNOWN_MARKETPLACES" > "${KNOWN_MARKETPLACES}.tmp" && mv "${KNOWN_MARKETPLACES}.tmp" "$KNOWN_MARKETPLACES"

            echo -e "${GREEN}  Updated known_marketplaces.json (installLocation: $PROJECT_ROOT_FOR_INSTALL)${NC}"
        else
            echo -e "${YELLOW}  Warning: omninode-tools not found in known_marketplaces.json${NC}"
        fi
    fi

    # Update statusLine in settings.json to point at new version's statusline.sh
    SETTINGS_JSON="$HOME/.claude/settings.json"
    if [[ -f "$SETTINGS_JSON" ]]; then
        # Use ~ prefix: Claude Code's settings parser expands ~ to $HOME
        STATUSLINE_PATH_SHORT="~/.claude/plugins/cache/omninode-tools/onex/${NEW_VERSION}/hooks/scripts/statusline.sh"

        if jq -e '.statusLine.command' "$SETTINGS_JSON" >/dev/null 2>&1; then
            # Backup before modification (recoverable if jq fails mid-write)
            cp "$SETTINGS_JSON" "${SETTINGS_JSON}.bak"
            jq --arg cmd "$STATUSLINE_PATH_SHORT" '
                .statusLine.command = $cmd
            ' "$SETTINGS_JSON" > "${SETTINGS_JSON}.tmp" && mv "${SETTINGS_JSON}.tmp" "$SETTINGS_JSON"

            # Validate the target statusline.sh actually exists (tilde is
            # expanded by Claude Code's settings parser, not the shell)
            STATUSLINE_EXPANDED="${TARGET}/hooks/scripts/statusline.sh"
            if [[ ! -f "$STATUSLINE_EXPANDED" ]]; then
                echo -e "${YELLOW}  Warning: statusline.sh not found at ${STATUSLINE_EXPANDED}${NC}"
                echo -e "${YELLOW}  Settings updated but statusline may not work until file is present${NC}"
            fi

            echo -e "${GREEN}  Updated settings.json statusLine -> ${STATUSLINE_PATH_SHORT}${NC}"
        fi
    fi

    # Copy plugin components to ~/.claude namespace directories (real copies, not symlinks)
    CLAUDE_DIR="$HOME/.claude"
    mkdir -p "$CLAUDE_DIR/commands" "$CLAUDE_DIR/skills" "$CLAUDE_DIR/agents"

    # Remove stale symlinks, then rsync fresh copies (overwrite in place).
    for component in commands skills agents; do
        DEST="$CLAUDE_DIR/$component/onex"
        [[ -L "$DEST" ]] && rm -f "$DEST"
        mkdir -p "$DEST"
        rsync -a --delete "$TARGET/$component/" "$DEST/"
    done

    echo -e "${GREEN}  Copied commands/skills/agents to ~/.claude/ (no symlinks)${NC}"

    echo ""
    echo -e "${GREEN}Deployment complete!${NC}"
    echo ""
    echo "Restart Claude Code to load the new version."
else
    echo -e "${YELLOW}This is a dry run. Use --execute to apply changes.${NC}"
fi

echo ""
