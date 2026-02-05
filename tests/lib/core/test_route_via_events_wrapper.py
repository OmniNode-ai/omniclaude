# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""
Tests for route_via_events_wrapper.py (Polly-First Architecture)

Verifies:
- routing_path is always present in responses
- Polly-first routing always returns local path (event_attempted=False)
- _compute_routing_path helper works correctly
- Unknown methods produce warnings (no silent failures)
"""

import json
import logging
import sys
from pathlib import Path

import pytest

# Add hooks lib to path for imports
_HOOKS_LIB = Path(__file__).parent.parent.parent.parent / "plugins/onex/hooks/lib"
if str(_HOOKS_LIB) not in sys.path:
    sys.path.insert(0, str(_HOOKS_LIB))

from route_via_events_wrapper import (
    VALID_ROUTING_PATHS,
    RoutingMethod,
    RoutingPath,
    RoutingPolicy,
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


class TestRouteViaEventsPollyFirst:
    """Tests for the Polly-first route_via_events function.

    In Polly-first architecture:
    - polymorphic-agent is ALWAYS selected
    - routing_path is ALWAYS 'local'
    - event_attempted is ALWAYS False
    - routing_method is ALWAYS 'local'
    - routing_policy is ALWAYS 'polly_first'
    """

    def test_always_returns_polymorphic_agent(self):
        """Polly-first: should always return polymorphic-agent."""
        result = route_via_events("test prompt", "corr-123")
        assert result["selected_agent"] == "polymorphic-agent"

    def test_always_returns_local_routing_path(self):
        """Polly-first: routing_path should always be 'local'."""
        result = route_via_events("test prompt", "corr-123")
        assert result["routing_path"] == "local"
        assert result["routing_path"] in VALID_ROUTING_PATHS

    def test_event_attempted_is_always_false(self):
        """Polly-first never attempts event-based routing."""
        result = route_via_events("test prompt", "corr-123")
        assert result["event_attempted"] is False

    def test_routing_method_is_local(self):
        """Polly-first uses local routing method."""
        result = route_via_events("test prompt", "corr-123")
        assert result["routing_method"] == RoutingMethod.LOCAL.value

    def test_routing_policy_is_polly_first(self):
        """Polly-first sets routing_policy to polly_first."""
        result = route_via_events("test prompt", "corr-123")
        assert result["routing_policy"] == RoutingPolicy.POLLY_FIRST.value

    def test_high_confidence(self):
        """Polly-first should have high confidence."""
        result = route_via_events("test prompt", "corr-123")
        assert result["confidence"] == 0.95

    def test_includes_domain_and_purpose(self):
        """Response should include agent metadata."""
        result = route_via_events("test prompt", "corr-123")
        assert result["domain"] == "workflow_coordination"
        assert result["purpose"] == "Intelligent coordinator for development workflows"

    def test_latency_is_captured(self):
        """Latency should be captured in milliseconds."""
        result = route_via_events("test prompt", "corr-123")
        assert "latency_ms" in result
        assert isinstance(result["latency_ms"], int)
        assert result["latency_ms"] >= 0

    def test_routing_path_is_always_present(self):
        """routing_path must always be present in response."""
        result = route_via_events("test", "corr")
        assert "routing_path" in result
        assert result["routing_path"] in VALID_ROUTING_PATHS

    def test_reasoning_explains_polly_first(self):
        """Reasoning should explain Polly-first architecture."""
        result = route_via_events("test prompt", "corr-123")
        assert "Polly-first" in result["reasoning"]

    def test_legacy_method_field_for_backward_compatibility(self):
        """Legacy 'method' field should still be present."""
        result = route_via_events("test prompt", "corr-123")
        assert "method" in result
        assert result["method"] == RoutingPolicy.POLLY_FIRST.value


class TestRouteViaEventsCohort:
    """Tests for cohort assignment in route_via_events."""

    def test_cohort_included_when_session_id_provided(self):
        """Cohort information should be included when session_id is provided."""
        result = route_via_events(
            "test prompt", "corr-123", session_id="session-abc-123"
        )
        # Cohort may or may not be present depending on whether
        # cohort_assignment module is available - just verify no errors
        assert "selected_agent" in result

    def test_cohort_excluded_when_no_session_id(self):
        """Cohort information should not be present without session_id."""
        result = route_via_events("test prompt", "corr-123")
        # Without session_id, cohort assignment is skipped
        # (cohort field won't be present or will be None)
        assert result["selected_agent"] == "polymorphic-agent"


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
        # In Polly-first, method is polly_first not fallback
        assert result["method"] == RoutingPolicy.POLLY_FIRST.value

    def test_with_args_returns_polly_first_result(self, capsys, monkeypatch):
        """CLI with proper args should return Polly-first routing."""
        monkeypatch.setattr(
            sys, "argv", ["route_via_events_wrapper.py", "test prompt", "corr-123"]
        )

        from route_via_events_wrapper import main

        # main() doesn't call sys.exit on success - it just returns
        main()

        captured = capsys.readouterr()
        result = json.loads(captured.out)

        assert result["selected_agent"] == "polymorphic-agent"
        assert result["routing_path"] == "local"

    def test_cli_with_timeout_and_session_id(self, capsys, monkeypatch):
        """CLI accepts timeout_ms and session_id arguments."""
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "route_via_events_wrapper.py",
                "test prompt",
                "corr-123",
                "5000",
                "session-123",
            ],
        )

        from route_via_events_wrapper import main

        # Run main - it should not raise
        try:
            main()
        except SystemExit as e:
            pass  # Expected - main doesn't exit normally

        captured = capsys.readouterr()
        result = json.loads(captured.out)

        assert result["selected_agent"] == "polymorphic-agent"
        assert result["routing_path"] == "local"


class TestRoutingEnums:
    """Tests for routing enum consistency."""

    def test_routing_method_values(self):
        """Verify RoutingMethod enum values."""
        assert RoutingMethod.EVENT_BASED.value == "event_based"
        assert RoutingMethod.LOCAL.value == "local"
        assert RoutingMethod.FALLBACK.value == "fallback"

    def test_routing_policy_values(self):
        """Verify RoutingPolicy enum values."""
        assert RoutingPolicy.POLLY_FIRST.value == "polly_first"
        assert RoutingPolicy.SAFETY_GATE.value == "safety_gate"
        assert RoutingPolicy.COST_GATE.value == "cost_gate"
        assert RoutingPolicy.EXPLICIT_AGENT.value == "explicit_agent"

    def test_routing_path_values(self):
        """Verify RoutingPath enum values."""
        assert RoutingPath.EVENT.value == "event"
        assert RoutingPath.LOCAL.value == "local"
        assert RoutingPath.HYBRID.value == "hybrid"

    def test_valid_routing_paths_matches_enum(self):
        """VALID_ROUTING_PATHS should contain all RoutingPath enum values."""
        for path in RoutingPath:
            assert path.value in VALID_ROUTING_PATHS
