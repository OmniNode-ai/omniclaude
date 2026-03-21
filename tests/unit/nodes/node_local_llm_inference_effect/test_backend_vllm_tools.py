# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Unit tests for VllmInferenceBackend.chat_completion_sync() (OMN-5722).

Coverage:
- Normal text response (no tool calls)
- Tool call response with well-formed tool_calls
- Mixed response (content + tool_calls)
- Malformed response (missing choices)
- Empty tool_calls array
- Tool call with dict arguments (some backends)
- Timeout error
- Network error
- Non-200 HTTP status
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest

from omniclaude.config.model_local_llm_config import (
    LocalLlmEndpointRegistry,
)
from omniclaude.nodes.node_local_llm_inference_effect.backends.backend_vllm import (
    VllmInferenceBackend,
    _parse_chat_completion_response,
    _parse_tool_calls_from_message,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_ENDPOINT_URL = "http://localhost:8000/"


def _make_backend() -> VllmInferenceBackend:
    """Create a VllmInferenceBackend with a mock registry."""
    registry = MagicMock(spec=LocalLlmEndpointRegistry)
    return VllmInferenceBackend(registry=registry)


def _chat_response(
    content: str | None = None,
    tool_calls: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a mock chat completion response body."""
    message: dict[str, Any] = {}
    if content is not None:
        message["content"] = content
    if tool_calls is not None:
        message["tool_calls"] = tool_calls
    return {
        "choices": [
            {
                "index": 0,
                "message": message,
                "finish_reason": "stop" if not tool_calls else "tool_calls",
            }
        ]
    }


def _tool_call(
    name: str,
    arguments: str | dict[str, Any],
    call_id: str = "call_0",
) -> dict[str, Any]:
    """Build a single tool_call entry."""
    return {
        "id": call_id,
        "type": "function",
        "function": {
            "name": name,
            "arguments": arguments,
        },
    }


# ---------------------------------------------------------------------------
# Tests: _parse_tool_calls_from_message
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestParseToolCalls:
    def test_no_tool_calls_key(self) -> None:
        assert _parse_tool_calls_from_message({"content": "hello"}) == []

    def test_empty_tool_calls(self) -> None:
        assert _parse_tool_calls_from_message({"tool_calls": []}) == []

    def test_none_tool_calls(self) -> None:
        assert _parse_tool_calls_from_message({"tool_calls": None}) == []

    def test_well_formed_tool_call(self) -> None:
        msg = {
            "tool_calls": [
                _tool_call("read_file", json.dumps({"path": "/tmp/a.py"}), "call_1")
            ]
        }
        result = _parse_tool_calls_from_message(msg)
        assert len(result) == 1
        assert result[0]["function"]["name"] == "read_file"
        assert result[0]["id"] == "call_1"
        args = json.loads(result[0]["function"]["arguments"])
        assert args["path"] == "/tmp/a.py"

    def test_dict_arguments_normalized_to_string(self) -> None:
        """Some backends return arguments as a dict instead of string."""
        msg = {"tool_calls": [_tool_call("find_files", {"pattern": "*.py"})]}
        result = _parse_tool_calls_from_message(msg)
        assert len(result) == 1
        # Arguments should be serialized to JSON string
        args = json.loads(result[0]["function"]["arguments"])
        assert args["pattern"] == "*.py"

    def test_missing_function_name_skipped(self) -> None:
        msg = {
            "tool_calls": [
                {"id": "call_0", "type": "function", "function": {"arguments": "{}"}},
                _tool_call("valid_tool", "{}"),
            ]
        }
        result = _parse_tool_calls_from_message(msg)
        assert len(result) == 1
        assert result[0]["function"]["name"] == "valid_tool"

    def test_non_dict_entries_skipped(self) -> None:
        msg = {"tool_calls": ["garbage", 42, _tool_call("real_tool", "{}")]}
        result = _parse_tool_calls_from_message(msg)
        assert len(result) == 1


# ---------------------------------------------------------------------------
# Tests: _parse_chat_completion_response
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestParseChatCompletionResponse:
    def test_text_only_response(self) -> None:
        data = _chat_response(content="The answer is 42")
        result = _parse_chat_completion_response(data)
        assert result.content == "The answer is 42"
        assert result.tool_calls == []
        assert result.error is None

    def test_tool_call_response(self) -> None:
        data = _chat_response(
            tool_calls=[_tool_call("search_content", json.dumps({"pattern": "error"}))]
        )
        result = _parse_chat_completion_response(data)
        assert result.content is None
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0]["function"]["name"] == "search_content"

    def test_mixed_content_and_tools(self) -> None:
        data = _chat_response(
            content="Let me search for that.",
            tool_calls=[_tool_call("find_files", json.dumps({"pattern": "*.py"}))],
        )
        result = _parse_chat_completion_response(data)
        assert result.content == "Let me search for that."
        assert len(result.tool_calls) == 1

    def test_malformed_response_missing_choices(self) -> None:
        result = _parse_chat_completion_response({"id": "abc"})
        assert result.error == "MALFORMED_RESPONSE"

    def test_empty_choices_array(self) -> None:
        result = _parse_chat_completion_response({"choices": []})
        assert result.error == "MALFORMED_RESPONSE"


# ---------------------------------------------------------------------------
# Tests: chat_completion_sync
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestChatCompletionSync:
    def test_text_response(self) -> None:
        backend = _make_backend()
        response_data = _chat_response(content="Hello world")
        mock_response = httpx.Response(status_code=200, json=response_data)

        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.post.return_value = mock_response
            mock_client_cls.return_value = mock_client

            result = backend.chat_completion_sync(
                messages=[{"role": "user", "content": "hi"}],
                endpoint_url=_ENDPOINT_URL,
            )

        assert result.content == "Hello world"
        assert result.tool_calls == []
        assert result.error is None

    def test_tool_call_response(self) -> None:
        backend = _make_backend()
        response_data = _chat_response(
            tool_calls=[
                _tool_call(
                    "read_file", json.dumps({"path": "/tmp/test.py"}), "call_abc"
                )
            ]
        )
        mock_response = httpx.Response(status_code=200, json=response_data)

        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.post.return_value = mock_response
            mock_client_cls.return_value = mock_client

            result = backend.chat_completion_sync(
                messages=[{"role": "user", "content": "read the file"}],
                endpoint_url=_ENDPOINT_URL,
                tools=[{"type": "function", "function": {"name": "read_file"}}],
            )

        assert len(result.tool_calls) == 1
        assert result.tool_calls[0]["function"]["name"] == "read_file"

    def test_timeout_returns_error(self) -> None:
        backend = _make_backend()

        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.post.side_effect = httpx.TimeoutException("timed out")
            mock_client_cls.return_value = mock_client

            result = backend.chat_completion_sync(
                messages=[{"role": "user", "content": "hi"}],
                endpoint_url=_ENDPOINT_URL,
            )

        assert result.error == "TIMEOUT"

    def test_network_error_returns_backend_unavailable(self) -> None:
        backend = _make_backend()

        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.post.side_effect = httpx.NetworkError("refused")
            mock_client_cls.return_value = mock_client

            result = backend.chat_completion_sync(
                messages=[{"role": "user", "content": "hi"}],
                endpoint_url=_ENDPOINT_URL,
            )

        assert result.error == "BACKEND_UNAVAILABLE"

    def test_non_200_returns_http_error(self) -> None:
        backend = _make_backend()
        mock_response = httpx.Response(status_code=503, json={"error": "overloaded"})

        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.post.return_value = mock_response
            mock_client_cls.return_value = mock_client

            result = backend.chat_completion_sync(
                messages=[{"role": "user", "content": "hi"}],
                endpoint_url=_ENDPOINT_URL,
            )

        assert result.error is not None
        assert "503" in result.error

    def test_tools_and_tool_choice_passed_in_payload(self) -> None:
        backend = _make_backend()
        response_data = _chat_response(content="done")
        mock_response = httpx.Response(status_code=200, json=response_data)

        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.post.return_value = mock_response
            mock_client_cls.return_value = mock_client

            tools = [{"type": "function", "function": {"name": "test_tool"}}]
            backend.chat_completion_sync(
                messages=[{"role": "user", "content": "hi"}],
                endpoint_url=_ENDPOINT_URL,
                tools=tools,
                tool_choice="auto",
                max_tokens=100,
                temperature=0.5,
            )

            call_args = mock_client.post.call_args
            payload = (
                call_args[1]["json"] if "json" in call_args[1] else call_args[0][1]
            )
            if isinstance(payload, str):
                import json as _json

                payload = _json.loads(payload)
            # Verify via the kwargs
            sent_payload = call_args.kwargs.get(
                "json", call_args.args[1] if len(call_args.args) > 1 else None
            )
            assert sent_payload is not None
            assert sent_payload["tools"] == tools
            assert sent_payload["tool_choice"] == "auto"
            assert sent_payload["max_tokens"] == 100
            assert sent_payload["temperature"] == 0.5
