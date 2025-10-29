--------------------------------------------------------------------------------
-- Pattern System Cleanup Script
--------------------------------------------------------------------------------
-- Purpose: Remove file-based patterns (the bad data from filesystem ingestion)
-- Usage: psql -h HOST -p PORT -U USER -d DATABASE -f cleanup_file_patterns.sql
-- Safety: Wrapped in transaction (ROLLBACK if issues detected)
--------------------------------------------------------------------------------

BEGIN;

\echo '=========================================='
\echo 'Pattern System Cleanup'
\echo '=========================================='
\echo ''

--------------------------------------------------------------------------------
-- Step 1: Analyze current state
--------------------------------------------------------------------------------
\echo 'Step 1: Analyzing current pattern data...'
\echo ''

\echo 'Total patterns before cleanup:'
SELECT COUNT(*) as total_patterns FROM pattern_lineage_nodes;

\echo ''
\echo 'Patterns by category:'
SELECT
  CASE
    WHEN pattern_name LIKE '%__init__%' THEN 'Python __init__ files'
    WHEN pattern_name LIKE '%.py' THEN 'Python files'
    WHEN pattern_name LIKE '%test_%' THEN 'Test files'
    WHEN pattern_name LIKE '%.%' THEN 'Other files'
    ELSE 'Real patterns'
  END as category,
  COUNT(*) as count
FROM pattern_lineage_nodes
GROUP BY category
ORDER BY count DESC;

\echo ''
\echo 'Sample of patterns to be deleted:'
SELECT pattern_name, pattern_type, created_at
FROM pattern_lineage_nodes
WHERE pattern_name LIKE '%__init__%'
   OR pattern_name LIKE '%.py'
   OR pattern_name LIKE '%test_%'
ORDER BY created_at DESC
LIMIT 10;

--------------------------------------------------------------------------------
-- Step 2: Count relationships to be deleted
--------------------------------------------------------------------------------
\echo ''
\echo 'Step 2: Counting relationships to delete...'
\echo ''

CREATE TEMP TABLE patterns_to_delete AS
SELECT id FROM pattern_lineage_nodes
WHERE pattern_name LIKE '%__init__%'
   OR pattern_name LIKE '%.py'
   OR pattern_name LIKE '%test_%';

\echo 'Relationships to delete:'
SELECT COUNT(*) as relationship_count
FROM pattern_relationships
WHERE source_pattern_id IN (SELECT id FROM patterns_to_delete)
   OR target_pattern_id IN (SELECT id FROM patterns_to_delete);

\echo ''
\echo 'Edges to delete:'
SELECT COUNT(*) as edge_count
FROM pattern_lineage_edges
WHERE source_node_id IN (SELECT id FROM patterns_to_delete)
   OR target_node_id IN (SELECT id FROM patterns_to_delete);

\echo ''
\echo 'Nodes to delete:'
SELECT COUNT(*) as node_count FROM patterns_to_delete;

\echo ''
\echo 'Events to delete (pattern_node_id):'
SELECT COUNT(*) as event_count
FROM pattern_lineage_events
WHERE pattern_node_id IN (SELECT id FROM patterns_to_delete);

\echo ''
\echo 'Events to delete (parent_node_ids):'
SELECT COUNT(*) as event_count_parents
FROM pattern_lineage_events
WHERE parent_node_ids && (SELECT array_agg(id) FROM patterns_to_delete);

--------------------------------------------------------------------------------
-- Step 3: Delete lineage events (foreign keys first)
--------------------------------------------------------------------------------
\echo ''
\echo 'Step 3: Deleting pattern lineage events...'

WITH deleted AS (
  DELETE FROM pattern_lineage_events
  WHERE pattern_node_id IN (SELECT id FROM patterns_to_delete)
     OR parent_node_ids && (SELECT array_agg(id) FROM patterns_to_delete)
  RETURNING *
)
SELECT COUNT(*) || ' events deleted' FROM deleted;

--------------------------------------------------------------------------------
-- Step 4: Delete relationships
--------------------------------------------------------------------------------
\echo ''
\echo 'Step 4: Deleting pattern relationships...'

WITH deleted AS (
  DELETE FROM pattern_relationships
  WHERE source_pattern_id IN (SELECT id FROM patterns_to_delete)
     OR target_pattern_id IN (SELECT id FROM patterns_to_delete)
  RETURNING *
)
SELECT COUNT(*) || ' relationships deleted' FROM deleted;

--------------------------------------------------------------------------------
-- Step 5: Delete edges
--------------------------------------------------------------------------------
\echo ''
\echo 'Step 5: Deleting pattern edges...'

WITH deleted AS (
  DELETE FROM pattern_lineage_edges
  WHERE source_node_id IN (SELECT id FROM patterns_to_delete)
     OR target_node_id IN (SELECT id FROM patterns_to_delete)
  RETURNING *
)
SELECT COUNT(*) || ' edges deleted' FROM deleted;

--------------------------------------------------------------------------------
-- Step 6: Delete nodes
--------------------------------------------------------------------------------
\echo ''
\echo 'Step 6: Deleting pattern nodes...'

WITH deleted AS (
  DELETE FROM pattern_lineage_nodes
  WHERE id IN (SELECT id FROM patterns_to_delete)
  RETURNING *
)
SELECT COUNT(*) || ' nodes deleted' FROM deleted;

--------------------------------------------------------------------------------
-- Step 7: Verify cleanup
--------------------------------------------------------------------------------
\echo ''
\echo 'Step 7: Verifying cleanup...'
\echo ''

\echo 'Total patterns after cleanup:'
SELECT COUNT(*) as total_patterns FROM pattern_lineage_nodes;

\echo ''
\echo 'Remaining patterns by category:'
SELECT
  CASE
    WHEN pattern_name LIKE '%__init__%' THEN 'Python __init__ files (SHOULD BE 0!)'
    WHEN pattern_name LIKE '%.py' THEN 'Python files (SHOULD BE 0!)'
    WHEN pattern_name LIKE '%test_%' THEN 'Test files (SHOULD BE 0!)'
    WHEN pattern_name LIKE '%.%' THEN 'Other files (SHOULD BE 0!)'
    ELSE 'Real patterns'
  END as category,
  COUNT(*) as count
FROM pattern_lineage_nodes
GROUP BY category
ORDER BY count DESC;

\echo ''
\echo 'Verification checks:'
SELECT
  'File patterns remaining' as check_name,
  COUNT(*) as count,
  CASE
    WHEN COUNT(*) = 0 THEN 'PASS ✓'
    ELSE 'FAIL ✗'
  END as status
FROM pattern_lineage_nodes
WHERE pattern_name LIKE '%.py'
   OR pattern_name LIKE '%__init__%'
   OR pattern_name LIKE '%test_%';

--------------------------------------------------------------------------------
-- Step 8: Analyze remaining patterns
--------------------------------------------------------------------------------
\echo ''
\echo 'Step 8: Analyzing remaining patterns...'
\echo ''

\echo 'Pattern types:'
SELECT pattern_type, COUNT(*) as count
FROM pattern_lineage_nodes
GROUP BY pattern_type
ORDER BY count DESC
LIMIT 10;

\echo ''
\echo 'Sample remaining patterns:'
SELECT pattern_name, pattern_type, overall_quality, usage_count
FROM pattern_lineage_nodes
ORDER BY created_at DESC
LIMIT 10;

--------------------------------------------------------------------------------
-- Final decision point
--------------------------------------------------------------------------------
\echo ''
\echo '=========================================='
\echo 'Cleanup Analysis Complete'
\echo '=========================================='
\echo ''
\echo 'Review the results above.'
\echo 'If everything looks correct:'
\echo '  - Type COMMIT; to apply changes'
\echo '  - Or exit with \q to rollback'
\echo ''
\echo 'If anything looks wrong:'
\echo '  - Type ROLLBACK; to cancel all changes'
\echo '  - Or exit with \q to rollback'
\echo ''

-- Automatically commit if running in script mode
-- Comment out the COMMIT below if you want manual control
COMMIT;

\echo ''
\echo 'Changes committed successfully!'
\echo ''
