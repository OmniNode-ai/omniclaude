#!/bin/bash

# Password Alias Migration Script
# Migrates deprecated password aliases to POSTGRES_PASSWORD standard

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${YELLOW}Starting password alias migration...${NC}"
echo ""

# Files to migrate
FILES=(
    "agents/migrations/test_004_migration.sh"
    "agents/parallel_execution/migrations/apply_migrations.sh"
    "claude_hooks/post-tool-use-quality.sh"
    "claude_hooks/pre-tool-use-quality.sh"
    "claude_hooks/services/run_processor.sh"
    "claude_hooks/setup-symlinks.sh"
    "claude_hooks/tests/validate_database.sh"
    "claude_hooks/user-prompt-submit.sh"
    "claude_hooks/validate_monitoring_indexes.sh"
    "deployment/scripts/start-routing-adapter.sh"
    "scripts/apply_migration.sh"
    "scripts/dump_omninode_db.sh"
    "scripts/observability/monitor_routing_health.sh"
    "scripts/reingest_patterns.sh"
    "scripts/rollback_patterns.sh"
    "scripts/validate_patterns.sh"
)

MIGRATED=0
SKIPPED=0

for file in "${FILES[@]}"; do
    if [ ! -f "$file" ]; then
        echo -e "${YELLOW}⚠️  Skipping (not found): $file${NC}"
        ((SKIPPED++))
        continue
    fi

    # Check if file contains aliases
    if ! grep -q 'DB_PASSWORD\|DATABASE_PASSWORD\|TRACEABILITY_DB_PASSWORD' "$file"; then
        echo -e "${GREEN}✓ Already migrated: $file${NC}"
        ((SKIPPED++))
        continue
    fi

    echo -e "${YELLOW}Migrating: $file${NC}"

    # Create backup
    cp "$file" "$file.bak"

    # Perform replacements
    # 1. Replace $DB_PASSWORD with $POSTGRES_PASSWORD
    sed -i '' 's/\$DB_PASSWORD/\$POSTGRES_PASSWORD/g' "$file"
    sed -i '' 's/\${DB_PASSWORD}/\${POSTGRES_PASSWORD}/g' "$file"

    # 2. Replace $DATABASE_PASSWORD with $POSTGRES_PASSWORD
    sed -i '' 's/\$DATABASE_PASSWORD/\$POSTGRES_PASSWORD/g' "$file"
    sed -i '' 's/\${DATABASE_PASSWORD}/\${POSTGRES_PASSWORD}/g' "$file"

    # 3. Replace $TRACEABILITY_DB_PASSWORD with $POSTGRES_PASSWORD
    sed -i '' 's/\$TRACEABILITY_DB_PASSWORD/\$POSTGRES_PASSWORD/g' "$file"
    sed -i '' 's/\${TRACEABILITY_DB_PASSWORD}/\${POSTGRES_PASSWORD}/g' "$file"

    # 4. Replace DB_PASSWORD= assignments
    sed -i '' 's/^DB_PASSWORD="${POSTGRES_PASSWORD}"$/# Note: Using POSTGRES_PASSWORD directly (no alias)/g' "$file"
    sed -i '' 's/^export DB_PASSWORD="${DB_PASSWORD:-.*}"$/# Note: Using POSTGRES_PASSWORD directly (no alias)/g' "$file"

    # 5. Update comments
    sed -i '' 's/Set DB_PASSWORD environment variable/Set POSTGRES_PASSWORD environment variable/g' "$file"
    sed -i '' 's/DB_PASSWORD for database/POSTGRES_PASSWORD for database/g' "$file"
    sed -i '' 's/Ensure .env file is set up with DB_PASSWORD/Ensure .env file is set up with POSTGRES_PASSWORD/g' "$file"

    # 6. Update validation messages
    sed -i '' 's/missing_vars+=("DB_PASSWORD")/missing_vars+=("POSTGRES_PASSWORD")/g' "$file"

    # Verify migration worked
    if grep -q 'DB_PASSWORD\|DATABASE_PASSWORD\|TRACEABILITY_DB_PASSWORD' "$file"; then
        # Check if remaining occurrences are in comments or strings only
        if grep -v '^[[:space:]]*#' "$file" | grep -q 'DB_PASSWORD\|DATABASE_PASSWORD\|TRACEABILITY_DB_PASSWORD'; then
            echo -e "${YELLOW}   ⚠️  Manual review required (some aliases remain)${NC}"
        else
            echo -e "${GREEN}   ✓ Migrated successfully (only comments contain aliases)${NC}"
        fi
    else
        echo -e "${GREEN}   ✓ Migrated successfully (all aliases removed)${NC}"
    fi

    ((MIGRATED++))
done

echo ""
echo -e "${GREEN}===========================================${NC}"
echo -e "${GREEN}Migration Summary:${NC}"
echo -e "${GREEN}  Migrated: $MIGRATED files${NC}"
echo -e "${YELLOW}  Skipped: $SKIPPED files${NC}"
echo -e "${GREEN}===========================================${NC}"
echo ""
echo -e "${YELLOW}Backup files created with .bak extension${NC}"
echo -e "${YELLOW}Review changes and remove backups if satisfied:${NC}"
echo -e "  find . -name '*.bak' -delete"
