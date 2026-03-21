#!/bin/bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Install shared library from version control to user directory
#
# This script copies the shared library code from the omniclaude repository
# to $ONEX_STATE_DIR/lib/ for use by git hooks and agents.
#
# Usage: ./setup.sh

set -e  # Exit on error

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_LIB="$SCRIPT_DIR"

if [[ -z "${ONEX_STATE_DIR:-}" ]]; then
  echo "FATAL: ONEX_STATE_DIR is not set" >&2
  exit 1
fi
USER_LIB="${ONEX_STATE_DIR}/lib"

echo "=================================================="
echo "OmniClaude Shared Library Installation"
echo "=================================================="
echo ""
echo "Source: $REPO_LIB"
echo "Target: $USER_LIB"
echo ""

# Create target directory if it doesn't exist
if [ ! -d "$USER_LIB" ]; then
    echo "Creating directory: $USER_LIB"
    mkdir -p "$USER_LIB"
fi

# Copy Python files
echo "Copying Python files..."
cp -v "$REPO_LIB"/__init__.py "$USER_LIB/"
cp -v "$REPO_LIB"/kafka_config.py "$USER_LIB/"

# Copy documentation files
echo ""
echo "Copying documentation..."
cp -v "$REPO_LIB"/*.md "$USER_LIB/" 2>/dev/null || echo "No markdown files to copy"

echo ""
echo "=================================================="
echo "✓ Shared library installed successfully"
echo "=================================================="
echo ""
echo "Installed files:"
ls -lh "$USER_LIB"
echo ""
echo "You can now use shared library functions in your git hooks and agents."
