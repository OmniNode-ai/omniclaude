#!/bin/bash
################################################################################
# Pattern System Validation Script
################################################################################
# Purpose: Comprehensive validation of pattern migration results
# Usage: ./scripts/validate_patterns.sh
# Output: Detailed validation report with pass/fail checks
################################################################################

set -e  # Exit on error
set -u  # Exit on undefined variable

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

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo "=========================================="
echo "Pattern Migration Validation"
echo "=========================================="
echo ""
echo "Database: $DB_NAME @ $DB_HOST:$DB_PORT"
echo "Timestamp: $(date '+%Y-%m-%d %H:%M:%S')"
echo ""

# Execute validation SQL
PGPASSWORD="$DB_PASSWORD" psql \
  -h "$DB_HOST" \
  -p "$DB_PORT" \
  -U "$DB_USER" \
  -d "$DB_NAME" \
  --quiet \
<<'EOF'

\pset border 2
\pset format wrapped

\echo ''
\echo '=========================================='
\echo '1. Pattern Count Summary'
\echo '=========================================='
\echo ''

SELECT COUNT(*) as total_patterns
FROM pattern_lineage_nodes;

\echo ''
\echo 'Patterns by type:'
SELECT
  pattern_type,
  COUNT(*) as count,
  ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 2) as percentage
FROM pattern_lineage_nodes
WHERE pattern_type IS NOT NULL
GROUP BY pattern_type
ORDER BY count DESC;

\echo ''
\echo '=========================================='
\echo '2. Quality Score Distribution'
\echo '=========================================='
\echo ''

SELECT
  CASE
    WHEN overall_quality IS NULL THEN 'No quality score'
    WHEN overall_quality >= 0.8 THEN 'High (0.8+)'
    WHEN overall_quality >= 0.6 THEN 'Medium (0.6-0.8)'
    WHEN overall_quality >= 0.4 THEN 'Low (0.4-0.6)'
    ELSE 'Very Low (<0.4)'
  END as quality_tier,
  COUNT(*) as count,
  ROUND(AVG(overall_quality)::numeric, 3) as avg_quality,
  ROUND(MIN(overall_quality)::numeric, 3) as min_quality,
  ROUND(MAX(overall_quality)::numeric, 3) as max_quality
FROM pattern_lineage_nodes
GROUP BY quality_tier
ORDER BY avg_quality DESC NULLS LAST;

\echo ''
\echo '=========================================='
\echo '3. Top 10 Highest Quality Patterns'
\echo '=========================================='
\echo ''

SELECT
  pattern_name,
  pattern_type,
  ROUND(overall_quality::numeric, 3) as quality,
  usage_count,
  array_length(used_by_agents, 1) as agent_count
FROM pattern_lineage_nodes
WHERE overall_quality IS NOT NULL
ORDER BY overall_quality DESC, usage_count DESC
LIMIT 10;

\echo ''
\echo '=========================================='
\echo '4. Most Used Patterns'
\echo '=========================================='
\echo ''

SELECT
  pattern_name,
  usage_count,
  array_length(used_by_agents, 1) as agent_count,
  ROUND(overall_quality::numeric, 3) as quality
FROM pattern_lineage_nodes
WHERE usage_count > 0
ORDER BY usage_count DESC, overall_quality DESC NULLS LAST
LIMIT 10;

\echo ''
\echo '=========================================='
\echo '5. Pattern Relationships Analysis'
\echo '=========================================='
\echo ''

SELECT
  relationship_type,
  COUNT(*) as count,
  ROUND(AVG(confidence)::numeric, 3) as avg_confidence,
  ROUND(MIN(confidence)::numeric, 3) as min_confidence,
  ROUND(MAX(confidence)::numeric, 3) as max_confidence
FROM pattern_relationships
GROUP BY relationship_type
ORDER BY count DESC;

\echo ''
\echo 'Top relationship connections:'
SELECT
  pln1.pattern_name as source_pattern,
  pr.relationship_type,
  pln2.pattern_name as target_pattern,
  ROUND(pr.confidence::numeric, 3) as confidence
FROM pattern_relationships pr
JOIN pattern_lineage_nodes pln1 ON pr.source_pattern_id = pln1.id
JOIN pattern_lineage_nodes pln2 ON pr.target_pattern_id = pln2.id
ORDER BY pr.confidence DESC
LIMIT 10;

\echo ''
\echo '=========================================='
\echo '6. Pattern Lineage (Edges)'
\echo '=========================================='
\echo ''

SELECT
  COUNT(*) as total_edges,
  COUNT(DISTINCT source_id) as unique_sources,
  COUNT(DISTINCT created_by_agent) as unique_agents
FROM pattern_lineage_edges;

\echo ''
\echo 'Lineage by agent:'
SELECT
  created_by_agent,
  COUNT(*) as edge_count
FROM pattern_lineage_edges
GROUP BY created_by_agent
ORDER BY edge_count DESC
LIMIT 10;

\echo ''
\echo '=========================================='
\echo '7. Data Quality Verification Checks'
\echo '=========================================='
\echo ''

-- Check 1: No filenames in patterns
WITH check1 AS (
  SELECT COUNT(*) as violation_count
  FROM pattern_lineage_nodes
  WHERE pattern_name LIKE '%.py'
     OR pattern_name LIKE '%.ts'
     OR pattern_name LIKE '%.js'
     OR pattern_name LIKE '%.sql'
)
SELECT
  'No filenames in pattern names' as check_name,
  violation_count,
  CASE
    WHEN violation_count = 0 THEN '✓ PASS'
    ELSE '✗ FAIL - Found ' || violation_count || ' filename patterns'
  END as status
FROM check1

UNION ALL

-- Check 2: All quality scores in valid range [0,1]
SELECT
  'Quality scores in range [0,1]' as check_name,
  COUNT(*) as violation_count,
  CASE
    WHEN COUNT(*) = 0 THEN '✓ PASS'
    ELSE '✗ FAIL - Found ' || COUNT(*) || ' out of range'
  END as status
FROM pattern_lineage_nodes
WHERE overall_quality < 0 OR overall_quality > 1

UNION ALL

-- Check 3: No null pattern names
SELECT
  'No null pattern names' as check_name,
  COUNT(*) as violation_count,
  CASE
    WHEN COUNT(*) = 0 THEN '✓ PASS'
    ELSE '✗ FAIL - Found ' || COUNT(*) || ' null names'
  END as status
FROM pattern_lineage_nodes
WHERE pattern_name IS NULL OR pattern_name = ''

UNION ALL

-- Check 4: All relationships have valid confidence
SELECT
  'Relationship confidence in range [0,1]' as check_name,
  COUNT(*) as violation_count,
  CASE
    WHEN COUNT(*) = 0 THEN '✓ PASS'
    ELSE '✗ FAIL - Found ' || COUNT(*) || ' invalid confidence'
  END as status
FROM pattern_relationships
WHERE confidence < 0 OR confidence > 1

UNION ALL

-- Check 5: No orphaned relationships
SELECT
  'No orphaned relationships' as check_name,
  COUNT(*) as violation_count,
  CASE
    WHEN COUNT(*) = 0 THEN '✓ PASS'
    ELSE '✗ FAIL - Found ' || COUNT(*) || ' orphaned'
  END as status
FROM pattern_relationships pr
WHERE NOT EXISTS (
  SELECT 1 FROM pattern_lineage_nodes WHERE id = pr.source_pattern_id
) OR NOT EXISTS (
  SELECT 1 FROM pattern_lineage_nodes WHERE id = pr.target_pattern_id
)

UNION ALL

-- Check 6: Patterns have reasonable metadata
SELECT
  'Patterns have metadata fields' as check_name,
  COUNT(*) as violation_count,
  CASE
    WHEN COUNT(*) = 0 THEN '✓ PASS'
    ELSE '⚠ WARNING - ' || COUNT(*) || ' patterns missing metadata'
  END as status
FROM pattern_lineage_nodes
WHERE metadata IS NULL OR metadata = '{}'::jsonb;

\echo ''
\echo '=========================================='
\echo '8. Recent Pattern Activity'
\echo '=========================================='
\echo ''

SELECT
  DATE_TRUNC('day', created_at) as date,
  COUNT(*) as patterns_created
FROM pattern_lineage_nodes
WHERE created_at > NOW() - INTERVAL '7 days'
GROUP BY date
ORDER BY date DESC;

\echo ''
\echo '=========================================='
\echo '9. Pattern Complexity Analysis'
\echo '=========================================='
\echo ''

SELECT
  CASE
    WHEN (metadata->>'complexity')::int IS NULL THEN 'No complexity data'
    WHEN (metadata->>'complexity')::int <= 5 THEN 'Simple (1-5)'
    WHEN (metadata->>'complexity')::int <= 10 THEN 'Moderate (6-10)'
    WHEN (metadata->>'complexity')::int <= 15 THEN 'Complex (11-15)'
    ELSE 'Very Complex (>15)'
  END as complexity_tier,
  COUNT(*) as count
FROM pattern_lineage_nodes
WHERE metadata ? 'complexity'
GROUP BY complexity_tier
ORDER BY
  CASE complexity_tier
    WHEN 'No complexity data' THEN 5
    WHEN 'Simple (1-5)' THEN 1
    WHEN 'Moderate (6-10)' THEN 2
    WHEN 'Complex (11-15)' THEN 3
    WHEN 'Very Complex (>15)' THEN 4
  END;

\echo ''
\echo '=========================================='
\echo '10. Validation Summary'
\echo '=========================================='
\echo ''

WITH summary AS (
  SELECT
    COUNT(*) as total_patterns,
    COUNT(*) FILTER (WHERE overall_quality >= 0.6) as high_quality_patterns,
    COUNT(*) FILTER (WHERE overall_quality IS NOT NULL) as patterns_with_quality,
    COUNT(*) FILTER (WHERE usage_count > 0) as used_patterns,
    COUNT(*) FILTER (
      WHERE pattern_name LIKE '%.py'
         OR pattern_name LIKE '%.ts'
         OR pattern_name LIKE '%.js'
    ) as filename_patterns,
    (SELECT COUNT(*) FROM pattern_relationships) as total_relationships,
    (SELECT COUNT(*) FROM pattern_lineage_edges) as total_edges
  FROM pattern_lineage_nodes
)
SELECT
  'Total Patterns: ' || total_patterns as metric,
  CASE
    WHEN total_patterns >= 200 THEN '✓ Good'
    WHEN total_patterns >= 50 THEN '⚠ Low'
    ELSE '✗ Very Low'
  END as status
FROM summary
UNION ALL
SELECT
  'High Quality (≥0.6): ' || high_quality_patterns || ' (' ||
    ROUND(100.0 * high_quality_patterns / NULLIF(patterns_with_quality, 0), 1) || '%)',
  CASE
    WHEN high_quality_patterns::float / NULLIF(patterns_with_quality, 0) >= 0.6 THEN '✓ Good'
    WHEN high_quality_patterns::float / NULLIF(patterns_with_quality, 0) >= 0.4 THEN '⚠ Moderate'
    ELSE '✗ Low'
  END
FROM summary
UNION ALL
SELECT
  'Patterns With Usage: ' || used_patterns,
  CASE
    WHEN used_patterns > 0 THEN '✓ Good'
    ELSE '⚠ No usage data'
  END
FROM summary
UNION ALL
SELECT
  'Filename Patterns: ' || filename_patterns,
  CASE
    WHEN filename_patterns = 0 THEN '✓ Clean'
    ELSE '✗ Cleanup needed'
  END
FROM summary
UNION ALL
SELECT
  'Relationships: ' || total_relationships,
  CASE
    WHEN total_relationships > 0 THEN '✓ Present'
    ELSE '⚠ No relationships'
  END
FROM summary
UNION ALL
SELECT
  'Lineage Edges: ' || total_edges,
  CASE
    WHEN total_edges > 0 THEN '✓ Present'
    ELSE '⚠ No lineage'
  END
FROM summary;

\echo ''
\echo '=========================================='
\echo 'Validation Complete'
\echo '=========================================='
\echo ''

EOF

# Exit code based on validation
# For now, always exit 0 (script displays results, user interprets)
exit 0
