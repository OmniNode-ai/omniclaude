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
from tests.support.fake_agent_router import FakeAgentRouter

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
        fake_router = FakeAgentRouter()
        fake_router.recommendations = [rec]
        handler._router = fake_router

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
        fake_router = FakeAgentRouter()
        fake_router.recommendations = [rec]
        handler._router = fake_router

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
        fake_router = FakeAgentRouter()
        fake_router.recommendations = []
        handler._router = fake_router

        ctx = {"domain": "testing", "session_id": "abc123"}
        await handler.route(_make_request(context=ctx))

        assert fake_router.last_route_call["context"] == ctx

    @pytest.mark.unit
    async def test_route_passes_max_recommendations_to_router(self) -> None:
        handler = HandlerAgentRouter()
        fake_router = FakeAgentRouter()
        fake_router.recommendations = []
        handler._router = fake_router

        await handler.route(_make_request(max_recommendations=7))

        assert fake_router.last_route_call["max_recommendations"] == 7

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
        fake_router = FakeAgentRouter()
        fake_router.recommendations = recs
        handler._router = fake_router

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
        fake_router = FakeAgentRouter()
        fake_router.recommendations = []
        handler._router = fake_router

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
        fake_router = FakeAgentRouter()
        fake_router.route_exc = RuntimeError("registry broken")
        handler._router = fake_router

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


def _canonical_requests() -> list[ModelAgentRouterRequest]:
    """The replay corpus shared by parity execution and the adequacy recorder."""
    from uuid import UUID

    return [
        ModelAgentRouterRequest(
            user_request=case,
            context=context,
            max_recommendations=7,
            correlation_id=UUID("00000000-0000-0000-0000-000000000001"),
        )
        for case in ["recommendations", "empty", "raises", "unavailable"]
        for context in [None, {"domain": "testing"}]
    ]


class TestCanonicalHandle:
    @pytest.mark.unit
    @pytest.mark.parametrize(
        "request_model",
        _canonical_requests(),
        ids=[
            f"{r.user_request}-{'with' if r.context else 'without'}-context"
            for r in _canonical_requests()
        ],
    )
    async def test_handle_matches_route(
        self, request_model: ModelAgentRouterRequest
    ) -> None:
        """The runtime entrypoint keeps legacy results and forwarding behavior."""
        import importlib
        from pathlib import Path
        from typing import get_type_hints

        import yaml

        contract_path = (
            Path(__file__).resolve().parents[4]
            / "src/omniclaude/nodes/node_agent_router/contract.yaml"
        )
        contract = yaml.safe_load(contract_path.read_text())
        binding = contract["handler_routing"]["handlers"][0]["handler"]
        handler_class = getattr(
            importlib.import_module(binding["module"]), binding["name"]
        )
        handler = handler_class()
        assert handler_class is HandlerAgentRouter
        assert callable(getattr(handler, "handle", None)), "canonical handle is missing"
        annotations = get_type_hints(handler.handle)
        assert annotations["request"] is ModelAgentRouterRequest
        assert annotations["return"] is ModelAgentRouterResult
        case = request_model.user_request
        fake = FakeAgentRouter()
        if case == "recommendations":
            fake.recommendations = [
                _StubRecommendation(agent_name="agent-a"),
                _StubRecommendation(agent_name="agent-b"),
            ]
        elif case == "raises":
            fake.route_exc = RuntimeError("registry broken")
        if case == "unavailable":
            handler._init_failed = True
        else:
            handler._router = fake

        result = await handler.handle(request_model)
        legacy = await handler.route(
            request_model, correlation_id=request_model.correlation_id
        )

        assert isinstance(result, ModelAgentRouterResult)
        assert result == legacy
        assert result.routed is (case == "recommendations")
        assert tuple(r.agent_name for r in result.recommendations) == (
            ("agent-a", "agent-b") if case == "recommendations" else ()
        )
        if case != "unavailable":
            assert fake.route_call_count == 2
            assert (
                fake.route_calls
                == [
                    {
                        "user_request": request_model.user_request,
                        "context": request_model.context or {},
                        "max_recommendations": request_model.max_recommendations,
                    }
                ]
                * 2
            )
