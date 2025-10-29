-- Migration: 012_agent_complete_traceability
-- Description: Complete traceability for agent operations (prompts, files, intelligence)
-- Author: agent-observability
-- Created: 2025-10-29
-- ONEX Compliance: Effect node pattern for comprehensive observability
-- Correlation ID: accac9a8-a8b8-4793-9dda-6d5ccfceee9f
--
-- Purpose: Capture EVERYTHING an agent does for full execution replay
-- Components:
--   1. agent_prompts - User prompts + agent instructions
--   2. agent_file_operations - File read/write tracking with hashes
--   3. agent_intelligence_usage - Pattern/schema usage tracking
--
-- Integration Points:
--   - Links to agent_execution_logs via correlation_id
--   - Links to agent_manifest_injections for intelligence context
--   - Links to Archon intelligence DB via file_ids and pattern_ids

-- =============================================================================
-- UP MIGRATION
-- =============================================================================

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto"; -- For SHA-256 hashing

-- -------------------------------------------------------------------------
-- Table: agent_prompts
-- Purpose: Store user prompts and agent instructions for full context replay
-- -------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS agent_prompts (
    -- Primary key
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Correlation and tracing
    correlation_id UUID NOT NULL, -- Links to execution logs
    session_id UUID, -- Links prompts in a conversation
    execution_id UUID, -- Links to agent_execution_logs.execution_id

    -- Agent context
    agent_name VARCHAR(255) NOT NULL,
    agent_version VARCHAR(50) DEFAULT '1.0.0',

    -- Prompt capture
    user_prompt TEXT NOT NULL, -- Original user request
    user_prompt_hash VARCHAR(64) NOT NULL, -- SHA-256 hash for deduplication
    user_prompt_length INTEGER NOT NULL, -- Character count

    -- Agent instructions (from manifest injection)
    agent_instructions TEXT, -- Complete agent prompt/instructions
    agent_instructions_hash VARCHAR(64), -- SHA-256 hash
    agent_instructions_length INTEGER, -- Character count

    -- Manifest linkage
    manifest_injection_id UUID REFERENCES agent_manifest_injections(id), -- Link to manifest used
    manifest_sections_included TEXT[], -- Which sections were in the instructions

    -- Context enrichment
    system_context JSONB, -- System info (cwd, git status, environment)
    conversation_history JSONB, -- Previous messages in conversation
    attached_files TEXT[], -- Files attached to prompt

    -- Claude Code context
    claude_session_id VARCHAR(255), -- Claude session identifier
    terminal_id VARCHAR(255), -- Terminal identifier
    project_path TEXT, -- Working directory
    project_name VARCHAR(255), -- Project name

    -- Metadata
    metadata JSONB DEFAULT '{}'::jsonb,

    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    -- Constraints
    CONSTRAINT agent_prompts_length_check
        CHECK (user_prompt_length > 0 AND user_prompt_length <= 1000000) -- Max 1MB
);

-- Indexes for agent_prompts
CREATE INDEX IF NOT EXISTS idx_agent_prompts_correlation
    ON agent_prompts(correlation_id);

CREATE INDEX IF NOT EXISTS idx_agent_prompts_session
    ON agent_prompts(session_id)
    WHERE session_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_agent_prompts_execution
    ON agent_prompts(execution_id)
    WHERE execution_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_agent_prompts_agent
    ON agent_prompts(agent_name, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_agent_prompts_hash
    ON agent_prompts(user_prompt_hash, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_agent_prompts_manifest
    ON agent_prompts(manifest_injection_id)
    WHERE manifest_injection_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_agent_prompts_time
    ON agent_prompts(created_at DESC);

CREATE INDEX IF NOT EXISTS idx_agent_prompts_claude_session
    ON agent_prompts(claude_session_id)
    WHERE claude_session_id IS NOT NULL;

-- GIN indexes for complex queries
CREATE INDEX IF NOT EXISTS idx_agent_prompts_system_context
    ON agent_prompts USING GIN(system_context);

CREATE INDEX IF NOT EXISTS idx_agent_prompts_conversation
    ON agent_prompts USING GIN(conversation_history);

-- Full-text search on prompts (optional, for prompt search)
CREATE INDEX IF NOT EXISTS idx_agent_prompts_search
    ON agent_prompts USING GIN(to_tsvector('english', user_prompt));

-- Comments
COMMENT ON TABLE agent_prompts IS
    'Complete prompt traceability: user requests and agent instructions for full context replay';
COMMENT ON COLUMN agent_prompts.correlation_id IS
    'Links to agent_execution_logs, agent_actions, and agent_manifest_injections';
COMMENT ON COLUMN agent_prompts.user_prompt_hash IS
    'SHA-256 hash for prompt deduplication and similarity analysis';
COMMENT ON COLUMN agent_prompts.agent_instructions IS
    'Complete agent prompt with manifest injection - enables exact execution replay';
COMMENT ON COLUMN agent_prompts.manifest_injection_id IS
    'Links to specific manifest that was injected into agent instructions';

-- -------------------------------------------------------------------------
-- Table: agent_file_operations
-- Purpose: Track every file read/write with content hashes and intelligence links
-- -------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS agent_file_operations (
    -- Primary key
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Correlation and tracing
    correlation_id UUID NOT NULL, -- Links to execution logs
    execution_id UUID, -- Links to agent_execution_logs.execution_id
    prompt_id UUID REFERENCES agent_prompts(id), -- Links to prompt that triggered this

    -- Agent context
    agent_name VARCHAR(255) NOT NULL,

    -- Operation details
    operation_type VARCHAR(50) NOT NULL, -- 'read', 'write', 'edit', 'delete', 'create'
    file_path TEXT NOT NULL, -- Absolute path to file
    file_path_hash VARCHAR(64) NOT NULL, -- SHA-256 hash of file path

    -- File identification
    file_name VARCHAR(255), -- Extracted filename
    file_extension VARCHAR(50), -- File extension (.py, .js, etc)
    file_size_bytes BIGINT, -- File size at operation time

    -- Content hashing (for integrity and deduplication)
    content_hash_before VARCHAR(64), -- SHA-256 of content before operation
    content_hash_after VARCHAR(64), -- SHA-256 of content after operation
    content_changed BOOLEAN DEFAULT FALSE, -- Whether content was modified

    -- Intelligence DB linkage
    intelligence_file_id UUID, -- Links to Archon intelligence DB file records
    intelligence_pattern_match BOOLEAN DEFAULT FALSE, -- Whether file matched a pattern
    matched_pattern_ids UUID[], -- Array of pattern IDs that matched

    -- Operation context
    tool_name VARCHAR(100), -- Tool used (Read, Write, Edit, Bash, etc)
    line_range JSONB, -- {"start": 1, "end": 100} for partial operations
    operation_params JSONB, -- Tool parameters (old_string, new_string, etc)

    -- Operation results
    success BOOLEAN DEFAULT TRUE, -- Whether operation succeeded
    error_message TEXT, -- Error if operation failed
    bytes_read BIGINT, -- Bytes read (for Read operations)
    bytes_written BIGINT, -- Bytes written (for Write/Edit operations)

    -- Performance metrics
    duration_ms INTEGER, -- Operation duration

    -- Metadata
    metadata JSONB DEFAULT '{}'::jsonb,

    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    -- Constraints
    CONSTRAINT agent_file_operations_type_check
        CHECK (operation_type IN ('read', 'write', 'edit', 'delete', 'create', 'glob', 'grep')),
    CONSTRAINT agent_file_operations_duration_check
        CHECK (duration_ms IS NULL OR (duration_ms >= 0 AND duration_ms < 3600000)) -- Max 1 hour
);

-- Indexes for agent_file_operations
CREATE INDEX IF NOT EXISTS idx_agent_file_operations_correlation
    ON agent_file_operations(correlation_id);

CREATE INDEX IF NOT EXISTS idx_agent_file_operations_execution
    ON agent_file_operations(execution_id)
    WHERE execution_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_agent_file_operations_prompt
    ON agent_file_operations(prompt_id)
    WHERE prompt_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_agent_file_operations_agent
    ON agent_file_operations(agent_name, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_agent_file_operations_type
    ON agent_file_operations(operation_type, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_agent_file_operations_path
    ON agent_file_operations(file_path_hash, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_agent_file_operations_content_hash
    ON agent_file_operations(content_hash_after)
    WHERE content_hash_after IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_agent_file_operations_intelligence
    ON agent_file_operations(intelligence_file_id)
    WHERE intelligence_file_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_agent_file_operations_patterns
    ON agent_file_operations USING GIN(matched_pattern_ids);

CREATE INDEX IF NOT EXISTS idx_agent_file_operations_changed
    ON agent_file_operations(content_changed)
    WHERE content_changed = TRUE;

CREATE INDEX IF NOT EXISTS idx_agent_file_operations_time
    ON agent_file_operations(created_at DESC);

-- GIN indexes for complex queries
CREATE INDEX IF NOT EXISTS idx_agent_file_operations_params
    ON agent_file_operations USING GIN(operation_params);

-- Composite index for file history queries
CREATE INDEX IF NOT EXISTS idx_agent_file_operations_history
    ON agent_file_operations(file_path_hash, created_at DESC);

-- Comments
COMMENT ON TABLE agent_file_operations IS
    'Complete file operation traceability with content hashes and intelligence DB links';
COMMENT ON COLUMN agent_file_operations.correlation_id IS
    'Links to agent_execution_logs and other traceability tables';
COMMENT ON COLUMN agent_file_operations.content_hash_before IS
    'SHA-256 of file content before operation - enables change detection';
COMMENT ON COLUMN agent_file_operations.content_hash_after IS
    'SHA-256 of file content after operation - enables integrity verification';
COMMENT ON COLUMN agent_file_operations.intelligence_file_id IS
    'Links to Archon intelligence DB file records for cross-reference';
COMMENT ON COLUMN agent_file_operations.matched_pattern_ids IS
    'Array of Qdrant pattern IDs that matched this file';

-- -------------------------------------------------------------------------
-- Table: agent_intelligence_usage
-- Purpose: Track which patterns, schemas, and intelligence were actually used
-- -------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS agent_intelligence_usage (
    -- Primary key
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Correlation and tracing
    correlation_id UUID NOT NULL, -- Links to execution logs
    execution_id UUID, -- Links to agent_execution_logs.execution_id
    manifest_injection_id UUID REFERENCES agent_manifest_injections(id), -- Link to manifest
    prompt_id UUID REFERENCES agent_prompts(id), -- Link to prompt

    -- Agent context
    agent_name VARCHAR(255) NOT NULL,

    -- Intelligence source
    intelligence_type VARCHAR(100) NOT NULL, -- 'pattern', 'schema', 'debug_intelligence', 'model', 'infrastructure'
    intelligence_source VARCHAR(100) NOT NULL, -- 'qdrant', 'memgraph', 'postgres', 'archon-intelligence'

    -- Intelligence identification
    intelligence_id UUID, -- Qdrant point ID, Memgraph node ID, etc
    intelligence_name TEXT, -- Pattern name, schema name, etc
    collection_name VARCHAR(255), -- Qdrant collection (execution_patterns, code_patterns, etc)

    -- Usage details
    usage_context VARCHAR(100), -- 'reference', 'implementation', 'inspiration', 'validation'
    usage_count INTEGER DEFAULT 1, -- How many times this intelligence was referenced
    confidence_score NUMERIC(5,4), -- Confidence/relevance score if available

    -- Intelligence content (snapshot at usage time)
    intelligence_snapshot JSONB, -- Complete intelligence data structure
    intelligence_summary TEXT, -- Human-readable summary

    -- Query details
    query_used TEXT, -- Query that retrieved this intelligence
    query_time_ms INTEGER, -- Query performance
    query_results_rank INTEGER, -- Ranking in query results (1=top result)

    -- Application tracking
    was_applied BOOLEAN DEFAULT FALSE, -- Whether intelligence was actually used
    application_details JSONB, -- How it was applied
    file_operations_using_this UUID[], -- Links to agent_file_operations that used this

    -- Effectiveness tracking
    contributed_to_success BOOLEAN, -- Whether this helped achieve success
    quality_impact NUMERIC(5,4), -- Estimated quality contribution (0.0-1.0)

    -- Metadata
    metadata JSONB DEFAULT '{}'::jsonb,

    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    applied_at TIMESTAMP WITH TIME ZONE, -- When intelligence was applied

    -- Constraints
    CONSTRAINT agent_intelligence_usage_type_check
        CHECK (intelligence_type IN ('pattern', 'schema', 'debug_intelligence', 'model', 'infrastructure', 'relationship')),
    CONSTRAINT agent_intelligence_usage_source_check
        CHECK (intelligence_source IN ('qdrant', 'memgraph', 'postgres', 'archon-intelligence', 'fallback')),
    CONSTRAINT agent_intelligence_usage_confidence_check
        CHECK (confidence_score IS NULL OR (confidence_score >= 0 AND confidence_score <= 1)),
    CONSTRAINT agent_intelligence_usage_quality_check
        CHECK (quality_impact IS NULL OR (quality_impact >= 0 AND quality_impact <= 1))
);

-- Indexes for agent_intelligence_usage
CREATE INDEX IF NOT EXISTS idx_agent_intelligence_usage_correlation
    ON agent_intelligence_usage(correlation_id);

CREATE INDEX IF NOT EXISTS idx_agent_intelligence_usage_execution
    ON agent_intelligence_usage(execution_id)
    WHERE execution_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_agent_intelligence_usage_manifest
    ON agent_intelligence_usage(manifest_injection_id)
    WHERE manifest_injection_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_agent_intelligence_usage_prompt
    ON agent_intelligence_usage(prompt_id)
    WHERE prompt_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_agent_intelligence_usage_agent
    ON agent_intelligence_usage(agent_name, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_agent_intelligence_usage_type
    ON agent_intelligence_usage(intelligence_type, intelligence_source);

CREATE INDEX IF NOT EXISTS idx_agent_intelligence_usage_id
    ON agent_intelligence_usage(intelligence_id)
    WHERE intelligence_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_agent_intelligence_usage_collection
    ON agent_intelligence_usage(collection_name)
    WHERE collection_name IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_agent_intelligence_usage_applied
    ON agent_intelligence_usage(was_applied, contributed_to_success)
    WHERE was_applied = TRUE;

CREATE INDEX IF NOT EXISTS idx_agent_intelligence_usage_time
    ON agent_intelligence_usage(created_at DESC);

CREATE INDEX IF NOT EXISTS idx_agent_intelligence_usage_file_ops
    ON agent_intelligence_usage USING GIN(file_operations_using_this);

-- GIN indexes for complex queries
CREATE INDEX IF NOT EXISTS idx_agent_intelligence_usage_snapshot
    ON agent_intelligence_usage USING GIN(intelligence_snapshot);

CREATE INDEX IF NOT EXISTS idx_agent_intelligence_usage_application
    ON agent_intelligence_usage USING GIN(application_details);

-- Composite index for effectiveness analysis
CREATE INDEX IF NOT EXISTS idx_agent_intelligence_usage_effectiveness
    ON agent_intelligence_usage(intelligence_type, confidence_score DESC, quality_impact DESC)
    WHERE was_applied = TRUE;

-- Comments
COMMENT ON TABLE agent_intelligence_usage IS
    'Tracks which patterns, schemas, and intelligence were actually used during execution';
COMMENT ON COLUMN agent_intelligence_usage.correlation_id IS
    'Links to agent_execution_logs for complete execution trace';
COMMENT ON COLUMN agent_intelligence_usage.intelligence_id IS
    'Links back to Qdrant point IDs, Memgraph node IDs, or PostgreSQL records';
COMMENT ON COLUMN agent_intelligence_usage.intelligence_snapshot IS
    'Complete snapshot of intelligence at usage time - enables replay even if source changes';
COMMENT ON COLUMN agent_intelligence_usage.was_applied IS
    'Whether intelligence was actually used (not just read) - key for effectiveness analysis';
COMMENT ON COLUMN agent_intelligence_usage.file_operations_using_this IS
    'Links to agent_file_operations that applied this intelligence';

-- -------------------------------------------------------------------------
-- Views for comprehensive traceability analysis
-- -------------------------------------------------------------------------

-- View: Complete execution trace with all traceability data
CREATE OR REPLACE VIEW v_complete_execution_trace AS
SELECT
    -- Core IDs
    ael.execution_id,
    ael.correlation_id,
    ael.session_id,

    -- Agent info
    ael.agent_name,
    ael.status,
    ael.quality_score,

    -- Prompts
    ap.user_prompt,
    ap.user_prompt_length,
    ap.agent_instructions_length,
    ap.manifest_sections_included,

    -- Manifest
    ami.manifest_version,
    ami.patterns_count,
    ami.debug_intelligence_successes,
    ami.total_query_time_ms,

    -- File operations summary
    COUNT(DISTINCT afo.id) as file_operations_count,
    COUNT(DISTINCT afo.file_path_hash) as unique_files_touched,
    SUM(CASE WHEN afo.operation_type = 'read' THEN 1 ELSE 0 END) as files_read,
    SUM(CASE WHEN afo.operation_type IN ('write', 'edit') THEN 1 ELSE 0 END) as files_modified,
    SUM(CASE WHEN afo.content_changed THEN 1 ELSE 0 END) as files_changed,

    -- Intelligence usage summary
    COUNT(DISTINCT aiu.id) as intelligence_items_used,
    COUNT(DISTINCT aiu.intelligence_id) as unique_intelligence_sources,
    SUM(CASE WHEN aiu.was_applied THEN 1 ELSE 0 END) as intelligence_applied_count,
    AVG(aiu.quality_impact) FILTER (WHERE aiu.was_applied) as avg_intelligence_quality_impact,

    -- Timing
    ael.created_at as started_at,
    ael.completed_at,
    ael.duration_ms

FROM agent_execution_logs ael
LEFT JOIN agent_prompts ap ON ael.correlation_id = ap.correlation_id
LEFT JOIN agent_manifest_injections ami ON ael.correlation_id = ami.correlation_id
LEFT JOIN agent_file_operations afo ON ael.correlation_id = afo.correlation_id
LEFT JOIN agent_intelligence_usage aiu ON ael.correlation_id = aiu.correlation_id

GROUP BY
    ael.execution_id, ael.correlation_id, ael.session_id,
    ael.agent_name, ael.status, ael.quality_score,
    ap.user_prompt, ap.user_prompt_length, ap.agent_instructions_length, ap.manifest_sections_included,
    ami.manifest_version, ami.patterns_count, ami.debug_intelligence_successes, ami.total_query_time_ms,
    ael.created_at, ael.completed_at, ael.duration_ms

ORDER BY ael.created_at DESC;

COMMENT ON VIEW v_complete_execution_trace IS
    'Complete execution trace with prompts, files, intelligence usage for comprehensive analysis';

-- View: File operation history per file
CREATE OR REPLACE VIEW v_file_operation_history AS
SELECT
    file_path,
    file_name,
    file_extension,
    COUNT(*) as total_operations,
    COUNT(DISTINCT agent_name) as agents_touched,
    COUNT(DISTINCT correlation_id) as executions_touched,
    MIN(created_at) as first_operation,
    MAX(created_at) as last_operation,
    SUM(CASE WHEN operation_type = 'read' THEN 1 ELSE 0 END) as read_count,
    SUM(CASE WHEN operation_type IN ('write', 'edit') THEN 1 ELSE 0 END) as write_count,
    SUM(CASE WHEN content_changed THEN 1 ELSE 0 END) as change_count,
    AVG(duration_ms) as avg_operation_time_ms,
    array_agg(DISTINCT content_hash_after ORDER BY content_hash_after)
        FILTER (WHERE content_hash_after IS NOT NULL) as content_versions
FROM agent_file_operations
GROUP BY file_path, file_name, file_extension
ORDER BY last_operation DESC;

COMMENT ON VIEW v_file_operation_history IS
    'File operation history showing which files are frequently accessed/modified';

-- View: Intelligence effectiveness analysis
CREATE OR REPLACE VIEW v_intelligence_effectiveness AS
SELECT
    intelligence_type,
    intelligence_source,
    collection_name,
    intelligence_name,
    COUNT(*) as times_retrieved,
    SUM(CASE WHEN was_applied THEN 1 ELSE 0 END) as times_applied,
    (SUM(CASE WHEN was_applied THEN 1 ELSE 0 END)::numeric * 100) /
        NULLIF(COUNT(*), 0) as application_rate_percent,
    AVG(confidence_score) as avg_confidence,
    AVG(quality_impact) FILTER (WHERE was_applied) as avg_quality_impact,
    SUM(CASE WHEN contributed_to_success THEN 1 ELSE 0 END) as success_contributions,
    AVG(query_time_ms) as avg_query_time_ms,
    array_agg(DISTINCT agent_name) as agents_using_this
FROM agent_intelligence_usage
GROUP BY intelligence_type, intelligence_source, collection_name, intelligence_name
HAVING COUNT(*) > 1 -- Only show patterns used more than once
ORDER BY times_applied DESC, avg_quality_impact DESC NULLS LAST;

COMMENT ON VIEW v_intelligence_effectiveness IS
    'Intelligence effectiveness: which patterns/schemas are most useful';

-- View: Agent traceability summary
CREATE OR REPLACE VIEW v_agent_traceability_summary AS
SELECT
    agent_name,
    COUNT(DISTINCT ael.correlation_id) as total_executions,
    COUNT(DISTINCT ap.id) as prompts_captured,
    COUNT(DISTINCT afo.id) as file_operations_logged,
    COUNT(DISTINCT aiu.id) as intelligence_usages_tracked,
    AVG(ami.patterns_count) as avg_patterns_per_execution,
    AVG(afo.duration_ms) FILTER (WHERE afo.duration_ms IS NOT NULL) as avg_file_op_time_ms,
    COUNT(DISTINCT afo.file_path_hash) as unique_files_accessed,
    SUM(CASE WHEN aiu.was_applied THEN 1 ELSE 0 END) as intelligence_applied_count
FROM agent_execution_logs ael
LEFT JOIN agent_prompts ap ON ael.correlation_id = ap.correlation_id
LEFT JOIN agent_file_operations afo ON ael.correlation_id = afo.correlation_id
LEFT JOIN agent_intelligence_usage aiu ON ael.correlation_id = aiu.correlation_id
LEFT JOIN agent_manifest_injections ami ON ael.correlation_id = ami.correlation_id
GROUP BY agent_name
ORDER BY total_executions DESC;

COMMENT ON VIEW v_agent_traceability_summary IS
    'Per-agent traceability summary showing completeness of observability data';

-- -------------------------------------------------------------------------
-- Utility Functions
-- -------------------------------------------------------------------------

-- Function: Get complete execution trace by correlation_id
CREATE OR REPLACE FUNCTION get_complete_trace(p_correlation_id UUID)
RETURNS TABLE (
    trace_type TEXT,
    data JSONB
) AS $$
BEGIN
    -- Return prompts
    RETURN QUERY
    SELECT
        'prompt'::TEXT,
        row_to_json(ap.*)::JSONB
    FROM agent_prompts ap
    WHERE ap.correlation_id = p_correlation_id;

    -- Return file operations
    RETURN QUERY
    SELECT
        'file_operation'::TEXT,
        row_to_json(afo.*)::JSONB
    FROM agent_file_operations afo
    WHERE afo.correlation_id = p_correlation_id
    ORDER BY afo.created_at;

    -- Return intelligence usage
    RETURN QUERY
    SELECT
        'intelligence_usage'::TEXT,
        row_to_json(aiu.*)::JSONB
    FROM agent_intelligence_usage aiu
    WHERE aiu.correlation_id = p_correlation_id
    ORDER BY aiu.created_at;

    -- Return manifest
    RETURN QUERY
    SELECT
        'manifest'::TEXT,
        row_to_json(ami.*)::JSONB
    FROM agent_manifest_injections ami
    WHERE ami.correlation_id = p_correlation_id;

    -- Return execution log
    RETURN QUERY
    SELECT
        'execution'::TEXT,
        row_to_json(ael.*)::JSONB
    FROM agent_execution_logs ael
    WHERE ael.correlation_id = p_correlation_id;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION get_complete_trace(UUID) IS
    'Get complete execution trace for a correlation_id (prompts, files, intelligence, manifest, execution)';

-- Function: Calculate content hash (SHA-256)
CREATE OR REPLACE FUNCTION calculate_content_hash(p_content TEXT)
RETURNS VARCHAR(64) AS $$
BEGIN
    RETURN encode(digest(p_content, 'sha256'), 'hex');
END;
$$ LANGUAGE plpgsql IMMUTABLE;

COMMENT ON FUNCTION calculate_content_hash(TEXT) IS
    'Calculate SHA-256 hash of content for integrity verification';

-- =============================================================================
-- DOWN MIGRATION (ROLLBACK)
-- =============================================================================

-- To rollback this migration, run:
-- DROP FUNCTION IF EXISTS calculate_content_hash(TEXT);
-- DROP FUNCTION IF EXISTS get_complete_trace(UUID);
-- DROP VIEW IF EXISTS v_agent_traceability_summary;
-- DROP VIEW IF EXISTS v_intelligence_effectiveness;
-- DROP VIEW IF EXISTS v_file_operation_history;
-- DROP VIEW IF EXISTS v_complete_execution_trace;
-- DROP TABLE IF EXISTS agent_intelligence_usage CASCADE;
-- DROP TABLE IF EXISTS agent_file_operations CASCADE;
-- DROP TABLE IF EXISTS agent_prompts CASCADE;

-- Success message
DO $$
BEGIN
    RAISE NOTICE '✅ Migration 012: Complete agent traceability schema created successfully';
    RAISE NOTICE '   - agent_prompts: User prompts + agent instructions';
    RAISE NOTICE '   - agent_file_operations: File operations with content hashes';
    RAISE NOTICE '   - agent_intelligence_usage: Intelligence pattern/schema usage';
    RAISE NOTICE '   - 4 comprehensive views for analysis';
    RAISE NOTICE '   - 2 utility functions (get_complete_trace, calculate_content_hash)';
    RAISE NOTICE '';
    RAISE NOTICE '📊 Observability Coverage:';
    RAISE NOTICE '   - User prompts: ✅ Captured with SHA-256 hashing';
    RAISE NOTICE '   - Agent instructions: ✅ Linked to manifest injections';
    RAISE NOTICE '   - File operations: ✅ Complete with before/after hashes';
    RAISE NOTICE '   - Intelligence usage: ✅ Pattern/schema tracking with effectiveness';
    RAISE NOTICE '   - Correlation tracking: ✅ Complete trace from prompt to result';
    RAISE NOTICE '';
    RAISE NOTICE '🔗 Integration Points:';
    RAISE NOTICE '   - Links to agent_execution_logs via correlation_id';
    RAISE NOTICE '   - Links to agent_manifest_injections for intelligence context';
    RAISE NOTICE '   - Links to Archon intelligence DB (Qdrant, Memgraph, PostgreSQL)';
    RAISE NOTICE '';
    RAISE NOTICE '📈 Query Examples:';
    RAISE NOTICE '   - SELECT * FROM v_complete_execution_trace WHERE agent_name = ''agent-test'';';
    RAISE NOTICE '   - SELECT * FROM v_intelligence_effectiveness ORDER BY application_rate_percent DESC;';
    RAISE NOTICE '   - SELECT * FROM get_complete_trace(''<correlation-id>'');';
END $$;
