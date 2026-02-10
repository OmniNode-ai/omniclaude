-- Migration 002: Create learned_patterns Table
-- Date: 2026-01-26
-- Purpose: Create table for storing learned patterns for context injection
--
-- This table stores learned patterns that are injected into Claude Code sessions.
-- Patterns are filtered by domain, confidence, and project scope during context injection.
--
-- Part of OMN-1403: Context injection for session enrichment.

BEGIN;

-- Create learned_patterns table
CREATE TABLE IF NOT EXISTS learned_patterns (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    pattern_id text NOT NULL UNIQUE,
    domain text NOT NULL,
    title text NOT NULL,
    description text NOT NULL,
    confidence double precision NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    usage_count integer NOT NULL DEFAULT 0 CHECK (usage_count >= 0),
    success_rate double precision NOT NULL DEFAULT 0 CHECK (success_rate >= 0 AND success_rate <= 1),
    example_reference text,
    project_scope text,
    created_at timestamp with time zone NOT NULL DEFAULT NOW(),
    updated_at timestamp with time zone NOT NULL DEFAULT NOW()
);

-- Create index on pattern_id for lookups (unique constraint already creates index)
-- CREATE INDEX IF NOT EXISTS idx_learned_patterns_pattern_id ON learned_patterns(pattern_id);

-- Create index on domain for filtering
CREATE INDEX IF NOT EXISTS idx_learned_patterns_domain
    ON learned_patterns(domain);

-- Create index on confidence for filtering/sorting
CREATE INDEX IF NOT EXISTS idx_learned_patterns_confidence
    ON learned_patterns(confidence DESC);

-- Create index on project_scope for filtering
CREATE INDEX IF NOT EXISTS idx_learned_patterns_project_scope
    ON learned_patterns(project_scope);

-- Create composite index for common query pattern (domain + confidence)
CREATE INDEX IF NOT EXISTS idx_learned_patterns_domain_confidence
    ON learned_patterns(domain, confidence DESC);

-- Temporal queries for analytics and cache management
CREATE INDEX IF NOT EXISTS idx_learned_patterns_updated_at
    ON learned_patterns(updated_at DESC);

-- Composite index for scoped domain queries
-- Supports: WHERE (project_scope IS NULL OR project_scope = $project)
--           AND domain = $domain ORDER BY confidence DESC
CREATE INDEX IF NOT EXISTS idx_learned_patterns_scope_domain_confidence
    ON learned_patterns(project_scope, domain, confidence DESC);

-- Add table comment
COMMENT ON TABLE learned_patterns IS
'Learned patterns for Claude Code context injection. Patterns are injected into sessions based on domain, confidence, and project scope.';

-- Add column comments
COMMENT ON COLUMN learned_patterns.id IS
'Database UUID primary key.';

COMMENT ON COLUMN learned_patterns.pattern_id IS
'Unique string identifier for the pattern. Used for deduplication and external references.';

COMMENT ON COLUMN learned_patterns.domain IS
'Domain/category of the pattern (e.g., "code_review", "testing", "general").';

COMMENT ON COLUMN learned_patterns.title IS
'Human-readable title for the pattern.';

COMMENT ON COLUMN learned_patterns.description IS
'Detailed description of what the pattern represents and how to apply it.';

COMMENT ON COLUMN learned_patterns.confidence IS
'Confidence score (0.0-1.0). Higher confidence patterns are prioritized during injection.';

COMMENT ON COLUMN learned_patterns.usage_count IS
'Number of times this pattern has been applied/injected.';

COMMENT ON COLUMN learned_patterns.success_rate IS
'Success rate (0.0-1.0) based on feedback from pattern applications.';

COMMENT ON COLUMN learned_patterns.example_reference IS
'Optional reference to an example demonstrating the pattern.';

COMMENT ON COLUMN learned_patterns.project_scope IS
'Optional project scope. NULL means global pattern available to all projects.';

-- Create trigger function to auto-update updated_at on row modification
CREATE OR REPLACE FUNCTION update_learned_patterns_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Create trigger to call the function before any UPDATE
DROP TRIGGER IF EXISTS trg_learned_patterns_updated_at ON learned_patterns;
CREATE TRIGGER trg_learned_patterns_updated_at
    BEFORE UPDATE ON learned_patterns
    FOR EACH ROW
    EXECUTE FUNCTION update_learned_patterns_updated_at();

COMMENT ON FUNCTION update_learned_patterns_updated_at() IS
'Trigger function to auto-update updated_at timestamp on learned_patterns modifications';

-- Verify table was created
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public'
        AND table_name = 'learned_patterns'
    ) THEN
        RAISE EXCEPTION 'learned_patterns table was not created';
    END IF;

    RAISE NOTICE 'Successfully created learned_patterns table';
END $$;

COMMIT;

-- Verification query (run after migration)
-- SELECT COUNT(*) FROM learned_patterns;
-- SELECT * FROM pg_indexes WHERE tablename = 'learned_patterns';
