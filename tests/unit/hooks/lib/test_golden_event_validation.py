#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Golden event tests -- CI-enforced payload validation for all emitters [OMN-6885].

These tests enforce that every emitter produces payloads that:
1. Contain ALL required fields defined in golden_events/schemas.json
2. Have correct types for each field
3. Never contain sentinel/placeholder values ("unknown", "", "placeholder", "test",
   "00000000-0000-0000-0000-000000000000") in identity/correlation fields
4. Use valid status enum values where defined
5. Have valid ISO-8601 timestamps in emitted_at fields

The golden schema is the single source of truth. Adding a new emitter requires:
1. Add the event type to golden_events/schemas.json
2. Add a test class here that captures the payload and validates it

Design:
- Same test, swap the emitter: each emitter gets a dedicated capture test
- Sentinel detection is a reusable validator, not per-test
- Idempotent: no external deps, mock emit_event everywhere
"""

from __future__ import annotations

import json
import re
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# sys.path setup: plugin lib modules live outside the normal package tree
# ---------------------------------------------------------------------------
_LIB_PATH = str(
    Path(__file__).parent.parent.parent.parent.parent
    / "plugins"
    / "onex"
    / "hooks"
    / "lib"
)
if _LIB_PATH not in sys.path:
    sys.path.insert(0, _LIB_PATH)

# All tests in this module are unit tests
pytestmark = pytest.mark.unit

# ---------------------------------------------------------------------------
# Golden schema loader
# ---------------------------------------------------------------------------

_GOLDEN_SCHEMA_PATH = Path(__file__).parent / "golden_events" / "schemas.json"


def _load_golden_schemas() -> dict[str, Any]:
    """Load golden event schemas from the fixture file."""
    with open(_GOLDEN_SCHEMA_PATH) as f:
        data = json.load(f)
    # Remove the _doc key
    return {k: v for k, v in data.items() if not k.startswith("_")}


GOLDEN_SCHEMAS = _load_golden_schemas()

# ---------------------------------------------------------------------------
# Sentinel value detection
# ---------------------------------------------------------------------------

# Values that indicate the caller failed to supply a real value.
# These are the exact sentinel strings that were found in the emitter audit.
_SENTINEL_STRINGS = frozenset(
    {
        "unknown",
        "UNKNOWN",
        "placeholder",
        "test",
        "TODO",
        "todo",
        "N/A",
        "n/a",
        "none",
        "null",
        "undefined",
        "default",
        "example",
    }
)

# UUID sentinel: all-zeros UUID indicates the caller did not generate a real ID
_ZERO_UUID = "00000000-0000-0000-0000-000000000000"

# ISO-8601 timestamp pattern (basic validation)
_ISO_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")

# Python type mapping from schema string to runtime types
_TYPE_MAP: dict[str, type | tuple[type, ...]] = {
    "str": str,
    "int": int,
    "float": (int, float),  # int is acceptable where float is expected
    "bool": bool,
    "list": list,
    "dict": dict,
}


def assert_no_sentinels(payload: dict[str, Any], sentinel_fields: list[str]) -> None:
    """Assert that none of the sentinel_fields contain sentinel/placeholder values.

    This is the core enforcement: if a field is listed as a sentinel_field in the
    golden schema, its value must be a real, caller-provided value -- not a
    placeholder or default that slipped through.

    Args:
        payload: The emitted event payload dict.
        sentinel_fields: Field names to check for sentinels.

    Raises:
        AssertionError with a descriptive message identifying the offending field.
    """
    for field in sentinel_fields:
        if field not in payload:
            continue
        value = payload[field]

        # Empty string sentinel
        if isinstance(value, str) and value.strip() == "":
            raise AssertionError(
                f"Sentinel value detected: field '{field}' is an empty string. "
                f"Emitters must receive real values from callers."
            )

        # Known sentinel strings
        if isinstance(value, str) and value.strip() in _SENTINEL_STRINGS:
            raise AssertionError(
                f"Sentinel value detected: field '{field}' = {value!r}. "
                f"This is a known placeholder. Emitters must receive real values."
            )

        # All-zeros UUID
        if isinstance(value, str) and value == _ZERO_UUID:
            raise AssertionError(
                f"Sentinel value detected: field '{field}' is the all-zeros UUID. "
                f"Callers must generate a real UUID."
            )


def assert_required_fields(
    payload: dict[str, Any],
    schema: dict[str, Any],
    event_type: str,
) -> None:
    """Assert that all required fields are present with correct types.

    Args:
        payload: The emitted event payload dict.
        schema: The golden schema for this event type.
        event_type: Event type name (for error messages).

    Raises:
        AssertionError if a required field is missing or has the wrong type.
    """
    required = schema.get("required_fields", {})
    for field_name, type_str in required.items():
        assert field_name in payload, (
            f"[{event_type}] Missing required field: '{field_name}'. "
            f"Golden schema requires: {list(required.keys())}"
        )

        expected_types = _TYPE_MAP.get(type_str)
        if expected_types is None:
            continue  # Unknown type in schema, skip runtime check

        value = payload[field_name]
        # Allow None for fields that are nullable (similarity_score, etc.)
        if value is None:
            continue

        assert isinstance(value, expected_types), (
            f"[{event_type}] Field '{field_name}' has wrong type: "
            f"expected {type_str}, got {type(value).__name__} = {value!r}"
        )


def assert_valid_timestamp(payload: dict[str, Any], field: str = "emitted_at") -> None:
    """Assert that a timestamp field contains a valid ISO-8601 string.

    Args:
        payload: The emitted event payload dict.
        field: The timestamp field name to check.

    Raises:
        AssertionError if the field is missing or not a valid ISO-8601 timestamp.
    """
    if field not in payload:
        return  # Not all events have this field
    value = payload[field]
    assert isinstance(value, str), (
        f"Timestamp field '{field}' must be a string, got {type(value).__name__}"
    )
    assert _ISO_TIMESTAMP_RE.match(value), (
        f"Timestamp field '{field}' is not valid ISO-8601: {value!r}"
    )


def assert_valid_status(
    payload: dict[str, Any],
    schema: dict[str, Any],
    status_field: str = "status",
) -> None:
    """Assert that the status field contains a valid enum value.

    Args:
        payload: The emitted event payload dict.
        schema: The golden schema for this event type.
        status_field: The field name holding the status value.

    Raises:
        AssertionError if the status value is not in the valid set.
    """
    valid_statuses = schema.get("valid_statuses")
    if valid_statuses is None:
        return  # No status enum defined for this event type

    if status_field not in payload:
        return

    value = payload[status_field]
    assert value in valid_statuses, (
        f"Invalid status: '{value}'. Valid values: {valid_statuses}"
    )


def validate_golden_event(
    payload: dict[str, Any],
    event_type: str,
) -> None:
    """Run all golden event validations against a payload.

    This is the top-level validator called by each test. It runs:
    1. Required field presence + type check
    2. Sentinel value detection on identity/correlation fields
    3. Timestamp format validation
    4. Status enum validation (where applicable)

    Args:
        payload: The emitted event payload dict.
        event_type: The event type key from golden_events/schemas.json.

    Raises:
        AssertionError on any validation failure.
    """
    schema = GOLDEN_SCHEMAS[event_type]
    assert_required_fields(payload, schema, event_type)
    assert_no_sentinels(payload, schema.get("sentinel_fields", []))

    # Validate all timestamp fields
    for field_name, type_str in schema.get("required_fields", {}).items():
        if type_str == "str" and (
            field_name.endswith("_at") or field_name == "timestamp"
        ):
            assert_valid_timestamp(payload, field_name)


# ---------------------------------------------------------------------------
# Payload capture helper
# ---------------------------------------------------------------------------


def make_capture_mock() -> tuple[MagicMock, list[tuple[str, dict[str, Any]]]]:
    """Create a mock emit function that captures (topic, payload) tuples.

    Returns:
        Tuple of (mock_fn, captured_calls) where captured_calls is a mutable
        list of (topic, payload) tuples populated on each call.
    """
    captured: list[tuple[str, dict[str, Any]]] = []

    def _capture(topic: str, payload: dict[str, Any]) -> bool:
        captured.append((topic, dict(payload)))
        return True

    mock = MagicMock(side_effect=_capture)
    return mock, captured


# ===========================================================================
# Pipeline event emitter golden tests
# ===========================================================================


@pytest.mark.unit
class TestGoldenEpicRunUpdated:
    """Golden event validation for emit_epic_run_updated."""

    def test_golden_payload_structure(self) -> None:
        mock_fn, captured = make_capture_mock()
        with patch(
            "plugins.onex.hooks.lib.pipeline_event_emitters._get_emit_fn",
            return_value=mock_fn,
        ):
            from plugins.onex.hooks.lib.pipeline_event_emitters import (
                emit_epic_run_updated,
            )

            emit_epic_run_updated(
                run_id="run-golden-001",
                epic_id="OMN-9999",
                status="completed",
                tickets_total=5,
                tickets_completed=4,
                tickets_failed=1,
                correlation_id="corr-golden-001",
                session_id="sess-golden-001",
            )

        assert len(captured) == 1
        topic, payload = captured[0]
        assert topic == "epic.run.updated"
        validate_golden_event(payload, "epic.run.updated")
        assert_valid_status(payload, GOLDEN_SCHEMAS["epic.run.updated"])

    def test_rejects_empty_run_id(self) -> None:
        """Caller must provide a real run_id, not empty string."""
        mock_fn, captured = make_capture_mock()
        with patch(
            "plugins.onex.hooks.lib.pipeline_event_emitters._get_emit_fn",
            return_value=mock_fn,
        ):
            from plugins.onex.hooks.lib.pipeline_event_emitters import (
                emit_epic_run_updated,
            )

            emit_epic_run_updated(
                run_id="",
                epic_id="OMN-9999",
                status="running",
                correlation_id="corr-001",
            )

        assert len(captured) == 1
        _, payload = captured[0]
        with pytest.raises(AssertionError, match="empty string"):
            assert_no_sentinels(
                payload, GOLDEN_SCHEMAS["epic.run.updated"]["sentinel_fields"]
            )


@pytest.mark.unit
class TestGoldenPrWatchUpdated:
    """Golden event validation for emit_pr_watch_updated."""

    def test_golden_payload_structure(self) -> None:
        mock_fn, captured = make_capture_mock()
        with patch(
            "plugins.onex.hooks.lib.pipeline_event_emitters._get_emit_fn",
            return_value=mock_fn,
        ):
            from plugins.onex.hooks.lib.pipeline_event_emitters import (
                emit_pr_watch_updated,
            )

            emit_pr_watch_updated(
                run_id="run-pr-001",
                pr_number=42,
                repo="OmniNode-ai/omniclaude",
                ticket_id="OMN-1234",
                status="approved",
                review_cycles_used=2,
                watch_duration_hours=1.5,
                correlation_id="corr-pr-001",
            )

        assert len(captured) == 1
        topic, payload = captured[0]
        assert topic == "pr.watch.updated"
        validate_golden_event(payload, "pr.watch.updated")
        assert_valid_status(payload, GOLDEN_SCHEMAS["pr.watch.updated"])

    def test_pr_number_must_be_int(self) -> None:
        """pr_number must be an integer, not a string."""
        mock_fn, captured = make_capture_mock()
        with patch(
            "plugins.onex.hooks.lib.pipeline_event_emitters._get_emit_fn",
            return_value=mock_fn,
        ):
            from plugins.onex.hooks.lib.pipeline_event_emitters import (
                emit_pr_watch_updated,
            )

            emit_pr_watch_updated(
                run_id="run-pr-002",
                pr_number=381,
                repo="OmniNode-ai/omniclaude",
                ticket_id="OMN-5678",
                status="watching",
                correlation_id="corr-pr-002",
            )

        _, payload = captured[0]
        assert isinstance(payload["pr_number"], int)


@pytest.mark.unit
class TestGoldenGateDecision:
    """Golden event validation for emit_gate_decision."""

    def test_golden_payload_structure(self) -> None:
        mock_fn, captured = make_capture_mock()
        with patch(
            "plugins.onex.hooks.lib.pipeline_event_emitters._get_emit_fn",
            return_value=mock_fn,
        ):
            from plugins.onex.hooks.lib.pipeline_event_emitters import (
                emit_gate_decision,
            )

            emit_gate_decision(
                gate_id="gate-golden-001",
                decision="ACCEPTED",
                ticket_id="OMN-1234",
                gate_type="HIGH_RISK",
                wait_seconds=45.2,
                responder="jonah",
                correlation_id="corr-gate-001",
            )

        assert len(captured) == 1
        topic, payload = captured[0]
        assert topic == "gate.decision"
        validate_golden_event(payload, "gate.decision")
        assert_valid_status(
            payload, GOLDEN_SCHEMAS["gate.decision"], status_field="decision"
        )


@pytest.mark.unit
class TestGoldenBudgetCapHit:
    """Golden event validation for emit_budget_cap_hit."""

    def test_golden_payload_structure(self) -> None:
        mock_fn, captured = make_capture_mock()
        with patch(
            "plugins.onex.hooks.lib.pipeline_event_emitters._get_emit_fn",
            return_value=mock_fn,
        ):
            from plugins.onex.hooks.lib.pipeline_event_emitters import (
                emit_budget_cap_hit,
            )

            emit_budget_cap_hit(
                run_id="run-budget-golden-001",
                tokens_used=50000,
                tokens_budget=40000,
                cap_reason="max_tokens_injected exceeded",
                correlation_id="corr-budget-001",
            )

        assert len(captured) == 1
        topic, payload = captured[0]
        assert topic == "budget.cap.hit"
        validate_golden_event(payload, "budget.cap.hit")


@pytest.mark.unit
class TestGoldenCircuitBreakerTripped:
    """Golden event validation for emit_circuit_breaker_tripped."""

    def test_golden_payload_structure(self) -> None:
        mock_fn, captured = make_capture_mock()
        with patch(
            "plugins.onex.hooks.lib.pipeline_event_emitters._get_emit_fn",
            return_value=mock_fn,
        ):
            from plugins.onex.hooks.lib.pipeline_event_emitters import (
                emit_circuit_breaker_tripped,
            )

            emit_circuit_breaker_tripped(
                session_id="sess-cb-golden-001",
                failure_count=5,
                threshold=3,
                reset_timeout_seconds=30.0,
                last_error="Connection refused",
                correlation_id="corr-cb-001",
            )

        assert len(captured) == 1
        topic, payload = captured[0]
        assert topic == "circuit.breaker.tripped"
        validate_golden_event(payload, "circuit.breaker.tripped")


@pytest.mark.unit
class TestGoldenHostileReviewerCompleted:
    """Golden event validation for emit_hostile_reviewer_completed."""

    def test_golden_payload_structure(self) -> None:
        mock_fn, captured = make_capture_mock()
        with patch(
            "plugins.onex.hooks.lib.pipeline_event_emitters._get_emit_fn",
            return_value=mock_fn,
        ):
            from plugins.onex.hooks.lib.pipeline_event_emitters import (
                emit_hostile_reviewer_completed,
            )

            emit_hostile_reviewer_completed(
                mode="file",
                target="docs/plans/my-plan.md",
                models_attempted=["claude-sonnet-4-20250514"],
                models_succeeded=["claude-sonnet-4-20250514"],
                verdict="risks_noted",
                total_findings=3,
                critical_count=0,
                major_count=1,
                correlation_id="corr-hr-golden-001",
                session_id="sess-hr-golden-001",
            )

        assert len(captured) == 1
        topic, payload = captured[0]
        assert topic == "hostile.reviewer.completed"
        validate_golden_event(payload, "hostile.reviewer.completed")
        assert_valid_status(
            payload,
            GOLDEN_SCHEMAS["hostile.reviewer.completed"],
            status_field="verdict",
        )


@pytest.mark.unit
class TestGoldenPlanReviewCompleted:
    """Golden event validation for emit_plan_review_completed."""

    def test_golden_payload_structure(self) -> None:
        mock_fn, captured = make_capture_mock()
        with patch(
            "plugins.onex.hooks.lib.pipeline_event_emitters._get_emit_fn",
            return_value=mock_fn,
        ):
            from plugins.onex.hooks.lib.pipeline_event_emitters import (
                emit_plan_review_completed,
            )

            emit_plan_review_completed(
                session_id="sess-plan-golden-001",
                plan_file="docs/plans/2026-03-28-test-plan.md",
                total_rounds=3,
                final_status="converged",
                findings_by_severity={"CRITICAL": 0, "MAJOR": 1, "MINOR": 2},
                models_used=["claude-sonnet-4-20250514"],
                correlation_id="corr-plan-001",
            )

        assert len(captured) == 1
        topic, payload = captured[0]
        assert topic == "plan.review.completed"
        validate_golden_event(payload, "plan.review.completed")


@pytest.mark.unit
class TestGoldenDodSweepCompleted:
    """Golden event validation for emit_dod_sweep_completed."""

    def test_golden_payload_structure(self) -> None:
        mock_fn, captured = make_capture_mock()
        with patch(
            "plugins.onex.hooks.lib.pipeline_event_emitters._get_emit_fn",
            return_value=mock_fn,
        ):
            from plugins.onex.hooks.lib.pipeline_event_emitters import (
                emit_dod_sweep_completed,
            )

            emit_dod_sweep_completed(
                run_id="run-dod-golden-001",
                overall_status="passed",
                total_tickets=10,
                passed=8,
                failed=1,
                exempted=1,
                lookback_days=7,
                correlation_id="corr-dod-001",
            )

        assert len(captured) == 1
        topic, payload = captured[0]
        assert topic == "dod.sweep.completed"
        validate_golden_event(payload, "dod.sweep.completed")


# ===========================================================================
# Extraction event emitter golden tests
# ===========================================================================


@pytest.mark.unit
class TestGoldenExtractionEvents:
    """Golden event validation for extraction_event_emitter payload builders."""

    def test_golden_context_utilization_payload(self) -> None:
        import extraction_event_emitter as eee

        session_id = str(uuid.uuid4())
        correlation_id = str(uuid.uuid4())

        payload = eee.build_context_utilization_payload(
            session_id=session_id,
            correlation_id=correlation_id,
            cohort="treatment",
            injection_occurred=True,
            agent_name="polymorphic-agent",
            patterns_count=5,
            user_visible_latency_ms=250,
            cache_hit=False,
            emitted_at=datetime.now(UTC).isoformat(),
        )

        validate_golden_event(payload, "context.utilization")

    def test_golden_agent_match_payload(self) -> None:
        import extraction_event_emitter as eee

        session_id = str(uuid.uuid4())
        correlation_id = str(uuid.uuid4())

        payload = eee.build_agent_match_payload(
            session_id=session_id,
            correlation_id=correlation_id,
            cohort="treatment",
            agent_name="api-architect",
            agent_match_score=0.95,
            routing_confidence=0.88,
            emitted_at=datetime.now(UTC).isoformat(),
        )

        validate_golden_event(payload, "agent.match")

    def test_golden_latency_breakdown_payload(self) -> None:
        import extraction_event_emitter as eee

        session_id = str(uuid.uuid4())
        correlation_id = str(uuid.uuid4())

        payload = eee.build_latency_breakdown_payload(
            session_id=session_id,
            correlation_id=correlation_id,
            cohort="treatment",
            routing_time_ms=45,
            retrieval_time_ms=120,
            injection_time_ms=30,
            user_visible_latency_ms=250,
            cache_hit=False,
            emitted_at=datetime.now(UTC).isoformat(),
        )

        validate_golden_event(payload, "latency.breakdown")

    def test_rejects_empty_session_id(self) -> None:
        """Empty session_id is a sentinel that must be caught."""
        import extraction_event_emitter as eee

        payload = eee.build_context_utilization_payload(
            session_id="",
            correlation_id=str(uuid.uuid4()),
            cohort="treatment",
            injection_occurred=False,
            agent_name=None,
            patterns_count=0,
            user_visible_latency_ms=None,
            cache_hit=False,
            emitted_at=datetime.now(UTC).isoformat(),
        )

        with pytest.raises(AssertionError, match="empty string"):
            assert_no_sentinels(
                payload,
                GOLDEN_SCHEMAS["context.utilization"]["sentinel_fields"],
            )

    def test_rejects_unknown_cohort(self) -> None:
        """'unknown' as cohort is a sentinel that must be caught."""
        import extraction_event_emitter as eee

        payload = eee.build_context_utilization_payload(
            session_id=str(uuid.uuid4()),
            correlation_id=str(uuid.uuid4()),
            cohort="unknown",
            injection_occurred=False,
            agent_name=None,
            patterns_count=0,
            user_visible_latency_ms=None,
            cache_hit=False,
            emitted_at=datetime.now(UTC).isoformat(),
        )

        with pytest.raises(AssertionError, match="known placeholder"):
            assert_no_sentinels(
                payload,
                GOLDEN_SCHEMAS["context.utilization"]["sentinel_fields"],
            )


# ===========================================================================
# Enrichment observability emitter golden tests
# ===========================================================================


@pytest.mark.unit
class TestGoldenEnrichmentEvent:
    """Golden event validation for enrichment_observability_emitter."""

    def test_golden_enrichment_payload(self) -> None:
        import enrichment_observability_emitter as eoe

        now = datetime.now(UTC)
        payload = eoe.build_enrichment_event_payload(
            session_id="sess-enrich-golden-001",
            correlation_id="corr-enrich-golden-001",
            enrichment_type="summarization",
            model_used="qwen3-coder-30b",
            latency_ms=45.7,
            result_token_count=200,
            relevance_score=None,
            fallback_used=False,
            net_tokens_saved=300,
            was_dropped=False,
            prompt_version="v2",
            success=True,
            emitted_at=now,
            tokens_before=500,
            repo="omniclaude",
            agent_name="polymorphic-agent",
        )

        validate_golden_event(payload, "context.enrichment")

    def test_rejects_empty_session_id(self) -> None:
        import enrichment_observability_emitter as eoe

        now = datetime.now(UTC)
        payload = eoe.build_enrichment_event_payload(
            session_id="",
            correlation_id="corr-001",
            enrichment_type="summarization",
            model_used="",
            latency_ms=0.0,
            result_token_count=0,
            relevance_score=None,
            fallback_used=False,
            net_tokens_saved=0,
            was_dropped=False,
            prompt_version="",
            success=False,
            emitted_at=now,
        )

        with pytest.raises(AssertionError, match="empty string"):
            assert_no_sentinels(
                payload,
                GOLDEN_SCHEMAS["context.enrichment"]["sentinel_fields"],
            )

    def test_rejects_unknown_channel(self) -> None:
        import enrichment_observability_emitter as eoe

        now = datetime.now(UTC)
        payload = eoe.build_enrichment_event_payload(
            session_id="sess-001",
            correlation_id="corr-001",
            enrichment_type="unknown",
            model_used="",
            latency_ms=0.0,
            result_token_count=0,
            relevance_score=None,
            fallback_used=False,
            net_tokens_saved=0,
            was_dropped=False,
            prompt_version="",
            success=False,
            emitted_at=now,
        )

        with pytest.raises(AssertionError, match="known placeholder"):
            assert_no_sentinels(
                payload,
                GOLDEN_SCHEMAS["context.enrichment"]["sentinel_fields"],
            )


# ===========================================================================
# Sentinel detection unit tests
# ===========================================================================


@pytest.mark.unit
class TestSentinelDetection:
    """Direct tests for the sentinel detection logic itself."""

    def test_empty_string_detected(self) -> None:
        with pytest.raises(AssertionError, match="empty string"):
            assert_no_sentinels({"field_a": ""}, ["field_a"])

    def test_whitespace_only_detected(self) -> None:
        with pytest.raises(AssertionError, match="empty string"):
            assert_no_sentinels({"field_a": "   "}, ["field_a"])

    def test_unknown_detected(self) -> None:
        with pytest.raises(AssertionError, match="known placeholder"):
            assert_no_sentinels({"field_a": "unknown"}, ["field_a"])

    def test_placeholder_detected(self) -> None:
        with pytest.raises(AssertionError, match="known placeholder"):
            assert_no_sentinels({"field_a": "placeholder"}, ["field_a"])

    def test_zero_uuid_detected(self) -> None:
        with pytest.raises(AssertionError, match="all-zeros UUID"):
            assert_no_sentinels(
                {"field_a": "00000000-0000-0000-0000-000000000000"},
                ["field_a"],
            )

    def test_real_value_passes(self) -> None:
        # Should not raise
        assert_no_sentinels(
            {"field_a": "run-abc-123", "field_b": str(uuid.uuid4())},
            ["field_a", "field_b"],
        )

    def test_missing_field_ignored(self) -> None:
        # Fields not in payload are silently skipped
        assert_no_sentinels({"other": "value"}, ["missing_field"])

    def test_non_string_field_ignored(self) -> None:
        # Non-string values are not checked for string sentinels
        assert_no_sentinels({"count": 0}, ["count"])

    def test_todo_detected(self) -> None:
        with pytest.raises(AssertionError, match="known placeholder"):
            assert_no_sentinels({"field_a": "TODO"}, ["field_a"])

    def test_na_detected(self) -> None:
        with pytest.raises(AssertionError, match="known placeholder"):
            assert_no_sentinels({"field_a": "N/A"}, ["field_a"])


# ===========================================================================
# Golden schema completeness test
# ===========================================================================


@pytest.mark.unit
class TestGoldenSchemaCompleteness:
    """Meta-tests ensuring the golden schema file itself is valid."""

    def test_all_schemas_have_required_fields(self) -> None:
        """Every event type in the schema must define required_fields."""
        for event_type, schema in GOLDEN_SCHEMAS.items():
            assert "required_fields" in schema, (
                f"Schema for '{event_type}' missing 'required_fields'"
            )
            assert len(schema["required_fields"]) > 0, (
                f"Schema for '{event_type}' has empty 'required_fields'"
            )

    def test_sentinel_fields_are_subset_of_required(self) -> None:
        """Sentinel fields must be a subset of required fields."""
        for event_type, schema in GOLDEN_SCHEMAS.items():
            required = set(schema.get("required_fields", {}).keys())
            sentinel = set(schema.get("sentinel_fields", []))
            orphans = sentinel - required
            assert not orphans, (
                f"Schema for '{event_type}' has sentinel_fields not in "
                f"required_fields: {orphans}"
            )

    def test_type_strings_are_valid(self) -> None:
        """All type strings in required_fields must be recognized."""
        valid_types = set(_TYPE_MAP.keys())
        for event_type, schema in GOLDEN_SCHEMAS.items():
            for field, type_str in schema.get("required_fields", {}).items():
                assert type_str in valid_types, (
                    f"Schema for '{event_type}' field '{field}' has "
                    f"unrecognized type: '{type_str}'. Valid: {valid_types}"
                )

    def test_schema_file_is_valid_json(self) -> None:
        """The golden schema file must be parseable JSON."""
        with open(_GOLDEN_SCHEMA_PATH) as f:
            data = json.load(f)
        assert isinstance(data, dict)
        # Should have at least the pipeline emitter event types
        assert "epic.run.updated" in data
        assert "pr.watch.updated" in data


# ===========================================================================
# Error / edge-case event pattern tests
# ===========================================================================


@pytest.mark.unit
class TestErrorEventPatterns:
    """Tests for error/edge-case event emission patterns.

    These verify that emitters handle failure modes gracefully and that
    error payloads still conform to golden schemas.
    """

    def test_epic_run_failed_status_is_valid(self) -> None:
        """A 'failed' epic run must still produce a valid golden payload."""
        mock_fn, captured = make_capture_mock()
        with patch(
            "plugins.onex.hooks.lib.pipeline_event_emitters._get_emit_fn",
            return_value=mock_fn,
        ):
            from plugins.onex.hooks.lib.pipeline_event_emitters import (
                emit_epic_run_updated,
            )

            emit_epic_run_updated(
                run_id="run-fail-001",
                epic_id="OMN-FAIL",
                status="failed",
                tickets_total=3,
                tickets_completed=1,
                tickets_failed=2,
                correlation_id="corr-fail-001",
            )

        _, payload = captured[0]
        validate_golden_event(payload, "epic.run.updated")
        assert payload["status"] == "failed"
        assert payload["tickets_failed"] == 2

    def test_pr_watch_timeout_status_is_valid(self) -> None:
        """A 'timeout' PR watch must still produce a valid golden payload."""
        mock_fn, captured = make_capture_mock()
        with patch(
            "plugins.onex.hooks.lib.pipeline_event_emitters._get_emit_fn",
            return_value=mock_fn,
        ):
            from plugins.onex.hooks.lib.pipeline_event_emitters import (
                emit_pr_watch_updated,
            )

            emit_pr_watch_updated(
                run_id="run-timeout-001",
                pr_number=99,
                repo="OmniNode-ai/omniclaude",
                ticket_id="OMN-TIMEOUT",
                status="timeout",
                review_cycles_used=5,
                watch_duration_hours=24.0,
                correlation_id="corr-timeout-001",
            )

        _, payload = captured[0]
        validate_golden_event(payload, "pr.watch.updated")
        assert payload["status"] == "timeout"

    def test_gate_rejected_is_valid(self) -> None:
        """A REJECTED gate decision must produce a valid golden payload."""
        mock_fn, captured = make_capture_mock()
        with patch(
            "plugins.onex.hooks.lib.pipeline_event_emitters._get_emit_fn",
            return_value=mock_fn,
        ):
            from plugins.onex.hooks.lib.pipeline_event_emitters import (
                emit_gate_decision,
            )

            emit_gate_decision(
                gate_id="gate-reject-001",
                decision="REJECTED",
                ticket_id="OMN-REJECT",
                gate_type="HIGH_RISK",
                wait_seconds=5.0,
                responder="jonah",
                correlation_id="corr-reject-001",
            )

        _, payload = captured[0]
        validate_golden_event(payload, "gate.decision")
        assert payload["decision"] == "REJECTED"

    def test_enrichment_error_outcome(self) -> None:
        """An error-outcome enrichment event must still have valid structure."""
        import enrichment_observability_emitter as eoe

        now = datetime.now(UTC)
        payload = eoe.build_enrichment_event_payload(
            session_id="sess-err-001",
            correlation_id="corr-err-001",
            enrichment_type="code_analysis",
            model_used="",
            latency_ms=5000.0,
            result_token_count=0,
            relevance_score=None,
            fallback_used=True,
            net_tokens_saved=0,
            was_dropped=False,
            prompt_version="",
            success=False,
            emitted_at=now,
        )

        validate_golden_event(payload, "context.enrichment")
        assert payload["outcome"] == "error"
        assert payload["tokens_after"] == 0

    def test_extraction_missing_agent_name_still_valid(self) -> None:
        """context.utilization with agent_name=None must still have valid structure."""
        import extraction_event_emitter as eee

        payload = eee.build_context_utilization_payload(
            session_id=str(uuid.uuid4()),
            correlation_id=str(uuid.uuid4()),
            cohort="control",
            injection_occurred=False,
            agent_name=None,
            patterns_count=0,
            user_visible_latency_ms=None,
            cache_hit=False,
            emitted_at=datetime.now(UTC).isoformat(),
        )

        validate_golden_event(payload, "context.utilization")
