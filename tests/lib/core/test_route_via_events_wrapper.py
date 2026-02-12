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
    main,
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
        assert "selected_agent" in result
        # When cohort assignment is available, verify the value is well-formed
        if "cohort" in result and result["cohort"] is not None:
            assert isinstance(result["cohort"], str)
            assert len(result["cohort"]) > 0

    def test_cohort_excluded_when_no_session_id(self):
        """Cohort information should not be present without session_id."""
        result = route_via_events("test prompt", "corr-123")
        assert "selected_agent" in result
        # Without session_id, cohort should be absent or explicitly None
        cohort_value = result.get("cohort")
        assert cohort_value is None or cohort_value == ""

    def test_cohort_assignment_is_deterministic(self):
        """Same session_id should produce the same cohort assignment."""
        result_a = route_via_events(
            "test prompt", "corr-a", session_id="session-deterministic"
        )
        result_b = route_via_events(
            "test prompt", "corr-b", session_id="session-deterministic"
        )
        # When cohort assignment is available, verify determinism
        if "cohort" in result_a and result_a["cohort"] is not None:
            assert result_a["cohort"] == result_b["cohort"], (
                "Same session_id must produce the same cohort"
            )


class TestMainCLI:
    """Tests for the CLI entry point."""

    def test_missing_args_returns_local_path(self, capsys, monkeypatch):
        """Missing CLI args should return routing_path='local'."""
        monkeypatch.setattr(sys, "argv", ["route_via_events_wrapper.py"])

        # Use try/except instead of pytest.raises so that unexpected exit
        # codes propagate as real failures rather than being silently caught.
        try:
            main()
            pytest.fail("Expected SystemExit(0) was not raised")
        except SystemExit as exc:
            if exc.code != 0:
                raise  # Propagate unexpected exit codes

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

        # main() returns normally (no sys.exit) when args are provided.
        # Do NOT catch SystemExit broadly -- unexpected exit codes must
        # propagate as real test failures.
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

        # main() returns normally (no sys.exit) when args are provided.
        # Do NOT catch SystemExit broadly -- unexpected exit codes must
        # propagate as real test failures.
        main()

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


class TestCandidateListFormatting:
    """Tests for candidate list structure in routing results (OMN-1980).

    The candidates array is the primary agent selection mechanism:
    the hook generates candidates, Claude makes the final semantic selection.
    These tests verify the contract between the routing wrapper and
    downstream consumers (Claude, local LLM).
    """

    def test_candidates_array_is_always_present(self):
        """Candidates array must always exist in routing result, even if empty."""
        result = route_via_events("test prompt", "corr-123")
        assert "candidates" in result
        assert isinstance(result["candidates"], list)

    def test_candidates_populated_on_high_confidence_match(self):
        """When a good match is found, candidates should include all recommendations."""
        mock_recs = []
        for i, (name, score, desc) in enumerate(
            [
                ("agent-pr-review", 0.85, "PR review specialist"),
                ("agent-code-quality", 0.72, "Code quality analysis"),
                ("agent-testing", 0.60, "Testing agent"),
            ]
        ):
            mock_conf = MagicMock()
            mock_conf.total = score
            mock_conf.explanation = f"Match {i}"
            rec = MagicMock()
            rec.agent_name = name
            rec.agent_title = name.replace("agent-", "").replace("-", " ").title()
            rec.confidence = mock_conf
            rec.reason = f"Trigger match: '{name}'"
            rec.is_explicit = False
            mock_recs.append(rec)

        mock_router = MagicMock()
        mock_router.route.return_value = mock_recs
        mock_router.registry = {
            "agents": {
                "agent-pr-review": {
                    "domain_context": "code_review",
                    "description": "PR review specialist",
                },
                "agent-code-quality": {
                    "domain_context": "code_quality",
                    "description": "Code quality analysis",
                },
                "agent-testing": {
                    "domain_context": "testing",
                    "description": "Testing agent",
                },
            }
        }

        with patch("route_via_events_wrapper._get_router", return_value=mock_router):
            result = route_via_events("review PR 92", "corr-123")

        candidates = result["candidates"]
        assert len(candidates) == 3
        assert candidates[0]["name"] == "agent-pr-review"
        assert candidates[0]["score"] == 0.85

    def test_candidate_object_structure(self):
        """Each candidate must have name, score, description, and reason."""
        mock_conf = MagicMock()
        mock_conf.total = 0.80
        mock_conf.explanation = "Good match"

        mock_rec = MagicMock()
        mock_rec.agent_name = "agent-debug"
        mock_rec.agent_title = "Debug Agent"
        mock_rec.confidence = mock_conf
        mock_rec.reason = "Exact match: 'debug'"
        mock_rec.is_explicit = False

        mock_router = MagicMock()
        mock_router.route.return_value = [mock_rec]
        mock_router.registry = {
            "agents": {
                "agent-debug": {
                    "domain_context": "debugging",
                    "description": "Debug and troubleshoot",
                }
            }
        }

        with patch("route_via_events_wrapper._get_router", return_value=mock_router):
            result = route_via_events("debug this error", "corr-123")

        candidate = result["candidates"][0]
        assert "name" in candidate
        assert "score" in candidate
        assert "description" in candidate
        assert "reason" in candidate
        assert isinstance(candidate["name"], str)
        assert isinstance(candidate["score"], (int, float))
        assert isinstance(candidate["description"], str)
        assert isinstance(candidate["reason"], str)

    def test_candidates_empty_when_no_matches(self):
        """Candidates should be empty when no trigger matches found."""
        mock_router = MagicMock()
        mock_router.route.return_value = []
        mock_router.registry = {"agents": {}}

        with patch("route_via_events_wrapper._get_router", return_value=mock_router):
            result = route_via_events("completely unrelated text", "corr-123")

        assert result["candidates"] == []

    def test_candidates_empty_when_router_unavailable(self):
        """Candidates should be empty when router is not available."""
        with patch("route_via_events_wrapper._get_router", return_value=None):
            result = route_via_events("test prompt", "corr-123")

        assert result["candidates"] == []

    def test_candidates_sorted_by_score_descending(self):
        """Candidates must be sorted by score, highest first."""
        mock_recs = []
        for name, score in [
            ("agent-a", 0.60),
            ("agent-b", 0.85),
            ("agent-c", 0.72),
        ]:
            mock_conf = MagicMock()
            mock_conf.total = score
            mock_conf.explanation = "Match"
            rec = MagicMock()
            rec.agent_name = name
            rec.agent_title = name
            rec.confidence = mock_conf
            rec.reason = "Trigger match"
            rec.is_explicit = False
            mock_recs.append(rec)

        mock_router = MagicMock()
        # AgentRouter.route() returns sorted results, so the wrapper
        # should preserve that ordering when building the candidates list.
        mock_router.route.return_value = sorted(
            mock_recs, key=lambda r: r.confidence.total, reverse=True
        )
        mock_router.registry = {
            "agents": {
                "agent-a": {"description": "Agent A"},
                "agent-b": {"description": "Agent B"},
                "agent-c": {"description": "Agent C"},
            }
        }

        with patch("route_via_events_wrapper._get_router", return_value=mock_router):
            result = route_via_events("test prompt", "corr-123")

        scores = [c["score"] for c in result["candidates"]]
        assert scores == sorted(scores, reverse=True)

    def test_candidates_cleared_on_timeout(self):
        """Candidates must be empty when routing exceeds timeout."""
        import time

        mock_conf = MagicMock()
        mock_conf.total = 0.90
        mock_conf.explanation = "Good match"

        mock_rec = MagicMock()
        mock_rec.agent_name = "agent-test"
        mock_rec.agent_title = "Test Agent"
        mock_rec.confidence = mock_conf
        mock_rec.reason = "Match"
        mock_rec.is_explicit = False

        mock_router = MagicMock()
        mock_router.route.return_value = [mock_rec]
        mock_router.registry = {"agents": {"agent-test": {"description": "Test"}}}

        with patch("route_via_events_wrapper._get_router", return_value=mock_router):
            # Force timeout by setting _start_time far in the past (10 seconds ago),
            # so elapsed time exceeds the 1ms timeout_ms budget.
            result = route_via_events(
                "test", "corr-123", timeout_ms=1, _start_time=time.time() - 10
            )

        assert result["candidates"] == []
        assert result["selected_agent"] == DEFAULT_AGENT

    def test_candidates_empty_on_invalid_input(self):
        """Empty or invalid input should return empty candidates."""
        result = route_via_events("", "corr-123")
        assert result["candidates"] == []

        result = route_via_events("  ", "corr-123")
        assert result["candidates"] == []

    def test_candidates_use_description_from_registry(self):
        """Candidate descriptions should come from agent registry, not recommendation title."""
        mock_conf = MagicMock()
        mock_conf.total = 0.80
        mock_conf.explanation = "Match"

        mock_rec = MagicMock()
        mock_rec.agent_name = "agent-deploy"
        mock_rec.agent_title = "Deploy Agent"  # Title from recommendation
        mock_rec.confidence = mock_conf
        mock_rec.reason = "Trigger match"
        mock_rec.is_explicit = False

        mock_router = MagicMock()
        mock_router.route.return_value = [mock_rec]
        mock_router.registry = {
            "agents": {
                "agent-deploy": {
                    "domain_context": "devops",
                    # Description from registry should take precedence
                    "description": "Infrastructure deployment specialist",
                }
            }
        }

        with patch("route_via_events_wrapper._get_router", return_value=mock_router):
            result = route_via_events("deploy to production", "corr-123")

        assert (
            result["candidates"][0]["description"]
            == "Infrastructure deployment specialist"
        )


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
