#!/bin/bash
# Verify Configuration and Monitoring System Installation
# Tests all components and provides installation summary

set -euo pipefail

# Color codes
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

HOOKS_DIR="${HOME}/.claude/hooks"
ERRORS=0
WARNINGS=0

echo "========================================"
echo "Installation Verification"
echo "========================================"
echo ""

# Check directories
echo -e "${BLUE}Checking directory structure...${NC}"
for dir in bin lib/logging lib/cache logs .cache; do
    if [[ -d "$HOOKS_DIR/$dir" ]]; then
        echo -e "  ${GREEN}✓${NC} $dir"
    else
        echo -e "  ${RED}✗${NC} $dir (missing)"
        ((ERRORS++))
    fi
done
echo ""

# Check files
echo -e "${BLUE}Checking configuration files...${NC}"
for file in config.yaml bin/analyze_decisions.sh lib/logging/decision_logger.py lib/cache/manager.py; do
    if [[ -f "$HOOKS_DIR/$file" ]]; then
        echo -e "  ${GREEN}✓${NC} $file"
    else
        echo -e "  ${RED}✗${NC} $file (missing)"
        ((ERRORS++))
    fi
done
echo ""

# Check executable permissions
echo -e "${BLUE}Checking executable permissions...${NC}"
if [[ -x "$HOOKS_DIR/bin/analyze_decisions.sh" ]]; then
    echo -e "  ${GREEN}✓${NC} analyze_decisions.sh is executable"
else
    echo -e "  ${RED}✗${NC} analyze_decisions.sh is not executable"
    ((ERRORS++))
fi
echo ""

# Validate YAML configuration
echo -e "${BLUE}Validating configuration...${NC}"
if python3 -c "
import yaml
import sys

try:
    with open('$HOOKS_DIR/config.yaml', 'r') as f:
        config = yaml.safe_load(f)

    # Check required sections
    required_sections = ['enforcement', 'rag', 'quorum', 'logging', 'cache']
    for section in required_sections:
        if section not in config:
            print(f'Missing section: {section}')
            sys.exit(1)

    # Verify Phase 1 settings
    if config['rag']['enabled']:
        print('WARNING: RAG should be disabled for Phase 1')
        sys.exit(2)

    if config['quorum']['enabled']:
        print('WARNING: Quorum should be disabled for Phase 1')
        sys.exit(2)

    print('Configuration is valid')
    sys.exit(0)

except Exception as e:
    print(f'Configuration error: {e}')
    sys.exit(1)
" 2>&1; then
    result=$?
    if [[ $result -eq 0 ]]; then
        echo -e "  ${GREEN}✓${NC} config.yaml is valid"
    elif [[ $result -eq 2 ]]; then
        echo -e "  ${YELLOW}⚠${NC} config.yaml has warnings (see above)"
        ((WARNINGS++))
    else
        echo -e "  ${RED}✗${NC} config.yaml has errors (see above)"
        ((ERRORS++))
    fi
else
    echo -e "  ${RED}✗${NC} Failed to validate config.yaml"
    ((ERRORS++))
fi
echo ""

# Test Python components
echo -e "${BLUE}Testing Python components...${NC}"
if cd "$HOOKS_DIR" && python3 -c "
from lib.logging.decision_logger import DecisionLogger
from lib.cache.manager import CacheManager
from pathlib import Path

# Test DecisionLogger
try:
    logger = DecisionLogger(Path('$HOOKS_DIR/logs'))
    print('✓ DecisionLogger: OK')
except Exception as e:
    print(f'✗ DecisionLogger: {e}')
    exit(1)

# Test CacheManager
try:
    cache = CacheManager(Path('$HOOKS_DIR/.cache'))
    cache.set('test', 'value')
    value = cache.get('test')
    if value != 'value':
        raise ValueError('Cache get/set failed')
    cache.delete('test')
    print('✓ CacheManager: OK')
except Exception as e:
    print(f'✗ CacheManager: {e}')
    exit(1)
" 2>&1; then
    while IFS= read -r line; do
        if [[ $line == ✓* ]]; then
            echo -e "  ${GREEN}$line${NC}"
        elif [[ $line == ✗* ]]; then
            echo -e "  ${RED}$line${NC}"
            ((ERRORS++))
        else
            echo "  $line"
        fi
    done
else
    echo -e "  ${RED}✗${NC} Python component tests failed"
    ((ERRORS++))
fi
echo ""

# Test analytics script
echo -e "${BLUE}Testing analytics script...${NC}"
if [[ -f "$HOOKS_DIR/logs/decisions.jsonl" ]] && [[ -s "$HOOKS_DIR/logs/decisions.jsonl" ]]; then
    echo -e "  ${GREEN}✓${NC} decisions.jsonl exists with data"

    # Test if script runs (simplified test - just check exit code without pipes)
    TEMP_OUT=$(mktemp)
    if timeout 3 "$HOOKS_DIR/bin/analyze_decisions.sh" > "$TEMP_OUT" 2>&1; then
        if grep -q "Analytics Dashboard" "$TEMP_OUT"; then
            echo -e "  ${GREEN}✓${NC} analyze_decisions.sh runs successfully"
        else
            echo -e "  ${RED}✗${NC} analyze_decisions.sh output unexpected"
            ((ERRORS++))
        fi
    else
        echo -e "  ${RED}✗${NC} analyze_decisions.sh failed or timed out"
        ((ERRORS++))
    fi
    rm -f "$TEMP_OUT"
else
    echo -e "  ${YELLOW}⚠${NC} No decision log data yet (expected for new installation)"
    echo -e "  ${GREEN}✓${NC} Script is ready to use when decisions are logged"
fi
echo ""

# Check dependencies
echo -e "${BLUE}Checking dependencies...${NC}"

# Check Python
if command -v python3 &> /dev/null; then
    PYTHON_VERSION=$(python3 --version | cut -d' ' -f2)
    echo -e "  ${GREEN}✓${NC} python3 ($PYTHON_VERSION)"
else
    echo -e "  ${RED}✗${NC} python3 not found"
    ((ERRORS++))
fi

# Check PyYAML
if python3 -c "import yaml" 2>/dev/null; then
    echo -e "  ${GREEN}✓${NC} PyYAML installed"
else
    echo -e "  ${YELLOW}⚠${NC} PyYAML not installed (pip install pyyaml)"
    ((WARNINGS++))
fi

# Check jq
if command -v jq &> /dev/null; then
    echo -e "  ${GREEN}✓${NC} jq installed"
else
    echo -e "  ${RED}✗${NC} jq not found (required for analytics)"
    ((ERRORS++))
fi
echo ""

# Summary
echo "========================================"
echo "Installation Summary"
echo "========================================"

if [[ $ERRORS -eq 0 ]] && [[ $WARNINGS -eq 0 ]]; then
    echo -e "${GREEN}✓ Installation is complete and fully functional${NC}"
    echo ""
    echo "Next steps:"
    echo "  1. Review config.yaml and adjust settings as needed"
    echo "  2. Integrate with quality_enforcer.py"
    echo "  3. Monitor logs/decisions.jsonl for enforcement decisions"
    echo "  4. Run bin/analyze_decisions.sh for analytics"
elif [[ $ERRORS -eq 0 ]]; then
    echo -e "${YELLOW}⚠ Installation complete with $WARNINGS warning(s)${NC}"
    echo ""
    echo "Installation is functional but some optional components have warnings."
    echo "Review the warnings above and address as needed."
else
    echo -e "${RED}✗ Installation incomplete with $ERRORS error(s) and $WARNINGS warning(s)${NC}"
    echo ""
    echo "Please address the errors above before using the system."
    exit 1
fi

echo ""
echo "Documentation:"
echo "  - Configuration: ~/.claude/hooks/CONFIG_AND_MONITORING.md"
echo "  - Design doc: docs/agent-framework/ai-quality-enforcement-system.md"
echo ""
echo "Quick reference:"
echo "  - Config file: ~/.claude/hooks/config.yaml"
echo "  - Decision log: ~/.claude/hooks/logs/decisions.jsonl"
echo "  - Analytics: ~/.claude/hooks/bin/analyze_decisions.sh"
echo "  - Cache dir: ~/.claude/hooks/.cache"
