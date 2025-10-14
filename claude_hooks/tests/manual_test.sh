#!/bin/bash
# Manual testing script for quality enforcer
#
# This script demonstrates the validation system by running various test cases
# and displaying the results in a human-readable format.

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOOKS_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

echo -e "${BLUE}╔══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║       AI-Enhanced Quality Enforcer - Manual Tests           ║${NC}"
echo -e "${BLUE}╔══════════════════════════════════════════════════════════════╗${NC}"
echo ""

# Function to run a test case
run_test() {
    local test_name=$1
    local file_path=$2
    local content=$3

    echo -e "${YELLOW}═══════════════════════════════════════════════════════════════${NC}"
    echo -e "${YELLOW}Test: ${test_name}${NC}"
    echo -e "${YELLOW}═══════════════════════════════════════════════════════════════${NC}"
    echo ""
    echo -e "${BLUE}Code being validated:${NC}"
    echo "$content" | sed 's/^/  /'
    echo ""

    # Run the validator
    echo -e "${BLUE}Running validation...${NC}"

    # Create temp file
    temp_file=$(mktemp)
    echo "$content" > "$temp_file"

    # Run Python validator directly
    python3 -c "
import sys
sys.path.insert(0, '$HOOKS_DIR')
from lib.validators.naming_validator import NamingValidator
import shutil

# Copy temp file to target path
shutil.copy('$temp_file', '$file_path')

validator = NamingValidator()
violations = validator.validate_file('$file_path')

if violations:
    print('${RED}✗ Violations found:${NC}')
    for v in violations:
        print(f'  Line {v.line}: {v.violation_type} \"{v.name}\" should be {v.expected_format}')
        print(f'    Suggestion: {v.message}')
else:
    print('${GREEN}✓ No violations found - code passes validation!${NC}')
" 2>&1

    # Clean up
    rm -f "$temp_file" "$file_path"

    echo ""
}

# Test 1: Python function naming violation
run_test "Python Function Naming (camelCase violation)" \
    "/tmp/test_func.py" \
    "def calculateTotal(items):
    \"\"\"Calculate total of items.\"\"\"
    return sum(items)"

# Test 2: Python class naming violation
run_test "Python Class Naming (snake_case violation)" \
    "/tmp/test_class.py" \
    "class user_profile:
    \"\"\"User profile class.\"\"\"
    pass"

# Test 3: TypeScript function naming violation
run_test "TypeScript Function Naming (snake_case violation)" \
    "/tmp/test_ts_func.ts" \
    "function calculate_total(items: number[]): number {
    return items.reduce((a, b) => a + b, 0);
}"

# Test 4: TypeScript class naming violation
run_test "TypeScript Class Naming (snake_case violation)" \
    "/tmp/test_ts_class.ts" \
    "class user_profile {
    constructor(public name: string) {}
}"

# Test 5: TypeScript interface naming violation
run_test "TypeScript Interface Naming (snake_case violation)" \
    "/tmp/test_ts_interface.ts" \
    "interface data_processor {
    process(): void;
}"

# Test 6: Clean Python code (no violations)
run_test "Python Clean Code (no violations)" \
    "/tmp/test_clean.py" \
    "def calculate_total(items):
    \"\"\"Calculate total of items.\"\"\"
    return sum(items)

class UserProfile:
    \"\"\"User profile class.\"\"\"
    pass"

# Test 7: Clean TypeScript code (no violations)
run_test "TypeScript Clean Code (no violations)" \
    "/tmp/test_clean.ts" \
    "function calculateTotal(items: number[]): number {
    return items.reduce((a, b) => a + b, 0);
}

class UserProfile {
    constructor(public name: string) {}
}"

# Test 8: Multiple violations in one file
run_test "Multiple Violations (Python)" \
    "/tmp/test_multiple.py" \
    "class user_profile:
    def calculateTotal(self, items):
        return sum(items)

def processData():
    pass"

echo -e "${BLUE}╔══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║                     Tests Complete!                          ║${NC}"
echo -e "${BLUE}╚══════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "${GREEN}Summary:${NC}"
echo "  - All test cases executed successfully"
echo "  - Check output above for validation results"
echo ""
echo -e "${BLUE}Next steps:${NC}"
echo "  1. Review violations found in test cases"
echo "  2. Run unit tests: pytest $SCRIPT_DIR/test_naming_validator.py -v"
echo "  3. Run integration tests: pytest $SCRIPT_DIR/test_integration.py -v"
echo ""
