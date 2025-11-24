#!/usr/bin/env python3
"""
Event Validation Utilities

Validates events against omniclaude event bus integration standards:
- Envelope structure completeness (based on ModelRoutingEventEnvelope)
- Event naming conventions (namespace.domain.entity.action.v{version})
- Required fields presence
- Schema reference format (if used)
- Partition key policy compliance
- UUID validation
- Timestamp format validation

Standards Reference:
- services/routing_adapter/schemas/model_routing_event_envelope.py
- services/routing_adapter/schemas/topics.py
- docs/UNIFIED_EVENT_INFRASTRUCTURE.md

Created: 2025-11-13
"""

import re
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class ValidationResult(BaseModel):
    """
    Result of event validation.

    Attributes:
        is_valid: Overall validation status (True if no errors)
        errors: List of validation error messages
        warnings: List of non-critical warnings
    """

    is_valid: bool = True
    errors: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)

    def add_error(self, message: str) -> None:
        """Add error message and mark validation as failed."""
        self.errors.append(message)
        self.is_valid = False

    def add_warning(self, message: str) -> None:
        """Add warning message (doesn't affect is_valid)."""
        self.warnings.append(message)

    def merge(self, other: "ValidationResult") -> None:
        """Merge another validation result into this one."""
        if not other.is_valid:
            self.is_valid = False
        self.errors.extend(other.errors)
        self.warnings.extend(other.warnings)


def validate_event_envelope(envelope: Dict[str, Any]) -> ValidationResult:
    """
    Validate event envelope has all required fields.

    Required fields per ModelRoutingEventEnvelope pattern:
    - event_id: Unique event identifier (UUID string, auto-generated)
    - event_type: Event type identifier (string)
    - correlation_id: Request correlation ID for tracing (UUID string)
    - timestamp: Event timestamp (ISO 8601 format)
    - source: Source service name (min_length=1)
      Note: "service" also accepted for backward compatibility
    - payload: Event payload (dict or object)

    Optional but recommended:
    - version: Event schema version (default: "v1")
    - causation_id: ID of event that caused this event (for event chains)

    Args:
        envelope: Event envelope dictionary to validate

    Returns:
        ValidationResult with any errors or warnings found

    Example:
        >>> envelope = {
        ...     "event_id": "def-456",
        ...     "event_type": "AGENT_ROUTING_REQUESTED",
        ...     "correlation_id": "abc-123",
        ...     "timestamp": "2025-10-30T14:30:00Z",
        ...     "source": "polymorphic-agent",
        ...     "payload": {...},
        ...     "version": "v1"
        ... }
        >>> result = validate_event_envelope(envelope)
        >>> assert result.is_valid
    """
    result = ValidationResult()

    # Required fields
    required_fields = [
        "event_id",
        "event_type",
        "correlation_id",
        "timestamp",
        "payload",
    ]

    for field in required_fields:
        if field not in envelope:
            result.add_error(f"Missing required field: {field}")
        elif envelope[field] is None:
            result.add_error(f"Required field cannot be None: {field}")
        elif isinstance(envelope[field], str) and not envelope[field].strip():
            result.add_error(f"Required field cannot be empty: {field}")

    # Validate source/service field (accept either for backward compatibility)
    source_field = (
        "source"
        if "source" in envelope
        else "service" if "service" in envelope else None
    )
    if source_field is None:
        result.add_error("Missing required field: source")
    else:
        source_value = envelope[source_field]
        if not isinstance(source_value, str):
            result.add_error(
                f"{source_field} must be string, got {type(source_value).__name__}"
            )
        elif not source_value.strip():
            result.add_error(f"{source_field} cannot be empty string")

    # Optional but recommended fields
    if "version" not in envelope:
        result.add_warning(
            "Missing recommended field: version (consider adding for schema versioning)"
        )

    if "causation_id" not in envelope:
        result.add_warning(
            "Missing recommended field: causation_id (helps track event chains)"
        )

    # Validate field types
    if "event_id" in envelope and not isinstance(envelope["event_id"], str):
        result.add_error(
            f"event_id must be string, got {type(envelope['event_id']).__name__}"
        )

    if "event_type" in envelope and not isinstance(envelope["event_type"], str):
        result.add_error(
            f"event_type must be string, got {type(envelope['event_type']).__name__}"
        )

    if "correlation_id" in envelope and not isinstance(envelope["correlation_id"], str):
        result.add_error(
            f"correlation_id must be string, got {type(envelope['correlation_id']).__name__}"
        )

    if "timestamp" in envelope and not isinstance(envelope["timestamp"], str):
        result.add_error(
            f"timestamp must be string, got {type(envelope['timestamp']).__name__}"
        )

    if "payload" in envelope and envelope["payload"] is None:
        result.add_error("payload cannot be None (use empty dict if no data)")

    return result


def validate_uuid_field(value: str, field_name: str) -> ValidationResult:
    """
    Validate that a field value is a valid UUID string.

    Args:
        value: String value to validate as UUID
        field_name: Name of field being validated (for error messages)

    Returns:
        ValidationResult indicating if value is valid UUID

    Example:
        >>> result = validate_uuid_field("abc-123", "correlation_id")
        >>> assert not result.is_valid  # Not a valid UUID

        >>> result = validate_uuid_field("550e8400-e29b-41d4-a716-446655440000", "event_id")
        >>> assert result.is_valid
    """
    result = ValidationResult()

    if not isinstance(value, str):
        result.add_error(f"{field_name} must be string, got {type(value).__name__}")
        return result

    try:
        UUID(value)
    except ValueError as e:
        result.add_error(f"{field_name} must be valid UUID string: {e}")

    return result


def validate_timestamp_field(timestamp: str) -> ValidationResult:
    """
    Validate timestamp is in valid ISO 8601 format.

    Accepts formats:
    - 2025-10-30T14:30:00Z (UTC with Z suffix)
    - 2025-10-30T14:30:00+00:00 (UTC with offset)
    - 2025-10-30T14:30:00.123456Z (with microseconds)

    Args:
        timestamp: Timestamp string to validate

    Returns:
        ValidationResult indicating if timestamp is valid ISO 8601

    Example:
        >>> result = validate_timestamp_field("2025-10-30T14:30:00Z")
        >>> assert result.is_valid

        >>> result = validate_timestamp_field("2025-10-30 14:30:00")
        >>> assert not result.is_valid  # Invalid format
    """
    result = ValidationResult()

    if not isinstance(timestamp, str):
        result.add_error(f"timestamp must be string, got {type(timestamp).__name__}")
        return result

    try:
        # Parse ISO 8601 format (handle both Z and +00:00 suffixes)
        datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError as e:
        result.add_error(f"timestamp must be valid ISO 8601 format: {e}")
        result.add_warning(
            "Expected format: 2025-10-30T14:30:00Z or 2025-10-30T14:30:00+00:00"
        )

    return result


def validate_event_naming(event_type: str, strict: bool = True) -> ValidationResult:
    """
    Validate event type follows naming convention.

    Two formats accepted:
    1. Topic format (strict=True): {namespace}.{domain}.{entity}.{action}.v{version}
       Example: agent.routing.requested.v1

    2. Envelope format (strict=False): {PREFIX}_{ENTITY}_{ACTION}
       Example: AGENT_ROUTING_REQUESTED, DATABASE_QUERY_COMPLETED

    Args:
        event_type: Event type string to validate
        strict: If True, enforce topic format. If False, allow envelope format.

    Returns:
        ValidationResult indicating if event_type follows conventions

    Example:
        >>> # Topic format
        >>> result = validate_event_naming("agent.routing.requested.v1", strict=True)
        >>> assert result.is_valid

        >>> # Envelope format
        >>> result = validate_event_naming("AGENT_ROUTING_REQUESTED", strict=False)
        >>> assert result.is_valid
    """
    result = ValidationResult()

    if not isinstance(event_type, str):
        result.add_error(f"event_type must be string, got {type(event_type).__name__}")
        return result

    if not event_type:
        result.add_error("event_type cannot be empty")
        return result

    if strict:
        # Check for uppercase first (more specific error)
        if event_type != event_type.lower():
            result.add_error("Event type must be lowercase in topic format")

        # Topic format: namespace.domain.entity.action.v{version}
        # Example: agent.routing.requested.v1
        # Pattern requires at least 3 components (namespace.domain.entity) before .v{version}
        # That's: first component + 2 repetitions of (.component) + .v{version}
        pattern = r"^[a-z][a-z0-9_-]*(\.[a-z][a-z0-9_-]*){2,}\.v\d+$"

        if not re.match(pattern, event_type):
            result.add_error(
                f"Event type '{event_type}' doesn't match topic naming convention. "
                "Expected format: {{namespace}}.{{domain}}.{{entity}}.{{action}}.v{{version}} "
                "(e.g., 'agent.routing.requested.v1')"
            )

    else:
        # Check for lowercase first (more specific error)
        if event_type != event_type.upper():
            result.add_error("Event type must be uppercase in envelope format")

        # Must have at least one underscore
        if "_" not in event_type:
            result.add_error(
                "Event type must contain underscores to separate components"
            )

        # Envelope format: PREFIX_ENTITY_ACTION
        # Example: AGENT_ROUTING_REQUESTED
        pattern = r"^[A-Z][A-Z0-9_]*$"

        if not re.match(pattern, event_type):
            result.add_error(
                f"Event type '{event_type}' doesn't match envelope naming convention. "
                "Expected format: {{PREFIX}}_{{ENTITY}}_{{ACTION}} "
                "(e.g., 'AGENT_ROUTING_REQUESTED')"
            )

    return result


def validate_schema_reference(schema_ref: str) -> ValidationResult:
    """
    Validate schema reference format.

    Expected format: registry://{namespace}/{domain}/{schema_name}/{version}
    Example: registry://omninode/agent/routing_requested/v1

    Note: Schema references are optional in omniclaude events, but if provided
    they should follow this format for consistency.

    Args:
        schema_ref: Schema reference string to validate

    Returns:
        ValidationResult indicating if schema_ref follows format

    Example:
        >>> result = validate_schema_reference("registry://omninode/agent/routing_requested/v1")
        >>> assert result.is_valid

        >>> result = validate_schema_reference("http://example.com/schema")
        >>> assert not result.is_valid  # Wrong protocol
    """
    result = ValidationResult()

    if not isinstance(schema_ref, str):
        result.add_error(f"schema_ref must be string, got {type(schema_ref).__name__}")
        return result

    pattern = r"^registry://[a-z][a-z0-9_-]*/[a-z][a-z0-9_-]*/[a-z][a-z0-9_-]*/v\d+$"

    if not re.match(pattern, schema_ref):
        result.add_error(
            f"Schema reference '{schema_ref}' doesn't match format. "
            "Expected: registry://{{namespace}}/{{domain}}/{{schema}}/{{version}} "
            "(e.g., 'registry://omninode/agent/routing_requested/v1')"
        )

    return result


def validate_partition_key_policy(
    event_type: str,
    partition_key: Optional[str],
    envelope: Optional[Dict[str, Any]] = None,
) -> ValidationResult:
    """
    Validate partition key matches policy for event type.

    Partition key policies:
    - Routing events: Use correlation_id for request-response ordering
    - Database events: Use correlation_id or entity ID
    - Intelligence events: Use correlation_id
    - Default: correlation_id recommended for traceability

    Args:
        event_type: Event type to determine partition key policy
        partition_key: Partition key value (or None if not set)
        envelope: Optional full envelope to extract correlation_id

    Returns:
        ValidationResult indicating if partition key is appropriate

    Example:
        >>> envelope = {"correlation_id": "abc-123"}
        >>> result = validate_partition_key_policy(
        ...     "AGENT_ROUTING_REQUESTED",
        ...     "abc-123",
        ...     envelope
        ... )
        >>> assert result.is_valid
    """
    result = ValidationResult()

    # Partition key is recommended but not strictly required
    if not partition_key:
        result.add_warning(
            "No partition key provided. Consider using correlation_id for message ordering."
        )
        return result

    # If envelope provided, validate partition key matches correlation_id
    if envelope and "correlation_id" in envelope:
        correlation_id = envelope["correlation_id"]
        if partition_key != correlation_id:
            result.add_warning(
                f"Partition key '{partition_key}' doesn't match correlation_id '{correlation_id}'. "
                "Using correlation_id ensures request-response ordering."
            )

    return result


def validate_full_event(
    envelope: Dict[str, Any],
    validate_uuid_fields: bool = True,
    validate_naming: bool = True,
    strict_naming: bool = False,
) -> ValidationResult:
    """
    Comprehensive event validation.

    Validates:
    - Envelope structure (required fields, types)
    - UUID format for event_id and correlation_id
    - Timestamp format (ISO 8601)
    - Event type naming convention
    - Schema reference format (if present)
    - Partition key policy (if present)

    Args:
        envelope: Full event envelope to validate
        validate_uuid_fields: If True, validate UUID format for ID fields
        validate_naming: If True, validate event type naming convention
        strict_naming: If True, enforce topic format; if False, allow envelope format

    Returns:
        ValidationResult with aggregated errors and warnings

    Example:
        >>> envelope = {
        ...     "event_id": "550e8400-e29b-41d4-a716-446655440000",
        ...     "event_type": "AGENT_ROUTING_REQUESTED",
        ...     "correlation_id": "abc-123-def-456",
        ...     "timestamp": "2025-10-30T14:30:00Z",
        ...     "source": "polymorphic-agent",
        ...     "payload": {"user_request": "test"},
        ...     "version": "v1"
        ... }
        >>> result = validate_full_event(envelope, validate_uuid_fields=True)
        >>> # Will have errors for invalid UUID format in correlation_id
    """
    final_result = ValidationResult()

    # 1. Validate envelope structure
    envelope_result = validate_event_envelope(envelope)
    final_result.merge(envelope_result)

    # If envelope structure is invalid, skip field-level validation
    if not envelope_result.is_valid:
        return final_result

    # 2. Validate UUID fields
    if validate_uuid_fields:
        if "event_id" in envelope:
            uuid_result = validate_uuid_field(envelope["event_id"], "event_id")
            final_result.merge(uuid_result)

        if "correlation_id" in envelope:
            uuid_result = validate_uuid_field(
                envelope["correlation_id"], "correlation_id"
            )
            final_result.merge(uuid_result)

        if "causation_id" in envelope:
            uuid_result = validate_uuid_field(envelope["causation_id"], "causation_id")
            final_result.merge(uuid_result)

    # 3. Validate timestamp
    if "timestamp" in envelope:
        timestamp_result = validate_timestamp_field(envelope["timestamp"])
        final_result.merge(timestamp_result)

    # 4. Validate event type naming
    if validate_naming and "event_type" in envelope:
        naming_result = validate_event_naming(
            envelope["event_type"], strict=strict_naming
        )
        final_result.merge(naming_result)

    # 5. Validate schema reference (if present)
    if "schema_ref" in envelope:
        schema_result = validate_schema_reference(envelope["schema_ref"])
        final_result.merge(schema_result)

    # 6. Validate partition key (if present in metadata)
    if "partition_key" in envelope:
        partition_result = validate_partition_key_policy(
            envelope.get("event_type", ""),
            envelope["partition_key"],
            envelope,
        )
        final_result.merge(partition_result)

    return final_result


def validate_event_batch(
    envelopes: List[Dict[str, Any]],
    **validation_options,
) -> Dict[str, ValidationResult]:
    """
    Validate a batch of events.

    Useful for validating multiple events before publishing to Kafka.
    Returns a dictionary mapping index to validation result.

    Args:
        envelopes: List of event envelopes to validate
        **validation_options: Options passed to validate_full_event()

    Returns:
        Dictionary mapping event index to ValidationResult

    Example:
        >>> envelopes = [
        ...     {"event_id": "...", "event_type": "...", ...},
        ...     {"event_id": "...", "event_type": "...", ...},
        ... ]
        >>> results = validate_event_batch(envelopes)
        >>> for idx, result in results.items():
        ...     if not result.is_valid:
        ...         print(f"Event {idx} has {len(result.errors)} errors")
    """
    results = {}

    for idx, envelope in enumerate(envelopes):
        result = validate_full_event(envelope, **validation_options)
        results[idx] = result

    return results


def get_validation_summary(results: Dict[int, ValidationResult]) -> Dict[str, Any]:
    """
    Generate summary statistics from batch validation results.

    Args:
        results: Dictionary of validation results from validate_event_batch()

    Returns:
        Dictionary with summary statistics:
        - total: Total events validated
        - valid: Count of valid events
        - invalid: Count of invalid events
        - total_errors: Total error count across all events
        - total_warnings: Total warning count across all events

    Example:
        >>> results = validate_event_batch(envelopes)
        >>> summary = get_validation_summary(results)
        >>> print(f"Valid: {summary['valid']}/{summary['total']}")
    """
    total = len(results)
    valid = sum(1 for r in results.values() if r.is_valid)
    invalid = total - valid
    total_errors = sum(len(r.errors) for r in results.values())
    total_warnings = sum(len(r.warnings) for r in results.values())

    return {
        "total": total,
        "valid": valid,
        "invalid": invalid,
        "total_errors": total_errors,
        "total_warnings": total_warnings,
    }


__all__ = [
    "ValidationResult",
    "get_validation_summary",
    "validate_event_batch",
    "validate_event_envelope",
    "validate_event_naming",
    "validate_full_event",
    "validate_partition_key_policy",
    "validate_schema_reference",
    "validate_timestamp_field",
    "validate_uuid_field",
]
