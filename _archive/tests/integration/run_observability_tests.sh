#!/bin/bash
# Run Agent Observability Integration Tests
#
# Comprehensive test runner for agent observability system.
# Handles environment setup, service checks, and test execution.
#
# Usage:
#   ./run_observability_tests.sh                    # Run all tests
#   ./run_observability_tests.sh --verbose          # Verbose output
#   ./run_observability_tests.sh --class=TestName   # Run specific class
#   ./run_observability_tests.sh --help             # Show help

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# Default options
VERBOSE=false
TEST_CLASS=""
SKIP_CHECKS=false

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --verbose|-v)
            VERBOSE=true
            shift
            ;;
        --class=*)
            TEST_CLASS="${1#*=}"
            shift
            ;;
        --skip-checks)
            SKIP_CHECKS=true
            shift
            ;;
        --help|-h)
            cat << EOF
Agent Observability Integration Tests Runner

Usage:
  ./run_observability_tests.sh [OPTIONS]

Options:
  --verbose, -v           Enable verbose output
  --class=CLASS_NAME      Run specific test class only
  --skip-checks           Skip infrastructure checks
  --help, -h              Show this help message

Examples:
  # Run all tests
  ./run_observability_tests.sh

  # Run with verbose output
  ./run_observability_tests.sh --verbose

  # Run specific test class
  ./run_observability_tests.sh --class=TestAgentActionsLogging

  # Skip infrastructure checks (faster, but may fail)
  ./run_observability_tests.sh --skip-checks

Test Classes:
  - TestAgentActionsLogging           (5 tests - action logging)
  - TestTransformationEvents          (4 tests - transformation tracking)
  - TestManifestInjections            (2 tests - manifest tracking)
  - TestDatabaseSchemaValidation      (5 tests - schema validation)

Environment:
  Required environment variables (load with: source .env):
    POSTGRES_HOST, POSTGRES_PORT, POSTGRES_DATABASE
    POSTGRES_USER, POSTGRES_PASSWORD
    KAFKA_BOOTSTRAP_SERVERS

EOF
            exit 0
            ;;
        *)
            echo -e "${RED}Unknown option: $1${NC}"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Agent Observability Integration Tests${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Change to project root
cd "$PROJECT_ROOT"

# Load environment variables
if [ -f .env ]; then
    echo -e "${GREEN}✓${NC} Loading environment from .env"
    set -a
    source .env
    set +a
else
    echo -e "${RED}✗${NC} .env file not found"
    echo "  Create .env file: cp .env.example .env"
    exit 1
fi

# Verify required environment variables
if [ -z "$POSTGRES_PASSWORD" ]; then
    echo -e "${RED}✗${NC} POSTGRES_PASSWORD not set in .env"
    echo "  Edit .env and set POSTGRES_PASSWORD"
    exit 1
fi

if [ -z "$KAFKA_BOOTSTRAP_SERVERS" ]; then
    echo -e "${RED}✗${NC} KAFKA_BOOTSTRAP_SERVERS not set in .env"
    echo "  Edit .env and set KAFKA_BOOTSTRAP_SERVERS"
    exit 1
fi

echo -e "${GREEN}✓${NC} Environment variables loaded"

# Infrastructure checks (unless skipped)
if [ "$SKIP_CHECKS" = false ]; then
    echo ""
    echo -e "${BLUE}Checking Infrastructure...${NC}"

    # Check PostgreSQL
    if psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DATABASE" -c "SELECT 1" > /dev/null 2>&1; then
        echo -e "${GREEN}✓${NC} PostgreSQL: $POSTGRES_HOST:$POSTGRES_PORT"
    else
        echo -e "${RED}✗${NC} PostgreSQL connection failed"
        echo "  Check database is running: docker ps | grep postgres"
        exit 1
    fi

    # Check Kafka (basic connectivity test)
    # Note: This is a simple check - just verify the env var is set
    echo -e "${GREEN}✓${NC} Kafka: $KAFKA_BOOTSTRAP_SERVERS"

    # Check if consumer is running (optional warning)
    if ! pgrep -f "agent_actions_consumer" > /dev/null && ! docker ps | grep -q "consumer"; then
        echo -e "${YELLOW}⚠${NC}  Warning: Consumer may not be running"
        echo "  Some tests may timeout waiting for consumer processing"
        echo "  Start consumer: python consumers/agent_actions_consumer.py"
    else
        echo -e "${GREEN}✓${NC} Consumer is running"
    fi
fi

# Build pytest command
PYTEST_CMD="pytest tests/integration/test_agent_observability_integration.py"

if [ -n "$TEST_CLASS" ]; then
    PYTEST_CMD="$PYTEST_CMD::$TEST_CLASS"
fi

if [ "$VERBOSE" = true ]; then
    PYTEST_CMD="$PYTEST_CMD -v -s"
else
    PYTEST_CMD="$PYTEST_CMD -v"
fi

# Add integration marker
PYTEST_CMD="$PYTEST_CMD -m integration"

echo ""
echo -e "${BLUE}Running Tests...${NC}"
echo "Command: $PYTEST_CMD"
echo ""

# Run tests
if $PYTEST_CMD; then
    echo ""
    echo -e "${GREEN}========================================${NC}"
    echo -e "${GREEN}✓ All Tests Passed!${NC}"
    echo -e "${GREEN}========================================${NC}"
    exit 0
else
    EXIT_CODE=$?
    echo ""
    echo -e "${RED}========================================${NC}"
    echo -e "${RED}✗ Some Tests Failed${NC}"
    echo -e "${RED}========================================${NC}"
    echo ""
    echo "Troubleshooting:"
    echo "  1. Check database: psql -h \$POSTGRES_HOST -p \$POSTGRES_PORT -U postgres -c 'SELECT 1'"
    echo "  2. Check Kafka: docker exec omninode-bridge-redpanda rpk topic list"
    echo "  3. Check consumer logs: docker logs -f <consumer-container>"
    echo "  4. Review test output above for specific failures"
    echo ""
    echo "See tests/integration/README.md for detailed troubleshooting"
    exit $EXIT_CODE
fi
