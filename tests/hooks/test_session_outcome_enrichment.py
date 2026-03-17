# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Unit tests for ModelSessionOutcome enrichment fields (OMN-5184).

Tests:
    1. Enriched fields present and serialize correctly
    2. Existing events without new fields still validate (backward compatibility)
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from omnibase_core.enums import EnumClaudeCodeSessionOutcome

from omniclaude.hooks.schemas import ModelSessionOutcome

pytestmark = pytest.mark.unit


class TestSessionOutcomeEnrichment:
    """Test OMN-5184 enrichment fields on ModelSessionOutcome."""

    def test_enriched_fields_serialize(self) -> None:
        """All 9 enrichment fields present in serialized output when provided."""
        event = ModelSessionOutcome(
            session_id="sess-123",
            outcome=EnumClaudeCodeSessionOutcome.SUCCESS,
            emitted_at=datetime(2026, 3, 17, 12, 0, 0, tzinfo=UTC),
            intent_class="code_generation",
            token_count=5000,
            cost_usd=0.0,
            duration_ms=45000,
            task_type="feature",
            model_id="claude-sonnet-4-6",
            pattern_id="pattern-abc",
            treatment_group="treatment",
            outcome_score=0.85,
        )

        data = event.model_dump(mode="json")
        assert data["intent_class"] == "code_generation"
        assert data["token_count"] == 5000
        assert data["cost_usd"] == 0.0
        assert data["duration_ms"] == 45000
        assert data["task_type"] == "feature"
        assert data["model_id"] == "claude-sonnet-4-6"
        assert data["pattern_id"] == "pattern-abc"
        assert data["treatment_group"] == "treatment"
        assert data["outcome_score"] == 0.85

    def test_backward_compatibility_no_enrichment(self) -> None:
        """Events without enrichment fields still validate (None defaults)."""
        event = ModelSessionOutcome(
            session_id="sess-456",
            outcome=EnumClaudeCodeSessionOutcome.FAILED,
            emitted_at=datetime(2026, 3, 17, 12, 0, 0, tzinfo=UTC),
        )

        assert event.intent_class is None
        assert event.token_count is None
        assert event.cost_usd is None
        assert event.duration_ms is None
        assert event.task_type is None
        assert event.model_id is None
        assert event.pattern_id is None
        assert event.treatment_group is None
        assert event.outcome_score is None

        # Serialization should include None fields
        data = event.model_dump(mode="json")
        assert "intent_class" in data
        assert data["intent_class"] is None

    def test_partial_enrichment(self) -> None:
        """Some enrichment fields can be provided while others remain None."""
        event = ModelSessionOutcome(
            session_id="sess-789",
            outcome=EnumClaudeCodeSessionOutcome.SUCCESS,
            emitted_at=datetime(2026, 3, 17, 12, 0, 0, tzinfo=UTC),
            duration_ms=30000,
            model_id="claude-sonnet-4-6",
        )

        assert event.duration_ms == 30000
        assert event.model_id == "claude-sonnet-4-6"
        assert event.intent_class is None
        assert event.pattern_id is None

    def test_outcome_score_range_validation(self) -> None:
        """outcome_score must be between 0.0 and 1.0."""
        with pytest.raises(Exception):
            ModelSessionOutcome(
                session_id="sess-bad",
                outcome=EnumClaudeCodeSessionOutcome.SUCCESS,
                emitted_at=datetime(2026, 3, 17, 12, 0, 0, tzinfo=UTC),
                outcome_score=1.5,
            )

    def test_roundtrip_serialization_with_enrichment(self) -> None:
        """Roundtrip: model -> JSON -> model preserves all fields."""
        event = ModelSessionOutcome(
            session_id="sess-rt",
            outcome=EnumClaudeCodeSessionOutcome.ABANDONED,
            emitted_at=datetime(2026, 3, 17, 12, 0, 0, tzinfo=UTC),
            intent_class="debugging",
            token_count=1200,
            duration_ms=15000,
        )

        data = event.model_dump(mode="json")
        reconstructed = ModelSessionOutcome.model_validate(data)
        assert reconstructed == event
