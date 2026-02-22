"""Database schema definitions for the Agent Trace system.

This module provides:
1. SQL DDL strings for all 5 agent trace tables
2. Python dataclass representations (no SQLAlchemy dependency) for use
   in the persistence layer while migration freeze is active

MIGRATION FREEZE NOTICE (OMN-2055):
A migration freeze is active (.migration_freeze). The Alembic migration
for these tables (TRACE_MIGRATION_DDL below) must be applied once the freeze
lifts. Do not create an alembic migration file until OMN-2055 is resolved.

Stage 7 of DESIGN_AGENT_TRACE_PR_DEBUGGING_SYSTEM.md
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# SQL DDL — authoritative schema definition
# ---------------------------------------------------------------------------

TRACE_MIGRATION_DDL = """
-- Agent Trace System Tables
-- MIGRATION FREEZE: Do not apply until OMN-2055 is resolved.
-- Created by: OMN-2406 TRACE-02

-- Failure signatures must be created first (referenced by change_frames)
CREATE TABLE IF NOT EXISTS failure_signatures (
    signature_id        TEXT PRIMARY KEY,
    failure_type        TEXT NOT NULL,
    primary_signal      TEXT NOT NULL,
    fingerprint         TEXT NOT NULL UNIQUE,
    repro_command       TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_failure_signatures_fingerprint
    ON failure_signatures(fingerprint);

-- Main frame table (immutable records — no updates, no deletes)
CREATE TABLE IF NOT EXISTS change_frames (
    frame_id            UUID PRIMARY KEY,
    parent_frame_id     UUID REFERENCES change_frames(frame_id),
    timestamp_utc       TIMESTAMPTZ NOT NULL,
    agent_id            TEXT NOT NULL,
    model_id            TEXT NOT NULL,
    base_commit         TEXT NOT NULL,
    repo                TEXT NOT NULL,
    branch_name         TEXT NOT NULL,
    outcome_status      TEXT NOT NULL,
    failure_signature_id TEXT REFERENCES failure_signatures(signature_id),
    frame_blob_ref      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_change_frames_failure_sig
    ON change_frames(failure_signature_id);

CREATE INDEX IF NOT EXISTS idx_change_frames_base_commit
    ON change_frames(base_commit);

-- PR envelopes (containers for frames)
CREATE TABLE IF NOT EXISTS pr_envelopes (
    pr_id               UUID PRIMARY KEY,
    repo                TEXT NOT NULL,
    pr_number           INT NOT NULL,
    head_sha            TEXT NOT NULL,
    base_sha            TEXT NOT NULL,
    branch_name         TEXT NOT NULL,
    merged_at           TIMESTAMPTZ,
    envelope_blob_ref   TEXT NOT NULL
);

-- Frame to PR association (many-to-many)
CREATE TABLE IF NOT EXISTS frame_pr_association (
    frame_id            UUID REFERENCES change_frames(frame_id),
    pr_id               UUID REFERENCES pr_envelopes(pr_id),
    association_method  TEXT NOT NULL,
    PRIMARY KEY (frame_id, pr_id)
);

CREATE INDEX IF NOT EXISTS idx_frame_pr_association_pr_id
    ON frame_pr_association(pr_id);

-- Fix transitions (failure -> success pairs)
CREATE TABLE IF NOT EXISTS fix_transitions (
    transition_id       UUID PRIMARY KEY,
    failure_signature_id TEXT REFERENCES failure_signatures(signature_id),
    initial_frame_id    UUID REFERENCES change_frames(frame_id),
    success_frame_id    UUID REFERENCES change_frames(frame_id),
    delta_hash          TEXT NOT NULL,
    files_involved      TEXT[] NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_fix_transitions_failure_sig
    ON fix_transitions(failure_signature_id);
"""

TRACE_ROLLBACK_DDL = """
-- Rollback for Agent Trace System Tables
-- Drop in reverse dependency order
DROP TABLE IF EXISTS fix_transitions;
DROP TABLE IF EXISTS frame_pr_association;
DROP TABLE IF EXISTS pr_envelopes;
DROP TABLE IF EXISTS change_frames;
DROP TABLE IF EXISTS failure_signatures;
"""


# ---------------------------------------------------------------------------
# Python dataclass table definitions (no SQLAlchemy dependency)
# Used by persistence layer until migration freeze lifts and ORM is added.
# ---------------------------------------------------------------------------

from dataclasses import dataclass, field  # noqa: E402
from datetime import datetime  # noqa: E402
from uuid import UUID  # noqa: E402


@dataclass
class RowChangeFrame:
    """Represents a row in the change_frames table.

    All fields map directly to the DB column of the same name.
    Records are immutable after insert — never update, never delete.
    """

    frame_id: UUID
    timestamp_utc: datetime
    agent_id: str
    model_id: str
    base_commit: str
    repo: str
    branch_name: str
    outcome_status: str
    frame_blob_ref: str
    parent_frame_id: UUID | None = None
    failure_signature_id: str | None = None

    TABLE_NAME: str = field(default="change_frames", init=False, repr=False)


@dataclass
class RowFailureSignature:
    """Represents a row in the failure_signatures table.

    Records are immutable after insert.
    Uniqueness enforced by the fingerprint column.
    """

    signature_id: str
    failure_type: str
    primary_signal: str
    fingerprint: str
    repro_command: str

    TABLE_NAME: str = field(default="failure_signatures", init=False, repr=False)


@dataclass
class RowPREnvelope:
    """Represents a row in the pr_envelopes table."""

    pr_id: UUID
    repo: str
    pr_number: int
    head_sha: str
    base_sha: str
    branch_name: str
    envelope_blob_ref: str
    merged_at: datetime | None = None

    TABLE_NAME: str = field(default="pr_envelopes", init=False, repr=False)


@dataclass
class RowFramePRAssociation:
    """Represents a row in the frame_pr_association table."""

    frame_id: UUID
    pr_id: UUID
    association_method: str

    TABLE_NAME: str = field(default="frame_pr_association", init=False, repr=False)


@dataclass
class RowFixTransition:
    """Represents a row in the fix_transitions table."""

    transition_id: UUID
    initial_frame_id: UUID
    success_frame_id: UUID
    delta_hash: str
    files_involved: list[str]
    created_at: datetime
    failure_signature_id: str | None = None

    TABLE_NAME: str = field(default="fix_transitions", init=False, repr=False)


# ---------------------------------------------------------------------------
# Table name constants (for use in query builders)
# ---------------------------------------------------------------------------

TABLE_CHANGE_FRAMES = "change_frames"
TABLE_FAILURE_SIGNATURES = "failure_signatures"
TABLE_PR_ENVELOPES = "pr_envelopes"
TABLE_FRAME_PR_ASSOCIATION = "frame_pr_association"
TABLE_FIX_TRANSITIONS = "fix_transitions"

ALL_TRACE_TABLES = [
    TABLE_FAILURE_SIGNATURES,
    TABLE_CHANGE_FRAMES,
    TABLE_PR_ENVELOPES,
    TABLE_FRAME_PR_ASSOCIATION,
    TABLE_FIX_TRANSITIONS,
]
