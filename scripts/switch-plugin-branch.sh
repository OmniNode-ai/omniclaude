#!/bin/bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Switch the onex plugin to pull from a specific GitHub branch
# Usage: ./switch-plugin-branch.sh [branch-name]
# Default: main

set -euo pipefail

BRANCH="${1:-main}"
KNOWN_MARKETPLACES="$HOME/.claude/plugins/known_marketplaces.json"

if [[ ! -f "$KNOWN_MARKETPLACES" ]]; then
    echo "Error: $KNOWN_MARKETPLACES not found"
    exit 1
fi

echo "Switching onex plugin to branch: $BRANCH"

# Update the ref in known_marketplaces.json
jq --arg branch "$BRANCH" --arg home "$HOME" '
  .["omninode-tools"].source.ref = $branch |
  .["omninode-tools"].installLocation = ($home + "/.claude/plugins/marketplaces/omninode-tools") |
  .["omninode-tools"].lastUpdated = (now | strftime("%Y-%m-%dT%H:%M:%S.000Z"))
' "$KNOWN_MARKETPLACES" > "${KNOWN_MARKETPLACES}.tmp" && mv "${KNOWN_MARKETPLACES}.tmp" "$KNOWN_MARKETPLACES"

echo "✅ Updated marketplace to use branch: $BRANCH"
echo ""
echo "Current config:"
jq '.["omninode-tools"]' "$KNOWN_MARKETPLACES"
echo ""
echo "Next steps:"
echo "  1. Restart Claude Code to pull from the new branch"
echo "  2. Or run: claude /mcp to reconnect"
