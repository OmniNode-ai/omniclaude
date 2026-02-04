# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""
Tests for route_via_events_wrapper.py

Verifies:
- routing_path is always present in responses
- routing_path correctly reflects event_attempted state
- Unknown methods produce warnings (no silent failures)
- Fallback behavior is properly instrumented
"""

import json
import logging
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Add hooks lib to path for imports
_HOOKS_LIB = Path(__file__).parent.parent.parent.parent / "plugins/onex/hooks/lib"
if str(_HOOKS_LIB) not in sys.path:
    sys.path.insert(0, str(_HOOKS_LIB))

from route_via_events_wrapper import (
    VALID_ROUTING_PATHS,
    _compute_routing_path,
    route_via_events,
)


class TestComputeRoutingPath:
    """Tests for the _compute_routing_path helper function."""

    def test_returns_event_when_event_based_and_attempted(self):
        """Event-based routing that succeeded should return 'event'."""
        result = _compute_routing_path("event_based", event_attempted=True)
        assert result == "event"

    def test_returns_hybrid_when_fallback_and_attempted(self):
        """Fallback after attempting event routing should return 'hybrid'."""
        result = _compute_routing_path("fallback", event_attempted=True)
        assert result == "hybrid"

    def test_returns_local_when_not_attempted(self):
        """When event routing was never attempted, should return 'local'."""
        result = _compute_routing_path("fallback", event_attempted=False)
        assert result == "local"

    def test_returns_local_when_not_attempted_regardless_of_method(self):
        """Method is irrelevant when event_attempted=False."""
        assert _compute_routing_path("event_based", event_attempted=False) == "local"
        assert _compute_routing_path("fallback", event_attempted=False) == "local"
        assert _compute_routing_path("unknown", event_attempted=False) == "local"

    def test_logs_warning_on_unknown_method(self, caplog):
        """Unknown method values should produce a warning log."""
        with caplog.at_level(logging.WARNING):
            result = _compute_routing_path("unknown_method", event_attempted=True)

        assert result == "local"
        assert "Unknown routing method 'unknown_method'" in caplog.text
        assert "instrumentation drift" in caplog.text

    def test_all_valid_paths_are_reachable(self):
        """Verify all VALID_ROUTING_PATHS can be produced."""
        # event
        assert _compute_routing_path("event_based", True) == "event"
        assert "event" in VALID_ROUTING_PATHS

        # hybrid
        assert _compute_routing_path("fallback", True) == "hybrid"
        assert "hybrid" in VALID_ROUTING_PATHS

        # local
        assert _compute_routing_path("fallback", False) == "local"
        assert "local" in VALID_ROUTING_PATHS


class TestRouteViaEvents:
    """Tests for the route_via_events function."""

    def test_returns_routing_path_event_on_success(self):
        """Successful event-based routing should return routing_path='event'."""
        mock_adapter = MagicMock()
        mock_adapter.route_request.return_value = {
            "selected_agent": "test-agent",
            "confidence": 0.9,
            "reasoning": "Test routing",
            "domain": "testing",
            "purpose": "Test purpose",
        }

        with patch(
            "route_via_events_wrapper._get_hook_event_adapter",
            return_value=mock_adapter,
        ):
            result = route_via_events("test prompt", "corr-123")

        assert result["routing_path"] == "event"
        assert result["event_attempted"] is True
        assert result["method"] == "event_based"

    def test_returns_routing_path_hybrid_on_exception(self, caplog):
        """Exception after attempting event routing should return routing_path='hybrid'."""
        mock_adapter = MagicMock()
        mock_adapter.route_request.side_effect = TimeoutError("Kafka timeout")

        with patch(
            "route_via_events_wrapper._get_hook_event_adapter",
            return_value=mock_adapter,
        ):
            with caplog.at_level(logging.WARNING):
                result = route_via_events("test prompt", "corr-123")

        assert result["routing_path"] == "hybrid"
        assert result["event_attempted"] is True
        assert result["method"] == "fallback"
        assert "TimeoutError" in caplog.text

    def test_returns_routing_path_local_when_adapter_unavailable(self, caplog):
        """When adapter is None (import failed), should return routing_path='local'."""
        with patch("route_via_events_wrapper._get_hook_event_adapter", None):
            with caplog.at_level(logging.WARNING):
                result = route_via_events("test prompt", "corr-123")

        assert result["routing_path"] == "local"
        assert result["event_attempted"] is False
        assert result["method"] == "fallback"
        assert "hook_event_adapter import failed" in caplog.text

    def test_returns_routing_path_local_when_adapter_lacks_route_request(self):
        """Adapter without route_request method should return routing_path='local'."""
        mock_adapter = MagicMock(spec=[])  # No route_request attribute

        with patch(
            "route_via_events_wrapper._get_hook_event_adapter",
            return_value=mock_adapter,
        ):
            result = route_via_events("test prompt", "corr-123")

        # Adapter exists but can't route - event_attempted stays False
        assert result["routing_path"] == "local"
        assert result["event_attempted"] is False

    def test_routing_path_is_always_present(self):
        """Both success and fallback paths must include routing_path."""
        # Success path
        mock_adapter = MagicMock()
        mock_adapter.route_request.return_value = {
            "selected_agent": "test-agent",
            "confidence": 0.9,
        }

        with patch(
            "route_via_events_wrapper._get_hook_event_adapter",
            return_value=mock_adapter,
        ):
            success_result = route_via_events("test", "corr")

        assert "routing_path" in success_result
        assert success_result["routing_path"] in VALID_ROUTING_PATHS

        # Fallback path
        with patch("route_via_events_wrapper._get_hook_event_adapter", None):
            fallback_result = route_via_events("test", "corr")

        assert "routing_path" in fallback_result
        assert fallback_result["routing_path"] in VALID_ROUTING_PATHS

    def test_fallback_includes_debugging_context(self, caplog):
        """Fallback should log enough context for debugging."""
        mock_adapter = MagicMock()
        mock_adapter.route_request.side_effect = ConnectionError("Connection refused")

        with patch(
            "route_via_events_wrapper._get_hook_event_adapter",
            return_value=mock_adapter,
        ):
            with caplog.at_level(logging.WARNING):
                route_via_events("test prompt", "corr-123")

        # Should include exception type
        assert "ConnectionError" in caplog.text
        # Should include event_attempted state
        assert "event_attempted=True" in caplog.text

    def test_latency_is_captured(self):
        """Latency should be captured in milliseconds."""
        with patch("route_via_events_wrapper._get_hook_event_adapter", None):
            result = route_via_events("test", "corr")

        assert "latency_ms" in result
        assert isinstance(result["latency_ms"], int)
        assert result["latency_ms"] >= 0


class TestMainCLI:
    """Tests for the CLI entry point."""

    def test_missing_args_returns_local_path(self, capsys, monkeypatch):
        """Missing CLI args should return routing_path='local'."""
        monkeypatch.setattr(sys, "argv", ["route_via_events_wrapper.py"])

        # Import and run main
        from route_via_events_wrapper import main

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 0

        captured = capsys.readouterr()
        result = json.loads(captured.out)

        assert result["routing_path"] == "local"
        assert result["event_attempted"] is False
        assert result["method"] == "fallback"
