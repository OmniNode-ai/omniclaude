#!/bin/bash
# =====================================================================
# Agent Activity Dashboard
# =====================================================================
# Purpose: Show comprehensive agent activity (not just routing service)
# Focus: Which agents are being used, what actions they take, success rates
# Database: Configured via .env file (POSTGRES_* variables)
# Usage: ./agent_activity_dashboard.sh [--routing|--manifests|--actions|--summary|--all]
# =====================================================================

set -euo pipefail

# =====================================================================
# Configuration
# =====================================================================

# Display mode (default: all)
DISPLAY_MODE="${1:-all}"

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
    echo ""
}

print_section() {
    echo ""
    echo "┌─────────────────────────────────────────────────────────────────┐"
    printf "│ %-63s │\n" "$1"
    echo "└─────────────────────────────────────────────────────────────────┘"
    echo ""
}

run_query() {
    psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -c "$1"
}

run_query_quiet() {
    psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -t -c "$1" | xargs
}

# =====================================================================
# Display Functions
# =====================================================================

show_routing_decisions() {
    print_section "🎯 LAST 10 AGENT ROUTING DECISIONS"

    COUNT=$(run_query_quiet "SELECT COUNT(*) FROM agent_routing_decisions;")

    if [[ "$COUNT" -eq 0 ]]; then
        echo "ℹ️  No routing decisions recorded yet"
        return
    fi

    run_query "
    SELECT
        TO_CHAR(created_at, 'MM-DD HH24:MI:SS') AS timestamp,
        selected_agent,
        ROUND(confidence_score::numeric, 2) AS confidence,
        routing_strategy,
        routing_time_ms || 'ms' AS routing_time,
        LEFT(user_request, 60) || '...' AS request_preview
    FROM agent_routing_decisions
    ORDER BY created_at DESC
    LIMIT 10;
    "

    echo ""
    echo "📊 Total routing decisions: $COUNT"
}

show_manifest_injections() {
    print_section "📋 LAST 5 MANIFEST INJECTIONS (Intelligence Context)"

    COUNT=$(run_query_quiet "SELECT COUNT(*) FROM agent_manifest_injections;")

    if [[ "$COUNT" -eq 0 ]]; then
        echo "ℹ️  No manifest injections recorded yet"
        return
    fi

    run_query "
    SELECT
        TO_CHAR(created_at, 'MM-DD HH24:MI:SS') AS timestamp,
        agent_name,
        patterns_count AS patterns,
        ROUND(manifest_size_bytes::numeric / 1024.0, 1) || ' KB' AS size,
        total_query_time_ms || 'ms' AS query_time,
        CASE
            WHEN total_query_time_ms < 2000 THEN '✅ Fast'
            WHEN total_query_time_ms < 5000 THEN '⚠️  Slow'
            ELSE '❌ Very Slow'
        END AS performance
    FROM agent_manifest_injections
    ORDER BY created_at DESC
    LIMIT 5;
    "

    echo ""
    echo "📊 Total manifest injections: $COUNT"

    # Show average performance
    AVG_QUERY_TIME=$(run_query_quiet "
        SELECT ROUND(AVG(total_query_time_ms)::numeric, 0)
        FROM agent_manifest_injections
        WHERE created_at > NOW() - INTERVAL '24 hours';
    ")

    if [[ -n "$AVG_QUERY_TIME" && "$AVG_QUERY_TIME" != "" ]]; then
        echo "📈 Average query time (24h): ${AVG_QUERY_TIME}ms"
    fi
}

show_agent_actions() {
    print_section "🔧 LAST 20 AGENT ACTIONS (Tool Calls, Decisions, Errors)"

    COUNT=$(run_query_quiet "SELECT COUNT(*) FROM agent_actions;")

    if [[ "$COUNT" -eq 0 ]]; then
        echo "ℹ️  No agent actions recorded yet"
        echo ""
        echo "💡 Note: This is normal if using event-based routing."
        echo "   Agent actions are only logged when agents explicitly log them."
        return
    fi

    run_query "
    SELECT
        TO_CHAR(created_at, 'MM-DD HH24:MI:SS') AS timestamp,
        CASE action_type
            WHEN 'tool_call' THEN '🔧'
            WHEN 'decision' THEN '💡'
            WHEN 'error' THEN '❌'
            WHEN 'success' THEN '✅'
            ELSE '❓'
        END AS icon,
        action_type,
        agent_name,
        action_name,
        COALESCE(duration_ms::text || 'ms', 'N/A') AS duration
    FROM agent_actions
    ORDER BY created_at DESC
    LIMIT 20;
    "

    echo ""
    echo "📊 Total agent actions: $COUNT"
}

show_24h_summary() {
    print_section "📊 AGENT ACTIVITY SUMMARY (Last 24 Hours)"

    # Count actions by type
    echo "Actions by Type:"
    run_query "
    SELECT
        CASE action_type
            WHEN 'tool_call' THEN '🔧 Tool Calls'
            WHEN 'decision' THEN '💡 Decisions'
            WHEN 'error' THEN '❌ Errors'
            WHEN 'success' THEN '✅ Successes'
            ELSE '❓ Unknown'
        END AS action_category,
        COUNT(*) AS count,
        ROUND(AVG(duration_ms)::numeric, 0) || 'ms' AS avg_duration
    FROM agent_actions
    WHERE created_at > NOW() - INTERVAL '24 hours'
    GROUP BY action_type
    ORDER BY COUNT(*) DESC;
    "

    echo ""
    echo "Actions by Agent:"

    ACTION_COUNT=$(run_query_quiet "
        SELECT COUNT(DISTINCT agent_name)
        FROM agent_actions
        WHERE created_at > NOW() - INTERVAL '24 hours';
    ")

    if [[ "$ACTION_COUNT" -eq 0 ]]; then
        echo "ℹ️  No agent actions in last 24 hours"
    else
        run_query "
        SELECT
            agent_name,
            COUNT(*) AS total_actions,
            SUM(CASE WHEN action_type = 'tool_call' THEN 1 ELSE 0 END) AS tool_calls,
            SUM(CASE WHEN action_type = 'decision' THEN 1 ELSE 0 END) AS decisions,
            SUM(CASE WHEN action_type = 'error' THEN 1 ELSE 0 END) AS errors,
            SUM(CASE WHEN action_type = 'success' THEN 1 ELSE 0 END) AS successes,
            CASE
                WHEN SUM(CASE WHEN action_type IN ('success', 'error') THEN 1 ELSE 0 END) > 0
                THEN ROUND(
                    100.0 * SUM(CASE WHEN action_type = 'success' THEN 1 ELSE 0 END)::numeric /
                    NULLIF(SUM(CASE WHEN action_type IN ('success', 'error') THEN 1 ELSE 0 END), 0),
                    1
                )
                ELSE NULL
            END || '%' AS success_rate,
            ROUND(AVG(duration_ms)::numeric, 0) || 'ms' AS avg_duration
        FROM agent_actions
        WHERE created_at > NOW() - INTERVAL '24 hours'
        GROUP BY agent_name
        ORDER BY total_actions DESC
        LIMIT 10;
        "
    fi

    echo ""
    echo "Agent Routing Summary (24h):"

    ROUTING_COUNT=$(run_query_quiet "
        SELECT COUNT(*)
        FROM agent_routing_decisions
        WHERE created_at > NOW() - INTERVAL '24 hours';
    ")

    if [[ "$ROUTING_COUNT" -eq 0 ]]; then
        echo "ℹ️  No routing decisions in last 24 hours"
    else
        run_query "
        SELECT
            selected_agent,
            COUNT(*) AS times_selected,
            ROUND(AVG(confidence_score::numeric), 2) AS avg_confidence,
            routing_strategy AS primary_strategy,
            ROUND(AVG(routing_time_ms)::numeric, 0) || 'ms' AS avg_routing_time
        FROM agent_routing_decisions
        WHERE created_at > NOW() - INTERVAL '24 hours'
        GROUP BY selected_agent, routing_strategy
        ORDER BY times_selected DESC
        LIMIT 10;
        "

        echo ""
        echo "📊 Total routing decisions (24h): $ROUTING_COUNT"
    fi
}

show_top_agents() {
    print_section "🏆 TOP AGENTS (All Time)"

    echo "By Routing Selections:"
    run_query "
    SELECT
        selected_agent,
        COUNT(*) AS times_selected,
        ROUND(AVG(confidence_score::numeric), 2) AS avg_confidence,
        ROUND(AVG(routing_time_ms)::numeric, 0) || 'ms' AS avg_routing_time,
        TO_CHAR(MAX(created_at), 'MM-DD HH24:MI') AS last_used
    FROM agent_routing_decisions
    GROUP BY selected_agent
    ORDER BY times_selected DESC
    LIMIT 10;
    "

    echo ""

    ACTION_COUNT=$(run_query_quiet "SELECT COUNT(*) FROM agent_actions;")

    if [[ "$ACTION_COUNT" -gt 0 ]]; then
        echo "By Actions Performed:"
        run_query "
        SELECT
            agent_name,
            COUNT(*) AS total_actions,
            SUM(CASE WHEN action_type = 'success' THEN 1 ELSE 0 END) AS successes,
            SUM(CASE WHEN action_type = 'error' THEN 1 ELSE 0 END) AS errors,
            TO_CHAR(MAX(created_at), 'MM-DD HH24:MI') AS last_active
        FROM agent_actions
        GROUP BY agent_name
        ORDER BY total_actions DESC
        LIMIT 10;
        "
    fi
}

show_help() {
    cat << EOF
Agent Activity Dashboard - Show ACTUAL agent usage and actions

Usage: ./agent_activity_dashboard.sh [mode]

Modes:
  routing       Show last 10 routing decisions (which agents selected)
  manifests     Show last 5 manifest injections (intelligence context)
  actions       Show last 20 agent actions (tool calls, decisions, errors)
  summary       Show 24-hour activity summary by agent
  top           Show top agents all-time
  all           Show all sections (default)
  help          Show this help

Examples:
  ./agent_activity_dashboard.sh                    # Show all
  ./agent_activity_dashboard.sh routing            # Just routing decisions
  ./agent_activity_dashboard.sh summary            # 24h summary

Database: ${DB_HOST}:${DB_PORT}/${DB_NAME}

Note: This dashboard shows ACTUAL agent activity (agents being used),
      not the routing service infrastructure.
EOF
}

# =====================================================================
# Main Display Logic
# =====================================================================

print_header "🤖 AGENT ACTIVITY DASHBOARD - $(date)"

case "$DISPLAY_MODE" in
    routing)
        show_routing_decisions
        ;;

    manifests)
        show_manifest_injections
        ;;

    actions)
        show_agent_actions
        ;;

    summary)
        show_24h_summary
        ;;

    top)
        show_top_agents
        ;;

    all)
        show_routing_decisions
        show_manifest_injections
        show_agent_actions
        show_24h_summary
        show_top_agents
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
