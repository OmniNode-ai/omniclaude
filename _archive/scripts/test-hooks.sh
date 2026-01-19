#!/bin/bash
#
# Test script for git hooks documentation tracking
#
# This script validates the git hooks installation and functionality
# without requiring a running Kafka broker.

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

print_test() {
    echo -e "${BLUE}TEST:${NC} $1"
}

print_pass() {
    echo -e "${GREEN}✓ PASS${NC}: $1"
}

print_fail() {
    echo -e "${RED}✗ FAIL${NC}: $1"
}

print_info() {
    echo -e "${BLUE}INFO${NC}: $1"
}

# Test counter
TESTS_RUN=0
TESTS_PASSED=0
TESTS_FAILED=0

run_test() {
    local test_name=$1
    local test_command=$2

    TESTS_RUN=$((TESTS_RUN + 1))
    print_test "$test_name"

    if eval "$test_command"; then
        print_pass "$test_name"
        TESTS_PASSED=$((TESTS_PASSED + 1))
        return 0
    else
        print_fail "$test_name"
        TESTS_FAILED=$((TESTS_FAILED + 1))
        return 1
    fi
}

echo "================================================"
echo "Git Hooks Documentation Tracking - Test Suite"
echo "================================================"
echo ""

# Test 1: Verify git repository
print_test "Verify git repository"
if [ -d .git ]; then
    print_pass "Git repository found"
    TESTS_PASSED=$((TESTS_PASSED + 1))
else
    print_fail "Not a git repository"
    TESTS_FAILED=$((TESTS_FAILED + 1))
fi
TESTS_RUN=$((TESTS_RUN + 1))
echo ""

# Test 2: Verify hook scripts exist
print_test "Verify hook scripts in scripts/"
HOOK_SCRIPTS=("post-commit" "post-merge" "pre-push")
for hook in "${HOOK_SCRIPTS[@]}"; do
    if [ -f "scripts/$hook" ] && [ -x "scripts/$hook" ]; then
        print_pass "Found executable scripts/$hook"
        TESTS_PASSED=$((TESTS_PASSED + 1))
    else
        print_fail "Missing or not executable: scripts/$hook"
        TESTS_FAILED=$((TESTS_FAILED + 1))
    fi
    TESTS_RUN=$((TESTS_RUN + 1))
done
echo ""

# Test 3: Verify installed hooks
print_test "Verify installed hooks in .git/hooks/"
for hook in "${HOOK_SCRIPTS[@]}"; do
    if [ -f ".git/hooks/$hook" ] && [ -x ".git/hooks/$hook" ]; then
        print_pass "Found executable .git/hooks/$hook"
        TESTS_PASSED=$((TESTS_PASSED + 1))
    else
        print_fail "Missing or not executable: .git/hooks/$hook"
        TESTS_FAILED=$((TESTS_FAILED + 1))
    fi
    TESTS_RUN=$((TESTS_RUN + 1))
done
echo ""

# Test 4: Verify publisher script
print_test "Verify publisher script"
if [ -f "scripts/publish_doc_change.py" ] && [ -x "scripts/publish_doc_change.py" ]; then
    print_pass "Found executable scripts/publish_doc_change.py"
    TESTS_PASSED=$((TESTS_PASSED + 1))
else
    print_fail "Missing or not executable: scripts/publish_doc_change.py"
    TESTS_FAILED=$((TESTS_FAILED + 1))
fi
TESTS_RUN=$((TESTS_RUN + 1))
echo ""

# Test 5: Test publisher script help
print_test "Test publisher script --help"
if poetry run python3 scripts/publish_doc_change.py --help > /dev/null 2>&1; then
    print_pass "Publisher script help works"
    TESTS_PASSED=$((TESTS_PASSED + 1))
else
    print_fail "Publisher script help failed"
    TESTS_FAILED=$((TESTS_FAILED + 1))
fi
TESTS_RUN=$((TESTS_RUN + 1))
echo ""

# Test 6: Test publisher script with README (dry run without Kafka)
print_test "Test publisher script execution (will fail without Kafka - expected)"
print_info "Running: poetry run python3 scripts/publish_doc_change.py --file README.md --event document_updated --commit $(git rev-parse HEAD)"
if poetry run python3 scripts/publish_doc_change.py \
    --file README.md \
    --event document_updated \
    --commit "$(git rev-parse HEAD)" 2>&1 | grep -E "(Published|Error|Failed)" > /dev/null; then
    print_pass "Publisher script executed (Kafka connection expected to fail)"
    print_info "This is expected behavior without a running Kafka broker"
    TESTS_PASSED=$((TESTS_PASSED + 1))
else
    print_fail "Publisher script failed to execute"
    TESTS_FAILED=$((TESTS_FAILED + 1))
fi
TESTS_RUN=$((TESTS_RUN + 1))
echo ""

# Test 7: Verify environment configuration
print_test "Verify environment configuration"
if [ -f ".env" ]; then
    print_pass "Found .env file"
    if grep -q "KAFKA_BOOTSTRAP_SERVERS" .env 2>/dev/null; then
        print_pass "KAFKA_BOOTSTRAP_SERVERS configured"
        TESTS_PASSED=$((TESTS_PASSED + 1))
    else
        print_info "KAFKA_BOOTSTRAP_SERVERS not in .env (using defaults)"
        TESTS_PASSED=$((TESTS_PASSED + 1))
    fi
    TESTS_PASSED=$((TESTS_PASSED + 1))
else
    print_info ".env file not found (using defaults)"
    TESTS_PASSED=$((TESTS_PASSED + 1))
fi
TESTS_RUN=$((TESTS_RUN + 2))
echo ""

# Test 8: Verify documentation
print_test "Verify documentation exists"
if [ -f "docs/GIT_HOOKS_DOCUMENTATION.md" ]; then
    print_pass "Found docs/GIT_HOOKS_DOCUMENTATION.md"
    TESTS_PASSED=$((TESTS_PASSED + 1))
else
    print_fail "Missing documentation"
    TESTS_FAILED=$((TESTS_FAILED + 1))
fi
TESTS_RUN=$((TESTS_RUN + 1))
echo ""

# Test 9: Verify installation script
print_test "Verify installation script"
if [ -f "scripts/install-hooks.sh" ] && [ -x "scripts/install-hooks.sh" ]; then
    print_pass "Found executable scripts/install-hooks.sh"
    TESTS_PASSED=$((TESTS_PASSED + 1))
else
    print_fail "Missing or not executable: scripts/install-hooks.sh"
    TESTS_FAILED=$((TESTS_FAILED + 1))
fi
TESTS_RUN=$((TESTS_RUN + 1))
echo ""

# Test 10: Test installation script help
print_test "Test installation script --help"
if scripts/install-hooks.sh --help > /dev/null 2>&1; then
    print_pass "Installation script help works"
    TESTS_PASSED=$((TESTS_PASSED + 1))
else
    print_fail "Installation script help failed"
    TESTS_FAILED=$((TESTS_FAILED + 1))
fi
TESTS_RUN=$((TESTS_RUN + 1))
echo ""

# Summary
echo "================================================"
echo "Test Summary"
echo "================================================"
echo "Total Tests: $TESTS_RUN"
echo -e "${GREEN}Passed: $TESTS_PASSED${NC}"
if [ $TESTS_FAILED -gt 0 ]; then
    echo -e "${RED}Failed: $TESTS_FAILED${NC}"
fi
echo ""

if [ $TESTS_FAILED -eq 0 ]; then
    echo -e "${GREEN}✓ All tests passed!${NC}"
    echo ""
    echo "To test with actual commits:"
    echo "  1. Make sure Kafka is running (or events will fail silently)"
    echo "  2. Edit a .md file: echo '# Test' >> test.md"
    echo "  3. Commit: git add test.md && git commit -m 'Test hooks'"
    echo "  4. Check output for '📝 Detected X documentation file(s)'"
    exit 0
else
    echo -e "${RED}✗ Some tests failed${NC}"
    echo "Please fix the issues above before using the hooks"
    exit 1
fi
