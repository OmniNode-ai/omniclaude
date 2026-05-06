-- Migration 001: Create delegation projection tables
-- Pinned to Postgres projection contract (OMN-10604)

CREATE TABLE IF NOT EXISTS schema_migrations (
    version         TEXT    PRIMARY KEY,
    applied_at      REAL    NOT NULL,
    description     TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS delegation_events (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    correlation_id          TEXT    NOT NULL UNIQUE,
    session_id              TEXT,
    tool_use_id             TEXT,
    hook_name               TEXT,
    task_type               TEXT    NOT NULL DEFAULT '',
    delegated_to            TEXT    NOT NULL DEFAULT '',
    model_name              TEXT    NOT NULL DEFAULT '',
    quality_gate_passed     INTEGER NOT NULL DEFAULT 0,
    quality_gate_detail     TEXT,
    latency_ms              INTEGER,
    input_hash              TEXT,
    input_redaction_policy  TEXT    NOT NULL DEFAULT 'hash_only',
    contract_version        TEXT    NOT NULL DEFAULT 'v1',
    created_at              REAL    NOT NULL
);

CREATE TABLE IF NOT EXISTS llm_call_metrics (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    input_hash          TEXT    NOT NULL UNIQUE,
    model_id            TEXT    NOT NULL,
    prompt_tokens       INTEGER NOT NULL DEFAULT 0,
    completion_tokens   INTEGER NOT NULL DEFAULT 0,
    estimated_cost_usd  REAL    NOT NULL DEFAULT 0.0,
    usage_source        TEXT    NOT NULL DEFAULT 'estimated',
    token_provenance    TEXT,
    created_at          REAL    NOT NULL
);

CREATE TABLE IF NOT EXISTS savings_estimates (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id              TEXT    NOT NULL,
    event_timestamp         REAL    NOT NULL,
    model_local             TEXT    NOT NULL,
    model_cloud_baseline    TEXT    NOT NULL,
    local_cost_usd          REAL    NOT NULL DEFAULT 0.0,
    cloud_cost_usd          REAL    NOT NULL DEFAULT 0.0,
    savings_usd             REAL    NOT NULL DEFAULT 0.0,
    baseline_model          TEXT    NOT NULL,
    pricing_manifest_version TEXT   NOT NULL DEFAULT 'v1',
    savings_method          TEXT    NOT NULL DEFAULT 'token_diff',
    usage_source            TEXT    NOT NULL DEFAULT 'estimated',
    created_at              REAL    NOT NULL,
    UNIQUE (session_id, event_timestamp, model_local, model_cloud_baseline)
);

CREATE TABLE IF NOT EXISTS delegation_event_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    envelope    TEXT    NOT NULL,
    created_at  REAL    NOT NULL
);
