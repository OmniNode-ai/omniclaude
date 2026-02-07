# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""
Integration tests for the ONEX routing path with mocked Kafka.

Ticket: OMN-1928 — [P5] Validation
Parent: OMN-1922 (Extract Agent Routing to ONEX Nodes)

Exercises the full ONEX routing pipeline:
    route_via_events (USE_ONEX_ROUTING_NODES=true)
        -> HandlerRoutingDefault.compute_routing()
        -> HandlerRoutingEmitter.emit_routing_decision()
        -> Result shaping back to wrapper dict

All Kafka interactions are mocked via the session-scoped conftest mock.
The emit daemon is replaced with a test double that captures payloads.

Real bus validation is in test_onex_kafka_real_bus.py, gated behind
KAFKA_INTEGRATION_TESTS=real. These mock tests remain as the CI fast path.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

# --------------------------------------------------------------------------
# Path setup
# --------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).parents[2]
_HOOKS_LIB = _PROJECT_ROOT / "plugins" / "onex" / "hooks" / "lib"
if str(_HOOKS_LIB) not in sys.path:
    sys.path.insert(0, str(_HOOKS_LIB))

from omniclaude.nodes.node_agent_routing_compute.models import (
    ModelConfidenceBreakdown,
    ModelRoutingCandidate,
    ModelRoutingResult,
)
from omniclaude.nodes.node_routing_emission_effect.models import (
    ModelEmissionResult,
)

# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

DEFAULT_AGENT = "polymorphic-agent"


def _make_breakdown(
    total: float = 0.85, explanation: str = "Test match"
) -> ModelConfidenceBreakdown:
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
) -> ModelRoutingResult:
    breakdown = _make_breakdown(
        total=confidence, explanation=f"Match for {selected_agent}"
    )
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
    return ModelEmissionResult(
        success=True,
        correlation_id=cid or uuid4(),
        topics_emitted=("onex.evt.omniclaude.routing-decision.v1",),
        error=None,
        duration_ms=1.5,
    )


def _mock_router_registry() -> MagicMock:
    """Build a mock AgentRouter with a registry containing test agents."""
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
            "agent-debugger": {
                "domain_context": "debugging",
                "description": "Debug agent",
                "title": "Debug Agent",
                "activation_triggers": ["debug", "error"],
                "capabilities": ["debugging"],
                "definition_path": "/debug.yaml",
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
    return mock_router


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_wrapper_singletons():
    """Reset ONEX handler singletons between tests."""
    import route_via_events_wrapper as mod

    orig_compute = mod._compute_handler
    orig_emit = mod._emit_handler
    orig_history = mod._history_handler
    orig_stats = mod._cached_stats
    orig_router = mod._router_instance

    yield

    mod._compute_handler = orig_compute
    mod._emit_handler = orig_emit
    mod._history_handler = orig_history
    mod._cached_stats = orig_stats
    mod._router_instance = orig_router


# --------------------------------------------------------------------------
# Integration: ONEX path with mocked Kafka
# --------------------------------------------------------------------------


class TestOnexKafkaIntegration:
    """Integration tests for the full ONEX routing path.

    TECH DEBT: All Kafka interactions are mocked. Real bus validation
    is required before production rollout. When implementing real-bus
    tests, gate them behind KAFKA_INTEGRATION_TESTS=real and verify
    events appear on onex.evt.omniclaude.routing-decision.v1 within
    a 5-second window.
    """

    @pytest.mark.integration
    def test_onex_path_routes_and_emits(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Full ONEX path: compute + emit + result shaping."""
        monkeypatch.setenv("USE_ONEX_ROUTING_NODES", "true")

        mock_compute = MagicMock()
        mock_compute.compute_routing = AsyncMock(
            return_value=_make_routing_result(
                selected_agent="agent-testing", confidence=0.85
            )
        )

        emitted_payloads: list[dict[str, Any]] = []

        async def capturing_emit(request, correlation_id=None):
            emitted_payloads.append(
                {
                    "agent": request.selected_agent,
                    "confidence": request.confidence,
                    "policy": request.routing_policy,
                }
            )
            return _make_emission_result(correlation_id)

        mock_emitter = MagicMock()
        mock_emitter.emit_routing_decision = AsyncMock(side_effect=capturing_emit)
        mock_history = MagicMock()

        with (
            patch(
                "route_via_events_wrapper._get_onex_handlers",
                return_value=(mock_compute, mock_emitter, mock_history),
            ),
            patch(
                "route_via_events_wrapper._get_router",
                return_value=_mock_router_registry(),
            ),
        ):
            from route_via_events_wrapper import route_via_events

            result = route_via_events(
                "run tests", str(uuid4()), session_id="test-session"
            )

        # Verify routing result
        assert result["selected_agent"] == "agent-testing"
        assert result["confidence"] == 0.85
        assert result["routing_policy"] == "trigger_match"
        assert result["routing_path"] == "local"

        # Verify emission was called
        mock_emitter.emit_routing_decision.assert_called_once()

        # Verify emitted payload structure
        # TECH DEBT: With real Kafka, consume from the topic and validate
        # the event schema matches ModelHookRoutingDecisionPayload.
        assert len(emitted_payloads) == 1
        assert emitted_payloads[0]["agent"] == "agent-testing"
        assert emitted_payloads[0]["confidence"] == 0.85

    @pytest.mark.integration
    def test_onex_emission_failure_is_non_blocking(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Emission failure must not block routing result."""
        monkeypatch.setenv("USE_ONEX_ROUTING_NODES", "true")

        mock_compute = MagicMock()
        mock_compute.compute_routing = AsyncMock(return_value=_make_routing_result())
        mock_emitter = MagicMock()
        mock_emitter.emit_routing_decision = AsyncMock(
            side_effect=RuntimeError("Kafka unavailable")
        )
        mock_history = MagicMock()

        with (
            patch(
                "route_via_events_wrapper._get_onex_handlers",
                return_value=(mock_compute, mock_emitter, mock_history),
            ),
            patch(
                "route_via_events_wrapper._get_router",
                return_value=_mock_router_registry(),
            ),
        ):
            from route_via_events_wrapper import route_via_events

            result = route_via_events("run tests", str(uuid4()))

        # Routing succeeds despite emission failure
        assert result["selected_agent"] == "agent-testing"
        assert result["confidence"] == 0.85

    @pytest.mark.integration
    def test_onex_compute_failure_falls_back_to_legacy(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Compute handler failure triggers graceful fallback."""
        monkeypatch.setenv("USE_ONEX_ROUTING_NODES", "true")

        mock_compute = MagicMock()
        mock_compute.compute_routing = AsyncMock(
            side_effect=RuntimeError("Compute node crashed")
        )
        mock_emitter = MagicMock()
        mock_history = MagicMock()

        with (
            patch(
                "route_via_events_wrapper._get_onex_handlers",
                return_value=(mock_compute, mock_emitter, mock_history),
            ),
            patch(
                "route_via_events_wrapper._get_router",
                return_value=_mock_router_registry(),
            ),
        ):
            from route_via_events_wrapper import route_via_events

            result = route_via_events("run tests", str(uuid4()))

        # Should fall back to legacy path and still produce a result
        assert result["selected_agent"] is not None
        assert "routing_path" in result
        assert "routing_policy" in result

    @pytest.mark.integration
    def test_onex_result_has_all_wrapper_fields(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """ONEX result must contain all fields the wrapper promises."""
        monkeypatch.setenv("USE_ONEX_ROUTING_NODES", "true")

        mock_compute = MagicMock()
        mock_compute.compute_routing = AsyncMock(return_value=_make_routing_result())
        mock_emitter = MagicMock()
        mock_emitter.emit_routing_decision = AsyncMock(
            return_value=_make_emission_result()
        )
        mock_history = MagicMock()

        with (
            patch(
                "route_via_events_wrapper._get_onex_handlers",
                return_value=(mock_compute, mock_emitter, mock_history),
            ),
            patch(
                "route_via_events_wrapper._get_router",
                return_value=_mock_router_registry(),
            ),
        ):
            from route_via_events_wrapper import route_via_events

            result = route_via_events("run tests", str(uuid4()))

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
        missing = required_fields - set(result.keys())
        assert not missing, f"Missing fields in ONEX result: {missing}"


# --------------------------------------------------------------------------
# Feature flag toggle tests
# --------------------------------------------------------------------------


class TestFeatureFlagToggle:
    """Verify that USE_ONEX_ROUTING_NODES correctly toggles routing paths.

    TECH DEBT: With real Kafka, verify that:
    1. Flag ON: events emitted to Kafka topic
    2. Flag OFF: no events emitted
    3. Flag toggle mid-session: clean switch without stale state
    """

    @pytest.mark.integration
    def test_flag_off_uses_legacy_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When flag is off, legacy path is used regardless of ONEX availability."""
        monkeypatch.delenv("USE_ONEX_ROUTING_NODES", raising=False)

        from route_via_events_wrapper import route_via_events

        result = route_via_events("debug this error", str(uuid4()))

        assert result["selected_agent"] is not None
        assert result["routing_path"] in {"event", "local", "hybrid"}
        # Legacy path always sets event_attempted=False
        assert result["event_attempted"] is False

    @pytest.mark.integration
    def test_flag_on_attempts_onex_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When flag is on and handlers available, ONEX path is used."""
        monkeypatch.setenv("USE_ONEX_ROUTING_NODES", "true")

        mock_compute = MagicMock()
        mock_compute.compute_routing = AsyncMock(
            return_value=_make_routing_result(
                selected_agent="agent-debugger", confidence=0.90
            )
        )
        mock_emitter = MagicMock()
        mock_emitter.emit_routing_decision = AsyncMock(
            return_value=_make_emission_result()
        )
        mock_history = MagicMock()

        with (
            patch(
                "route_via_events_wrapper._get_onex_handlers",
                return_value=(mock_compute, mock_emitter, mock_history),
            ),
            patch(
                "route_via_events_wrapper._get_router",
                return_value=_mock_router_registry(),
            ),
        ):
            from route_via_events_wrapper import route_via_events

            result = route_via_events("debug this error", str(uuid4()))

        assert result["selected_agent"] == "agent-debugger"
        assert result["confidence"] == 0.90
        mock_compute.compute_routing.assert_called_once()

    @pytest.mark.integration
    def test_flag_on_but_handlers_unavailable_falls_back(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When flag is on but handlers fail to init, falls back to legacy."""
        monkeypatch.setenv("USE_ONEX_ROUTING_NODES", "true")

        with patch("route_via_events_wrapper._get_onex_handlers", return_value=None):
            from route_via_events_wrapper import route_via_events

            result = route_via_events("debug this error", str(uuid4()))

        assert result["selected_agent"] is not None
        assert "routing_path" in result


# --------------------------------------------------------------------------
# Emission payload structure validation
# --------------------------------------------------------------------------


class TestEmissionPayloadStructure:
    """Validate that emission payloads conform to the expected schema.

    TECH DEBT: With real Kafka, consume from
    onex.evt.omniclaude.routing-decision.v1 and validate the full event
    envelope (event_type, correlation_id, timestamp, payload schema).
    """

    @pytest.mark.integration
    def test_emission_request_has_required_fields(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """ModelEmissionRequest must be populated with all required fields."""
        monkeypatch.setenv("USE_ONEX_ROUTING_NODES", "true")

        captured_requests: list[Any] = []

        mock_compute = MagicMock()
        mock_compute.compute_routing = AsyncMock(return_value=_make_routing_result())

        async def capturing_emit(request, correlation_id=None):
            captured_requests.append(request)
            return _make_emission_result(correlation_id)

        mock_emitter = MagicMock()
        mock_emitter.emit_routing_decision = AsyncMock(side_effect=capturing_emit)
        mock_history = MagicMock()

        with (
            patch(
                "route_via_events_wrapper._get_onex_handlers",
                return_value=(mock_compute, mock_emitter, mock_history),
            ),
            patch(
                "route_via_events_wrapper._get_router",
                return_value=_mock_router_registry(),
            ),
        ):
            from route_via_events_wrapper import route_via_events

            route_via_events("run tests", str(uuid4()), session_id="test-session")

        assert len(captured_requests) == 1
        req = captured_requests[0]

        # Validate all required fields of ModelEmissionRequest
        assert req.selected_agent == "agent-testing"
        assert req.confidence == 0.85
        assert req.routing_policy == "trigger_match"
        assert req.routing_path == "local"
        assert req.session_id == "test-session"
        assert req.prompt_length > 0
        assert req.prompt_preview  # Not empty
        assert req.emitted_at is not None
        assert isinstance(req.correlation_id, UUID)

    @pytest.mark.integration
    def test_emission_result_reports_topics(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Emission result must list the topics events were emitted to."""
        monkeypatch.setenv("USE_ONEX_ROUTING_NODES", "true")

        mock_compute = MagicMock()
        mock_compute.compute_routing = AsyncMock(return_value=_make_routing_result())

        emission_result = _make_emission_result()
        mock_emitter = MagicMock()
        mock_emitter.emit_routing_decision = AsyncMock(return_value=emission_result)
        mock_history = MagicMock()

        with (
            patch(
                "route_via_events_wrapper._get_onex_handlers",
                return_value=(mock_compute, mock_emitter, mock_history),
            ),
            patch(
                "route_via_events_wrapper._get_router",
                return_value=_mock_router_registry(),
            ),
        ):
            from route_via_events_wrapper import route_via_events

            route_via_events("run tests", str(uuid4()))

        assert emission_result.success is True
        assert (
            "onex.evt.omniclaude.routing-decision.v1" in emission_result.topics_emitted
        )
