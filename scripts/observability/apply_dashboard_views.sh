#!/bin/bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# =====================================================================
# Apply Dashboard Views to Database
# =====================================================================
# Purpose: Create or update all dashboard SQL views for agent monitoring
# Database: Configured via .env file (POSTGRES_* variables)
# Usage: ./apply_dashboard_views.sh [--force]
# =====================================================================

set -euo pipefail

# =====================================================================
# Configuration
# =====================================================================

# Load environment variables from .env
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

if [[ ! -f "$PROJECT_ROOT/.env" ]]; then
    echo "❌ ERROR: .env file not found at $PROJECT_ROOT/.env"
    echo "   Please copy .env.example to .env and configure it"
    exit 1
fi

# Source .env file
source "$PROJECT_ROOT/.env"

# Database connection (no fallbacks - must be set in .env)
DB_HOST="${POSTGRES_HOST}"
DB_PORT="${POSTGRES_PORT}"
DB_NAME="${POSTGRES_DATABASE}"
DB_USER="${POSTGRES_USER}"
export PGPASSWORD="${POSTGRES_PASSWORD}"

# Views SQL file location
VIEWS_FILE="$SCRIPT_DIR/dashboard_views.sql"

# Force flag
FORCE_APPLY=false
if [[ "${1:-}" == "--force" ]]; then
    FORCE_APPLY=true
fi

# =====================================================================
# Verify Required Variables
# =====================================================================

missing_vars=()
[ -z "$DB_HOST" ] && missing_vars+=("POSTGRES_HOST")
[ -z "$DB_PORT" ] && missing_vars+=("POSTGRES_PORT")
[ -z "$DB_NAME" ] && missing_vars+=("POSTGRES_DATABASE")
[ -z "$DB_USER" ] && missing_vars+=("POSTGRES_USER")
[ -z "$PGPASSWORD" ] && missing_vars+=("POSTGRES_PASSWORD")

if [ ${#missing_vars[@]} -gt 0 ]; then
    echo "❌ ERROR: Required environment variables not set in .env:"
    for var in "${missing_vars[@]}"; do
        echo "   - $var"
    done
    echo ""
    echo "Please update your .env file with these variables."
    exit 1
fi

# =====================================================================
# Verify Views File Exists
# =====================================================================

if [[ ! -f "$VIEWS_FILE" ]]; then
    echo "❌ ERROR: Views file not found: $VIEWS_FILE"
    exit 1
fi

# =====================================================================
# Display Header
# =====================================================================

echo ""
echo "================================================================="
echo "APPLY DASHBOARD VIEWS"
echo "================================================================="
echo ""
echo "Database: ${DB_HOST}:${DB_PORT}/${DB_NAME}"
echo "Views File: $VIEWS_FILE"
echo "Force Apply: $FORCE_APPLY"
echo ""

# =====================================================================
# Check Database Connection
# =====================================================================

echo "Checking database connection..."
if ! psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -c "SELECT 1" > /dev/null 2>&1; then
    echo "❌ ERROR: Cannot connect to database"
    echo "   Host: $DB_HOST:$DB_PORT"
    echo "   Database: $DB_NAME"
    echo "   User: $DB_USER"
    echo ""
    echo "Please verify your .env configuration and database availability."
    exit 1
fi
echo "✅ Database connection successful"
echo ""

# =====================================================================
# Check Existing Views
# =====================================================================

echo "Checking for existing views..."
EXISTING_VIEWS=$(psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -t -c "
    SELECT COUNT(*) FROM information_schema.views
    WHERE table_schema = 'public'
    AND table_name LIKE 'v_agent_%' OR table_name LIKE 'v_active_%' OR table_name LIKE 'v_stuck_%';
" | xargs)

echo "Found $EXISTING_VIEWS existing dashboard views"

if [[ "$EXISTING_VIEWS" -gt 0 ]] && [[ "$FORCE_APPLY" == false ]]; then
    echo ""
    echo "⚠️  Dashboard views already exist. This will update them."
    echo ""
    read -p "Continue? (y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "❌ Cancelled by user"
        exit 0
    fi
fi

echo ""

# =====================================================================
# Apply Views
# =====================================================================

# Create tmp directory (reuse PROJECT_ROOT from top of script)
mkdir -p "$PROJECT_ROOT/tmp"
TMP_LOG="$PROJECT_ROOT/tmp/apply_views.log"

echo "Applying dashboard views from: $VIEWS_FILE"
echo ""

if psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -f "$VIEWS_FILE" > "$TMP_LOG" 2>&1; then
    echo "✅ Dashboard views applied successfully"
else
    echo "❌ ERROR: Failed to apply views"
    echo ""
    echo "Error log:"
    cat "$TMP_LOG"
    exit 1
fi

echo ""

# =====================================================================
# Verify Views Created
# =====================================================================

echo "Verifying created views..."
echo ""

VIEWS_CREATED=$(psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -t -c "
    SELECT table_name FROM information_schema.views
    WHERE table_schema = 'public'
    AND (table_name LIKE 'v_agent_%' OR table_name LIKE 'v_active_%' OR table_name LIKE 'v_stuck_%')
    ORDER BY table_name;
")

if [[ -z "$VIEWS_CREATED" ]]; then
    echo "⚠️  WARNING: No views found after applying SQL file"
    echo "    This may indicate an issue with the SQL file or database permissions"
    exit 1
fi

echo "✅ Views created/updated:"
echo "$VIEWS_CREATED" | while read -r view; do
    if [[ -n "$view" ]]; then
        echo "   - $view"
    fi
done

echo ""

# =====================================================================
# Test Views
# =====================================================================

echo "Testing views..."
echo ""

test_view() {
    local view_name=$1
    if psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -c "SELECT * FROM $view_name LIMIT 1" > /dev/null 2>&1; then
        echo "   ✅ $view_name"
    else
        echo "   ❌ $view_name (query failed)"
        return 1
    fi
}

# Test each view
test_view "v_agent_execution_summary"
test_view "v_active_agents"
test_view "v_stuck_agents"
test_view "v_agent_completion_stats_24h"
test_view "v_agent_completion_stats_7d"
test_view "v_agent_performance"
test_view "v_agent_errors_recent"
test_view "v_agent_daily_trends"
test_view "v_agent_quality_leaderboard"

echo ""

# =====================================================================
# Summary
# =====================================================================

echo "================================================================="
echo "DASHBOARD VIEWS APPLIED SUCCESSFULLY"
echo "================================================================="
echo ""
echo "Next steps:"
echo "  1. Run dashboard: ./scripts/observability/dashboard_stats.sh"
echo "  2. Check summary: ./scripts/observability/dashboard_stats.sh summary"
echo "  3. View all stats: ./scripts/observability/dashboard_stats.sh all"
echo ""
echo "Documentation: scripts/observability/DASHBOARD_USAGE.md"
echo ""

exit 0
