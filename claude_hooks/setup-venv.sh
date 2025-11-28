#!/bin/bash
# Setup script for Claude hooks Python environment
#
# This script creates/updates the symlink from ~/.claude/hooks/.venv
# to the omniclaude poetry virtual environment.
#
# NO separate requirements.txt - uses poetry like everything else.
#
# Usage: ~/.claude/hooks/setup-venv.sh

set -euo pipefail

HOOK_DIR="${HOME}/.claude/hooks"
OMNICLAUDE_DIR="/Volumes/PRO-G40/Code/omniclaude"
VENV_LINK="${HOOK_DIR}/.venv"
CACHE_DIR="${HOOK_DIR}/.cache"

echo "=== Claude Hooks Environment Setup ==="
echo ""

# Check omniclaude directory exists
if [[ ! -d "$OMNICLAUDE_DIR" ]]; then
    echo "❌ Error: omniclaude directory not found at $OMNICLAUDE_DIR"
    echo "   Please update OMNICLAUDE_DIR in this script"
    exit 1
fi

# Check poetry is available
if ! command -v poetry &>/dev/null; then
    echo "❌ Error: poetry not found"
    echo "   Install with: curl -sSL https://install.python-poetry.org | python3 -"
    exit 1
fi

# Get poetry venv path
echo "Finding poetry virtual environment..."
POETRY_VENV=$(cd "$OMNICLAUDE_DIR" && poetry env info --path 2>/dev/null)

if [[ -z "$POETRY_VENV" || ! -d "$POETRY_VENV" ]]; then
    echo "❌ Error: Poetry venv not found"
    echo "   Run: cd $OMNICLAUDE_DIR && poetry install"
    exit 1
fi

echo "✓ Found poetry venv: $POETRY_VENV"

# Verify Python works
if [[ ! -x "${POETRY_VENV}/bin/python3" ]]; then
    echo "❌ Error: Python not found in poetry venv"
    exit 1
fi

# Check required packages
echo ""
echo "Checking required packages..."
MISSING_PACKAGES=()

for pkg in dotenv kafka pyyaml httpx loguru; do
    if ! "${POETRY_VENV}/bin/python3" -c "import $pkg" 2>/dev/null; then
        MISSING_PACKAGES+=("$pkg")
    fi
done

if [[ ${#MISSING_PACKAGES[@]} -gt 0 ]]; then
    echo "⚠️  Warning: Missing packages: ${MISSING_PACKAGES[*]}"
    echo "   Run: cd $OMNICLAUDE_DIR && poetry install"
else
    echo "✓ All required packages available"
fi

# Create/update symlink
echo ""
echo "Creating venv symlink..."
rm -rf "$VENV_LINK"
ln -s "$POETRY_VENV" "$VENV_LINK"
echo "✓ Symlink created: $VENV_LINK -> $POETRY_VENV"

# Update cache
echo ""
echo "Updating cache..."
mkdir -p "$CACHE_DIR"
echo "$POETRY_VENV" > "${CACHE_DIR}/poetry_venv_path"
echo "✓ Cache updated"

# Verify setup
echo ""
echo "Verifying setup..."
if "${HOOK_DIR}/bin/python3" -c "from config import settings; print(f'✓ Config module loads (enforcement_mode={settings.enforcement_mode})')" 2>/dev/null; then
    echo ""
    echo "=== Setup Complete ==="
    echo ""
    echo "The hooks are now configured to use the omniclaude poetry environment."
    echo "No separate requirements.txt needed - all dependencies managed via poetry."
else
    echo "⚠️  Warning: Config module didn't load. Check poetry install."
fi
