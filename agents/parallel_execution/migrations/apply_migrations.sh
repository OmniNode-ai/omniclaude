#!/bin/bash
# Migration Runner Script
# Author: agent-workflow-coordinator
# Created: 2025-10-09

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Database configuration
# Note: Set DB_PASSWORD environment variable for database access
DB_HOST="${DB_HOST:-localhost}"
DB_PORT="${DB_PORT:-5436}"
DB_NAME="${DB_NAME:-omninode_bridge}"
DB_USER="${DB_USER:-postgres}"
DB_PASSWORD="${DB_PASSWORD}"

# Migration directory
MIGRATIONS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo -e "${BLUE}╔══════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║  Agent Observability Framework - Migration Runner       ║${NC}"
echo -e "${BLUE}╚══════════════════════════════════════════════════════════╝${NC}"
echo ""

# Function to run SQL file
run_migration() {
    local migration_file="$1"
    local migration_name=$(basename "$migration_file" .sql)

    echo -e "${YELLOW}→${NC} Applying migration: ${GREEN}${migration_name}${NC}"

    if PGPASSWORD="$DB_PASSWORD" psql \
        -h "$DB_HOST" \
        -p "$DB_PORT" \
        -U "$DB_USER" \
        -d "$DB_NAME" \
        -f "$migration_file" \
        --quiet \
        --single-transaction; then
        echo -e "${GREEN}✓${NC} Migration ${GREEN}${migration_name}${NC} applied successfully"
        return 0
    else
        echo -e "${RED}✗${NC} Migration ${RED}${migration_name}${NC} failed!"
        return 1
    fi
}

# Function to verify connection
verify_connection() {
    echo -e "${YELLOW}→${NC} Verifying database connection..."

    if PGPASSWORD="$DB_PASSWORD" psql \
        -h "$DB_HOST" \
        -p "$DB_PORT" \
        -U "$DB_USER" \
        -d "$DB_NAME" \
        -c "SELECT version();" \
        --quiet \
        --tuples-only > /dev/null 2>&1; then
        echo -e "${GREEN}✓${NC} Database connection verified"
        return 0
    else
        echo -e "${RED}✗${NC} Cannot connect to database!"
        echo -e "${RED}  Host: ${DB_HOST}:${DB_PORT}${NC}"
        echo -e "${RED}  Database: ${DB_NAME}${NC}"
        echo -e "${RED}  User: ${DB_USER}${NC}"
        return 1
    fi
}

# Function to check if tables exist
check_existing_tables() {
    echo -e "${YELLOW}→${NC} Checking for existing tables..."

    local tables=$(PGPASSWORD="$DB_PASSWORD" psql \
        -h "$DB_HOST" \
        -p "$DB_PORT" \
        -U "$DB_USER" \
        -d "$DB_NAME" \
        -t -c "SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename IN ('agent_definitions', 'agent_transformation_events', 'router_performance_metrics');" \
        | tr -d ' ')

    if [ -n "$tables" ]; then
        echo -e "${YELLOW}⚠${NC}  Found existing tables: ${tables}"
        echo -e "${YELLOW}⚠${NC}  These will be modified by migrations"
        return 1
    else
        echo -e "${GREEN}✓${NC} No existing tables found"
        return 0
    fi
}

# Main execution
main() {
    echo -e "${BLUE}Configuration:${NC}"
    echo -e "  Host:     ${DB_HOST}:${DB_PORT}"
    echo -e "  Database: ${DB_NAME}"
    echo -e "  User:     ${DB_USER}"
    echo ""

    # Verify connection
    if ! verify_connection; then
        echo -e "${RED}Migration aborted due to connection failure${NC}"
        exit 1
    fi

    # Check existing tables
    check_existing_tables || true
    echo ""

    # Apply migrations in order
    echo -e "${BLUE}Applying migrations:${NC}"
    echo ""

    local migration_count=0
    local failed_count=0

    for migration_file in "$MIGRATIONS_DIR"/[0-9][0-9][0-9]_*.sql; do
        if [ -f "$migration_file" ]; then
            if run_migration "$migration_file"; then
                ((migration_count++))
            else
                ((failed_count++))
                echo -e "${RED}Aborting further migrations due to failure${NC}"
                exit 1
            fi
            echo ""
        fi
    done

    # Summary
    echo -e "${BLUE}╔══════════════════════════════════════════════════════════╗${NC}"
    echo -e "${BLUE}║  Migration Summary                                       ║${NC}"
    echo -e "${BLUE}╚══════════════════════════════════════════════════════════╝${NC}"
    echo -e "${GREEN}✓${NC} Migrations applied: ${migration_count}"
    echo -e "${RED}✗${NC} Migrations failed:  ${failed_count}"

    if [ $failed_count -eq 0 ]; then
        echo -e "${GREEN}All migrations completed successfully!${NC}"

        # Display table info
        echo ""
        echo -e "${BLUE}Created tables:${NC}"
        PGPASSWORD="$DB_PASSWORD" psql \
            -h "$DB_HOST" \
            -p "$DB_PORT" \
            -U "$DB_USER" \
            -d "$DB_NAME" \
            -c "SELECT
                    schemaname,
                    tablename,
                    pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) as size
                FROM pg_tables
                WHERE schemaname='public'
                AND tablename IN ('agent_definitions', 'agent_transformation_events', 'router_performance_metrics')
                ORDER BY tablename;"

        return 0
    else
        echo -e "${RED}Some migrations failed. Check logs above.${NC}"
        return 1
    fi
}

# Run main function
main
