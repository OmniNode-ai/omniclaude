#!/usr/bin/env bash
# scripts/validate-clean-root.sh
# Validates root directory cleanliness for omniclaude
# Based on omnibase_core pattern
#
# This script can be:
#   1. Run directly for validation
#   2. Copied to .git/hooks/pre-push for automatic enforcement
#
# Exit codes:
#   0 - Root directory is clean
#   1 - Violations found
#
# PORTABILITY:
#   This script auto-detects the project root from its location.
#   It works with any ONEX repository - no configuration needed.
#
#   The script assumes it's located in the `scripts/` directory:
#     project_root/
#       scripts/
#         validate-clean-root.sh  <-- this script
#       src/
#       ...
#
# USAGE:
#   ./scripts/validate-clean-root.sh
#   # Or from anywhere:
#   /path/to/project/scripts/validate-clean-root.sh

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Auto-detect project root from script location
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# =============================================================================
# Configuration: Files/directories that should NOT exist in project root
# =============================================================================
FORBIDDEN_PATTERNS=(
    # Log files
    "*.log"

    # Temporary files
    "*.tmp"
    "*.temp"

    # Editor swap files
    "*.swp"
    "*.swo"
    "*~"

    # Python bytecode
    "*.pyc"
    "*.pyo"

    # Python cache
    "__pycache__"

    # Coverage artifacts
    ".coverage"
    ".coverage.*"
    ".coverage.json"
    "htmlcov"
    "coverage.xml"

    # Audit reports (should be in docs/ or CI artifacts)
    "audit_*.json"
    "*_audit_report.json"
    "security_audit_*.json"

    # Output files (should be in appropriate directories)
    "*_output.txt"
    "collection_output.txt"

    # CI test artifacts
    "junit-*.xml"

    # Benchmark data
    "benchmark_results.json"

    # Build artifacts
    "dist"
    "build"
    "*.egg-info"

    # OS files
    ".DS_Store"
    "Thumbs.db"

    # Handoff docs (should be in docs/)
    "HANDOFF*.md"

    # Fix summaries (should be in docs/)
    "FIX_SUMMARY*.md"

    # Verification scripts (should be in scripts/)
    "verify_*.py"

    # Test files in root (should be in tests/)
    "test_*.py"

    # Demo scripts (should be in scripts/)
    "show_*.py"

    # Migration scripts (should be in scripts/)
    "migrate_*.py"

    # Pytest/mypy/ruff caches (if not gitignored)
    ".pytest_cache"
    ".mypy_cache"
    ".ruff_cache"

    # NPM/Yarn logs
    "npm-debug.log*"
    "yarn-debug.log*"
    "yarn-error.log*"

    # IDE backup files
    ".vscode/settings.json.bak"
    ".idea/workspace.xml"
)

# =============================================================================
# Whitelist: Directories that are allowed in root (standard project structure)
# =============================================================================
WHITELIST=(
    # Standard config directories
    ".github"
    ".vscode"
    ".claude"
    ".idea"

    # Source and test directories
    "src"
    "tests"
    "docs"
    "scripts"

    # Plugin and extension directories
    "plugins"
    "validation"
    "contracts"

    # Deployment and infrastructure
    "deployment"
    "monitoring"
    "grafana"

    # Service directories
    "services"
    "consumers"
    "shared_lib"

    # Additional project directories
    "skills"
    "agents"
    "app"
    "cli"
    "config"

    # Miscellaneous allowed directories
    "examples"
    "schemas"
    "sql"
    "tools"
    "tmp"

    # Archive directory
    "_archive"

    # Cache directories (allowed but should be gitignored)
    ".pytest_cache"
    ".mypy_cache"
    ".ruff_cache"
    ".DS_Store"
)

# =============================================================================
# Functions
# =============================================================================

check_root_cleanliness() {
    local violations_found=0
    local violations_list=()

    echo -e "${BLUE}Validating project root cleanliness...${NC}"
    echo "   Project: $PROJECT_ROOT"
    echo ""

    # Check each forbidden pattern
    for pattern in "${FORBIDDEN_PATTERNS[@]}"; do
        # Use find to check for pattern in root directory only (maxdepth 1)
        while IFS= read -r -d '' file; do
            # Get relative path from project root
            relative_path="${file#$PROJECT_ROOT/}"

            # Check if it's in whitelist
            is_whitelisted=0
            for whitelist_item in "${WHITELIST[@]}"; do
                if [[ "$relative_path" == "$whitelist_item"* ]]; then
                    is_whitelisted=1
                    break
                fi
            done

            if [ $is_whitelisted -eq 0 ]; then
                violations_list+=("$relative_path")
                violations_found=1
            fi
        done < <(find "$PROJECT_ROOT" -maxdepth 1 -name "$pattern" -print0 2>/dev/null)
    done

    # Report results
    if [ $violations_found -eq 0 ]; then
        echo -e "${GREEN}Project root is clean - no temporary/build artifacts found${NC}"
        return 0
    else
        echo -e "${RED}Project root validation FAILED${NC}"
        echo ""
        echo -e "${RED}======================================================================${NC}"
        echo -e "${RED}Found ${#violations_list[@]} forbidden file(s)/directory(ies) in project root:${NC}"
        echo -e "${RED}======================================================================${NC}"
        echo ""

        for violation in "${violations_list[@]}"; do
            echo -e "  ${RED}>${NC} $violation"
        done

        echo ""
        echo -e "${YELLOW}Why this matters:${NC}"
        echo "  - Temporary files pollute the repository"
        echo "  - Build artifacts should not be committed"
        echo "  - Coverage reports belong in CI, not source control"
        echo "  - Scripts/tests should be in their proper directories"
        echo "  - Clean root improves developer experience"
        echo ""
        echo -e "${YELLOW}How to fix:${NC}"
        echo "  1. Review the listed files above"
        echo "  2. Move files to appropriate directories:"
        echo -e "     ${BLUE}test_*.py -> tests/${NC}"
        echo -e "     ${BLUE}verify_*.py, show_*.py, migrate_*.py -> scripts/${NC}"
        echo -e "     ${BLUE}HANDOFF*.md, FIX_SUMMARY*.md -> docs/${NC}"
        echo "  3. Delete temporary/build artifacts:"
        echo -e "     ${BLUE}rm -rf htmlcov .coverage* *.log audit_*.json __pycache__ *.pyc${NC}"
        echo "  4. Add to .gitignore if needed"
        echo "  5. Try pushing again"
        echo ""
        echo -e "${YELLOW}To bypass this check (NOT recommended):${NC}"
        echo -e "  ${BLUE}git push --no-verify${NC}"
        echo ""

        return 1
    fi
}

# =============================================================================
# Main execution
# =============================================================================

check_root_cleanliness
exit $?
