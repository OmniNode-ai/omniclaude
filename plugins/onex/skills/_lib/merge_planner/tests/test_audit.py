# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for QPM audit ledger."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from merge_planner.audit import list_recent_audits, read_audit, write_audit
from merge_planner.models import ModelQPMAuditEntry


@pytest.fixture
def sample_audit() -> ModelQPMAuditEntry:
    now = datetime.now(UTC)
    return ModelQPMAuditEntry(
        run_id="qpm-test123",
        timestamp=now,
        mode="shadow",
        repos_queried=["OmniNode-ai/omnibase_core"],
        repo_fetch_errors={},
        promotion_threshold=0.3,
        max_promotions=3,
        records=[],
        promotions_executed=1,
        promotions_held=1,
    )


@pytest.mark.unit
class TestAuditRoundTrip:
    def test_write_read_round_trip(
        self, sample_audit: ModelQPMAuditEntry, tmp_path: pytest.TempPathFactory
    ) -> None:
        path = write_audit(sample_audit, root=tmp_path)
        assert path.exists()
        restored = read_audit("qpm-test123", root=tmp_path)
        assert restored is not None
        assert restored.run_id == sample_audit.run_id
        assert restored.promotions_executed == 1

    def test_read_missing_returns_none(self, tmp_path: pytest.TempPathFactory) -> None:
        assert read_audit("nonexistent", root=tmp_path) is None

    def test_write_idempotent(
        self, sample_audit: ModelQPMAuditEntry, tmp_path: pytest.TempPathFactory
    ) -> None:
        write_audit(sample_audit, root=tmp_path)
        write_audit(sample_audit, root=tmp_path)  # No error on overwrite
        assert read_audit("qpm-test123", root=tmp_path) is not None

    def test_list_recent_ordering(self, tmp_path: pytest.TempPathFactory) -> None:
        now = datetime.now(UTC)
        for i in range(5):
            entry = ModelQPMAuditEntry(
                run_id=f"qpm-{i:03d}",
                timestamp=now,
                mode="shadow",
                repos_queried=[],
                repo_fetch_errors={},
                promotion_threshold=0.3,
                max_promotions=3,
                records=[],
                promotions_executed=0,
                promotions_held=0,
            )
            write_audit(entry, root=tmp_path)
        recent = list_recent_audits(limit=3, root=tmp_path)
        assert len(recent) == 3

    def test_list_empty_root(self, tmp_path: pytest.TempPathFactory) -> None:
        empty = tmp_path / "empty"
        result = list_recent_audits(root=empty)
        assert result == []
