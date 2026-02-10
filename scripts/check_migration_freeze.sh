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
    # MIGRATION_CHECK_BASE: PR base SHA or push-before SHA (set by CI workflow)
    # GITHUB_BASE_REF: branch name, only set for pull_request events
    NULL_SHA="0000000000000000000000000000000000000000"
    if [ -n "${MIGRATION_CHECK_BASE:-}" ] && [ "${MIGRATION_CHECK_BASE}" != "$NULL_SHA" ] \
        && git rev-parse --verify "${MIGRATION_CHECK_BASE}^{commit}" >/dev/null 2>&1; then
        BASE_REF="$MIGRATION_CHECK_BASE"
    elif [ -n "${GITHUB_BASE_REF:-}" ]; then
        BASE_REF="origin/${GITHUB_BASE_REF}"
    else
        BASE_REF="origin/main"
    fi
    # Detect only added (A) files — renames/moves are allowed during freeze
    # Separate git diff (fail loudly on error) from grep (no-match exit 1 is OK)
    DIFF_OUTPUT=$(git diff --name-status "${BASE_REF}...HEAD" -- "$MIGRATIONS_DIR")
    NEW_MIGRATIONS=$(echo "$DIFF_OUTPUT" | grep -E '^A' | awk '{print $NF}' || true)
else
    # Pre-commit mode: check staged files
    # Only added (A) files — renames/moves are allowed during freeze
    DIFF_OUTPUT=$(git diff --cached --name-status -- "$MIGRATIONS_DIR")
    NEW_MIGRATIONS=$(echo "$DIFF_OUTPUT" | grep -E '^A' | awk '{print $NF}' || true)
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
