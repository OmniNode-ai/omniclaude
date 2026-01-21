#!/usr/bin/env python3
"""
Unit Tests for Event Validation Utilities

Tests validation functions against omniclaude event bus standards:
- Envelope structure validation
- UUID field validation
- Timestamp format validation
- Event naming conventions
- Schema reference validation
- Partition key policy validation
- Full event validation
- Batch validation

Run tests:
    pytest agents/lib/test_event_validation.py -v
    pytest agents/lib/test_event_validation.py::test_validate_event_envelope -v

Created: 2025-11-13
"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from .event_validation import (
    ValidationResult,
    get_validation_summary,
    validate_event_batch,
    validate_event_envelope,
    validate_event_naming,
    validate_full_event,
    validate_partition_key_policy,
    validate_schema_reference,
    validate_timestamp_field,
    validate_uuid_field,
)


class TestValidationResult:
    """Test ValidationResult model."""

    def test_default_values(self):
        """Test ValidationResult default state."""
        result = ValidationResult()
        assert result.is_valid is True
        assert result.errors == []
        assert result.warnings == []

    def test_add_error(self):
        """Test adding errors marks validation as failed."""
        result = ValidationResult()
        result.add_error("Test error")
        assert result.is_valid is False
        assert "Test error" in result.errors

    def test_add_warning(self):
        """Test adding warnings doesn't affect is_valid."""
        result = ValidationResult()
        result.add_warning("Test warning")
        assert result.is_valid is True
        assert "Test warning" in result.warnings

    def test_merge(self):
        """Test merging validation results."""
        result1 = ValidationResult()
        result1.add_error("Error 1")
        result1.add_warning("Warning 1")

        result2 = ValidationResult()
        result2.add_error("Error 2")
        result2.add_warning("Warning 2")

        result1.merge(result2)
        assert result1.is_valid is False
        assert len(result1.errors) == 2
        assert len(result1.warnings) == 2


class TestValidateEventEnvelope:
    """Test validate_event_envelope function."""

    def test_valid_envelope(self):
        """Test validation passes for valid envelope."""
        envelope = {
            "event_id": str(uuid4()),
            "event_type": "AGENT_ROUTING_REQUESTED",
            "correlation_id": str(uuid4()),
            "timestamp": datetime.now(UTC).isoformat(),
            "service": "test-service",
            "payload": {"test": "data"},
            "version": "v1",
        }
        result = validate_event_envelope(envelope)
        assert result.is_valid is True
        assert len(result.errors) == 0

    def test_missing_required_fields(self):
        """Test validation fails for missing required fields."""
        envelope = {
            "event_id": str(uuid4()),
            # Missing event_type, correlation_id, timestamp, service, payload
        }
        result = validate_event_envelope(envelope)
        assert result.is_valid is False
        assert len(result.errors) == 5  # 5 missing fields

    def test_none_values_rejected(self):
        """Test None values in required fields are rejected."""
        envelope = {
            "event_id": None,
            "event_type": None,
            "correlation_id": None,
            "timestamp": None,
            "service": None,
            "payload": None,
        }
        result = validate_event_envelope(envelope)
        assert result.is_valid is False
        # We get errors for both None checks and type checks (12 total)
        assert len(result.errors) >= 6

    def test_empty_strings_rejected(self):
        """Test empty strings in required fields are rejected."""
        envelope = {
            "event_id": "",
            "event_type": "",
            "correlation_id": "",
            "timestamp": "",
            "service": "",
            "payload": {},
        }
        result = validate_event_envelope(envelope)
        assert result.is_valid is False
        assert len(result.errors) >= 5  # At least 5 empty string errors

    def test_type_validation(self):
        """Test type validation for fields."""
        envelope = {
            "event_id": 12345,  # Should be string
            "event_type": ["list"],  # Should be string
            "correlation_id": {"dict": "value"},  # Should be string
            "timestamp": 1234567890,  # Should be string
            "service": True,  # Should be string
            "payload": None,  # Cannot be None
        }
        result = validate_event_envelope(envelope)
        assert result.is_valid is False
        assert len(result.errors) >= 6

    def test_optional_version_warning(self):
        """Test warning for missing version field."""
        envelope = {
            "event_id": str(uuid4()),
            "event_type": "AGENT_ROUTING_REQUESTED",
            "correlation_id": str(uuid4()),
            "timestamp": datetime.now(UTC).isoformat(),
            "service": "test-service",
            "payload": {},
            # Missing version
        }
        result = validate_event_envelope(envelope)
        assert result.is_valid is True  # Still valid
        assert any("version" in w for w in result.warnings)

    def test_optional_causation_id_warning(self):
        """Test warning for missing causation_id field."""
        envelope = {
            "event_id": str(uuid4()),
            "event_type": "AGENT_ROUTING_REQUESTED",
            "correlation_id": str(uuid4()),
            "timestamp": datetime.now(UTC).isoformat(),
            "service": "test-service",
            "payload": {},
            "version": "v1",
            # Missing causation_id
        }
        result = validate_event_envelope(envelope)
        assert result.is_valid is True
        assert any("causation_id" in w for w in result.warnings)


class TestValidateUuidField:
    """Test validate_uuid_field function."""

    def test_valid_uuid(self):
        """Test validation passes for valid UUID."""
        uuid_str = str(uuid4())
        result = validate_uuid_field(uuid_str, "test_field")
        assert result.is_valid is True

    def test_uuid_with_hyphens(self):
        """Test UUID with standard hyphen format."""
        uuid_str = "550e8400-e29b-41d4-a716-446655440000"
        result = validate_uuid_field(uuid_str, "test_field")
        assert result.is_valid is True

    def test_invalid_uuid_format(self):
        """Test validation fails for invalid UUID format."""
        result = validate_uuid_field("not-a-uuid", "test_field")
        assert result.is_valid is False
        assert "test_field" in result.errors[0]

    def test_non_string_value(self):
        """Test validation fails for non-string values."""
        result = validate_uuid_field(12345, "test_field")
        assert result.is_valid is False
        assert "must be string" in result.errors[0]

    def test_empty_string(self):
        """Test validation fails for empty string."""
        result = validate_uuid_field("", "test_field")
        assert result.is_valid is False


class TestValidateTimestampField:
    """Test validate_timestamp_field function."""

    def test_valid_timestamp_with_z_suffix(self):
        """Test validation passes for timestamp with Z suffix."""
        timestamp = "2025-10-30T14:30:00Z"
        result = validate_timestamp_field(timestamp)
        assert result.is_valid is True

    def test_valid_timestamp_with_offset(self):
        """Test validation passes for timestamp with timezone offset."""
        timestamp = "2025-10-30T14:30:00+00:00"
        result = validate_timestamp_field(timestamp)
        assert result.is_valid is True

    def test_valid_timestamp_with_microseconds(self):
        """Test validation passes for timestamp with microseconds."""
        timestamp = "2025-10-30T14:30:00.123456Z"
        result = validate_timestamp_field(timestamp)
        assert result.is_valid is True

    def test_invalid_timestamp_format(self):
        """Test validation fails for invalid timestamp format."""
        timestamp = "not-a-valid-timestamp"  # Completely invalid
        result = validate_timestamp_field(timestamp)
        assert result.is_valid is False
        assert "ISO 8601" in result.errors[0]

    def test_non_string_timestamp(self):
        """Test validation fails for non-string timestamp."""
        result = validate_timestamp_field(1234567890)
        assert result.is_valid is False
        assert "must be string" in result.errors[0]

    def test_empty_timestamp(self):
        """Test validation fails for empty timestamp."""
        result = validate_timestamp_field("")
        assert result.is_valid is False


class TestValidateEventNaming:
    """Test validate_event_naming function."""

    def test_valid_topic_format(self):
        """Test validation passes for valid topic format."""
        event_type = "agent.routing.requested.v1"
        result = validate_event_naming(event_type, strict=True)
        assert result.is_valid is True

    def test_valid_envelope_format(self):
        """Test validation passes for valid envelope format."""
        event_type = "AGENT_ROUTING_REQUESTED"
        result = validate_event_naming(event_type, strict=False)
        assert result.is_valid is True

    def test_invalid_topic_format_missing_version(self):
        """Test validation fails for topic format without version."""
        event_type = "agent.routing.requested"
        result = validate_event_naming(event_type, strict=True)
        assert result.is_valid is False

    def test_invalid_topic_format_uppercase(self):
        """Test validation fails for uppercase topic format."""
        event_type = "Agent.Routing.Requested.v1"
        result = validate_event_naming(event_type, strict=True)
        assert result.is_valid is False
        assert "lowercase" in result.errors[0]

    def test_invalid_envelope_format_lowercase(self):
        """Test validation fails for lowercase envelope format."""
        event_type = "agent_routing_requested"
        result = validate_event_naming(event_type, strict=False)
        assert result.is_valid is False
        assert "uppercase" in result.errors[0]

    def test_empty_event_type(self):
        """Test validation fails for empty event type."""
        result = validate_event_naming("", strict=True)
        assert result.is_valid is False
        assert "empty" in result.errors[0]

    def test_non_string_event_type(self):
        """Test validation fails for non-string event type."""
        result = validate_event_naming(12345, strict=True)
        assert result.is_valid is False
        assert "must be string" in result.errors[0]


class TestValidateSchemaReference:
    """Test validate_schema_reference function."""

    def test_valid_schema_reference(self):
        """Test validation passes for valid schema reference."""
        schema_ref = "registry://omninode/agent/routing_requested/v1"
        result = validate_schema_reference(schema_ref)
        assert result.is_valid is True

    def test_invalid_protocol(self):
        """Test validation fails for wrong protocol."""
        schema_ref = "http://omninode/agent/routing_requested/v1"
        result = validate_schema_reference(schema_ref)
        assert result.is_valid is False

    def test_missing_version(self):
        """Test validation fails for missing version."""
        schema_ref = "registry://omninode/agent/routing_requested"
        result = validate_schema_reference(schema_ref)
        assert result.is_valid is False

    def test_uppercase_components(self):
        """Test validation fails for uppercase components."""
        schema_ref = "registry://OmniNode/Agent/RoutingRequested/v1"
        result = validate_schema_reference(schema_ref)
        assert result.is_valid is False

    def test_non_string_schema_ref(self):
        """Test validation fails for non-string schema reference."""
        result = validate_schema_reference(12345)
        assert result.is_valid is False
        assert "must be string" in result.errors[0]


class TestValidatePartitionKeyPolicy:
    """Test validate_partition_key_policy function."""

    def test_no_partition_key_warning(self):
        """Test warning when no partition key provided."""
        result = validate_partition_key_policy("AGENT_ROUTING_REQUESTED", None)
        assert result.is_valid is True  # Warning only
        assert len(result.warnings) > 0

    def test_partition_key_matches_correlation_id(self):
        """Test no warning when partition key matches correlation_id."""
        envelope = {"correlation_id": "abc-123"}
        result = validate_partition_key_policy(
            "AGENT_ROUTING_REQUESTED",
            "abc-123",
            envelope,
        )
        assert result.is_valid is True
        assert len(result.warnings) == 0

    def test_partition_key_mismatch_warning(self):
        """Test warning when partition key doesn't match correlation_id."""
        envelope = {"correlation_id": "abc-123"}
        result = validate_partition_key_policy(
            "AGENT_ROUTING_REQUESTED",
            "xyz-789",
            envelope,
        )
        assert result.is_valid is True  # Warning only
        assert any("doesn't match" in w for w in result.warnings)


class TestValidateFullEvent:
    """Test validate_full_event function."""

    def test_fully_valid_event(self):
        """Test validation passes for fully valid event."""
        envelope = {
            "event_id": str(uuid4()),
            "event_type": "AGENT_ROUTING_REQUESTED",
            "correlation_id": str(uuid4()),
            "timestamp": datetime.now(UTC).isoformat(),
            "service": "test-service",
            "payload": {"user_request": "test"},
            "version": "v1",
        }
        result = validate_full_event(envelope, validate_uuid_fields=True)
        assert result.is_valid is True

    def test_invalid_uuid_fields(self):
        """Test validation catches invalid UUID fields."""
        envelope = {
            "event_id": "not-a-uuid",
            "event_type": "AGENT_ROUTING_REQUESTED",
            "correlation_id": "also-not-a-uuid",
            "timestamp": datetime.now(UTC).isoformat(),
            "service": "test-service",
            "payload": {},
        }
        result = validate_full_event(envelope, validate_uuid_fields=True)
        assert result.is_valid is False
        assert len(result.errors) >= 2  # Both UUIDs invalid

    def test_invalid_timestamp(self):
        """Test validation catches invalid timestamp."""
        envelope = {
            "event_id": str(uuid4()),
            "event_type": "AGENT_ROUTING_REQUESTED",
            "correlation_id": str(uuid4()),
            "timestamp": "invalid-timestamp",
            "service": "test-service",
            "payload": {},
        }
        result = validate_full_event(envelope)
        assert result.is_valid is False
        assert any("timestamp" in e for e in result.errors)

    def test_skip_uuid_validation(self):
        """Test UUID validation can be skipped."""
        envelope = {
            "event_id": "not-a-uuid",
            "event_type": "AGENT_ROUTING_REQUESTED",
            "correlation_id": "also-not-a-uuid",
            "timestamp": datetime.now(UTC).isoformat(),
            "service": "test-service",
            "payload": {},
        }
        result = validate_full_event(envelope, validate_uuid_fields=False)
        # Should pass envelope validation but not UUID validation
        assert result.is_valid is True or len(result.errors) == 0

    def test_skip_naming_validation(self):
        """Test naming validation can be skipped."""
        envelope = {
            "event_id": str(uuid4()),
            "event_type": "InvalidFormat",
            "correlation_id": str(uuid4()),
            "timestamp": datetime.now(UTC).isoformat(),
            "service": "test-service",
            "payload": {},
        }
        result = validate_full_event(envelope, validate_naming=False)
        assert result.is_valid is True

    def test_schema_reference_validation(self):
        """Test schema reference is validated if present."""
        envelope = {
            "event_id": str(uuid4()),
            "event_type": "AGENT_ROUTING_REQUESTED",
            "correlation_id": str(uuid4()),
            "timestamp": datetime.now(UTC).isoformat(),
            "service": "test-service",
            "payload": {},
            "schema_ref": "invalid://schema",
        }
        result = validate_full_event(envelope)
        assert result.is_valid is False
        assert any("schema" in e.lower() for e in result.errors)


class TestValidateEventBatch:
    """Test validate_event_batch function."""

    def test_batch_with_mixed_validity(self):
        """Test batch validation with valid and invalid events."""
        envelopes = [
            # Valid event
            {
                "event_id": str(uuid4()),
                "event_type": "AGENT_ROUTING_REQUESTED",
                "correlation_id": str(uuid4()),
                "timestamp": datetime.now(UTC).isoformat(),
                "service": "test-service",
                "payload": {},
            },
            # Invalid event (missing fields)
            {
                "event_id": str(uuid4()),
            },
            # Valid event
            {
                "event_id": str(uuid4()),
                "event_type": "AGENT_ROUTING_COMPLETED",
                "correlation_id": str(uuid4()),
                "timestamp": datetime.now(UTC).isoformat(),
                "service": "test-service",
                "payload": {},
            },
        ]

        results = validate_event_batch(envelopes, validate_uuid_fields=True)

        assert len(results) == 3
        assert results[0].is_valid is True
        assert results[1].is_valid is False
        assert results[2].is_valid is True

    def test_empty_batch(self):
        """Test batch validation with empty list."""
        results = validate_event_batch([])
        assert len(results) == 0


class TestGetValidationSummary:
    """Test get_validation_summary function."""

    def test_summary_statistics(self):
        """Test summary generates correct statistics."""
        results = {
            0: ValidationResult(is_valid=True),
            1: ValidationResult(is_valid=False, errors=["Error 1", "Error 2"]),
            2: ValidationResult(is_valid=True, warnings=["Warning 1"]),
            3: ValidationResult(is_valid=False, errors=["Error 3"]),
        }

        summary = get_validation_summary(results)

        assert summary["total"] == 4
        assert summary["valid"] == 2
        assert summary["invalid"] == 2
        assert summary["total_errors"] == 3
        assert summary["total_warnings"] == 1

    def test_all_valid_summary(self):
        """Test summary with all valid events."""
        results = {
            0: ValidationResult(is_valid=True),
            1: ValidationResult(is_valid=True),
        }

        summary = get_validation_summary(results)

        assert summary["total"] == 2
        assert summary["valid"] == 2
        assert summary["invalid"] == 0
        assert summary["total_errors"] == 0

    def test_empty_results_summary(self):
        """Test summary with empty results."""
        summary = get_validation_summary({})

        assert summary["total"] == 0
        assert summary["valid"] == 0
        assert summary["invalid"] == 0
        assert summary["total_errors"] == 0
        assert summary["total_warnings"] == 0


class TestIntegrationScenarios:
    """Test real-world integration scenarios."""

    def test_routing_request_event(self):
        """Test validation of actual routing request event."""
        envelope = {
            "event_id": str(uuid4()),
            "event_type": "AGENT_ROUTING_REQUESTED",
            "correlation_id": str(uuid4()),
            "timestamp": datetime.now(UTC).isoformat(),
            "service": "polymorphic-agent",
            "payload": {
                "user_request": "optimize my database queries",
                "context": {"domain": "database_optimization"},
                "options": {
                    "max_recommendations": 3,
                    "min_confidence": 0.7,
                },
            },
            "version": "v1",
        }

        result = validate_full_event(envelope, strict_naming=False)
        assert result.is_valid is True

    def test_routing_response_event(self):
        """Test validation of actual routing response event."""
        envelope = {
            "event_id": str(uuid4()),
            "event_type": "AGENT_ROUTING_COMPLETED",
            "correlation_id": str(uuid4()),
            "timestamp": datetime.now(UTC).isoformat(),
            "service": "agent-router-service",
            "payload": {
                "recommendations": [
                    {
                        "agent_name": "agent-database",
                        "confidence": 0.95,
                    }
                ],
                "routing_metadata": {
                    "routing_time_ms": 45,
                },
            },
            "version": "v1",
        }

        result = validate_full_event(envelope, strict_naming=False)
        assert result.is_valid is True

    def test_database_event(self):
        """Test validation of database operation event."""
        envelope = {
            "event_id": str(uuid4()),
            "event_type": "DATABASE_QUERY_REQUESTED",
            "correlation_id": str(uuid4()),
            "timestamp": datetime.now(UTC).isoformat(),
            "service": "omniclaude-agent",
            "payload": {
                "query": "SELECT * FROM agent_routing_decisions",
                "params": [],
            },
            "version": "v1",
        }

        result = validate_full_event(envelope, strict_naming=False)
        assert result.is_valid is True


if __name__ == "__main__":
    # Run tests with pytest
    pytest.main([__file__, "-v", "--tb=short"])
