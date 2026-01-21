#!/bin/bash
# Test runner for system-status skills
#
# Usage:
#   ./run_tests.sh              # Run all tests
#   ./run_tests.sh -v           # Verbose output
#   ./run_tests.sh --cov        # With coverage report
#   ./run_tests.sh -k test_name # Run specific test
#
# Created: 2025-11-20

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}================================${NC}"
echo -e "${BLUE}System Status Skills Test Suite${NC}"
echo -e "${BLUE}================================${NC}"
echo

# Check if pytest is installed
if ! command -v pytest &> /dev/null; then
    echo -e "${RED}Error: pytest is not installed${NC}"
    echo "Install with: pip install pytest pytest-cov"
    exit 1
fi

# Parse arguments
PYTEST_ARGS=()
RUN_COVERAGE=false

for arg in "$@"; do
    case $arg in
        --cov|--coverage)
            RUN_COVERAGE=true
            ;;
        *)
            PYTEST_ARGS+=("$arg")
            ;;
    esac
done

# Run tests
if [ "$RUN_COVERAGE" = true ]; then
    echo -e "${YELLOW}Running tests with coverage...${NC}"
    echo

    pytest \
        --cov=.. \
        --cov-report=html \
        --cov-report=term-missing \
        --cov-branch \
        "${PYTEST_ARGS[@]}"

    EXIT_CODE=$?

    if [ $EXIT_CODE -eq 0 ]; then
        echo
        echo -e "${GREEN}✓ All tests passed!${NC}"
        echo
        echo -e "${BLUE}Coverage report generated:${NC}"
        echo "  HTML: file://$SCRIPT_DIR/htmlcov/index.html"
    else
        echo
        echo -e "${RED}✗ Some tests failed${NC}"
    fi
else
    echo -e "${YELLOW}Running tests...${NC}"
    echo

    pytest "${PYTEST_ARGS[@]}"

    EXIT_CODE=$?

    if [ $EXIT_CODE -eq 0 ]; then
        echo
        echo -e "${GREEN}✓ All tests passed!${NC}"
    else
        echo
        echo -e "${RED}✗ Some tests failed${NC}"
    fi
fi

echo
echo -e "${BLUE}Test run complete${NC}"
echo

exit $EXIT_CODE
