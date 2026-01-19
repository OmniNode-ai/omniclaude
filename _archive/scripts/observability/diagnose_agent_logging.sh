#!/bin/bash
################################################################################
# diagnose_agent_logging.sh
#
# Purpose: Diagnose agent logging system health and identify issues
#
# What it checks:
# 1. Database connectivity (PostgreSQL)
# 2. agent_execution_logs table statistics
# 3. Kafka consumer service status
# 4. Event flow verification (Kafka → Consumer → Database)
# 5. Logger functionality test
#
# Usage:
#   ./diagnose_agent_logging.sh
#   ./diagnose_agent_logging.sh --verbose
#   ./diagnose_agent_logging.sh --fix-issues  # Attempt automatic fixes
#
# Prerequisites:
#   - PostgreSQL credentials in .env file
#   - Docker access (for checking consumer containers)
#   - Network access to Kafka broker
#
# Environment Variables (configured in .env):
#   POSTGRES_HOST (required)
#   POSTGRES_PORT (required)
#   POSTGRES_USER (required)
#   POSTGRES_PASSWORD (required)
#   POSTGRES_DATABASE (required)
#   KAFKA_BOOTSTRAP_SERVERS (required)
#
# Exit Codes (see scripts/observability/EXIT_CODES.md):
#   0 - All checks passed
#   1 - Critical issues found
#   2 - Warnings found (non-critical)
#   3 - Configuration error (missing .env or credentials)
#   4 - Dependency missing (psql, docker, etc.)
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
NC='\033[0m'

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
VERBOSE=false
FIX_ISSUES=false
ISSUES_FOUND=0
WARNINGS_FOUND=0

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --verbose|-v)
            VERBOSE=true
            shift
            ;;
        --fix-issues|-f)
            FIX_ISSUES=true
            shift
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
    exit 3  # Configuration error
fi

set -a
source "$PROJECT_ROOT/.env"
set +a

# Configuration (no fallbacks - must be set in .env)
POSTGRES_HOST="${POSTGRES_HOST}"
POSTGRES_PORT="${POSTGRES_PORT}"
POSTGRES_USER="${POSTGRES_USER}"
POSTGRES_DB="${POSTGRES_DATABASE}"
KAFKA_BOOTSTRAP_SERVERS="${KAFKA_BOOTSTRAP_SERVERS}"
export PGPASSWORD="${POSTGRES_PASSWORD}"

# Verify required variables are set
missing_vars=()
[ -z "$POSTGRES_HOST" ] && missing_vars+=("POSTGRES_HOST")
[ -z "$POSTGRES_PORT" ] && missing_vars+=("POSTGRES_PORT")
[ -z "$POSTGRES_USER" ] && missing_vars+=("POSTGRES_USER")
[ -z "$POSTGRES_DB" ] && missing_vars+=("POSTGRES_DATABASE")
[ -z "$PGPASSWORD" ] && missing_vars+=("POSTGRES_PASSWORD")
[ -z "$KAFKA_BOOTSTRAP_SERVERS" ] && missing_vars+=("KAFKA_BOOTSTRAP_SERVERS")

if [ ${#missing_vars[@]} -gt 0 ]; then
    echo -e "${RED}❌ ERROR: Required environment variables not set in .env:${NC}"
    for var in "${missing_vars[@]}"; do
        echo "   - $var"
    done
    echo ""
    echo "Please update your .env file with these variables."
    exit 3  # Configuration error
fi

# Helper functions
log_info() {
    echo -e "${CYAN}ℹ${NC}  $1"
}

log_success() {
    echo -e "${GREEN}✅${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}⚠️${NC}  $1"
    WARNINGS_FOUND=$((WARNINGS_FOUND + 1))
}

log_error() {
    echo -e "${RED}❌${NC} $1"
    ISSUES_FOUND=$((ISSUES_FOUND + 1))
}

log_verbose() {
    if [ "$VERBOSE" = true ]; then
        echo -e "${BLUE}  → $1${NC}"
    fi
}

section_header() {
    echo ""
    echo -e "${BLUE}═══════════════════════════════════════════════════════${NC}"
    echo -e "${BLUE}$1${NC}"
    echo -e "${BLUE}═══════════════════════════════════════════════════════${NC}"
}

check_command() {
    if command -v "$1" &> /dev/null; then
        log_verbose "Command '$1' is available"
        return 0
    else
        log_warning "Command '$1' not found (optional)"
        return 1
    fi
}

# Main diagnostic flow
echo -e "${CYAN}"
echo "╔═════════════════════════════════════════════════════════════════╗"
echo "║       Agent Logging System Diagnostic Tool                      ║"
echo "╚═════════════════════════════════════════════════════════════════╝"
echo -e "${NC}"
echo "Started: $(date '+%Y-%m-%d %H:%M:%S')"
echo ""

# Check 1: Database Connectivity
section_header "1. DATABASE CONNECTIVITY CHECK"

log_info "Testing PostgreSQL connection..."
log_verbose "Host: $POSTGRES_HOST:$POSTGRES_PORT"
log_verbose "Database: $POSTGRES_DB"
log_verbose "User: $POSTGRES_USER"

if [ -z "$POSTGRES_PASSWORD" ]; then
    log_error "POSTGRES_PASSWORD not set in environment"
    log_info "Set it in .env or export POSTGRES_PASSWORD=your_password"
else
    if psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
        -c "SELECT 1" &> /dev/null; then
        log_success "Database connection successful"

        # Check table exists
        TABLE_EXISTS=$(psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
            -tAc "SELECT EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'agent_execution_logs');" 2>/dev/null)

        if [ "$TABLE_EXISTS" = "t" ]; then
            log_success "agent_execution_logs table exists"
        else
            log_error "agent_execution_logs table not found"
            log_info "Run migrations: ./scripts/apply_migration.sh"
        fi
    else
        log_error "Cannot connect to database"
        log_info "Check credentials and network connectivity"
        log_info "Verify PostgreSQL container is running: docker ps | grep postgres"
    fi
fi

# Check 2: Agent Execution Logs Statistics
section_header "2. AGENT EXECUTION LOGS STATISTICS"

if [ "$TABLE_EXISTS" = "t" ]; then
    log_info "Querying agent_execution_logs statistics..."

    # Total records
    TOTAL_LOGS=$(psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
        -tAc "SELECT COUNT(*) FROM agent_execution_logs;" 2>/dev/null || echo "0")

    log_info "Total execution logs: $TOTAL_LOGS"

    if [ "$TOTAL_LOGS" -eq 0 ]; then
        log_warning "No execution logs found (system might be new or not used yet)"
    else
        log_success "Found $TOTAL_LOGS execution logs"

        # Recent activity (last 24 hours)
        RECENT_LOGS=$(psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
            -tAc "SELECT COUNT(*) FROM agent_execution_logs WHERE started_at > NOW() - INTERVAL '24 hours';" 2>/dev/null || echo "0")

        log_info "Logs in last 24 hours: $RECENT_LOGS"

        # Status breakdown
        STATUS_BREAKDOWN=$(psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
            -tAc "SELECT status, COUNT(*) FROM agent_execution_logs GROUP BY status ORDER BY status;" 2>/dev/null)

        if [ -n "$STATUS_BREAKDOWN" ]; then
            log_info "Status breakdown:"
            while IFS='|' read -r status count; do
                log_verbose "  $status: $count"
            done <<< "$STATUS_BREAKDOWN"
        fi

        # Average duration
        AVG_DURATION=$(psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
            -tAc "SELECT ROUND(AVG(duration_ms)::numeric, 2) FROM agent_execution_logs WHERE duration_ms IS NOT NULL;" 2>/dev/null)

        if [ -n "$AVG_DURATION" ] && [ "$AVG_DURATION" != "" ]; then
            log_info "Average execution duration: ${AVG_DURATION}ms"
        fi

        # Check for stuck executions (in_progress > 1 hour)
        STUCK_EXECUTIONS=$(psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
            -tAc "SELECT COUNT(*) FROM agent_execution_logs WHERE status = 'in_progress' AND started_at < NOW() - INTERVAL '1 hour';" 2>/dev/null || echo "0")

        if [ "$STUCK_EXECUTIONS" -gt 0 ]; then
            log_warning "Found $STUCK_EXECUTIONS stuck executions (in_progress > 1 hour)"
            log_info "These may indicate crashed agents or incomplete logging"
        else
            log_success "No stuck executions found"
        fi
    fi
else
    log_error "Skipping statistics check (table not found)"
fi

# Check 3: Kafka Consumer Status
section_header "3. KAFKA CONSUMER SERVICE CHECK"

log_info "Checking Kafka consumer containers..."

# Check for consumer containers
CONSUMER_CONTAINERS=$(docker ps --format "{{.Names}}" | grep -E "(consumer|kafka)" || echo "")

if [ -z "$CONSUMER_CONTAINERS" ]; then
    log_warning "No Kafka consumer containers found"
    log_info "Expected containers: archon-kafka-consumer, omniclaude_agent_consumer"
else
    log_success "Found consumer containers:"

    while IFS= read -r container; do
        # Check container health
        CONTAINER_STATUS=$(docker inspect --format='{{.State.Status}}' "$container" 2>/dev/null)
        CONTAINER_HEALTH=$(docker inspect --format='{{.State.Health.Status}}' "$container" 2>/dev/null)

        if [ "$CONTAINER_STATUS" = "running" ]; then
            if [ "$CONTAINER_HEALTH" = "healthy" ] || [ "$CONTAINER_HEALTH" = "" ]; then
                log_success "  $container: running"
            else
                log_warning "  $container: running but unhealthy ($CONTAINER_HEALTH)"
            fi

            # Check recent logs for errors
            ERROR_COUNT=$(docker logs --since 5m "$container" 2>&1 | grep -i "error" | wc -l)
            if [ "$ERROR_COUNT" -gt 10 ]; then
                log_warning "  $container: $ERROR_COUNT errors in last 5 minutes"
                if [ "$VERBOSE" = true ]; then
                    docker logs --tail 10 "$container" 2>&1 | grep -i "error" | sed 's/^/    /'
                fi
            fi
        else
            log_error "  $container: not running ($CONTAINER_STATUS)"
            if [ "$FIX_ISSUES" = true ]; then
                log_info "  Attempting to start container..."
                docker start "$container" &> /dev/null
            fi
        fi
    done <<< "$CONSUMER_CONTAINERS"
fi

# Check 4: Event Flow Verification
section_header "4. EVENT FLOW VERIFICATION"

log_info "Checking Kafka connectivity..."

# Check if kafkacat/kcat is available
if check_command "kcat" || check_command "kafkacat"; then
    KAFKA_CMD=$(command -v kcat || command -v kafkacat)

    # Test Kafka connection
    if timeout 5 "$KAFKA_CMD" -L -b "$KAFKA_BOOTSTRAP_SERVERS" &> /dev/null; then
        log_success "Kafka broker reachable at $KAFKA_BOOTSTRAP_SERVERS"

        # List relevant topics
        TOPICS=$("$KAFKA_CMD" -L -b "$KAFKA_BOOTSTRAP_SERVERS" 2>/dev/null | grep "topic" | grep -E "(agent|execution)" || echo "")

        if [ -n "$TOPICS" ]; then
            log_info "Agent-related Kafka topics:"
            echo "$TOPICS" | sed 's/^/  /' | sed 's/topic "/  /' | sed 's/" with/:/g'
        fi
    else
        log_warning "Cannot connect to Kafka broker at $KAFKA_BOOTSTRAP_SERVERS"
        log_info "Verify Redpanda container is running: docker ps | grep redpanda"
    fi
else
    log_warning "kafkacat/kcat not installed (optional - install for Kafka diagnostics)"
    log_info "Install with: brew install kcat"
fi

# Check recent agent_actions to verify Kafka → DB flow
if [ "$TABLE_EXISTS" = "t" ]; then
    RECENT_ACTIONS=$(psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
        -tAc "SELECT COUNT(*) FROM agent_actions WHERE created_at > NOW() - INTERVAL '5 minutes';" 2>/dev/null || echo "0")

    if [ "$RECENT_ACTIONS" -gt 0 ]; then
        log_success "Event flow working: $RECENT_ACTIONS actions logged in last 5 minutes"
    else
        log_warning "No recent agent actions logged (last 5 minutes)"
        log_info "This might be normal if no agents have run recently"
    fi
fi

# Check 5: Logger Functionality Test
section_header "5. LOGGER FUNCTIONALITY TEST"

log_info "Testing logger by querying recent execution patterns..."

if [ "$TABLE_EXISTS" = "t" ]; then
    # Check if we can query execution data
    QUERY_RESULT=$(psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
        -tAc "SELECT correlation_id, agent_name, status, started_at FROM agent_execution_logs ORDER BY started_at DESC LIMIT 5;" 2>/dev/null)

    if [ -n "$QUERY_RESULT" ]; then
        log_success "Logger queries working correctly"

        if [ "$VERBOSE" = true ]; then
            log_info "Recent executions:"
            echo "$QUERY_RESULT" | while IFS='|' read -r corr_id agent_name status started_at; do
                log_verbose "  $agent_name ($status) - $started_at"
            done
        fi
    else
        log_warning "No execution data found (might be new installation)"
    fi

    # Check for missing correlation IDs (data quality issue)
    NULL_CORRELATION=$(psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
        -tAc "SELECT COUNT(*) FROM agent_execution_logs WHERE correlation_id IS NULL;" 2>/dev/null || echo "0")

    if [ "$NULL_CORRELATION" -gt 0 ]; then
        log_warning "Found $NULL_CORRELATION execution logs with missing correlation_id"
        log_info "This indicates incomplete logging - correlation IDs are required for traceability"
    else
        log_success "All execution logs have valid correlation IDs"
    fi
fi

# Summary
section_header "DIAGNOSTIC SUMMARY"

echo ""
if [ "$ISSUES_FOUND" -eq 0 ] && [ "$WARNINGS_FOUND" -eq 0 ]; then
    echo -e "${GREEN}╔════════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║  ✅ ALL CHECKS PASSED                      ║${NC}"
    echo -e "${GREEN}║  Agent logging system is healthy!         ║${NC}"
    echo -e "${GREEN}╚════════════════════════════════════════════╝${NC}"
    EXIT_CODE=0
elif [ "$ISSUES_FOUND" -eq 0 ]; then
    echo -e "${YELLOW}╔════════════════════════════════════════════╗${NC}"
    echo -e "${YELLOW}║  ⚠️  WARNINGS FOUND: $WARNINGS_FOUND                      ║${NC}"
    echo -e "${YELLOW}║  System functional but needs attention    ║${NC}"
    echo -e "${YELLOW}╚════════════════════════════════════════════╝${NC}"
    EXIT_CODE=2
else
    echo -e "${RED}╔════════════════════════════════════════════╗${NC}"
    echo -e "${RED}║  ❌ CRITICAL ISSUES FOUND: $ISSUES_FOUND                ║${NC}"
    echo -e "${RED}║  Agent logging system needs fixes         ║${NC}"
    echo -e "${RED}╚════════════════════════════════════════════╝${NC}"
    EXIT_CODE=1
fi
echo ""

echo "Completed: $(date '+%Y-%m-%d %H:%M:%S')"
echo ""

if [ "$ISSUES_FOUND" -gt 0 ] || [ "$WARNINGS_FOUND" -gt 0 ]; then
    echo -e "${CYAN}Troubleshooting Tips:${NC}"
    echo "  • Run with --verbose for more details"
    echo "  • Check container logs: docker logs archon-kafka-consumer"
    echo "  • Verify .env configuration"
    echo "  • Run health check: ./scripts/health_check.sh"
    echo ""
fi

exit $EXIT_CODE
