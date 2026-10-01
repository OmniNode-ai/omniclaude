#!/bin/bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# Post-install deploy step for the onex plugin.
# Creates/updates the stable launcher at $ONEX_STATE_DIR/bin/statusline.sh
# so that settings.json can point to a version-independent path.
#
# Usage: bash deploy.sh
# Invoked automatically after: claude plugin install onex@omninode-tools

set -euo pipefail

# Always write the stable launcher to $HOME/.onex_state/bin — the user-portable
# path referenced by ~/.claude/settings.json. ONEX_STATE_DIR may point elsewhere
# (e.g. $ONEX_REGISTRY_ROOT/.onex_state) in dev environments, but settings.json targets
# the user home path unconditionally.
BIN_DIR="$HOME/.onex_state/bin"
SHIM="$BIN_DIR/statusline.sh"

mkdir -p "$BIN_DIR"

cat > "$SHIM" << 'SHIM_BODY'
#!/bin/bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# Stable launcher for the ONEX statusline — resolves the enabled onex plugin's
# install path (falling back to the newest cached copy) so settings.json never
# needs updating after deploys or a switch of marketplace.

CLAUDE_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
CACHE_ROOT="${ONEX_PLUGIN_CACHE_ROOT:-$CLAUDE_DIR/plugins/cache/omninode-tools/onex}"
VERSIONED=""

# 1. The ENABLED onex plugin's own install path. Which marketplace copy is
#    enabled (omninode-tools, or a development marketplace) is a setting, so a
#    launcher pinned to one cache directory runs a stale copy when the other is
#    the one enabled. Resolve it from enabledPlugins and installed_plugins.json.
if command -v jq >/dev/null 2>&1 && [ -f "$CLAUDE_DIR/settings.json" ] \
   && [ -f "$CLAUDE_DIR/plugins/installed_plugins.json" ]; then
    ENABLED_KEY=$(jq -r '[(.enabledPlugins // {}) | to_entries[]
        | select((.key | startswith("onex@")) and .value == true) | .key][0] // empty' \
        "$CLAUDE_DIR/settings.json" 2>/dev/null)
    if [ -n "$ENABLED_KEY" ]; then
        INSTALL_PATH=$(jq -r --arg k "$ENABLED_KEY" '.plugins[$k][0].installPath // empty' \
            "$CLAUDE_DIR/plugins/installed_plugins.json" 2>/dev/null)
        if [ -n "$INSTALL_PATH" ] && [ -f "$INSTALL_PATH/hooks/scripts/statusline.sh" ]; then
            VERSIONED="$INSTALL_PATH/hooks/scripts/statusline.sh"
        fi
    fi
fi

# 2. Fallback: highest semver-sorted copy under the cache root
#    (sort -V avoids mtime races).
if [ -z "$VERSIONED" ]; then
    VERSIONED=$(
        ls "$CACHE_ROOT"/*/hooks/scripts/statusline.sh 2>/dev/null \
        | sort -V \
        | tail -1
    )
fi

if [ -z "$VERSIONED" ]; then
    # Fallback: emit minimal output so Claude Code doesn't show a blank statusline
    echo "Claude"
    exit 0
fi

# Guard: must be a regular readable file before exec
if [ ! -f "$VERSIONED" ] || [ ! -r "$VERSIONED" ]; then
    echo "Claude"
    exit 0
fi

exec bash "$VERSIONED" "$@"
SHIM_BODY

chmod +x "$SHIM"

echo "Stable statusline launcher created at: $SHIM"
