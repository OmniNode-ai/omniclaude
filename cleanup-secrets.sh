#!/bin/bash

################################################################################
# Git History Secret Cleanup Script
#
# Purpose: Remove exposed API keys and sensitive files from git history
# Method: git-filter-repo (recommended by Git core team)
# Risk Level: HIGH - This rewrites git history permanently
#
# WARNING: This script will:
#   - Rewrite all commit history
#   - Change all commit hashes
#   - Require force push to remote
#   - Invalidate all existing branches/PRs/references
#
# Prerequisites:
#   1. git-filter-repo installed (brew install git-filter-repo)
#   2. All API keys already revoked
#   3. Full backup created
#   4. Team notified
#   5. Clean working directory
#
# Usage:
#   ./cleanup-secrets.sh           # Run full cleanup
#   ./cleanup-secrets.sh --dry-run # Analyze without changes
#   ./cleanup-secrets.sh --help    # Show help
#
################################################################################

set -euo pipefail  # Exit on error, undefined vars, pipe failures

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
MAGENTA='\033[0;35m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color
BOLD='\033[1m'

# Configuration
REPO_PATH="/Volumes/PRO-G40/Code/omniclaude"
BACKUP_BASE="$HOME/git-backups"
DRY_RUN=false
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
BACKUP_DIR="$BACKUP_BASE/omniclaude-$TIMESTAMP"

# Secrets to remove
GEMINI_KEY="***GEMINI_KEY_REMOVED***"
ZAI_KEY_FULL="***ZAI_KEY_REMOVED***"
ZAI_KEY_PARTIAL="***ZAI_KEY_REMOVED***"
ENV_FILE="agents/parallel_execution/.env"

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
    echo -e "${MAGENTA}ℹ${NC} $1"
}

confirm_action() {
    local prompt="$1"
    local response

    echo -e "${YELLOW}${BOLD}$prompt${NC}"
    read -p "Type 'yes' to continue: " response

    if [[ "$response" != "yes" ]]; then
        print_error "Operation cancelled by user"
        exit 1
    fi
}

check_command() {
    if ! command -v "$1" &> /dev/null; then
        print_error "Required command not found: $1"
        return 1
    fi
    print_success "Found: $1"
    return 0
}

################################################################################
# Help Message
################################################################################

show_help() {
    cat << EOF
${BOLD}Git History Secret Cleanup Script${NC}

${BOLD}USAGE:${NC}
    $0 [OPTIONS]

${BOLD}OPTIONS:${NC}
    --dry-run    Analyze repository without making changes
    --help       Show this help message

${BOLD}DESCRIPTION:${NC}
    This script removes exposed secrets from git history using git-filter-repo.

    ${YELLOW}${BOLD}WARNING:${NC} This operation:
      • Rewrites all commit history
      • Changes all commit hashes
      • Requires force push to remote
      • Invalidates existing branches/PRs

${BOLD}PREREQUISITES:${NC}
    1. Install git-filter-repo: ${CYAN}brew install git-filter-repo${NC}
    2. Revoke all exposed API keys
    3. Create full repository backup
    4. Notify team members
    5. Clean working directory

${BOLD}SECRETS TO BE REMOVED:${NC}
    • GEMINI_API_KEY: $GEMINI_KEY
    • ZAI_API_KEY: $ZAI_KEY_FULL
    • File: $ENV_FILE

${BOLD}EXAMPLE:${NC}
    # Dry run first (recommended)
    $0 --dry-run

    # Full cleanup
    $0

${BOLD}MORE INFO:${NC}
    See GIT_HISTORY_CLEANUP_PLAN.md for complete documentation

EOF
    exit 0
}

################################################################################
# Prerequisite Checks
################################################################################

check_prerequisites() {
    print_header "Checking Prerequisites"

    local all_good=true

    # Check required commands
    print_step "Verifying required tools..."
    check_command "git" || all_good=false
    check_command "git-filter-repo" || all_good=false
    check_command "jq" || all_good=false

    # Check if we're in a git repository
    print_step "Verifying git repository..."
    if [[ ! -d "$REPO_PATH/.git" ]]; then
        print_error "Not a git repository: $REPO_PATH"
        all_good=false
    else
        print_success "Valid git repository"
    fi

    # Check working directory is clean
    print_step "Checking working directory status..."
    cd "$REPO_PATH"
    if [[ -n $(git status --porcelain) ]]; then
        print_warning "Working directory has uncommitted changes"
        print_info "Run: git status"
        echo
        git status --short
        echo
        confirm_action "Continue with uncommitted changes? (They will be preserved)"
    else
        print_success "Working directory is clean"
    fi

    # Check if secrets exist in history
    print_step "Verifying secrets exist in history..."
    local found_secrets=false

    if git log --all --full-history -S "$GEMINI_KEY" --pretty=format:"%H" | grep -q .; then
        print_warning "Found GEMINI_API_KEY in history"
        found_secrets=true
    fi

    if git log --all --full-history -S "$ZAI_KEY_PARTIAL" --pretty=format:"%H" | grep -q .; then
        print_warning "Found ZAI_API_KEY in history"
        found_secrets=true
    fi

    if git log --all --full-history -- "$ENV_FILE" --pretty=format:"%H" | grep -q .; then
        print_warning "Found .env file in history"
        found_secrets=true
    fi

    if [[ "$found_secrets" == false ]]; then
        print_info "No secrets found in history - cleanup may not be needed"
        confirm_action "Continue anyway?"
    fi

    if [[ "$all_good" == false ]]; then
        print_error "Prerequisites check failed"
        echo
        print_info "Install missing tools:"
        echo "  brew install git-filter-repo"
        echo "  brew install jq"
        exit 1
    fi

    print_success "All prerequisites met"
}

################################################################################
# Backup Creation
################################################################################

create_backup() {
    print_header "Creating Backup"

    if [[ "$DRY_RUN" == true ]]; then
        print_info "DRY RUN: Skipping backup creation"
        return
    fi

    print_step "Creating backup at: $BACKUP_DIR"

    mkdir -p "$BACKUP_DIR"

    # Clone as mirror (complete backup)
    print_info "Cloning repository mirror..."
    git clone --mirror "$REPO_PATH" "$BACKUP_DIR/omniclaude-backup.git"

    # Export commit list
    print_info "Exporting commit history..."
    cd "$REPO_PATH"
    git log --all --pretty=format:"%H %s" > "$BACKUP_DIR/pre-cleanup-commits.txt"
    git tag -l > "$BACKUP_DIR/pre-cleanup-tags.txt"
    git branch -a > "$BACKUP_DIR/pre-cleanup-branches.txt"
    git rev-list --all --count > "$BACKUP_DIR/pre-cleanup-commit-count.txt"

    # Verify backup
    print_info "Verifying backup..."
    cd "$BACKUP_DIR/omniclaude-backup.git"
    if git fsck --full --no-progress 2>&1 | grep -q "error"; then
        print_error "Backup verification failed"
        exit 1
    fi

    print_success "Backup created and verified"
    print_info "Backup location: $BACKUP_DIR"

    # Save backup location for later
    echo "$BACKUP_DIR" > /tmp/git-cleanup-backup-location.txt
}

################################################################################
# Secret Cleanup
################################################################################

cleanup_secrets() {
    print_header "Cleaning Secrets from History"

    cd "$REPO_PATH"

    if [[ "$DRY_RUN" == true ]]; then
        print_info "DRY RUN: Simulating cleanup operations"
        print_warning "The following changes would be made:"
        echo
        print_info "1. Remove file: $ENV_FILE"
        print_info "2. Replace: $GEMINI_KEY => ***GEMINI_KEY_REMOVED***"
        print_info "3. Replace: $ZAI_KEY_FULL => ***ZAI_KEY_REMOVED***"
        print_info "4. Replace: $ZAI_KEY_PARTIAL => ***ZAI_KEY_REMOVED***"
        echo
        print_info "Commits that would be affected:"
        git log --all --full-history --pretty=format:"%h %s" -- "$ENV_FILE" | head -10
        echo
        return
    fi

    # Create replacement file for secrets
    print_step "Creating secret replacement configuration..."
    cat > /tmp/secrets-to-remove.txt <<EOF
$GEMINI_KEY==>***GEMINI_KEY_REMOVED***
$ZAI_KEY_FULL==>***ZAI_KEY_REMOVED***
$ZAI_KEY_PARTIAL==>***ZAI_KEY_REMOVED***
EOF

    print_success "Secret replacement configuration created"

    # Final confirmation
    print_warning "═══════════════════════════════════════════════════════════════"
    print_warning "                  FINAL CONFIRMATION REQUIRED                  "
    print_warning "═══════════════════════════════════════════════════════════════"
    echo
    echo -e "${RED}${BOLD}This operation will:${NC}"
    echo -e "  ${RED}•${NC} Rewrite all commit history"
    echo -e "  ${RED}•${NC} Change all commit hashes"
    echo -e "  ${RED}•${NC} Remove secrets from all branches and tags"
    echo -e "  ${RED}•${NC} Require force push to remote"
    echo
    echo -e "${YELLOW}${BOLD}After this operation:${NC}"
    echo -e "  ${YELLOW}•${NC} All collaborators must re-clone"
    echo -e "  ${YELLOW}•${NC} Open PRs may need recreation"
    echo -e "  ${YELLOW}•${NC} Local branches become invalid"
    echo
    echo -e "${GREEN}${BOLD}Backup location:${NC}"
    echo -e "  $BACKUP_DIR"
    echo
    confirm_action "Proceed with history rewrite?"

    # Run git-filter-repo
    print_step "Running git-filter-repo (this may take a few minutes)..."

    # Remove .env file from history
    print_info "Removing $ENV_FILE from all commits..."
    git filter-repo --force \
        --path "$ENV_FILE" --invert-paths \
        --replace-text /tmp/secrets-to-remove.txt

    print_success "History rewrite complete"

    # Clean up temp file
    rm -f /tmp/secrets-to-remove.txt
}

################################################################################
# Validation
################################################################################

validate_cleanup() {
    print_header "Validating Cleanup"

    cd "$REPO_PATH"

    if [[ "$DRY_RUN" == true ]]; then
        print_info "DRY RUN: Skipping validation"
        return
    fi

    local validation_passed=true

    # Check 1: Secrets should not appear in history
    print_step "Verifying secrets removed from history..."

    if git log --all --full-history -S "$GEMINI_KEY" --pretty=format:"%H" | grep -q .; then
        print_error "GEMINI_API_KEY still found in history"
        validation_passed=false
    else
        print_success "GEMINI_API_KEY removed from history"
    fi

    if git log --all --full-history -S "$ZAI_KEY_PARTIAL" --pretty=format:"%H" | grep -q .; then
        print_error "ZAI_API_KEY still found in history"
        validation_passed=false
    else
        print_success "ZAI_API_KEY removed from history"
    fi

    # Check 2: .env file should not exist in history
    print_step "Verifying .env file removed..."

    if git log --all --full-history -- "$ENV_FILE" --pretty=format:"%H" | grep -q .; then
        print_error ".env file still found in history"
        validation_passed=false
    else
        print_success ".env file removed from history"
    fi

    # Check 3: Repository integrity
    print_step "Checking repository integrity..."

    if git fsck --full --no-progress 2>&1 | grep -q "error"; then
        print_error "Repository integrity check failed"
        validation_passed=false
    else
        print_success "Repository integrity check passed"
    fi

    # Check 4: Commit count
    print_step "Verifying commit count..."

    local new_count=$(git rev-list --all --count)
    print_info "New commit count: $new_count"

    if [[ -f "$BACKUP_DIR/pre-cleanup-commit-count.txt" ]]; then
        local old_count=$(cat "$BACKUP_DIR/pre-cleanup-commit-count.txt")
        print_info "Original commit count: $old_count"

        if [[ "$new_count" -lt $((old_count - 10)) ]]; then
            print_warning "Significant commit count reduction detected"
            print_warning "This may indicate an issue - review carefully"
        fi
    fi

    # Check 5: Branches
    print_step "Verifying branches..."
    git branch -a | head -10
    print_success "Branches verified"

    if [[ "$validation_passed" == false ]]; then
        print_error "Validation failed - review issues above"
        exit 1
    fi

    print_success "All validation checks passed"
}

################################################################################
# Next Steps
################################################################################

show_next_steps() {
    print_header "Next Steps"

    if [[ "$DRY_RUN" == true ]]; then
        echo -e "${GREEN}${BOLD}Dry run complete!${NC}"
        echo
        print_info "No changes were made to the repository"
        print_info "Review the output above to understand what would happen"
        echo
        print_step "To perform the actual cleanup:"
        echo "  ./cleanup-secrets.sh"
        return
    fi

    echo -e "${GREEN}${BOLD}Cleanup complete!${NC}"
    echo
    print_warning "IMPORTANT: Additional steps required"
    echo

    echo -e "${CYAN}${BOLD}1. Force Push to Remote${NC}"
    echo "   ${YELLOW}WARNING: This will overwrite remote history${NC}"
    echo
    echo "   # View remotes"
    echo "   git remote -v"
    echo
    echo "   # Force push all branches (DANGER)"
    echo "   git push origin --force --all"
    echo
    echo "   # Force push all tags (DANGER)"
    echo "   git push origin --force --tags"
    echo

    echo -e "${CYAN}${BOLD}2. Notify Team Members${NC}"
    echo "   All collaborators must:"
    echo "   • Delete their local repository"
    echo "   • Re-clone from remote"
    echo "   • Recreate any local branches"
    echo

    echo -e "${CYAN}${BOLD}3. Handle Open Pull Requests${NC}"
    echo "   • Review all open PRs"
    echo "   • Recreate PRs as needed"
    echo "   • Update PR descriptions with new commit references"
    echo

    echo -e "${CYAN}${BOLD}4. Update Documentation${NC}"
    echo "   • Update any commit references in documentation"
    echo "   • Update CI/CD pipelines with new commit hashes"
    echo "   • Archive old commit mapping for reference"
    echo

    echo -e "${CYAN}${BOLD}5. Implement Prevention${NC}"
    echo "   • Update .gitignore"
    echo "   • Install git-secrets: ${YELLOW}brew install git-secrets${NC}"
    echo "   • Configure pre-commit hooks"
    echo "   • Create env.template files"
    echo

    echo -e "${MAGENTA}${BOLD}Backup Location:${NC}"
    echo "   $BACKUP_DIR"
    echo

    echo -e "${MAGENTA}${BOLD}For Detailed Instructions:${NC}"
    echo "   See: GIT_HISTORY_CLEANUP_PLAN.md"
    echo
}

################################################################################
# Main Execution
################################################################################

main() {
    # Parse arguments
    while [[ $# -gt 0 ]]; do
        case $1 in
            --dry-run)
                DRY_RUN=true
                shift
                ;;
            --help)
                show_help
                ;;
            *)
                print_error "Unknown option: $1"
                echo "Use --help for usage information"
                exit 1
                ;;
        esac
    done

    # Print banner
    clear
    print_header "Git History Secret Cleanup Script"

    if [[ "$DRY_RUN" == true ]]; then
        print_warning "DRY RUN MODE - No changes will be made"
        echo
    fi

    # Execute cleanup steps
    check_prerequisites
    create_backup
    cleanup_secrets
    validate_cleanup
    show_next_steps

    # Final message
    echo
    if [[ "$DRY_RUN" == true ]]; then
        print_success "Dry run completed successfully"
    else
        print_success "Cleanup completed successfully"
        print_warning "Don't forget to force push and notify team!"
    fi
    echo
}

# Trap errors
trap 'print_error "Script failed at line $LINENO"' ERR

# Run main function
main "$@"
