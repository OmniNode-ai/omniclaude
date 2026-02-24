# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Routing prompt regression tests (OMN-2266).

Snapshot the expected prompt structure and validate strict parsing of the
LLM response into ``selected_agent``.  Complements the broader handler tests
in ``tests/routing/test_handler_routing_llm.py`` by focusing on:

* Exact prompt schema — structural sections and formatting invariants
* Malformed API response recovery — missing keys, wrong types, empty choices
* Additional edge cases for _parse_agent_from_response
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
    ModelConfidenceBreakdown,
    ModelRoutingCandidate,
)

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


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


def _make_handler() -> HandlerRoutingLlm:
    return HandlerRoutingLlm(llm_url="http://localhost:8200", model_name="Qwen2.5-14B")


# ---------------------------------------------------------------------------
# Prompt schema snapshot tests
# ---------------------------------------------------------------------------


class TestRoutingPromptSchema:
    """Snapshot-style tests that pin the exact sections of the routing prompt.

    These act as regression guards: if the prompt format changes
    (new headers, different agent list format, etc.), these tests fail and
    force a deliberate prompt-version bump via _ROUTING_PROMPT_VERSION.
    """

    @pytest.mark.unit
    def test_prompt_opens_with_selection_instruction(self) -> None:
        """First line must tell the model what to do."""
        candidates = [_make_candidate("agent-debugger")]
        result = _build_routing_prompt(candidates, "fix this bug")
        first_line = result.splitlines()[0]
        assert "Select the best agent" in first_line

    @pytest.mark.unit
    def test_prompt_contains_respond_only_instruction(self) -> None:
        """Model must be told to respond with ONLY the agent name."""
        candidates = [_make_candidate("agent-debugger")]
        result = _build_routing_prompt(candidates, "fix this bug")
        assert "Respond with ONLY the agent name" in result

    @pytest.mark.unit
    def test_prompt_contains_available_agents_section(self) -> None:
        """'Available agents:' section must be present."""
        candidates = [_make_candidate("agent-api-architect")]
        result = _build_routing_prompt(candidates, "design an API")
        assert "Available agents:" in result

    @pytest.mark.unit
    def test_prompt_agent_list_uses_dash_prefix(self) -> None:
        """Each candidate line must use '  - ' prefix."""
        candidates = [
            _make_candidate("agent-debugger", reason="matched debug"),
            _make_candidate("agent-api-architect", reason="matched api"),
        ]
        result = _build_routing_prompt(candidates, "test")
        assert "  - agent-debugger: matched debug" in result
        assert "  - agent-api-architect: matched api" in result

    @pytest.mark.unit
    def test_prompt_contains_user_request_section(self) -> None:
        """'User request:' label must appear before the quoted prompt."""
        candidates = [_make_candidate("agent-debugger")]
        result = _build_routing_prompt(candidates, "my actual request")
        assert 'User request: "my actual request"' in result

    @pytest.mark.unit
    def test_prompt_ends_with_agent_name_cue(self) -> None:
        """Last non-empty line must be 'Agent name:' to elicit a bare name."""
        candidates = [_make_candidate("agent-debugger")]
        result = _build_routing_prompt(candidates, "test")
        non_empty = [line for line in result.splitlines() if line.strip()]
        assert non_empty[-1] == "Agent name:"

    @pytest.mark.unit
    def test_prompt_section_order(self) -> None:
        """Sections must appear in order: instructions → agents → request → cue."""
        candidates = [_make_candidate("agent-debugger")]
        result = _build_routing_prompt(candidates, "my request")
        idx_agents = result.index("Available agents:")
        idx_request = result.index("User request:")
        idx_cue = result.index("Agent name:")
        assert idx_agents < idx_request < idx_cue

    @pytest.mark.unit
    def test_prompt_version_constant_is_semver(self) -> None:
        """_ROUTING_PROMPT_VERSION must follow semver (e.g. '1.0.0')."""
        parts = _ROUTING_PROMPT_VERSION.split(".")
        assert len(parts) == 3, (
            f"Expected 3 semver parts, got: {_ROUTING_PROMPT_VERSION}"
        )
        for part in parts:
            assert part.isdigit(), f"Each part must be numeric: {part}"

    @pytest.mark.unit
    def test_prompt_candidate_colon_separator(self) -> None:
        """Agent name and reason must be separated by ': '."""
        candidates = [_make_candidate("agent-debugger", reason="matched debug")]
        result = _build_routing_prompt(candidates, "test")
        assert "agent-debugger: matched debug" in result

    @pytest.mark.unit
    def test_prompt_user_request_in_quotes(self) -> None:
        """User request must be quoted to delimit it from the prompt structure."""
        candidates = [_make_candidate("agent-debugger")]
        result = _build_routing_prompt(candidates, "some prompt text")
        assert '"some prompt text"' in result

    @pytest.mark.unit
    def test_multiple_candidates_all_in_list(self) -> None:
        """All candidates must appear in the agent list."""
        candidates = [
            _make_candidate("agent-debugger"),
            _make_candidate("agent-api-architect"),
            _make_candidate("agent-refactorer"),
        ]
        result = _build_routing_prompt(candidates, "test")
        for name in ("agent-debugger", "agent-api-architect", "agent-refactorer"):
            assert name in result


# ---------------------------------------------------------------------------
# Response parsing edge cases
# ---------------------------------------------------------------------------


class TestParseAgentEdgeCases:
    """Edge cases for _parse_agent_from_response not covered by the handler tests."""

    @pytest.mark.unit
    def test_whitespace_only_response_returns_none(self) -> None:
        known = {"agent-debugger"}
        assert _parse_agent_from_response("   \t\n  ", known) is None

    @pytest.mark.unit
    def test_newline_in_response_still_matches(self) -> None:
        """LLMs sometimes emit trailing newlines — strip handles this."""
        known = {"agent-debugger"}
        result = _parse_agent_from_response("agent-debugger\n", known)
        assert result == "agent-debugger"

    @pytest.mark.unit
    def test_response_with_explanation_still_matches(self) -> None:
        """'I chose agent-debugger because...' must still match via substring."""
        known = {"agent-debugger"}
        result = _parse_agent_from_response(
            "I chose agent-debugger because it handles debugging best.", known
        )
        assert result == "agent-debugger"

    @pytest.mark.unit
    def test_longer_name_wins_over_prefix(self) -> None:
        """agent-api-architect must beat agent-api when both present."""
        known = {"agent-api", "agent-api-architect"}
        result = _parse_agent_from_response("agent-api-architect", known)
        assert result == "agent-api-architect"

    @pytest.mark.unit
    def test_response_with_only_punctuation_returns_none(self) -> None:
        known = {"agent-debugger"}
        assert _parse_agent_from_response("!!!---...", known) is None

    @pytest.mark.unit
    def test_numeric_response_returns_none(self) -> None:
        known = {"agent-debugger"}
        assert _parse_agent_from_response("42", known) is None

    @pytest.mark.unit
    def test_empty_known_agents_returns_none(self) -> None:
        assert _parse_agent_from_response("agent-debugger", set()) is None

    @pytest.mark.unit
    def test_response_with_quoted_agent_name_matches(self) -> None:
        """LLM may quote the name: '"agent-debugger"' must still match."""
        known = {"agent-debugger"}
        result = _parse_agent_from_response('"agent-debugger"', known)
        assert result == "agent-debugger"

    @pytest.mark.unit
    def test_response_mixed_case_substring(self) -> None:
        """Case-folded substring match must work for verbose responses."""
        known = {"agent-api-architect"}
        result = _parse_agent_from_response(
            "The best agent is AGENT-API-ARCHITECT.", known
        )
        assert result == "agent-api-architect"


# ---------------------------------------------------------------------------
# Malformed API response recovery (tests for _ask_llm KeyError/IndexError paths)
# ---------------------------------------------------------------------------


class TestMalformedApiResponseRecovery:
    """Validate that _ask_llm returns None for every malformed response shape.

    These tests cover the `except (KeyError, IndexError, TypeError)` block
    that extracts `data["choices"][0]["message"]["content"]`.
    """

    @pytest.fixture
    def handler(self) -> HandlerRoutingLlm:
        return _make_handler()

    def _make_mock_client(self, response_json: Any) -> AsyncMock:
        """Return a mock AsyncClient whose POST returns response_json."""
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json = MagicMock(return_value=response_json)

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_response)
        return mock_client

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_missing_choices_key_returns_none(
        self, handler: HandlerRoutingLlm
    ) -> None:
        """Response without 'choices' key must not raise."""
        candidates = [_make_candidate("agent-debugger")]
        agent_names = {"agent-debugger"}

        with patch(
            "omniclaude.nodes.node_agent_routing_compute.handler_routing_llm.httpx.AsyncClient",
            return_value=self._make_mock_client({"model": "Qwen2.5-14B"}),
        ):
            result = await handler._ask_llm(
                candidates=candidates,
                prompt="debug this",
                agent_names=agent_names,
                correlation_id=uuid4(),
            )

        assert result is None

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_empty_choices_list_returns_none(
        self, handler: HandlerRoutingLlm
    ) -> None:
        """Empty choices list causes IndexError — must return None gracefully."""
        candidates = [_make_candidate("agent-debugger")]
        agent_names = {"agent-debugger"}

        with patch(
            "omniclaude.nodes.node_agent_routing_compute.handler_routing_llm.httpx.AsyncClient",
            return_value=self._make_mock_client({"choices": []}),
        ):
            result = await handler._ask_llm(
                candidates=candidates,
                prompt="debug this",
                agent_names=agent_names,
                correlation_id=uuid4(),
            )

        assert result is None

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_choices_item_missing_message_key_returns_none(
        self, handler: HandlerRoutingLlm
    ) -> None:
        """Choice item without 'message' key must return None."""
        candidates = [_make_candidate("agent-debugger")]
        agent_names = {"agent-debugger"}

        with patch(
            "omniclaude.nodes.node_agent_routing_compute.handler_routing_llm.httpx.AsyncClient",
            return_value=self._make_mock_client(
                {"choices": [{"finish_reason": "stop"}]}
            ),
        ):
            result = await handler._ask_llm(
                candidates=candidates,
                prompt="debug this",
                agent_names=agent_names,
                correlation_id=uuid4(),
            )

        assert result is None

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_message_missing_content_key_returns_none(
        self, handler: HandlerRoutingLlm
    ) -> None:
        """Message without 'content' key must return None."""
        candidates = [_make_candidate("agent-debugger")]
        agent_names = {"agent-debugger"}

        bad_response = {"choices": [{"message": {"role": "assistant"}}]}

        with patch(
            "omniclaude.nodes.node_agent_routing_compute.handler_routing_llm.httpx.AsyncClient",
            return_value=self._make_mock_client(bad_response),
        ):
            result = await handler._ask_llm(
                candidates=candidates,
                prompt="debug this",
                agent_names=agent_names,
                correlation_id=uuid4(),
            )

        assert result is None

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_choices_is_none_returns_none(
        self, handler: HandlerRoutingLlm
    ) -> None:
        """`choices: null` must return None (TypeError path)."""
        candidates = [_make_candidate("agent-debugger")]
        agent_names = {"agent-debugger"}

        with patch(
            "omniclaude.nodes.node_agent_routing_compute.handler_routing_llm.httpx.AsyncClient",
            return_value=self._make_mock_client({"choices": None}),
        ):
            result = await handler._ask_llm(
                candidates=candidates,
                prompt="debug this",
                agent_names=agent_names,
                correlation_id=uuid4(),
            )

        assert result is None

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_empty_response_body_returns_none(
        self, handler: HandlerRoutingLlm
    ) -> None:
        """Completely empty response dict must return None."""
        candidates = [_make_candidate("agent-debugger")]
        agent_names = {"agent-debugger"}

        with patch(
            "omniclaude.nodes.node_agent_routing_compute.handler_routing_llm.httpx.AsyncClient",
            return_value=self._make_mock_client({}),
        ):
            result = await handler._ask_llm(
                candidates=candidates,
                prompt="debug this",
                agent_names=agent_names,
                correlation_id=uuid4(),
            )

        assert result is None

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_content_is_empty_string_returns_none(
        self, handler: HandlerRoutingLlm
    ) -> None:
        """Empty string content → no agent match → returns None."""
        candidates = [_make_candidate("agent-debugger")]
        agent_names = {"agent-debugger"}

        empty_content = {"choices": [{"message": {"role": "assistant", "content": ""}}]}

        with patch(
            "omniclaude.nodes.node_agent_routing_compute.handler_routing_llm.httpx.AsyncClient",
            return_value=self._make_mock_client(empty_content),
        ):
            result = await handler._ask_llm(
                candidates=candidates,
                prompt="debug this",
                agent_names=agent_names,
                correlation_id=uuid4(),
            )

        assert result is None

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_content_is_unrelated_text_returns_none(
        self, handler: HandlerRoutingLlm
    ) -> None:
        """Unrelated text (no valid agent name) returns None."""
        candidates = [_make_candidate("agent-debugger")]
        agent_names = {"agent-debugger"}

        unrelated = {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "I cannot help with that request.",
                    }
                }
            ]
        }

        with patch(
            "omniclaude.nodes.node_agent_routing_compute.handler_routing_llm.httpx.AsyncClient",
            return_value=self._make_mock_client(unrelated),
        ):
            result = await handler._ask_llm(
                candidates=candidates,
                prompt="debug this",
                agent_names=agent_names,
                correlation_id=uuid4(),
            )

        assert result is None

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_valid_response_after_noise_still_parses(
        self, handler: HandlerRoutingLlm
    ) -> None:
        """A valid agent name amid verbose text must still be extracted."""
        candidates = [_make_candidate("agent-debugger")]
        agent_names = {"agent-debugger"}

        verbose = {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "Based on the request, I recommend agent-debugger.",
                    }
                }
            ]
        }

        with patch(
            "omniclaude.nodes.node_agent_routing_compute.handler_routing_llm.httpx.AsyncClient",
            return_value=self._make_mock_client(verbose),
        ):
            result = await handler._ask_llm(
                candidates=candidates,
                prompt="debug this",
                agent_names=agent_names,
                correlation_id=uuid4(),
            )

        assert result == "agent-debugger"
