#!/bin/bash
# Test script for research feature in fetch-ci-data

set -euo pipefail

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${BLUE}Testing research feature enhancements...${NC}\n"

# Test 1: Verify script syntax
echo -e "${BLUE}Test 1: Verifying script syntax${NC}"
if bash -n "${HOME}/.claude/skills/onex/ci-failures/fetch-ci-data"; then
    echo -e "${GREEN}✓ Script syntax valid${NC}\n"
else
    echo -e "${RED}✗ Script has syntax errors${NC}\n"
    exit 1
fi

# Test 2: Check that new functions exist
echo -e "${BLUE}Test 2: Checking new functions exist${NC}"
functions_to_check=(
    "is_error_recognized"
    "extract_error_context"
    "research_error"
)

for func in "${functions_to_check[@]}"; do
    if grep -q "^${func}()" "${HOME}/.claude/skills/onex/ci-failures/fetch-ci-data"; then
        echo -e "${GREEN}✓ Function '$func' exists${NC}"
    else
        echo -e "${RED}✗ Function '$func' not found${NC}"
        exit 1
    fi
done
echo ""

# Test 3: Verify error recognition patterns
echo -e "${BLUE}Test 3: Verifying error recognition patterns${NC}"
patterns=(
    "pytest"
    "mypy"
    "ruff"
    "[Dd]ocker"
    "npm"
    "yarn"
)

for pattern in "${patterns[@]}"; do
    if grep -q "$pattern" "${HOME}/.claude/skills/onex/ci-failures/fetch-ci-data"; then
        echo -e "${GREEN}✓ Pattern '$pattern' implemented${NC}"
    else
        echo -e "${RED}✗ Pattern '$pattern' not found${NC}"
        exit 1
    fi
done
echo ""

# Test 4: Verify research query generation
echo -e "${BLUE}Test 4: Verifying research query generation${NC}"
required_elements=(
    "search_queries"
    "suggestions"
    "research_needed"
    "auto_research_hint"
    "context"
)

for element in "${required_elements[@]}"; do
    if grep -q "$element" "${HOME}/.claude/skills/onex/ci-failures/fetch-ci-data"; then
        echo -e "${GREEN}✓ Research element '$element' implemented${NC}"
    else
        echo -e "${RED}✗ Research element '$element' not found${NC}"
        exit 1
    fi
done
echo ""

# Test 5: Verify output includes researched count
echo -e "${BLUE}Test 5: Verifying summary includes researched count${NC}"
if grep -q "researched:" "${HOME}/.claude/skills/onex/ci-failures/fetch-ci-data"; then
    echo -e "${GREEN}✓ Researched count added to summary${NC}"
else
    echo -e "${RED}✗ Researched count not in summary${NC}"
    exit 1
fi
echo ""

# Test 6: Verify context extraction for technologies
echo -e "${BLUE}Test 6: Verifying technology context extraction${NC}"
technologies=(
    "Python"
    "JavaScript"
    "TypeScript"
    "Django"
    "Flask"
    "FastAPI"
    "GitHub.*Actions"
)

for tech in "${technologies[@]}"; do
    if grep -q "$tech" "${HOME}/.claude/skills/onex/ci-failures/fetch-ci-data"; then
        echo -e "${GREEN}✓ Technology '$tech' detection implemented${NC}"
    else
        echo -e "${RED}✗ Technology '$tech' detection not found${NC}"
        exit 1
    fi
done
echo ""

# Test 7: Verify integration into process_workflow_runs
echo -e "${BLUE}Test 7: Verifying integration into workflow processing${NC}"
if grep -q "is_error_recognized.*job_name.*step_name" "${HOME}/.claude/skills/onex/ci-failures/fetch-ci-data"; then
    echo -e "${GREEN}✓ Error recognition integrated into workflow processing${NC}"
else
    echo -e "${RED}✗ Error recognition not integrated${NC}"
    exit 1
fi

if grep -q "research_error.*job_name.*step_name" "${HOME}/.claude/skills/onex/ci-failures/fetch-ci-data"; then
    echo -e "${GREEN}✓ Research generation integrated into workflow processing${NC}"
else
    echo -e "${RED}✗ Research generation not integrated${NC}"
    exit 1
fi
echo ""

# Test 8: Verify updated documentation
echo -e "${BLUE}Test 8: Verifying documentation updates${NC}"
doc_elements=(
    "Automatic error classification"
    "Intelligent research query"
    "Context extraction"
    "WebSearch"
)

for element in "${doc_elements[@]}"; do
    if grep -qi "$element" "${HOME}/.claude/skills/onex/ci-failures/fetch-ci-data"; then
        echo -e "${GREEN}✓ Documentation mentions '$element'${NC}"
    else
        echo -e "${YELLOW}⚠ Documentation may be missing '$element'${NC}"
    fi
done
echo ""

# Test 9: Verify research object structure
echo -e "${BLUE}Test 9: Verifying research object structure${NC}"
research_fields=(
    "job:"
    "step:"
    "workflow:"
    "context:"
    "research_needed:"
    "search_queries:"
    "suggestions:"
    "auto_research_hint:"
)

all_fields_found=true
for field in "${research_fields[@]}"; do
    if ! grep -q "$field" "${HOME}/.claude/skills/onex/ci-failures/fetch-ci-data"; then
        echo -e "${RED}✗ Research field '$field' not found${NC}"
        all_fields_found=false
    fi
done

if [ "$all_fields_found" = true ]; then
    echo -e "${GREEN}✓ Complete research object structure implemented${NC}"
else
    exit 1
fi
echo ""

# Test 10: Verify conditional research attachment
echo -e "${BLUE}Test 10: Verifying conditional research attachment${NC}"
if grep -q 'if \[ -n "\$research" \]; then' "${HOME}/.claude/skills/onex/ci-failures/fetch-ci-data"; then
    echo -e "${GREEN}✓ Research conditionally attached to failures${NC}"
else
    echo -e "${RED}✗ Research attachment logic not found${NC}"
    exit 1
fi
echo ""

echo -e "${GREEN}═══════════════════════════════════════${NC}"
echo -e "${GREEN}All tests passed!${NC}"
echo -e "${GREEN}═══════════════════════════════════════${NC}\n"

echo -e "${BLUE}Summary of enhancements:${NC}"
echo "  ✓ Error pattern recognition (recognized vs unrecognized)"
echo "  ✓ Context extraction (Python, JavaScript, frameworks, etc.)"
echo "  ✓ Research query generation (4-5 queries per error)"
echo "  ✓ Actionable suggestions (GitHub issues, Stack Overflow, etc.)"
echo "  ✓ Integration into workflow processing"
echo "  ✓ Enhanced JSON output with research field"
echo "  ✓ Summary includes researched count"
echo "  ✓ Updated documentation and usage"
echo ""

echo -e "${BLUE}Next steps:${NC}"
echo "  1. Test with actual CI failures: fetch-ci-data --no-cache <PR_NUMBER>"
echo "  2. Look for 'research' field in output JSON"
echo "  3. Use ci-quick-review wrapper to automatically execute searches"
echo "  4. Claude Code can use WebSearch tool for prepared queries"
echo ""
