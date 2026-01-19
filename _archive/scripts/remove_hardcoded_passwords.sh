#!/bin/bash
set -e

# Script to remove all hardcoded passwords from documentation
# Replaces production password with environment variable placeholders

# Password pattern to search for (set via environment or use placeholder)
HARDCODED_PASSWORD="${HARDCODED_PASSWORD:-***REDACTED***}"
FILES_MODIFIED=0
TOTAL_REPLACEMENTS=0

# Safety check - don't run if password not set
if [ "$HARDCODED_PASSWORD" = "***REDACTED***" ]; then
    echo "⚠️  WARNING: Using default password pattern"
    echo "To use a different pattern, set HARDCODED_PASSWORD environment variable"
    echo ""
fi

echo "=========================================="
echo "Password Removal Script"
echo "=========================================="
echo ""
echo "Finding files with hardcoded passwords..."
echo ""

# Find all markdown and SQL files with hardcoded password
FILES=$(find docs migrations agents/migrations agents/parallel_execution/migrations agents/lib scripts/observability -type f \( -name "*.md" -o -name "*.sql" \) | xargs grep -l "$HARDCODED_PASSWORD" 2>/dev/null | sort -u || true)

if [ -z "$FILES" ]; then
    echo "✅ No files found with hardcoded passwords!"
    exit 0
fi

FILE_COUNT=$(echo "$FILES" | wc -l | tr -d ' ')
echo "Found $FILE_COUNT files to fix"
echo ""

# Process each file
for file in $FILES; do
    echo "Processing: $file"

    # Count replacements before
    BEFORE_COUNT=$(grep -o "$HARDCODED_PASSWORD" "$file" 2>/dev/null | wc -l | tr -d ' ')

    # Create backup
    cp "$file" "$file.bak"

    # Apply replacements in order (most specific first)

    # 1. PGPASSWORD in bash commands (quoted)
    sed -i '' "s/PGPASSWORD=\"$HARDCODED_PASSWORD\"/PGPASSWORD=\"\${POSTGRES_PASSWORD}\"/g" "$file"

    # 2. PGPASSWORD in bash commands (single quoted)
    sed -i '' "s/PGPASSWORD='$HARDCODED_PASSWORD'/PGPASSWORD=\${POSTGRES_PASSWORD}/g" "$file"

    # 3. export PGPASSWORD
    sed -i '' "s/export PGPASSWORD=$HARDCODED_PASSWORD/export PGPASSWORD=\${POSTGRES_PASSWORD}/g" "$file"

    # 4. Connection strings in postgresql:// URLs
    sed -i '' "s|postgresql://postgres:$HARDCODED_PASSWORD@|postgresql://postgres:\${POSTGRES_PASSWORD}@|g" "$file"

    # 5. Python os.getenv default values
    sed -i '' "s/\"POSTGRES_PASSWORD\", \"$HARDCODED_PASSWORD\"/\"POSTGRES_PASSWORD\"/g" "$file"

    # 6. Python getenv with quotes (single quotes)
    sed -i '' "s/'POSTGRES_PASSWORD', '$HARDCODED_PASSWORD'/'POSTGRES_PASSWORD'/g" "$file"

    # 7. Environment variable assignments
    sed -i '' "s/POSTGRES_PASSWORD=$HARDCODED_PASSWORD/POSTGRES_PASSWORD=<set_in_env>/g" "$file"
    sed -i '' "s/TRACEABILITY_DB_PASSWORD=$HARDCODED_PASSWORD/TRACEABILITY_DB_PASSWORD=<set_in_env>/g" "$file"
    sed -i '' "s/OMNINODE_BRIDGE_POSTGRES_PASSWORD=$HARDCODED_PASSWORD/OMNINODE_BRIDGE_POSTGRES_PASSWORD=<set_in_env>/g" "$file"

    # 8. Database URLs with embedded passwords
    sed -i '' "s|TRACEABILITY_DB_URL=postgresql://postgres:$HARDCODED_PASSWORD@|TRACEABILITY_DB_URL=postgresql://postgres:\${POSTGRES_PASSWORD}@|g" "$file"
    sed -i '' "s|PG_DSN=postgresql://postgres:$HARDCODED_PASSWORD@|PG_DSN=postgresql://postgres:\${POSTGRES_PASSWORD}@|g" "$file"
    sed -i '' "s|DATABASE_URL=postgresql://postgres:$HARDCODED_PASSWORD@|DATABASE_URL=postgresql://postgres:\${POSTGRES_PASSWORD}@|g" "$file"
    sed -i '' "s|HOST_DATABASE_URL=postgresql://postgres:$HARDCODED_PASSWORD@|HOST_DATABASE_URL=postgresql://postgres:\${POSTGRES_PASSWORD}@|g" "$file"

    # 9. Python dictionary password values
    sed -i '' "s/password=\"$HARDCODED_PASSWORD\"/password=os.getenv(\"POSTGRES_PASSWORD\")/g" "$file"
    sed -i '' "s/'password': '$HARDCODED_PASSWORD'/'password': os.getenv('POSTGRES_PASSWORD')/g" "$file"

    # 10. Plain text password mentions in configuration listings
    sed -i '' "s/Password: \`$HARDCODED_PASSWORD\`/Password: \`<set_in_env>\`/g" "$file"
    sed -i '' "s/Password: $HARDCODED_PASSWORD/Password: <set_in_env>/g" "$file"
    sed -i '' "s/- Password: \`$HARDCODED_PASSWORD\`/- Password: \`<set_in_env>\`/g" "$file"

    # 11. --password flags
    sed -i '' "s/--password $HARDCODED_PASSWORD/--password \${POSTGRES_PASSWORD}/g" "$file"

    # Count replacements after
    AFTER_COUNT=$(grep -o "$HARDCODED_PASSWORD" "$file" 2>/dev/null | wc -l | tr -d ' ')
    REPLACEMENTS=$((BEFORE_COUNT - AFTER_COUNT))

    if [ $REPLACEMENTS -gt 0 ]; then
        echo "  ✅ Made $REPLACEMENTS replacements"
        FILES_MODIFIED=$((FILES_MODIFIED + 1))
        TOTAL_REPLACEMENTS=$((TOTAL_REPLACEMENTS + REPLACEMENTS))
        rm "$file.bak"
    else
        echo "  ⚠️  No replacements made (pattern may need updating)"
        mv "$file.bak" "$file"
    fi

    # Check if any passwords remain
    if [ $AFTER_COUNT -gt 0 ]; then
        echo "  ⚠️  WARNING: $AFTER_COUNT instances still remain - manual review needed"
    fi

    echo ""
done

echo "=========================================="
echo "Summary"
echo "=========================================="
echo "Files processed: $FILE_COUNT"
echo "Files modified: $FILES_MODIFIED"
echo "Total replacements: $TOTAL_REPLACEMENTS"
echo ""

# Final verification
REMAINING=$(find docs migrations agents/migrations agents/parallel_execution/migrations agents/lib scripts/observability -type f \( -name "*.md" -o -name "*.sql" \) | xargs grep -l "$HARDCODED_PASSWORD" 2>/dev/null | wc -l | tr -d ' ')

if [ "$REMAINING" -eq 0 ]; then
    echo "✅ SUCCESS: No hardcoded passwords remain in documentation!"
    exit 0
else
    echo "⚠️  WARNING: $REMAINING files still contain hardcoded passwords"
    echo ""
    echo "Files needing manual review:"
    find docs migrations agents/migrations agents/parallel_execution/migrations agents/lib scripts/observability -type f \( -name "*.md" -o -name "*.sql" \) | xargs grep -l "$HARDCODED_PASSWORD" 2>/dev/null || true
    exit 1
fi
