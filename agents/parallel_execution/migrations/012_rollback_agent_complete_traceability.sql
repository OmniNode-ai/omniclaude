-- Migration Rollback: 012_agent_complete_traceability
-- Description: Rollback complete traceability schema
-- Author: agent-observability
-- Created: 2025-10-29

-- =============================================================================
-- DOWN MIGRATION (ROLLBACK)
-- =============================================================================

-- Drop utility functions
DROP FUNCTION IF EXISTS calculate_content_hash(TEXT);
DROP FUNCTION IF EXISTS get_complete_trace(UUID);

-- Drop views
DROP VIEW IF EXISTS v_agent_traceability_summary;
DROP VIEW IF EXISTS v_intelligence_effectiveness;
DROP VIEW IF EXISTS v_file_operation_history;
DROP VIEW IF EXISTS v_complete_execution_trace;

-- Drop tables (CASCADE removes dependent objects)
DROP TABLE IF EXISTS agent_intelligence_usage CASCADE;
DROP TABLE IF EXISTS agent_file_operations CASCADE;
DROP TABLE IF EXISTS agent_prompts CASCADE;

-- Success message
DO $$
BEGIN
    RAISE NOTICE '✅ Migration 012 rollback: Complete traceability schema removed';
    RAISE NOTICE '   - Dropped 3 tables: agent_prompts, agent_file_operations, agent_intelligence_usage';
    RAISE NOTICE '   - Dropped 4 views: v_complete_execution_trace, v_file_operation_history, v_intelligence_effectiveness, v_agent_traceability_summary';
    RAISE NOTICE '   - Dropped 2 functions: get_complete_trace, calculate_content_hash';
END $$;
