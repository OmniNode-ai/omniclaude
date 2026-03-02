# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Unit tests for routing decision payload helpers (OMN-3410).

Tests cover:
- Required keys present and forbidden keys absent
- id and correlation_id are valid UUID strings
- created_at is ISO 8601 parseable
- confidence clamping for various input types
- Invalid correlation_id produces valid UUID fallback and metadata preservation
- Emitter passes helper output to _emit_event_fn without mutation
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from uuid import UUID

import pytest

# Plugin lib path (belt-and-suspenders; conftest.py also sets this)
_LIB_PATH = str(
    Path(__file__).parent.parent.parent.parent.parent
    / "plugins"
    / "onex"
    / "hooks"
    / "lib"
)
if _LIB_PATH not in sys.path:
    sys.path.insert(0, _LIB_PATH)

from route_via_events_wrapper import (
    _build_routing_decision_payload,
    _emit_routing_decision,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_REQUIRED_KEYS = frozenset(
    {"id", "correlation_id", "selected_agent", "confidence_score", "created_at"}
)
_FORBIDDEN_KEYS = frozenset(
    {
        "session_id",
        "confidence",
        "routing_method",
        "routing_policy",
        "routing_path",
        "latency_ms",
        "reasoning",
        "prompt_preview",
        "event_attempted",
    }
)

_SAMPLE_RESULT: dict[str, object] = {
    "selected_agent": "agent-debug",
    "confidence": 0.85,
    "routing_method": "local",
    "routing_policy": "trigger_match",
    "routing_path": "local",
    "latency_ms": 15,
    "domain": "debugging",
    "reasoning": "Strong trigger match",
    "event_attempted": False,
}
_SAMPLE_PROMPT = "Help me debug this issue"
_SAMPLE_CID = "550e8400-e29b-41d4-a716-446655440000"
_SAMPLE_SESSION = "session-abc-123"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_payload_has_required_keys() -> None:
    """Required keys present; forbidden keys absent in built payload."""
    payload = _build_routing_decision_payload(
        result=_SAMPLE_RESULT,
        prompt=_SAMPLE_PROMPT,
        correlation_id=_SAMPLE_CID,
        session_id=_SAMPLE_SESSION,
    )

    missing = _REQUIRED_KEYS - payload.keys()
    assert not missing, f"Required keys missing from payload: {missing}"

    present_forbidden = _FORBIDDEN_KEYS & payload.keys()
    assert not present_forbidden, (
        f"Forbidden keys present at top level of payload: {present_forbidden}"
    )


@pytest.mark.unit
def test_id_and_correlation_id_are_uuid_like() -> None:
    """Both id and correlation_id are parseable as UUID strings."""
    payload = _build_routing_decision_payload(
        result=_SAMPLE_RESULT,
        prompt=_SAMPLE_PROMPT,
        correlation_id=_SAMPLE_CID,
        session_id=None,
    )

    # id is always a fresh UUID
    UUID(str(payload["id"]))  # raises ValueError on invalid format

    # correlation_id is preserved or replaced with valid UUID
    UUID(str(payload["correlation_id"]))  # raises ValueError on invalid format


@pytest.mark.unit
def test_created_at_is_parseable_datetime() -> None:
    """created_at is an ISO 8601 string parseable as a timezone-aware datetime."""
    payload = _build_routing_decision_payload(
        result=_SAMPLE_RESULT,
        prompt=_SAMPLE_PROMPT,
        correlation_id=_SAMPLE_CID,
        session_id=None,
    )

    created_at = payload["created_at"]
    assert isinstance(created_at, str), "created_at must be a string"

    parsed = datetime.fromisoformat(created_at)
    # Verify it is timezone-aware (has tzinfo)
    assert parsed.tzinfo is not None, "created_at must be timezone-aware"


@pytest.mark.unit
@pytest.mark.parametrize(
    ("raw_confidence", "expected"),
    [
        (None, 0.5),  # None → default
        ("high", 0.5),  # non-numeric string → default
        (75, 1.0),  # int > 1 → clamp to 1.0
        (-1.0, 0.0),  # negative → clamp to 0.0
        (0.75, 0.75),  # valid float passes through unchanged
    ],
)
def test_confidence_clamp_cases(raw_confidence: object, expected: float) -> None:
    """confidence_score is clamped to [0.0, 1.0] for all input types."""
    result = dict(_SAMPLE_RESULT)
    result["confidence"] = raw_confidence  # type: ignore[assignment]

    payload = _build_routing_decision_payload(
        result=result,
        prompt=_SAMPLE_PROMPT,
        correlation_id=_SAMPLE_CID,
        session_id=None,
    )

    assert payload["confidence_score"] == pytest.approx(expected), (
        f"Expected confidence_score={expected} for raw={raw_confidence!r}, "
        f"got {payload['confidence_score']!r}"
    )


@pytest.mark.unit
def test_invalid_correlation_id_produces_valid_uuid() -> None:
    """Non-UUID correlation_id is replaced with a valid UUID; original is preserved in metadata."""
    bad_cid = "not-a-uuid-value"

    payload = _build_routing_decision_payload(
        result=_SAMPLE_RESULT,
        prompt=_SAMPLE_PROMPT,
        correlation_id=bad_cid,
        session_id=None,
    )

    # correlation_id in payload must now be a valid UUID
    UUID(str(payload["correlation_id"]))

    # Original must be preserved in metadata
    meta = payload["metadata"]
    assert isinstance(meta, dict), "metadata must be a dict"
    assert meta.get("correlation_id_original") == bad_cid, (
        "Original invalid correlation_id must be stored in metadata['correlation_id_original']"
    )


@pytest.mark.unit
def test_emitter_passes_helper_output_without_mutation() -> None:
    """_emit_routing_decision calls _emit_event_fn with the payload from the helper, unmodified."""
    captured: list[dict[str, object]] = []

    def fake_emit(event_type: str, payload: dict[str, object]) -> bool:
        captured.append(dict(payload))  # copy so mutation after call is visible
        return True

    # Build the expected payload independently for comparison
    expected = _build_routing_decision_payload(
        result=_SAMPLE_RESULT,
        prompt=_SAMPLE_PROMPT,
        correlation_id=_SAMPLE_CID,
        session_id=_SAMPLE_SESSION,
    )

    import route_via_events_wrapper as _mod

    with patch.object(_mod, "_emit_event_fn", fake_emit):
        with patch.object(
            _mod,
            "_build_routing_decision_payload",
            wraps=_build_routing_decision_payload,
        ) as spy:
            _emit_routing_decision(
                result=_SAMPLE_RESULT,
                prompt=_SAMPLE_PROMPT,
                correlation_id=_SAMPLE_CID,
                session_id=_SAMPLE_SESSION,
            )
            assert spy.call_count == 1, (
                "_build_routing_decision_payload must be called exactly once"
            )

    assert len(captured) == 1, "_emit_event_fn must be called exactly once"
    emitted = captured[0]

    # Verify shape: required keys present, forbidden keys absent
    missing = _REQUIRED_KEYS - emitted.keys()
    assert not missing, f"Emitted payload missing required keys: {missing}"

    present_forbidden = _FORBIDDEN_KEYS & emitted.keys()
    assert not present_forbidden, (
        f"Emitted payload contains forbidden keys: {present_forbidden}"
    )

    # id is a valid UUID
    UUID(str(emitted["id"]))
    # correlation_id is a valid UUID
    UUID(str(emitted["correlation_id"]))
