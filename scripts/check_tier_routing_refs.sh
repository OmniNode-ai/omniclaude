#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# check_tier_routing_refs.sh — CI enforcement for tier-routing migration
#
# Lists all skill files that still reference tier-routing patterns.
# Threshold enforcement (OMN-4994):
#   >= THRESHOLD remaining: CI FAILS (exit 1) — too many references
#   1 to THRESHOLD-1 remaining: CI passes with WARNING (exit 0)
#   0 remaining: CI passes silently (migration complete)
#
# Usage:
#   scripts/check_tier_routing_refs.sh              # default threshold: 10
#   scripts/check_tier_routing_refs.sh --threshold 5
#   scripts/check_tier_routing_refs.sh --warn-only  # never block

set -euo pipefail

THRESHOLD=10
WARN_ONLY=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --threshold) THRESHOLD="$2"; shift 2 ;;
        --warn-only) WARN_ONLY=true; shift ;;
        *) echo "Unknown argument: $1" >&2; exit 1 ;;
    esac
done

SKILLS_DIR="plugins/onex/skills"
PATTERNS='tier-routing|detect_onex_tier|tier_routing'

echo "=== Tier-Routing Migration Status ==="
echo "Enforcement threshold: $THRESHOLD"
echo ""

# Count remaining references (exclude the deleted helpers.md itself)
REFS=$(grep -rl -E "$PATTERNS" "$SKILLS_DIR" 2>/dev/null | grep -v '_lib/tier-routing/helpers.md' || true)
if [ -z "$REFS" ]; then
    COUNT=0
else
    COUNT=$(echo "$REFS" | wc -l | tr -d ' ')
fi

if [ "$COUNT" -eq 0 ]; then
    echo "No remaining tier-routing references found. Migration complete."
    echo ""
    echo "=== End Tier-Routing Migration Status ==="
    exit 0
fi

echo "$COUNT skill files still reference tier-routing patterns:"
echo ""
echo "$REFS" | while IFS= read -r file; do
    [ -z "$file" ] && continue
    echo "  - $file"
done
echo ""

if [ "$WARN_ONLY" = true ]; then
    echo "Mode: warn-only (CI not blocked)"
    echo "=== End Tier-Routing Migration Status ==="
    exit 0
fi

if [ "$COUNT" -ge "$THRESHOLD" ]; then
    echo "Count ($COUNT) >= threshold ($THRESHOLD): BLOCKING CI"
    echo ""
    echo "Too many tier-routing references remain. Migrate skills to the"
    echo "skill bootstrapper runtime to reduce the count below $THRESHOLD."
    echo "=== End Tier-Routing Migration Status ==="
    exit 1
else
    echo "Count ($COUNT) < threshold ($THRESHOLD): WARNING only (CI not blocked)"
    echo "These skills still need migration but the count is below the enforcement threshold."
    echo "=== End Tier-Routing Migration Status ==="
    exit 0
fi
