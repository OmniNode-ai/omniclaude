# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Tests for learned pattern persistence models.

Validates Pydantic model constraints for:
- ModelLearnedPatternRecord
- ModelLearnedPatternQuery
- ModelLearnedPatternQueryResult
- ModelLearnedPatternUpsertResult

These models are used by NodePatternPersistenceEffect for
storing and retrieving learned patterns from the persistence layer.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from omniclaude.nodes.node_pattern_persistence_effect.models import (
    ModelLearnedPatternQuery,
    ModelLearnedPatternQueryResult,
    ModelLearnedPatternRecord,
    ModelLearnedPatternUpsertResult,
)

# All tests in this module are unit tests
pytestmark = pytest.mark.unit


# =============================================================================
# Helper Factories
# =============================================================================


def make_valid_pattern_record(**overrides) -> ModelLearnedPatternRecord:
    """Create a valid pattern record with sensible defaults.

    Args:
        **overrides: Fields to override from defaults.

    Returns:
        A valid ModelLearnedPatternRecord instance.
    """
    defaults = {
        "pattern_id": "testing.pytest_fixtures",
        "domain": "testing",
        "title": "Pytest Fixture Patterns",
        "description": "Use pytest fixtures for test setup and teardown.",
        "confidence": 0.9,
        "usage_count": 15,
        "success_rate": 0.95,
    }
    defaults.update(overrides)
    return ModelLearnedPatternRecord(**defaults)


# =============================================================================
# ModelLearnedPatternRecord Tests
# =============================================================================


class TestModelLearnedPatternRecordValidPatternId:
    """Tests for valid pattern_id values."""

    def test_valid_pattern_id_simple(self) -> None:
        """Simple lowercase alphanumeric pattern_id passes validation."""
        record = make_valid_pattern_record(pattern_id="testing")
        assert record.pattern_id == "testing"

    def test_valid_pattern_id_with_dots(self) -> None:
        """Pattern_id with dots passes validation (e.g., 'testing.pytest_fixtures')."""
        record = make_valid_pattern_record(pattern_id="testing.pytest_fixtures")
        assert record.pattern_id == "testing.pytest_fixtures"

    def test_valid_pattern_id_with_underscores(self) -> None:
        """Pattern_id with underscores passes validation."""
        record = make_valid_pattern_record(pattern_id="testing_patterns")
        assert record.pattern_id == "testing_patterns"

    def test_valid_pattern_id_with_hyphens(self) -> None:
        """Pattern_id with hyphens passes validation."""
        record = make_valid_pattern_record(pattern_id="testing-patterns")
        assert record.pattern_id == "testing-patterns"

    def test_valid_pattern_id_mixed_separators(self) -> None:
        """Pattern_id with mixed separators passes validation."""
        record = make_valid_pattern_record(pattern_id="testing.pytest_fixtures-v2")
        assert record.pattern_id == "testing.pytest_fixtures-v2"

    def test_valid_pattern_id_starts_with_number(self) -> None:
        """Pattern_id starting with number passes validation."""
        record = make_valid_pattern_record(pattern_id="0testing.patterns")
        assert record.pattern_id == "0testing.patterns"

    def test_valid_pattern_id_min_length_3(self) -> None:
        """Pattern_id with exactly 3 characters passes validation."""
        record = make_valid_pattern_record(pattern_id="abc")
        assert record.pattern_id == "abc"

    def test_valid_pattern_id_max_length_200(self) -> None:
        """Pattern_id with exactly 200 characters passes validation."""
        long_id = "a" + "b" * 199  # 200 chars total
        record = make_valid_pattern_record(pattern_id=long_id)
        assert len(record.pattern_id) == 200


class TestModelLearnedPatternRecordInvalidPatternId:
    """Tests for invalid pattern_id values."""

    def test_invalid_pattern_id_uppercase(self) -> None:
        """Pattern_id with uppercase letters fails validation."""
        with pytest.raises(ValidationError) as exc_info:
            make_valid_pattern_record(pattern_id="Testing.Patterns")
        assert "pattern_id" in str(exc_info.value)

    def test_invalid_pattern_id_starts_with_dot(self) -> None:
        """Pattern_id starting with dot fails validation."""
        with pytest.raises(ValidationError) as exc_info:
            make_valid_pattern_record(pattern_id=".testing.patterns")
        assert "pattern_id" in str(exc_info.value)

    def test_invalid_pattern_id_starts_with_underscore(self) -> None:
        """Pattern_id starting with underscore fails validation."""
        with pytest.raises(ValidationError) as exc_info:
            make_valid_pattern_record(pattern_id="_testing")
        assert "pattern_id" in str(exc_info.value)

    def test_invalid_pattern_id_starts_with_hyphen(self) -> None:
        """Pattern_id starting with hyphen fails validation."""
        with pytest.raises(ValidationError) as exc_info:
            make_valid_pattern_record(pattern_id="-testing")
        assert "pattern_id" in str(exc_info.value)

    def test_invalid_pattern_id_too_short(self) -> None:
        """Pattern_id with less than 3 characters fails validation."""
        with pytest.raises(ValidationError) as exc_info:
            make_valid_pattern_record(pattern_id="ab")
        assert "pattern_id" in str(exc_info.value)

    def test_invalid_pattern_id_too_long(self) -> None:
        """Pattern_id with more than 200 characters fails validation."""
        long_id = "a" * 201
        with pytest.raises(ValidationError) as exc_info:
            make_valid_pattern_record(pattern_id=long_id)
        assert "pattern_id" in str(exc_info.value)

    def test_invalid_pattern_id_special_chars(self) -> None:
        """Pattern_id with special characters fails validation."""
        with pytest.raises(ValidationError) as exc_info:
            make_valid_pattern_record(pattern_id="testing@patterns")
        assert "pattern_id" in str(exc_info.value)

    def test_invalid_pattern_id_spaces(self) -> None:
        """Pattern_id with spaces fails validation."""
        with pytest.raises(ValidationError) as exc_info:
            make_valid_pattern_record(pattern_id="testing patterns")
        assert "pattern_id" in str(exc_info.value)

    def test_invalid_pattern_id_empty(self) -> None:
        """Empty pattern_id fails validation."""
        with pytest.raises(ValidationError) as exc_info:
            make_valid_pattern_record(pattern_id="")
        # Either pattern_id field validation or min_length constraint
        error_str = str(exc_info.value)
        assert "pattern_id" in error_str or "min_length" in error_str.lower()


class TestModelLearnedPatternRecordImmutability:
    """Tests for model immutability (frozen=True)."""

    def test_frozen_prevents_mutation(self) -> None:
        """Attempting to mutate a frozen model raises ValidationError."""
        record = make_valid_pattern_record()
        with pytest.raises(ValidationError):
            record.pattern_id = "different.pattern"  # type: ignore[misc]

    def test_frozen_prevents_domain_mutation(self) -> None:
        """Attempting to mutate domain raises ValidationError."""
        record = make_valid_pattern_record()
        with pytest.raises(ValidationError):
            record.domain = "different"  # type: ignore[misc]

    def test_frozen_prevents_confidence_mutation(self) -> None:
        """Attempting to mutate confidence raises ValidationError."""
        record = make_valid_pattern_record()
        with pytest.raises(ValidationError):
            record.confidence = 0.5  # type: ignore[misc]


class TestModelLearnedPatternRecordExtraFields:
    """Tests for extra fields forbidden (extra='forbid')."""

    def test_extra_fields_forbidden(self) -> None:
        """Extra fields not in the model raise ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            ModelLearnedPatternRecord(
                pattern_id="testing.patterns",
                domain="testing",
                title="Test Pattern",
                description="A test pattern description.",
                confidence=0.9,
                extra_field="not allowed",  # type: ignore[call-arg]
            )
        assert "extra_field" in str(exc_info.value)


class TestModelLearnedPatternRecordConfidence:
    """Tests for confidence field bounds."""

    def test_confidence_min_zero(self) -> None:
        """Confidence of 0.0 is valid."""
        record = make_valid_pattern_record(confidence=0.0)
        assert record.confidence == 0.0

    def test_confidence_max_one(self) -> None:
        """Confidence of 1.0 is valid."""
        record = make_valid_pattern_record(confidence=1.0)
        assert record.confidence == 1.0

    def test_confidence_below_zero_fails(self) -> None:
        """Confidence below 0.0 fails validation."""
        with pytest.raises(ValidationError) as exc_info:
            make_valid_pattern_record(confidence=-0.1)
        assert "confidence" in str(exc_info.value)

    def test_confidence_above_one_fails(self) -> None:
        """Confidence above 1.0 fails validation."""
        with pytest.raises(ValidationError) as exc_info:
            make_valid_pattern_record(confidence=1.1)
        assert "confidence" in str(exc_info.value)


class TestModelLearnedPatternRecordSuccessRate:
    """Tests for success_rate field bounds."""

    def test_success_rate_default(self) -> None:
        """Success rate defaults to 1.0."""
        record = ModelLearnedPatternRecord(
            pattern_id="testing.patterns",
            domain="testing",
            title="Test",
            description="Test description",
            confidence=0.9,
        )
        assert record.success_rate == 1.0

    def test_success_rate_min_zero(self) -> None:
        """Success rate of 0.0 is valid."""
        record = make_valid_pattern_record(success_rate=0.0)
        assert record.success_rate == 0.0

    def test_success_rate_max_one(self) -> None:
        """Success rate of 1.0 is valid."""
        record = make_valid_pattern_record(success_rate=1.0)
        assert record.success_rate == 1.0

    def test_success_rate_below_zero_fails(self) -> None:
        """Success rate below 0.0 fails validation."""
        with pytest.raises(ValidationError) as exc_info:
            make_valid_pattern_record(success_rate=-0.1)
        assert "success_rate" in str(exc_info.value)

    def test_success_rate_above_one_fails(self) -> None:
        """Success rate above 1.0 fails validation."""
        with pytest.raises(ValidationError) as exc_info:
            make_valid_pattern_record(success_rate=1.1)
        assert "success_rate" in str(exc_info.value)


class TestModelLearnedPatternRecordUsageCount:
    """Tests for usage_count field."""

    def test_usage_count_default_zero(self) -> None:
        """Usage count defaults to 0."""
        record = ModelLearnedPatternRecord(
            pattern_id="testing.patterns",
            domain="testing",
            title="Test",
            description="Test description",
            confidence=0.9,
        )
        assert record.usage_count == 0

    def test_usage_count_non_negative(self) -> None:
        """Usage count must be non-negative."""
        record = make_valid_pattern_record(usage_count=0)
        assert record.usage_count == 0

    def test_usage_count_positive(self) -> None:
        """Positive usage count is valid."""
        record = make_valid_pattern_record(usage_count=100)
        assert record.usage_count == 100

    def test_usage_count_negative_fails(self) -> None:
        """Negative usage count fails validation."""
        with pytest.raises(ValidationError) as exc_info:
            make_valid_pattern_record(usage_count=-1)
        assert "usage_count" in str(exc_info.value)


class TestModelLearnedPatternRecordOptionalFields:
    """Tests for optional fields."""

    def test_example_reference_optional(self) -> None:
        """Example reference is optional."""
        record = make_valid_pattern_record()
        assert record.example_reference is None

    def test_example_reference_set(self) -> None:
        """Example reference can be set."""
        record = make_valid_pattern_record(
            example_reference="tests/fixtures/example.py"
        )
        assert record.example_reference == "tests/fixtures/example.py"

    def test_example_reference_max_length(self) -> None:
        """Example reference has max length of 500."""
        record = make_valid_pattern_record(example_reference="x" * 500)
        assert len(record.example_reference) == 500

    def test_example_reference_too_long_fails(self) -> None:
        """Example reference over 500 chars fails validation."""
        with pytest.raises(ValidationError) as exc_info:
            make_valid_pattern_record(example_reference="x" * 501)
        assert "example_reference" in str(exc_info.value)


# =============================================================================
# ModelLearnedPatternQuery Tests
# =============================================================================


class TestModelLearnedPatternQueryDefaults:
    """Tests for query model default values."""

    def test_all_defaults(self) -> None:
        """Query model has sensible defaults."""
        query = ModelLearnedPatternQuery()
        assert query.domain is None
        assert query.min_confidence == 0.0
        assert query.include_general is True
        assert query.limit == 50
        assert query.offset == 0

    def test_domain_optional(self) -> None:
        """Domain filter is optional."""
        query = ModelLearnedPatternQuery(domain="testing")
        assert query.domain == "testing"


class TestModelLearnedPatternQueryMinConfidence:
    """Tests for min_confidence bounds (0.0-1.0)."""

    def test_min_confidence_zero(self) -> None:
        """min_confidence of 0.0 is valid."""
        query = ModelLearnedPatternQuery(min_confidence=0.0)
        assert query.min_confidence == 0.0

    def test_min_confidence_one(self) -> None:
        """min_confidence of 1.0 is valid."""
        query = ModelLearnedPatternQuery(min_confidence=1.0)
        assert query.min_confidence == 1.0

    def test_min_confidence_mid_range(self) -> None:
        """min_confidence in mid-range is valid."""
        query = ModelLearnedPatternQuery(min_confidence=0.7)
        assert query.min_confidence == 0.7

    def test_min_confidence_below_zero_fails(self) -> None:
        """min_confidence below 0.0 fails validation."""
        with pytest.raises(ValidationError) as exc_info:
            ModelLearnedPatternQuery(min_confidence=-0.1)
        assert "min_confidence" in str(exc_info.value)

    def test_min_confidence_above_one_fails(self) -> None:
        """min_confidence above 1.0 fails validation."""
        with pytest.raises(ValidationError) as exc_info:
            ModelLearnedPatternQuery(min_confidence=1.1)
        assert "min_confidence" in str(exc_info.value)


class TestModelLearnedPatternQueryLimit:
    """Tests for limit bounds (1-500)."""

    def test_limit_min_one(self) -> None:
        """limit of 1 is valid."""
        query = ModelLearnedPatternQuery(limit=1)
        assert query.limit == 1

    def test_limit_max_500(self) -> None:
        """limit of 500 is valid."""
        query = ModelLearnedPatternQuery(limit=500)
        assert query.limit == 500

    def test_limit_default_50(self) -> None:
        """limit defaults to 50."""
        query = ModelLearnedPatternQuery()
        assert query.limit == 50

    def test_limit_zero_fails(self) -> None:
        """limit of 0 fails validation."""
        with pytest.raises(ValidationError) as exc_info:
            ModelLearnedPatternQuery(limit=0)
        assert "limit" in str(exc_info.value)

    def test_limit_negative_fails(self) -> None:
        """Negative limit fails validation."""
        with pytest.raises(ValidationError) as exc_info:
            ModelLearnedPatternQuery(limit=-1)
        assert "limit" in str(exc_info.value)

    def test_limit_above_500_fails(self) -> None:
        """limit above 500 fails validation."""
        with pytest.raises(ValidationError) as exc_info:
            ModelLearnedPatternQuery(limit=501)
        assert "limit" in str(exc_info.value)


class TestModelLearnedPatternQueryOffset:
    """Tests for offset field."""

    def test_offset_zero(self) -> None:
        """offset of 0 is valid."""
        query = ModelLearnedPatternQuery(offset=0)
        assert query.offset == 0

    def test_offset_positive(self) -> None:
        """Positive offset is valid."""
        query = ModelLearnedPatternQuery(offset=100)
        assert query.offset == 100

    def test_offset_negative_fails(self) -> None:
        """Negative offset fails validation."""
        with pytest.raises(ValidationError) as exc_info:
            ModelLearnedPatternQuery(offset=-1)
        assert "offset" in str(exc_info.value)


class TestModelLearnedPatternQueryImmutability:
    """Tests for query model immutability."""

    def test_frozen_prevents_mutation(self) -> None:
        """Attempting to mutate a frozen query raises ValidationError."""
        query = ModelLearnedPatternQuery(domain="testing")
        with pytest.raises(ValidationError):
            query.domain = "different"  # type: ignore[misc]


class TestModelLearnedPatternQueryExtraFields:
    """Tests for extra fields forbidden."""

    def test_extra_fields_forbidden(self) -> None:
        """Extra fields raise ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            ModelLearnedPatternQuery(
                domain="testing",
                extra_field="not allowed",  # type: ignore[call-arg]
            )
        assert "extra_field" in str(exc_info.value)


# =============================================================================
# ModelLearnedPatternQueryResult Tests
# =============================================================================


class TestModelLearnedPatternQueryResultRecords:
    """Tests for records field (tuple of records)."""

    def test_records_default_empty_tuple(self) -> None:
        """Records defaults to empty tuple."""
        result = ModelLearnedPatternQueryResult(success=True)
        assert result.records == ()
        assert isinstance(result.records, tuple)

    def test_records_as_tuple(self) -> None:
        """Records are stored as tuple."""
        record1 = make_valid_pattern_record(pattern_id="testing.one")
        record2 = make_valid_pattern_record(pattern_id="testing.two")
        result = ModelLearnedPatternQueryResult(
            success=True,
            records=(record1, record2),
        )
        assert isinstance(result.records, tuple)
        assert len(result.records) == 2
        assert result.records[0].pattern_id == "testing.one"
        assert result.records[1].pattern_id == "testing.two"

    def test_records_empty_on_failure(self) -> None:
        """Records should be empty on failure."""
        result = ModelLearnedPatternQueryResult(
            success=False,
            error="Database connection failed",
        )
        assert result.records == ()


class TestModelLearnedPatternQueryResultTotalCount:
    """Tests for total_count field."""

    def test_total_count_default_zero(self) -> None:
        """total_count defaults to 0."""
        result = ModelLearnedPatternQueryResult(success=True)
        assert result.total_count == 0

    def test_total_count_set(self) -> None:
        """total_count can be set."""
        result = ModelLearnedPatternQueryResult(
            success=True,
            total_count=42,
        )
        assert result.total_count == 42

    def test_total_count_non_negative(self) -> None:
        """total_count must be non-negative."""
        with pytest.raises(ValidationError) as exc_info:
            ModelLearnedPatternQueryResult(
                success=True,
                total_count=-1,
            )
        assert "total_count" in str(exc_info.value)


class TestModelLearnedPatternQueryResultMetadata:
    """Tests for result metadata fields."""

    def test_duration_ms_default(self) -> None:
        """duration_ms defaults to 0.0."""
        result = ModelLearnedPatternQueryResult(success=True)
        assert result.duration_ms == 0.0

    def test_duration_ms_set(self) -> None:
        """duration_ms can be set."""
        result = ModelLearnedPatternQueryResult(
            success=True,
            duration_ms=15.5,
        )
        assert result.duration_ms == 15.5

    def test_duration_ms_non_negative(self) -> None:
        """duration_ms must be non-negative."""
        with pytest.raises(ValidationError) as exc_info:
            ModelLearnedPatternQueryResult(
                success=True,
                duration_ms=-1.0,
            )
        assert "duration_ms" in str(exc_info.value)

    def test_backend_type_default(self) -> None:
        """backend_type defaults to 'postgresql'."""
        result = ModelLearnedPatternQueryResult(success=True)
        assert result.backend_type == "postgresql"

    def test_correlation_id_optional(self) -> None:
        """correlation_id is optional."""
        result = ModelLearnedPatternQueryResult(success=True)
        assert result.correlation_id is None

    def test_correlation_id_set(self) -> None:
        """correlation_id can be set."""
        corr_id = uuid4()
        result = ModelLearnedPatternQueryResult(
            success=True,
            correlation_id=corr_id,
        )
        assert result.correlation_id == corr_id


class TestModelLearnedPatternQueryResultImmutability:
    """Tests for result model immutability."""

    def test_frozen_prevents_mutation(self) -> None:
        """Attempting to mutate a frozen result raises ValidationError."""
        result = ModelLearnedPatternQueryResult(success=True)
        with pytest.raises(ValidationError):
            result.success = False  # type: ignore[misc]


# =============================================================================
# ModelLearnedPatternUpsertResult Tests
# =============================================================================


class TestModelLearnedPatternUpsertResultOperation:
    """Tests for operation literal type ('insert' | 'update')."""

    def test_operation_insert(self) -> None:
        """Operation can be 'insert'."""
        result = ModelLearnedPatternUpsertResult(
            success=True,
            pattern_id="testing.patterns",
            operation="insert",
        )
        assert result.operation == "insert"

    def test_operation_update(self) -> None:
        """Operation can be 'update'."""
        result = ModelLearnedPatternUpsertResult(
            success=True,
            pattern_id="testing.patterns",
            operation="update",
        )
        assert result.operation == "update"

    def test_operation_none_on_failure(self) -> None:
        """Operation is None on failure."""
        result = ModelLearnedPatternUpsertResult(
            success=False,
            error="Insert failed",
        )
        assert result.operation is None

    def test_operation_invalid_literal_fails(self) -> None:
        """Invalid operation literal fails validation."""
        with pytest.raises(ValidationError) as exc_info:
            ModelLearnedPatternUpsertResult(
                success=True,
                pattern_id="testing.patterns",
                operation="delete",  # type: ignore[arg-type]
            )
        assert "operation" in str(exc_info.value)


class TestModelLearnedPatternUpsertResultFields:
    """Tests for upsert result fields."""

    def test_success_required(self) -> None:
        """success field is required."""
        # This should work
        result = ModelLearnedPatternUpsertResult(success=True)
        assert result.success is True

        result = ModelLearnedPatternUpsertResult(success=False)
        assert result.success is False

    def test_pattern_id_optional(self) -> None:
        """pattern_id is optional (None on failure)."""
        result = ModelLearnedPatternUpsertResult(success=False)
        assert result.pattern_id is None

    def test_pattern_id_set_on_success(self) -> None:
        """pattern_id is set on success."""
        result = ModelLearnedPatternUpsertResult(
            success=True,
            pattern_id="testing.patterns",
            operation="insert",
        )
        assert result.pattern_id == "testing.patterns"

    def test_error_on_failure(self) -> None:
        """error message is set on failure."""
        result = ModelLearnedPatternUpsertResult(
            success=False,
            error="Database constraint violation",
        )
        assert result.error == "Database constraint violation"

    def test_error_none_on_success(self) -> None:
        """error is None on success."""
        result = ModelLearnedPatternUpsertResult(
            success=True,
            pattern_id="testing.patterns",
            operation="insert",
        )
        assert result.error is None

    def test_duration_ms_default(self) -> None:
        """duration_ms defaults to 0.0."""
        result = ModelLearnedPatternUpsertResult(success=True)
        assert result.duration_ms == 0.0

    def test_duration_ms_non_negative(self) -> None:
        """duration_ms must be non-negative."""
        with pytest.raises(ValidationError) as exc_info:
            ModelLearnedPatternUpsertResult(
                success=True,
                duration_ms=-1.0,
            )
        assert "duration_ms" in str(exc_info.value)

    def test_correlation_id_optional(self) -> None:
        """correlation_id is optional."""
        result = ModelLearnedPatternUpsertResult(success=True)
        assert result.correlation_id is None

    def test_correlation_id_set(self) -> None:
        """correlation_id can be set."""
        corr_id = uuid4()
        result = ModelLearnedPatternUpsertResult(
            success=True,
            correlation_id=corr_id,
        )
        assert result.correlation_id == corr_id


class TestModelLearnedPatternUpsertResultImmutability:
    """Tests for upsert result model immutability."""

    def test_frozen_prevents_mutation(self) -> None:
        """Attempting to mutate a frozen result raises ValidationError."""
        result = ModelLearnedPatternUpsertResult(
            success=True,
            pattern_id="testing.patterns",
            operation="insert",
        )
        with pytest.raises(ValidationError):
            result.success = False  # type: ignore[misc]


class TestModelLearnedPatternUpsertResultExtraFields:
    """Tests for extra fields forbidden."""

    def test_extra_fields_forbidden(self) -> None:
        """Extra fields raise ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            ModelLearnedPatternUpsertResult(
                success=True,
                extra_field="not allowed",  # type: ignore[call-arg]
            )
        assert "extra_field" in str(exc_info.value)


# =============================================================================
# Serialization Tests
# =============================================================================


class TestModelSerialization:
    """Tests for JSON serialization of learned pattern models."""

    def test_record_serialization_roundtrip(self) -> None:
        """Pattern record survives JSON roundtrip."""
        original = make_valid_pattern_record()
        json_str = original.model_dump_json()
        restored = ModelLearnedPatternRecord.model_validate_json(json_str)

        assert restored.pattern_id == original.pattern_id
        assert restored.domain == original.domain
        assert restored.title == original.title
        assert restored.description == original.description
        assert restored.confidence == original.confidence
        assert restored.usage_count == original.usage_count
        assert restored.success_rate == original.success_rate

    def test_query_serialization_roundtrip(self) -> None:
        """Pattern query survives JSON roundtrip."""
        original = ModelLearnedPatternQuery(
            domain="testing",
            min_confidence=0.7,
            include_general=True,
            limit=20,
            offset=10,
        )
        json_str = original.model_dump_json()
        restored = ModelLearnedPatternQuery.model_validate_json(json_str)

        assert restored.domain == original.domain
        assert restored.min_confidence == original.min_confidence
        assert restored.include_general == original.include_general
        assert restored.limit == original.limit
        assert restored.offset == original.offset

    def test_query_result_serialization_roundtrip(self) -> None:
        """Query result with records survives JSON roundtrip."""
        record = make_valid_pattern_record()
        original = ModelLearnedPatternQueryResult(
            success=True,
            records=(record,),
            total_count=1,
            duration_ms=15.5,
        )
        json_str = original.model_dump_json()
        restored = ModelLearnedPatternQueryResult.model_validate_json(json_str)

        assert restored.success == original.success
        assert len(restored.records) == 1
        assert restored.records[0].pattern_id == record.pattern_id
        assert restored.total_count == original.total_count
        assert restored.duration_ms == original.duration_ms

    def test_upsert_result_serialization_roundtrip(self) -> None:
        """Upsert result survives JSON roundtrip."""
        corr_id = uuid4()
        original = ModelLearnedPatternUpsertResult(
            success=True,
            pattern_id="testing.patterns",
            operation="insert",
            duration_ms=5.2,
            correlation_id=corr_id,
        )
        json_str = original.model_dump_json()
        restored = ModelLearnedPatternUpsertResult.model_validate_json(json_str)

        assert restored.success == original.success
        assert restored.pattern_id == original.pattern_id
        assert restored.operation == original.operation
        assert restored.duration_ms == original.duration_ms
        assert restored.correlation_id == original.correlation_id
