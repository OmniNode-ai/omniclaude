-- Reference migration: skill_execution_logs for Kafka-to-table projection (OMN-2778)
-- Location: docs/db/ (NOT sql/migrations/) — stored here because omniclaude
-- has an active migration freeze (OMN-2073/OMN-2055). Apply this migration
-- directly once the freeze lifts or as part of the DB-per-repo boundary work.
--
-- Date: 2026-02-25
-- Purpose: Persist skill lifecycle events from onex.evt.omniclaude.skill-completed.v1
--          into a queryable PostgreSQL table for pipeline-metrics and observability.
--
-- Ticket: OMN-2778
-- Parent: OMN-2773 (skill lifecycle events Kafka emission)
--
-- Tables:
--   skill_execution_logs  - Projection of skill-completed Kafka events
--
-- Notes:
--   - Schema mirrors agent_execution_logs with additional fields:
--     run_id, skill_id, repo_id, started_emit_failed.
--   - run_id is the join key between skill-started and skill-completed events.
--   - ON CONFLICT DO UPDATE (upsert) on run_id for idempotent consumer replays.
--   - Partition candidate: partition by emitted_at (monthly) once volume warrants it.

-- pgcrypto is required for gen_random_uuid()
-- NOTE: CREATE EXTENSION is intentionally outside the transaction block for
-- compatibility with managed PostgreSQL (RDS, Cloud SQL) where extensions cannot
-- be created inside a transaction.
CREATE EXTENSION IF NOT EXISTS pgcrypto;

BEGIN;

-- ============================================================================
-- skill_execution_logs — projection of onex.evt.omniclaude.skill-completed.v1
-- ============================================================================
CREATE TABLE IF NOT EXISTS skill_execution_logs (
    -- Primary key: execution_id is synthesised from run_id for consistency
    -- with agent_execution_logs which uses a UUID PK.
    execution_id    UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Join key shared by skill-started and skill-completed events.
    -- Unique constraint enables upsert idempotency for consumer replays.
    run_id          UUID NOT NULL UNIQUE,

    -- Human-readable skill identifier (e.g. "pr-review", "ticket-pipeline").
    skill_name      TEXT NOT NULL,

    -- Repo-relative skill path (e.g. "plugins/onex/skills/pipeline-metrics").
    -- NULL when the consumer cannot determine the path (pre-OMN-2773 events).
    skill_id        TEXT,

    -- Repository identifier (e.g. "omniclaude").
    -- Prevents cross-repo run_id collisions.
    repo_id         TEXT NOT NULL,

    -- End-to-end correlation ID from the originating request.
    correlation_id  UUID,

    -- Optional Claude Code session identifier.
    session_id      TEXT,

    -- Outcome of the skill invocation.
    -- Locked to three values to prevent string drift.
    status          TEXT NOT NULL CHECK (status IN ('success', 'failed', 'partial')),

    -- Wall-clock duration from perf_counter() (NTP-immune).
    duration_ms     INTEGER NOT NULL CHECK (duration_ms >= 0),

    -- Exception class name if skill raised, else NULL.
    error_type      TEXT,

    -- True when the skill-started emission failed before skill-completed was
    -- emitted. Consumers can use this flag to detect orphaned completed events.
    started_emit_failed BOOLEAN NOT NULL DEFAULT FALSE,

    -- UTC timestamp when the skill-completed event was emitted.
    emitted_at      TIMESTAMPTZ NOT NULL,

    -- Row insertion timestamp (set by the consumer on write).
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- Indexes
-- ---------------------------------------------------------------------------

-- Support range queries in pipeline-metrics (Step 4: skill duration by window)
CREATE INDEX IF NOT EXISTS idx_skill_execution_logs_emitted_at
    ON skill_execution_logs (emitted_at);

-- Support skill-level aggregation (p50 duration, call_count by skill_name)
CREATE INDEX IF NOT EXISTS idx_skill_execution_logs_skill_name
    ON skill_execution_logs (skill_name);

-- Support status-filtered queries (failure rate dashboards)
CREATE INDEX IF NOT EXISTS idx_skill_execution_logs_status
    ON skill_execution_logs (status);

-- Support repo-scoped queries
CREATE INDEX IF NOT EXISTS idx_skill_execution_logs_repo_id
    ON skill_execution_logs (repo_id);

COMMIT;
