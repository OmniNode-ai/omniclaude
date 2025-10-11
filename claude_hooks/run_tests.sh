#!/bin/bash
# Polymorphic Agent Framework - Test Runner
# Comprehensive test execution with multiple modes

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TESTS_DIR="${SCRIPT_DIR}/tests"
COVERAGE_DIR="${SCRIPT_DIR}/htmlcov"

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

print_header() {
    echo ""
    echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}"
    echo -e "${BLUE}  $1${NC}"
    echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}"
    echo ""
}

print_success() {
    echo -e "${GREEN}✓ $1${NC}"
}

print_error() {
    echo -e "${RED}✗ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠ $1${NC}"
}

print_info() {
    echo -e "${BLUE}ℹ $1${NC}"
}

# ============================================================================
# TEST MODES
# ============================================================================

run_unit_tests() {
    print_header "Running Unit Tests (Fast, Isolated)"
    print_info "Target: <100ms per test, 100% code coverage"

    cd "$SCRIPT_DIR"
    pytest -m unit \
        --tb=short \
        --durations=10 \
        tests/

    print_success "Unit tests completed"
}

run_integration_tests() {
    print_header "Running Integration Tests (Moderate Speed)"
    print_info "Target: <500ms per test, 95% integration coverage"

    cd "$SCRIPT_DIR"
    pytest -m integration \
        --tb=short \
        --durations=10 \
        tests/

    print_success "Integration tests completed"
}

run_e2e_tests() {
    print_header "Running End-to-End Tests (Full System)"
    print_info "Target: <5s per test, 85% workflow coverage"

    cd "$SCRIPT_DIR"
    pytest -m e2e \
        --tb=short \
        --durations=10 \
        tests/

    print_success "End-to-end tests completed"
}

run_performance_tests() {
    print_header "Running Performance Tests"
    print_info "Benchmarking hook performance and scalability"

    cd "$SCRIPT_DIR"
    pytest -m performance \
        --tb=short \
        --durations=0 \
        tests/

    print_success "Performance tests completed"
}

run_all_tests() {
    print_header "Running All Tests (Full Suite)"
    print_info "This may take 5-10 minutes..."

    cd "$SCRIPT_DIR"
    pytest \
        --tb=short \
        --durations=20 \
        tests/

    print_success "All tests completed"
}

run_fast_tests() {
    print_header "Running Fast Tests (Unit + Integration)"
    print_info "Quick validation, skipping slow tests"

    cd "$SCRIPT_DIR"
    pytest -m "not slow and not e2e and not performance" \
        --tb=line \
        tests/

    print_success "Fast tests completed"
}

run_with_coverage() {
    print_header "Running Tests with Coverage Analysis"
    print_info "Generating coverage report..."

    cd "$SCRIPT_DIR"
    pytest \
        --cov=lib \
        --cov-report=html \
        --cov-report=term \
        --tb=short \
        tests/

    if [ -d "$COVERAGE_DIR" ]; then
        print_success "Coverage report generated: ${COVERAGE_DIR}/index.html"
        print_info "Open with: open ${COVERAGE_DIR}/index.html"
    fi
}

run_parallel() {
    print_header "Running Tests in Parallel"
    print_info "Using pytest-xdist for parallel execution"

    if ! python3 -c "import xdist" 2>/dev/null; then
        print_warning "pytest-xdist not installed, installing..."
        pip3 install pytest-xdist
    fi

    cd "$SCRIPT_DIR"
    pytest -n auto \
        --tb=short \
        tests/

    print_success "Parallel tests completed"
}

run_specific_test() {
    local test_file="$1"

    print_header "Running Specific Test: $test_file"

    cd "$SCRIPT_DIR"
    pytest "$test_file" -v --tb=short

    print_success "Test completed"
}

run_watch_mode() {
    print_header "Running Tests in Watch Mode"
    print_info "Tests will re-run on file changes (Ctrl+C to stop)"

    if ! python3 -c "import pytest_watch" 2>/dev/null; then
        print_warning "pytest-watch not installed, installing..."
        pip3 install pytest-watch
    fi

    cd "$SCRIPT_DIR"
    pytest-watch tests/
}

# ============================================================================
# VALIDATION & SETUP
# ============================================================================

check_dependencies() {
    print_header "Checking Dependencies"

    # Check Python
    if ! command -v python3 &> /dev/null; then
        print_error "python3 not found"
        exit 1
    fi
    print_success "Python 3 found: $(python3 --version)"

    # Check pytest
    if ! python3 -c "import pytest" 2>/dev/null; then
        print_error "pytest not installed"
        print_info "Install with: pip3 install pytest pytest-cov pytest-xdist"
        exit 1
    fi
    print_success "pytest found: $(python3 -c 'import pytest; print(pytest.__version__)')"

    # Check test files exist
    if [ ! -d "$TESTS_DIR" ]; then
        print_error "Tests directory not found: $TESTS_DIR"
        exit 1
    fi
    print_success "Tests directory found"

    # Count test files
    local test_count=$(find "$TESTS_DIR" -name "test_*.py" | wc -l | tr -d ' ')
    print_info "Found $test_count test files"
}

install_dependencies() {
    print_header "Installing Test Dependencies"

    pip3 install -r "${SCRIPT_DIR}/requirements.txt" || true

    print_info "Installing additional test tools..."
    pip3 install \
        pytest \
        pytest-cov \
        pytest-xdist \
        pytest-timeout \
        pytest-benchmark \
        pytest-watch \
        pyyaml

    print_success "Dependencies installed"
}

# ============================================================================
# REPORTING
# ============================================================================

show_test_statistics() {
    print_header "Test Statistics"

    cd "$SCRIPT_DIR"

    echo "Test Files:"
    find tests/ -name "test_*.py" -exec echo "  - {}" \;

    echo ""
    echo "Test Markers:"
    pytest --markers | grep "^@pytest.mark" | head -10

    echo ""
    echo "Test Count by Type:"
    echo "  Unit:        $(grep -r "@pytest.mark.unit" tests/ | wc -l | tr -d ' ')"
    echo "  Integration: $(grep -r "@pytest.mark.integration" tests/ | wc -l | tr -d ' ')"
    echo "  E2E:         $(grep -r "@pytest.mark.e2e" tests/ | wc -l | tr -d ' ')"
    echo "  Performance: $(grep -r "@pytest.mark.performance" tests/ | wc -l | tr -d ' ')"
}

generate_test_report() {
    print_header "Generating Test Report"

    cd "$SCRIPT_DIR"

    # Run tests with JSON report
    pytest \
        --json-report \
        --json-report-file=test-report.json \
        tests/ 2>/dev/null || true

    if [ -f "test-report.json" ]; then
        print_success "Test report generated: test-report.json"
    fi
}

# ============================================================================
# CI/CD INTEGRATION
# ============================================================================

run_ci_tests() {
    print_header "Running CI/CD Test Suite"
    print_info "Optimized for continuous integration"

    cd "$SCRIPT_DIR"

    # Run with coverage and JUnit XML for CI systems
    pytest \
        --cov=lib \
        --cov-report=xml \
        --cov-report=term \
        --junit-xml=junit.xml \
        --tb=short \
        -m "not slow" \
        tests/

    print_success "CI tests completed"

    if [ -f "coverage.xml" ]; then
        print_info "Coverage XML: coverage.xml"
    fi

    if [ -f "junit.xml" ]; then
        print_info "JUnit XML: junit.xml"
    fi
}

# ============================================================================
# MAIN MENU
# ============================================================================

show_usage() {
    cat << EOF
Polymorphic Agent Framework - Test Runner

Usage: $0 [command]

Commands:
  unit              Run unit tests only (fast, <100ms per test)
  integration       Run integration tests (moderate, <500ms per test)
  e2e               Run end-to-end tests (slow, <5s per test)
  performance       Run performance benchmarks
  all               Run all tests (full suite)
  fast              Run fast tests (unit + integration)
  coverage          Run tests with coverage analysis
  parallel          Run tests in parallel (faster)
  watch             Run tests in watch mode (auto-rerun on changes)
  specific <file>   Run specific test file
  ci                Run CI/CD optimized test suite
  check             Check dependencies and setup
  install           Install test dependencies
  stats             Show test statistics
  report            Generate test report
  help              Show this help message

Examples:
  $0 unit                          # Run unit tests only
  $0 coverage                      # Run with coverage report
  $0 specific tests/test_agent_detection.py  # Run specific file
  $0 parallel                      # Run tests in parallel

Performance Targets:
  - Unit tests: <100ms per test
  - Integration tests: <500ms per test
  - End-to-end tests: <5s per test
  - Full suite: <5 minutes

Coverage Targets:
  - Unit test coverage: ≥95%
  - Integration coverage: ≥90%
  - Overall coverage: ≥90%

EOF
}

# ============================================================================
# COMMAND DISPATCHER
# ============================================================================

main() {
    local command="${1:-help}"

    case "$command" in
        unit)
            check_dependencies
            run_unit_tests
            ;;
        integration)
            check_dependencies
            run_integration_tests
            ;;
        e2e)
            check_dependencies
            run_e2e_tests
            ;;
        performance)
            check_dependencies
            run_performance_tests
            ;;
        all)
            check_dependencies
            run_all_tests
            ;;
        fast)
            check_dependencies
            run_fast_tests
            ;;
        coverage)
            check_dependencies
            run_with_coverage
            ;;
        parallel)
            check_dependencies
            run_parallel
            ;;
        watch)
            check_dependencies
            run_watch_mode
            ;;
        specific)
            if [ -z "${2:-}" ]; then
                print_error "Please specify test file"
                exit 1
            fi
            check_dependencies
            run_specific_test "$2"
            ;;
        ci)
            check_dependencies
            run_ci_tests
            ;;
        check)
            check_dependencies
            ;;
        install)
            install_dependencies
            ;;
        stats)
            show_test_statistics
            ;;
        report)
            generate_test_report
            ;;
        help|--help|-h)
            show_usage
            ;;
        *)
            print_error "Unknown command: $command"
            echo ""
            show_usage
            exit 1
            ;;
    esac
}

# Run main
main "$@"
