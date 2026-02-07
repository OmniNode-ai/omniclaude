# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Tests for ONEX routing node path in route_via_events_wrapper.

Verifies:
- Feature flag USE_ONEX_ROUTING_NODES toggles between ONEX and legacy paths
- ONEX path: builds ModelRoutingRequest, calls compute handler, shapes result
- Stats pre-fetching and caching
- Graceful fallback when ONEX nodes fail
- Result format matches legacy path shape
"""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest
from route_via_events_wrapper import (
    DEFAULT_AGENT,
    VALID_ROUTING_PATHS,
    RoutingMethod,
    route_via_events,
)

# Import ONEX models for building test fixtures
from omniclaude.nodes.node_agent_routing_compute.models import (
    ModelConfidenceBreakdown,
    ModelRoutingCandidate,
    ModelRoutingResult,
)
from omniclaude.nodes.node_routing_emission_effect.models import (
    ModelEmissionResult,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_breakdown(
    total: float = 0.85, explanation: str = "Test match"
) -> ModelConfidenceBreakdown:
    """Create a test ModelConfidenceBreakdown."""
    return ModelConfidenceBreakdown(
        total=total,
        trigger_score=total,
        context_score=0.7,
        capability_score=0.5,
        historical_score=0.5,
        explanation=explanation,
    )


def _make_routing_result(
    selected_agent: str = "agent-testing",
    confidence: float = 0.85,
    routing_policy: str = "trigger_match",
    fallback_reason: str | None = None,
    candidates: tuple = (),
) -> ModelRoutingResult:
    """Create a test ModelRoutingResult."""
    breakdown = _make_breakdown(
        total=confidence, explanation=f"Match for {selected_agent}"
    )
    if not candidates:
        candidates = (
            ModelRoutingCandidate(
                agent_name=selected_agent,
                confidence=confidence,
                confidence_breakdown=breakdown,
                match_reason=f"Trigger match: {selected_agent}",
            ),
        )
    return ModelRoutingResult(
        selected_agent=selected_agent,
        confidence=confidence,
        confidence_breakdown=breakdown,
        routing_policy=routing_policy,
        routing_path="local",
        candidates=candidates,
        fallback_reason=fallback_reason,
    )


def _make_emission_result(cid: UUID | None = None) -> ModelEmissionResult:
    """Create a test ModelEmissionResult."""
    return ModelEmissionResult(
        success=True,
        correlation_id=cid or uuid4(),
        topics_emitted=("onex.evt.omniclaude.routing-decision.v1",),
        error=None,
        duration_ms=1.5,
    )


@pytest.fixture(autouse=True)
def _reset_onex_singletons():
    """Reset ONEX handler singletons between tests."""
    import route_via_events_wrapper as mod

    # Save originals
    orig_compute = mod._compute_handler
    orig_emit = mod._emit_handler
    orig_history = mod._history_handler
    orig_stats = mod._cached_stats

    yield

    # Restore originals
    mod._compute_handler = orig_compute
    mod._emit_handler = orig_emit
    mod._history_handler = orig_history
    mod._cached_stats = orig_stats


# ---------------------------------------------------------------------------
# Feature Flag Tests
# ---------------------------------------------------------------------------


class TestOnexFeatureFlag:
    """Tests for USE_ONEX_ROUTING_NODES feature flag."""

    def test_flag_disabled_uses_legacy_path(self, monkeypatch):
        """When flag is off, ONEX path is not used."""
        monkeypatch.delenv("USE_ONEX_ROUTING_NODES", raising=False)
        result = route_via_events("test prompt", "corr-123")
        assert "selected_agent" in result
        assert result["routing_path"] in VALID_ROUTING_PATHS

    def test_flag_enabled_uses_onex_path(self, monkeypatch):
        """When flag is on and nodes available, ONEX path is used."""
        monkeypatch.setenv("USE_ONEX_ROUTING_NODES", "true")

        mock_compute = MagicMock()
        mock_compute.compute_routing = AsyncMock(return_value=_make_routing_result())
        mock_emitter = MagicMock()
        mock_emitter.emit_routing_decision = AsyncMock(
            return_value=_make_emission_result()
        )
        mock_history = MagicMock()

        # Create a mock router with registry
        mock_router = MagicMock()
        mock_router.registry = {
            "agents": {
                "agent-testing": {
                    "domain_context": "testing",
                    "description": "Test agent",
                    "title": "Test Agent",
                    "activation_triggers": ["test"],
                    "capabilities": [],
                    "definition_path": "/test.yaml",
                }
            }
        }

        with (
            patch(
                "route_via_events_wrapper._get_onex_handlers",
                return_value=(mock_compute, mock_emitter, mock_history),
            ),
            patch("route_via_events_wrapper._get_router", return_value=mock_router),
        ):
            result = route_via_events("test prompt", str(uuid4()))

        assert result["selected_agent"] == "agent-testing"
        assert result["confidence"] == 0.85
        assert result["routing_policy"] == "trigger_match"
        mock_compute.compute_routing.assert_called_once()

    def test_flag_false_string_disables(self, monkeypatch):
        """Explicit 'false' disables ONEX path."""
        monkeypatch.setenv("USE_ONEX_ROUTING_NODES", "false")
        from route_via_events_wrapper import _use_onex_routing_nodes

        assert _use_onex_routing_nodes() is False

    def test_flag_true_string_enables(self, monkeypatch):
        """Explicit 'true' enables ONEX path."""
        monkeypatch.setenv("USE_ONEX_ROUTING_NODES", "true")
        from route_via_events_wrapper import _use_onex_routing_nodes

        assert _use_onex_routing_nodes() is True

    def test_flag_1_enables(self, monkeypatch):
        """'1' enables ONEX path."""
        monkeypatch.setenv("USE_ONEX_ROUTING_NODES", "1")
        from route_via_events_wrapper import _use_onex_routing_nodes

        assert _use_onex_routing_nodes() is True


# ---------------------------------------------------------------------------
# ONEX Routing Path Tests
# ---------------------------------------------------------------------------


class TestOnexRoutingPath:
    """Tests for the ONEX node routing path."""

    @pytest.fixture
    def onex_env(self, monkeypatch):
        """Enable ONEX routing and return mock objects."""
        monkeypatch.setenv("USE_ONEX_ROUTING_NODES", "true")

        mock_compute = MagicMock()
        mock_emitter = MagicMock()
        mock_emitter.emit_routing_decision = AsyncMock(
            return_value=_make_emission_result()
        )
        mock_history = MagicMock()

        mock_router = MagicMock()
        mock_router.registry = {
            "agents": {
                "agent-testing": {
                    "domain_context": "testing",
                    "description": "Test agent",
                    "title": "Test Agent",
                    "activation_triggers": ["test", "testing"],
                    "capabilities": ["testing"],
                    "definition_path": "/test.yaml",
                },
                "polymorphic-agent": {
                    "domain_context": "general",
                    "description": "General coordinator",
                    "title": "Polymorphic Agent",
                    "activation_triggers": [],
                    "capabilities": [],
                    "definition_path": "/poly.yaml",
                },
            }
        }

        return {
            "compute": mock_compute,
            "emitter": mock_emitter,
            "history": mock_history,
            "router": mock_router,
        }

    def test_high_confidence_routes_to_matched_agent(self, onex_env):
        """High confidence ONEX result routes to the matched agent."""
        onex_env["compute"].compute_routing = AsyncMock(
            return_value=_make_routing_result(
                selected_agent="agent-testing", confidence=0.85
            )
        )

        with (
            patch(
                "route_via_events_wrapper._get_onex_handlers",
                return_value=(
                    onex_env["compute"],
                    onex_env["emitter"],
                    onex_env["history"],
                ),
            ),
            patch(
                "route_via_events_wrapper._get_router", return_value=onex_env["router"]
            ),
        ):
            result = route_via_events("run tests", str(uuid4()))

        assert result["selected_agent"] == "agent-testing"
        assert result["confidence"] == 0.85
        assert result["routing_policy"] == "trigger_match"

    def test_fallback_result_returns_default_agent(self, onex_env):
        """Fallback ONEX result returns polymorphic-agent."""
        onex_env["compute"].compute_routing = AsyncMock(
            return_value=_make_routing_result(
                selected_agent="polymorphic-agent",
                confidence=0.0,
                routing_policy="fallback_default",
                fallback_reason="No agents matched above threshold 0.50",
            )
        )

        with (
            patch(
                "route_via_events_wrapper._get_onex_handlers",
                return_value=(
                    onex_env["compute"],
                    onex_env["emitter"],
                    onex_env["history"],
                ),
            ),
            patch(
                "route_via_events_wrapper._get_router", return_value=onex_env["router"]
            ),
        ):
            result = route_via_events("vague prompt", str(uuid4()))

        assert result["selected_agent"] == "polymorphic-agent"
        assert result["routing_policy"] == "fallback_default"
        assert "threshold" in result["reasoning"]

    def test_result_has_all_required_fields(self, onex_env):
        """ONEX result contains all fields matching legacy format."""
        onex_env["compute"].compute_routing = AsyncMock(
            return_value=_make_routing_result()
        )

        with (
            patch(
                "route_via_events_wrapper._get_onex_handlers",
                return_value=(
                    onex_env["compute"],
                    onex_env["emitter"],
                    onex_env["history"],
                ),
            ),
            patch(
                "route_via_events_wrapper._get_router", return_value=onex_env["router"]
            ),
        ):
            result = route_via_events("test prompt", str(uuid4()))

        required_fields = {
            "selected_agent",
            "confidence",
            "candidates",
            "reasoning",
            "routing_method",
            "routing_policy",
            "routing_path",
            "method",
            "latency_ms",
            "domain",
            "purpose",
            "event_attempted",
        }
        assert required_fields.issubset(result.keys())
        assert result["routing_path"] in VALID_ROUTING_PATHS
        assert result["routing_method"] == RoutingMethod.LOCAL.value
        assert result["event_attempted"] is False
        assert isinstance(result["latency_ms"], int)
        assert 0.0 <= result["confidence"] <= 1.0

    def test_candidates_populated_from_result(self, onex_env):
        """Candidates list is populated from ONEX ModelRoutingResult."""
        breakdown = _make_breakdown(total=0.85)
        candidates = (
            ModelRoutingCandidate(
                agent_name="agent-testing",
                confidence=0.85,
                confidence_breakdown=breakdown,
                match_reason="Exact match: 'test'",
            ),
            ModelRoutingCandidate(
                agent_name="polymorphic-agent",
                confidence=0.3,
                confidence_breakdown=_make_breakdown(total=0.3),
                match_reason="Weak match",
            ),
        )
        onex_env["compute"].compute_routing = AsyncMock(
            return_value=_make_routing_result(candidates=candidates)
        )

        with (
            patch(
                "route_via_events_wrapper._get_onex_handlers",
                return_value=(
                    onex_env["compute"],
                    onex_env["emitter"],
                    onex_env["history"],
                ),
            ),
            patch(
                "route_via_events_wrapper._get_router", return_value=onex_env["router"]
            ),
        ):
            result = route_via_events("test prompt", str(uuid4()))

        assert len(result["candidates"]) == 2
        assert result["candidates"][0]["name"] == "agent-testing"
        assert result["candidates"][0]["score"] == 0.85
        assert "reason" in result["candidates"][0]

    def test_emission_called_after_routing(self, onex_env):
        """ONEX emitter is called after successful routing."""
        onex_env["compute"].compute_routing = AsyncMock(
            return_value=_make_routing_result()
        )

        with (
            patch(
                "route_via_events_wrapper._get_onex_handlers",
                return_value=(
                    onex_env["compute"],
                    onex_env["emitter"],
                    onex_env["history"],
                ),
            ),
            patch(
                "route_via_events_wrapper._get_router", return_value=onex_env["router"]
            ),
        ):
            route_via_events("test prompt", str(uuid4()), session_id="session-1")

        onex_env["emitter"].emit_routing_decision.assert_called_once()

    def test_emission_failure_does_not_break_routing(self, onex_env):
        """Emission failure is non-blocking."""
        onex_env["compute"].compute_routing = AsyncMock(
            return_value=_make_routing_result()
        )
        onex_env["emitter"].emit_routing_decision = AsyncMock(
            side_effect=RuntimeError("Kafka down")
        )

        with (
            patch(
                "route_via_events_wrapper._get_onex_handlers",
                return_value=(
                    onex_env["compute"],
                    onex_env["emitter"],
                    onex_env["history"],
                ),
            ),
            patch(
                "route_via_events_wrapper._get_router", return_value=onex_env["router"]
            ),
        ):
            result = route_via_events("test prompt", str(uuid4()))

        # Routing still succeeds despite emission failure
        assert result["selected_agent"] == "agent-testing"


# ---------------------------------------------------------------------------
# Graceful Fallback Tests
# ---------------------------------------------------------------------------


class TestOnexGracefulFallback:
    """Tests that ONEX failures fall back to legacy path."""

    def test_compute_handler_error_falls_back(self, monkeypatch):
        """Compute handler error triggers fallback to legacy path."""
        monkeypatch.setenv("USE_ONEX_ROUTING_NODES", "true")

        mock_compute = MagicMock()
        mock_compute.compute_routing = AsyncMock(
            side_effect=RuntimeError("Compute node error")
        )
        mock_emitter = MagicMock()
        mock_history = MagicMock()

        mock_router = MagicMock()
        mock_router.registry = {
            "agents": {
                "agent-testing": {
                    "activation_triggers": ["test"],
                    "capabilities": [],
                    "domain_context": "testing",
                    "description": "Test",
                    "definition_path": "/test.yaml",
                }
            }
        }

        with (
            patch(
                "route_via_events_wrapper._get_onex_handlers",
                return_value=(mock_compute, mock_emitter, mock_history),
            ),
            patch("route_via_events_wrapper._get_router", return_value=mock_router),
        ):
            result = route_via_events("test prompt", "corr-123")

        # Should fall through to legacy path and still return a result
        assert result["selected_agent"] is not None
        assert "routing_path" in result

    def test_handlers_unavailable_falls_back(self, monkeypatch):
        """When ONEX handlers can't be created, falls back to legacy."""
        monkeypatch.setenv("USE_ONEX_ROUTING_NODES", "true")

        with patch("route_via_events_wrapper._get_onex_handlers", return_value=None):
            result = route_via_events("test prompt", "corr-123")

        assert result["selected_agent"] is not None
        assert "routing_path" in result

    def test_router_unavailable_falls_back(self, monkeypatch):
        """When AgentRouter is unavailable, ONEX path falls back."""
        monkeypatch.setenv("USE_ONEX_ROUTING_NODES", "true")

        mock_compute = MagicMock()
        mock_emitter = MagicMock()
        mock_history = MagicMock()

        with (
            patch(
                "route_via_events_wrapper._get_onex_handlers",
                return_value=(mock_compute, mock_emitter, mock_history),
            ),
            patch("route_via_events_wrapper._get_router", return_value=None),
        ):
            result = route_via_events("test prompt", "corr-123")

        assert result["selected_agent"] == DEFAULT_AGENT


# ---------------------------------------------------------------------------
# Stats Pre-fetching Tests
# ---------------------------------------------------------------------------


class TestStatsPrefetching:
    """Tests for routing stats pre-fetching and caching."""

    def test_stats_passed_to_compute_request(self, monkeypatch):
        """Pre-fetched stats are passed to the ModelRoutingRequest."""
        monkeypatch.setenv("USE_ONEX_ROUTING_NODES", "true")

        from omniclaude.nodes.node_routing_history_reducer.models import (
            ModelAgentRoutingStats,
        )

        mock_stats = ModelAgentRoutingStats(
            entries=(),
            total_routing_decisions=42,
            snapshot_at=None,
        )

        mock_compute = MagicMock()
        mock_compute.compute_routing = AsyncMock(return_value=_make_routing_result())
        mock_emitter = MagicMock()
        mock_emitter.emit_routing_decision = AsyncMock(
            return_value=_make_emission_result()
        )
        mock_history = MagicMock()

        mock_router = MagicMock()
        mock_router.registry = {
            "agents": {
                "agent-testing": {
                    "activation_triggers": ["test"],
                    "capabilities": [],
                    "domain_context": "testing",
                    "description": "Test",
                    "definition_path": "/test.yaml",
                }
            }
        }

        with (
            patch(
                "route_via_events_wrapper._get_onex_handlers",
                return_value=(mock_compute, mock_emitter, mock_history),
            ),
            patch("route_via_events_wrapper._get_router", return_value=mock_router),
            patch(
                "route_via_events_wrapper._get_cached_stats", return_value=mock_stats
            ),
        ):
            route_via_events("test prompt", str(uuid4()))

        # Verify stats were passed to compute_routing
        call_args = mock_compute.compute_routing.call_args
        request = call_args[0][0] if call_args[0] else call_args[1].get("request")
        assert request.historical_stats is not None
        assert request.historical_stats.total_routing_decisions == 42


# ---------------------------------------------------------------------------
# Agent Definition Conversion Tests
# ---------------------------------------------------------------------------


class TestBuildAgentDefinitions:
    """Tests for _build_agent_definitions helper."""

    def test_converts_registry_to_definitions(self):
        """Converts AgentRouter registry dict to ModelAgentDefinition tuple."""
        from route_via_events_wrapper import _build_agent_definitions

        registry = {
            "agents": {
                "agent-testing": {
                    "activation_triggers": ["test", "testing"],
                    "capabilities": ["run tests", "validate"],
                    "domain_context": "testing",
                    "description": "Test agent",
                    "definition_path": "/test.yaml",
                },
                "agent-debug": {
                    "activation_triggers": ["debug"],
                    "capabilities": ["debugging"],
                    "domain_context": "debugging",
                    "title": "Debug Agent",
                    "definition_path": "/debug.yaml",
                },
            }
        }

        defs = _build_agent_definitions(registry)
        assert len(defs) == 2
        names = {d.name for d in defs}
        assert names == {"agent-testing", "agent-debug"}

    def test_empty_registry_returns_empty(self):
        """Empty registry produces empty tuple."""
        from route_via_events_wrapper import _build_agent_definitions

        assert _build_agent_definitions({"agents": {}}) == ()

    def test_skips_invalid_agents(self):
        """Invalid agent data is skipped without raising."""
        from route_via_events_wrapper import _build_agent_definitions

        registry = {
            "agents": {
                "": {  # Invalid: empty name
                    "activation_triggers": [],
                    "capabilities": [],
                },
                "agent-valid": {
                    "activation_triggers": ["test"],
                    "capabilities": [],
                    "domain_context": "general",
                    "description": "Valid",
                    "definition_path": "/valid.yaml",
                },
            }
        }

        defs = _build_agent_definitions(registry)
        # Only valid agent should be included
        assert len(defs) == 1
        assert defs[0].name == "agent-valid"
