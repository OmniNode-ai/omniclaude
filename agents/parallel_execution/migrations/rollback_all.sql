-- Rollback Script: rollback_all.sql
-- Description: Rollback all agent observability migrations in reverse order
-- Author: agent-workflow-coordinator
-- Created: 2025-10-09
-- Usage: psql -h localhost -p 5436 -U postgres -d omninode_bridge -f rollback_all.sql

-- =============================================================================
-- ROLLBACK ALL MIGRATIONS (REVERSE ORDER)
-- =============================================================================

-- Rollback 003: router_performance_metrics
DROP TABLE IF EXISTS router_performance_metrics CASCADE;

-- Rollback 002: agent_transformation_events
DROP TABLE IF EXISTS agent_transformation_events CASCADE;

-- Rollback 001: agent_definitions
DROP TRIGGER IF EXISTS trigger_agent_definitions_updated_at ON agent_definitions;
DROP FUNCTION IF EXISTS update_agent_definitions_timestamp();
DROP TABLE IF EXISTS agent_definitions CASCADE;

-- Verify rollback
SELECT 'Rollback complete. All agent observability tables dropped.' AS status;
