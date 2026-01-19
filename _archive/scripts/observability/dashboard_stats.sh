#!/bin/bash
# =====================================================================
# Agent Execution Dashboard Statistics
# =====================================================================
# Purpose: Display dashboard-friendly statistics for agent executions
# Database: Configured via .env file (POSTGRES_* variables)
# Usage: ./dashboard_stats.sh [--summary|--active|--performance|--errors|--trends|--all]
#
# Exit Codes (see scripts/observability/EXIT_CODES.md):
#   0 - Dashboard displayed successfully
#   1 - Invalid mode/argument, database query failed (non-fatal)
#   3 - Configuration error (missing .env or credentials)
#   4 - Dependency missing (psql not installed)
# =====================================================================

set -euo pipefail

# =====================================================================
# Configuration
# =====================================================================

# Display mode (default: summary)
DISPLAY_MODE="${1:-summary}"

# Load environment variables from .env
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

if [[ ! -f "$PROJECT_ROOT/.env" ]]; then
    echo "❌ ERROR: .env file not found at $PROJECT_ROOT/.env"
    echo "   Please copy .env.example to .env and configure it"
    exit 3  # Configuration error
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
    exit 3  # Configuration error
fi

# =====================================================================
# Helper Functions
# =====================================================================

print_header() {
    echo ""
    echo "================================================================="
    echo "$1"
    echo "================================================================="
    echo ""
}

print_section() {
    echo ""
    echo "┌─────────────────────────────────────────────────────────────────┐"
    echo "│ $1"
    echo "└─────────────────────────────────────────────────────────────────┘"
    echo ""
}

run_query() {
    # Check if psql is available
    if ! command -v psql &> /dev/null; then
        echo "❌ ERROR: psql command not found. Please install PostgreSQL client."
        exit 4  # Dependency missing
    fi

    psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -c "$1"
}

# =====================================================================
# Display Functions
# =====================================================================

show_summary() {
    print_section "AGENT EXECUTION SUMMARY"
    run_query "SELECT * FROM v_agent_execution_summary;"
}

show_active_agents() {
    print_section "ACTIVE AGENTS (Currently Running)"

    # Check if any active
    ACTIVE_COUNT=$(psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -t -c "
    SELECT COUNT(*) FROM v_active_agents;
    " | xargs)

    if [[ "$ACTIVE_COUNT" -eq 0 ]]; then
        echo "✅ No agents currently active"
    else
        run_query "SELECT * FROM v_active_agents;"
    fi
}

show_stuck_agents() {
    print_section "STUCK AGENTS (>30 minutes)"

    # Check if any stuck
    STUCK_COUNT=$(psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -t -c "
    SELECT COUNT(*) FROM v_stuck_agents;
    " | xargs)

    if [[ "$STUCK_COUNT" -eq 0 ]]; then
        echo "✅ No stuck agents detected"
    else
        echo "⚠️  Found ${STUCK_COUNT} stuck agents"
        run_query "SELECT * FROM v_stuck_agents;"
        echo ""
        echo "💡 To cleanup stuck agents, run:"
        echo "   ./cleanup_stuck_agents.sh 60 --dry-run  # Preview"
        echo "   ./cleanup_stuck_agents.sh 60            # Execute"
    fi
}

show_24h_stats() {
    print_section "24-HOUR STATISTICS"
    run_query "SELECT * FROM v_agent_completion_stats_24h;"
}

show_7d_stats() {
    print_section "7-DAY STATISTICS"
    run_query "SELECT * FROM v_agent_completion_stats_7d;"
}

show_performance() {
    print_section "AGENT PERFORMANCE (Last 7 Days)"
    run_query "SELECT * FROM v_agent_performance LIMIT 20;"
}

show_recent_errors() {
    print_section "RECENT ERRORS (Last 7 Days)"

    # Check if any errors
    ERROR_COUNT=$(psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -t -c "
    SELECT COUNT(*) FROM v_agent_errors_recent;
    " | xargs)

    if [[ "$ERROR_COUNT" -eq 0 ]]; then
        echo "✅ No errors in last 7 days"
    else
        run_query "SELECT * FROM v_agent_errors_recent LIMIT 10;"
    fi
}

show_daily_trends() {
    print_section "DAILY TRENDS (Last 7 Days)"
    run_query "SELECT * FROM v_agent_daily_trends LIMIT 7;"
}

show_quality_leaderboard() {
    print_section "QUALITY LEADERBOARD (Last 7 Days, Min 3 Runs)"

    # Check if any agents with quality scores
    QUALITY_COUNT=$(psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -t -c "
    SELECT COUNT(*) FROM v_agent_quality_leaderboard;
    " | xargs)

    if [[ "$QUALITY_COUNT" -eq 0 ]]; then
        echo "ℹ️  No agents with quality scores (min 3 scored runs required)"
    else
        run_query "SELECT * FROM v_agent_quality_leaderboard LIMIT 10;"
    fi
}

show_help() {
    cat << EOF
Agent Execution Dashboard Statistics

Usage: ./dashboard_stats.sh [mode]

Modes:
  summary       Show high-level summary (default)
  active        Show currently active agents
  stuck         Show agents stuck in progress
  24h           Show 24-hour statistics
  7d            Show 7-day statistics
  performance   Show agent performance metrics
  errors        Show recent errors
  trends        Show daily trends
  quality       Show quality leaderboard
  all           Show all statistics

Examples:
  ./dashboard_stats.sh                    # Show summary
  ./dashboard_stats.sh active             # Show active agents
  ./dashboard_stats.sh performance        # Show performance metrics
  ./dashboard_stats.sh all                # Show everything

Exit Codes:
  0 - Dashboard displayed successfully
  1 - Invalid mode/argument, database query failed (non-fatal)
  3 - Configuration error (missing .env or credentials)
  4 - Dependency missing (psql not installed)

Database: ${DB_HOST}:${DB_PORT}/${DB_NAME}
EOF
}

# =====================================================================
# Main Display Logic
# =====================================================================

print_header "AGENT EXECUTION DASHBOARD - $(date)"

case "$DISPLAY_MODE" in
    summary)
        show_summary
        show_active_agents
        show_stuck_agents
        ;;

    active)
        show_active_agents
        show_stuck_agents
        ;;

    stuck)
        show_stuck_agents
        ;;

    24h)
        show_24h_stats
        ;;

    7d)
        show_7d_stats
        ;;

    performance)
        show_performance
        show_quality_leaderboard
        ;;

    errors)
        show_recent_errors
        ;;

    trends)
        show_daily_trends
        ;;

    quality)
        show_quality_leaderboard
        ;;

    all)
        show_summary
        show_active_agents
        show_stuck_agents
        show_24h_stats
        show_7d_stats
        show_performance
        show_recent_errors
        show_daily_trends
        show_quality_leaderboard
        ;;

    --help|-h|help)
        show_help
        exit 0
        ;;

    *)
        echo "❌ Unknown mode: $DISPLAY_MODE"
        echo ""
        show_help
        exit 1
        ;;
esac

# =====================================================================
# Footer
# =====================================================================

echo ""
echo "================================================================="
echo "Dashboard refreshed at: $(date)"
echo "Database: ${DB_HOST}:${DB_PORT}/${DB_NAME}"
echo "================================================================="
echo ""

exit 0
