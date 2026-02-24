# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Tests for agent_status_emitter module.

This module tests the adapter layer for agent lifecycle status emission.
It validates:
- Valid state emission (happy path with mocked emit_event)
- Invalid state rejection (state string not in EnumAgentState)
- Environment variable fallback (agent_name/session_id from env)
- Pydantic validation errors (malformed input)
- Fail-open exception handling (emit_event raises, function does NOT raise)
- Metadata passthrough (extra metadata dict included in payload)
- correlation_id generation (always passed to model, generated if not supplied)

Transitive dependency note:
    omniclaude.hooks.schemas transitively imports tiktoken (via injection_limits
    or omnibase_core/omnibase_infra). When tiktoken is not installed the lazy
    ``from omniclaude.hooks.schemas import ...`` inside emit_agent_status()
    raises ModuleNotFoundError, which the fail-open handler catches and returns
    False -- causing all happy-path tests to fail.

    To decouple these tests from tiktoken availability we attempt to import the
    real schemas first.  If that fails we install lightweight stand-ins into
    ``sys.modules`` so the lazy import succeeds.  The stand-ins faithfully
    replicate EnumAgentState (StrEnum) and ModelAgentStatusPayload (frozen
    Pydantic BaseModel with identical field constraints) so every test exercises
    the same validation logic as production.
"""

from __future__ import annotations

import builtins
import os
import sys
from datetime import datetime
from enum import StrEnum
from typing import Literal
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from pydantic import BaseModel, ConfigDict, Field

# All tests in this module are unit tests
pytestmark = pytest.mark.unit


# =============================================================================
# Tiktoken-safe schema mocking
# =============================================================================
#
# Try to import the real schemas.  If that succeeds the tests run against the
# production code with zero mocking.  If the import fails (typically because
# tiktoken is absent) we build minimal stand-ins and inject them into
# sys.modules so the lazy import inside agent_status_emitter succeeds.

_SCHEMAS_MOCK_INSTALLED = False

try:
    from omniclaude.hooks.schemas import (  # noqa: F401
        EnumAgentState,
        ModelAgentStatusPayload,
    )

    # Real schemas available -- nothing to do.
except Exception:
    # -----------------------------------------------------------------
    # Stand-in EnumAgentState (StrEnum, identical values)
    # -----------------------------------------------------------------
    class EnumAgentState(StrEnum):  # type: ignore[no-redef]
        IDLE = "idle"
        WORKING = "working"
        BLOCKED = "blocked"
        AWAITING_INPUT = "awaiting_input"
        FINISHED = "finished"
        ERROR = "error"

    # -----------------------------------------------------------------
    # Stand-in ModelAgentStatusPayload (frozen Pydantic model, same
    # field names/types/constraints as the real schema)
    # -----------------------------------------------------------------
    class ModelAgentStatusPayload(BaseModel):  # type: ignore[no-redef]
        model_config = ConfigDict(frozen=True, extra="forbid")

        correlation_id: UUID = Field(...)
        agent_name: str = Field(..., min_length=1)
        session_id: str = Field(..., min_length=1)
        agent_instance_id: str | None = Field(default=None)
        state: EnumAgentState = Field(...)
        schema_version: Literal[1] = Field(default=1)
        message: str = Field(..., min_length=1, max_length=500)
        progress: float | None = Field(default=None, ge=0.0, le=1.0)
        current_phase: str | None = Field(default=None)
        current_task: str | None = Field(default=None)
        blocking_reason: str | None = Field(default=None)
        emitted_at: datetime = Field(...)
        metadata: dict[str, str] = Field(default_factory=dict)

    # Inject stand-ins into sys.modules so the lazy import inside
    # agent_status_emitter.emit_agent_status() finds them.
    import types as _types

    _schemas_mod = sys.modules.get("omniclaude.hooks.schemas")
    if _schemas_mod is None:
        _schemas_mod = _types.ModuleType("omniclaude.hooks.schemas")
        # Ensure parent packages exist in sys.modules
        for _parent in ("omniclaude", "omniclaude.hooks"):
            if _parent not in sys.modules:
                sys.modules[_parent] = _types.ModuleType(_parent)
        sys.modules["omniclaude.hooks.schemas"] = _schemas_mod

    _schemas_mod.EnumAgentState = EnumAgentState  # type: ignore[attr-defined]
    _schemas_mod.ModelAgentStatusPayload = ModelAgentStatusPayload  # type: ignore[attr-defined]
    _SCHEMAS_MOCK_INSTALLED = True


# =============================================================================
# Module Import Tests
# =============================================================================


class TestModuleImport:
    """Tests for module imports and constants."""

    def test_module_imports_successfully(self) -> None:
        """Verify module can be imported without errors."""
        from plugins.onex.hooks.lib import agent_status_emitter

        assert agent_status_emitter is not None

    def test_emit_agent_status_is_callable(self) -> None:
        """Verify emit_agent_status function exists and is callable."""
        from plugins.onex.hooks.lib.agent_status_emitter import emit_agent_status

        assert callable(emit_agent_status)

    def test_public_api_exports(self) -> None:
        """Verify __all__ exports expected public API."""
        from plugins.onex.hooks.lib.agent_status_emitter import __all__

        expected_exports = {"emit_agent_status"}
        assert set(__all__) == expected_exports


# =============================================================================
# Valid State Emission Tests (Happy Path)
# =============================================================================


class TestValidStateEmission:
    """Tests for successful agent status emission."""

    def test_emit_working_state_returns_true(self) -> None:
        """Emitting a valid 'working' state returns True when daemon accepts."""
        from plugins.onex.hooks.lib.agent_status_emitter import emit_agent_status

        with patch(
            "plugins.onex.hooks.lib.emit_client_wrapper.emit_event",
            return_value=True,
        ) as mock_emit:
            result = emit_agent_status(
                "working",
                "Processing user request",
                agent_name="test-agent",
                session_id="session-123",
            )

        assert result is True
        mock_emit.assert_called_once()
        # Verify event type is "agent.status"
        call_args = mock_emit.call_args
        assert call_args[0][0] == "agent.status"

    def test_emit_all_valid_states(self) -> None:
        """All EnumAgentState values are accepted."""
        from plugins.onex.hooks.lib.agent_status_emitter import emit_agent_status

        valid_states = [
            "idle",
            "working",
            "blocked",
            "awaiting_input",
            "finished",
            "error",
        ]

        for state in valid_states:
            with patch(
                "plugins.onex.hooks.lib.emit_client_wrapper.emit_event",
                return_value=True,
            ):
                result = emit_agent_status(
                    state,
                    f"Agent is {state}",
                    agent_name="test-agent",
                    session_id="session-123",
                )
            assert result is True, f"State '{state}' should be accepted"

    def test_payload_structure_contains_required_fields(self) -> None:
        """Emitted payload dict contains all required fields."""
        from plugins.onex.hooks.lib.agent_status_emitter import emit_agent_status

        captured_payload = {}

        def capture_emit(event_type: str, payload: dict) -> bool:
            captured_payload.update(payload)
            return True

        with patch(
            "plugins.onex.hooks.lib.emit_client_wrapper.emit_event",
            side_effect=capture_emit,
        ):
            emit_agent_status(
                "working",
                "Doing work",
                agent_name="my-agent",
                session_id="sess-456",
            )

        # Verify required fields in serialized payload
        assert captured_payload["agent_name"] == "my-agent"
        assert captured_payload["session_id"] == "sess-456"
        assert captured_payload["state"] == "working"
        assert captured_payload["message"] == "Doing work"
        assert captured_payload["schema_version"] == 1
        assert "emitted_at" in captured_payload
        assert "correlation_id" in captured_payload

    def test_emit_returns_false_when_daemon_rejects(self) -> None:
        """Returns False when emit_event returns False."""
        from plugins.onex.hooks.lib.agent_status_emitter import emit_agent_status

        with patch(
            "plugins.onex.hooks.lib.emit_client_wrapper.emit_event",
            return_value=False,
        ):
            result = emit_agent_status(
                "idle",
                "Agent idle",
                agent_name="test-agent",
                session_id="session-123",
            )

        assert result is False

    def test_optional_fields_included_when_provided(self) -> None:
        """Optional fields (progress, current_phase, etc.) are included in payload."""
        from plugins.onex.hooks.lib.agent_status_emitter import emit_agent_status

        captured_payload = {}

        def capture_emit(event_type: str, payload: dict) -> bool:
            captured_payload.update(payload)
            return True

        with patch(
            "plugins.onex.hooks.lib.emit_client_wrapper.emit_event",
            side_effect=capture_emit,
        ):
            emit_agent_status(
                "working",
                "Processing step 3 of 5",
                agent_name="my-agent",
                session_id="sess-789",
                agent_instance_id="instance-001",
                progress=0.6,
                current_phase="implementation",
                current_task="Writing tests",
                blocking_reason=None,
            )

        assert captured_payload["agent_instance_id"] == "instance-001"
        assert captured_payload["progress"] == 0.6
        assert captured_payload["current_phase"] == "implementation"
        assert captured_payload["current_task"] == "Writing tests"


# =============================================================================
# Invalid State Rejection Tests
# =============================================================================


class TestInvalidStateRejection:
    """Tests for rejection of invalid state strings."""

    def test_invalid_state_returns_false(self) -> None:
        """An invalid state string returns False without emitting."""
        from plugins.onex.hooks.lib.agent_status_emitter import emit_agent_status

        with patch(
            "plugins.onex.hooks.lib.emit_client_wrapper.emit_event",
        ) as mock_emit:
            result = emit_agent_status(
                "nonexistent_state",
                "This should fail",
                agent_name="test-agent",
                session_id="session-123",
            )

        assert result is False
        mock_emit.assert_not_called()

    def test_empty_state_returns_false(self) -> None:
        """An empty string state returns False."""
        from plugins.onex.hooks.lib.agent_status_emitter import emit_agent_status

        with patch(
            "plugins.onex.hooks.lib.emit_client_wrapper.emit_event",
        ) as mock_emit:
            result = emit_agent_status(
                "",
                "Empty state",
                agent_name="test-agent",
                session_id="session-123",
            )

        assert result is False
        mock_emit.assert_not_called()

    def test_case_sensitive_state_rejection(self) -> None:
        """State matching is case-sensitive (uppercase 'WORKING' is invalid)."""
        from plugins.onex.hooks.lib.agent_status_emitter import emit_agent_status

        with patch(
            "plugins.onex.hooks.lib.emit_client_wrapper.emit_event",
        ) as mock_emit:
            result = emit_agent_status(
                "WORKING",
                "Wrong case",
                agent_name="test-agent",
                session_id="session-123",
            )

        assert result is False
        mock_emit.assert_not_called()

    def test_invalid_state_logs_error(self) -> None:
        """Invalid state logs an error with valid states listed."""
        from plugins.onex.hooks.lib import agent_status_emitter

        with patch.object(agent_status_emitter.logger, "error") as mock_log:
            agent_status_emitter.emit_agent_status(
                "bogus",
                "Bad state",
                agent_name="test-agent",
                session_id="session-123",
            )

        mock_log.assert_called_once()
        log_message = mock_log.call_args[0][0]
        assert "Invalid agent state" in log_message


# =============================================================================
# Environment Variable Fallback Tests
# =============================================================================


class TestEnvironmentVariableFallback:
    """Tests for environment variable fallback when agent_name/session_id not passed."""

    def test_agent_name_falls_back_to_env_var(self) -> None:
        """When agent_name is None, falls back to AGENT_NAME env var."""
        from plugins.onex.hooks.lib.agent_status_emitter import emit_agent_status

        captured_payload = {}

        def capture_emit(event_type: str, payload: dict) -> bool:
            captured_payload.update(payload)
            return True

        with (
            patch.dict(
                os.environ, {"AGENT_NAME": "env-agent", "SESSION_ID": "env-sess"}
            ),
            patch(
                "plugins.onex.hooks.lib.emit_client_wrapper.emit_event",
                side_effect=capture_emit,
            ),
        ):
            result = emit_agent_status("idle", "Idle from env")

        assert result is True
        assert captured_payload["agent_name"] == "env-agent"
        assert captured_payload["session_id"] == "env-sess"

    def test_session_id_falls_back_to_env_var(self) -> None:
        """When session_id is None, falls back to SESSION_ID env var."""
        from plugins.onex.hooks.lib.agent_status_emitter import emit_agent_status

        captured_payload = {}

        def capture_emit(event_type: str, payload: dict) -> bool:
            captured_payload.update(payload)
            return True

        with (
            patch.dict(os.environ, {"SESSION_ID": "from-env-session"}),
            patch(
                "plugins.onex.hooks.lib.emit_client_wrapper.emit_event",
                side_effect=capture_emit,
            ),
        ):
            result = emit_agent_status(
                "working",
                "Working with env session",
                agent_name="explicit-agent",
            )

        assert result is True
        assert captured_payload["session_id"] == "from-env-session"

    def test_defaults_to_unknown_when_no_env_var(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When no env vars set and no args passed, defaults to 'unknown'."""
        from plugins.onex.hooks.lib.agent_status_emitter import emit_agent_status

        captured_payload = {}

        def capture_emit(event_type: str, payload: dict) -> bool:
            captured_payload.update(payload)
            return True

        # Use monkeypatch to safely remove env vars; automatically restored after test
        monkeypatch.delenv("AGENT_NAME", raising=False)
        monkeypatch.delenv("SESSION_ID", raising=False)

        with patch(
            "plugins.onex.hooks.lib.emit_client_wrapper.emit_event",
            side_effect=capture_emit,
        ):
            result = emit_agent_status("idle", "No context")

        assert result is True
        assert captured_payload["agent_name"] == "unknown"
        assert captured_payload["session_id"] == "unknown"

    def test_explicit_args_override_env_vars(self) -> None:
        """Explicit agent_name/session_id args take precedence over env vars."""
        from plugins.onex.hooks.lib.agent_status_emitter import emit_agent_status

        captured_payload = {}

        def capture_emit(event_type: str, payload: dict) -> bool:
            captured_payload.update(payload)
            return True

        with (
            patch.dict(
                os.environ,
                {"AGENT_NAME": "env-agent", "SESSION_ID": "env-session"},
            ),
            patch(
                "plugins.onex.hooks.lib.emit_client_wrapper.emit_event",
                side_effect=capture_emit,
            ),
        ):
            emit_agent_status(
                "working",
                "Explicit wins",
                agent_name="explicit-agent",
                session_id="explicit-session",
            )

        assert captured_payload["agent_name"] == "explicit-agent"
        assert captured_payload["session_id"] == "explicit-session"


# =============================================================================
# Pydantic Validation Error Tests
# =============================================================================


class TestPydanticValidationErrors:
    """Tests for Pydantic validation catching malformed input."""

    def test_empty_message_returns_false(self) -> None:
        """Empty message string fails Pydantic min_length=1 validation."""
        from plugins.onex.hooks.lib.agent_status_emitter import emit_agent_status

        result = emit_agent_status(
            "working",
            "",
            agent_name="test-agent",
            session_id="session-123",
        )

        # Pydantic ValidationError is caught by the outer try/except
        assert result is False

    def test_message_exceeding_max_length_returns_false(self) -> None:
        """Message exceeding 500 chars fails Pydantic max_length validation."""
        from plugins.onex.hooks.lib.agent_status_emitter import emit_agent_status

        long_message = "x" * 501

        result = emit_agent_status(
            "working",
            long_message,
            agent_name="test-agent",
            session_id="session-123",
        )

        assert result is False

    def test_progress_out_of_range_returns_false(self) -> None:
        """Progress value > 1.0 fails Pydantic le=1.0 validation."""
        from plugins.onex.hooks.lib.agent_status_emitter import emit_agent_status

        result = emit_agent_status(
            "working",
            "In progress",
            agent_name="test-agent",
            session_id="session-123",
            progress=1.5,
        )

        assert result is False

    def test_negative_progress_returns_false(self) -> None:
        """Progress value < 0.0 fails Pydantic ge=0.0 validation."""
        from plugins.onex.hooks.lib.agent_status_emitter import emit_agent_status

        result = emit_agent_status(
            "working",
            "Negative progress",
            agent_name="test-agent",
            session_id="session-123",
            progress=-0.1,
        )

        assert result is False


# =============================================================================
# Fail-Open Exception Handling Tests
# =============================================================================


class TestFailOpenExceptionHandling:
    """Tests that the emitter never raises, always returns False on error."""

    def test_emit_event_exception_returns_false(self) -> None:
        """When emit_event raises, emit_agent_status returns False (not raise)."""
        from plugins.onex.hooks.lib.agent_status_emitter import emit_agent_status

        with patch(
            "plugins.onex.hooks.lib.emit_client_wrapper.emit_event",
            side_effect=ConnectionRefusedError("Daemon not running"),
        ):
            result = emit_agent_status(
                "working",
                "Should not crash",
                agent_name="test-agent",
                session_id="session-123",
            )

        assert result is False

    def test_runtime_error_in_emit_returns_false(self) -> None:
        """RuntimeError from emit_event is swallowed, returns False."""
        from plugins.onex.hooks.lib.agent_status_emitter import emit_agent_status

        with patch(
            "plugins.onex.hooks.lib.emit_client_wrapper.emit_event",
            side_effect=RuntimeError("Unexpected runtime failure"),
        ):
            result = emit_agent_status(
                "idle",
                "Runtime error test",
                agent_name="test-agent",
                session_id="session-123",
            )

        assert result is False

    def test_import_error_returns_false(self) -> None:
        """If schema import fails, returns False without raising."""
        from plugins.onex.hooks.lib.agent_status_emitter import emit_agent_status

        _real_import = builtins.__import__

        def _fake_import(name: str, *args, **kwargs):  # type: ignore[no-untyped-def]
            if name == "omniclaude.hooks.schemas":
                raise ImportError("Simulated schema import failure")
            return _real_import(name, *args, **kwargs)

        with patch.object(builtins, "__import__", side_effect=_fake_import):
            # The lazy `from omniclaude.hooks.schemas import ...` inside the
            # function will trigger our fake import, which raises ImportError.
            # The outer try/except catches it and returns False.
            result = emit_agent_status(
                "working",
                "Import error test",
                agent_name="test-agent",
                session_id="session-123",
            )

        assert result is False

    def test_exception_logs_warning(self) -> None:
        """Exceptions in emit path log a warning with structured context."""
        from plugins.onex.hooks.lib import agent_status_emitter

        with (
            patch(
                "plugins.onex.hooks.lib.emit_client_wrapper.emit_event",
                side_effect=OSError("Socket broken"),
            ),
            patch.object(agent_status_emitter.logger, "warning") as mock_warn,
        ):
            agent_status_emitter.emit_agent_status(
                "working",
                "Will fail",
                agent_name="test-agent",
                session_id="session-123",
            )

        mock_warn.assert_called_once()
        log_msg = mock_warn.call_args[0][0]
        assert "Failed to emit agent status" in log_msg

    def test_never_raises_regardless_of_input(self) -> None:
        """emit_agent_status must never raise, even with bizarre input."""
        from plugins.onex.hooks.lib.agent_status_emitter import emit_agent_status

        # None state (TypeError in EnumAgentState())
        try:
            result = emit_agent_status(
                None,  # type: ignore[arg-type]
                "Bad input",
                agent_name="test-agent",
                session_id="session-123",
            )
            assert isinstance(result, bool)
        except Exception:
            pytest.fail("emit_agent_status raised an exception with None state")


# =============================================================================
# Metadata Passthrough Tests
# =============================================================================


class TestMetadataPassthrough:
    """Tests that extra metadata dict is included in the emitted payload."""

    def test_metadata_included_in_payload(self) -> None:
        """Metadata dict is passed through to the serialized payload."""
        from plugins.onex.hooks.lib.agent_status_emitter import emit_agent_status

        captured_payload = {}

        def capture_emit(event_type: str, payload: dict) -> bool:
            captured_payload.update(payload)
            return True

        with patch(
            "plugins.onex.hooks.lib.emit_client_wrapper.emit_event",
            side_effect=capture_emit,
        ):
            emit_agent_status(
                "working",
                "With metadata",
                agent_name="test-agent",
                session_id="session-123",
                metadata={"request_id": "req-001", "source": "unit-test"},
            )

        assert captured_payload["metadata"] == {
            "request_id": "req-001",
            "source": "unit-test",
        }

    def test_empty_metadata_defaults_to_empty_dict(self) -> None:
        """When metadata is None, it defaults to an empty dict."""
        from plugins.onex.hooks.lib.agent_status_emitter import emit_agent_status

        captured_payload = {}

        def capture_emit(event_type: str, payload: dict) -> bool:
            captured_payload.update(payload)
            return True

        with patch(
            "plugins.onex.hooks.lib.emit_client_wrapper.emit_event",
            side_effect=capture_emit,
        ):
            emit_agent_status(
                "idle",
                "No metadata",
                agent_name="test-agent",
                session_id="session-123",
                metadata=None,
            )

        assert captured_payload["metadata"] == {}

    def test_explicit_empty_metadata_is_empty_dict(self) -> None:
        """Passing an explicit empty dict results in empty metadata."""
        from plugins.onex.hooks.lib.agent_status_emitter import emit_agent_status

        captured_payload = {}

        def capture_emit(event_type: str, payload: dict) -> bool:
            captured_payload.update(payload)
            return True

        with patch(
            "plugins.onex.hooks.lib.emit_client_wrapper.emit_event",
            side_effect=capture_emit,
        ):
            emit_agent_status(
                "idle",
                "Explicit empty",
                agent_name="test-agent",
                session_id="session-123",
                metadata={},
            )

        assert captured_payload["metadata"] == {}


# =============================================================================
# Correlation ID Tests
# =============================================================================


class TestCorrelationId:
    """Tests for correlation_id generation and passthrough."""

    def test_explicit_correlation_id_is_passed_through(self) -> None:
        """When caller provides correlation_id, it appears in the payload."""
        from plugins.onex.hooks.lib.agent_status_emitter import emit_agent_status

        captured_payload = {}
        explicit_id = uuid4()

        def capture_emit(event_type: str, payload: dict) -> bool:
            captured_payload.update(payload)
            return True

        with patch(
            "plugins.onex.hooks.lib.emit_client_wrapper.emit_event",
            side_effect=capture_emit,
        ):
            emit_agent_status(
                "working",
                "With explicit correlation",
                agent_name="test-agent",
                session_id="session-123",
                correlation_id=explicit_id,
            )

        assert captured_payload["correlation_id"] == str(explicit_id)

    def test_correlation_id_auto_generated_when_not_provided(self) -> None:
        """When correlation_id is None, the emitter generates a valid UUID."""
        from plugins.onex.hooks.lib.agent_status_emitter import emit_agent_status

        captured_payload = {}

        def capture_emit(event_type: str, payload: dict) -> bool:
            captured_payload.update(payload)
            return True

        with patch(
            "plugins.onex.hooks.lib.emit_client_wrapper.emit_event",
            side_effect=capture_emit,
        ):
            emit_agent_status(
                "idle",
                "Auto correlation",
                agent_name="test-agent",
                session_id="session-123",
            )

        # Should be a valid UUID string
        correlation_id = captured_payload["correlation_id"]
        assert correlation_id is not None
        UUID(correlation_id)  # Raises ValueError if not valid UUID

    def test_two_calls_without_correlation_id_get_different_ids(self) -> None:
        """Each call without explicit correlation_id gets a unique UUID."""
        from plugins.onex.hooks.lib.agent_status_emitter import emit_agent_status

        payloads: list[dict] = []

        def capture_emit(event_type: str, payload: dict) -> bool:
            payloads.append(dict(payload))
            return True

        with patch(
            "plugins.onex.hooks.lib.emit_client_wrapper.emit_event",
            side_effect=capture_emit,
        ):
            emit_agent_status(
                "idle", "First call", agent_name="agent", session_id="sess"
            )
            emit_agent_status(
                "working", "Second call", agent_name="agent", session_id="sess"
            )

        assert len(payloads) == 2
        assert payloads[0]["correlation_id"] != payloads[1]["correlation_id"]
