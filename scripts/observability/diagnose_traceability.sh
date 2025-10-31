#!/bin/bash
################################################################################
# diagnose_traceability.sh
#
# Purpose: Diagnose agent traceability system health and data integrity
#
# What it checks:
# 1. All traceability tables exist and have correct schema
# 2. Recent traceability data and activity patterns
# 3. File operation tracking (Read, Write, Edit operations)
# 4. Intelligence usage tracking (manifest injections, patterns)
# 5. Data relationships and integrity constraints
#
# Usage:
#   ./diagnose_traceability.sh
#   ./diagnose_traceability.sh --verbose
#   ./diagnose_traceability.sh --correlation-id <uuid>  # Check specific execution
#
# Prerequisites:
#   - PostgreSQL credentials in .env or environment variables
#   - Network access to database (192.168.86.200:5436)
#
# Environment Variables:
#   POSTGRES_HOST (default: 192.168.86.200)
#   POSTGRES_PORT (default: 5436)
#   POSTGRES_USER (default: postgres)
#   POSTGRES_PASSWORD (required)
#   POSTGRES_DB (default: omninode_bridge)
#
# Exit Codes:
#   0 - All checks passed
#   1 - Critical issues found
#   2 - Warnings found (non-critical)
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
CORRELATION_ID=""
ISSUES_FOUND=0
WARNINGS_FOUND=0

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --verbose|-v)
            VERBOSE=true
            shift
            ;;
        --correlation-id|-c)
            CORRELATION_ID="$2"
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
if [ -f "$PROJECT_ROOT/.env" ]; then
    set -a
    source "$PROJECT_ROOT/.env"
    set +a
fi

# Configuration with defaults
POSTGRES_HOST=${POSTGRES_HOST:-"192.168.86.200"}
POSTGRES_PORT=${POSTGRES_PORT:-"5436"}
POSTGRES_USER=${POSTGRES_USER:-"postgres"}
POSTGRES_DB=${POSTGRES_DB:-"omninode_bridge"}
export PGPASSWORD="${POSTGRES_PASSWORD}"

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

check_table_exists() {
    local table_name="$1"
    local exists=$(psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
        -tAc "SELECT EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = '$table_name');" 2>/dev/null)

    if [ "$exists" = "t" ]; then
        return 0
    else
        return 1
    fi
}

# Main diagnostic flow
echo -e "${CYAN}"
echo "╔═════════════════════════════════════════════════════════════════╗"
echo "║       Agent Traceability System Diagnostic Tool                 ║"
echo "╚═════════════════════════════════════════════════════════════════╝"
echo -e "${NC}"
echo "Started: $(date '+%Y-%m-%d %H:%M:%S')"
echo ""

# Check 1: Database Connection
section_header "1. DATABASE CONNECTIVITY CHECK"

log_info "Testing PostgreSQL connection..."
log_verbose "Host: $POSTGRES_HOST:$POSTGRES_PORT"
log_verbose "Database: $POSTGRES_DB"

if [ -z "$POSTGRES_PASSWORD" ]; then
    log_error "POSTGRES_PASSWORD not set in environment"
    log_info "Set it in .env or export POSTGRES_PASSWORD=your_password"
    exit 1
fi

if psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
    -c "SELECT 1" &> /dev/null; then
    log_success "Database connection successful"
else
    log_error "Cannot connect to database"
    log_info "Check credentials and network connectivity"
    exit 1
fi

# Check 2: Traceability Tables
section_header "2. TRACEABILITY TABLES CHECK"

log_info "Checking required traceability tables..."

# Define required tables (simple array for compatibility)
TRACEABILITY_TABLES=(
    "agent_execution_logs:Main execution tracking"
    "agent_actions:Tool calls and decisions"
    "agent_manifest_injections:Intelligence context tracking"
    "agent_routing_decisions:Agent selection and routing"
    "agent_transformation_events:Polymorphic transformations"
    "router_performance_metrics:Routing performance"
)

ALL_TABLES_EXIST=true
for table_entry in "${TRACEABILITY_TABLES[@]}"; do
    IFS=':' read -r table description <<< "$table_entry"

    if check_table_exists "$table"; then
        log_success "$table: exists ($description)"

        # Get row count
        ROW_COUNT=$(psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
            -tAc "SELECT COUNT(*) FROM $table;" 2>/dev/null || echo "0")

        log_verbose "  $ROW_COUNT total records"
    else
        log_error "$table: missing"
        ALL_TABLES_EXIST=false
    fi
done

if [ "$ALL_TABLES_EXIST" = false ]; then
    log_error "Some traceability tables are missing"
    log_info "Run migrations: ./scripts/apply_migration.sh"
fi

# Check 3: Recent Activity
section_header "3. RECENT TRACEABILITY ACTIVITY"

log_info "Checking activity in last 24 hours..."

# Execution logs
RECENT_EXECUTIONS=$(psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
    -tAc "SELECT COUNT(*) FROM agent_execution_logs WHERE started_at > NOW() - INTERVAL '24 hours';" 2>/dev/null || echo "0")

if [ "$RECENT_EXECUTIONS" -gt 0 ]; then
    log_success "Executions: $RECENT_EXECUTIONS in last 24h"
else
    log_warning "No executions in last 24 hours"
fi

# Actions
RECENT_ACTIONS=$(psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
    -tAc "SELECT COUNT(*) FROM agent_actions WHERE created_at > NOW() - INTERVAL '24 hours';" 2>/dev/null || echo "0")

log_info "Actions: $RECENT_ACTIONS in last 24h"

# Manifest injections
RECENT_MANIFESTS=$(psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
    -tAc "SELECT COUNT(*) FROM agent_manifest_injections WHERE created_at > NOW() - INTERVAL '24 hours';" 2>/dev/null || echo "0")

log_info "Manifest injections: $RECENT_MANIFESTS in last 24h"

# Routing decisions
RECENT_ROUTING=$(psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
    -tAc "SELECT COUNT(*) FROM agent_routing_decisions WHERE created_at > NOW() - INTERVAL '24 hours';" 2>/dev/null || echo "0")

log_info "Routing decisions: $RECENT_ROUTING in last 24h"

# Check 4: File Operation Tracking
section_header "4. FILE OPERATION TRACKING"

log_info "Analyzing file operations..."

# Count by action type
ACTION_BREAKDOWN=$(psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
    -tAc "SELECT action_name, COUNT(*) FROM agent_actions WHERE action_type = 'tool_call' AND action_name IN ('Read', 'Write', 'Edit', 'Glob', 'Grep', 'Bash') GROUP BY action_name ORDER BY COUNT(*) DESC;" 2>/dev/null)

if [ -n "$ACTION_BREAKDOWN" ]; then
    log_success "File operations tracked:"
    while IFS='|' read -r action count; do
        log_verbose "  $action: $count operations"
    done <<< "$ACTION_BREAKDOWN"
else
    log_warning "No file operations tracked yet"
fi

# Check for missing file details (data quality)
MISSING_DETAILS=$(psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
    -tAc "SELECT COUNT(*) FROM agent_actions WHERE action_type = 'tool_call' AND action_details = '{}'::jsonb;" 2>/dev/null || echo "0")

if [ "$MISSING_DETAILS" -gt 0 ]; then
    log_warning "$MISSING_DETAILS tool calls with missing details"
    log_info "This indicates incomplete action logging"
else
    log_success "All tool calls have detailed metadata"
fi

# Check 5: Intelligence Usage Tracking
section_header "5. INTELLIGENCE USAGE TRACKING"

log_info "Analyzing intelligence context usage..."

# Total manifest injections
TOTAL_MANIFESTS=$(psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
    -tAc "SELECT COUNT(*) FROM agent_manifest_injections;" 2>/dev/null || echo "0")

if [ "$TOTAL_MANIFESTS" -gt 0 ]; then
    log_success "Total manifest injections: $TOTAL_MANIFESTS"

    # Average patterns discovered
    AVG_PATTERNS=$(psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
        -tAc "SELECT ROUND(AVG(patterns_count)::numeric, 1) FROM agent_manifest_injections WHERE patterns_count IS NOT NULL;" 2>/dev/null)

    if [ -n "$AVG_PATTERNS" ]; then
        log_info "Average patterns per injection: $AVG_PATTERNS"
    fi

    # Average query time
    AVG_QUERY_TIME=$(psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
        -tAc "SELECT ROUND(AVG(total_query_time_ms)::numeric, 0) FROM agent_manifest_injections WHERE total_query_time_ms IS NOT NULL;" 2>/dev/null)

    if [ -n "$AVG_QUERY_TIME" ]; then
        log_info "Average query time: ${AVG_QUERY_TIME}ms"

        if [ "$AVG_QUERY_TIME" -gt 5000 ]; then
            log_warning "Query time >5000ms indicates performance issues"
        fi
    fi

    # Check for fallback manifests (intelligence failures)
    FALLBACK_MANIFESTS=$(psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
        -tAc "SELECT COUNT(*) FROM agent_manifest_injections WHERE patterns_count = 0 OR patterns_count IS NULL;" 2>/dev/null || echo "0")

    if [ "$FALLBACK_MANIFESTS" -gt 0 ]; then
        FALLBACK_PERCENT=$(psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
            -tAc "SELECT ROUND((COUNT(*) FILTER (WHERE patterns_count = 0 OR patterns_count IS NULL)::numeric / COUNT(*)::numeric * 100), 1) FROM agent_manifest_injections;" 2>/dev/null)

        log_warning "$FALLBACK_MANIFESTS fallback manifests (${FALLBACK_PERCENT}% of total)"
        log_info "High fallback rate indicates intelligence service issues"
    else
        log_success "All manifest injections have pattern data"
    fi
else
    log_warning "No manifest injections tracked yet"
fi

# Check 6: Data Integrity and Relationships
section_header "6. DATA INTEGRITY CHECK"

log_info "Verifying data relationships..."

# Check correlation ID consistency
ORPHAN_ACTIONS=$(psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
    -tAc "SELECT COUNT(*) FROM agent_actions WHERE correlation_id NOT IN (SELECT correlation_id FROM agent_execution_logs);" 2>/dev/null || echo "0")

if [ "$ORPHAN_ACTIONS" -gt 0 ]; then
    log_warning "$ORPHAN_ACTIONS actions with no matching execution log"
    log_info "This might be normal for ongoing executions"
else
    log_success "All actions linked to execution logs"
fi

# Check for missing correlation IDs
NULL_CORRELATIONS=$(psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
    -tAc "SELECT COUNT(*) FROM agent_execution_logs WHERE correlation_id IS NULL;" 2>/dev/null || echo "0")

if [ "$NULL_CORRELATIONS" -gt 0 ]; then
    log_warning "$NULL_CORRELATIONS execution logs with missing correlation_id"
    log_info "Correlation IDs are required for complete traceability"
else
    log_success "All execution logs have valid correlation IDs"
fi

# Check 7: Specific Correlation Trace (if provided)
if [ -n "$CORRELATION_ID" ]; then
    section_header "7. CORRELATION TRACE: $CORRELATION_ID"

    log_info "Tracing execution for correlation ID..."

    # Check execution log
    EXECUTION_EXISTS=$(psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
        -tAc "SELECT EXISTS(SELECT 1 FROM agent_execution_logs WHERE correlation_id::text = '$CORRELATION_ID');" 2>/dev/null)

    if [ "$EXECUTION_EXISTS" = "t" ]; then
        log_success "Execution log found"

        # Get execution details
        EXECUTION_DETAILS=$(psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
            -tAc "SELECT agent_name, status, started_at, duration_ms FROM agent_execution_logs WHERE correlation_id::text = '$CORRELATION_ID';" 2>/dev/null)

        if [ -n "$EXECUTION_DETAILS" ]; then
            IFS='|' read -r agent status started duration <<< "$EXECUTION_DETAILS"
            log_info "Agent: $agent"
            log_info "Status: $status"
            log_info "Started: $started"
            log_info "Duration: ${duration}ms"
        fi
    else
        log_warning "No execution log found for this correlation ID"
    fi

    # Count associated actions
    ACTION_COUNT=$(psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
        -tAc "SELECT COUNT(*) FROM agent_actions WHERE correlation_id::text = '$CORRELATION_ID';" 2>/dev/null || echo "0")

    log_info "Actions tracked: $ACTION_COUNT"

    # Check manifest injection
    MANIFEST_EXISTS=$(psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
        -tAc "SELECT EXISTS(SELECT 1 FROM agent_manifest_injections WHERE correlation_id::text = '$CORRELATION_ID');" 2>/dev/null)

    if [ "$MANIFEST_EXISTS" = "t" ]; then
        MANIFEST_DETAILS=$(psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
            -tAc "SELECT patterns_count, total_query_time_ms FROM agent_manifest_injections WHERE correlation_id::text = '$CORRELATION_ID';" 2>/dev/null)

        if [ -n "$MANIFEST_DETAILS" ]; then
            IFS='|' read -r patterns query_time <<< "$MANIFEST_DETAILS"
            log_info "Patterns discovered: $patterns"
            log_info "Query time: ${query_time}ms"
        fi
    else
        log_warning "No manifest injection found"
    fi

    # List actions
    if [ "$VERBOSE" = true ] && [ "$ACTION_COUNT" -gt 0 ]; then
        log_info "Action trace:"
        psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
            -c "SELECT action_type, action_name, duration_ms, created_at FROM agent_actions WHERE correlation_id::text = '$CORRELATION_ID' ORDER BY created_at;" 2>/dev/null | sed 's/^/  /'
    fi
fi

# Summary
section_header "DIAGNOSTIC SUMMARY"

echo ""
if [ "$ISSUES_FOUND" -eq 0 ] && [ "$WARNINGS_FOUND" -eq 0 ]; then
    echo -e "${GREEN}╔════════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║  ✅ ALL CHECKS PASSED                      ║${NC}"
    echo -e "${GREEN}║  Traceability system is healthy!          ║${NC}"
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
    echo -e "${RED}║  Traceability system needs fixes          ║${NC}"
    echo -e "${RED}╚════════════════════════════════════════════╝${NC}"
    EXIT_CODE=1
fi
echo ""

echo "Completed: $(date '+%Y-%m-%d %H:%M:%S')"
echo ""

if [ "$ISSUES_FOUND" -gt 0 ] || [ "$WARNINGS_FOUND" -gt 0 ]; then
    echo -e "${CYAN}Troubleshooting Tips:${NC}"
    echo "  • Run with --verbose for more details"
    echo "  • Check specific execution: --correlation-id <uuid>"
    echo "  • Browse history: python3 agents/lib/agent_history_browser.py"
    echo "  • Verify migrations: ./scripts/apply_migration.sh"
    echo ""
fi

exit $EXIT_CODE
