# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Unit tests for omniclaude.trace.db_schema.

Tests verify:
- DDL strings contain all required tables and indexes
- Rollback DDL contains all required DROP statements
- Python dataclass row types have the correct fields
- Table name constants are correct
- All 5 tables are present in ALL_TRACE_TABLES

Note: These tests do NOT connect to a database. They validate the schema
definitions are correct and complete, which can be done without infrastructure.
"""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from omniclaude.trace.db_schema import (
    ALL_TRACE_TABLES,
    TABLE_CHANGE_FRAMES,
    TABLE_FAILURE_SIGNATURES,
    TABLE_FIX_TRANSITIONS,
    TABLE_FRAME_PR_ASSOCIATION,
    TABLE_PR_ENVELOPES,
    TRACE_MIGRATION_DDL,
    TRACE_ROLLBACK_DDL,
    RowChangeFrame,
    RowFailureSignature,
    RowFixTransition,
    RowFramePRAssociation,
    RowPREnvelope,
)

# ---------------------------------------------------------------------------
# DDL content tests
# ---------------------------------------------------------------------------


class TestMigrationDDL:
    def test_all_five_tables_created(self) -> None:
        """All 5 required tables must appear in the DDL."""
        expected_tables = [
            "change_frames",
            "failure_signatures",
            "pr_envelopes",
            "frame_pr_association",
            "fix_transitions",
        ]
        for table in expected_tables:
            assert "CREATE TABLE" in TRACE_MIGRATION_DDL
            assert table in TRACE_MIGRATION_DDL, f"Table {table} missing from DDL"

    def test_all_five_indexes_created(self) -> None:
        """All 5 required indexes must appear in the DDL."""
        expected_indexes = [
            "idx_change_frames_failure_sig",
            "idx_change_frames_base_commit",
            "idx_frame_pr_association_pr_id",
            "idx_failure_signatures_fingerprint",
            "idx_fix_transitions_failure_sig",
        ]
        for idx in expected_indexes:
            assert idx in TRACE_MIGRATION_DDL, f"Index {idx} missing from DDL"

    def test_change_frames_columns(self) -> None:
        """change_frames table must have all required columns."""
        required_cols = [
            "frame_id",
            "parent_frame_id",
            "timestamp_utc",
            "agent_id",
            "model_id",
            "base_commit",
            "repo",
            "branch_name",
            "outcome_status",
            "failure_signature_id",
            "frame_blob_ref",
        ]
        for col in required_cols:
            assert col in TRACE_MIGRATION_DDL, f"Column {col} missing from DDL"

    def test_failure_signatures_columns(self) -> None:
        """failure_signatures table must have all required columns."""
        required_cols = [
            "signature_id",
            "failure_type",
            "primary_signal",
            "fingerprint",
            "repro_command",
        ]
        for col in required_cols:
            assert col in TRACE_MIGRATION_DDL, f"Column {col} missing"

    def test_fix_transitions_columns(self) -> None:
        """fix_transitions table must have all required columns."""
        required_cols = [
            "transition_id",
            "failure_signature_id",
            "initial_frame_id",
            "success_frame_id",
            "delta_hash",
            "files_involved",
            "created_at",
        ]
        for col in required_cols:
            assert col in TRACE_MIGRATION_DDL, f"Column {col} missing"

    def test_pr_envelopes_columns(self) -> None:
        """pr_envelopes table must have all required columns."""
        required_cols = [
            "pr_id",
            "repo",
            "pr_number",
            "head_sha",
            "base_sha",
            "branch_name",
            "merged_at",
            "envelope_blob_ref",
        ]
        for col in required_cols:
            assert col in TRACE_MIGRATION_DDL, f"Column {col} missing"

    def test_frame_pr_association_columns(self) -> None:
        """frame_pr_association table must have all required columns."""
        required_cols = ["frame_id", "pr_id", "association_method"]
        for col in required_cols:
            assert col in TRACE_MIGRATION_DDL, f"Column {col} missing"

    def test_foreign_key_references(self) -> None:
        """Key foreign key relationships must be present in DDL."""
        fk_patterns = [
            "REFERENCES change_frames",
            "REFERENCES failure_signatures",
            "REFERENCES pr_envelopes",
        ]
        for pattern in fk_patterns:
            assert pattern in TRACE_MIGRATION_DDL, f"FK reference '{pattern}' missing"

    def test_primary_keys_defined(self) -> None:
        """All tables must have PRIMARY KEY defined."""
        pk_count = TRACE_MIGRATION_DDL.count("PRIMARY KEY")
        assert pk_count >= 5, (
            f"Expected at least 5 PRIMARY KEY definitions, got {pk_count}"
        )

    def test_uuid_type_used_for_frame_ids(self) -> None:
        """frame_id and related UUIDs should use UUID type."""
        assert "UUID" in TRACE_MIGRATION_DDL

    def test_timestamptz_used_for_timestamps(self) -> None:
        """Timestamps should use TIMESTAMPTZ (timezone-aware)."""
        assert "TIMESTAMPTZ" in TRACE_MIGRATION_DDL


class TestRollbackDDL:
    def test_all_five_tables_dropped(self) -> None:
        """Rollback DDL must DROP all 5 tables."""
        expected_drops = [
            "change_frames",
            "failure_signatures",
            "pr_envelopes",
            "frame_pr_association",
            "fix_transitions",
        ]
        for table in expected_drops:
            assert table in TRACE_ROLLBACK_DDL, (
                f"Table {table} missing from rollback DDL"
            )

    def test_drop_uses_if_exists(self) -> None:
        """Rollback DDL should use IF EXISTS for idempotent rollback."""
        assert "IF EXISTS" in TRACE_ROLLBACK_DDL

    def test_dependency_order_in_rollback(self) -> None:
        """fix_transitions must be dropped before failure_signatures (FK dependency)."""
        fix_pos = TRACE_ROLLBACK_DDL.find("fix_transitions")
        sig_pos = TRACE_ROLLBACK_DDL.find("failure_signatures")
        assert fix_pos < sig_pos, (
            "fix_transitions must be dropped before failure_signatures"
        )

    def test_change_frames_dropped_before_failure_signatures(self) -> None:
        """change_frames must be dropped before failure_signatures."""
        frames_pos = TRACE_ROLLBACK_DDL.find("change_frames")
        sig_pos = TRACE_ROLLBACK_DDL.find("failure_signatures")
        assert frames_pos < sig_pos, (
            "change_frames must be dropped before failure_signatures"
        )


# ---------------------------------------------------------------------------
# Dataclass row tests
# ---------------------------------------------------------------------------


class TestRowChangeFrame:
    def test_construction(self) -> None:
        """RowChangeFrame can be constructed with required fields."""
        row = RowChangeFrame(
            frame_id=uuid4(),
            timestamp_utc=datetime.now(),  # noqa: DTZ005
            agent_id="polymorphic-agent",
            model_id="claude-opus-4-6",
            base_commit="abc123",
            repo="org/repo",
            branch_name="main",
            outcome_status="pass",
            frame_blob_ref="s3://bucket/frame.json",
        )
        assert row.outcome_status == "pass"
        assert row.parent_frame_id is None
        assert row.failure_signature_id is None

    def test_optional_fields(self) -> None:
        """Optional fields default to None."""
        row = RowChangeFrame(
            frame_id=uuid4(),
            timestamp_utc=datetime.now(),  # noqa: DTZ005
            agent_id="agent",
            model_id="model",
            base_commit="abc",
            repo="repo",
            branch_name="branch",
            outcome_status="fail",
            frame_blob_ref="ref",
            parent_frame_id=uuid4(),
            failure_signature_id="sig-001",
        )
        assert row.failure_signature_id == "sig-001"


class TestRowFailureSignature:
    def test_construction(self) -> None:
        """RowFailureSignature can be constructed with all required fields."""
        row = RowFailureSignature(
            signature_id="sig-abc123",
            failure_type="test_fail",
            primary_signal="AssertionError in test_router",
            fingerprint="sha256-deadbeef" * 4,
            repro_command="uv run pytest tests/test_router.py -v",
        )
        assert row.signature_id == "sig-abc123"
        assert row.failure_type == "test_fail"


class TestRowPREnvelope:
    def test_construction(self) -> None:
        """RowPREnvelope can be constructed with required fields."""
        row = RowPREnvelope(
            pr_id=uuid4(),
            repo="org/repo",
            pr_number=42,
            head_sha="abc123",
            base_sha="def456",
            branch_name="feat/my-feature",
            envelope_blob_ref="s3://bucket/pr.json",
        )
        assert row.pr_number == 42
        assert row.merged_at is None

    def test_merged_at_optional(self) -> None:
        """merged_at is optional and defaults to None."""
        row = RowPREnvelope(
            pr_id=uuid4(),
            repo="org/repo",
            pr_number=1,
            head_sha="a",
            base_sha="b",
            branch_name="feat",
            envelope_blob_ref="ref",
            merged_at=datetime.now(),  # noqa: DTZ005
        )
        assert row.merged_at is not None


class TestRowFramePRAssociation:
    def test_construction(self) -> None:
        """RowFramePRAssociation can be constructed with all required fields."""
        row = RowFramePRAssociation(
            frame_id=uuid4(),
            pr_id=uuid4(),
            association_method="commit_ancestry",
        )
        assert row.association_method == "commit_ancestry"


class TestRowFixTransition:
    def test_construction(self) -> None:
        """RowFixTransition can be constructed with all required fields."""
        row = RowFixTransition(
            transition_id=uuid4(),
            failure_signature_id="sig-001",
            initial_frame_id=uuid4(),
            success_frame_id=uuid4(),
            delta_hash="sha256-abc123",
            files_involved=["src/router.py", "tests/test_router.py"],
            created_at=datetime.now(),  # noqa: DTZ005
        )
        assert len(row.files_involved) == 2
        assert row.failure_signature_id == "sig-001"


# ---------------------------------------------------------------------------
# Table name constant tests
# ---------------------------------------------------------------------------


class TestTableNameConstants:
    def test_table_name_values(self) -> None:
        """Table name constants must match expected SQL identifiers."""
        assert TABLE_CHANGE_FRAMES == "change_frames"
        assert TABLE_FAILURE_SIGNATURES == "failure_signatures"
        assert TABLE_PR_ENVELOPES == "pr_envelopes"
        assert TABLE_FRAME_PR_ASSOCIATION == "frame_pr_association"
        assert TABLE_FIX_TRANSITIONS == "fix_transitions"

    def test_all_trace_tables_list(self) -> None:
        """ALL_TRACE_TABLES must contain all 5 table names."""
        assert len(ALL_TRACE_TABLES) == 5
        assert TABLE_CHANGE_FRAMES in ALL_TRACE_TABLES
        assert TABLE_FAILURE_SIGNATURES in ALL_TRACE_TABLES
        assert TABLE_PR_ENVELOPES in ALL_TRACE_TABLES
        assert TABLE_FRAME_PR_ASSOCIATION in ALL_TRACE_TABLES
        assert TABLE_FIX_TRANSITIONS in ALL_TRACE_TABLES

    def test_failure_signatures_first_in_list(self) -> None:
        """failure_signatures must be first (no FK dependencies on it)."""
        assert ALL_TRACE_TABLES[0] == TABLE_FAILURE_SIGNATURES
