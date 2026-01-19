#!/bin/bash
#
# Install Git Hooks for Documentation Change Tracking
#
# This script installs git hooks that automatically publish documentation
# changes to Kafka. It copies the hook scripts from scripts/ to .git/hooks/
# and sets up the necessary environment configuration.
#
# Usage:
#   ./scripts/install-hooks.sh              # Install all hooks
#   ./scripts/install-hooks.sh --uninstall  # Remove installed hooks
#   ./scripts/install-hooks.sh --help       # Show this help

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
HOOKS_DIR="$PROJECT_ROOT/.git/hooks"

# Hook names
HOOKS=("post-commit" "post-merge" "pre-push")

# Function to print colored messages
print_info() {
    echo -e "${BLUE}ℹ${NC} $1"
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

# Function to show help
show_help() {
    cat << EOF
Git Hooks Installation Script

Usage:
    ./scripts/install-hooks.sh [OPTIONS]

Options:
    --uninstall    Remove installed git hooks
    --help         Show this help message

Description:
    This script installs git hooks that automatically publish documentation
    changes to Kafka. The following hooks are installed:

    - post-commit:  Publishes doc changes after each commit
    - post-merge:   Publishes doc changes after merges
    - pre-push:     Optional validation before push (requires GIT_HOOK_VALIDATE_DOCS=true)

Requirements:
    - Git repository (.git directory must exist)
    - Python 3.7+ with confluent-kafka installed
    - Kafka broker running (or will be skipped gracefully)

Environment Variables:
    KAFKA_BOOTSTRAP_SERVERS - Kafka broker address (default: localhost:9092)
    KAFKA_DOC_TOPIC         - Kafka topic name (default: documentation-changed)
    GIT_HOOK_VALIDATE_DOCS  - Enable pre-push validation (default: false)

See README or documentation for more details.
EOF
}

# Function to check prerequisites
check_prerequisites() {
    print_info "Checking prerequisites..."

    # Check if in git repository
    if [ ! -d "$PROJECT_ROOT/.git" ]; then
        print_error "Not a git repository. Please run from project root."
        exit 1
    fi

    # Check if hooks directory exists
    if [ ! -d "$HOOKS_DIR" ]; then
        print_error "Git hooks directory not found: $HOOKS_DIR"
        exit 1
    fi

    # Check if Python is available
    if ! command -v python3 &> /dev/null; then
        print_warning "Python 3 not found. Hooks may fail at runtime."
    fi

    print_success "Prerequisites check passed"
}

# Function to backup existing hook
backup_hook() {
    local hook_name=$1
    local hook_path="$HOOKS_DIR/$hook_name"

    if [ -f "$hook_path" ] && [ ! -L "$hook_path" ]; then
        local backup_path="${hook_path}.backup.$(date +%Y%m%d_%H%M%S)"
        print_info "Backing up existing $hook_name to $(basename "$backup_path")"
        cp "$hook_path" "$backup_path"
    fi
}

# Function to install a single hook
install_hook() {
    local hook_name=$1
    local source_path="$SCRIPT_DIR/$hook_name"
    local dest_path="$HOOKS_DIR/$hook_name"

    if [ ! -f "$source_path" ]; then
        print_warning "Hook script not found: $source_path"
        return 1
    fi

    # Backup existing hook if it exists
    backup_hook "$hook_name"

    # Copy hook script
    cp "$source_path" "$dest_path"
    chmod +x "$dest_path"

    print_success "Installed $hook_name"
}

# Function to uninstall a single hook
uninstall_hook() {
    local hook_name=$1
    local hook_path="$HOOKS_DIR/$hook_name"

    if [ -f "$hook_path" ]; then
        # Check if it's one of our hooks (contains marker)
        if grep -q "publish_doc_change.py" "$hook_path" 2>/dev/null; then
            rm "$hook_path"
            print_success "Removed $hook_name"

            # Restore backup if available
            local latest_backup=$(ls -t "${hook_path}.backup."* 2>/dev/null | head -1)
            if [ -n "$latest_backup" ]; then
                print_info "Restoring backup: $(basename "$latest_backup")"
                cp "$latest_backup" "$hook_path"
                chmod +x "$hook_path"
            fi
        else
            print_warning "Skipping $hook_name (not our hook)"
        fi
    else
        print_info "$hook_name not installed"
    fi
}

# Function to check environment configuration
check_environment() {
    print_info "Checking environment configuration..."

    # Check if .env exists
    if [ ! -f "$PROJECT_ROOT/.env" ]; then
        print_warning ".env file not found. Using defaults."
        print_info "Copy .env.example to .env and configure Kafka settings:"
        print_info "  cp .env.example .env"
        print_info "  # Edit KAFKA_BOOTSTRAP_SERVERS and KAFKA_DOC_TOPIC"
    else
        print_success "Found .env file"
    fi

    # Check environment variables
    KAFKA_SERVERS="${KAFKA_BOOTSTRAP_SERVERS:-localhost:9092}"
    KAFKA_TOPIC="${KAFKA_DOC_TOPIC:-documentation-changed}"

    print_info "Kafka Configuration:"
    print_info "  Bootstrap Servers: $KAFKA_SERVERS"
    print_info "  Topic: $KAFKA_TOPIC"
}

# Main installation function
install_hooks() {
    print_info "Installing git hooks for documentation change tracking..."
    echo ""

    check_prerequisites
    echo ""

    # Install each hook
    for hook in "${HOOKS[@]}"; do
        install_hook "$hook"
    done

    echo ""
    check_environment
    echo ""

    print_success "Git hooks installed successfully!"
    echo ""
    print_info "The following hooks are now active:"
    print_info "  • post-commit: Publishes doc changes after commits"
    print_info "  • post-merge:  Publishes doc changes after merges"
    print_info "  • pre-push:    Validates docs before push (if enabled)"
    echo ""
    print_info "To test: Make a commit that modifies a .md file"
    print_info "To uninstall: Run ./scripts/install-hooks.sh --uninstall"
}

# Main uninstallation function
uninstall_hooks() {
    print_info "Uninstalling git hooks..."
    echo ""

    for hook in "${HOOKS[@]}"; do
        uninstall_hook "$hook"
    done

    echo ""
    print_success "Git hooks uninstalled successfully!"
}

# Main entry point
main() {
    case "${1:-}" in
        --uninstall)
            uninstall_hooks
            ;;
        --help|-h)
            show_help
            ;;
        "")
            install_hooks
            ;;
        *)
            print_error "Unknown option: $1"
            echo ""
            show_help
            exit 1
            ;;
    esac
}

main "$@"
