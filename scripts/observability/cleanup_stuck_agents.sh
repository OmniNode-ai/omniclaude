#!/bin/bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# =====================================================================
# Cleanup Stuck Agents Script
# =====================================================================
# Purpose: Mark agents stuck in "in_progress" for >threshold as "error"
# Database: Configured via .env file (POSTGRES_* variables)
# Usage: ./cleanup_stuck_agents.sh [threshold_minutes] [--dry-run]
# =====================================================================

set -euo pipefail

# =====================================================================
# Configuration
# =====================================================================

# Default threshold: 60 minutes (1 hour)
STUCK_THRESHOLD_MINUTES="${1:-60}"
DRY_RUN=false

# Check for --dry-run flag
if [[ "${2:-}" == "--dry-run" ]] || [[ "${1:-}" == "--dry-run" ]]; then
    DRY_RUN=true
    if [[ "${1:-}" == "--dry-run" ]]; then
        STUCK_THRESHOLD_MINUTES="${2:-60}"
    fi
fi

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

# Verify required variables are set
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
# Helper Functions
# =====================================================================

print_header() {
    echo ""
    echo "================================================================="
    echo "$1"
    echo "================================================================="
}

print_section() {
    echo ""
    echo "--- $1 ---"
}

# =====================================================================
# Pre-Check: Show stuck agents
# =====================================================================

print_header "STUCK AGENTS CLEANUP - $(date)"

echo "Configuration:"
echo "  Database: ${DB_HOST}:${DB_PORT}/${DB_NAME}"
echo "  Threshold: ${STUCK_THRESHOLD_MINUTES} minutes"
echo "  Dry Run: ${DRY_RUN}"
echo ""

print_section "Checking for stuck agents (>= ${STUCK_THRESHOLD_MINUTES} minutes)"

# Query stuck agents
STUCK_AGENTS=$(psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -t -c "
SELECT COUNT(*)
FROM agent_execution_logs
WHERE status = 'in_progress'
  AND started_at < NOW() - INTERVAL '${STUCK_THRESHOLD_MINUTES} minutes'
  AND completed_at IS NULL;
" | xargs)

echo "Found: ${STUCK_AGENTS} stuck agents"

if [[ "$STUCK_AGENTS" -eq 0 ]]; then
    echo "✅ No stuck agents found. Exiting."
    exit 0
fi

# =====================================================================
# Show details of stuck agents
# =====================================================================

print_section "Stuck Agent Details"

psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -c "
SELECT
    execution_id,
    agent_name,
    LEFT(correlation_id::TEXT, 13) || '...' as correlation_id,
    started_at,
    ROUND(EXTRACT(EPOCH FROM (NOW() - started_at)) / 60, 1) as stuck_minutes,
    LEFT(user_prompt, 60) as user_prompt_preview
FROM agent_execution_logs
WHERE status = 'in_progress'
  AND started_at < NOW() - INTERVAL '${STUCK_THRESHOLD_MINUTES} minutes'
  AND completed_at IS NULL
ORDER BY started_at ASC;
"

# =====================================================================
# Cleanup or dry-run
# =====================================================================

if [[ "$DRY_RUN" == true ]]; then
    print_section "DRY RUN - No changes made"
    echo "Would mark ${STUCK_AGENTS} agents as 'error' with timeout message."
    echo ""
    echo "To execute cleanup, run without --dry-run flag:"
    echo "  ./cleanup_stuck_agents.sh ${STUCK_THRESHOLD_MINUTES}"
    exit 0
fi

# =====================================================================
# Execute cleanup
# =====================================================================

print_section "Executing Cleanup"

echo "Marking ${STUCK_AGENTS} stuck agents as 'error'..."

# Update stuck agents
UPDATED=$(psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -t -A -c "
UPDATE agent_execution_logs
SET
    status = 'error',
    error_message = 'Execution timeout - stuck in progress > ${STUCK_THRESHOLD_MINUTES} minutes (auto-cleanup)',
    error_type = 'timeout',
    completed_at = NOW(),
    duration_ms = EXTRACT(EPOCH FROM (NOW() - started_at)) * 1000
WHERE status = 'in_progress'
  AND started_at < NOW() - INTERVAL '${STUCK_THRESHOLD_MINUTES} minutes'
  AND completed_at IS NULL
RETURNING execution_id;
" | wc -l | xargs)

echo "✅ Updated: ${UPDATED} agents marked as error"

# =====================================================================
# Show updated records
# =====================================================================

print_section "Updated Records"

psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -c "
SELECT
    execution_id,
    agent_name,
    LEFT(correlation_id::TEXT, 13) || '...' as correlation_id,
    started_at,
    completed_at,
    ROUND(duration_ms / 1000, 1) as duration_seconds,
    error_type,
    LEFT(error_message, 60) as error_message_preview
FROM agent_execution_logs
WHERE status = 'error'
  AND error_type = 'timeout'
  AND completed_at > NOW() - INTERVAL '1 minute'
ORDER BY completed_at DESC;
"

# =====================================================================
# Summary
# =====================================================================

print_section "Summary"

echo "Cleanup completed successfully!"
echo "  Stuck agents found: ${STUCK_AGENTS}"
echo "  Agents updated: ${UPDATED}"
echo "  Timestamp: $(date)"
echo ""

# Show updated stats
echo "Current agent status summary:"
psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -c "
SELECT
    status,
    COUNT(*) as count,
    ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 1) as percent
FROM agent_execution_logs
WHERE started_at > NOW() - INTERVAL '24 hours'
GROUP BY status
ORDER BY count DESC;
"

print_header "Cleanup Complete"

exit 0
