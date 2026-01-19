#!/bin/bash
################################################################################
# query_agent_history.sh
#
# Purpose: Query and display agent execution history with complete traceability
#
# What it shows:
# 1. Agent execution details (agent name, status, duration)
# 2. Complete action trace (tool calls, decisions, errors)
# 3. File operations performed (Read, Write, Edit)
# 4. Intelligence context used (patterns, manifest data)
# 5. Human-readable formatted output with colors
#
# Usage:
#   ./query_agent_history.sh
#   ./query_agent_history.sh --correlation-id <uuid>
#   ./query_agent_history.sh --agent <agent-name>
#   ./query_agent_history.sh --last 10
#   ./query_agent_history.sh --since "2025-10-28"
#   ./query_agent_history.sh --status error
#   ./query_agent_history.sh --export json > history.json
#
# Prerequisites:
#   - PostgreSQL credentials in .env file
#   - Network access to database
#
# Environment Variables (configured in .env):
#   POSTGRES_HOST (required)
#   POSTGRES_PORT (required)
#   POSTGRES_USER (required)
#   POSTGRES_PASSWORD (required)
#   POSTGRES_DATABASE (required)
#
# Created: 2025-10-29
################################################################################

set -o pipefail

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
MAGENTA='\033[0;35m'
NC='\033[0m'

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
CORRELATION_ID=""
AGENT_NAME=""
LAST=10
SINCE=""
STATUS=""
EXPORT_FORMAT=""

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --correlation-id|-c)
            CORRELATION_ID="$2"
            shift 2
            ;;
        --agent|-a)
            AGENT_NAME="$2"
            shift 2
            ;;
        --last|-l)
            LAST="$2"
            shift 2
            ;;
        --since|-s)
            SINCE="$2"
            shift 2
            ;;
        --status)
            STATUS="$2"
            shift 2
            ;;
        --export|-e)
            EXPORT_FORMAT="$2"
            shift 2
            ;;
        --help|-h)
            grep "^#" "$0" | grep -v "^#!/" | sed 's/^# //' | sed 's/^#//'
            exit 0
            ;;
        *)
            echo -e "${RED}Unknown option: $1${NC}"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

# Load environment
if [ ! -f "$PROJECT_ROOT/.env" ]; then
    echo -e "${RED}❌ ERROR: .env file not found at $PROJECT_ROOT/.env${NC}"
    echo "   Please copy .env.example to .env and configure it"
    exit 1
fi

set -a
source "$PROJECT_ROOT/.env"
set +a

# Configuration (no fallbacks - must be set in .env)
POSTGRES_HOST="${POSTGRES_HOST}"
POSTGRES_PORT="${POSTGRES_PORT}"
POSTGRES_USER="${POSTGRES_USER}"
POSTGRES_DB="${POSTGRES_DATABASE}"
export PGPASSWORD="${POSTGRES_PASSWORD}"

# Verify required variables are set
missing_vars=()
[ -z "$POSTGRES_HOST" ] && missing_vars+=("POSTGRES_HOST")
[ -z "$POSTGRES_PORT" ] && missing_vars+=("POSTGRES_PORT")
[ -z "$POSTGRES_USER" ] && missing_vars+=("POSTGRES_USER")
[ -z "$POSTGRES_DB" ] && missing_vars+=("POSTGRES_DATABASE")
[ -z "$PGPASSWORD" ] && missing_vars+=("POSTGRES_PASSWORD")

if [ ${#missing_vars[@]} -gt 0 ]; then
    echo -e "${RED}❌ ERROR: Required environment variables not set in .env:${NC}"
    for var in "${missing_vars[@]}"; do
        echo "   - $var"
    done
    echo ""
    echo "Please update your .env file with these variables."
    exit 1
fi

# Helper functions
log_info() {
    if [ "$EXPORT_FORMAT" = "" ]; then
        echo -e "${CYAN}ℹ${NC}  $1"
    fi
}

log_error() {
    echo -e "${RED}❌${NC} $1" >&2
}

section_header() {
    if [ "$EXPORT_FORMAT" = "" ]; then
        echo ""
        echo -e "${BLUE}═══════════════════════════════════════════════════════${NC}"
        echo -e "${BLUE}$1${NC}"
        echo -e "${BLUE}═══════════════════════════════════════════════════════${NC}"
    fi
}

format_duration() {
    local ms="$1"
    if [ -z "$ms" ] || [ "$ms" = "" ]; then
        echo "N/A"
    elif [ "$ms" -lt 0 ]; then
        # Negative duration indicates timezone bug
        echo -e "${RED}${ms}ms (INVALID - negative duration, timezone bug)${NC}"
    elif [ "$ms" -lt 1000 ]; then
        echo "${ms}ms"
    else
        local seconds=$(echo "scale=1; $ms / 1000" | bc)
        echo "${seconds}s"
    fi
}

format_status() {
    local status="$1"
    case "$status" in
        success)
            echo -e "${GREEN}✅ SUCCESS${NC}"
            ;;
        error)
            echo -e "${RED}❌ ERROR${NC}"
            ;;
        in_progress)
            echo -e "${YELLOW}⏳ IN PROGRESS${NC}"
            ;;
        cancelled)
            echo -e "${YELLOW}🚫 CANCELLED${NC}"
            ;;
        *)
            echo -e "${CYAN}${status}${NC}"
            ;;
    esac
}

format_action_type() {
    local action_type="$1"
    case "$action_type" in
        tool_call)
            echo -e "${BLUE}🔧${NC}"
            ;;
        decision)
            echo -e "${MAGENTA}🤔${NC}"
            ;;
        error)
            echo -e "${RED}⚠️${NC}"
            ;;
        success)
            echo -e "${GREEN}✓${NC}"
            ;;
        *)
            echo -e "${CYAN}•${NC}"
            ;;
    esac
}

# Check database connection
if [ -z "$POSTGRES_PASSWORD" ]; then
    log_error "POSTGRES_PASSWORD not set in environment"
    exit 1
fi

if ! psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
    -c "SELECT 1" &> /dev/null; then
    log_error "Cannot connect to database"
    exit 1
fi

# Build query based on filters
build_where_clause() {
    local where_parts=()

    if [ -n "$CORRELATION_ID" ]; then
        where_parts+=("LOWER(correlation_id::text) = LOWER('$CORRELATION_ID')")
    fi

    if [ -n "$AGENT_NAME" ]; then
        where_parts+=("agent_name ILIKE '%$AGENT_NAME%'")
    fi

    if [ -n "$STATUS" ]; then
        where_parts+=("status = '$STATUS'")
    fi

    if [ -n "$SINCE" ]; then
        where_parts+=("started_at >= '$SINCE'::timestamp")
    fi

    if [ ${#where_parts[@]} -gt 0 ]; then
        IFS=' AND ' eval 'echo "${where_parts[*]}"'
    else
        echo "1=1"
    fi
}

WHERE_CLAUSE=$(build_where_clause)

# Export mode (JSON output)
if [ "$EXPORT_FORMAT" = "json" ]; then
    QUERY="
    SELECT json_agg(
        json_build_object(
            'correlation_id', correlation_id,
            'agent_name', agent_name,
            'status', status,
            'started_at', started_at,
            'completed_at', completed_at,
            'duration_ms', duration_ms,
            'user_prompt', user_prompt,
            'error_message', error_message
        )
    )
    FROM agent_execution_logs
    WHERE $WHERE_CLAUSE
    ORDER BY started_at DESC
    LIMIT $LAST;
    "

    psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
        -tAc "$QUERY" 2>/dev/null

    exit 0
fi

# Interactive mode (formatted output)
echo -e "${CYAN}"
echo "╔═════════════════════════════════════════════════════════════════╗"
echo "║       Agent Execution History Query Tool                        ║"
echo "╚═════════════════════════════════════════════════════════════════╝"
echo -e "${NC}"

# Show filters if any
if [ -n "$CORRELATION_ID" ] || [ -n "$AGENT_NAME" ] || [ -n "$STATUS" ] || [ -n "$SINCE" ]; then
    log_info "Active filters:"
    [ -n "$CORRELATION_ID" ] && echo "  • Correlation ID: $CORRELATION_ID"
    [ -n "$AGENT_NAME" ] && echo "  • Agent Name: $AGENT_NAME"
    [ -n "$STATUS" ] && echo "  • Status: $STATUS"
    [ -n "$SINCE" ] && echo "  • Since: $SINCE"
    echo ""
fi

# Query executions
QUERY="
SELECT
    correlation_id,
    agent_name,
    status,
    started_at,
    completed_at,
    duration_ms,
    user_prompt,
    error_message
FROM agent_execution_logs
WHERE $WHERE_CLAUSE
ORDER BY started_at DESC
LIMIT $LAST;
"

RESULTS=$(psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
    -tA -F'|' -c "$QUERY" 2>/dev/null)

if [ -z "$RESULTS" ]; then
    log_info "No executions found matching criteria"
    exit 0
fi

# Count total results
RESULT_COUNT=$(echo "$RESULTS" | wc -l | tr -d ' ')
log_info "Found $RESULT_COUNT execution(s)"

# Display each execution
EXECUTION_NUM=0
while IFS='|' read -r corr_id agent status started completed duration prompt error_msg; do
    EXECUTION_NUM=$((EXECUTION_NUM + 1))

    section_header "EXECUTION #$EXECUTION_NUM"

    # Basic info
    echo -e "${CYAN}Correlation ID:${NC} $corr_id"
    echo -e "${CYAN}Agent:${NC} $agent"
    echo -e "${CYAN}Status:${NC} $(format_status "$status")"
    echo -e "${CYAN}Started:${NC} $started"
    [ -n "$completed" ] && echo -e "${CYAN}Completed:${NC} $completed"
    [ -n "$duration" ] && echo -e "${CYAN}Duration:${NC} $(format_duration "$duration")"

    # User prompt
    if [ -n "$prompt" ]; then
        echo ""
        echo -e "${CYAN}User Prompt:${NC}"
        echo "$prompt" | fold -w 70 -s | sed 's/^/  /'
    fi

    # Error message
    if [ -n "$error_msg" ]; then
        echo ""
        echo -e "${RED}Error:${NC}"
        echo "$error_msg" | fold -w 70 -s | sed 's/^/  /'
    fi

    # Query associated actions
    ACTIONS_QUERY="
    SELECT
        action_type,
        action_name,
        duration_ms,
        to_char(created_at, 'HH24:MI:SS.MS') as time,
        action_details::text
    FROM agent_actions
    WHERE LOWER(correlation_id::text) = LOWER('$corr_id')
    ORDER BY created_at;
    "

    ACTIONS=$(psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
        -tA -F'|' -c "$ACTIONS_QUERY" 2>/dev/null)

    if [ -n "$ACTIONS" ]; then
        ACTION_COUNT=$(echo "$ACTIONS" | wc -l | tr -d ' ')
        echo ""
        echo -e "${CYAN}Actions (${ACTION_COUNT}):${NC}"

        while IFS='|' read -r action_type action_name action_duration time details; do
            icon=$(format_action_type "$action_type")
            duration_fmt=$(format_duration "$action_duration")

            echo -e "  $icon $time | ${BLUE}$action_name${NC} ($action_type) - $duration_fmt"

            # Show key details for tool calls
            if [ "$action_type" = "tool_call" ] && [ -n "$details" ] && [ "$details" != "{}" ]; then
                case "$action_name" in
                    Read|Write|Edit)
                        file_path=$(echo "$details" | grep -o '"file_path"[[:space:]]*:[[:space:]]*"[^"]*"' | sed 's/.*"\([^"]*\)".*/\1/' | head -n 1)
                        [ -n "$file_path" ] && [ "$file_path" != "null" ] && echo -e "     ${CYAN}→${NC} $file_path"
                        ;;
                    Bash)
                        command=$(echo "$details" | grep -o '"command"[[:space:]]*:[[:space:]]*"[^"]*"' | sed 's/.*"\([^"]*\)".*/\1/' | head -n 1)
                        [ -n "$command" ] && [ "$command" != "null" ] && echo -e "     ${CYAN}→${NC} $command"
                        ;;
                    Glob|Grep)
                        pattern=$(echo "$details" | grep -o '"pattern"[[:space:]]*:[[:space:]]*"[^"]*"' | sed 's/.*"\([^"]*\)".*/\1/' | head -n 1)
                        [ -n "$pattern" ] && [ "$pattern" != "null" ] && echo -e "     ${CYAN}→${NC} pattern: $pattern"
                        ;;
                esac
            fi
        done <<< "$ACTIONS"
    else
        echo ""
        echo -e "  ${YELLOW}⚠️  No tool executions found (check correlation ID format)${NC}"
    fi

    # Query manifest injection data
    MANIFEST_QUERY="
    SELECT
        patterns_count,
        total_query_time_ms,
        sections_content::jsonb->'patterns' as patterns
    FROM agent_manifest_injections
    WHERE LOWER(correlation_id::text) = LOWER('$corr_id');
    "

    MANIFEST=$(psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
        -tA -F'|' -c "$MANIFEST_QUERY" 2>/dev/null)

    if [ -n "$MANIFEST" ]; then
        IFS='|' read -r patterns_count query_time patterns_data <<< "$MANIFEST"

        if [ -n "$patterns_count" ] && [ "$patterns_count" != "0" ]; then
            echo ""
            echo -e "${CYAN}Intelligence Context:${NC}"
            echo -e "  Patterns discovered: $patterns_count"
            [ -n "$query_time" ] && echo -e "  Query time: $(format_duration "$query_time")"
        fi
    fi

    # Query routing decision
    ROUTING_QUERY="
    SELECT
        selected_agent,
        confidence_score,
        routing_strategy,
        reasoning
    FROM agent_routing_decisions
    WHERE LOWER(correlation_id::text) = LOWER('$corr_id');
    "

    ROUTING=$(psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
        -tA -F'|' -c "$ROUTING_QUERY" 2>/dev/null)

    if [ -n "$ROUTING" ]; then
        IFS='|' read -r selected_agent confidence strategy reasoning <<< "$ROUTING"

        echo ""
        echo -e "${CYAN}Routing Decision:${NC}"
        echo -e "  Selected: $selected_agent"
        [ -n "$confidence" ] && echo -e "  Confidence: $(echo "scale=1; $confidence * 100" | bc)%"
        [ -n "$strategy" ] && echo -e "  Strategy: $strategy"
        if [ -n "$reasoning" ]; then
            echo -e "  Reasoning:"
            echo "$reasoning" | fold -w 66 -s | sed 's/^/    /'
        fi
    fi

    echo ""

done <<< "$RESULTS"

# Summary statistics
if [ "$RESULT_COUNT" -gt 1 ]; then
    section_header "SUMMARY STATISTICS"

    # Status breakdown
    STATUS_STATS=$(psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
        -tA -F'|' -c "
        SELECT status, COUNT(*), ROUND(AVG(duration_ms)::numeric, 0)
        FROM agent_execution_logs
        WHERE $WHERE_CLAUSE
        GROUP BY status
        ORDER BY COUNT(*) DESC;
        " 2>/dev/null)

    if [ -n "$STATUS_STATS" ]; then
        echo -e "${CYAN}Status Breakdown:${NC}"
        while IFS='|' read -r status count avg_duration; do
            echo -e "  $(format_status "$status"): $count executions (avg: $(format_duration "$avg_duration"))"
        done <<< "$STATUS_STATS"
    fi

    # Most active agents
    AGENT_STATS=$(psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
        -tA -F'|' -c "
        SELECT agent_name, COUNT(*)
        FROM agent_execution_logs
        WHERE $WHERE_CLAUSE AND agent_name IS NOT NULL
        GROUP BY agent_name
        ORDER BY COUNT(*) DESC
        LIMIT 5;
        " 2>/dev/null)

    if [ -n "$AGENT_STATS" ]; then
        echo ""
        echo -e "${CYAN}Most Active Agents:${NC}"
        while IFS='|' read -r agent count; do
            echo -e "  ${BLUE}$agent${NC}: $count executions"
        done <<< "$AGENT_STATS"
    fi

    echo ""
fi

echo -e "${CYAN}Query completed: $(date '+%Y-%m-%d %H:%M:%S')${NC}"
echo ""

exit 0
