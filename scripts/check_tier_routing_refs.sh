#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# check_tier_routing_refs.sh — CI warning for remaining tier-routing references
#
# Lists all skill files that still reference tier-routing patterns.
# Exits 0 (non-blocking) — this is a migration tracking tool, not an enforcer.
# See OMN-4994 for threshold enforcement (blocks CI when count drops below 10).
#
# Usage: scripts/check_tier_routing_refs.sh

set -euo pipefail

SKILLS_DIR="plugins/onex/skills"
PATTERNS='tier-routing|detect_onex_tier|tier_routing'

echo "=== Tier-Routing Migration Status ==="
echo ""

# Count remaining references (exclude the deleted helpers.md itself)
REFS=$(grep -rl -E "$PATTERNS" "$SKILLS_DIR" 2>/dev/null | grep -v '_lib/tier-routing/helpers.md' || true)
COUNT=$(echo "$REFS" | grep -c '.' 2>/dev/null || echo 0)

if [ "$COUNT" -eq 0 ]; then
    echo "No remaining tier-routing references found. Migration complete."
else
    echo "WARNING: $COUNT skill files still reference tier-routing patterns:"
    echo ""
    echo "$REFS" | while IFS= read -r file; do
        [ -z "$file" ] && continue
        echo "  - $file"
    done
    echo ""
    echo "These skills need to be migrated to the skill bootstrapper runtime."
    echo "See OMN-4993 follow-up tickets for each remaining skill."
fi

echo ""
echo "=== End Tier-Routing Migration Status ==="

# Always exit 0 — this is a warning, not an enforcer
exit 0
