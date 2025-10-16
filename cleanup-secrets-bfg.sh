#!/bin/bash

################################################################################
# Git History Secret Cleanup Script - BFG Repo-Cleaner Method
#
# Purpose: Remove exposed API keys using BFG Repo-Cleaner (alternative method)
# Method: BFG Repo-Cleaner (faster for large repos)
# Risk Level: HIGH - This rewrites git history permanently
#
# WARNING: This script will:
#   - Rewrite all commit history
#   - Change all commit hashes
#   - Require force push to remote
#   - Invalidate all existing branches/PRs/references
#
# Prerequisites:
#   1. BFG Repo-Cleaner installed (brew install bfg)
#   2. All API keys already revoked
#   3. Full backup created
#   4. Team notified
#
# Usage:
#   ./cleanup-secrets-bfg.sh           # Run full cleanup
#   ./cleanup-secrets-bfg.sh --help    # Show help
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

# Configuration
REPO_PATH="/Volumes/PRO-G40/Code/omniclaude"
BACKUP_BASE="$HOME/git-backups"
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
WORK_DIR="$BACKUP_BASE/bfg-cleanup-$TIMESTAMP"

# Secrets to remove
GEMINI_KEY="***GEMINI_KEY_REMOVED***"
ZAI_KEY_FULL="***ZAI_KEY_REMOVED***"
ZAI_KEY_PARTIAL="***ZAI_KEY_REMOVED***"

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

print_warning() {
    echo -e "${YELLOW}⚠${NC} $1"
}

print_error() {
    echo -e "${RED}✗${NC} $1"
}

print_info() {
    echo -e "${CYAN}ℹ${NC} $1"
}

confirm_action() {
    local prompt="$1"
    echo -e "${YELLOW}${BOLD}$prompt${NC}"
    read -p "Type 'yes' to continue: " response
    if [[ "$response" != "yes" ]]; then
        print_error "Operation cancelled"
        exit 1
    fi
}

################################################################################
# Help
################################################################################

show_help() {
    cat << EOF
${BOLD}BFG Repo-Cleaner Method${NC}

${BOLD}USAGE:${NC}
    $0 [OPTIONS]

${BOLD}OPTIONS:${NC}
    --help       Show this help message

${BOLD}DESCRIPTION:${NC}
    Alternative cleanup method using BFG Repo-Cleaner.
    Generally faster than git-filter-repo for large repositories.

${BOLD}PREREQUISITES:${NC}
    1. Install BFG: ${CYAN}brew install bfg${NC}
    2. Revoke all exposed API keys
    3. Create full repository backup
    4. Notify team members

${BOLD}METHOD:${NC}
    This script will:
    1. Create a fresh mirror clone
    2. Use BFG to remove secrets
    3. Use BFG to remove .env file
    4. Run git gc for cleanup
    5. Validate results

${BOLD}MORE INFO:${NC}
    See GIT_HISTORY_CLEANUP_PLAN.md for details

EOF
    exit 0
}

################################################################################
# Main Execution
################################################################################

main() {
    # Parse arguments
    if [[ "${1:-}" == "--help" ]]; then
        show_help
    fi

    print_header "BFG Repo-Cleaner Secret Cleanup"

    # Check if BFG is installed
    print_step "Checking for BFG Repo-Cleaner..."
    if ! command -v bfg &> /dev/null; then
        print_error "BFG not found"
        echo
        print_info "Install with: brew install bfg"
        exit 1
    fi
    print_success "BFG found: $(which bfg)"

    # Create working directory
    print_step "Creating working directory..."
    mkdir -p "$WORK_DIR"
    cd "$WORK_DIR"
    print_success "Working directory: $WORK_DIR"

    # Create secrets replacement file
    print_step "Creating secrets configuration..."
    cat > secrets.txt <<EOF
$GEMINI_KEY
$ZAI_KEY_FULL
$ZAI_KEY_PARTIAL
EOF
    print_success "Secrets configuration created"

    # Final confirmation
    echo
    print_warning "═══════════════════════════════════════════════════════════════"
    print_warning "                  FINAL CONFIRMATION REQUIRED                  "
    print_warning "═══════════════════════════════════════════════════════════════"
    echo
    echo -e "${RED}${BOLD}This operation will:${NC}"
    echo -e "  ${RED}•${NC} Rewrite all commit history"
    echo -e "  ${RED}•${NC} Change all commit hashes"
    echo -e "  ${RED}•${NC} Remove secrets from all branches"
    echo
    confirm_action "Proceed with BFG cleanup?"

    # Clone mirror
    print_step "Cloning repository mirror..."
    git clone --mirror "$REPO_PATH" repo.git
    print_success "Mirror clone created"

    # Run BFG to replace secrets
    print_step "Running BFG to replace secrets..."
    bfg --replace-text secrets.txt repo.git
    print_success "Secrets replaced"

    # Run BFG to delete .env file
    print_step "Running BFG to delete .env file..."
    cd repo.git
    bfg --delete-files .env
    print_success ".env file deleted"

    # Clean up repository
    print_step "Running git gc (cleanup)..."
    git reflog expire --expire=now --all
    git gc --prune=now --aggressive
    print_success "Repository cleaned"

    # Validate
    print_step "Validating cleanup..."
    local validation_passed=true

    if git log --all -S "$GEMINI_KEY" --oneline | grep -q .; then
        print_error "GEMINI_KEY still found"
        validation_passed=false
    else
        print_success "GEMINI_KEY removed"
    fi

    if git log --all -S "$ZAI_KEY_PARTIAL" --oneline | grep -q .; then
        print_error "ZAI_KEY still found"
        validation_passed=false
    else
        print_success "ZAI_KEY removed"
    fi

    if git log --all -- "agents/parallel_execution/.env" --oneline | grep -q .; then
        print_error ".env still found"
        validation_passed=false
    else
        print_success ".env removed"
    fi

    if [[ "$validation_passed" == false ]]; then
        print_error "Validation failed"
        exit 1
    fi

    print_success "Validation passed"

    # Show next steps
    print_header "Next Steps"
    echo
    echo -e "${CYAN}${BOLD}1. Replace Your Repository${NC}"
    echo "   # Backup current repository"
    echo "   mv $REPO_PATH ${REPO_PATH}.backup"
    echo
    echo "   # Convert mirror to regular repo"
    echo "   git clone $WORK_DIR/repo.git $REPO_PATH"
    echo
    echo -e "${CYAN}${BOLD}2. Force Push to Remote${NC}"
    echo "   cd $REPO_PATH"
    echo "   git remote add origin <your-remote-url>"
    echo "   git push origin --force --all"
    echo "   git push origin --force --tags"
    echo
    echo -e "${CYAN}${BOLD}3. Notify Team${NC}"
    echo "   All collaborators must re-clone the repository"
    echo

    print_success "BFG cleanup complete"
    print_info "Cleaned repository: $WORK_DIR/repo.git"
}

# Run main
main "$@"
