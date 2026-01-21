-- Migration 004: Pattern Quality and Usage Tracking
-- Adds detailed quality score columns and usage tracking to pattern_lineage_nodes
-- Creates pattern_relationships table for relationship tracking with confidence scoring

-- ============================================================================
-- PART 1: Add Quality Score Columns to pattern_lineage_nodes
-- ============================================================================

-- Add individual quality metric columns
ALTER TABLE pattern_lineage_nodes
ADD COLUMN IF NOT EXISTS complexity_score DECIMAL(3,2) CHECK (complexity_score IS NULL OR (complexity_score >= 0 AND complexity_score <= 1)),
ADD COLUMN IF NOT EXISTS documentation_score DECIMAL(3,2) CHECK (documentation_score IS NULL OR (documentation_score >= 0 AND documentation_score <= 1)),
ADD COLUMN IF NOT EXISTS test_coverage_score DECIMAL(3,2) CHECK (test_coverage_score IS NULL OR (test_coverage_score >= 0 AND test_coverage_score <= 1)),
ADD COLUMN IF NOT EXISTS reusability_score DECIMAL(3,2) CHECK (reusability_score IS NULL OR (reusability_score >= 0 AND reusability_score <= 1)),
ADD COLUMN IF NOT EXISTS maintainability_score DECIMAL(3,2) CHECK (maintainability_score IS NULL OR (maintainability_score >= 0 AND maintainability_score <= 1)),
ADD COLUMN IF NOT EXISTS overall_quality DECIMAL(3,2) CHECK (overall_quality IS NULL OR (overall_quality >= 0 AND overall_quality <= 1));

-- Create indexes for quality score queries
CREATE INDEX IF NOT EXISTS idx_pattern_lineage_overall_quality
    ON pattern_lineage_nodes(overall_quality DESC NULLS LAST);
CREATE INDEX IF NOT EXISTS idx_pattern_lineage_complexity
    ON pattern_lineage_nodes(complexity_score DESC NULLS LAST);
CREATE INDEX IF NOT EXISTS idx_pattern_lineage_maintainability
    ON pattern_lineage_nodes(maintainability_score DESC NULLS LAST);

-- Add comment explaining the quality scoring system
COMMENT ON COLUMN pattern_lineage_nodes.complexity_score IS
    'Pattern complexity score (0.0-1.0): Higher score = lower complexity (better)';
COMMENT ON COLUMN pattern_lineage_nodes.documentation_score IS
    'Documentation quality score (0.0-1.0): Completeness and clarity of documentation';
COMMENT ON COLUMN pattern_lineage_nodes.test_coverage_score IS
    'Test coverage score (0.0-1.0): Percentage of code covered by tests';
COMMENT ON COLUMN pattern_lineage_nodes.reusability_score IS
    'Reusability score (0.0-1.0): How reusable this pattern is across contexts';
COMMENT ON COLUMN pattern_lineage_nodes.maintainability_score IS
    'Maintainability score (0.0-1.0): Ease of maintenance and modification';
COMMENT ON COLUMN pattern_lineage_nodes.overall_quality IS
    'Overall quality score (0.0-1.0): Weighted average of all quality metrics';

-- ============================================================================
-- PART 2: Add Usage Tracking Columns to pattern_lineage_nodes
-- ============================================================================

-- Add usage tracking columns
ALTER TABLE pattern_lineage_nodes
ADD COLUMN IF NOT EXISTS usage_count INTEGER DEFAULT 0 CHECK (usage_count >= 0),
ADD COLUMN IF NOT EXISTS last_used_at TIMESTAMP WITH TIME ZONE,
ADD COLUMN IF NOT EXISTS used_by_agents TEXT[] DEFAULT ARRAY[]::TEXT[];

-- Create indexes for usage queries
CREATE INDEX IF NOT EXISTS idx_pattern_lineage_usage_count
    ON pattern_lineage_nodes(usage_count DESC);
CREATE INDEX IF NOT EXISTS idx_pattern_lineage_last_used
    ON pattern_lineage_nodes(last_used_at DESC NULLS LAST);
CREATE INDEX IF NOT EXISTS idx_pattern_lineage_used_by_agents
    ON pattern_lineage_nodes USING GIN(used_by_agents);

-- Add comments for usage tracking
COMMENT ON COLUMN pattern_lineage_nodes.usage_count IS
    'Number of times this pattern has been used in agent manifest injections';
COMMENT ON COLUMN pattern_lineage_nodes.last_used_at IS
    'Timestamp of the last time this pattern was used';
COMMENT ON COLUMN pattern_lineage_nodes.used_by_agents IS
    'Array of agent names that have used this pattern';

-- ============================================================================
-- PART 3: Create pattern_relationships Table
-- ============================================================================

-- Create pattern_relationships table for tracking relationships with confidence
CREATE TABLE IF NOT EXISTS pattern_relationships (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_pattern_id UUID NOT NULL REFERENCES pattern_lineage_nodes(id) ON DELETE CASCADE,
    target_pattern_id UUID NOT NULL REFERENCES pattern_lineage_nodes(id) ON DELETE CASCADE,
    relationship_type VARCHAR(50) NOT NULL,
    confidence DECIMAL(3,2) CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    created_by VARCHAR(100),

    -- Ensure no self-relationships
    CONSTRAINT no_self_relationship CHECK (source_pattern_id <> target_pattern_id),

    -- Unique constraint on source, target, and type
    CONSTRAINT unique_pattern_relationship UNIQUE (source_pattern_id, target_pattern_id, relationship_type)
);

-- Create indexes for pattern_relationships
CREATE INDEX IF NOT EXISTS idx_pattern_rel_source
    ON pattern_relationships(source_pattern_id);
CREATE INDEX IF NOT EXISTS idx_pattern_rel_target
    ON pattern_relationships(target_pattern_id);
CREATE INDEX IF NOT EXISTS idx_pattern_rel_type
    ON pattern_relationships(relationship_type);
CREATE INDEX IF NOT EXISTS idx_pattern_rel_confidence
    ON pattern_relationships(confidence DESC NULLS LAST);
CREATE INDEX IF NOT EXISTS idx_pattern_rel_created
    ON pattern_relationships(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_pattern_rel_metadata
    ON pattern_relationships USING GIN(metadata);

-- Add comments for pattern_relationships
COMMENT ON TABLE pattern_relationships IS
    'Tracks relationships between patterns with confidence scoring';
COMMENT ON COLUMN pattern_relationships.relationship_type IS
    'Type of relationship: depends_on, extends, similar_to, replaces, etc.';
COMMENT ON COLUMN pattern_relationships.confidence IS
    'Confidence score (0.0-1.0) for this relationship';

-- ============================================================================
-- PART 4: Create Trigger for Automatic Usage Tracking
-- ============================================================================

-- Function to increment pattern usage when patterns appear in manifests
CREATE OR REPLACE FUNCTION increment_pattern_usage()
RETURNS TRIGGER AS $$
DECLARE
    pattern_rec RECORD;
    agent_name_val TEXT;
    pattern_file TEXT;
    pattern_name_val TEXT;
BEGIN
    -- Extract agent name from NEW record
    agent_name_val := NEW.agent_name;

    -- Check if full_manifest_snapshot contains patterns
    -- Patterns are stored in full_manifest_snapshot->'patterns'->'available' JSONB array
    IF NEW.full_manifest_snapshot IS NOT NULL AND
       NEW.full_manifest_snapshot->'patterns'->'available' IS NOT NULL THEN

        -- Loop through each pattern in the manifest
        FOR pattern_rec IN
            SELECT
                value->>'file' as file_path,
                value->>'name' as pattern_name
            FROM jsonb_array_elements(NEW.full_manifest_snapshot->'patterns'->'available')
            WHERE value->>'file' IS NOT NULL AND value->>'name' IS NOT NULL
        LOOP
            pattern_file := pattern_rec.file_path;
            pattern_name_val := pattern_rec.pattern_name;

            -- Update usage statistics for patterns matching by file_path and pattern_name
            -- Note: file_path may be in the file_path column OR in pattern_data->>'file_path'
            UPDATE pattern_lineage_nodes
            SET
                usage_count = usage_count + 1,
                last_used_at = NOW(),
                used_by_agents = CASE
                    -- Add agent to array if not already present
                    WHEN agent_name_val IS NOT NULL AND NOT (agent_name_val = ANY(used_by_agents))
                    THEN array_append(used_by_agents, agent_name_val)
                    ELSE used_by_agents
                END
            WHERE (
                -- Match by file_path column (if populated)
                (file_path IS NOT NULL AND file_path = pattern_file)
                OR
                -- Match by pattern_data->>'file_path' (if file_path column is null)
                (file_path IS NULL AND pattern_data->>'file_path' = pattern_file)
            )
            AND pattern_name = pattern_name_val;
        END LOOP;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Create trigger on agent_manifest_injections table
-- This trigger fires after each insert to track pattern usage
DROP TRIGGER IF EXISTS increment_pattern_usage_trigger ON agent_manifest_injections;
CREATE TRIGGER increment_pattern_usage_trigger
AFTER INSERT ON agent_manifest_injections
FOR EACH ROW
EXECUTE FUNCTION increment_pattern_usage();

-- Add comment for the trigger function
COMMENT ON FUNCTION increment_pattern_usage() IS
    'Automatically updates pattern usage statistics when patterns are used in agent manifest injections';

-- ============================================================================
-- Track Migration
-- ============================================================================

-- Record this migration in schema_migrations table
INSERT INTO schema_migrations (version, description, applied_at)
VALUES (4, 'Pattern Quality and Usage Tracking - adds quality scores, usage tracking, and pattern_relationships table', NOW())
ON CONFLICT (version) DO NOTHING;
