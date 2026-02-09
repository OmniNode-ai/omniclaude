-- ======================================================================
-- Migration: Create learned_patterns Table
-- ======================================================================
-- Date: 2026-01-26
-- Ticket: OMN-1403 (Context injection for session enrichment)
-- Purpose: Replace file-based pattern storage (.claude/learned_patterns.json)
--          with PostgreSQL persistence in omninode_bridge database.
-- Database: omninode_bridge @ 192.168.86.200:5436
-- ======================================================================
--
-- Schema matches PatternRecord from:
--   - src/omniclaude/hooks/handler_context_injection.py (lines 42-86)
--   - plugins/onex/hooks/lib/pattern_types.py (lines 23-67)
--
-- Fields from PatternRecord:
--   - pattern_id: Unique external identifier for the pattern
--   - domain: Pattern category (e.g., "code_review", "testing", "general")
--   - title: Human-readable title
--   - description: Detailed description of the pattern
--   - confidence: Confidence score [0.0, 1.0]
--   - usage_count: Number of times pattern has been applied (non-negative)
--   - success_rate: Success rate [0.0, 1.0]
--   - example_reference: Optional reference to an example
--
-- Additional database fields:
--   - id: Internal UUID primary key (gen_random_uuid)
--   - project_scope: NULL = global pattern, otherwise project-specific
--   - created_at: Pattern creation timestamp
--   - updated_at: Last modification timestamp
--
-- ======================================================================

BEGIN;

-- ======================================================================
-- 1. Create learned_patterns Table
-- ======================================================================

CREATE TABLE IF NOT EXISTS learned_patterns (
    -- Internal database identifier (UUID v4)
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- External pattern identifier (unique across all patterns)
    -- Format: typically domain-specific identifier (e.g., "code_review_pr_size_001")
    pattern_id VARCHAR(255) UNIQUE NOT NULL,

    -- Pattern domain/category for filtering
    -- Examples: "code_review", "testing", "debugging", "documentation", "general"
    -- The "general" domain is always included regardless of domain filter
    domain VARCHAR(100) NOT NULL,

    -- Human-readable pattern title
    -- Displayed in the injected markdown context
    title VARCHAR(255) NOT NULL,

    -- Detailed pattern description
    -- Contains the full pattern explanation, guidelines, and best practices
    description TEXT NOT NULL,

    -- Confidence score from machine learning or manual curation
    -- Range: [0.0, 1.0] where 1.0 = highest confidence
    -- Used for filtering (min_confidence threshold) and sorting (descending)
    confidence FLOAT NOT NULL CHECK (confidence >= 0.0 AND confidence <= 1.0),

    -- Number of times this pattern has been applied/used
    -- Must be non-negative, incremented on each successful application
    usage_count INTEGER NOT NULL DEFAULT 0 CHECK (usage_count >= 0),

    -- Success rate of pattern applications
    -- Range: [0.0, 1.0] where 1.0 = 100% success rate
    -- Calculated as: successful_applications / total_applications
    success_rate FLOAT NOT NULL CHECK (success_rate >= 0.0 AND success_rate <= 1.0),

    -- Optional reference to an example demonstrating the pattern
    -- Format: typically "path/to/file.py:42" or "project:commit:file"
    example_reference TEXT,

    -- Project scope for pattern visibility
    -- NULL = global pattern (visible to all projects)
    -- Non-NULL = project-specific pattern (e.g., "omniclaude", "omnibase_core")
    project_scope VARCHAR(255),

    -- Timestamps for auditing and cache invalidation
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ======================================================================
-- 2. Create Indexes for Common Query Patterns
-- ======================================================================

-- Primary query pattern: Filter by domain, sort by confidence DESC
-- Used by HandlerContextInjection._load_patterns_from_database()
-- Supports queries like:
--   SELECT * FROM learned_patterns
--   WHERE domain IN ($domain, 'general') AND confidence >= $min_confidence
--   ORDER BY confidence DESC
--   LIMIT $max_patterns
CREATE INDEX IF NOT EXISTS idx_learned_patterns_domain_confidence
ON learned_patterns(domain, confidence DESC);

-- Project scope filtering for multi-project deployments
-- Supports queries like:
--   SELECT * FROM learned_patterns
--   WHERE project_scope IS NULL OR project_scope = $current_project
CREATE INDEX IF NOT EXISTS idx_learned_patterns_project_scope
ON learned_patterns(project_scope);

-- Pattern lookup by external ID (for updates and deduplication)
-- Already covered by UNIQUE constraint, but explicit for clarity
-- Note: pattern_id UNIQUE constraint creates implicit index

-- Temporal queries for analytics and cache management
CREATE INDEX IF NOT EXISTS idx_learned_patterns_updated_at
ON learned_patterns(updated_at DESC);

-- Composite index for scoped domain queries
-- Supports queries like:
--   SELECT * FROM learned_patterns
--   WHERE (project_scope IS NULL OR project_scope = $project)
--   AND domain = $domain
--   ORDER BY confidence DESC
CREATE INDEX IF NOT EXISTS idx_learned_patterns_scope_domain_confidence
ON learned_patterns(project_scope, domain, confidence DESC);

-- ======================================================================
-- 3. Add Column Comments
-- ======================================================================

COMMENT ON TABLE learned_patterns IS
    'Stores learned patterns for context injection during Claude Code sessions. '
    'Replaces file-based storage (.claude/learned_patterns.json). '
    'Part of OMN-1403: Context injection for session enrichment.';

COMMENT ON COLUMN learned_patterns.id IS
    'Internal UUID primary key (auto-generated)';

COMMENT ON COLUMN learned_patterns.pattern_id IS
    'External unique identifier for the pattern (e.g., "code_review_pr_size_001")';

COMMENT ON COLUMN learned_patterns.domain IS
    'Pattern category for filtering (e.g., "code_review", "testing", "general"). '
    'The "general" domain patterns are always included regardless of filter.';

COMMENT ON COLUMN learned_patterns.title IS
    'Human-readable pattern title displayed in injected context';

COMMENT ON COLUMN learned_patterns.description IS
    'Full pattern description with guidelines and best practices';

COMMENT ON COLUMN learned_patterns.confidence IS
    'Confidence score [0.0, 1.0] used for filtering and sorting. '
    'Patterns below min_confidence threshold are excluded from injection.';

COMMENT ON COLUMN learned_patterns.usage_count IS
    'Number of times pattern has been applied (non-negative integer)';

COMMENT ON COLUMN learned_patterns.success_rate IS
    'Success rate [0.0, 1.0] of pattern applications';

COMMENT ON COLUMN learned_patterns.example_reference IS
    'Optional reference to example (e.g., "path/to/file.py:42")';

COMMENT ON COLUMN learned_patterns.project_scope IS
    'Project scope: NULL = global, non-NULL = project-specific pattern';

COMMENT ON COLUMN learned_patterns.created_at IS
    'Pattern creation timestamp (auto-set to NOW())';

COMMENT ON COLUMN learned_patterns.updated_at IS
    'Last modification timestamp (must be updated on changes)';

-- ======================================================================
-- 4. Create Trigger for updated_at Auto-Update
-- ======================================================================

-- Function to automatically update updated_at on row modification
CREATE OR REPLACE FUNCTION update_learned_patterns_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger to call the function before any UPDATE
DROP TRIGGER IF EXISTS trg_learned_patterns_updated_at ON learned_patterns;
CREATE TRIGGER trg_learned_patterns_updated_at
    BEFORE UPDATE ON learned_patterns
    FOR EACH ROW
    EXECUTE FUNCTION update_learned_patterns_updated_at();

COMMENT ON FUNCTION update_learned_patterns_updated_at() IS
    'Trigger function to auto-update updated_at timestamp on learned_patterns modifications';

COMMIT;

-- ======================================================================
-- ROLLBACK SECTION
-- ======================================================================
-- To rollback this migration, run the following commands:
--
-- BEGIN;
-- DROP TRIGGER IF EXISTS trg_learned_patterns_updated_at ON learned_patterns;
-- DROP FUNCTION IF EXISTS update_learned_patterns_updated_at();
-- DROP INDEX IF EXISTS idx_learned_patterns_scope_domain_confidence;
-- DROP INDEX IF EXISTS idx_learned_patterns_updated_at;
-- DROP INDEX IF EXISTS idx_learned_patterns_project_scope;
-- DROP INDEX IF EXISTS idx_learned_patterns_domain_confidence;
-- DROP TABLE IF EXISTS learned_patterns;
-- COMMIT;
--
-- ======================================================================

-- ======================================================================
-- Summary
-- ======================================================================
-- Changes applied:
-- 1. Created learned_patterns table with all PatternRecord fields
-- 2. Added UUID primary key (id) and external identifier (pattern_id)
-- 3. Added project_scope for multi-project support
-- 4. Added created_at/updated_at timestamps with auto-update trigger
-- 5. Created indexes for:
--    - Domain + confidence filtering (primary query pattern)
--    - Project scope filtering
--    - Temporal queries (updated_at)
--    - Composite scope + domain + confidence queries
-- 6. Added comprehensive column comments
--
-- Query patterns supported:
-- - Filter by domain and confidence threshold
-- - Filter by project scope (global vs project-specific)
-- - Sort by confidence descending
-- - Lookup by external pattern_id
-- - Temporal queries for analytics
-- ======================================================================
