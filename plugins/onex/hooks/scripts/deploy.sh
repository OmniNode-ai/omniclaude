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
# (e.g. $OMNI_HOME/.onex_state) in dev environments, but settings.json targets
# the user home path unconditionally.
BIN_DIR="$HOME/.onex_state/bin"
SHIM="$BIN_DIR/statusline.sh"

mkdir -p "$BIN_DIR"

cat > "$SHIM" << 'SHIM_BODY'
#!/bin/bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# Stable launcher for the ONEX statusline — auto-discovers the current
# plugin cache version so settings.json never needs updating after deploys.

CACHE_ROOT="${ONEX_PLUGIN_CACHE_ROOT:-$HOME/.claude/plugins/cache/omninode-tools/onex}"

# Find the highest semver-sorted installed copy (sort -V avoids mtime races)
VERSIONED=$(
    ls "$CACHE_ROOT"/*/hooks/scripts/statusline.sh 2>/dev/null \
    | sort -V \
    | tail -1
)

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
