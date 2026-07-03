# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Unit tests for HandlerAgentRouter (OMN-11599).

Verifies that:
- HandlerAgentRouter.route() returns routed=True with recommendations on success
- HandlerAgentRouter.route() returns routed=False (empty) when AgentRouter returns []
- HandlerAgentRouter.route() returns routed=False when AgentRouter init fails
- HandlerAgentRouter.route() returns routed=False when AgentRouter.route() raises
- _convert_recommendation() maps AgentRecommendation fields to typed model correctly
- _safe_float() clamps values to [0.0, 1.0]
- handler_key is "default"
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock

import pytest

from omniclaude.nodes.node_agent_router.handlers.handler_agent_router import (
    HandlerAgentRouter,
    _safe_float,
)
from omniclaude.nodes.node_agent_router.models import (
    ModelAgentRecommendation,
    ModelAgentRouterRequest,
    ModelAgentRouterResult,
)

# ---------------------------------------------------------------------------
# Minimal stubs matching AgentRecommendation / ConfidenceScore dataclass shape
# ---------------------------------------------------------------------------


@dataclass
class _StubConfidence:
    total: float = 0.85
    trigger_score: float = 0.9
    context_score: float = 0.8
    capability_score: float = 0.75
    historical_score: float = 0.7
    explanation: str = "trigger matched"


@dataclass
class _StubRecommendation:
    agent_name: str = "agent-debug"
    agent_title: str = "Debug Specialist"
    confidence: _StubConfidence = None  # type: ignore[assignment]
    reason: str = "debug trigger matched"
    definition_path: str = "/fake/agent-debug.yaml"

    def __post_init__(self) -> None:
        if self.confidence is None:
            self.confidence = _StubConfidence()


def _make_request(
    user_request: str = "debug this error",
    max_recommendations: int = 3,
    context: dict[str, Any] | None = None,
) -> ModelAgentRouterRequest:
    return ModelAgentRouterRequest(
        user_request=user_request,
        max_recommendations=max_recommendations,
        context=context,
    )


# ---------------------------------------------------------------------------
# Tests: handler_key
# ---------------------------------------------------------------------------


class TestHandlerKey:
    def test_handler_key_is_default(self) -> None:
        handler = HandlerAgentRouter()
        assert handler.handler_key == "default"


# ---------------------------------------------------------------------------
# Tests: route() — success path
# ---------------------------------------------------------------------------


class TestRouteSuccess:
    @pytest.mark.unit
    async def test_route_returns_routed_true_when_recommendations(self) -> None:
        handler = HandlerAgentRouter()
        rec = _StubRecommendation()
        mock_router = MagicMock()
        mock_router.route.return_value = [rec]
        handler._router = mock_router

        result = await handler.route(_make_request())

        assert isinstance(result, ModelAgentRouterResult)
        assert result.routed is True
        assert len(result.recommendations) == 1

    @pytest.mark.unit
    async def test_route_recommendation_fields_mapped_correctly(self) -> None:
        handler = HandlerAgentRouter()
        rec = _StubRecommendation(
            agent_name="agent-api",
            agent_title="API Architect",
            confidence=_StubConfidence(
                total=0.9,
                trigger_score=0.95,
                context_score=0.85,
                capability_score=0.8,
                historical_score=0.75,
                explanation="api design trigger",
            ),
            reason="api trigger",
            definition_path="/fake/agent-api.yaml",
        )
        mock_router = MagicMock()
        mock_router.route.return_value = [rec]
        handler._router = mock_router

        result = await handler.route(_make_request("design an api"))

        r = result.recommendations[0]
        assert isinstance(r, ModelAgentRecommendation)
        assert r.agent_name == "agent-api"
        assert r.agent_title == "API Architect"
        assert r.confidence == pytest.approx(0.9)
        assert r.trigger_score == pytest.approx(0.95)
        assert r.context_score == pytest.approx(0.85)
        assert r.capability_score == pytest.approx(0.8)
        assert r.historical_score == pytest.approx(0.75)
        assert r.confidence_explanation == "api design trigger"
        assert r.reason == "api trigger"
        assert r.definition_path == "/fake/agent-api.yaml"

    @pytest.mark.unit
    async def test_route_passes_context_to_router(self) -> None:
        handler = HandlerAgentRouter()
        mock_router = MagicMock()
        mock_router.route.return_value = []
        handler._router = mock_router

        ctx = {"domain": "testing", "session_id": "abc123"}
        await handler.route(_make_request(context=ctx))

        call_kwargs = mock_router.route.call_args
        assert call_kwargs.kwargs["context"] == ctx

    @pytest.mark.unit
    async def test_route_passes_max_recommendations_to_router(self) -> None:
        handler = HandlerAgentRouter()
        mock_router = MagicMock()
        mock_router.route.return_value = []
        handler._router = mock_router

        await handler.route(_make_request(max_recommendations=7))

        call_kwargs = mock_router.route.call_args
        assert call_kwargs.kwargs["max_recommendations"] == 7

    @pytest.mark.unit
    async def test_route_multiple_recommendations_preserved_order(self) -> None:
        handler = HandlerAgentRouter()
        recs = [
            _StubRecommendation(
                agent_name="agent-a", confidence=_StubConfidence(total=0.9)
            ),
            _StubRecommendation(
                agent_name="agent-b", confidence=_StubConfidence(total=0.7)
            ),
            _StubRecommendation(
                agent_name="agent-c", confidence=_StubConfidence(total=0.5)
            ),
        ]
        mock_router = MagicMock()
        mock_router.route.return_value = recs
        handler._router = mock_router

        result = await handler.route(_make_request())

        assert len(result.recommendations) == 3
        assert result.recommendations[0].agent_name == "agent-a"
        assert result.recommendations[1].agent_name == "agent-b"
        assert result.recommendations[2].agent_name == "agent-c"


# ---------------------------------------------------------------------------
# Tests: route() — empty result path
# ---------------------------------------------------------------------------


class TestRouteEmpty:
    @pytest.mark.unit
    async def test_route_returns_routed_false_when_empty_list(self) -> None:
        handler = HandlerAgentRouter()
        mock_router = MagicMock()
        mock_router.route.return_value = []
        handler._router = mock_router

        result = await handler.route(_make_request())

        assert result.routed is False
        assert result.recommendations == ()


# ---------------------------------------------------------------------------
# Tests: route() — failure paths
# ---------------------------------------------------------------------------


class TestRouteFailure:
    @pytest.mark.unit
    async def test_route_returns_empty_when_init_failed(self) -> None:
        handler = HandlerAgentRouter()
        handler._init_failed = True  # simulate previous init failure

        result = await handler.route(_make_request())

        assert result.routed is False
        assert result.recommendations == ()

    @pytest.mark.unit
    async def test_route_returns_empty_when_router_raises(self) -> None:
        handler = HandlerAgentRouter()
        mock_router = MagicMock()
        mock_router.route.side_effect = RuntimeError("registry broken")
        handler._router = mock_router

        result = await handler.route(_make_request())

        assert result.routed is False
        assert result.recommendations == ()

    @pytest.mark.unit
    async def test_route_returns_empty_when_router_unavailable(self) -> None:
        handler = HandlerAgentRouter()
        # _router is None and _init_failed is True (no real init)
        handler._init_failed = True

        result = await handler.route(_make_request())

        assert result.routed is False


# ---------------------------------------------------------------------------
# Tests: _safe_float
# ---------------------------------------------------------------------------


class TestSafeFloat:
    @pytest.mark.unit
    def test_valid_float_passthrough(self) -> None:
        assert _safe_float(0.75) == pytest.approx(0.75)

    @pytest.mark.unit
    def test_clamps_above_one(self) -> None:
        assert _safe_float(1.5) == pytest.approx(1.0)

    @pytest.mark.unit
    def test_clamps_below_zero(self) -> None:
        assert _safe_float(-0.1) == pytest.approx(0.0)

    @pytest.mark.unit
    def test_none_returns_zero(self) -> None:
        assert _safe_float(None) == pytest.approx(0.0)

    @pytest.mark.unit
    def test_string_returns_zero(self) -> None:
        assert _safe_float("not_a_float") == pytest.approx(0.0)

    @pytest.mark.unit
    def test_integer_input(self) -> None:
        assert _safe_float(1) == pytest.approx(1.0)
        assert _safe_float(0) == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Tests: protocol conformance
# ---------------------------------------------------------------------------


class TestProtocolConformance:
    @pytest.mark.unit
    def test_handler_satisfies_protocol(self) -> None:
        from omniclaude.nodes.node_agent_router.protocols import ProtocolAgentRouter

        handler = HandlerAgentRouter()
        assert isinstance(handler, ProtocolAgentRouter)
