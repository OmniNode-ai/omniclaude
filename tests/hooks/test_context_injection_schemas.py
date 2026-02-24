# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Tests for context injection event schemas.

Validates ONEX-compliant event schemas for context injection following
the registration events pattern from omnibase_infra.

ONEX Compliance Tests:
- entity_id: Required partition key (no default)
- correlation_id: Required for distributed tracing (no default)
- causation_id: Required for event chain tracking (no default)
- emitted_at: Required, must be timezone-aware (no default_factory!)
- Immutability (frozen=True)
- Extra fields forbidden (extra="forbid")
- from_attributes=True for ORM compatibility
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from omniclaude.hooks import (
    ContextSource,
    HookEventType,
    ModelHookContextInjectedPayload,
    ModelHookEventEnvelope,
)

# All tests in this module are unit tests
pytestmark = pytest.mark.unit


# =============================================================================
# Helper Factories
# =============================================================================


def make_timestamp() -> datetime:
    """Create a valid timezone-aware timestamp."""
    return datetime.now(UTC)


def make_entity_id() -> UUID:
    """Create a valid entity ID."""
    return uuid4()


def make_correlation_id() -> UUID:
    """Create a valid correlation ID."""
    return uuid4()


def make_causation_id() -> UUID:
    """Create a valid causation ID."""
    return uuid4()


def make_base_payload_kwargs() -> dict:
    """Create base keyword arguments for payload construction."""
    session_id = make_entity_id()
    return {
        "entity_id": session_id,
        "session_id": str(session_id),
        "correlation_id": make_correlation_id(),
        "causation_id": make_causation_id(),
        "emitted_at": make_timestamp(),
    }


# =============================================================================
# ContextSource Enum Tests
# =============================================================================


class TestContextSource:
    """Tests for ContextSource enum."""

    def test_all_values_exist(self) -> None:
        """All expected context source values are defined."""
        assert ContextSource.DATABASE == "database"
        assert ContextSource.SESSION_AGGREGATOR == "session_aggregator"
        assert ContextSource.RAG_QUERY == "rag_query"
        assert ContextSource.FALLBACK_STATIC == "fallback_static"
        assert ContextSource.NONE == "none"

    def test_is_str_enum(self) -> None:
        """ContextSource values are strings (StrEnum)."""
        assert isinstance(ContextSource.DATABASE, str)
        assert isinstance(ContextSource.SESSION_AGGREGATOR, str)
        assert isinstance(ContextSource.RAG_QUERY, str)
        assert isinstance(ContextSource.FALLBACK_STATIC, str)
        assert isinstance(ContextSource.NONE, str)

    def test_string_comparison(self) -> None:
        """ContextSource can be compared to strings."""
        assert ContextSource.DATABASE == "database"
        assert ContextSource.RAG_QUERY == "rag_query"
        assert ContextSource.NONE == "none"

    def test_has_five_values(self) -> None:
        """ContextSource has exactly 5 defined values."""
        assert len(ContextSource) == 5


# =============================================================================
# ModelHookContextInjectedPayload Tests
# =============================================================================


class TestModelHookContextInjectedPayload:
    """Tests for ModelHookContextInjectedPayload."""

    def test_has_required_fields(self) -> None:
        """Payload defines all required ONEX envelope fields."""
        fields = ModelHookContextInjectedPayload.model_fields
        # ONEX envelope fields
        assert "entity_id" in fields
        assert "session_id" in fields
        assert "correlation_id" in fields
        assert "causation_id" in fields
        assert "emitted_at" in fields
        # Domain-specific fields
        assert "context_source" in fields
        assert "pattern_count" in fields
        assert "context_size_bytes" in fields
        assert "agent_domain" in fields
        assert "min_confidence_threshold" in fields
        assert "retrieval_duration_ms" in fields

    def test_create_minimal(self) -> None:
        """Test creating payload with minimal required fields."""
        base = make_base_payload_kwargs()
        payload = ModelHookContextInjectedPayload(
            **base,
            context_source=ContextSource.DATABASE,
            pattern_count=3,
            context_size_bytes=1024,
            retrieval_duration_ms=50,
        )
        assert payload.pattern_count == 3
        assert payload.context_source == ContextSource.DATABASE
        assert payload.context_size_bytes == 1024
        assert payload.retrieval_duration_ms == 50
        # Defaults
        assert payload.agent_domain is None
        assert payload.min_confidence_threshold == 0.7

    def test_create_full(self) -> None:
        """Test creating payload with all fields."""
        base = make_base_payload_kwargs()
        payload = ModelHookContextInjectedPayload(
            **base,
            context_source=ContextSource.RAG_QUERY,
            pattern_count=5,
            context_size_bytes=2048,
            agent_domain="code_review",
            min_confidence_threshold=0.8,
            retrieval_duration_ms=100,
        )
        assert payload.context_source == ContextSource.RAG_QUERY
        assert payload.agent_domain == "code_review"
        assert payload.min_confidence_threshold == 0.8

    def test_entity_id_is_required(self) -> None:
        """entity_id is required, not auto-generated."""
        with pytest.raises(ValidationError) as exc_info:
            ModelHookContextInjectedPayload(
                # Missing entity_id
                session_id="test",
                correlation_id=make_correlation_id(),
                causation_id=make_causation_id(),
                emitted_at=make_timestamp(),
                context_source=ContextSource.NONE,
                pattern_count=0,
                context_size_bytes=0,
                retrieval_duration_ms=0,
            )
        assert "entity_id" in str(exc_info.value)

    def test_correlation_id_is_required(self) -> None:
        """correlation_id is required, not auto-generated (ONEX compliance)."""
        with pytest.raises(ValidationError) as exc_info:
            ModelHookContextInjectedPayload(
                entity_id=make_entity_id(),
                session_id="test",
                # Missing correlation_id - should raise
                causation_id=make_causation_id(),
                emitted_at=make_timestamp(),
                context_source=ContextSource.NONE,
                pattern_count=0,
                context_size_bytes=0,
                retrieval_duration_ms=0,
            )
        assert "correlation_id" in str(exc_info.value)

    def test_causation_id_is_required(self) -> None:
        """causation_id is required for event chain tracking."""
        with pytest.raises(ValidationError) as exc_info:
            ModelHookContextInjectedPayload(
                entity_id=make_entity_id(),
                session_id="test",
                correlation_id=make_correlation_id(),
                # Missing causation_id
                emitted_at=make_timestamp(),
                context_source=ContextSource.NONE,
                pattern_count=0,
                context_size_bytes=0,
                retrieval_duration_ms=0,
            )
        assert "causation_id" in str(exc_info.value)

    def test_emitted_at_is_required(self) -> None:
        """emitted_at is required, not auto-generated."""
        with pytest.raises(ValidationError) as exc_info:
            ModelHookContextInjectedPayload(
                entity_id=make_entity_id(),
                session_id="test",
                correlation_id=make_correlation_id(),
                causation_id=make_causation_id(),
                # Missing emitted_at
                context_source=ContextSource.NONE,
                pattern_count=0,
                context_size_bytes=0,
                retrieval_duration_ms=0,
            )
        assert "emitted_at" in str(exc_info.value)


# =============================================================================
# Pattern Count Bounds Tests
# =============================================================================


class TestPatternCountBounds:
    """Tests for pattern_count validation bounds (0-100)."""

    def test_pattern_count_zero_valid(self) -> None:
        """pattern_count at lower bound (0) is valid."""
        base = make_base_payload_kwargs()
        payload = ModelHookContextInjectedPayload(
            **base,
            context_source=ContextSource.NONE,
            pattern_count=0,
            context_size_bytes=0,
            retrieval_duration_ms=0,
        )
        assert payload.pattern_count == 0

    def test_pattern_count_max_valid(self) -> None:
        """pattern_count at upper bound (100) is valid."""
        base = make_base_payload_kwargs()
        payload = ModelHookContextInjectedPayload(
            **base,
            context_source=ContextSource.DATABASE,
            pattern_count=100,
            context_size_bytes=1000,
            retrieval_duration_ms=50,
        )
        assert payload.pattern_count == 100

    def test_pattern_count_negative_invalid(self) -> None:
        """Negative pattern_count raises validation error."""
        base = make_base_payload_kwargs()
        with pytest.raises(ValidationError) as exc_info:
            ModelHookContextInjectedPayload(
                **base,
                context_source=ContextSource.NONE,
                pattern_count=-1,
                context_size_bytes=0,
                retrieval_duration_ms=0,
            )
        assert "pattern_count" in str(exc_info.value)

    def test_pattern_count_over_max_invalid(self) -> None:
        """pattern_count over 100 raises validation error."""
        base = make_base_payload_kwargs()
        with pytest.raises(ValidationError) as exc_info:
            ModelHookContextInjectedPayload(
                **base,
                context_source=ContextSource.DATABASE,
                pattern_count=101,
                context_size_bytes=0,
                retrieval_duration_ms=0,
            )
        assert "pattern_count" in str(exc_info.value)


# =============================================================================
# Context Size Bytes Bounds Tests
# =============================================================================


class TestContextSizeBytesBounds:
    """Tests for context_size_bytes validation (0-50000)."""

    def test_context_size_zero_valid(self) -> None:
        """context_size_bytes at lower bound (0) is valid."""
        base = make_base_payload_kwargs()
        payload = ModelHookContextInjectedPayload(
            **base,
            context_source=ContextSource.NONE,
            pattern_count=0,
            context_size_bytes=0,
            retrieval_duration_ms=0,
        )
        assert payload.context_size_bytes == 0

    def test_context_size_max_valid(self) -> None:
        """context_size_bytes at upper bound (50000) is valid."""
        base = make_base_payload_kwargs()
        payload = ModelHookContextInjectedPayload(
            **base,
            context_source=ContextSource.RAG_QUERY,
            pattern_count=10,
            context_size_bytes=50000,
            retrieval_duration_ms=100,
        )
        assert payload.context_size_bytes == 50000

    def test_context_size_negative_invalid(self) -> None:
        """Negative context_size_bytes raises validation error."""
        base = make_base_payload_kwargs()
        with pytest.raises(ValidationError) as exc_info:
            ModelHookContextInjectedPayload(
                **base,
                context_source=ContextSource.NONE,
                pattern_count=0,
                context_size_bytes=-1,
                retrieval_duration_ms=0,
            )
        assert "context_size_bytes" in str(exc_info.value)

    def test_context_size_over_max_invalid(self) -> None:
        """context_size_bytes over 50000 raises validation error."""
        base = make_base_payload_kwargs()
        with pytest.raises(ValidationError) as exc_info:
            ModelHookContextInjectedPayload(
                **base,
                context_source=ContextSource.DATABASE,
                pattern_count=5,
                context_size_bytes=50001,
                retrieval_duration_ms=0,
            )
        assert "context_size_bytes" in str(exc_info.value)


# =============================================================================
# Retrieval Duration Bounds Tests
# =============================================================================


class TestRetrievalDurationBounds:
    """Tests for retrieval_duration_ms validation (0-10000)."""

    def test_retrieval_duration_zero_valid(self) -> None:
        """retrieval_duration_ms at lower bound (0) is valid."""
        base = make_base_payload_kwargs()
        payload = ModelHookContextInjectedPayload(
            **base,
            context_source=ContextSource.NONE,
            pattern_count=0,
            context_size_bytes=0,
            retrieval_duration_ms=0,
        )
        assert payload.retrieval_duration_ms == 0

    def test_retrieval_duration_max_valid(self) -> None:
        """retrieval_duration_ms at upper bound (10000) is valid."""
        base = make_base_payload_kwargs()
        payload = ModelHookContextInjectedPayload(
            **base,
            context_source=ContextSource.RAG_QUERY,
            pattern_count=5,
            context_size_bytes=2048,
            retrieval_duration_ms=10000,
        )
        assert payload.retrieval_duration_ms == 10000

    def test_retrieval_duration_negative_invalid(self) -> None:
        """Negative retrieval_duration_ms raises validation error."""
        base = make_base_payload_kwargs()
        with pytest.raises(ValidationError) as exc_info:
            ModelHookContextInjectedPayload(
                **base,
                context_source=ContextSource.NONE,
                pattern_count=0,
                context_size_bytes=0,
                retrieval_duration_ms=-1,
            )
        assert "retrieval_duration_ms" in str(exc_info.value)

    def test_retrieval_duration_over_max_invalid(self) -> None:
        """retrieval_duration_ms over 10000 raises validation error."""
        base = make_base_payload_kwargs()
        with pytest.raises(ValidationError) as exc_info:
            ModelHookContextInjectedPayload(
                **base,
                context_source=ContextSource.DATABASE,
                pattern_count=5,
                context_size_bytes=1024,
                retrieval_duration_ms=10001,
            )
        assert "retrieval_duration_ms" in str(exc_info.value)


# =============================================================================
# Confidence Threshold Bounds Tests
# =============================================================================


class TestConfidenceThresholdBounds:
    """Tests for min_confidence_threshold validation (0.0-1.0)."""

    def test_confidence_default_value(self) -> None:
        """min_confidence_threshold defaults to 0.7."""
        base = make_base_payload_kwargs()
        payload = ModelHookContextInjectedPayload(
            **base,
            context_source=ContextSource.NONE,
            pattern_count=0,
            context_size_bytes=0,
            retrieval_duration_ms=0,
        )
        assert payload.min_confidence_threshold == 0.7

    def test_confidence_zero_valid(self) -> None:
        """min_confidence_threshold at lower bound (0.0) is valid."""
        base = make_base_payload_kwargs()
        payload = ModelHookContextInjectedPayload(
            **base,
            context_source=ContextSource.DATABASE,
            pattern_count=10,
            context_size_bytes=500,
            min_confidence_threshold=0.0,
            retrieval_duration_ms=50,
        )
        assert payload.min_confidence_threshold == 0.0

    def test_confidence_max_valid(self) -> None:
        """min_confidence_threshold at upper bound (1.0) is valid."""
        base = make_base_payload_kwargs()
        payload = ModelHookContextInjectedPayload(
            **base,
            context_source=ContextSource.RAG_QUERY,
            pattern_count=2,
            context_size_bytes=200,
            min_confidence_threshold=1.0,
            retrieval_duration_ms=75,
        )
        assert payload.min_confidence_threshold == 1.0

    def test_confidence_negative_invalid(self) -> None:
        """Negative min_confidence_threshold raises validation error."""
        base = make_base_payload_kwargs()
        with pytest.raises(ValidationError) as exc_info:
            ModelHookContextInjectedPayload(
                **base,
                context_source=ContextSource.NONE,
                pattern_count=0,
                context_size_bytes=0,
                min_confidence_threshold=-0.1,
                retrieval_duration_ms=0,
            )
        assert "min_confidence_threshold" in str(exc_info.value)

    def test_confidence_over_one_invalid(self) -> None:
        """min_confidence_threshold over 1.0 raises validation error."""
        base = make_base_payload_kwargs()
        with pytest.raises(ValidationError) as exc_info:
            ModelHookContextInjectedPayload(
                **base,
                context_source=ContextSource.DATABASE,
                pattern_count=5,
                context_size_bytes=1024,
                min_confidence_threshold=1.1,
                retrieval_duration_ms=0,
            )
        assert "min_confidence_threshold" in str(exc_info.value)


# =============================================================================
# Immutability Tests
# =============================================================================


class TestImmutability:
    """Tests for payload immutability (frozen)."""

    def test_frozen_immutable(self) -> None:
        """Test payload is immutable (frozen)."""
        base = make_base_payload_kwargs()
        payload = ModelHookContextInjectedPayload(
            **base,
            context_source=ContextSource.NONE,
            pattern_count=0,
            context_size_bytes=0,
            retrieval_duration_ms=0,
        )
        with pytest.raises(ValidationError):
            payload.pattern_count = 10  # type: ignore[misc]

    def test_frozen_cannot_modify_context_source(self) -> None:
        """Cannot modify context_source on frozen model."""
        base = make_base_payload_kwargs()
        payload = ModelHookContextInjectedPayload(
            **base,
            context_source=ContextSource.NONE,
            pattern_count=0,
            context_size_bytes=0,
            retrieval_duration_ms=0,
        )
        with pytest.raises(ValidationError):
            payload.context_source = ContextSource.RAG_QUERY  # type: ignore[misc]


# =============================================================================
# Extra Fields Tests
# =============================================================================


class TestExtraFields:
    """Tests for extra fields forbidden behavior."""

    def test_extra_fields_forbidden(self) -> None:
        """Test extra fields are rejected."""
        base = make_base_payload_kwargs()
        with pytest.raises(ValidationError) as exc_info:
            ModelHookContextInjectedPayload(
                **base,
                context_source=ContextSource.NONE,
                pattern_count=0,
                context_size_bytes=0,
                retrieval_duration_ms=0,
                unknown_field="not allowed",  # type: ignore[call-arg]
            )
        assert "unknown_field" in str(exc_info.value) or "extra" in str(exc_info.value)


# =============================================================================
# Serialization Tests
# =============================================================================


class TestSerialization:
    """Tests for JSON serialization."""

    def test_serialize_to_json(self) -> None:
        """Event can be serialized to JSON."""
        base = make_base_payload_kwargs()
        payload = ModelHookContextInjectedPayload(
            **base,
            context_source=ContextSource.RAG_QUERY,
            pattern_count=5,
            context_size_bytes=2048,
            agent_domain="testing",
            retrieval_duration_ms=150,
        )
        json_str = payload.model_dump_json()
        assert '"context_source":"rag_query"' in json_str
        assert '"pattern_count":5' in json_str
        assert '"context_size_bytes":2048' in json_str
        assert '"agent_domain":"testing"' in json_str
        assert '"retrieval_duration_ms":150' in json_str

    def test_roundtrip_serialization(self) -> None:
        """Event survives JSON roundtrip."""
        base = make_base_payload_kwargs()
        original = ModelHookContextInjectedPayload(
            **base,
            context_source=ContextSource.DATABASE,
            pattern_count=10,
            context_size_bytes=4096,
            agent_domain="code_review",
            min_confidence_threshold=0.85,
            retrieval_duration_ms=200,
        )
        json_str = original.model_dump_json()
        restored = ModelHookContextInjectedPayload.model_validate_json(json_str)

        assert restored.entity_id == original.entity_id
        assert restored.session_id == original.session_id
        assert restored.correlation_id == original.correlation_id
        assert restored.causation_id == original.causation_id
        assert restored.emitted_at == original.emitted_at
        assert restored.context_source == original.context_source
        assert restored.pattern_count == original.pattern_count
        assert restored.context_size_bytes == original.context_size_bytes
        assert restored.agent_domain == original.agent_domain
        assert restored.min_confidence_threshold == original.min_confidence_threshold
        assert restored.retrieval_duration_ms == original.retrieval_duration_ms


# =============================================================================
# Event Envelope Integration Tests
# =============================================================================


class TestEventEnvelopeIntegration:
    """Tests for using context injection payload with event envelope."""

    def test_context_injected_in_envelope(self) -> None:
        """ContextInjected payload works in envelope."""
        base = make_base_payload_kwargs()
        payload = ModelHookContextInjectedPayload(
            **base,
            context_source=ContextSource.RAG_QUERY,
            pattern_count=5,
            context_size_bytes=2048,
            retrieval_duration_ms=100,
        )
        envelope = ModelHookEventEnvelope(
            event_type=HookEventType.CONTEXT_INJECTED,
            payload=payload,
        )
        assert envelope.event_type == HookEventType.CONTEXT_INJECTED
        assert envelope.event_type == "hook.context.injected"
        assert isinstance(envelope.payload, ModelHookContextInjectedPayload)
        assert envelope.payload.pattern_count == 5

    def test_context_injected_wrong_event_type_rejected(self) -> None:
        """Mismatched event_type for context injection raises error."""
        base = make_base_payload_kwargs()
        payload = ModelHookContextInjectedPayload(
            **base,
            context_source=ContextSource.NONE,
            pattern_count=0,
            context_size_bytes=0,
            retrieval_duration_ms=0,
        )
        # Try to create envelope with wrong event_type
        with pytest.raises(ValidationError) as exc_info:
            ModelHookEventEnvelope(
                event_type=HookEventType.SESSION_STARTED,  # Wrong type!
                payload=payload,
            )
        assert "requires payload type ModelHookSessionStartedPayload" in str(
            exc_info.value
        )


# =============================================================================
# Context Source All Values Tests
# =============================================================================


class TestAllContextSourceValues:
    """Tests that all context source values can be used in payloads."""

    def test_database_source(self) -> None:
        """DATABASE source creates valid payload."""
        base = make_base_payload_kwargs()
        payload = ModelHookContextInjectedPayload(
            **base,
            context_source=ContextSource.DATABASE,
            pattern_count=5,
            context_size_bytes=1024,
            retrieval_duration_ms=50,
        )
        assert payload.context_source == ContextSource.DATABASE

    def test_session_aggregator_source(self) -> None:
        """SESSION_AGGREGATOR source creates valid payload."""
        base = make_base_payload_kwargs()
        payload = ModelHookContextInjectedPayload(
            **base,
            context_source=ContextSource.SESSION_AGGREGATOR,
            pattern_count=3,
            context_size_bytes=512,
            retrieval_duration_ms=25,
        )
        assert payload.context_source == ContextSource.SESSION_AGGREGATOR

    def test_rag_query_source(self) -> None:
        """RAG_QUERY source creates valid payload."""
        base = make_base_payload_kwargs()
        payload = ModelHookContextInjectedPayload(
            **base,
            context_source=ContextSource.RAG_QUERY,
            pattern_count=10,
            context_size_bytes=4096,
            retrieval_duration_ms=200,
        )
        assert payload.context_source == ContextSource.RAG_QUERY

    def test_fallback_static_source(self) -> None:
        """FALLBACK_STATIC source creates valid payload."""
        base = make_base_payload_kwargs()
        payload = ModelHookContextInjectedPayload(
            **base,
            context_source=ContextSource.FALLBACK_STATIC,
            pattern_count=2,
            context_size_bytes=256,
            retrieval_duration_ms=5,
        )
        assert payload.context_source == ContextSource.FALLBACK_STATIC

    def test_none_source(self) -> None:
        """NONE source creates valid payload."""
        base = make_base_payload_kwargs()
        payload = ModelHookContextInjectedPayload(
            **base,
            context_source=ContextSource.NONE,
            pattern_count=0,
            context_size_bytes=0,
            retrieval_duration_ms=0,
        )
        assert payload.context_source == ContextSource.NONE


# =============================================================================
# Naive Datetime Warning Tests
# =============================================================================


class TestNaiveDatetimeWarning:
    """Tests for naive datetime warning behavior."""

    def test_naive_datetime_triggers_conversion(self) -> None:
        """Naive datetimes are converted to UTC (graceful degradation)."""
        naive_dt = datetime(2025, 1, 19, 12, 0, 0)  # No tzinfo
        session_id = make_entity_id()
        payload = ModelHookContextInjectedPayload(
            entity_id=session_id,
            session_id=str(session_id),
            correlation_id=make_correlation_id(),
            causation_id=make_causation_id(),
            emitted_at=naive_dt,
            context_source=ContextSource.NONE,
            pattern_count=0,
            context_size_bytes=0,
            retrieval_duration_ms=0,
        )
        # Verify the conversion happened correctly
        assert payload.emitted_at.tzinfo is not None

    def test_timezone_aware_datetime_preserved(self) -> None:
        """Timezone-aware datetimes pass through without conversion."""
        aware_dt = datetime(2025, 1, 19, 12, 0, 0, tzinfo=UTC)
        session_id = make_entity_id()
        payload = ModelHookContextInjectedPayload(
            entity_id=session_id,
            session_id=str(session_id),
            correlation_id=make_correlation_id(),
            causation_id=make_causation_id(),
            emitted_at=aware_dt,
            context_source=ContextSource.NONE,
            pattern_count=0,
            context_size_bytes=0,
            retrieval_duration_ms=0,
        )
        assert payload.emitted_at == aware_dt
        assert payload.emitted_at.tzinfo is not None
