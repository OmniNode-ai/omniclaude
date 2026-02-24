#!/bin/bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# ============================================================================
# ROUTING HEALTH MONITORING SCRIPT
# ============================================================================
# Purpose: Monitor routing health with threshold checks and alerts
# Database: omninode_bridge
# Queries: routing_metrics.sql
# Correlation ID: 60d7acac-8d46-4041-ae43-49f1aa7fdccc
#
# Exit Codes (see scripts/observability/EXIT_CODES.md):
#   0 - All checks passed, routing system healthy
#   1 - Threshold violations found, system degraded
#   3 - Configuration error (missing .env, SQL file, or credentials)
#   4 - Dependency missing (psql, bc not installed)
# ============================================================================

set -euo pipefail

# ============================================================================
# Configuration
# ============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
SQL_FILE="$SCRIPT_DIR/routing_metrics.sql"
LOG_DIR="$PROJECT_ROOT/logs/observability"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
LOG_FILE="$LOG_DIR/routing_health_${TIMESTAMP}.log"

# Load environment variables from .env
if [ ! -f "$PROJECT_ROOT/.env" ]; then
    echo "❌ ERROR: .env file not found at $PROJECT_ROOT/.env"
    echo "   Please copy .env.example to .env and configure it"
    exit 3  # Configuration error
fi

# Source .env file
# shellcheck disable=SC1091
source "$PROJECT_ROOT/.env"

# Database connection parameters (no fallbacks - must be set in .env)
DB_HOST="${POSTGRES_HOST}"
DB_PORT="${POSTGRES_PORT}"
DB_NAME="${POSTGRES_DATABASE}"
DB_USER="${POSTGRES_USER}"
# Note: Using POSTGRES_PASSWORD directly (no alias)

# Verify required variables are set
missing_vars=()
[ -z "$DB_HOST" ] && missing_vars+=("POSTGRES_HOST")
[ -z "$DB_PORT" ] && missing_vars+=("POSTGRES_PORT")
[ -z "$DB_NAME" ] && missing_vars+=("POSTGRES_DATABASE")
[ -z "$DB_USER" ] && missing_vars+=("POSTGRES_USER")
[ -z "$POSTGRES_PASSWORD" ] && missing_vars+=("POSTGRES_PASSWORD")

if [ ${#missing_vars[@]} -gt 0 ]; then
    echo "❌ ERROR: Required environment variables not set in .env:"
    for var in "${missing_vars[@]}"; do
        echo "   - $var"
    done
    echo ""
    echo "Please update your .env file with these variables."
    exit 3  # Configuration error
fi

# Thresholds
SELF_TRANSFORMATION_THRESHOLD=10
BYPASS_ATTEMPT_THRESHOLD=0
AVG_CONFIDENCE_THRESHOLD=0.7
FRONTEND_ACCURACY_THRESHOLD=100
FAILURE_RATE_THRESHOLD=5

# Colors
RED='\033[0;31m'
YELLOW='\033[1;33m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# ============================================================================
# Helper Functions
# ============================================================================

print_header() {
    echo ""
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${BLUE}  $1${NC}"
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""
}

print_success() {
    echo -e "${GREEN}✅ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

print_error() {
    echo -e "${RED}❌ $1${NC}"
}

print_info() {
    echo -e "${BLUE}ℹ️  $1${NC}"
}

check_prerequisites() {
    # Check psql
    if ! command -v psql &> /dev/null; then
        print_error "psql command not found. Please install PostgreSQL client."
        exit 4  # Dependency missing
    fi

    # Check bc (for float comparisons)
    if ! command -v bc &> /dev/null; then
        print_error "bc command not found. Please install bc for floating-point comparisons."
        echo "  macOS: brew install bc"
        echo "  Ubuntu/Debian: sudo apt-get install bc"
        exit 4  # Dependency missing
    fi

    # Check SQL file
    if [ ! -f "$SQL_FILE" ]; then
        print_error "SQL file not found: $SQL_FILE"
        exit 3  # Configuration error
    fi

    # Check database connection
    if [ -z "$POSTGRES_PASSWORD" ]; then
        print_error "POSTGRES_PASSWORD not set in environment"
        exit 3  # Configuration error
    fi
}

setup_log_directory() {
    if [ ! -d "$LOG_DIR" ]; then
        mkdir -p "$LOG_DIR"
        print_info "Created log directory: $LOG_DIR"
    fi
}

# ============================================================================
# Metric Check Functions
# ============================================================================

check_self_transformation_rate() {
    local query="
        WITH transformation_stats AS (
            SELECT
                COUNT(*) FILTER (
                    WHERE source_agent = 'polymorphic-agent'
                    AND target_agent = 'polymorphic-agent'
                ) as self_transformations,
                COUNT(*) FILTER (
                    WHERE source_agent = 'polymorphic-agent'
                ) as total_transformations
            FROM agent_transformation_events
            WHERE created_at > NOW() - INTERVAL '7 days'
        )
        SELECT
            COALESCE(
                ROUND(
                    CASE
                        WHEN total_transformations > 0
                        THEN (self_transformations::numeric / total_transformations::numeric) * 100
                        ELSE 0
                    END,
                    2
                ),
                0
            ) as rate
        FROM transformation_stats;
    "

    local rate
    rate=$(PGPASSWORD="$POSTGRES_PASSWORD" psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -t -c "$query" 2>/dev/null | tr -d ' ')

    if [ -z "$rate" ] || [ "$rate" = "" ]; then
        rate="0"
    fi

    echo "$rate"
}

check_bypass_attempts() {
    local query="
        SELECT
            COUNT(*) as bypass_count
        FROM agent_routing_decisions
        WHERE created_at > NOW() - INTERVAL '7 days'
        AND (
            routing_strategy IS NULL
            OR routing_strategy = ''
            OR (confidence_score > 0.99 AND alternatives = '[]'::jsonb)
            OR routing_time_ms < 1
        );
    "

    local count
    count=$(PGPASSWORD="$POSTGRES_PASSWORD" psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -t -c "$query" 2>/dev/null | tr -d ' ')

    if [ -z "$count" ] || [ "$count" = "" ]; then
        count="0"
    fi

    echo "$count"
}

check_avg_confidence() {
    local query="
        SELECT
            COALESCE(ROUND(AVG(confidence_score), 3), 0)
        FROM agent_routing_decisions
        WHERE created_at > NOW() - INTERVAL '7 days'
        AND confidence_score IS NOT NULL;
    "

    local avg
    avg=$(PGPASSWORD="$POSTGRES_PASSWORD" psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -t -c "$query" 2>/dev/null | tr -d ' ')

    if [ -z "$avg" ] || [ "$avg" = "" ]; then
        avg="0"
    fi

    echo "$avg"
}

check_frontend_accuracy() {
    local query="
        WITH frontend_tasks AS (
            SELECT
                CASE
                    WHEN selected_agent IN ('agent-frontend-developer', 'frontend-developer')
                    THEN true
                    ELSE false
                END as routed_to_frontend
            FROM agent_routing_decisions
            WHERE created_at > NOW() - INTERVAL '7 days'
            AND (
                LOWER(user_request) LIKE '%frontend%'
                OR LOWER(user_request) LIKE '%react%'
                OR LOWER(user_request) LIKE '%vue%'
                OR LOWER(user_request) LIKE '%angular%'
                OR LOWER(user_request) LIKE '%ui component%'
                OR LOWER(user_request) LIKE '%css%'
                OR LOWER(user_request) LIKE '%html%'
            )
        )
        SELECT
            COALESCE(
                ROUND(
                    CASE
                        WHEN COUNT(*) > 0
                        THEN (COUNT(*) FILTER (WHERE routed_to_frontend = true)::numeric / COUNT(*)::numeric) * 100
                        ELSE 100
                    END,
                    2
                ),
                100
            )
        FROM frontend_tasks;
    "

    local accuracy
    accuracy=$(PGPASSWORD="$POSTGRES_PASSWORD" psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -t -c "$query" 2>/dev/null | tr -d ' ')

    if [ -z "$accuracy" ] || [ "$accuracy" = "" ]; then
        accuracy="100"
    fi

    echo "$accuracy"
}

check_failure_rate() {
    local query="
        SELECT
            COALESCE(
                ROUND(
                    CASE
                        WHEN COUNT(*) > 0
                        THEN (COUNT(*) FILTER (WHERE execution_succeeded = false)::numeric / COUNT(*)::numeric) * 100
                        ELSE 0
                    END,
                    2
                ),
                0
            )
        FROM agent_routing_decisions
        WHERE created_at > NOW() - INTERVAL '7 days';
    "

    local rate
    rate=$(PGPASSWORD="$POSTGRES_PASSWORD" psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -t -c "$query" 2>/dev/null | tr -d ' ')

    if [ -z "$rate" ] || [ "$rate" = "" ]; then
        rate="0"
    fi

    echo "$rate"
}

# ============================================================================
# Threshold Validation
# ============================================================================

validate_thresholds() {
    print_header "THRESHOLD VALIDATION"

    local violations=0

    # Check 1: Self-transformation rate
    print_info "Checking self-transformation rate..."
    local self_transform_rate
    self_transform_rate=$(check_self_transformation_rate)

    if (( $(echo "$self_transform_rate > $SELF_TRANSFORMATION_THRESHOLD" | bc -l) )); then
        print_error "Self-transformation rate: ${self_transform_rate}% (threshold: ${SELF_TRANSFORMATION_THRESHOLD}%)"
        violations=$((violations + 1))
    else
        print_success "Self-transformation rate: ${self_transform_rate}% (threshold: ${SELF_TRANSFORMATION_THRESHOLD}%)"
    fi

    # Check 2: Bypass attempts
    print_info "Checking bypass attempts..."
    local bypass_count
    bypass_count=$(check_bypass_attempts)

    if [ "$bypass_count" -gt "$BYPASS_ATTEMPT_THRESHOLD" ]; then
        print_error "Bypass attempts: ${bypass_count} (threshold: ${BYPASS_ATTEMPT_THRESHOLD})"
        violations=$((violations + 1))
    else
        print_success "Bypass attempts: ${bypass_count} (threshold: ${BYPASS_ATTEMPT_THRESHOLD})"
    fi

    # Check 3: Average confidence
    print_info "Checking average routing confidence..."
    local avg_confidence
    avg_confidence=$(check_avg_confidence)

    if (( $(echo "$avg_confidence < $AVG_CONFIDENCE_THRESHOLD" | bc -l) )); then
        print_error "Average confidence: ${avg_confidence} (threshold: ${AVG_CONFIDENCE_THRESHOLD})"
        violations=$((violations + 1))
    else
        print_success "Average confidence: ${avg_confidence} (threshold: ${AVG_CONFIDENCE_THRESHOLD})"
    fi

    # Check 4: Frontend routing accuracy
    print_info "Checking frontend routing accuracy..."
    local frontend_accuracy
    frontend_accuracy=$(check_frontend_accuracy)

    if (( $(echo "$frontend_accuracy < $FRONTEND_ACCURACY_THRESHOLD" | bc -l) )); then
        print_warning "Frontend accuracy: ${frontend_accuracy}% (threshold: ${FRONTEND_ACCURACY_THRESHOLD}%)"
        violations=$((violations + 1))
    else
        print_success "Frontend accuracy: ${frontend_accuracy}% (threshold: ${FRONTEND_ACCURACY_THRESHOLD}%)"
    fi

    # Check 5: Failure rate
    print_info "Checking failure rate..."
    local failure_rate
    failure_rate=$(check_failure_rate)

    if (( $(echo "$failure_rate > $FAILURE_RATE_THRESHOLD" | bc -l) )); then
        print_error "Failure rate: ${failure_rate}% (threshold: ${FAILURE_RATE_THRESHOLD}%)"
        violations=$((violations + 1))
    else
        print_success "Failure rate: ${failure_rate}% (threshold: ${FAILURE_RATE_THRESHOLD}%)"
    fi

    echo ""
    if [ $violations -eq 0 ]; then
        print_success "All thresholds passed! 🎉"
        return 0
    else
        print_error "Found $violations threshold violation(s)"
        return 1
    fi
}

# ============================================================================
# Main Execution
# ============================================================================

main() {
    print_header "ROUTING HEALTH MONITORING"
    echo "Timestamp: $(date '+%Y-%m-%d %H:%M:%S')"
    echo "Database: $DB_HOST:$DB_PORT/$DB_NAME"
    echo "Log File: $LOG_FILE"
    echo ""

    # Check prerequisites
    print_info "Checking prerequisites..."
    check_prerequisites  # Exits with 3 or 4 on failure
    print_success "Prerequisites check passed"
    echo ""

    # Setup log directory
    setup_log_directory

    # Validate thresholds
    local threshold_status=0
    if ! validate_thresholds; then
        threshold_status=1
    fi

    # Run full metrics report
    print_header "DETAILED METRICS REPORT"
    print_info "Running comprehensive routing metrics queries..."
    echo ""

    if PGPASSWORD="$POSTGRES_PASSWORD" psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -f "$SQL_FILE" 2>&1 | tee -a "$LOG_FILE"; then
        print_success "Metrics report completed successfully"
    else
        print_error "Metrics report execution failed"
        threshold_status=1
    fi

    # Save results
    print_header "RESULTS SAVED"
    print_success "Full report saved to: $LOG_FILE"
    echo ""

    # Final status
    print_header "FINAL STATUS"
    if [ $threshold_status -eq 0 ]; then
        print_success "🟢 ROUTING HEALTH: HEALTHY"
        echo ""
        echo "All metrics within acceptable thresholds."
        exit 0
    else
        print_error "🔴 ROUTING HEALTH: ISSUES DETECTED"
        echo ""
        echo "Review the detailed report above for threshold violations."
        echo "Log file: $LOG_FILE"
        exit 1
    fi
}

# ============================================================================
# Script Entry Point
# ============================================================================

# Run main function (prerequisites are checked inside main)
main "$@"
