#!/bin/bash

# Password Alias Migration Script
# Migrates deprecated password aliases to POSTGRES_PASSWORD standard

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Detect OS for sed compatibility
if [[ "$OSTYPE" == "darwin"* ]]; then
    SED_INPLACE="sed -i ''"
else
    SED_INPLACE="sed -i"
fi

echo -e "${YELLOW}Starting password alias migration...${NC}"
echo ""

# Discover files containing deprecated aliases dynamically
echo -e "${YELLOW}Discovering files with deprecated password aliases...${NC}"
FILES=()

# Check if fd is available, otherwise use find
if command -v fd &> /dev/null; then
    # Use fd for faster file discovery
    while IFS= read -r file; do
        FILES+=("$file")
    done < <(fd -e sh -e py --type f | xargs grep -l 'DB_PASSWORD\|DATABASE_PASSWORD\|TRACEABILITY_DB_PASSWORD' 2>/dev/null || true)
else
    # Fallback to find
    while IFS= read -r file; do
        FILES+=("$file")
    done < <(find . -type f \( -name "*.sh" -o -name "*.py" \) | xargs grep -l 'DB_PASSWORD\|DATABASE_PASSWORD\|TRACEABILITY_DB_PASSWORD' 2>/dev/null || true)
fi

if [ ${#FILES[@]} -eq 0 ]; then
    echo -e "${GREEN}✓ No files found containing deprecated aliases${NC}"
    exit 0
fi

echo -e "${YELLOW}Found ${#FILES[@]} files to migrate:${NC}"
for file in "${FILES[@]}"; do
    echo "  - $file"
done
echo ""

MIGRATED=0
SKIPPED=0

for file in "${FILES[@]}"; do
    echo -e "${YELLOW}Migrating: $file${NC}"

    # Create backup
    cp "$file" "$file.bak"

    # Perform replacements
    # 1. Replace $DB_PASSWORD with $POSTGRES_PASSWORD
    $SED_INPLACE 's/\$DB_PASSWORD/\$POSTGRES_PASSWORD/g' "$file"
    $SED_INPLACE 's/\${DB_PASSWORD}/\${POSTGRES_PASSWORD}/g' "$file"

    # 2. Replace $DATABASE_PASSWORD with $POSTGRES_PASSWORD
    $SED_INPLACE 's/\$DATABASE_PASSWORD/\$POSTGRES_PASSWORD/g' "$file"
    $SED_INPLACE 's/\${DATABASE_PASSWORD}/\${POSTGRES_PASSWORD}/g' "$file"

    # 3. Replace $TRACEABILITY_DB_PASSWORD with $POSTGRES_PASSWORD
    $SED_INPLACE 's/\$TRACEABILITY_DB_PASSWORD/\$POSTGRES_PASSWORD/g' "$file"
    $SED_INPLACE 's/\${TRACEABILITY_DB_PASSWORD}/\${POSTGRES_PASSWORD}/g' "$file"

    # 4. Replace DB_PASSWORD= assignments
    $SED_INPLACE 's/^DB_PASSWORD="${POSTGRES_PASSWORD}"$/# Note: Using POSTGRES_PASSWORD directly (no alias)/g' "$file"
    $SED_INPLACE 's/^export DB_PASSWORD="${DB_PASSWORD:-.*}"$/# Note: Using POSTGRES_PASSWORD directly (no alias)/g' "$file"

    # 5. Update comments
    $SED_INPLACE 's/Set DB_PASSWORD environment variable/Set POSTGRES_PASSWORD environment variable/g' "$file"
    $SED_INPLACE 's/DB_PASSWORD for database/POSTGRES_PASSWORD for database/g' "$file"
    $SED_INPLACE 's/Ensure .env file is set up with DB_PASSWORD/Ensure .env file is set up with POSTGRES_PASSWORD/g' "$file"

    # 6. Update validation messages
    $SED_INPLACE 's/missing_vars+=("DB_PASSWORD")/missing_vars+=("POSTGRES_PASSWORD")/g' "$file"

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
