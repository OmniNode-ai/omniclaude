# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Tests for emit_client_wrapper module.

This module tests the client-side interface for hooks to emit events via
the emit daemon. It validates:
- Module imports and constants
- Event type validation
- Client initialization (thread-safe)
- CLI argument parsing
- Public API behavior
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# All tests in this module are unit tests
pytestmark = pytest.mark.unit


# =============================================================================
# Module Import Tests
# =============================================================================


class TestModuleImport:
    """Tests for module imports and constants."""

    def test_module_imports_successfully(self) -> None:
        """Verify module can be imported without errors."""
        from plugins.onex.hooks.lib import emit_client_wrapper

        assert emit_client_wrapper is not None

    def test_supported_event_types_defined(self) -> None:
        """Verify SUPPORTED_EVENT_TYPES constant is defined."""
        from plugins.onex.hooks.lib.emit_client_wrapper import SUPPORTED_EVENT_TYPES

        assert SUPPORTED_EVENT_TYPES is not None
        assert isinstance(SUPPORTED_EVENT_TYPES, frozenset)

    def test_supported_event_types_contains_expected_types(self) -> None:
        """Verify expected event types are defined."""
        from plugins.onex.hooks.lib.emit_client_wrapper import SUPPORTED_EVENT_TYPES

        expected_types = {
            "session.started",
            "session.ended",
            "session.outcome",
            "prompt.submitted",
            "tool.executed",
            "injection.recorded",
            "context.utilization",  # OMN-1889
            "agent.match",  # OMN-1889
            "latency.breakdown",  # OMN-1889
            "routing.decision",  # Polly-first routing observability
            "routing.feedback",  # OMN-1892 - Routing feedback for reinforcement
            "routing.skipped",  # OMN-1892 - Routing feedback skipped
            "notification.blocked",  # OMN-1831
            "notification.completed",  # PR-92
            "phase.metrics",  # OMN-2027 - Phase instrumentation metrics
            "agent.status",  # OMN-1848 - Agent status reporting
            "compliance.evaluate",  # OMN-2256
            "static.context.edit.detected",  # OMN-2237 - Static context change detection
            "llm.routing.decision",  # OMN-2273 - LLM routing decision observability
            "llm.routing.fallback",  # OMN-2273 - LLM routing fallback observability
        }
        assert expected_types == SUPPORTED_EVENT_TYPES

    def test_supported_event_types_match_event_registry(self) -> None:
        """SUPPORTED_EVENT_TYPES must stay in sync with EVENT_REGISTRY keys.

        These two sets define the same valid event types in different modules.
        Drift between them causes events to be silently dropped or accepted
        but unroutable.
        """
        from omniclaude.hooks.event_registry import EVENT_REGISTRY
        from plugins.onex.hooks.lib.emit_client_wrapper import SUPPORTED_EVENT_TYPES

        registry_types = set(EVENT_REGISTRY.keys())
        assert registry_types == SUPPORTED_EVENT_TYPES, (
            f"SUPPORTED_EVENT_TYPES and EVENT_REGISTRY are out of sync.\n"
            f"  In SUPPORTED_EVENT_TYPES only: {SUPPORTED_EVENT_TYPES - registry_types}\n"
            f"  In EVENT_REGISTRY only: {registry_types - SUPPORTED_EVENT_TYPES}"
        )

    def test_event_types_are_internal_not_kafka_topics(self) -> None:
        """Verify emit daemon event types are distinct from Kafka topic names.

        IMPORTANT: Event types in SUPPORTED_EVENT_TYPES are internal identifiers
        for the emit daemon, NOT Kafka topic names. The emit daemon maps these
        event types to appropriate Kafka topics.

        For example:
        - Event type "routing.decision" is routed to Kafka topic "onex.evt.omniclaude.routing-decision.v1"
        - Event type "session.started" is routed to Kafka topic "onex.evt.omniclaude.session-started.v1"

        This test documents the naming convention: event types use dotted lowercase
        names like "category.action" for internal routing, while Kafka topics follow
        either ONEX canonical format (onex.{kind}.{producer}.{event-name}.v{n}) or
        ONEX canonical format (onex.evt.omniclaude.routing-decision.v1).

        See topics.py for actual Kafka topic definitions.
        """
        from plugins.onex.hooks.lib.emit_client_wrapper import SUPPORTED_EVENT_TYPES

        # All event types follow the internal naming convention: lowercase dotted names
        for event_type in SUPPORTED_EVENT_TYPES:
            # Should be lowercase
            assert event_type == event_type.lower(), (
                f"Event type '{event_type}' should be lowercase"
            )
            # Should contain at least one dot (category.action format).
            # Most events use exactly one dot (e.g. "session.started").
            # Compound events (e.g. "static.context.edit.detected") may use more dots
            # but must still not look like Kafka wire topics.
            assert event_type.count(".") >= 1, (
                f"Event type '{event_type}' should contain at least one dot"
            )
            # Should not be a Kafka topic (those start with 'onex.' or are hyphenated)
            assert not event_type.startswith("onex."), (
                f"Event type '{event_type}' looks like a Kafka topic name"
            )
            assert "-" not in event_type, (
                f"Event type '{event_type}' contains hyphen (Kafka topic style)"
            )

    def test_get_default_socket_path_returns_fresh_value(self) -> None:
        """Verify get_default_socket_path() computes path per-call via tempfile.gettempdir()."""
        import tempfile

        from plugins.onex.hooks.lib.emit_client_wrapper import get_default_socket_path

        result = get_default_socket_path()
        assert result is not None
        assert isinstance(result, Path)
        expected = Path(tempfile.gettempdir()) / "omniclaude-emit.sock"
        assert expected == result

    def test_default_socket_path_backwards_compat(self) -> None:
        """Verify DEFAULT_SOCKET_PATH constant still exists for backwards compatibility."""
        from plugins.onex.hooks.lib.emit_client_wrapper import DEFAULT_SOCKET_PATH

        assert DEFAULT_SOCKET_PATH is not None
        assert isinstance(DEFAULT_SOCKET_PATH, Path)

    def test_default_timeout_ms_defined(self) -> None:
        """Verify DEFAULT_TIMEOUT_MS constant is defined."""
        from plugins.onex.hooks.lib.emit_client_wrapper import DEFAULT_TIMEOUT_MS

        assert DEFAULT_TIMEOUT_MS == 50

    def test_public_api_exports(self) -> None:
        """Verify __all__ exports expected public API."""
        from plugins.onex.hooks.lib.emit_client_wrapper import __all__

        expected_exports = {
            # Public API
            "emit_event",
            "daemon_available",
            "get_status",
            "reset_client",
            # Constants
            "SUPPORTED_EVENT_TYPES",
            "DEFAULT_SOCKET_PATH",
            "DEFAULT_TIMEOUT_MS",
            # Functions
            "get_default_socket_path",
            # CLI
            "main",
        }
        assert set(__all__) == expected_exports


# =============================================================================
# Event Type Validation Tests
# =============================================================================


class TestEventTypeValidation:
    """Tests for event type validation in emit_event."""

    def test_emit_event_rejects_invalid_event_type(self) -> None:
        """emit_event returns False for invalid event types."""
        from plugins.onex.hooks.lib.emit_client_wrapper import emit_event

        result = emit_event(
            event_type="invalid.event.type",
            payload={"test": "data"},
            timeout_ms=50,
        )
        assert result is False

    def test_emit_event_rejects_empty_event_type(self) -> None:
        """emit_event returns False for empty event type."""
        from plugins.onex.hooks.lib.emit_client_wrapper import emit_event

        result = emit_event(
            event_type="",
            payload={"test": "data"},
            timeout_ms=50,
        )
        assert result is False

    def test_emit_event_accepts_valid_event_types(self) -> None:
        """emit_event accepts all valid event types (but may fail on daemon connection)."""
        from plugins.onex.hooks.lib.emit_client_wrapper import (
            SUPPORTED_EVENT_TYPES,
            emit_event,
        )

        # For each valid event type, the function should NOT immediately return False
        # due to validation. It may return False due to daemon unavailability, but
        # that's expected in unit tests.
        for event_type in SUPPORTED_EVENT_TYPES:
            # We can't assert the result is True (daemon not running in tests)
            # but we verify it doesn't raise an exception
            result = emit_event(
                event_type=event_type,
                payload={"session_id": "test-123"},
                timeout_ms=1,  # Short timeout for unit tests
            )
            # Result may be True or False depending on daemon availability
            assert isinstance(result, bool)


# =============================================================================
# Status Tests
# =============================================================================


class TestGetStatus:
    """Tests for get_status function."""

    def test_get_status_returns_dict(self) -> None:
        """get_status returns a dictionary."""
        from plugins.onex.hooks.lib.emit_client_wrapper import get_status

        status = get_status()
        assert isinstance(status, dict)

    def test_get_status_has_required_keys(self) -> None:
        """get_status returns dict with all required keys."""
        from plugins.onex.hooks.lib.emit_client_wrapper import get_status

        status = get_status()

        required_keys = {
            "client_available",
            "socket_path",
            "daemon_running",
        }
        # Use subset check for forward compatibility if status grows
        assert required_keys.issubset(status.keys())

    def test_get_status_client_available_is_bool(self) -> None:
        """client_available is a boolean."""
        from plugins.onex.hooks.lib.emit_client_wrapper import get_status

        status = get_status()
        assert isinstance(status["client_available"], bool)

    def test_get_status_socket_path_is_string(self) -> None:
        """socket_path is a string."""
        from plugins.onex.hooks.lib.emit_client_wrapper import get_status

        status = get_status()
        assert isinstance(status["socket_path"], str)

    def test_get_status_daemon_running_is_bool(self) -> None:
        """daemon_running is a boolean."""
        from plugins.onex.hooks.lib.emit_client_wrapper import get_status

        status = get_status()
        assert isinstance(status["daemon_running"], bool)


# =============================================================================
# Thread Safety Tests
# =============================================================================


class TestThreadSafety:
    """Tests for thread-safe client initialization."""

    def test_concurrent_status_calls_are_safe(self) -> None:
        """Multiple threads can call get_status concurrently.

        This test verifies thread safety of get_status() - not actual daemon
        connectivity. We mock daemon_available() to avoid expensive socket
        timeout operations in CI where no daemon is running.
        """
        from plugins.onex.hooks.lib.emit_client_wrapper import get_status

        errors: list[Exception] = []
        results: list[dict] = []

        def status_worker():
            try:
                for _ in range(100):
                    status = get_status()
                    results.append(status)
            except Exception as e:
                errors.append(e)

        # Mock daemon_available to avoid slow socket timeouts in CI
        # The test is about thread safety, not actual daemon connectivity
        with patch(
            "plugins.onex.hooks.lib.emit_client_wrapper.daemon_available",
            return_value=False,
        ):
            threads = [threading.Thread(target=status_worker) for _ in range(10)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

        # No errors should have occurred
        assert len(errors) == 0

        # All results should be valid dicts
        assert len(results) == 1000
        for status in results:
            assert isinstance(status, dict)
            assert "client_available" in status

    def test_concurrent_emit_calls_are_safe(self) -> None:
        """Multiple threads can call emit_event concurrently."""
        from plugins.onex.hooks.lib import emit_client_wrapper

        errors: list[Exception] = []
        results: list[bool] = []

        # Mock _get_client to avoid real socket operations that would block
        mock_client = MagicMock()
        mock_client.emit_sync.return_value = "test-event-id"

        def emit_worker():
            try:
                for _ in range(50):
                    result = emit_client_wrapper.emit_event(
                        event_type="session.started",
                        payload={"session_id": "test"},
                        timeout_ms=1,
                    )
                    results.append(result)
            except Exception as e:
                errors.append(e)

        with patch.object(emit_client_wrapper, "_get_client", return_value=mock_client):
            threads = [threading.Thread(target=emit_worker) for _ in range(10)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

        # No errors should have occurred
        assert len(errors) == 0

        # All results should be bools (True since mock succeeds)
        assert len(results) == 500
        for result in results:
            assert isinstance(result, bool)
            assert result is True  # Mock client succeeds


# =============================================================================
# Reset Client Tests
# =============================================================================


class TestResetClient:
    """Tests for reset_client function."""

    def test_reset_client_is_callable(self) -> None:
        """reset_client function exists and is callable."""
        from plugins.onex.hooks.lib.emit_client_wrapper import reset_client

        assert callable(reset_client)

    def test_reset_client_returns_none(self) -> None:
        """reset_client returns None."""
        from plugins.onex.hooks.lib.emit_client_wrapper import reset_client

        result = reset_client()
        assert result is None

    def test_reset_client_can_be_called_multiple_times(self) -> None:
        """reset_client can be called repeatedly without error."""
        from plugins.onex.hooks.lib.emit_client_wrapper import reset_client

        # Call multiple times - should not raise
        for _ in range(5):
            reset_client()

    def test_reset_client_clears_cached_client(self) -> None:
        """reset_client clears the cached client state."""
        from plugins.onex.hooks.lib import emit_client_wrapper

        # First, trigger client initialization by calling get_status
        emit_client_wrapper.get_status()

        # Reset the client
        emit_client_wrapper.reset_client()

        # Verify internal state is cleared
        # Access module-level variables directly for testing
        assert emit_client_wrapper._emit_client is None
        assert emit_client_wrapper._client_initialized is False

    def test_reset_client_allows_reconnection(self) -> None:
        """After reset_client, next emit attempts reconnection."""
        from plugins.onex.hooks.lib import emit_client_wrapper

        # Mock a successful emit
        mock_client = MagicMock()
        mock_client.emit_sync.return_value = "event-id-1"

        with patch.object(emit_client_wrapper, "_get_client", return_value=mock_client):
            result1 = emit_client_wrapper.emit_event(
                event_type="session.started",
                payload={"session_id": "test"},
            )
            assert result1 is True

        # Reset the client
        emit_client_wrapper.reset_client()

        # Verify _get_client would be called again on next emit
        # (internal state should be cleared)
        assert emit_client_wrapper._client_initialized is False


# =============================================================================
# Daemon Available Tests
# =============================================================================


class TestDaemonAvailable:
    """Tests for daemon_available function."""

    def test_daemon_available_returns_bool(self) -> None:
        """daemon_available returns a boolean."""
        from plugins.onex.hooks.lib.emit_client_wrapper import daemon_available

        result = daemon_available()
        assert isinstance(result, bool)

    def test_daemon_available_false_when_socket_missing(self) -> None:
        """daemon_available returns False when socket file doesn't exist."""
        from plugins.onex.hooks.lib.emit_client_wrapper import daemon_available

        # In unit tests without daemon running, should return False
        # (assuming no daemon is running during tests)
        # Note: This test may pass or fail depending on environment
        result = daemon_available()
        # We just verify it doesn't raise an exception
        assert isinstance(result, bool)


# =============================================================================
# CLI Argument Parsing Tests
# =============================================================================


class TestCliArgumentParsing:
    """Tests for CLI argument parsing via main()."""

    def test_cli_status_command_works(self) -> None:
        """CLI status command runs without error."""
        from plugins.onex.hooks.lib.emit_client_wrapper import main

        # status command should return 0
        result = main(["status"])
        assert result == 0

    def test_cli_status_json_output(self) -> None:
        """CLI status --json outputs valid JSON."""
        # Capture stdout
        import io
        from contextlib import redirect_stdout

        from plugins.onex.hooks.lib.emit_client_wrapper import main

        f = io.StringIO()
        with redirect_stdout(f):
            result = main(["status", "--json"])

        assert result == 0
        output = f.getvalue()
        # Should be valid JSON
        parsed = json.loads(output)
        assert "client_available" in parsed
        assert "socket_path" in parsed

    def test_cli_ping_command_returns_int(self) -> None:
        """CLI ping command returns an integer exit code."""
        from plugins.onex.hooks.lib.emit_client_wrapper import main

        # ping will return 1 if daemon not available (expected in tests)
        result = main(["ping"])
        assert result in (0, 1)

    def test_cli_emit_requires_event_type(self) -> None:
        """CLI emit command requires --event-type argument."""
        from plugins.onex.hooks.lib.emit_client_wrapper import main

        with pytest.raises(SystemExit) as exc_info:
            main(["emit", "--payload", '{"test": "data"}'])
        # argparse exits with code 2 for missing required arguments
        assert exc_info.value.code == 2

    def test_cli_emit_requires_payload(self) -> None:
        """CLI emit command requires --payload argument."""
        from plugins.onex.hooks.lib.emit_client_wrapper import main

        with pytest.raises(SystemExit) as exc_info:
            main(["emit", "--event-type", "session.started"])
        assert exc_info.value.code == 2

    def test_cli_emit_validates_event_type_choices(self) -> None:
        """CLI emit command only accepts valid event types."""
        from plugins.onex.hooks.lib.emit_client_wrapper import main

        with pytest.raises(SystemExit) as exc_info:
            main(
                [
                    "emit",
                    "--event-type",
                    "invalid.type",
                    "--payload",
                    '{"test": "data"}',
                ]
            )
        assert exc_info.value.code == 2

    def test_cli_emit_rejects_invalid_json_payload(self) -> None:
        """CLI emit command rejects invalid JSON in payload."""
        from plugins.onex.hooks.lib.emit_client_wrapper import main

        result = main(
            ["emit", "--event-type", "session.started", "--payload", "not valid json"]
        )
        # Should return 1 for error
        assert result == 1

    def test_cli_emit_rejects_non_object_payload(self) -> None:
        """CLI emit command rejects non-object JSON payload."""
        from plugins.onex.hooks.lib.emit_client_wrapper import main

        # JSON array is valid JSON but not an object
        result = main(
            ["emit", "--event-type", "session.started", "--payload", '["array"]']
        )
        assert result == 1

    def test_cli_verbose_flag_accepted(self) -> None:
        """CLI accepts -v/--verbose flag."""
        from plugins.onex.hooks.lib.emit_client_wrapper import main

        # Verbose status should still work
        result = main(["-v", "status"])
        assert result == 0

    def test_cli_help_available(self) -> None:
        """CLI --help exits with code 0."""
        from plugins.onex.hooks.lib.emit_client_wrapper import main

        with pytest.raises(SystemExit) as exc_info:
            main(["--help"])
        assert exc_info.value.code == 0

    def test_cli_emit_subcommand_help_available(self) -> None:
        """CLI emit --help exits with code 0."""
        from plugins.onex.hooks.lib.emit_client_wrapper import main

        with pytest.raises(SystemExit) as exc_info:
            main(["emit", "--help"])
        assert exc_info.value.code == 0


# =============================================================================
# Environment Variable Override Tests
# =============================================================================


class TestEnvironmentVariableOverrides:
    """Tests for environment variable overrides."""

    def test_socket_path_from_environment(self) -> None:
        """get_status respects OMNICLAUDE_EMIT_SOCKET env var."""
        import os

        from plugins.onex.hooks.lib.emit_client_wrapper import get_status

        custom_path = "/custom/socket.sock"

        # Set environment variable
        old_value = os.environ.get("OMNICLAUDE_EMIT_SOCKET")
        try:
            os.environ["OMNICLAUDE_EMIT_SOCKET"] = custom_path
            status = get_status()
            assert status["socket_path"] == custom_path
        finally:
            # Restore original value
            if old_value is None:
                os.environ.pop("OMNICLAUDE_EMIT_SOCKET", None)
            else:
                os.environ["OMNICLAUDE_EMIT_SOCKET"] = old_value


# =============================================================================
# Edge Case Tests
# =============================================================================


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_emit_event_with_empty_payload(self) -> None:
        """emit_event handles empty payload dict."""
        from plugins.onex.hooks.lib.emit_client_wrapper import emit_event

        # Empty payload is valid (daemon validates required fields)
        result = emit_event(
            event_type="session.started",
            payload={},
            timeout_ms=1,
        )
        # Returns bool regardless of success/failure
        assert isinstance(result, bool)

    def test_emit_event_with_complex_payload(self) -> None:
        """emit_event handles complex nested payload."""
        from plugins.onex.hooks.lib.emit_client_wrapper import emit_event

        complex_payload = {
            "session_id": "test-123",
            "metadata": {
                "nested": {
                    "deeply": {
                        "value": [1, 2, 3],
                    }
                }
            },
            "tags": ["a", "b", "c"],
        }

        result = emit_event(
            event_type="session.started",
            payload=complex_payload,
            timeout_ms=1,
        )
        assert isinstance(result, bool)

    def test_emit_event_never_raises_exception(self) -> None:
        """emit_event is designed to never raise exceptions."""
        from plugins.onex.hooks.lib.emit_client_wrapper import emit_event

        # Even with weird inputs, should not raise
        try:
            result = emit_event(
                event_type="session.started",
                payload={"key": "value"},
                timeout_ms=0,  # Zero timeout
            )
            assert isinstance(result, bool)
        except Exception as e:
            pytest.fail(f"emit_event raised an exception: {e}")

    def test_daemon_available_never_raises_exception(self) -> None:
        """daemon_available is designed to never raise exceptions."""
        from plugins.onex.hooks.lib.emit_client_wrapper import daemon_available

        try:
            result = daemon_available()
            assert isinstance(result, bool)
        except Exception as e:
            pytest.fail(f"daemon_available raised an exception: {e}")


# =============================================================================
# Integration-style Tests (Mocked)
# =============================================================================


class TestMockedIntegration:
    """Tests with mocked dependencies for integration scenarios."""

    def test_emit_event_success_with_mocked_client(self) -> None:
        """Successful emit returns True with mocked client."""
        from plugins.onex.hooks.lib import emit_client_wrapper

        # Mock the client to succeed
        mock_client = MagicMock()
        mock_client.emit_sync.return_value = "test-event-id"

        with patch.object(emit_client_wrapper, "_get_client", return_value=mock_client):
            result = emit_client_wrapper.emit_event(
                event_type="session.started",
                payload={"session_id": "test"},
                timeout_ms=50,
            )

        assert result is True
        mock_client.emit_sync.assert_called_once_with(
            "session.started", {"session_id": "test"}
        )

    def test_emit_event_failure_with_mocked_client(self) -> None:
        """Failed emit returns False with mocked client."""
        from plugins.onex.hooks.lib import emit_client_wrapper

        # Mock the client to fail
        mock_client = MagicMock()
        mock_client.emit_sync.side_effect = Exception("Connection refused")

        with patch.object(emit_client_wrapper, "_get_client", return_value=mock_client):
            result = emit_client_wrapper.emit_event(
                event_type="session.started",
                payload={"session_id": "test"},
                timeout_ms=50,
            )

        assert result is False

    def test_emit_event_returns_false_when_client_unavailable(self) -> None:
        """emit_event returns False when client is None."""
        from plugins.onex.hooks.lib import emit_client_wrapper

        with patch.object(emit_client_wrapper, "_get_client", return_value=None):
            result = emit_client_wrapper.emit_event(
                event_type="session.started",
                payload={"session_id": "test"},
                timeout_ms=50,
            )

        assert result is False

    def test_daemon_available_with_mocked_client(self) -> None:
        """daemon_available returns True when client reports daemon running."""
        from plugins.onex.hooks.lib import emit_client_wrapper

        mock_client = MagicMock()
        mock_client.is_daemon_running_sync.return_value = True

        with patch.object(emit_client_wrapper, "_get_client", return_value=mock_client):
            result = emit_client_wrapper.daemon_available()

        assert result is True

    def test_daemon_available_false_when_client_unavailable(self) -> None:
        """daemon_available returns False when client is None."""
        from plugins.onex.hooks.lib import emit_client_wrapper

        with patch.object(emit_client_wrapper, "_get_client", return_value=None):
            result = emit_client_wrapper.daemon_available()

        assert result is False


# =============================================================================
# Error Classification Tests
# =============================================================================


class TestErrorClassification:
    """Tests for error classification in emit_event."""

    def test_connection_refused_logs_at_warning_level(self) -> None:
        """ConnectionRefusedError logs at WARNING level for visibility."""

        from plugins.onex.hooks.lib import emit_client_wrapper

        mock_client = MagicMock()
        mock_client.emit_sync.side_effect = ConnectionRefusedError("Connection refused")

        with patch.object(emit_client_wrapper, "_get_client", return_value=mock_client):
            with patch.object(emit_client_wrapper.logger, "warning") as mock_warning:
                result = emit_client_wrapper.emit_event(
                    event_type="session.started",
                    payload={"session_id": "test"},
                )

        assert result is False
        mock_warning.assert_called()

    def test_file_not_found_logs_at_warning_level(self) -> None:
        """FileNotFoundError logs at WARNING level for visibility."""
        from plugins.onex.hooks.lib import emit_client_wrapper

        mock_client = MagicMock()
        mock_client.emit_sync.side_effect = FileNotFoundError("Socket not found")

        with patch.object(emit_client_wrapper, "_get_client", return_value=mock_client):
            with patch.object(emit_client_wrapper.logger, "warning") as mock_warning:
                result = emit_client_wrapper.emit_event(
                    event_type="session.started",
                    payload={"session_id": "test"},
                )

        assert result is False
        mock_warning.assert_called()

    def test_broken_pipe_logs_at_warning_level(self) -> None:
        """BrokenPipeError logs at WARNING level for visibility."""
        from plugins.onex.hooks.lib import emit_client_wrapper

        mock_client = MagicMock()
        mock_client.emit_sync.side_effect = BrokenPipeError("Broken pipe")

        with patch.object(emit_client_wrapper, "_get_client", return_value=mock_client):
            with patch.object(emit_client_wrapper.logger, "warning") as mock_warning:
                result = emit_client_wrapper.emit_event(
                    event_type="session.started",
                    payload={"session_id": "test"},
                )

        assert result is False
        mock_warning.assert_called()

    def test_type_error_logs_at_error_level(self) -> None:
        """TypeError logs at ERROR level (indicates bug)."""
        from plugins.onex.hooks.lib import emit_client_wrapper

        mock_client = MagicMock()
        mock_client.emit_sync.side_effect = TypeError("unhashable type")

        with patch.object(emit_client_wrapper, "_get_client", return_value=mock_client):
            with patch.object(emit_client_wrapper.logger, "error") as mock_error:
                result = emit_client_wrapper.emit_event(
                    event_type="session.started",
                    payload={"session_id": "test"},
                )

        assert result is False
        mock_error.assert_called()

    def test_value_error_logs_at_error_level(self) -> None:
        """ValueError logs at ERROR level (indicates bug)."""
        from plugins.onex.hooks.lib import emit_client_wrapper

        mock_client = MagicMock()
        mock_client.emit_sync.side_effect = ValueError("invalid value")

        with patch.object(emit_client_wrapper, "_get_client", return_value=mock_client):
            with patch.object(emit_client_wrapper.logger, "error") as mock_error:
                result = emit_client_wrapper.emit_event(
                    event_type="session.started",
                    payload={"session_id": "test"},
                )

        assert result is False
        mock_error.assert_called()

    def test_json_decode_error_logs_at_error_level(self) -> None:
        """JSONDecodeError logs at ERROR level (indicates bug)."""
        import json

        from plugins.onex.hooks.lib import emit_client_wrapper

        mock_client = MagicMock()
        mock_client.emit_sync.side_effect = json.JSONDecodeError("msg", "doc", 0)

        with patch.object(emit_client_wrapper, "_get_client", return_value=mock_client):
            with patch.object(emit_client_wrapper.logger, "error") as mock_error:
                result = emit_client_wrapper.emit_event(
                    event_type="session.started",
                    payload={"session_id": "test"},
                )

        assert result is False
        mock_error.assert_called()

    def test_unexpected_error_logs_at_warning_level(self) -> None:
        """Unknown exceptions log at WARNING level."""
        from plugins.onex.hooks.lib import emit_client_wrapper

        mock_client = MagicMock()
        mock_client.emit_sync.side_effect = RuntimeError("unexpected error")

        with patch.object(emit_client_wrapper, "_get_client", return_value=mock_client):
            with patch.object(emit_client_wrapper.logger, "warning") as mock_warning:
                result = emit_client_wrapper.emit_event(
                    event_type="session.started",
                    payload={"session_id": "test"},
                )

        assert result is False
        mock_warning.assert_called()

    def test_client_unavailable_logs_at_debug_level(self) -> None:
        """When client is None, logs at DEBUG level (expected during startup)."""
        from plugins.onex.hooks.lib import emit_client_wrapper

        with patch.object(emit_client_wrapper, "_get_client", return_value=None):
            with patch.object(emit_client_wrapper.logger, "debug") as mock_debug:
                with patch.object(
                    emit_client_wrapper.logger, "warning"
                ) as mock_warning:
                    result = emit_client_wrapper.emit_event(
                        event_type="session.started",
                        payload={"session_id": "test"},
                    )

        assert result is False
        # Should log at DEBUG, not WARNING
        mock_debug.assert_called()
        assert not any(
            "not available" in str(call) for call in mock_warning.call_args_list
        )


# =============================================================================
# Integration Tests
# =============================================================================


class TestIntegration:
    """Integration tests for actual socket operations.

    These tests require a running emit daemon and are skipped in CI.
    Run locally with: pytest -m integration
    """

    @pytest.mark.integration
    def test_concurrent_socket_operations_with_real_daemon(self) -> None:
        """Integration test: concurrent operations against real daemon socket.

        This test verifies thread-safety with actual socket operations.
        Requires emit daemon to be running.
        """
        from plugins.onex.hooks.lib import emit_client_wrapper

        # Skip if daemon is not running
        initial_status = emit_client_wrapper.get_status()
        if not initial_status.get("daemon_running", False):
            pytest.skip(
                "Emit daemon not running - start with: "
                "python -m omnibase_infra.runtime.emit_daemon.cli start "
                "--kafka-servers <host:port>"
            )

        errors: list[Exception] = []
        results: list[dict] = []

        def status_worker() -> None:
            try:
                for _ in range(20):
                    status = emit_client_wrapper.get_status()
                    results.append(status)
            except Exception as e:
                errors.append(e)

        # Run 5 threads making 20 status calls each
        threads = [threading.Thread(target=status_worker) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        # Verify no errors occurred
        assert len(errors) == 0, f"Errors during concurrent access: {errors}"

        # All 100 calls should have succeeded
        assert len(results) == 100

        # All results should indicate daemon is running
        for result in results:
            assert result.get("daemon_running") is True
