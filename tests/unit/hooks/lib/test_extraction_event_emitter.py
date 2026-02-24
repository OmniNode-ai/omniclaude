# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Unit tests for extraction_event_emitter.py (OMN-2344).

Tests cover:
- build_context_utilization_payload: required fields including cohort, injection_occurred
- build_agent_match_payload: required fields including cohort, agent_match_score
- build_latency_breakdown_payload: renamed fields (routing_time_ms, injection_time_ms,
  user_visible_latency_ms) and required cohort
- emit_extraction_events: baseline 3-event emission, agent.match skipped without agent_name,
  missing session_id short-circuit, count return values
- Graceful degradation when emit_client_wrapper is unavailable
- Helper functions: _to_entity_id, _safe_float, _safe_int, _safe_bool

All tests run without network access or external services.
"""

from __future__ import annotations

import sys
import uuid
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

import extraction_event_emitter as eee

# All tests in this module are unit tests
pytestmark = pytest.mark.unit

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_SESSION_ID = str(uuid.uuid4())
_CORR_ID = str(uuid.uuid4())


def _make_emit_mock(return_value: bool = True) -> MagicMock:
    return MagicMock(return_value=return_value)


def _minimal_data(**overrides: Any) -> dict[str, Any]:
    """Minimal valid input dict for emit_extraction_events."""
    base: dict[str, Any] = {
        "session_id": _SESSION_ID,
        "correlation_id": _CORR_ID,
        "agent_name": "polymorphic-agent",
        "agent_match_score": 0.9,
        "routing_confidence": 0.85,
        "cohort": "treatment",
        "injection_occurred": True,
        "patterns_count": 3,
        "routing_time_ms": 45,
        "retrieval_time_ms": 120,
        "injection_time_ms": 30,
        "user_visible_latency_ms": 250,
        "cache_hit": False,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# 1. build_context_utilization_payload
# ---------------------------------------------------------------------------


class TestBuildContextUtilizationPayload:
    """Tests for build_context_utilization_payload()."""

    def test_all_required_fields_present(self) -> None:
        """Payload must contain all fields required by omnidash consumer."""
        payload = eee.build_context_utilization_payload(
            session_id=_SESSION_ID,
            correlation_id=_CORR_ID,
            cohort="treatment",
            injection_occurred=True,
            agent_name="agent-api-architect",
            patterns_count=3,
            user_visible_latency_ms=250,
            cache_hit=False,
            emitted_at="2026-01-01T00:00:00+00:00",
        )
        required = {
            "session_id",
            "entity_id",
            "correlation_id",
            "causation_id",
            "emitted_at",
            "cohort",
            "injection_occurred",
            "agent_name",
            "patterns_count",
            "user_visible_latency_ms",
            "cache_hit",
            "utilization_score",
            "method",
            "injected_count",
            "reused_count",
            "detection_duration_ms",
        }
        assert required <= set(payload.keys())

    def test_cohort_value_propagated(self) -> None:
        """cohort field must match the input — this is the omnidash type guard key."""
        payload = eee.build_context_utilization_payload(
            session_id=_SESSION_ID,
            correlation_id=_CORR_ID,
            cohort="control",
            injection_occurred=False,
            agent_name=None,
            patterns_count=0,
            user_visible_latency_ms=None,
            cache_hit=False,
            emitted_at="2026-01-01T00:00:00+00:00",
        )
        assert payload["cohort"] == "control"

    def test_utilization_score_defaults_to_zero(self) -> None:
        """utilization_score is 0.0 at hook time (response not yet generated)."""
        payload = eee.build_context_utilization_payload(
            session_id=_SESSION_ID,
            correlation_id=_CORR_ID,
            cohort="treatment",
            injection_occurred=True,
            agent_name="agent-x",
            patterns_count=2,
            user_visible_latency_ms=100,
            cache_hit=True,
            emitted_at="2026-01-01T00:00:00+00:00",
        )
        assert payload["utilization_score"] == 0.0

    def test_method_defaults_to_timeout_fallback(self) -> None:
        """method='timeout_fallback' at hook time (identifier overlap not yet run)."""
        payload = eee.build_context_utilization_payload(
            session_id=_SESSION_ID,
            correlation_id=_CORR_ID,
            cohort="treatment",
            injection_occurred=False,
            agent_name=None,
            patterns_count=0,
            user_visible_latency_ms=None,
            cache_hit=False,
            emitted_at="2026-01-01T00:00:00+00:00",
        )
        assert payload["method"] == "timeout_fallback"

    def test_entity_id_equals_session_id_when_valid_uuid(self) -> None:
        """entity_id must be the session_id string when it is a valid UUID."""
        sid = str(uuid.uuid4())
        payload = eee.build_context_utilization_payload(
            session_id=sid,
            correlation_id=_CORR_ID,
            cohort="treatment",
            injection_occurred=False,
            agent_name=None,
            patterns_count=0,
            user_visible_latency_ms=None,
            cache_hit=False,
            emitted_at="2026-01-01T00:00:00+00:00",
        )
        assert payload["entity_id"] == sid


# ---------------------------------------------------------------------------
# 2. build_agent_match_payload
# ---------------------------------------------------------------------------


class TestBuildAgentMatchPayload:
    """Tests for build_agent_match_payload()."""

    def test_all_required_fields_present(self) -> None:
        """Payload must contain cohort, agent_match_score, and standard envelope fields."""
        payload = eee.build_agent_match_payload(
            session_id=_SESSION_ID,
            correlation_id=_CORR_ID,
            cohort="treatment",
            agent_name="polymorphic-agent",
            agent_match_score=0.9,
            routing_confidence=0.85,
            emitted_at="2026-01-01T00:00:00+00:00",
        )
        required = {
            "session_id",
            "entity_id",
            "correlation_id",
            "causation_id",
            "emitted_at",
            "cohort",
            "selected_agent",
            "expected_agent",
            "match_grade",
            "agent_match_score",
            "confidence",
            "routing_method",
        }
        assert required <= set(payload.keys())

    def test_cohort_propagated(self) -> None:
        payload = eee.build_agent_match_payload(
            session_id=_SESSION_ID,
            correlation_id=_CORR_ID,
            cohort="control",
            agent_name="agent-x",
            agent_match_score=0.5,
            routing_confidence=0.6,
            emitted_at="2026-01-01T00:00:00+00:00",
        )
        assert payload["cohort"] == "control"

    def test_agent_match_score_propagated(self) -> None:
        """agent_match_score from routing confidence must appear in payload."""
        payload = eee.build_agent_match_payload(
            session_id=_SESSION_ID,
            correlation_id=_CORR_ID,
            cohort="treatment",
            agent_name="agent-api-architect",
            agent_match_score=0.72,
            routing_confidence=0.68,
            emitted_at="2026-01-01T00:00:00+00:00",
        )
        assert payload["agent_match_score"] == pytest.approx(0.72, abs=1e-9)
        assert payload["confidence"] == pytest.approx(0.68, abs=1e-9)

    def test_selected_agent_propagated(self) -> None:
        payload = eee.build_agent_match_payload(
            session_id=_SESSION_ID,
            correlation_id=_CORR_ID,
            cohort="treatment",
            agent_name="agent-data-scientist",
            agent_match_score=0.8,
            routing_confidence=0.75,
            emitted_at="2026-01-01T00:00:00+00:00",
        )
        assert payload["selected_agent"] == "agent-data-scientist"

    def test_routing_method_is_event_routing(self) -> None:
        payload = eee.build_agent_match_payload(
            session_id=_SESSION_ID,
            correlation_id=_CORR_ID,
            cohort="treatment",
            agent_name="polymorphic-agent",
            agent_match_score=0.5,
            routing_confidence=0.5,
            emitted_at="2026-01-01T00:00:00+00:00",
        )
        assert payload["routing_method"] == "event_routing"


# ---------------------------------------------------------------------------
# 3. build_latency_breakdown_payload
# ---------------------------------------------------------------------------


class TestBuildLatencyBreakdownPayload:
    """Tests for build_latency_breakdown_payload() — verifies renamed fields."""

    def test_all_required_fields_present(self) -> None:
        """Payload must use renamed fields: routing_time_ms, injection_time_ms, user_visible_latency_ms."""
        payload = eee.build_latency_breakdown_payload(
            session_id=_SESSION_ID,
            correlation_id=_CORR_ID,
            cohort="treatment",
            routing_time_ms=45,
            retrieval_time_ms=120,
            injection_time_ms=30,
            user_visible_latency_ms=250,
            cache_hit=False,
            emitted_at="2026-01-01T00:00:00+00:00",
        )
        required = {
            "session_id",
            "entity_id",
            "correlation_id",
            "causation_id",
            "emitted_at",
            "cohort",
            "routing_time_ms",
            "retrieval_time_ms",
            "injection_time_ms",
            "total_hook_ms",
            "user_visible_latency_ms",
            "cache_hit",
            "agent_load_ms",
        }
        assert required <= set(payload.keys())

    def test_old_field_names_absent(self) -> None:
        """routing_ms, context_injection_ms, user_perceived_ms must NOT appear (they were renamed)."""
        payload = eee.build_latency_breakdown_payload(
            session_id=_SESSION_ID,
            correlation_id=_CORR_ID,
            cohort="treatment",
            routing_time_ms=45,
            retrieval_time_ms=None,
            injection_time_ms=30,
            user_visible_latency_ms=None,
            cache_hit=False,
            emitted_at="2026-01-01T00:00:00+00:00",
        )
        assert "routing_ms" not in payload
        assert "context_injection_ms" not in payload
        assert "user_perceived_ms" not in payload

    def test_cohort_propagated(self) -> None:
        payload = eee.build_latency_breakdown_payload(
            session_id=_SESSION_ID,
            correlation_id=_CORR_ID,
            cohort="control",
            routing_time_ms=10,
            retrieval_time_ms=None,
            injection_time_ms=5,
            user_visible_latency_ms=100,
            cache_hit=True,
            emitted_at="2026-01-01T00:00:00+00:00",
        )
        assert payload["cohort"] == "control"

    def test_field_values_match_inputs(self) -> None:
        payload = eee.build_latency_breakdown_payload(
            session_id=_SESSION_ID,
            correlation_id=_CORR_ID,
            cohort="treatment",
            routing_time_ms=55,
            retrieval_time_ms=130,
            injection_time_ms=40,
            user_visible_latency_ms=300,
            cache_hit=True,
            emitted_at="2026-01-01T00:00:00+00:00",
        )
        assert payload["routing_time_ms"] == 55
        assert payload["retrieval_time_ms"] == 130
        assert payload["injection_time_ms"] == 40
        assert payload["user_visible_latency_ms"] == 300
        assert payload["cache_hit"] is True

    def test_total_hook_ms_uses_user_visible_latency(self) -> None:
        """total_hook_ms should equal user_visible_latency_ms when provided."""
        payload = eee.build_latency_breakdown_payload(
            session_id=_SESSION_ID,
            correlation_id=_CORR_ID,
            cohort="treatment",
            routing_time_ms=20,
            retrieval_time_ms=None,
            injection_time_ms=10,
            user_visible_latency_ms=200,
            cache_hit=False,
            emitted_at="2026-01-01T00:00:00+00:00",
        )
        assert payload["total_hook_ms"] == 200

    def test_total_hook_ms_zero_when_latency_none(self) -> None:
        """total_hook_ms falls back to 0 when user_visible_latency_ms is None."""
        payload = eee.build_latency_breakdown_payload(
            session_id=_SESSION_ID,
            correlation_id=_CORR_ID,
            cohort="treatment",
            routing_time_ms=10,
            retrieval_time_ms=None,
            injection_time_ms=5,
            user_visible_latency_ms=None,
            cache_hit=False,
            emitted_at="2026-01-01T00:00:00+00:00",
        )
        assert payload["total_hook_ms"] == 0


# ---------------------------------------------------------------------------
# 4. emit_extraction_events — baseline flow
# ---------------------------------------------------------------------------


class TestEmitExtractionEventsBasic:
    """Tests for the primary emit_extraction_events() flow."""

    def test_emits_three_events_when_agent_name_present(self) -> None:
        """All three event types must be emitted when agent_name is provided."""
        mock_emit = _make_emit_mock(True)
        data = _minimal_data()
        with patch.object(eee, "_emit_event", mock_emit):
            count = eee.emit_extraction_events(data)
        assert count == 3
        assert mock_emit.call_count == 3

    def test_event_types_emitted(self) -> None:
        """Exactly the three omnidash-required event types must be emitted."""
        called_types: list[str] = []

        def _capture(event_type: str, payload: Any) -> bool:
            called_types.append(event_type)
            return True

        with patch.object(eee, "_emit_event", _capture):
            eee.emit_extraction_events(_minimal_data())

        assert set(called_types) == {
            "context.utilization",
            "agent.match",
            "latency.breakdown",
        }

    def test_emits_two_events_when_no_agent_name(self) -> None:
        """agent.match must be skipped when agent_name is absent/empty."""
        mock_emit = _make_emit_mock(True)
        data = _minimal_data(agent_name="")
        with patch.object(eee, "_emit_event", mock_emit):
            count = eee.emit_extraction_events(data)
        assert count == 2
        called_types = [call.args[0] for call in mock_emit.call_args_list]
        assert "agent.match" not in called_types

    def test_returns_zero_when_session_id_missing(self) -> None:
        """Missing session_id must cause a no-op (returns 0, no emit calls)."""
        mock_emit = _make_emit_mock(True)
        data = _minimal_data(session_id="")
        with patch.object(eee, "_emit_event", mock_emit):
            count = eee.emit_extraction_events(data)
        assert count == 0
        mock_emit.assert_not_called()

    def test_failed_emit_not_counted(self) -> None:
        """When emit returns False, the failed event is not counted."""
        mock_emit = _make_emit_mock(False)
        with patch.object(eee, "_emit_event", mock_emit):
            count = eee.emit_extraction_events(_minimal_data())
        assert count == 0

    def test_cohort_appears_in_all_emitted_payloads(self) -> None:
        """All three payloads must include the cohort field to pass omnidash type guard."""
        payloads: list[dict[str, Any]] = []

        def _capture(event_type: str, payload: dict[str, Any]) -> bool:
            payloads.append(payload)
            return True

        with patch.object(eee, "_emit_event", _capture):
            eee.emit_extraction_events(_minimal_data(cohort="control"))

        assert len(payloads) == 3
        for p in payloads:
            assert p.get("cohort") == "control", f"cohort missing or wrong in {p}"

    def test_partial_emit_failure_still_returns_successes(self) -> None:
        """Count reflects only successful emits even when some fail."""
        call_count = 0

        def _alternating(event_type: str, payload: Any) -> bool:
            nonlocal call_count
            call_count += 1
            return call_count % 2 == 0  # even calls succeed

        with patch.object(eee, "_emit_event", _alternating):
            count = eee.emit_extraction_events(_minimal_data())
        # 3 calls: 1→False, 2→True, 3→False → 1 success
        assert count == 1


# ---------------------------------------------------------------------------
# 5. Graceful degradation
# ---------------------------------------------------------------------------


class TestGracefulDegradation:
    """Tests that emission failures never propagate to callers."""

    def test_returns_zero_when_emit_event_is_none(self) -> None:
        """When _emit_event is None (import failed), returns 0 without raising."""
        with patch.object(eee, "_emit_event", None):
            count = eee.emit_extraction_events(_minimal_data())
        assert count == 0

    def test_exception_in_emit_event_does_not_propagate(self) -> None:
        """RuntimeError from daemon is caught and does not escape emit_extraction_events."""

        def _raise(event_type: str, payload: Any) -> bool:
            raise RuntimeError("daemon down")

        with patch.object(eee, "_emit_event", _raise):
            count = eee.emit_extraction_events(_minimal_data())
        # All 3 calls raise → 0 successes
        assert count == 0

    def test_empty_data_does_not_raise(self) -> None:
        """emit_extraction_events({}) must not raise even with all defaults applied."""
        mock_emit = _make_emit_mock(True)
        with patch.object(eee, "_emit_event", mock_emit):
            count = eee.emit_extraction_events({})
        # Empty session_id → early return
        assert count == 0


# ---------------------------------------------------------------------------
# 6. _to_entity_id helper
# ---------------------------------------------------------------------------


class TestToEntityId:
    """Tests for _to_entity_id()."""

    def test_valid_uuid_returned_unchanged(self) -> None:
        sid = str(uuid.uuid4())
        assert eee._to_entity_id(sid) == sid

    def test_invalid_string_returns_deterministic_uuid(self) -> None:
        """Non-UUID input must return a stable UUID-formatted string."""
        result1 = eee._to_entity_id("not-a-uuid")
        result2 = eee._to_entity_id("not-a-uuid")
        assert result1 == result2  # deterministic
        # Must be parseable as a UUID
        uuid.UUID(result1)

    def test_different_inputs_produce_different_entity_ids(self) -> None:
        """Different non-UUID session IDs must yield different entity IDs."""
        a = eee._to_entity_id("session-alpha")
        b = eee._to_entity_id("session-beta")
        assert a != b


# ---------------------------------------------------------------------------
# 7. Helper functions
# ---------------------------------------------------------------------------


class TestSafeHelpers:
    """Tests for _safe_float, _safe_int, _safe_bool."""

    def test_safe_float_converts_string(self) -> None:
        assert eee._safe_float("0.75") == pytest.approx(0.75)

    def test_safe_float_returns_default_on_none(self) -> None:
        assert eee._safe_float(None) == 0.0

    def test_safe_float_returns_default_on_bad_string(self) -> None:
        assert eee._safe_float("bad", default=1.0) == 1.0

    def test_safe_int_converts_string(self) -> None:
        assert eee._safe_int("42") == 42

    def test_safe_int_returns_default_on_float_string(self) -> None:
        # int("3.9") raises ValueError in Python — _safe_int returns the default
        assert eee._safe_int("3.9", default=0) == 0

    def test_safe_int_returns_default_on_none(self) -> None:
        assert eee._safe_int(None) == 0

    def test_safe_bool_true_variants(self) -> None:
        for v in (True, "true", "True", "1", "yes"):
            assert eee._safe_bool(v) is True, f"Expected True for {v!r}"

    def test_safe_bool_false_variants(self) -> None:
        for v in (False, "false", "0", "no", ""):
            assert eee._safe_bool(v) is False, f"Expected False for {v!r}"

    def test_safe_bool_none_returns_default(self) -> None:
        assert eee._safe_bool(None, default=False) is False
        assert eee._safe_bool(None, default=True) is True
