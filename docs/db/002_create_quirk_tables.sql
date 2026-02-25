-- Reference migration: quirk_signals and quirk_findings for omninode_bridge
-- Location: docs/db/ (NOT sql/migrations/) — stored here because omniclaude
-- has an active migration freeze (OMN-2073/OMN-2055). Apply this migration
-- directly against omninode_bridge when the freeze lifts or as part of the
-- DB-per-repo boundary work.
--
-- Date: 2026-02-24
-- Purpose: Persist Quirks Detector signals and policy findings (OMN-2533 / OMN-2360)
--
-- Tables:
--   quirk_signals   - Raw detection events emitted by detector tiers
--   quirk_findings  - Policy recommendations derived from quirk_signals
--
-- Notes:
--   - evidence and suggested_exemptions are stored as JSONB arrays for flexible querying.
--   - ast_span is a two-element JSONB array [start_line, end_line].
--   - confidence is stored as NUMERIC(5,4) for 4 decimal places of precision.
--   - Both tables track created_at automatically via DEFAULT now().
--   - quirk_findings.signal_id references quirk_signals with ON DELETE CASCADE so
--     removing a signal removes its derived findings.

-- pgcrypto is required for gen_random_uuid()
-- NOTE: CREATE EXTENSION is intentionally outside the transaction block for
-- compatibility with managed PostgreSQL (RDS, Cloud SQL) where extensions cannot
-- be created inside a transaction.
CREATE EXTENSION IF NOT EXISTS pgcrypto;

BEGIN;

-- ============================================================================
-- quirk_signals — raw detection events
-- ============================================================================
CREATE TABLE IF NOT EXISTS quirk_signals (
    id                 UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    quirk_type         VARCHAR(50) NOT NULL
                           CHECK (quirk_type IN (
                               'SYCOPHANCY', 'STUB_CODE', 'NO_TESTS', 'LOW_EFFORT_PATCH',
                               'UNSAFE_ASSUMPTION', 'IGNORED_INSTRUCTIONS', 'HALLUCINATED_API'
                           )),
    session_id         TEXT        NOT NULL,
    confidence         NUMERIC(5, 4) NOT NULL
                           CHECK (confidence >= 0 AND confidence <= 1),
    evidence           JSONB       NOT NULL
                           CHECK (
                               jsonb_typeof(evidence) = 'array'
                               AND jsonb_array_length(evidence) > 0
                           ),
    stage              VARCHAR(20) NOT NULL
                           CHECK (stage IN ('OBSERVE', 'WARN', 'BLOCK')),
    detected_at        TIMESTAMPTZ NOT NULL,
    extraction_method  VARCHAR(20) NOT NULL
                           CHECK (extraction_method IN ('regex', 'AST', 'heuristic', 'model')),
    file_path          TEXT,
    diff_hunk          TEXT,
    ast_span           JSONB
                           CHECK (
                               ast_span IS NULL OR (
                                   jsonb_typeof(ast_span) = 'array'
                                   AND jsonb_array_length(ast_span) = 2
                                   AND (ast_span ->> 0)::INT <= (ast_span ->> 1)::INT
                               )
                           ),
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_quirk_signals_quirk_type
    ON quirk_signals (quirk_type);

CREATE INDEX IF NOT EXISTS idx_quirk_signals_session_id
    ON quirk_signals (session_id);

CREATE INDEX IF NOT EXISTS idx_quirk_signals_detected_at
    ON quirk_signals (detected_at DESC);

-- ============================================================================
-- quirk_findings — policy recommendations derived from a signal
-- ============================================================================
CREATE TABLE IF NOT EXISTS quirk_findings (
    id                      UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    signal_id               UUID        NOT NULL
                                REFERENCES quirk_signals (id) ON DELETE CASCADE,
    quirk_type              VARCHAR(50) NOT NULL
                                CHECK (quirk_type IN (
                                    'SYCOPHANCY', 'STUB_CODE', 'NO_TESTS', 'LOW_EFFORT_PATCH',
                                    'UNSAFE_ASSUMPTION', 'IGNORED_INSTRUCTIONS', 'HALLUCINATED_API'
                                )),
    policy_recommendation   VARCHAR(20) NOT NULL
                                CHECK (policy_recommendation IN ('observe', 'warn', 'block')),
    validator_blueprint_id  TEXT,
    suggested_exemptions    JSONB       NOT NULL DEFAULT '[]'::JSONB,
    fix_guidance            TEXT        NOT NULL,
    confidence              NUMERIC(5, 4) NOT NULL
                                CHECK (confidence >= 0 AND confidence <= 1),
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_quirk_findings_signal_id
    ON quirk_findings (signal_id);

CREATE INDEX IF NOT EXISTS idx_quirk_findings_quirk_type
    ON quirk_findings (quirk_type);

CREATE INDEX IF NOT EXISTS idx_quirk_findings_policy_recommendation
    ON quirk_findings (policy_recommendation);

-- ============================================================================
-- Migration tracking
-- ============================================================================
INSERT INTO schema_migrations (filename)
VALUES ('002_create_quirk_tables.sql')
ON CONFLICT (filename) DO NOTHING;

COMMIT;
