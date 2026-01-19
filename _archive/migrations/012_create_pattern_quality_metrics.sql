-- Migration 012: Create pattern_quality_metrics Table
-- Date: 2025-11-02
-- Purpose: Create table for storing pattern quality metrics
--
-- This table stores quality scores for code patterns from Qdrant.
-- Quality metrics are used to filter and rank patterns during manifest injection.

BEGIN;

-- Create pattern_quality_metrics table
CREATE TABLE IF NOT EXISTS pattern_quality_metrics (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    pattern_id uuid NOT NULL,
    quality_score double precision NOT NULL CHECK (quality_score >= 0 AND quality_score <= 1),
    confidence double precision NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    measurement_timestamp timestamp with time zone NOT NULL DEFAULT NOW(),
    version text DEFAULT '1.0.0',
    metadata jsonb DEFAULT '{}'::jsonb,
    created_at timestamp with time zone DEFAULT NOW(),
    updated_at timestamp with time zone DEFAULT NOW()
);

-- Create index on pattern_id for lookups
CREATE INDEX IF NOT EXISTS idx_pattern_quality_metrics_pattern_id
    ON pattern_quality_metrics(pattern_id);

-- Create index on quality_score for filtering
CREATE INDEX IF NOT EXISTS idx_pattern_quality_metrics_quality_score
    ON pattern_quality_metrics(quality_score DESC);

-- Create index on measurement_timestamp
CREATE INDEX IF NOT EXISTS idx_pattern_quality_metrics_measurement_timestamp
    ON pattern_quality_metrics(measurement_timestamp DESC);

-- Create GIN index on metadata for JSONB queries
CREATE INDEX IF NOT EXISTS idx_pattern_quality_metrics_metadata
    ON pattern_quality_metrics USING GIN(metadata);

-- Add table comment
COMMENT ON TABLE pattern_quality_metrics IS
'Quality metrics for code patterns from Qdrant. Scores patterns across multiple dimensions for manifest injection filtering.';

-- Add column comments
COMMENT ON COLUMN pattern_quality_metrics.pattern_id IS
'Pattern UUID from Qdrant. No FK constraint to allow scoring all patterns independently of lineage tracking.';

COMMENT ON COLUMN pattern_quality_metrics.quality_score IS
'Composite quality score (0.0-1.0). Weighted average of all quality dimensions.';

COMMENT ON COLUMN pattern_quality_metrics.confidence IS
'Confidence score (0.0-1.0) from Archon Intelligence for this pattern.';

COMMENT ON COLUMN pattern_quality_metrics.measurement_timestamp IS
'When this quality measurement was taken. Updated on upsert.';

COMMENT ON COLUMN pattern_quality_metrics.version IS
'Quality scoring algorithm version. Allows tracking score changes across algorithm updates.';

COMMENT ON COLUMN pattern_quality_metrics.metadata IS
'JSONB containing dimension scores: completeness_score, documentation_score, onex_compliance_score, metadata_richness_score, complexity_score.';

-- Verify table was created
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public'
        AND table_name = 'pattern_quality_metrics'
    ) THEN
        RAISE EXCEPTION 'pattern_quality_metrics table was not created';
    END IF;

    RAISE NOTICE 'Successfully created pattern_quality_metrics table';
END $$;

COMMIT;

-- Verification query (run after migration)
-- SELECT COUNT(*) FROM pattern_quality_metrics;
-- SELECT * FROM pg_indexes WHERE tablename = 'pattern_quality_metrics';
