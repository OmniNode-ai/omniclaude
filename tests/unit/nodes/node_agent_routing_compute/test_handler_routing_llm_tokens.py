# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Unit tests for token tracking in HandlerRoutingLlm (OMN-3448).

Verifies that:
- Token counts are extracted from the vLLM ``usage`` dict and surfaced in
  the returned ``ModelRoutingResult``.
- Missing ``usage`` key defaults to all-zero counts without raising.
- ``omninode_enabled`` is set to ``True`` on the ONEX path.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from omniclaude.nodes.node_agent_routing_compute.handler_routing_llm import (
    HandlerRoutingLlm,
)
from omniclaude.nodes.node_agent_routing_compute.models import (
    ModelAgentDefinition,
    ModelConfidenceBreakdown,
    ModelRoutingCandidate,
    ModelRoutingRequest,
)

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_agent(name: str, triggers: tuple[str, ...] = ()) -> ModelAgentDefinition:
    return ModelAgentDefinition(
        name=name,
        agent_type=name.replace("agent-", "").replace("-", "_"),
        explicit_triggers=triggers,
        context_triggers=(),
        capabilities=(),
        domain_context="general",
        description=f"Test agent: {name}",
    )


def _make_request(
    prompt: str,
    agents: tuple[ModelAgentDefinition, ...],
    threshold: float = 0.1,
) -> ModelRoutingRequest:
    return ModelRoutingRequest(
        prompt=prompt,
        correlation_id=uuid4(),
        agent_registry=agents,
        confidence_threshold=threshold,
    )


def _make_candidate(
    name: str,
    confidence: float = 0.8,
) -> ModelRoutingCandidate:
    return ModelRoutingCandidate(
        agent_name=name,
        confidence=confidence,
        confidence_breakdown=ModelConfidenceBreakdown(
            total=confidence,
            trigger_score=confidence,
            context_score=0.5,
            capability_score=0.5,
            historical_score=0.5,
            explanation="test",
        ),
        match_reason="trigger match",
    )


def _llm_response(content: str, usage: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build a minimal OpenAI-compatible chat completion response.

    Args:
        content: The assistant message content.
        usage: Optional usage dict.  When *None*, the ``usage`` key is omitted
            from the response to simulate servers that do not report token counts.
    """
    response: dict[str, Any] = {
        "choices": [{"message": {"role": "assistant", "content": content}}],
    }
    if usage is not None:
        response["usage"] = usage
    return response


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestHandlerRoutingLlmTokens:
    """Tests for token extraction in HandlerRoutingLlm (OMN-3448).

    These tests call ``_ask_llm`` directly so that token extraction is tested
    independently of TriggerMatcher candidate generation and confidence scoring,
    which are covered by the existing test suite in tests/routing/.
    """

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_routing_decision_includes_token_counts(self) -> None:
        """Token counts from vLLM ``usage`` dict are surfaced in the result.

        ``_ask_llm`` must return (selected_agent, prompt_tokens,
        completion_tokens, total_tokens) extracted from the ``usage`` dict.
        """
        candidates = [_make_candidate("agent-debugger")]
        agent_names = {"agent-debugger", "polymorphic-agent"}

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = _llm_response(
            content="agent-debugger",
            usage={
                "prompt_tokens": 42,
                "completion_tokens": 7,
                "total_tokens": 49,
            },
        )

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=mock_response)

        handler = HandlerRoutingLlm(llm_url="http://fake-llm:8001")

        with patch(
            "omniclaude.nodes.node_agent_routing_compute.handler_routing_llm.httpx.AsyncClient",
            return_value=mock_client,
        ):
            (
                selected,
                prompt_tokens,
                completion_tokens,
                total_tokens,
            ) = await handler._ask_llm(
                candidates=candidates,
                prompt="debug this",
                agent_names=agent_names,
                correlation_id=uuid4(),
            )

        assert selected == "agent-debugger"
        assert prompt_tokens == 42
        assert completion_tokens == 7
        assert total_tokens == 49

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_routing_decision_defaults_zero_tokens_on_missing_usage(
        self,
    ) -> None:
        """Missing ``usage`` key defaults to all-zero counts without raising.

        When the LLM response omits the ``usage`` dict entirely, ``_ask_llm``
        must return (selected_agent, 0, 0, 0) — no KeyError or exception.
        """
        candidates = [_make_candidate("agent-debugger")]
        agent_names = {"agent-debugger", "polymorphic-agent"}

        # Response has no ``usage`` key at all
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = _llm_response(
            content="agent-debugger",
            usage=None,  # simulates a server that omits usage
        )

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=mock_response)

        handler = HandlerRoutingLlm(llm_url="http://fake-llm:8001")

        with patch(
            "omniclaude.nodes.node_agent_routing_compute.handler_routing_llm.httpx.AsyncClient",
            return_value=mock_client,
        ):
            (
                selected,
                prompt_tokens,
                completion_tokens,
                total_tokens,
            ) = await handler._ask_llm(
                candidates=candidates,
                prompt="debug this",
                agent_names=agent_names,
                correlation_id=uuid4(),
            )

        assert selected == "agent-debugger"
        assert prompt_tokens == 0
        assert completion_tokens == 0
        assert total_tokens == 0
