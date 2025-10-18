#!/bin/bash
# Phase 4 Database Validation Script
#
# Validates that Phase 4 pattern data is correctly stored in the database.
# Checks pattern_lineage_nodes, pattern_analytics, and pattern_feedback tables.

set -e

echo "======================================================================="
echo "Phase 4 Pattern Traceability - Database Validation"
echo "======================================================================="
echo ""

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Database connection info (adjust as needed)
DB_HOST="${DB_HOST:-localhost}"
DB_PORT="${DB_PORT:-5436}"
DB_NAME="${DB_NAME:-omninode_bridge}"
DB_USER="${DB_USER:-postgres}"
DB_PASSWORD="${DB_PASSWORD:-}"

echo "Database Configuration:"
echo "  Host: $DB_HOST"
echo "  Port: $DB_PORT"
echo "  Database: $DB_NAME"
echo "  User: $DB_USER"
echo ""

# Check if psql is available
if ! command -v psql &> /dev/null; then
    echo -e "${RED}✗ psql not found${NC}"
    echo "  Please install PostgreSQL client tools"
    exit 1
fi

# Test database connection
echo "Testing database connection..."
if PGPASSWORD=$DB_PASSWORD psql -h $DB_HOST -p $DB_PORT -U $DB_USER -d $DB_NAME -c "SELECT 1;" > /dev/null 2>&1; then
    echo -e "${GREEN}✓ Database connection successful${NC}"
else
    echo -e "${RED}✗ Database connection failed${NC}"
    echo "  Check that PostgreSQL is running and credentials are correct"
    exit 1
fi

echo ""
echo "-----------------------------------------------------------------------"
echo "1. Checking pattern_lineage_nodes table..."
echo "-----------------------------------------------------------------------"

# Check if table exists
if PGPASSWORD=$DB_PASSWORD psql -h $DB_HOST -p $DB_PORT -U $DB_USER -d $DB_NAME \
    -c "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'pattern_lineage_nodes');" \
    | grep -q "t"; then
    echo -e "${GREEN}✓ pattern_lineage_nodes table exists${NC}"
    
    # Get row count
    ROW_COUNT=$(PGPASSWORD=$DB_PASSWORD psql -h $DB_HOST -p $DB_PORT -U $DB_USER -d $DB_NAME \
        -t -c "SELECT COUNT(*) FROM pattern_lineage_nodes;")
    
    echo "  Total patterns: $ROW_COUNT"
    
    if [ "$ROW_COUNT" -gt 0 ]; then
        echo ""
        echo "Sample pattern data (last 5):"
        PGPASSWORD=$DB_PASSWORD psql -h $DB_HOST -p $DB_PORT -U $DB_USER -d $DB_NAME \
            -c "SELECT pattern_id, pattern_name, pattern_type, created_at FROM pattern_lineage_nodes ORDER BY created_at DESC LIMIT 5;" \
            2>/dev/null || echo "  (Unable to retrieve sample data)"
    else
        echo -e "${YELLOW}  ⚠ No pattern data found${NC}"
    fi
else
    echo -e "${RED}✗ pattern_lineage_nodes table not found${NC}"
fi

echo ""
echo "-----------------------------------------------------------------------"
echo "2. Checking pattern_analytics table..."
echo "-----------------------------------------------------------------------"

# Check if table exists
if PGPASSWORD=$DB_PASSWORD psql -h $DB_HOST -p $DB_PORT -U $DB_USER -d $DB_NAME \
    -c "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'pattern_analytics');" \
    | grep -q "t"; then
    echo -e "${GREEN}✓ pattern_analytics table exists${NC}"
    
    # Get row count
    ROW_COUNT=$(PGPASSWORD=$DB_PASSWORD psql -h $DB_HOST -p $DB_PORT -U $DB_USER -d $DB_NAME \
        -t -c "SELECT COUNT(*) FROM pattern_analytics;")
    
    echo "  Total analytics records: $ROW_COUNT"
    
    if [ "$ROW_COUNT" -gt 0 ]; then
        echo ""
        echo "Sample analytics data (last 5):"
        PGPASSWORD=$DB_PASSWORD psql -h $DB_HOST -p $DB_PORT -U $DB_USER -d $DB_NAME \
            -c "SELECT pattern_id, execution_count, avg_quality_score, created_at FROM pattern_analytics ORDER BY created_at DESC LIMIT 5;" \
            2>/dev/null || echo "  (Unable to retrieve sample data)"
    else
        echo -e "${YELLOW}  ⚠ No analytics data found${NC}"
    fi
else
    echo -e "${YELLOW}✗ pattern_analytics table not found (may not be created yet)${NC}"
fi

echo ""
echo "-----------------------------------------------------------------------"
echo "3. Checking pattern_feedback table..."
echo "-----------------------------------------------------------------------"

# Check if table exists
if PGPASSWORD=$DB_PASSWORD psql -h $DB_HOST -p $DB_PORT -U $DB_USER -d $DB_NAME \
    -c "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'pattern_feedback');" \
    | grep -q "t"; then
    echo -e "${GREEN}✓ pattern_feedback table exists${NC}"
    
    # Get row count
    ROW_COUNT=$(PGPASSWORD=$DB_PASSWORD psql -h $DB_HOST -p $DB_PORT -U $DB_USER -d $DB_NAME \
        -t -c "SELECT COUNT(*) FROM pattern_feedback;")
    
    echo "  Total feedback records: $ROW_COUNT"
    
    if [ "$ROW_COUNT" -gt 0 ]; then
        echo ""
        echo "Sample feedback data (last 5):"
        PGPASSWORD=$DB_PASSWORD psql -h $DB_HOST -p $DB_PORT -U $DB_USER -d $DB_NAME \
            -c "SELECT pattern_id, feedback_type, created_at FROM pattern_feedback ORDER BY created_at DESC LIMIT 5;" \
            2>/dev/null || echo "  (Unable to retrieve sample data)"
    else
        echo -e "${YELLOW}  ⚠ No feedback data found${NC}"
    fi
else
    echo -e "${YELLOW}✗ pattern_feedback table not found (may not be created yet)${NC}"
fi

echo ""
echo "-----------------------------------------------------------------------"
echo "4. Checking pattern lineage relationships..."
echo "-----------------------------------------------------------------------"

# Check for patterns with parents (derived patterns)
DERIVED_COUNT=$(PGPASSWORD=$DB_PASSWORD psql -h $DB_HOST -p $DB_PORT -U $DB_USER -d $DB_NAME \
    -t -c "SELECT COUNT(*) FROM pattern_lineage_nodes WHERE parent_ids IS NOT NULL AND array_length(parent_ids, 1) > 0;" \
    2>/dev/null || echo "0")

echo "  Patterns with parent relationships: $DERIVED_COUNT"

if [ "$DERIVED_COUNT" -gt 0 ]; then
    echo -e "${GREEN}✓ Lineage relationships found${NC}"
else
    echo -e "${YELLOW}  ⚠ No lineage relationships found (patterns are independent)${NC}"
fi

echo ""
echo "======================================================================="
echo "Database Validation Complete"
echo "======================================================================="
echo ""
echo "Summary:"
echo "  • Database connection: ✓"
echo "  • Pattern storage: $([ "$ROW_COUNT" -gt 0 ] && echo '✓' || echo '⚠')"
echo "  • Analytics data: $(PGPASSWORD=$DB_PASSWORD psql -h $DB_HOST -p $DB_PORT -U $DB_USER -d $DB_NAME -t -c 'SELECT CASE WHEN EXISTS (SELECT 1 FROM pattern_analytics LIMIT 1) THEN '\''✓'\'' ELSE '\''⚠'\'' END;' 2>/dev/null || echo '⚠')"
echo "  • Lineage tracking: $([ "$DERIVED_COUNT" -gt 0 ] && echo '✓' || echo '⚠')"
echo ""
