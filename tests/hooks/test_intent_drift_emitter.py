# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Unit tests for intent_drift_emitter -- PostToolUse drift detection emitter.

Tests verify:
    - Drift event emitted when detect_drift returns a signal
    - No emit when detect_drift returns None
    - Graceful skip when no session intent is stored
    - Payload field names match omnidash's projectIntentDriftDetected expectations
    - Non-blocking: emitter failure does not propagate

Reference: OMN-7141
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

# Path bootstrap
_HOOKS_LIB = Path(__file__).parent.parent.parent / "plugins" / "onex" / "hooks" / "lib"
if str(_HOOKS_LIB) not in sys.path:
    sys.path.insert(0, str(_HOOKS_LIB))

from intent_drift_emitter import build_drift_payload, check_and_emit_drift


@pytest.mark.unit
class TestBuildDriftPayload:
    """Tests for the payload builder."""

    def test_payload_has_required_fields(self) -> None:
        """Payload contains all fields expected by omnidash projection."""
        payload = build_drift_payload(
            session_id="sess-123",
            original_intent="code_generation",
            detected_intent="testing",
            drift_score=0.7,
            severity="high",
            tool_name="Write",
            file_path="tests/test_foo.py",
        )
        assert payload["session_id"] == "sess-123"
        assert payload["original_intent"] == "code_generation"
        assert payload["current_intent"] == "testing"  # mapped from detected_intent
        assert payload["drift_score"] == 0.7
        assert payload["severity"] == "high"

    def test_payload_maps_detected_to_current(self) -> None:
        """DriftSignal.detected_intent is mapped to current_intent in payload."""
        payload = build_drift_payload(
            session_id="s",
            original_intent="bugfix",
            detected_intent="documentation",
            drift_score=0.5,
            severity="medium",
            tool_name="Edit",
        )
        # omnidash projection expects current_intent, not detected_intent
        assert "current_intent" in payload
        assert "detected_intent" not in payload
        assert payload["current_intent"] == "documentation"

    def test_payload_matches_omnidash_projection(self) -> None:
        """All field names match projectIntentDriftDetected extraction at
        omniintelligence-projections.ts:1278-1289.

        The projection expects:
            session_id / sessionId
            original_intent / originalIntent
            current_intent / currentIntent
            drift_score / driftScore
            severity
        """
        payload = build_drift_payload(
            session_id="s1",
            original_intent="refactoring",
            detected_intent="testing",
            drift_score=0.6,
            severity="medium",
            tool_name="Edit",
        )
        # Verify snake_case names (projection handles both snake and camel)
        required_fields = {
            "session_id",
            "original_intent",
            "current_intent",
            "drift_score",
            "severity",
        }
        assert required_fields.issubset(set(payload.keys()))


@pytest.mark.unit
class TestCheckAndEmitDrift:
    """Tests for the main check_and_emit_drift function."""

    def test_emits_drift_when_detected(self, tmp_path: Path) -> None:
        """When detect_drift returns a signal, the emitter calls emit_fn."""
        # Set up correlation state with intent
        import json

        state_dir = tmp_path / "state"
        state_dir.mkdir()
        state_file = state_dir / "correlation_id.json"
        state_file.write_text(
            json.dumps(
                {
                    "intent_id": "i-123",
                    "intent_class": "code_generation",
                    "intent_confidence": 0.85,
                }
            )
        )

        emit_fn = MagicMock()

        result = check_and_emit_drift(
            session_id="sess-1",
            tool_name="Write",
            file_path="tests/test_foo.py",  # file path suggests testing intent
            state_dir=state_dir,
            emit_fn=emit_fn,
        )

        assert result is True
        emit_fn.assert_called_once()
        event_type, payload_json = emit_fn.call_args[0]
        assert event_type == "intent.drift.detected"
        payload = json.loads(payload_json)
        assert payload["session_id"] == "sess-1"
        assert payload["original_intent"] == "code_generation"
        assert "current_intent" in payload
        assert isinstance(payload["drift_score"], float)

    def test_skips_when_no_drift(self, tmp_path: Path) -> None:
        """When detect_drift returns None, no event is emitted."""
        import json

        state_dir = tmp_path / "state"
        state_dir.mkdir()
        state_file = state_dir / "correlation_id.json"
        # investigation intent + Read tool = no drift (Read is expected)
        state_file.write_text(
            json.dumps(
                {
                    "intent_id": "i-456",
                    "intent_class": "investigation",
                    "intent_confidence": 0.9,
                }
            )
        )

        emit_fn = MagicMock()

        result = check_and_emit_drift(
            session_id="sess-2",
            tool_name="Read",
            file_path="src/main.py",
            state_dir=state_dir,
            emit_fn=emit_fn,
        )

        assert result is False
        emit_fn.assert_not_called()

    def test_skips_when_no_session_intent(self, tmp_path: Path) -> None:
        """When no intent is stored in correlation state, drift check is skipped."""
        state_dir = tmp_path / "state"
        state_dir.mkdir()
        # No correlation_id.json file

        emit_fn = MagicMock()

        result = check_and_emit_drift(
            session_id="sess-3",
            tool_name="Write",
            file_path="docs/README.md",
            state_dir=state_dir,
            emit_fn=emit_fn,
        )

        assert result is False
        emit_fn.assert_not_called()

    def test_skips_when_empty_intent_class(self, tmp_path: Path) -> None:
        """When intent_class is empty, drift check is skipped."""
        import json

        state_dir = tmp_path / "state"
        state_dir.mkdir()
        state_file = state_dir / "correlation_id.json"
        state_file.write_text(
            json.dumps(
                {
                    "intent_id": "i-789",
                    "intent_class": "",
                    "intent_confidence": 0.0,
                }
            )
        )

        emit_fn = MagicMock()

        result = check_and_emit_drift(
            session_id="sess-4",
            tool_name="Edit",
            state_dir=state_dir,
            emit_fn=emit_fn,
        )

        assert result is False
        emit_fn.assert_not_called()

    def test_emitter_failure_does_not_propagate(self, tmp_path: Path) -> None:
        """Emitter failure is swallowed -- returns False, does not raise."""
        import json

        state_dir = tmp_path / "state"
        state_dir.mkdir()
        state_file = state_dir / "correlation_id.json"
        state_file.write_text(
            json.dumps(
                {
                    "intent_id": "i-err",
                    "intent_class": "code_generation",
                    "intent_confidence": 0.8,
                }
            )
        )

        def exploding_emit(*args: Any) -> None:
            raise RuntimeError("emit daemon down")

        # Should not raise
        result = check_and_emit_drift(
            session_id="sess-5",
            tool_name="Write",
            file_path="tests/test_bar.py",
            state_dir=state_dir,
            emit_fn=exploding_emit,
        )

        assert result is False
