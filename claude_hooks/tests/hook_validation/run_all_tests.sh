#!/usr/bin/env bash
# run_all_tests.sh - Master test runner for hook validation framework
#
# Executes all hook tests and generates validation report

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Test directory
TEST_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RESULTS_DIR="$TEST_DIR/results"
mkdir -p "$RESULTS_DIR"

# Logging
LOG_FILE="$RESULTS_DIR/test_run_$(date +%Y%m%d_%H%M%S).log"

log() {
    echo -e "[$(date +'%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"
}

log_success() {
    echo -e "${GREEN}✓${NC} $*" | tee -a "$LOG_FILE"
}

log_error() {
    echo -e "${RED}✗${NC} $*" | tee -a "$LOG_FILE"
}

log_warning() {
    echo -e "${YELLOW}⚠${NC} $*" | tee -a "$LOG_FILE"
}

log_info() {
    echo -e "${BLUE}ℹ${NC} $*" | tee -a "$LOG_FILE"
}

# Test results tracking
TESTS_PASSED=0
TESTS_FAILED=0
TESTS_SKIPPED=0

run_test() {
    local test_name="$1"
    local test_script="$2"

    log_info "Running: $test_name"

    if [[ ! -f "$test_script" ]]; then
        log_warning "Test script not found: $test_script (SKIPPED)"
        TESTS_SKIPPED=$((TESTS_SKIPPED + 1))
        return 0
    fi

    if ! bash "$test_script" > "$RESULTS_DIR/${test_name}.log" 2>&1; then
        log_error "$test_name FAILED (see $RESULTS_DIR/${test_name}.log)"
        TESTS_FAILED=$((TESTS_FAILED + 1))
        return 1
    else
        log_success "$test_name PASSED"
        TESTS_PASSED=$((TESTS_PASSED + 1))
        return 0
    fi
}

run_python_test() {
    local test_name="$1"
    local test_script="$2"

    log_info "Running: $test_name"

    if [[ ! -f "$test_script" ]]; then
        log_warning "Test script not found: $test_script (SKIPPED)"
        TESTS_SKIPPED=$((TESTS_SKIPPED + 1))
        return 0
    fi

    if ! python3 "$test_script" > "$RESULTS_DIR/${test_name}.log" 2>&1; then
        log_error "$test_name FAILED (see $RESULTS_DIR/${test_name}.log)"
        TESTS_FAILED=$((TESTS_FAILED + 1))
        return 1
    else
        log_success "$test_name PASSED"
        TESTS_PASSED=$((TESTS_PASSED + 1))
        return 0
    fi
}

# Main test execution
log "=========================================="
log "Hook Validation Test Suite"
log "=========================================="
log "Started: $(date)"
log ""

# Pre-flight checks
log_info "Pre-flight checks..."

# Check database connectivity
if ! PGPASSWORD="omninode-bridge-postgres-dev-2024" psql -h localhost -p 5436 -U postgres -d omninode_bridge -c "SELECT 1" > /dev/null 2>&1; then
    log_error "Database not available! Tests require database connection."
    exit 1
fi
log_success "Database connectivity OK"

# Check Python dependencies
if ! python3 -c "import psycopg2" 2>/dev/null; then
    log_warning "psycopg2 not installed - some tests may fail"
fi

log ""
log_info "Starting test execution..."
log ""

# 1. Session Hooks Tests
log "=========================================="
log "1. Session Hooks Tests"
log "=========================================="
run_test "session_hooks" "$TEST_DIR/test_session_hooks.sh" || true
log ""

# 2. Stop Hook Tests
log "=========================================="
log "2. Stop Hook Tests"
log "=========================================="
run_test "stop_hook" "$TEST_DIR/test_stop_hook.sh" || true
log ""

# 3. Enhanced Metadata Tests
log "=========================================="
log "3. Enhanced Metadata Tests"
log "=========================================="
run_test "enhanced_metadata" "$TEST_DIR/test_enhanced_metadata.sh" || true
log ""

# 4. Performance Tests
log "=========================================="
log "4. Performance Tests"
log "=========================================="
run_python_test "performance" "$TEST_DIR/test_performance.py" || true
log ""

# 5. Integration Tests
log "=========================================="
log "5. Integration Tests"
log "=========================================="
run_python_test "integration" "$TEST_DIR/test_integration.py" || true
log ""

# 6. Generate Validation Report
log "=========================================="
log "6. Validation Report Generation"
log "=========================================="
if [[ -f "$TEST_DIR/generate_validation_report.py" ]]; then
    log_info "Generating validation report..."
    if python3 "$TEST_DIR/generate_validation_report.py" > "$RESULTS_DIR/validation_report.md" 2>&1; then
        log_success "Validation report generated: $RESULTS_DIR/validation_report.md"

        # Also generate JSON report
        if python3 "$TEST_DIR/generate_validation_report.py" --format json > "$RESULTS_DIR/validation_report.json" 2>&1; then
            log_success "JSON report generated: $RESULTS_DIR/validation_report.json"
        fi
    else
        log_error "Failed to generate validation report"
    fi
else
    log_warning "Validation report generator not found (SKIPPED)"
fi
log ""

# Test Summary
log "=========================================="
log "Test Summary"
log "=========================================="
log "Passed:  $TESTS_PASSED"
log "Failed:  $TESTS_FAILED"
log "Skipped: $TESTS_SKIPPED"
log "Total:   $((TESTS_PASSED + TESTS_FAILED + TESTS_SKIPPED))"
log ""

# Success rate
if [[ $((TESTS_PASSED + TESTS_FAILED)) -gt 0 ]]; then
    SUCCESS_RATE=$((100 * TESTS_PASSED / (TESTS_PASSED + TESTS_FAILED)))
    log "Success Rate: ${SUCCESS_RATE}%"
else
    log_warning "No tests were run"
fi
log ""

log "Completed: $(date)"
log "Log file: $LOG_FILE"
log "Results directory: $RESULTS_DIR"

# Exit with appropriate code
if [[ $TESTS_FAILED -gt 0 ]]; then
    log_error "Some tests failed!"
    exit 1
else
    log_success "All tests passed!"
    exit 0
fi
