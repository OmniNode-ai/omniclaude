# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Unit tests for HandlerRoutingLlm.

Tests prompt construction, LLM response parsing, fallback behaviour,
and the full compute_routing() flow using a mocked HTTP client.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from omniclaude.nodes.node_agent_routing_compute.handler_routing_llm import (
    _ROUTING_PROMPT_VERSION,
    HandlerRoutingLlm,
    _build_routing_prompt,
    _parse_agent_from_response,
)
from omniclaude.nodes.node_agent_routing_compute.models import (
    ModelAgentDefinition,
    ModelConfidenceBreakdown,
    ModelRoutingCandidate,
    ModelRoutingRequest,
)

# ---------------------------------------------------------------------------
# Helpers shared by multiple test classes
# ---------------------------------------------------------------------------


def _make_agent(
    name: str,
    triggers: tuple[str, ...] = (),
    capabilities: tuple[str, ...] = (),
    domain: str = "general",
    context_triggers: tuple[str, ...] = (),
    description: str = "",
) -> ModelAgentDefinition:
    return ModelAgentDefinition(
        name=name,
        agent_type=name.replace("agent-", "").replace("-", "_"),
        explicit_triggers=triggers,
        context_triggers=context_triggers,
        capabilities=capabilities,
        domain_context=domain,
        description=description,
    )


def _make_request(
    prompt: str,
    agents: tuple[ModelAgentDefinition, ...],
    threshold: float = 0.5,
) -> ModelRoutingRequest:
    return ModelRoutingRequest(
        prompt=prompt,
        correlation_id=uuid4(),
        agent_registry=agents,
        confidence_threshold=threshold,
    )


def _make_candidate(
    name: str,
    confidence: float = 0.7,
    reason: str = "trigger match",
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
        match_reason=reason,
    )


def _make_llm_response(content: str) -> dict[str, Any]:
    """Build a minimal OpenAI-compatible chat completion response."""
    return {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": content,
                }
            }
        ]
    }


# ---------------------------------------------------------------------------
# Tests for _build_routing_prompt
# ---------------------------------------------------------------------------


class TestBuildRoutingPrompt:
    """Tests for the _build_routing_prompt() helper."""

    @pytest.mark.unit
    def test_contains_user_prompt(self) -> None:
        candidates = [_make_candidate("agent-debugger")]
        prompt = _build_routing_prompt(candidates, "fix this bug")
        assert "fix this bug" in prompt

    @pytest.mark.unit
    def test_contains_candidate_name(self) -> None:
        candidates = [
            _make_candidate("agent-api-architect"),
            _make_candidate("agent-debugger"),
        ]
        result = _build_routing_prompt(candidates, "some request")
        assert "agent-api-architect" in result
        assert "agent-debugger" in result

    @pytest.mark.unit
    def test_contains_match_reason(self) -> None:
        candidates = [_make_candidate("agent-debugger", reason="matched debug trigger")]
        result = _build_routing_prompt(candidates, "help me")
        assert "matched debug trigger" in result

    @pytest.mark.unit
    def test_user_prompt_truncated_at_500_chars(self) -> None:
        long_prompt = "x" * 1000
        result = _build_routing_prompt([_make_candidate("agent-test")], long_prompt)
        assert "x" * 500 in result
        assert "x" * 501 not in result

    @pytest.mark.unit
    def test_instructs_single_name_response(self) -> None:
        candidates = [_make_candidate("agent-debugger")]
        result = _build_routing_prompt(candidates, "test")
        assert "ONLY the agent name" in result

    @pytest.mark.unit
    def test_empty_candidates_does_not_raise(self) -> None:
        result = _build_routing_prompt([], "test prompt")
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# Tests for _parse_agent_from_response
# ---------------------------------------------------------------------------


class TestParseAgentFromResponse:
    """Tests for the _parse_agent_from_response() helper."""

    @pytest.mark.unit
    def test_exact_match(self) -> None:
        known = {"agent-debugger", "agent-api-architect"}
        result = _parse_agent_from_response("agent-debugger", known)
        assert result == "agent-debugger"

    @pytest.mark.unit
    def test_exact_match_with_trailing_whitespace(self) -> None:
        known = {"agent-debugger"}
        result = _parse_agent_from_response("  agent-debugger  ", known)
        assert result == "agent-debugger"

    @pytest.mark.unit
    def test_substring_match_with_punctuation(self) -> None:
        known = {"agent-debugger"}
        result = _parse_agent_from_response("agent-debugger.", known)
        assert result == "agent-debugger"

    @pytest.mark.unit
    def test_substring_match_in_sentence(self) -> None:
        known = {"agent-debugger"}
        result = _parse_agent_from_response(
            "The best choice is agent-debugger for this task.", known
        )
        assert result == "agent-debugger"

    @pytest.mark.unit
    def test_case_insensitive(self) -> None:
        known = {"agent-debugger"}
        result = _parse_agent_from_response("AGENT-DEBUGGER", known)
        assert result == "agent-debugger"

    @pytest.mark.unit
    def test_no_match_returns_none(self) -> None:
        known = {"agent-debugger", "agent-api-architect"}
        result = _parse_agent_from_response("agent-nonexistent", known)
        assert result is None

    @pytest.mark.unit
    def test_empty_response_returns_none(self) -> None:
        known = {"agent-debugger"}
        result = _parse_agent_from_response("", known)
        assert result is None

    @pytest.mark.unit
    def test_deterministic_on_multiple_matches(self) -> None:
        """When multiple agents appear in the response, the stable sort ensures determinism.

        Both names are the same length (9 chars), so the primary sort key (-len)
        is equal. The secondary sort key (alphabetical ascending) breaks the tie:
        'agent-aaa' < 'agent-zzz', so 'agent-aaa' is iterated first and returned.
        """
        known = {"agent-aaa", "agent-zzz"}
        # Both names appear in the response; length tie-broken alphabetically,
        # so 'agent-aaa' < 'agent-zzz' and 'agent-aaa' wins.
        result = _parse_agent_from_response("agent-aaa agent-zzz", known)
        assert result == "agent-aaa"


# ---------------------------------------------------------------------------
# Tests for HandlerRoutingLlm
# ---------------------------------------------------------------------------


class TestHandlerRoutingLlm:
    """Tests for HandlerRoutingLlm.compute_routing()."""

    @pytest.fixture
    def handler(self) -> HandlerRoutingLlm:
        return HandlerRoutingLlm(
            llm_url="http://localhost:8200",
            model_name="Qwen2.5-14B",
            timeout=4.0,
        )

    # -- handler_key --

    @pytest.mark.unit
    def test_handler_key_is_llm(self, handler: HandlerRoutingLlm) -> None:
        assert handler.handler_key == "llm"

    # -- explicit agent request (no LLM call needed) --

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_explicit_agent_request_bypasses_llm(
        self, handler: HandlerRoutingLlm
    ) -> None:
        agents = (
            _make_agent("agent-debugger", triggers=("debug",)),
            _make_agent("polymorphic-agent", triggers=("poly",)),
        )
        request = _make_request("use agent-debugger", agents)

        with patch.object(handler, "_ask_llm", new_callable=AsyncMock) as mock_llm:
            result = await handler.compute_routing(request)

        mock_llm.assert_not_called()
        assert result.selected_agent == "agent-debugger"
        assert result.routing_policy == "explicit_request"
        assert result.confidence == 1.0

    # -- no trigger candidates -> fallback, no LLM call --

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_no_candidates_returns_fallback_without_llm(
        self, handler: HandlerRoutingLlm
    ) -> None:
        """When no triggers match, fall back without calling the LLM."""
        agents = (
            _make_agent("agent-api-architect", triggers=("api design",)),
            _make_agent("polymorphic-agent", triggers=("poly",)),
        )
        request = _make_request(
            "write me a haiku about autumn leaves", agents, threshold=0.99
        )

        with patch.object(handler, "_ask_llm", new_callable=AsyncMock) as mock_llm:
            result = await handler.compute_routing(request)

        mock_llm.assert_not_called()
        assert result.routing_policy == "fallback_default"
        assert result.selected_agent == "polymorphic-agent"

    # -- successful LLM call --

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_llm_selection_returned(self, handler: HandlerRoutingLlm) -> None:
        """LLM picks a valid agent from candidates."""
        agents = (
            _make_agent("agent-debugger", triggers=("debug", "troubleshoot")),
            _make_agent("agent-api-architect", triggers=("api design",)),
            _make_agent("polymorphic-agent", triggers=("poly",)),
        )
        request = _make_request("I need to debug this error", agents)

        with patch.object(
            handler,
            "_ask_llm",
            new_callable=AsyncMock,
            return_value="agent-debugger",
        ):
            result = await handler.compute_routing(request)

        assert result.selected_agent == "agent-debugger"
        assert result.routing_policy == "trigger_match"
        assert result.routing_path == "local"
        assert result.fallback_reason is None

    # -- prompt version annotation on winning candidate --

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_winning_candidate_annotated_with_prompt_version(
        self, handler: HandlerRoutingLlm
    ) -> None:
        agents = (
            _make_agent("agent-debugger", triggers=("debug", "troubleshoot")),
            _make_agent("polymorphic-agent", triggers=("poly",)),
        )
        request = _make_request("help me debug this", agents)

        with patch.object(
            handler,
            "_ask_llm",
            new_callable=AsyncMock,
            return_value="agent-debugger",
        ):
            result = await handler.compute_routing(request)

        winning_candidate = next(
            c for c in result.candidates if c.agent_name == "agent-debugger"
        )
        assert f"prompt_v{_ROUTING_PROMPT_VERSION}" in winning_candidate.match_reason
        assert "llm_selected" in winning_candidate.match_reason

    # -- LLM returns None -> fall back to top trigger match --

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_llm_none_uses_top_trigger_candidate(
        self, handler: HandlerRoutingLlm
    ) -> None:
        agents = (
            _make_agent("agent-debugger", triggers=("debug", "troubleshoot")),
            _make_agent("polymorphic-agent", triggers=("poly",)),
        )
        request = _make_request("debug this issue", agents)

        with patch.object(
            handler, "_ask_llm", new_callable=AsyncMock, return_value=None
        ):
            result = await handler.compute_routing(request)

        assert result.selected_agent == "agent-debugger"
        assert result.routing_policy == "trigger_match"
        assert result.fallback_reason is not None
        assert "LLM" in result.fallback_reason

    # -- httpx connection error -> returns None (graceful degradation) --

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_httpx_connect_error_returns_none(
        self, handler: HandlerRoutingLlm
    ) -> None:
        """When the LLM endpoint is unreachable, _ask_llm returns None gracefully."""
        import httpx

        candidates = [_make_candidate("agent-debugger")]
        agent_names = {"agent-debugger", "polymorphic-agent"}

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(
            side_effect=httpx.ConnectError("connection refused")
        )

        with patch(
            "omniclaude.nodes.node_agent_routing_compute.handler_routing_llm.httpx.AsyncClient",
            return_value=mock_client,
        ):
            result = await handler._ask_llm(
                candidates=candidates,
                prompt="debug this",
                agent_names=agent_names,
                correlation_id=uuid4(),
            )

        assert result is None

    # -- HTTP timeout -> returns None (graceful degradation) --

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_llm_timeout_returns_none(self, handler: HandlerRoutingLlm) -> None:
        import httpx

        candidates = [_make_candidate("agent-debugger")]
        agent_names = {"agent-debugger", "polymorphic-agent"}

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(side_effect=httpx.TimeoutException("timed out"))

        with patch(
            "omniclaude.nodes.node_agent_routing_compute.handler_routing_llm.httpx.AsyncClient",
            return_value=mock_client,
        ):
            result = await handler._ask_llm(
                candidates=candidates,
                prompt="debug this",
                agent_names=agent_names,
                correlation_id=uuid4(),
            )

        assert result is None

    # -- HTTP error -> returns None --

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_llm_http_error_returns_none(
        self, handler: HandlerRoutingLlm
    ) -> None:
        import httpx

        candidates = [_make_candidate("agent-debugger")]
        agent_names = {"agent-debugger"}

        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "500 Server Error",
            request=MagicMock(),
            response=MagicMock(status_code=500),
        )

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch(
            "omniclaude.nodes.node_agent_routing_compute.handler_routing_llm.httpx.AsyncClient",
            return_value=mock_client,
        ):
            result = await handler._ask_llm(
                candidates=candidates,
                prompt="debug this",
                agent_names=agent_names,
                correlation_id=uuid4(),
            )

        assert result is None

    # -- LLM returns unrecognised agent name -> returns None --

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_llm_unrecognised_name_returns_none(
        self, handler: HandlerRoutingLlm
    ) -> None:
        candidates = [_make_candidate("agent-debugger")]
        agent_names = {"agent-debugger"}

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json = MagicMock(
            return_value=_make_llm_response("agent-nonexistent-xyz")
        )

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch(
            "omniclaude.nodes.node_agent_routing_compute.handler_routing_llm.httpx.AsyncClient",
            return_value=mock_client,
        ):
            result = await handler._ask_llm(
                candidates=candidates,
                prompt="debug this",
                agent_names=agent_names,
                correlation_id=uuid4(),
            )

        assert result is None

    # -- successful _ask_llm parsing a valid response --

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_ask_llm_parses_valid_response(
        self, handler: HandlerRoutingLlm
    ) -> None:
        candidates = [_make_candidate("agent-debugger")]
        agent_names = {"agent-debugger", "agent-api-architect"}

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json = MagicMock(
            return_value=_make_llm_response("agent-debugger")
        )

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch(
            "omniclaude.nodes.node_agent_routing_compute.handler_routing_llm.httpx.AsyncClient",
            return_value=mock_client,
        ):
            result = await handler._ask_llm(
                candidates=candidates,
                prompt="debug this",
                agent_names=agent_names,
                correlation_id=uuid4(),
            )

        assert result == "agent-debugger"

    # -- LLM selects agent not in candidates (still in registry) --

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_llm_can_select_low_confidence_candidate(
        self, handler: HandlerRoutingLlm
    ) -> None:
        """LLM picks an agent that was in candidates but ranked lower."""
        agents = (
            _make_agent("agent-debugger", triggers=("debug",)),
            _make_agent("agent-api-architect", triggers=("api",)),
            _make_agent("polymorphic-agent", triggers=("poly",)),
        )
        request = _make_request("debug the api endpoint", agents)

        # Mock LLM to pick the second-best candidate
        with patch.object(
            handler,
            "_ask_llm",
            new_callable=AsyncMock,
            return_value="agent-api-architect",
        ):
            result = await handler.compute_routing(request)

        assert result.selected_agent == "agent-api-architect"
        assert result.routing_policy == "trigger_match"

    # -- candidates tuple capped at _MAX_CANDIDATES --

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_candidates_capped_at_max(self, handler: HandlerRoutingLlm) -> None:
        agents = tuple(
            _make_agent(f"agent-test-{i}", triggers=("testing",)) for i in range(10)
        )
        request = _make_request("I need help testing", agents)

        with patch.object(
            handler,
            "_ask_llm",
            new_callable=AsyncMock,
            return_value="agent-test-0",
        ):
            result = await handler.compute_routing(request)

        assert len(result.candidates) <= 5

    # -- routing_path is always "local" --

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_routing_path_is_local(self, handler: HandlerRoutingLlm) -> None:
        agents = (
            _make_agent("agent-debugger", triggers=("debug",)),
            _make_agent("polymorphic-agent", triggers=("poly",)),
        )
        request = _make_request("debug this error", agents)

        with patch.object(
            handler,
            "_ask_llm",
            new_callable=AsyncMock,
            return_value="agent-debugger",
        ):
            result = await handler.compute_routing(request)

        assert result.routing_path == "local"

    # -- LLM payload uses correct model name and parameters --

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_llm_payload_parameters(self, handler: HandlerRoutingLlm) -> None:
        candidates = [_make_candidate("agent-debugger")]
        agent_names = {"agent-debugger"}
        captured_payloads: list[dict[str, Any]] = []

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json = MagicMock(
            return_value=_make_llm_response("agent-debugger")
        )

        async def capture_post(url: str, **kwargs: Any) -> Any:
            captured_payloads.append(kwargs.get("json", {}))
            return mock_response

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = capture_post

        with patch(
            "omniclaude.nodes.node_agent_routing_compute.handler_routing_llm.httpx.AsyncClient",
            return_value=mock_client,
        ):
            await handler._ask_llm(
                candidates=candidates,
                prompt="debug this",
                agent_names=agent_names,
                correlation_id=uuid4(),
            )

        assert len(captured_payloads) == 1
        payload = captured_payloads[0]
        assert payload["model"] == "Qwen2.5-14B"
        assert payload["temperature"] == 0.0
        assert payload["max_tokens"] == 50
        assert payload["messages"][0]["role"] == "user"

    # -- LLM URL uses /v1/chat/completions endpoint --

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_llm_url_endpoint(self, handler: HandlerRoutingLlm) -> None:
        candidates = [_make_candidate("agent-debugger")]
        agent_names = {"agent-debugger"}
        captured_urls: list[str] = []

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json = MagicMock(
            return_value=_make_llm_response("agent-debugger")
        )

        async def capture_post(url: str, **kwargs: Any) -> Any:
            captured_urls.append(url)
            return mock_response

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = capture_post

        with patch(
            "omniclaude.nodes.node_agent_routing_compute.handler_routing_llm.httpx.AsyncClient",
            return_value=mock_client,
        ):
            await handler._ask_llm(
                candidates=candidates,
                prompt="debug this",
                agent_names=agent_names,
                correlation_id=uuid4(),
            )

        assert len(captured_urls) == 1
        assert captured_urls[0].endswith("/v1/chat/completions")
        assert "localhost:8200" in captured_urls[0]
