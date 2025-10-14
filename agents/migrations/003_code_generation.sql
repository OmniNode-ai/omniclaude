-- Code Generation Schema (Phase 1 foundation)

BEGIN;

CREATE TABLE IF NOT EXISTS generation_sessions (
    session_id UUID PRIMARY KEY,
    correlation_id UUID UNIQUE,
    prd_content TEXT,
    workflow_run_id UUID,
    status TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    completed_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS generation_artifacts (
    artifact_id UUID PRIMARY KEY,
    session_id UUID REFERENCES generation_sessions(session_id) ON DELETE CASCADE,
    artifact_type TEXT,
    file_path TEXT,
    content TEXT,
    quality_score DECIMAL,
    validation_status TEXT,
    template_version TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS generation_intelligence (
    intelligence_id UUID PRIMARY KEY,
    session_id UUID REFERENCES generation_sessions(session_id) ON DELETE CASCADE,
    intelligence_type TEXT,
    source_service TEXT,
    intelligence_data JSONB,
    received_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS mixin_compatibility (
    mixin_name TEXT,
    compatible_with TEXT[],
    incompatible_with TEXT[],
    requires TEXT[],
    usage_count INT DEFAULT 0,
    success_rate DECIMAL
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_generation_artifacts_session ON generation_artifacts(session_id);
CREATE INDEX IF NOT EXISTS idx_generation_intelligence_session ON generation_intelligence(session_id);

COMMIT;


