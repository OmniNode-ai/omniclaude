#!/bin/bash
################################################################################
# Pattern System Re-ingestion Orchestration Script
################################################################################
# Purpose: Complete workflow for pattern migration
# Usage: ./scripts/reingest_patterns.sh [--dry-run] [--skip-backup]
# Steps:
#   1. Backup current data
#   2. Validate backup
#   3. Clean file-based patterns
#   4. Extract real patterns from codebases
#   5. Ingest patterns to database
#   6. Validate migration results
################################################################################

set -e  # Exit on error
set -u  # Exit on undefined variable

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Configuration
DB_HOST="${POSTGRES_HOST:-192.168.86.200}"
DB_PORT="${POSTGRES_PORT:-5436}"
DB_USER="${POSTGRES_USER:-postgres}"
DB_NAME="${POSTGRES_DATABASE:-omninode_bridge}"
DB_PASSWORD="${POSTGRES_PASSWORD}"  # Must be set in environment

# Verify password is set
if [ -z "$DB_PASSWORD" ]; then
    echo -e "${RED}❌ ERROR: POSTGRES_PASSWORD environment variable not set${NC}"
    echo "   Please run: source .env"
    exit 1
fi

# Source directories for pattern extraction
SOURCE_DIRS=(
    "/Volumes/PRO-G40/Code/omniclaude"
    "/Volumes/PRO-G40/Code/Omniarchon"
    "/Volumes/PRO-G40/Code/omnidash"
)

# Output files
EXTRACTED_PATTERNS="/tmp/extracted_patterns.json"
BACKUP_DIR="./backups"
LOG_FILE="${BACKUP_DIR}/reingest_$(date +%Y%m%d_%H%M%S).log"

# Parse arguments
DRY_RUN=false
SKIP_BACKUP=false
PARALLEL_JOBS=4
MIN_QUALITY=0.6
MAX_COMPLEXITY=15

while [[ $# -gt 0 ]]; do
    case $1 in
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --skip-backup)
            SKIP_BACKUP=true
            shift
            ;;
        --parallel)
            PARALLEL_JOBS="$2"
            shift 2
            ;;
        --min-quality)
            MIN_QUALITY="$2"
            shift 2
            ;;
        --max-complexity)
            MAX_COMPLEXITY="$2"
            shift 2
            ;;
        -h|--help)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --dry-run            Run without making changes"
            echo "  --skip-backup        Skip backup step (not recommended)"
            echo "  --parallel N         Number of parallel extraction jobs (default: 4)"
            echo "  --min-quality N      Minimum quality score (default: 0.6)"
            echo "  --max-complexity N   Maximum complexity (default: 15)"
            echo "  -h, --help           Show this help message"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

# Create log directory
mkdir -p "$BACKUP_DIR"

# Logging function
log() {
    local level=$1
    shift
    local message="$@"
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    echo -e "${timestamp} [${level}] ${message}" | tee -a "$LOG_FILE"
}

# Error handler
error_exit() {
    log "ERROR" "${RED}$1${NC}"
    log "ERROR" "Re-ingestion failed!"
    log "ERROR" "Check log file: $LOG_FILE"
    exit 1
}

# Success handler
success() {
    log "SUCCESS" "${GREEN}$1${NC}"
}

# Warning handler
warning() {
    log "WARNING" "${YELLOW}$1${NC}"
}

# Info handler
info() {
    log "INFO" "${CYAN}$1${NC}"
}

################################################################################
# Main workflow
################################################################################

echo ""
echo "=========================================="
echo "Pattern System Re-ingestion"
echo "=========================================="
echo ""
echo "Configuration:"
echo "  Database: $DB_NAME @ $DB_HOST:$DB_PORT"
echo "  Source dirs: ${#SOURCE_DIRS[@]} codebases"
echo "  Min quality: $MIN_QUALITY"
echo "  Max complexity: $MAX_COMPLEXITY"
echo "  Parallel jobs: $PARALLEL_JOBS"
echo "  Dry run: $DRY_RUN"
echo "  Skip backup: $SKIP_BACKUP"
echo ""
echo "Log file: $LOG_FILE"
echo ""

if [ "$DRY_RUN" = true ]; then
    warning "DRY RUN MODE - No changes will be made"
    echo ""
fi

# Confirmation prompt (unless dry run)
if [ "$DRY_RUN" = false ]; then
    read -p "Continue with re-ingestion? (yes/no): " confirm
    if [ "$confirm" != "yes" ]; then
        info "Re-ingestion cancelled by user"
        exit 0
    fi
    echo ""
fi

################################################################################
# Step 1: Backup
################################################################################

if [ "$SKIP_BACKUP" = false ]; then
    info "Step 1/5: Creating backup..."

    if [ "$DRY_RUN" = false ]; then
        if ! ./scripts/backup_patterns.sh >> "$LOG_FILE" 2>&1; then
            error_exit "Backup failed! Aborting re-ingestion."
        fi
        success "Backup created successfully"
    else
        info "DRY RUN: Would create backup"
    fi
else
    warning "SKIPPING BACKUP (--skip-backup flag set)"
    warning "This is dangerous! No rollback possible if migration fails."
    sleep 2
fi

echo ""

################################################################################
# Step 2: Cleanup
################################################################################

info "Step 2/5: Cleaning file-based patterns..."

if [ "$DRY_RUN" = false ]; then
    # Run cleanup script
    if ! PGPASSWORD="$DB_PASSWORD" psql \
        -h "$DB_HOST" \
        -p "$DB_PORT" \
        -U "$DB_USER" \
        -d "$DB_NAME" \
        -f scripts/cleanup_file_patterns.sql >> "$LOG_FILE" 2>&1; then
        error_exit "Cleanup failed! Check log file for details."
    fi
    success "File-based patterns cleaned successfully"
else
    info "DRY RUN: Would clean file-based patterns"
fi

echo ""

################################################################################
# Step 3: Extract patterns
################################################################################

info "Step 3/5: Extracting patterns from codebases..."
info "Source directories:"
for dir in "${SOURCE_DIRS[@]}"; do
    info "  - $dir"
done

if [ "$DRY_RUN" = false ]; then
    # Check if ingest_patterns.py exists
    if [ ! -f "scripts/ingest_patterns.py" ]; then
        error_exit "scripts/ingest_patterns.py not found! Please create it first."
    fi

    # Build source dir arguments
    SOURCE_ARGS=""
    for dir in "${SOURCE_DIRS[@]}"; do
        if [ -d "$dir" ]; then
            SOURCE_ARGS="$SOURCE_ARGS --sources $dir"
        else
            warning "Directory not found: $dir (skipping)"
        fi
    done

    # Extract patterns
    info "Running pattern extraction..."
    if ! python3 scripts/ingest_patterns.py \
        $SOURCE_ARGS \
        --output "$EXTRACTED_PATTERNS" \
        --min-quality "$MIN_QUALITY" \
        --max-complexity "$MAX_COMPLEXITY" \
        --parallel "$PARALLEL_JOBS" >> "$LOG_FILE" 2>&1; then
        error_exit "Pattern extraction failed!"
    fi

    # Count extracted patterns
    if [ -f "$EXTRACTED_PATTERNS" ]; then
        PATTERN_COUNT=$(python3 -c "import json; print(len(json.load(open('$EXTRACTED_PATTERNS'))))" 2>/dev/null || echo "0")
        success "Extracted $PATTERN_COUNT patterns"

        if [ "$PATTERN_COUNT" -lt 50 ]; then
            warning "Low pattern count ($PATTERN_COUNT) - expected 200-500"
            warning "Consider lowering --min-quality or --max-complexity"
        fi
    else
        error_exit "Pattern extraction output file not found!"
    fi
else
    info "DRY RUN: Would extract patterns from ${#SOURCE_DIRS[@]} directories"
    info "DRY RUN: Would write to $EXTRACTED_PATTERNS"
fi

echo ""

################################################################################
# Step 4: Ingest patterns
################################################################################

info "Step 4/5: Ingesting patterns to database..."

if [ "$DRY_RUN" = false ]; then
    if [ -f "$EXTRACTED_PATTERNS" ]; then
        info "Ingesting from: $EXTRACTED_PATTERNS"

        if ! python3 scripts/ingest_patterns.py \
            --input "$EXTRACTED_PATTERNS" \
            --database "$DB_NAME" \
            --host "$DB_HOST" \
            --port "$DB_PORT" \
            --user "$DB_USER" \
            --password "$DB_PASSWORD" \
            --batch-size 100 \
            --skip-duplicates >> "$LOG_FILE" 2>&1; then
            error_exit "Pattern ingestion failed!"
        fi

        success "Patterns ingested successfully"
    else
        error_exit "Extracted patterns file not found: $EXTRACTED_PATTERNS"
    fi
else
    info "DRY RUN: Would ingest patterns from $EXTRACTED_PATTERNS"
fi

echo ""

################################################################################
# Step 5: Validate
################################################################################

info "Step 5/5: Validating migration results..."

if [ "$DRY_RUN" = false ]; then
    if ! ./scripts/validate_patterns.sh >> "$LOG_FILE" 2>&1; then
        warning "Validation script failed - check log for details"
    else
        success "Validation complete"
    fi

    # Show validation summary to user
    echo ""
    echo "=========================================="
    echo "Validation Summary"
    echo "=========================================="
    ./scripts/validate_patterns.sh 2>&1 | grep -E "(✓|✗|⚠|Total|High Quality|Filename)" || true
else
    info "DRY RUN: Would run validation"
fi

echo ""

################################################################################
# Final summary
################################################################################

echo "=========================================="
if [ "$DRY_RUN" = false ]; then
    success "Re-ingestion Complete!"
else
    info "DRY RUN Complete!"
fi
echo "=========================================="
echo ""
echo "Log file: $LOG_FILE"
echo ""

if [ "$DRY_RUN" = false ]; then
    echo "Next steps:"
    echo "  1. Review validation results above"
    echo "  2. Check log file for any warnings: $LOG_FILE"
    echo "  3. Test pattern queries in your application"
    echo ""
    echo "If issues found, rollback with:"
    echo "  ./scripts/rollback_patterns.sh <backup_file>"
    echo ""
    echo "Recent backups:"
    ls -lht "$BACKUP_DIR" | grep "backup_patterns" | head -3 || true
else
    echo "To run for real:"
    echo "  ./scripts/reingest_patterns.sh"
fi

echo ""

exit 0
