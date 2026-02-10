#!/usr/bin/env bash
# check_migration_freeze.sh — Block new migrations while .migration_freeze exists.
#
# Usage:
#   Pre-commit: ./scripts/check_migration_freeze.sh           (checks staged files)
#   CI:         ./scripts/check_migration_freeze.sh --ci       (checks diff vs base branch)
#
# Exit codes:
#   0 — No freeze active, or no new migrations detected
#   1 — Freeze violation: new migration files added

set -euo pipefail

FREEZE_FILE=".migration_freeze"
MIGRATIONS_DIR="sql/migrations"

# If no freeze file, nothing to enforce.
if [ ! -f "$FREEZE_FILE" ]; then
    echo "No migration freeze active — skipping check."
    exit 0
fi

echo "Migration freeze is ACTIVE ($FREEZE_FILE exists)"

MODE="${1:-precommit}"

if [ "$MODE" = "--ci" ]; then
    # CI mode: compare against base branch
    BASE_BRANCH="${GITHUB_BASE_REF:-main}"
    # Detect added (A) or renamed (R) files in the migrations directory
    NEW_MIGRATIONS=$(git diff --name-status "origin/${BASE_BRANCH}...HEAD" -- "$MIGRATIONS_DIR" \
        | grep -E '^[AR]' | awk '{print $NF}' || true)
else
    # Pre-commit mode: check staged files
    NEW_MIGRATIONS=$(git diff --cached --name-status -- "$MIGRATIONS_DIR" \
        | grep -E '^[AR]' | awk '{print $NF}' || true)
fi

if [ -n "$NEW_MIGRATIONS" ]; then
    echo ""
    echo "ERROR: Migration freeze violation!"
    echo "New migration files are blocked while $FREEZE_FILE exists:"
    echo ""
    echo "$NEW_MIGRATIONS" | sed 's/^/  /'
    echo ""
    echo "Allowed during freeze: moves, ownership fixes, rollback bug fixes."
    echo "See $FREEZE_FILE for details."
    exit 1
fi

echo "No new migrations detected — freeze check passed."
exit 0
