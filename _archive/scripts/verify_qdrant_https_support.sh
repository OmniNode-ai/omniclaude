#!/bin/bash
#
# Qdrant HTTPS Support Verification Script
#
# Verifies that Qdrant helper correctly supports both HTTP and HTTPS protocols
# based on QDRANT_URL configuration and ENVIRONMENT settings.
#
# Usage: ./scripts/verify_qdrant_https_support.sh
#
# Tests:
# 1. Explicit HTTPS URL → Uses HTTPS
# 2. Explicit HTTP URL → Uses HTTP (development only)
# 3. Auto-HTTPS (production) → Constructs HTTPS URL
# 4. Auto-HTTP (development) → Constructs HTTP URL
#
# Created: 2025-11-20
#

set -euo pipefail

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "======================================================================="
echo "Qdrant HTTPS Support Verification"
echo "======================================================================="
echo ""

# Test counter
TOTAL_TESTS=0
PASSED_TESTS=0
FAILED_TESTS=0

# Test function
run_test() {
    local test_name="$1"
    local expected_protocol="$2"
    local env_vars="$3"

    TOTAL_TESTS=$((TOTAL_TESTS + 1))
    echo "Test $TOTAL_TESTS: $test_name"
    echo "  Environment: $env_vars"

    # Run Python test
    local result
    result=$(bash -c "$env_vars python3 -c \"
import sys
sys.path.insert(0, '$PROJECT_ROOT/skills/_shared')
sys.path.insert(0, '$PROJECT_ROOT')

from qdrant_helper import get_qdrant_url

url = get_qdrant_url()
print(url)
\" 2>&1" || echo "ERROR")

    if [[ "$result" == "ERROR" ]] || [[ -z "$result" ]]; then
        echo -e "  ${RED}❌ FAILED${NC}: Test execution error"
        echo "  Error: $result"
        FAILED_TESTS=$((FAILED_TESTS + 1))
        return 1
    fi

    # Check protocol
    if [[ "$result" =~ ^${expected_protocol}:// ]]; then
        echo -e "  ${GREEN}✅ PASSED${NC}: URL uses $expected_protocol protocol"
        echo "  Result: $result"
        PASSED_TESTS=$((PASSED_TESTS + 1))
        return 0
    else
        echo -e "  ${RED}❌ FAILED${NC}: Expected $expected_protocol, got: $result"
        FAILED_TESTS=$((FAILED_TESTS + 1))
        return 1
    fi
}

# Test 1: Explicit HTTPS URL
echo ""
run_test \
    "Explicit HTTPS URL (production)" \
    "https" \
    "ENVIRONMENT=production QDRANT_URL=https://192.168.86.101:6333 QDRANT_HOST=192.168.86.101 QDRANT_PORT=6333"

# Test 2: Explicit HTTP URL (development)
echo ""
run_test \
    "Explicit HTTP URL (development)" \
    "http" \
    "ENVIRONMENT=development QDRANT_URL=http://localhost:6333 QDRANT_HOST=localhost QDRANT_PORT=6333"

# Test 3: Auto-HTTPS (production, no explicit URL)
echo ""
run_test \
    "Auto-HTTPS (production, no URL)" \
    "https" \
    "ENVIRONMENT=production QDRANT_HOST=192.168.86.101 QDRANT_PORT=6333"

# Test 4: Auto-HTTP (development, no explicit URL)
echo ""
run_test \
    "Auto-HTTP (development, no URL)" \
    "http" \
    "ENVIRONMENT=development QDRANT_HOST=localhost QDRANT_PORT=6333"

# Summary
echo ""
echo "======================================================================="
echo "Test Summary"
echo "======================================================================="
echo "Total Tests:  $TOTAL_TESTS"
echo -e "Passed:       ${GREEN}$PASSED_TESTS${NC}"
echo -e "Failed:       ${RED}$FAILED_TESTS${NC}"
echo ""

if [[ $FAILED_TESTS -eq 0 ]]; then
    echo -e "${GREEN}✅ All HTTPS support tests passed!${NC}"
    echo ""
    echo "Production deployment is ready:"
    echo "  • Set ENVIRONMENT=production in .env"
    echo "  • Set QDRANT_URL=https://your-qdrant-host:6333 in .env"
    echo "  • Verify TLS certificate is valid"
    echo ""
    exit 0
else
    echo -e "${RED}❌ Some tests failed!${NC}"
    echo ""
    echo "Please review the failed tests above and fix any issues."
    exit 1
fi
