-- SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
-- SPDX-License-Identifier: MIT
--
-- Schema: quirk_stage_config + quirk_stage_audit tables
--
-- PURPOSE: Documents the DB schema for ValidatorRolloutController (OMN-2564).
--
-- STATUS: Pending migration freeze lift (OMN-2055 / OMN-2073).
--         Once .migration_freeze is removed, apply via Alembic migration.
--         Do NOT add this as a numbered file under sql/migrations/ until
--         the freeze is explicitly lifted.
--
-- Related:
--     OMN-2564: ValidatorRolloutController implementation
--     OMN-2055: DB-per-repo refactor (migration freeze parent)
--     OMN-2073: Migration freeze tracking ticket

-- ---------------------------------------------------------------------------
-- quirk_stage_config
-- ---------------------------------------------------------------------------
-- Stores the current enforcement stage for each QuirkType.
-- One row per QuirkType; upserted on each stage promotion.

CREATE TABLE IF NOT EXISTS quirk_stage_config (
    quirk_type     TEXT        NOT NULL PRIMARY KEY,
    current_stage  TEXT        NOT NULL DEFAULT 'OBSERVE',
    promoted_at    TIMESTAMPTZ,
    approved_by    TEXT,                -- e-mail of approving operator (BLOCK only)
    notes          TEXT,
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT quirk_stage_config_stage_check
        CHECK (current_stage IN ('OBSERVE', 'WARN', 'BLOCK'))
);

-- ---------------------------------------------------------------------------
-- quirk_stage_audit
-- ---------------------------------------------------------------------------
-- Immutable audit log of every stage promotion.
-- Append-only; rows are never updated or deleted.

CREATE TABLE IF NOT EXISTS quirk_stage_audit (
    id             BIGSERIAL   NOT NULL PRIMARY KEY,
    quirk_type     TEXT        NOT NULL,
    from_stage     TEXT        NOT NULL,
    to_stage       TEXT        NOT NULL,
    promoted_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    approved_by    TEXT,
    notes          TEXT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT quirk_stage_audit_from_stage_check
        CHECK (from_stage IN ('OBSERVE', 'WARN', 'BLOCK')),
    CONSTRAINT quirk_stage_audit_to_stage_check
        CHECK (to_stage IN ('OBSERVE', 'WARN', 'BLOCK'))
);

-- Index: recent audit entries by quirk_type
CREATE INDEX IF NOT EXISTS quirk_stage_audit_quirk_type_idx
    ON quirk_stage_audit (quirk_type, promoted_at DESC);
