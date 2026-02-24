#!/bin/bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# deploy-local-plugin: Sync local plugin to Claude Code cache
#
# Usage:
#   ./deploy.sh [--execute] [--bump-version]
#   ./deploy.sh --repair-venv
#
# Default: Dry run, deploys to same version (no bump)
# --execute: Actually perform deployment (sync files + build venv)
# --bump-version: Increment patch version before deploying
# --repair-venv: Build lib/.venv in the currently-active deployed version (no file sync, no version bump)
#                Use this when hooks fail with "No valid Python found" after a deploy.
# Deploys to plugin cache ONLY. Skills/commands/agents discovered via plugin installPath.

set -euo pipefail

# Check required dependencies
# rsync is only required for full deploys, not for --repair-venv
_NEED_RSYNC=true
for arg in "$@"; do [[ "$arg" == "--repair-venv" ]] && { _NEED_RSYNC=false; break; }; done

for cmd in jq; do
    if ! command -v "$cmd" &>/dev/null; then
        echo "Error: Required command '$cmd' not found"
        exit 1
    fi
done
if [[ "$_NEED_RSYNC" == "true" ]] && ! command -v rsync &>/dev/null; then
    echo "Error: Required command 'rsync' not found"
    exit 1
fi
unset _NEED_RSYNC

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Parse arguments
EXECUTE=false
NO_VERSION_BUMP=true
BUMP_VERSION=false
REPAIR_VENV=false

for arg in "$@"; do
    case $arg in
        --execute)
            EXECUTE=true
            ;;
        --no-version-bump)
            echo -e "${YELLOW}Warning: --no-version-bump is deprecated; no-bump is now the default. Use --bump-version to increment.${NC}" >&2
            NO_VERSION_BUMP=true
            ;;
        --bump-version)
            NO_VERSION_BUMP=false
            BUMP_VERSION=true
            ;;
        --repair-venv)
            REPAIR_VENV=true
            ;;
        --help|-h)
            echo "Usage: deploy.sh [--execute] [--bump-version]"
            echo "       deploy.sh --repair-venv"
            echo ""
            echo "Options:"
            echo "  --execute         Actually perform deployment (default: dry run)"
            echo "  --bump-version    Increment patch version (default: deploy to same version)"
            echo "  --repair-venv     Build lib/.venv in the active deployed version without a full redeploy."
            echo "                    Use when hooks fail with 'No valid Python found' after a deploy."
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

# Guard: --no-version-bump and --bump-version are mutually exclusive.
# Since --no-version-bump sets NO_VERSION_BUMP=true and --bump-version sets
# BUMP_VERSION=true, detect the conflict explicitly rather than relying on
# argument order (last-writer-wins is confusing and unpredictable).
if [[ "$NO_VERSION_BUMP" == "true" && "$BUMP_VERSION" == "true" ]]; then
    echo -e "${RED}Error: --no-version-bump and --bump-version are mutually exclusive.${NC}" >&2
    exit 1
fi

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

# =============================================================================
# --repair-venv: Provision lib/.venv in the active deployed version.
# =============================================================================
# This mode is used when hooks fail with "No valid Python found" because lib/.venv
# was not built — for example, if the cache dir was populated by rsync/git-clone
# instead of a full deploy.sh --execute run, or if the venv build was interrupted.
#
# Steps:
#   1. Read installPath from installed_plugins.json (the live cache version)
#   2. Resolve PROJECT_ROOT from this repo (for pip install source)
#   3. Build lib/.venv in-place under installPath/lib/
#   4. Run smoke test; exit non-zero on failure (no registry mutation)
# =============================================================================
if [[ "$REPAIR_VENV" == "true" ]]; then
    echo ""
    echo -e "${GREEN}=== Repair Venv ===${NC}"
    echo ""

    # --- Find the active installed version ---
    if [[ ! -f "$REGISTRY" ]]; then
        echo -e "${RED}Error: Registry not found at ${REGISTRY}${NC}"
        echo -e "${RED}Cannot determine active install path. Run a full deploy first.${NC}"
        exit 1
    fi
    if ! ACTIVE_INSTALL_PATH=$(jq -re '.plugins["onex@omninode-tools"][0].installPath' "$REGISTRY" 2>/dev/null) \
        || [[ -z "$ACTIVE_INSTALL_PATH" ]]; then
        echo -e "${RED}Error: Could not read installPath from registry${NC}"
        echo -e "${RED}Run a full deploy first: ./deploy.sh --execute${NC}"
        exit 1
    fi
    ACTIVE_VERSION=$(jq -re '.plugins["onex@omninode-tools"][0].version' "$REGISTRY" 2>/dev/null || echo "unknown")

    echo "Active install: ${ACTIVE_INSTALL_PATH} (version ${ACTIVE_VERSION})"
    echo ""

    if [[ ! -d "$ACTIVE_INSTALL_PATH" ]]; then
        echo -e "${RED}Error: Active install path does not exist: ${ACTIVE_INSTALL_PATH}${NC}"
        echo -e "${RED}Run a full deploy first: ./deploy.sh --execute${NC}"
        exit 1
    fi

    REPAIR_VENV_DIR="${ACTIVE_INSTALL_PATH}/lib/.venv"
    if [[ -d "$REPAIR_VENV_DIR" && -x "${REPAIR_VENV_DIR}/bin/python3" ]]; then
        echo -e "${YELLOW}lib/.venv already exists at ${REPAIR_VENV_DIR}${NC}"
        echo ""
        echo "Running smoke test to verify..."
        if "${REPAIR_VENV_DIR}/bin/python3" -c "import omnibase_spi; import omniclaude; from omniclaude.hooks.topics import TopicBase; print('Smoke test: OK')" 2>&1; then
            echo -e "${GREEN}Venv is healthy. No repair needed.${NC}"
            echo ""
            exit 0
        else
            echo -e "${YELLOW}Venv exists but smoke test failed. Rebuilding...${NC}"
            rm -rf "$REPAIR_VENV_DIR"
        fi
    fi

    # Rebuild venv if still missing (either wasn't there or was just removed above)
    if [[ ! -d "$REPAIR_VENV_DIR" || ! -x "${REPAIR_VENV_DIR}/bin/python3" ]]; then
        # --- Resolve PROJECT_ROOT (same logic as full deploy) ---
        if ! REPAIR_PROJECT_ROOT="$(git -C "${SOURCE_ROOT}" rev-parse --show-toplevel 2>/dev/null)"; then
            echo -e "${RED}Error: Could not determine repo root via git rev-parse.${NC}"
            echo -e "${RED}Ensure SOURCE_ROOT (${SOURCE_ROOT}) is inside the omniclaude git repo.${NC}"
            exit 1
        fi
        if [[ ! -f "${REPAIR_PROJECT_ROOT}/pyproject.toml" ]]; then
            echo -e "${RED}Error: pyproject.toml not found at ${REPAIR_PROJECT_ROOT}${NC}"
            exit 1
        fi
        echo "Project root: ${REPAIR_PROJECT_ROOT}"

        # --- Validate Python >= 3.12 ---
        REPAIR_PYTHON_BIN="python3"
        if ! command -v "$REPAIR_PYTHON_BIN" &>/dev/null; then
            echo -e "${RED}Error: python3 not found in PATH. Python 3.12+ required.${NC}"
            exit 1
        fi
        PY_MAJOR=$("$REPAIR_PYTHON_BIN" -c "import sys; print(sys.version_info.major)")
        PY_MINOR=$("$REPAIR_PYTHON_BIN" -c "import sys; print(sys.version_info.minor)")
        if [[ "${PY_MAJOR}" -lt 3 ]] || { [[ "${PY_MAJOR}" -eq 3 ]] && [[ "${PY_MINOR}" -lt 12 ]]; }; then
            echo -e "${RED}Error: Python ${PY_MAJOR}.${PY_MINOR} found, but >= 3.12 required.${NC}"
            exit 1
        fi
        echo -e "${GREEN}Python ${PY_MAJOR}.${PY_MINOR} validated${NC}"
        echo ""

        echo "Building lib/.venv at ${REPAIR_VENV_DIR}..."
        REPAIR_LOCKED_REQS=$(mktemp /tmp/omniclaude-repair-reqs.XXXXXX)
        REPAIR_UV_STDERR="$(mktemp /tmp/omniclaude-repair-uv-err.XXXXXX)"
        _REPAIR_TRAP_REMOVE=false
        trap '[[ "${_REPAIR_TRAP_REMOVE:-false}" == "true" ]] && rm -rf "${REPAIR_VENV_DIR:-}"; rm -f "${REPAIR_LOCKED_REQS:-}" "${REPAIR_UV_STDERR:-}"' EXIT

        mkdir -p "${ACTIVE_INSTALL_PATH}/lib"
        "$REPAIR_PYTHON_BIN" -m venv "$REPAIR_VENV_DIR"
        _REPAIR_TRAP_REMOVE=true
        echo -e "${GREEN}  Venv created${NC}"

        if ! "${REPAIR_VENV_DIR}/bin/python3" -m ensurepip --upgrade 2>&1; then
            echo -e "${RED}Error: ensurepip failed.${NC}"
            rm -rf "$REPAIR_VENV_DIR"
            exit 1
        fi
        "${REPAIR_VENV_DIR}/bin/pip" install --upgrade pip wheel --quiet
        echo -e "${GREEN}  pip toolchain bootstrapped${NC}"

        echo "  Installing project from ${REPAIR_PROJECT_ROOT} (locked versions)..."
        _REPAIR_USE_LOCKED=false
        if command -v uv &>/dev/null && [[ -f "${REPAIR_PROJECT_ROOT}/uv.lock" ]]; then
            if (cd "${REPAIR_PROJECT_ROOT}" && uv export --frozen --no-dev --no-hashes --format requirements-txt > "$REPAIR_LOCKED_REQS" 2>"$REPAIR_UV_STDERR"); then
                if [ ! -s "$REPAIR_LOCKED_REQS" ]; then
                    echo -e "${YELLOW}  WARNING: uv export produced empty requirements file; falling back to pip install${NC}"
                    rm -f "$REPAIR_LOCKED_REQS"
                else
                    _REPAIR_USE_LOCKED=true
                fi
            else
                if [ -s "$REPAIR_UV_STDERR" ]; then
                    echo -e "${YELLOW}  WARNING: uv export failed: $(head -3 "$REPAIR_UV_STDERR")${NC}"
                fi
                rm -f "$REPAIR_LOCKED_REQS"
            fi
        fi
        rm -f "$REPAIR_UV_STDERR"

        if [[ "$_REPAIR_USE_LOCKED" == "true" ]]; then
            if ! (cd "${REPAIR_PROJECT_ROOT}" && "${REPAIR_VENV_DIR}/bin/pip" install --no-cache-dir -r "$REPAIR_LOCKED_REQS" --quiet); then
                echo -e "${RED}Error: pip install from locked requirements failed.${NC}"
                rm -f "$REPAIR_LOCKED_REQS"
                rm -rf "$REPAIR_VENV_DIR"
                exit 1
            fi
            rm -f "$REPAIR_LOCKED_REQS"
            echo -e "${GREEN}  Project installed (locked versions from uv.lock)${NC}"
        else
            echo -e "${YELLOW}  uv not found or uv.lock missing — falling back to pip install (versions may drift)${NC}"
            rm -f "$REPAIR_LOCKED_REQS"
            if ! "${REPAIR_VENV_DIR}/bin/pip" install --no-cache-dir "${REPAIR_PROJECT_ROOT}" --quiet; then
                echo -e "${RED}Error: pip install failed.${NC}"
                rm -rf "$REPAIR_VENV_DIR"
                exit 1
            fi
            echo -e "${GREEN}  Project installed${NC}"
        fi

        # --- Write venv manifest ---
        REPAIR_MANIFEST="${ACTIVE_INSTALL_PATH}/lib/venv_manifest.txt"
        {
            echo "# Plugin Venv Manifest"
            echo "# Generated: $(date -u +"%Y-%m-%dT%H:%M:%SZ")"
            echo "# Repair version: ${ACTIVE_VERSION} (repaired, not redeployed)"
            echo ""
            echo "python_version: $("${REPAIR_VENV_DIR}/bin/python3" --version 2>&1)"
            echo "pip_version: $("${REPAIR_VENV_DIR}/bin/pip" --version 2>&1)"
            echo "source_root: ${REPAIR_PROJECT_ROOT}"
            echo "git_sha: $(cd "${REPAIR_PROJECT_ROOT}" && git rev-parse HEAD 2>/dev/null || echo 'unknown')"
            echo ""
            echo "# Installed packages:"
            "${REPAIR_VENV_DIR}/bin/pip" freeze 2>/dev/null
        } > "$REPAIR_MANIFEST"
        echo -e "${GREEN}  Manifest written to ${REPAIR_MANIFEST}${NC}"

        # --- Smoke test ---
        echo ""
        echo "Running smoke test..."
        if "${REPAIR_VENV_DIR}/bin/python3" -c "import omnibase_spi; import omniclaude; from omniclaude.hooks.topics import TopicBase; print('Smoke test: OK')" 2>&1; then
            _REPAIR_TRAP_REMOVE=false  # Venv is good; retain on exit
            echo ""
            echo -e "${GREEN}Venv repair complete!${NC}"
            echo ""
            echo "Restart Claude Code to activate the repaired venv."
        else
            echo -e "${RED}Error: Smoke test FAILED. Venv was removed.${NC}"
            echo "  The following imports must work:"
            echo "    import omnibase_spi"
            echo "    import omniclaude"
            echo "    from omniclaude.hooks.topics import TopicBase"
            rm -rf "$REPAIR_VENV_DIR"
            rm -f "$REPAIR_MANIFEST"
            exit 1
        fi
    fi

    echo ""
    exit 0
fi

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
echo "  skills/:        $(count_skills) directories"
echo "  agents/configs: $(count_agents) files"
echo "  hooks/:         $(count_hooks) items"
echo "  .claude-plugin: plugin.json + metadata"
echo ""
echo -e "${BLUE}Note: Commands are discovered via installPath, not synced to cache.${NC}"
echo ""

# Check if target exists
if [[ -d "$TARGET" ]]; then
    echo -e "${YELLOW}Warning: Target directory exists, will overwrite${NC}"
    echo ""
fi

# Validate required source directories exist
REQUIRED_DIRS=("skills" "agents" "hooks" ".claude-plugin")
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

    # =========================================================================
    # Resolve PROJECT_ROOT — the repo root containing .claude-plugin/marketplace.json.
    #
    # Claude Code's plugin loader (IEA → bz7 → MQR) reads marketplace.json
    # from known_marketplaces.json:installLocation. If installLocation points
    # to the cache instead of the repo root, MQR fails with
    # "missing .claude-plugin/marketplace.json" and the ENTIRE plugin is skipped
    # (zero skills, zero commands, zero agents).
    #
    # This path is used for:
    #   1. pip install (needs pyproject.toml)
    #   2. known_marketplaces.json installLocation (needs marketplace.json)
    #   3. git SHA in venv manifest
    #
    # Use `git rev-parse --show-toplevel` instead of relative traversal
    # (../../) so this works regardless of where CLAUDE_PLUGIN_ROOT points.
    # =========================================================================
    if ! PROJECT_ROOT="$(git -C "${SOURCE_ROOT}" rev-parse --show-toplevel 2>/dev/null)"; then
        echo -e "${RED}Error: Could not determine repo root via 'git rev-parse --show-toplevel'.${NC}"
        echo -e "${RED}SOURCE_ROOT (${SOURCE_ROOT}) does not appear to be inside a git repository.${NC}"
        echo -e "${RED}Ensure CLAUDE_PLUGIN_ROOT points to a directory within the omniclaude repo.${NC}"
        exit 1
    fi

    # Validate PROJECT_ROOT has the required files (safety net in case the
    # git root is correct but the repo layout is unexpected)
    if [[ ! -f "${PROJECT_ROOT}/.claude-plugin/marketplace.json" ]]; then
        echo -e "${RED}Error: marketplace.json not found at ${PROJECT_ROOT}/.claude-plugin/${NC}"
        echo -e "${RED}PROJECT_ROOT resolved to: ${PROJECT_ROOT}${NC}"
        echo -e "${RED}Ensure this is the omniclaude repo root containing .claude-plugin/.${NC}"
        exit 1
    fi
    if [[ ! -f "${PROJECT_ROOT}/pyproject.toml" ]]; then
        echo -e "${RED}Error: pyproject.toml not found at ${PROJECT_ROOT}${NC}"
        echo -e "${RED}PROJECT_ROOT resolved to: ${PROJECT_ROOT}${NC}"
        echo -e "${RED}Ensure this is the omniclaude repo root containing pyproject.toml.${NC}"
        exit 1
    fi
    echo -e "${GREEN}  Project root: ${PROJECT_ROOT}${NC}"

    # Create target directory FIRST, then write bumped version to target only.
    # Never mutate SOURCE plugin.json — that caused corruption when deploys fail midway.
    mkdir -p "$TARGET"
    echo -e "${GREEN}  Created target directory${NC}"

    # Sync components
    echo "  Syncing skills..."
    rsync -a --delete "${SOURCE_ROOT}/skills/" "${TARGET}/skills/"

    echo "  Syncing agents..."
    rsync -a --delete "${SOURCE_ROOT}/agents/" "${TARGET}/agents/"

    echo "  Syncing hooks..."
    rsync -a --delete "${SOURCE_ROOT}/hooks/" "${TARGET}/hooks/"

    echo "  Syncing .claude-plugin..."
    rsync -a --delete "${SOURCE_ROOT}/.claude-plugin/" "${TARGET}/.claude-plugin/"

    # Write bumped version to TARGET plugin.json only (source is never mutated)
    if [[ "$NO_VERSION_BUMP" != "true" ]]; then
        TARGET_PLUGIN_JSON="${TARGET}/.claude-plugin/plugin.json"
        jq --arg v "$NEW_VERSION" '.version = $v' "$TARGET_PLUGIN_JSON" > "${TARGET_PLUGIN_JSON}.tmp"
        mv "${TARGET_PLUGIN_JSON}.tmp" "$TARGET_PLUGIN_JSON"
        echo -e "${GREEN}  Set target plugin.json version to ${NEW_VERSION}${NC}"
    fi

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

    # PROJECT_ROOT already resolved and validated at top of execute block

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
    LOCKED_REQS_FILE=$(mktemp /tmp/omniclaude-locked-reqs.XXXXXX)
    _uv_stderr="$(mktemp /tmp/omniclaude-uv-export-err.XXXXXX)"
    # Register EXIT trap BEFORE setting _TRAP_REMOVE_VENV=true so that any
    # SIGINT/SIGTERM between venv creation and successful completion is caught.
    # _TRAP_REMOVE_VENV starts false (no venv yet); set true right after creation;
    # reset to false after the smoke test passes so a successful deploy retains the venv.
    _TRAP_REMOVE_VENV=false
    trap '[[ "${_TRAP_REMOVE_VENV:-false}" == "true" ]] && rm -rf "${VENV_DIR:-}"; rm -f "${LOCKED_REQS_FILE:-}" "${_uv_stderr:-}"' EXIT
    rm -rf "$VENV_DIR"
    mkdir -p "${TARGET}/lib"
    "$PYTHON_BIN" -m venv "$VENV_DIR"
    _TRAP_REMOVE_VENV=true  # Venv now exists; signal EXIT trap to clean up if interrupted hereafter
    echo -e "${GREEN}  Venv created at ${VENV_DIR}${NC}"

    # --- Bootstrap pip toolchain ---
    if ! "$VENV_DIR/bin/python3" -m ensurepip --upgrade 2>&1; then
        echo -e "${RED}Error: ensurepip failed. Python may lack the ensurepip module (common on minimal installs).${NC}"
        rm -rf "$VENV_DIR"
        exit 1
    fi
    "$VENV_DIR/bin/pip" install --upgrade pip wheel --quiet
    echo -e "${GREEN}  pip toolchain bootstrapped${NC}"

    # --- Install project using locked dependencies from uv.lock ---
    # Use 'uv export --frozen' to pin exact versions from uv.lock, preventing
    # version drift between deploys (e.g. qdrant-client 1.17.0 introduced a
    # runtime TypeError with grpcio's EnumTypeWrapper that breaks the smoke test).
    echo "  Installing project from ${PROJECT_ROOT} (locked versions)..."
    _USE_LOCKED=false
    if command -v uv &>/dev/null && [[ -f "${PROJECT_ROOT}/uv.lock" ]]; then
        if (cd "${PROJECT_ROOT}" && uv export --frozen --no-dev --no-hashes --format requirements-txt > "$LOCKED_REQS_FILE" 2>"$_uv_stderr"); then
            # Validate the requirements file is non-empty (uv export can produce an empty
            # file in degenerate cases; pip install on an empty file silently succeeds).
            if [ ! -s "$LOCKED_REQS_FILE" ]; then
                echo -e "${YELLOW}  WARNING: uv export produced empty requirements file; falling back to pip install (versions may drift)${NC}"
                rm -f "$LOCKED_REQS_FILE"
            else
                _USE_LOCKED=true
            fi
        else
            # uv export failed — show why so users aren't left wondering
            if [ -s "$_uv_stderr" ]; then
                echo -e "${YELLOW}  WARNING: uv export failed: $(head -3 "$_uv_stderr")${NC}"
            fi
            rm -f "$LOCKED_REQS_FILE"
        fi
    fi
    rm -f "$_uv_stderr"

    if [[ "$_USE_LOCKED" == "true" ]]; then
        # Run pip install from PROJECT_ROOT so that the '-e .' editable entry in the
        # requirements file (produced by 'uv export') resolves to PROJECT_ROOT rather
        # than the script's current working directory.
        if ! (cd "${PROJECT_ROOT}" && "$VENV_DIR/bin/pip" install --no-cache-dir -r "$LOCKED_REQS_FILE" --quiet); then
            echo -e "${RED}Error: pip install from locked requirements failed. Deploy aborted.${NC}"
            rm -f "$LOCKED_REQS_FILE"
            rm -rf "$VENV_DIR"
            exit 1
        fi
        rm -f "$LOCKED_REQS_FILE"
        echo -e "${GREEN}  Project installed into venv (locked versions from uv.lock)${NC}"
    else
        echo -e "${YELLOW}  uv not found or uv.lock missing — falling back to pip install (versions may drift)${NC}"
        rm -f "$LOCKED_REQS_FILE"
        if ! "$VENV_DIR/bin/pip" install --no-cache-dir "${PROJECT_ROOT}" --quiet; then
            echo -e "${RED}Error: pip install failed for ${PROJECT_ROOT}. Deploy aborted.${NC}"
            rm -rf "$VENV_DIR"
            exit 1
        fi
        echo -e "${GREEN}  Project installed into venv${NC}"
    fi

    # --- Write venv manifest ---
    MANIFEST="${TARGET}/lib/venv_manifest.txt"
    {
        echo "# Plugin Venv Manifest"
        echo "# Generated: $(date -u +"%Y-%m-%dT%H:%M:%SZ")"
        echo "# Deploy version: ${NEW_VERSION}"
        echo ""
        echo "python_version: $("$VENV_DIR/bin/python3" --version 2>&1)"
        echo "pip_version: $("$VENV_DIR/bin/pip" --version 2>&1)"
        echo "source_root: ${PROJECT_ROOT}"
        echo "git_sha: $(cd "${PROJECT_ROOT}" && git rev-parse HEAD 2>/dev/null || echo 'unknown')"
        echo ""
        echo "# Installed packages:"
        "$VENV_DIR/bin/pip" freeze 2>/dev/null
    } > "$MANIFEST"
    echo -e "${GREEN}  Venv manifest written to ${MANIFEST}${NC}"

    # --- Smoke test ---
    if "$VENV_DIR/bin/python3" -c "import omnibase_spi; import omniclaude; from omniclaude.hooks.topics import TopicBase; print('Smoke test: OK')" 2>&1; then
        _TRAP_REMOVE_VENV=false  # Venv is good; retain it on normal exit
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

            jq --arg p "$PROJECT_ROOT" --arg ts "$TIMESTAMP" '
                .["omninode-tools"].source.source = "directory" |
                .["omninode-tools"].source.path = $p |
                del(.["omninode-tools"].source.repo) |
                del(.["omninode-tools"].source.ref) |
                .["omninode-tools"].installLocation = $p |
                .["omninode-tools"].lastUpdated = $ts
            ' "$KNOWN_MARKETPLACES" > "${KNOWN_MARKETPLACES}.tmp" && mv "${KNOWN_MARKETPLACES}.tmp" "$KNOWN_MARKETPLACES"

            echo -e "${GREEN}  Updated known_marketplaces.json (installLocation: $PROJECT_ROOT)${NC}"
        else
            echo -e "${YELLOW}  Warning: omninode-tools not found in known_marketplaces.json${NC}"
        fi
    fi

    # Update statusLine in settings.json to point at new version's statusline.sh
    SETTINGS_JSON="$HOME/.claude/settings.json"
    if [[ -f "$SETTINGS_JSON" ]]; then
        # Single backup before ANY modification to settings.json.
        # Placed here so it covers both the statusLine block and the hooks block
        # below regardless of which branches execute. The hooks block previously
        # had its own cp that would overwrite this backup; that duplicate was removed.
        cp "$SETTINGS_JSON" "${SETTINGS_JSON}.bak"

        # Use ~ prefix: Claude Code's settings parser expands ~ to $HOME
        STATUSLINE_PATH_SHORT="~/.claude/plugins/cache/omninode-tools/onex/${NEW_VERSION}/hooks/scripts/statusline.sh"

        if jq -e '.statusLine.command' "$SETTINGS_JSON" >/dev/null 2>&1; then
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

    # Update hooks in settings.json to point at new version's hook scripts.
    # Strips any existing onex hook entries (matched by cache path) then writes
    # fresh entries for each event type. Other plugins' hooks are preserved.
    if [[ -f "$SETTINGS_JSON" ]]; then
        HOOKS_BASE="~/.claude/plugins/cache/omninode-tools/onex/${NEW_VERSION}/hooks/scripts"
        PRETOOL_MATCHER='^(Edit|Write)$'
        POSTTOOL_MATCHER='^(Read|Write|Edit|Bash|Glob|Grep|Task|Skill|WebFetch|WebSearch|NotebookEdit|NotebookRead)$'

        jq --arg base "$HOOKS_BASE" \
           --arg ptum "$PRETOOL_MATCHER" \
           --arg ptoom "$POSTTOOL_MATCHER" '
          def is_onex: .hooks | map(.command // "") | any(test("plugins/cache/omninode-tools/onex/"));
          def rm_onex: if . == null then [] else map(select(is_onex | not)) end;
          def add_cmd(cmd): . + [{"hooks": [{"type": "command", "command": cmd}]}];
          def add_m(m; cmd): . + [{"matcher": m, "hooks": [{"type": "command", "command": cmd}]}];
          .hooks |= (. // {}) |
          .hooks.SessionStart     = ((.hooks.SessionStart     // []) | rm_onex | add_cmd("\($base)/session-start.sh")) |
          .hooks.SessionEnd       = ((.hooks.SessionEnd       // []) | rm_onex | add_cmd("\($base)/session-end.sh")) |
          .hooks.UserPromptSubmit = ((.hooks.UserPromptSubmit // []) | rm_onex | add_cmd("\($base)/user-prompt-submit.sh")) |
          .hooks.PreToolUse       = ((.hooks.PreToolUse       // []) | rm_onex | add_m($ptum;  "\($base)/pre_tool_use_authorization_shim.sh")) |
          .hooks.PostToolUse      = ((.hooks.PostToolUse      // []) | rm_onex | add_m($ptoom; "\($base)/post-tool-use-quality.sh"))
        ' "$SETTINGS_JSON" > "${SETTINGS_JSON}.tmp" && mv "${SETTINGS_JSON}.tmp" "$SETTINGS_JSON"

        echo -e "${GREEN}  Updated settings.json hooks (5 entries) -> ${HOOKS_BASE}${NC}"
    fi

    # Install register-tab.sh to ~/.claude/ — required by statusline.sh for tab bar.
    # This file is not inside the plugin cache; it must live at ~/.claude/register-tab.sh.
    REGISTER_TAB_SRC="${SOURCE_ROOT}/hooks/scripts/register-tab.sh"
    REGISTER_TAB_DEST="$HOME/.claude/register-tab.sh"
    if [[ -f "$REGISTER_TAB_SRC" ]]; then
        cp "$REGISTER_TAB_SRC" "$REGISTER_TAB_DEST"
        chmod +x "$REGISTER_TAB_DEST"
        echo -e "${GREEN}  Installed register-tab.sh to ${REGISTER_TAB_DEST}${NC}"
    else
        echo -e "${YELLOW}  Warning: register-tab.sh not found at ${REGISTER_TAB_SRC} (tab bar will be empty)${NC}"
    fi

    # Clean up legacy ~/.claude/{commands,skills,agents}/onex/ directories.
    # Skills/commands/agents are now discovered via the plugin installPath only.
    CLAUDE_DIR="$HOME/.claude"
    for component in commands skills agents; do
        LEGACY="$CLAUDE_DIR/$component/onex"
        if [[ -d "$LEGACY" || -L "$LEGACY" ]]; then
            echo -e "  Removing legacy directory: ${LEGACY}"
            rm -rf "$LEGACY"
            echo -e "${GREEN}  Removed legacy ${LEGACY}${NC}"
        fi
    done

    # Prune old version directories — keep only NEW_VERSION.
    # Runs last so all writes (registry, settings) succeed before we remove rollback targets.
    # Only delete directories whose names match the semver pattern X.Y.Z to avoid
    # accidentally removing non-version directories under CACHE_BASE.
    echo "  Pruning old version directories..."
    shopt -s nullglob
    for old_dir in "${CACHE_BASE}"/[0-9]*.[0-9]*.[0-9]*/; do
        old_version=$(basename "$old_dir")
        if [[ "$old_version" != "$NEW_VERSION" ]]; then
            rm -rf "$old_dir"
            echo -e "${GREEN}  Removed old version: ${old_version}${NC}"
        fi
    done
    shopt -u nullglob

    echo ""
    echo -e "${GREEN}Deployment complete!${NC}"
    echo ""
    echo "Restart Claude Code to load the new version."
else
    echo -e "${YELLOW}This is a dry run. Use --execute to apply changes.${NC}"
fi

echo ""
