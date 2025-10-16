#!/bin/bash

################################################################################
# Git History Cleanup Validation Script
#
# Purpose: Validate that secrets have been successfully removed from git history
# Usage: ./validate-cleanup.sh
#
################################################################################

set -euo pipefail

# Color codes
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'
BOLD='\033[1m'

# Secrets to check for
GEMINI_KEY="***GEMINI_KEY_REMOVED***"
ZAI_KEY_FULL="***ZAI_KEY_REMOVED***"
ZAI_KEY_PARTIAL="***ZAI_KEY_REMOVED***"
ENV_FILE="agents/parallel_execution/.env"

REPO_PATH="${1:-$(pwd)}"

################################################################################
# Utility Functions
################################################################################

print_header() {
    echo -e "\n${CYAN}${BOLD}════════════════════════════════════════════════════════════════${NC}"
    echo -e "${CYAN}${BOLD}  $1${NC}"
    echo -e "${CYAN}${BOLD}════════════════════════════════════════════════════════════════${NC}\n"
}

print_step() {
    echo -e "${BLUE}➜${NC} ${BOLD}$1${NC}"
}

print_success() {
    echo -e "${GREEN}✓${NC} $1"
}

print_error() {
    echo -e "${RED}✗${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}⚠${NC} $1"
}

print_info() {
    echo -e "${CYAN}ℹ${NC} $1"
}

################################################################################
# Validation Functions
################################################################################

check_secret_in_history() {
    local secret="$1"
    local name="$2"

    print_step "Checking for $name..."

    if git log --all --full-history -S "$secret" --pretty=format:"%H" 2>/dev/null | grep -q .; then
        print_error "FOUND: $name exists in history"
        echo
        print_info "Commits containing this secret:"
        git log --all --full-history -S "$secret" --pretty=format:"  %h - %s" | head -10
        echo
        return 1
    else
        print_success "CLEAN: $name not found in history"
        return 0
    fi
}

check_file_in_history() {
    local file="$1"

    print_step "Checking for file: $file..."

    if git log --all --full-history -- "$file" --pretty=format:"%H" 2>/dev/null | grep -q .; then
        print_error "FOUND: $file exists in history"
        echo
        print_info "Commits containing this file:"
        git log --all --full-history -- "$file" --pretty=format:"  %h - %s" | head -10
        echo
        return 1
    else
        print_success "CLEAN: $file not found in history"
        return 0
    fi
}

check_file_in_tree() {
    local file="$1"

    print_step "Checking if $file exists in any commit tree..."

    if git rev-list --all | xargs git ls-tree -r --name-only | grep -q "$file"; then
        print_error "FOUND: $file exists in commit trees"
        return 1
    else
        print_success "CLEAN: $file not in any commit tree"
        return 0
    fi
}

check_repository_integrity() {
    print_step "Checking repository integrity..."

    if git fsck --full --no-progress 2>&1 | grep -q "error"; then
        print_error "Repository integrity check failed"
        return 1
    else
        print_success "Repository integrity check passed"
        return 0
    fi
}

################################################################################
# Advanced Scans
################################################################################

deep_content_scan() {
    print_step "Running deep content scan (all blobs)..."

    local found_secrets=false

    # Check all blobs for secrets
    for blob in $(git rev-list --all --objects | awk '{print $1}'); do
        if git cat-file -p "$blob" 2>/dev/null | grep -q "$GEMINI_KEY" 2>/dev/null; then
            print_error "Found GEMINI_KEY in blob: $blob"
            found_secrets=true
        fi

        if git cat-file -p "$blob" 2>/dev/null | grep -q "$ZAI_KEY_PARTIAL" 2>/dev/null; then
            print_error "Found ZAI_KEY in blob: $blob"
            found_secrets=true
        fi
    done

    if [[ "$found_secrets" == true ]]; then
        return 1
    else
        print_success "No secrets found in blob scan"
        return 0
    fi
}

################################################################################
# External Tool Integration
################################################################################

run_gitleaks() {
    print_step "Running gitleaks scan..."

    if ! command -v gitleaks &> /dev/null; then
        print_warning "gitleaks not installed - skipping"
        return 0
    fi

    if gitleaks detect --source "$REPO_PATH" --verbose --no-git 2>&1 | grep -q "leaks found"; then
        print_error "gitleaks found potential secrets"
        return 1
    else
        print_success "gitleaks scan clean"
        return 0
    fi
}

run_trufflehog() {
    print_step "Running truffleHog scan..."

    if ! command -v trufflehog &> /dev/null; then
        print_warning "trufflehog not installed - skipping"
        return 0
    fi

    if trufflehog git "file://$REPO_PATH" --json 2>&1 | grep -q "Raw"; then
        print_error "truffleHog found potential secrets"
        return 1
    else
        print_success "truffleHog scan clean"
        return 0
    fi
}

################################################################################
# Statistics
################################################################################

show_statistics() {
    print_step "Repository statistics..."

    local total_commits=$(git rev-list --all --count)
    local total_branches=$(git branch -a | wc -l | tr -d ' ')
    local total_tags=$(git tag -l | wc -l | tr -d ' ')
    local repo_size=$(du -sh .git 2>/dev/null | awk '{print $1}')

    echo
    echo -e "  ${CYAN}Total commits:${NC} $total_commits"
    echo -e "  ${CYAN}Total branches:${NC} $total_branches"
    echo -e "  ${CYAN}Total tags:${NC} $total_tags"
    echo -e "  ${CYAN}Repository size:${NC} $repo_size"
    echo
}

################################################################################
# Main Execution
################################################################################

main() {
    print_header "Git History Cleanup Validation"

    # Change to repository directory
    if [[ ! -d "$REPO_PATH/.git" ]]; then
        print_error "Not a git repository: $REPO_PATH"
        exit 1
    fi

    cd "$REPO_PATH"
    print_info "Validating repository: $REPO_PATH"
    echo

    # Track validation results
    local all_passed=true

    # Basic checks
    print_header "Basic Secret Checks"
    check_secret_in_history "$GEMINI_KEY" "GEMINI_API_KEY" || all_passed=false
    check_secret_in_history "$ZAI_KEY_FULL" "ZAI_API_KEY (full)" || all_passed=false
    check_secret_in_history "$ZAI_KEY_PARTIAL" "ZAI_API_KEY (partial)" || all_passed=false

    # File checks
    print_header "File Existence Checks"
    check_file_in_history "$ENV_FILE" || all_passed=false
    check_file_in_tree "$ENV_FILE" || all_passed=false

    # Repository integrity
    print_header "Repository Integrity"
    check_repository_integrity || all_passed=false

    # Advanced scans (optional, can be slow)
    if [[ "${DEEP_SCAN:-false}" == "true" ]]; then
        print_header "Deep Content Scan"
        print_warning "This may take several minutes..."
        deep_content_scan || all_passed=false
    fi

    # External tools
    print_header "External Security Scans"
    run_gitleaks || all_passed=false
    run_trufflehog || all_passed=false

    # Statistics
    print_header "Repository Statistics"
    show_statistics

    # Final result
    print_header "Validation Results"

    if [[ "$all_passed" == true ]]; then
        echo -e "${GREEN}${BOLD}✓ ALL CHECKS PASSED${NC}"
        echo
        print_success "No secrets found in repository history"
        print_success "Repository is clean and ready for push"
        echo
        print_info "Next steps:"
        echo "  1. Force push to remote: git push origin --force --all"
        echo "  2. Notify team members to re-clone"
        echo "  3. Implement prevention measures (git-secrets, pre-commit hooks)"
        echo
        exit 0
    else
        echo -e "${RED}${BOLD}✗ VALIDATION FAILED${NC}"
        echo
        print_error "Secrets or issues found in repository"
        print_error "Review the errors above before proceeding"
        echo
        print_info "Possible actions:"
        echo "  1. Re-run cleanup script: ./cleanup-secrets.sh"
        echo "  2. Manual inspection: git log -S <secret>"
        echo "  3. Restore from backup if needed"
        echo
        exit 1
    fi
}

# Show usage if --help
if [[ "${1:-}" == "--help" ]]; then
    cat << EOF
${BOLD}Git History Cleanup Validation Script${NC}

${BOLD}USAGE:${NC}
    $0 [REPO_PATH]

${BOLD}OPTIONS:${NC}
    REPO_PATH    Path to git repository (default: current directory)

${BOLD}ENVIRONMENT:${NC}
    DEEP_SCAN=true    Enable deep blob scanning (slow)

${BOLD}EXAMPLES:${NC}
    # Validate current directory
    ./validate-cleanup.sh

    # Validate specific repository
    ./validate-cleanup.sh /path/to/repo

    # Deep scan with blob inspection
    DEEP_SCAN=true ./validate-cleanup.sh

${BOLD}CHECKS PERFORMED:${NC}
    • Secret presence in commit history
    • File existence in commit trees
    • Repository integrity (git fsck)
    • External tool scans (gitleaks, truffleHog)
    • Repository statistics

${BOLD}EXIT CODES:${NC}
    0 - All validation checks passed
    1 - Validation failed, secrets found

EOF
    exit 0
fi

# Run main
main "$@"
