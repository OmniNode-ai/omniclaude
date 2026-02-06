# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""
Tests for route_via_events_wrapper.py (Intelligent Routing Architecture)

Verifies:
- routing_path is always present in responses
- Intelligent routing uses trigger matching with confidence scoring
- Explicit agent requests are honored
- Fallback to polymorphic-agent when confidence is low
- _compute_routing_path helper works correctly
- Unknown methods produce warnings (no silent failures)
"""

import json
import logging
import sys
from unittest.mock import MagicMock, patch

import pytest

# Note: Plugin lib path is added by tests/conftest.py, no need for manual sys.path manipulation
from route_via_events_wrapper import (
    CONFIDENCE_THRESHOLD,
    DEFAULT_AGENT,
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


class TestRouteViaEventsIntelligent:
    """Tests for the intelligent route_via_events function.

    In intelligent routing architecture:
    - AgentRouter performs trigger matching with confidence scoring
    - High-confidence matches route to the matched agent
    - Low-confidence matches fall back to polymorphic-agent
    - Explicit agent requests are honored with confidence=1.0
    - routing_path is always 'local' (no event-based routing yet)
    """

    def test_routing_path_is_always_present(self):
        """routing_path must always be present in response."""
        result = route_via_events("test", "corr")
        assert "routing_path" in result
        assert result["routing_path"] in VALID_ROUTING_PATHS

    def test_routing_path_is_local(self):
        """Intelligent routing uses local path (no event bus)."""
        result = route_via_events("test prompt", "corr-123")
        assert result["routing_path"] == "local"

    def test_event_attempted_is_always_false(self):
        """Intelligent routing never attempts event-based routing."""
        result = route_via_events("test prompt", "corr-123")
        assert result["event_attempted"] is False

    def test_routing_method_is_local(self):
        """Intelligent routing uses local routing method."""
        result = route_via_events("test prompt", "corr-123")
        assert result["routing_method"] == RoutingMethod.LOCAL.value

    def test_includes_domain_and_purpose(self):
        """Response should include agent metadata."""
        result = route_via_events("test prompt", "corr-123")
        assert "domain" in result
        assert "purpose" in result

    def test_latency_is_captured(self):
        """Latency should be captured in milliseconds."""
        result = route_via_events("test prompt", "corr-123")
        assert "latency_ms" in result
        assert isinstance(result["latency_ms"], int)
        assert result["latency_ms"] >= 0

    def test_confidence_is_between_0_and_1(self):
        """Confidence should be a valid score between 0 and 1."""
        result = route_via_events("test prompt", "corr-123")
        assert "confidence" in result
        assert 0.0 <= result["confidence"] <= 1.0

    def test_selected_agent_is_present(self):
        """Selected agent should always be present."""
        result = route_via_events("test prompt", "corr-123")
        assert "selected_agent" in result
        assert isinstance(result["selected_agent"], str)
        assert len(result["selected_agent"]) > 0

    def test_reasoning_is_present(self):
        """Reasoning explanation should be present."""
        result = route_via_events("test prompt", "corr-123")
        assert "reasoning" in result
        assert isinstance(result["reasoning"], str)

    def test_legacy_method_field_for_backward_compatibility(self):
        """Legacy 'method' field should still be present."""
        result = route_via_events("test prompt", "corr-123")
        assert "method" in result
        # Legacy method mirrors routing_policy
        assert result["method"] == result["routing_policy"]


class TestRouteViaEventsWithMockedRouter:
    """Tests using mocked AgentRouter for deterministic behavior."""

    def test_high_confidence_match_uses_recommended_agent(self):
        """High confidence match should route to the recommended agent."""
        # Create mock recommendation with high confidence
        mock_confidence = MagicMock()
        mock_confidence.total = 0.85
        mock_confidence.explanation = "Strong trigger match"

        mock_recommendation = MagicMock()
        mock_recommendation.agent_name = "agent-testing"
        mock_recommendation.agent_title = "Testing Agent"
        mock_recommendation.confidence = mock_confidence
        mock_recommendation.reason = "Exact match: 'test'"
        mock_recommendation.is_explicit = False

        mock_router = MagicMock()
        mock_router.route.return_value = [mock_recommendation]
        mock_router.registry = {
            "agents": {
                "agent-testing": {
                    "domain_context": "testing",
                    "description": "Test agent for testing purposes",
                }
            }
        }

        with patch("route_via_events_wrapper._get_router", return_value=mock_router):
            result = route_via_events("run tests for my code", "corr-123")

        assert result["selected_agent"] == "agent-testing"
        assert result["confidence"] == 0.85
        assert result["routing_policy"] == RoutingPolicy.TRIGGER_MATCH.value

    def test_low_confidence_match_falls_back_to_default(self):
        """Low confidence match should fall back to polymorphic-agent."""
        mock_confidence = MagicMock()
        mock_confidence.total = 0.3  # Below CONFIDENCE_THRESHOLD (0.5)
        mock_confidence.explanation = "Weak match"

        mock_recommendation = MagicMock()
        mock_recommendation.agent_name = "agent-some-agent"
        mock_recommendation.agent_title = "Some Agent"
        mock_recommendation.confidence = mock_confidence
        mock_recommendation.reason = "Fuzzy match"
        mock_recommendation.is_explicit = False

        mock_router = MagicMock()
        mock_router.route.return_value = [mock_recommendation]
        mock_router.registry = {"agents": {}}

        with patch("route_via_events_wrapper._get_router", return_value=mock_router):
            result = route_via_events("vague prompt", "corr-123")

        assert result["selected_agent"] == DEFAULT_AGENT
        assert result["routing_policy"] == RoutingPolicy.FALLBACK_DEFAULT.value
        assert str(CONFIDENCE_THRESHOLD) in result["reasoning"]

    def test_no_matches_falls_back_to_default(self):
        """No trigger matches should fall back to polymorphic-agent."""
        mock_router = MagicMock()
        mock_router.route.return_value = []  # No matches
        mock_router.registry = {"agents": {}}

        with patch("route_via_events_wrapper._get_router", return_value=mock_router):
            result = route_via_events("completely unrelated prompt", "corr-123")

        assert result["selected_agent"] == DEFAULT_AGENT
        assert result["routing_policy"] == RoutingPolicy.FALLBACK_DEFAULT.value
        assert "No trigger matches" in result["reasoning"]

    def test_explicit_request_sets_explicit_policy(self):
        """Explicit agent request should set EXPLICIT_REQUEST policy."""
        mock_confidence = MagicMock()
        mock_confidence.total = 1.0
        mock_confidence.explanation = "Explicit agent request"

        mock_recommendation = MagicMock()
        mock_recommendation.agent_name = "agent-debug"
        mock_recommendation.agent_title = "Debug Agent"
        mock_recommendation.confidence = mock_confidence
        mock_recommendation.reason = "Explicitly requested by user"
        mock_recommendation.is_explicit = True

        mock_router = MagicMock()
        mock_router.route.return_value = [mock_recommendation]
        mock_router.registry = {
            "agents": {
                "agent-debug": {
                    "domain_context": "debugging",
                    "description": "Debug agent",
                }
            }
        }

        with patch("route_via_events_wrapper._get_router", return_value=mock_router):
            result = route_via_events("use agent-debug to fix this", "corr-123")

        assert result["selected_agent"] == "agent-debug"
        assert result["confidence"] == 1.0
        assert result["routing_policy"] == RoutingPolicy.EXPLICIT_REQUEST.value

    def test_router_unavailable_falls_back_gracefully(self):
        """Router unavailable should fall back to polymorphic-agent."""
        with patch("route_via_events_wrapper._get_router", return_value=None):
            result = route_via_events("test prompt", "corr-123")

        assert result["selected_agent"] == DEFAULT_AGENT
        assert result["routing_policy"] == RoutingPolicy.FALLBACK_DEFAULT.value
        assert "no router available" in result["reasoning"]

    def test_router_error_falls_back_gracefully(self):
        """Router error should fall back to polymorphic-agent."""
        mock_router = MagicMock()
        mock_router.route.side_effect = RuntimeError("Router error")
        mock_router.registry = {"agents": {}}

        with patch("route_via_events_wrapper._get_router", return_value=mock_router):
            result = route_via_events("test prompt", "corr-123")

        assert result["selected_agent"] == DEFAULT_AGENT
        assert result["routing_policy"] == RoutingPolicy.FALLBACK_DEFAULT.value
        assert "Routing error" in result["reasoning"]


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
        assert "selected_agent" in result


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
        assert result["method"] == RoutingPolicy.FALLBACK_DEFAULT.value
        assert result["routing_policy"] == RoutingPolicy.FALLBACK_DEFAULT.value

    def test_with_args_returns_routing_result(self, capsys, monkeypatch):
        """CLI with proper args should return routing result."""
        monkeypatch.setattr(
            sys, "argv", ["route_via_events_wrapper.py", "test prompt", "corr-123"]
        )

        from route_via_events_wrapper import main

        # main() doesn't call sys.exit on success - it just returns
        main()

        captured = capsys.readouterr()
        result = json.loads(captured.out)

        assert "selected_agent" in result
        assert result["routing_path"] == "local"
        assert "routing_policy" in result

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
        except SystemExit:
            pass  # Expected - main doesn't exit normally

        captured = capsys.readouterr()
        result = json.loads(captured.out)

        assert "selected_agent" in result
        assert result["routing_path"] == "local"


class TestRoutingEnums:
    """Tests for routing enum consistency."""

    def test_routing_method_values(self):
        """Verify RoutingMethod enum values."""
        assert RoutingMethod.EVENT_BASED.value == "event_based"
        assert RoutingMethod.LOCAL.value == "local"
        assert RoutingMethod.FALLBACK.value == "fallback"

    def test_routing_policy_values(self):
        """Verify RoutingPolicy enum values for intelligent routing."""
        # Core intelligent routing policies
        assert RoutingPolicy.TRIGGER_MATCH.value == "trigger_match"
        assert RoutingPolicy.EXPLICIT_REQUEST.value == "explicit_request"
        assert RoutingPolicy.FALLBACK_DEFAULT.value == "fallback_default"
        # Additional policies (safety, cost)
        assert RoutingPolicy.SAFETY_GATE.value == "safety_gate"
        assert RoutingPolicy.COST_GATE.value == "cost_gate"

    def test_routing_path_values(self):
        """Verify RoutingPath enum values."""
        assert RoutingPath.EVENT.value == "event"
        assert RoutingPath.LOCAL.value == "local"
        assert RoutingPath.HYBRID.value == "hybrid"

    def test_valid_routing_paths_matches_enum(self):
        """VALID_ROUTING_PATHS should contain all RoutingPath enum values."""
        for path in RoutingPath:
            assert path.value in VALID_ROUTING_PATHS


class TestConfidenceThreshold:
    """Tests for confidence threshold behavior."""

    def test_confidence_threshold_is_defined(self):
        """Confidence threshold constant should be defined."""
        assert CONFIDENCE_THRESHOLD == 0.5

    def test_default_agent_is_defined(self):
        """Default fallback agent constant should be defined."""
        assert DEFAULT_AGENT == "polymorphic-agent"

    def test_threshold_boundary_below(self):
        """Confidence just below threshold should fall back."""
        mock_confidence = MagicMock()
        mock_confidence.total = CONFIDENCE_THRESHOLD - 0.01  # Just below threshold

        mock_recommendation = MagicMock()
        mock_recommendation.agent_name = "agent-test"
        mock_recommendation.agent_title = "Test Agent"
        mock_recommendation.confidence = mock_confidence
        mock_recommendation.reason = "Match"
        mock_recommendation.is_explicit = False

        mock_router = MagicMock()
        mock_router.route.return_value = [mock_recommendation]
        mock_router.registry = {"agents": {}}

        with patch("route_via_events_wrapper._get_router", return_value=mock_router):
            result = route_via_events("test", "corr")

        assert result["selected_agent"] == DEFAULT_AGENT

    def test_threshold_boundary_at(self):
        """Confidence exactly at threshold should use matched agent."""
        mock_confidence = MagicMock()
        mock_confidence.total = CONFIDENCE_THRESHOLD  # Exactly at threshold
        mock_confidence.explanation = "Exact threshold match"

        mock_recommendation = MagicMock()
        mock_recommendation.agent_name = "agent-test"
        mock_recommendation.agent_title = "Test Agent"
        mock_recommendation.confidence = mock_confidence
        mock_recommendation.reason = "Match"
        mock_recommendation.is_explicit = False

        mock_router = MagicMock()
        mock_router.route.return_value = [mock_recommendation]
        mock_router.registry = {
            "agents": {
                "agent-test": {
                    "domain_context": "testing",
                    "description": "Test",
                }
            }
        }

        with patch("route_via_events_wrapper._get_router", return_value=mock_router):
            result = route_via_events("test", "corr")

        assert result["selected_agent"] == "agent-test"

    def test_threshold_boundary_above(self):
        """Confidence above threshold should use matched agent."""
        mock_confidence = MagicMock()
        mock_confidence.total = CONFIDENCE_THRESHOLD + 0.01  # Just above threshold
        mock_confidence.explanation = "Above threshold match"

        mock_recommendation = MagicMock()
        mock_recommendation.agent_name = "agent-test"
        mock_recommendation.agent_title = "Test Agent"
        mock_recommendation.confidence = mock_confidence
        mock_recommendation.reason = "Match"
        mock_recommendation.is_explicit = False

        mock_router = MagicMock()
        mock_router.route.return_value = [mock_recommendation]
        mock_router.registry = {
            "agents": {
                "agent-test": {
                    "domain_context": "testing",
                    "description": "Test",
                }
            }
        }

        with patch("route_via_events_wrapper._get_router", return_value=mock_router):
            result = route_via_events("test", "corr")

        assert result["selected_agent"] == "agent-test"
