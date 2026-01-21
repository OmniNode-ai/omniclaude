#!/bin/bash
# ==============================================================================
# OmniNode Bridge Database Dump Utility
# ==============================================================================
# Purpose: Dump entire omninode_bridge database from remote PostgreSQL
# Author: OmniClaude Team
# Date: 2025-10-25
# ==============================================================================

set -euo pipefail

# Load environment variables from .env
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

if [[ ! -f "$PROJECT_ROOT/.env" ]]; then
    echo "❌ ERROR: .env file not found at $PROJECT_ROOT/.env"
    echo "   Please copy .env.example to .env and configure it"
    exit 1
fi

# Source .env file
source "$PROJECT_ROOT/.env"

# Configuration (no fallbacks - must be set in .env)
DB_HOST="${POSTGRES_HOST}"
DB_PORT="${POSTGRES_PORT}"
DB_NAME="${POSTGRES_DATABASE}"
DB_USER="${POSTGRES_USER}"
# Note: Using POSTGRES_PASSWORD directly (no alias)

# Colors (defined before validation to allow colored output)
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
RED='\033[0;31m'
NC='\033[0m'

# Verify required variables are set
missing_vars=()
[ -z "$DB_HOST" ] && missing_vars+=("POSTGRES_HOST")
[ -z "$DB_PORT" ] && missing_vars+=("POSTGRES_PORT")
[ -z "$DB_NAME" ] && missing_vars+=("POSTGRES_DATABASE")
[ -z "$DB_USER" ] && missing_vars+=("POSTGRES_USER")
[ -z "$POSTGRES_PASSWORD" ] && missing_vars+=("POSTGRES_PASSWORD")

if [ ${#missing_vars[@]} -gt 0 ]; then
    echo -e "${RED}❌ ERROR: Required environment variables not set in .env:${NC}"
    for var in "${missing_vars[@]}"; do
        echo "   - $var"
    done
    echo ""
    echo "Please update your .env file with these variables."
    exit 1
fi

# Output directory
DUMP_DIR="${DUMP_DIR:-./db_dumps}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

# ==============================================================================
# Functions
# ==============================================================================

print_header() {
    echo -e "\n${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${CYAN}$1${NC}"
    echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}\n"
}

print_step() {
    echo -e "${BLUE}▶ $1${NC}"
}

run_psql() {
    PGPASSWORD="$POSTGRES_PASSWORD" psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" "$@"
}

run_pg_dump() {
    PGPASSWORD="$POSTGRES_PASSWORD" pg_dump -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" "$@"
}

# ==============================================================================
# Dump Functions
# ==============================================================================

check_connection() {
    print_step "Checking database connection..."
    if run_psql -c "SELECT 'Connected!' as status;" 2>&1 | grep -q "Connected"; then
        echo -e "${GREEN}✓ Connected to $DB_HOST:$DB_PORT/$DB_NAME${NC}"
        return 0
    else
        echo -e "${RED}✗ Failed to connect${NC}"
        return 1
    fi
}

show_database_info() {
    print_step "Database Information"
    run_psql -c "
        SELECT
            pg_database.datname,
            pg_size_pretty(pg_database_size(pg_database.datname)) as size,
            (SELECT count(*) FROM information_schema.tables
             WHERE table_schema = 'public') as table_count
        FROM pg_database
        WHERE datname = '$DB_NAME';
    "
}

dump_schema_only() {
    local output_file="$DUMP_DIR/schema_${TIMESTAMP}.sql"
    print_step "Dumping schema to: $output_file"

    run_pg_dump --schema-only --no-owner --no-privileges -f "$output_file"

    if [ -f "$output_file" ]; then
        echo -e "${GREEN}✓ Schema dumped: $(wc -l < "$output_file") lines${NC}"
    fi
}

dump_data_only() {
    local output_file="$DUMP_DIR/data_${TIMESTAMP}.sql"
    print_step "Dumping data to: $output_file"

    run_pg_dump --data-only --inserts --column-inserts -f "$output_file"

    if [ -f "$output_file" ]; then
        echo -e "${GREEN}✓ Data dumped: $(wc -l < "$output_file") lines${NC}"
    fi
}

dump_full_database() {
    local output_file="$DUMP_DIR/full_${TIMESTAMP}.sql"
    print_step "Dumping full database to: $output_file"

    run_pg_dump --no-owner --no-privileges -f "$output_file"

    if [ -f "$output_file" ]; then
        echo -e "${GREEN}✓ Full dump complete: $(wc -l < "$output_file") lines${NC}"

        # Compress the dump
        gzip "$output_file"
        echo -e "${GREEN}✓ Compressed: ${output_file}.gz ($(du -h "${output_file}.gz" | cut -f1))${NC}"
    fi
}

dump_table_list() {
    local output_file="$DUMP_DIR/table_list_${TIMESTAMP}.txt"
    print_step "Generating table list: $output_file"

    run_psql -c "
        SELECT
            table_name,
            (SELECT COUNT(*) FROM information_schema.columns
             WHERE table_name = t.table_name) as column_count,
            pg_size_pretty(pg_total_relation_size(quote_ident(table_name))) as size
        FROM information_schema.tables t
        WHERE table_schema = 'public'
          AND table_type = 'BASE TABLE'
        ORDER BY table_name;
    " > "$output_file"

    echo -e "${GREEN}✓ Table list saved${NC}"
    cat "$output_file"
}

dump_row_counts() {
    local output_file="$DUMP_DIR/row_counts_${TIMESTAMP}.txt"
    print_step "Generating row counts: $output_file"

    # Get all tables
    tables=$(run_psql -t -c "
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'public'
          AND table_type = 'BASE TABLE'
        ORDER BY table_name;
    ")

    {
        echo "Table Row Counts - $(date)"
        echo "================================"
        echo ""

        for table in $tables; do
            count=$(run_psql -t -c "SELECT COUNT(*) FROM $table;" 2>/dev/null || echo "ERROR")
            printf "%-40s %10s\n" "$table" "$count"
        done
    } > "$output_file"

    echo -e "${GREEN}✓ Row counts saved${NC}"
    cat "$output_file"
}

dump_recent_data() {
    local output_file="$DUMP_DIR/recent_activity_${TIMESTAMP}.txt"
    print_step "Generating recent activity report: $output_file"

    {
        echo "Recent Database Activity - $(date)"
        echo "====================================="
        echo ""

        echo "Agent Routing Decisions (Last 10):"
        run_psql -c "
            SELECT selected_agent, confidence_score, created_at
            FROM agent_routing_decisions
            ORDER BY created_at DESC
            LIMIT 10;
        " 2>/dev/null || echo "Table not found or empty"

        echo -e "\nAgent Actions (Last 10):"
        run_psql -c "
            SELECT agent_name, action_type, action_name, created_at
            FROM agent_actions
            ORDER BY created_at DESC
            LIMIT 10;
        " 2>/dev/null || echo "Table not found or empty"

        echo -e "\nPattern Lineage Nodes (Last 10):"
        run_psql -c "
            SELECT pattern_name, pattern_type, created_at
            FROM pattern_lineage_nodes
            ORDER BY created_at DESC
            LIMIT 10;
        " 2>/dev/null || echo "Table not found or empty"

        echo -e "\nHook Events (Last 10):"
        run_psql -c "
            SELECT hook_name, event_type, created_at
            FROM hook_events
            ORDER BY created_at DESC
            LIMIT 10;
        " 2>/dev/null || echo "Table not found or empty"

    } > "$output_file"

    echo -e "${GREEN}✓ Recent activity report saved${NC}"
}

create_dump_directory() {
    if [ ! -d "$DUMP_DIR" ]; then
        mkdir -p "$DUMP_DIR"
        echo -e "${GREEN}✓ Created dump directory: $DUMP_DIR${NC}"
    fi
}

# ==============================================================================
# Main Script
# ==============================================================================

usage() {
    cat <<EOF
OmniNode Bridge Database Dump Utility

Usage: $0 [COMMAND]

Commands:
    full        Dump complete database (schema + data, compressed)
    schema      Dump schema only
    data        Dump data only
    tables      List all tables with sizes
    counts      Show row counts for all tables
    recent      Show recent activity
    all         Run all dump commands (default)
    help        Show this help message

Output:
    All dumps are saved to: $DUMP_DIR/
    Filenames include timestamp: ${TIMESTAMP}

Environment Variables (configured in .env):
    POSTGRES_HOST       Database host (required)
    POSTGRES_PORT       Database port (required)
    POSTGRES_DATABASE   Database name (required)
    POSTGRES_USER       Database user (required)
    POSTGRES_PASSWORD   Database password (required)
    DUMP_DIR            Output directory (default: ./db_dumps)

Examples:
    $0                    # Dump everything
    $0 full               # Full database dump
    $0 schema             # Schema only
    $0 tables counts      # Table list and row counts

EOF
}

main() {
    print_header "OMNINODE BRIDGE DATABASE DUMP UTILITY"

    create_dump_directory

    check_connection || exit 1

    show_database_info

    if [ $# -eq 0 ]; then
        # Default: dump everything
        dump_table_list
        dump_row_counts
        dump_schema_only
        dump_data_only
        dump_full_database
        dump_recent_data
    else
        for cmd in "$@"; do
            case "$cmd" in
                full)
                    dump_full_database
                    ;;
                schema)
                    dump_schema_only
                    ;;
                data)
                    dump_data_only
                    ;;
                tables)
                    dump_table_list
                    ;;
                counts)
                    dump_row_counts
                    ;;
                recent)
                    dump_recent_data
                    ;;
                all)
                    dump_table_list
                    dump_row_counts
                    dump_schema_only
                    dump_data_only
                    dump_full_database
                    dump_recent_data
                    ;;
                help|--help|-h)
                    usage
                    exit 0
                    ;;
                *)
                    echo -e "${RED}Unknown command: $cmd${NC}"
                    usage
                    exit 1
                    ;;
            esac
        done
    fi

    print_header "DUMP COMPLETE"
    echo -e "Output directory: ${CYAN}$DUMP_DIR/${NC}"
    echo -e "Files created:"
    ls -lh "$DUMP_DIR"/*${TIMESTAMP}* 2>/dev/null || echo "No files created"
}

main "$@"
