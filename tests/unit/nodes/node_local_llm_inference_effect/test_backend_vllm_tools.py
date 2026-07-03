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
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest
from omnibase_core.runtime.golden_chain import (
    EnumGoldenChainFailureClass,
    GoldenChainReplayError,
    RecordedReplayInferenceTransport,
    load_fixture,
)

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

# Concrete model + prompts the golden-chain fixtures below were recorded against
# (real vLLM inference on the local-coder backend; see fixture provenance). The
# test payloads MUST match these exactly or the canonical replay transport fails
# closed (REQUEST_HASH_MISMATCH) — that is the "replay is evidence, not authority"
# guarantee, not a fixture that rubber-stamps whatever the caller sends.
_RECORDED_MODEL = "Qwen3.6-35B-A3B"
_TEXT_PROMPT = "In one short sentence, greet the world."
_TOOL_PROMPT = "Read the file /tmp/test.py using the read_file tool."
_READ_FILE_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "read_file",
        "description": "Read a file from disk",
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    },
}

_FIXTURE_DIR = Path(__file__).resolve().parents[3] / "fixtures" / "golden_chain"
_TEXT_FIXTURE = _FIXTURE_DIR / "vllm_chat_text.json"
_TOOL_FIXTURE = _FIXTURE_DIR / "vllm_chat_tool_call.json"


def _make_backend(
    *, sync_transport: httpx.BaseTransport | None = None
) -> VllmInferenceBackend:
    """Create a VllmInferenceBackend.

    The registry is a ``spec``-bound double: ``chat_completion_sync`` takes the
    endpoint URL directly and never touches the registry (which only resolves
    URLs for the async ``infer`` path), so the registry is genuinely out of this
    method's boundary — it is not the inference egress under test.
    """
    registry = MagicMock(spec=LocalLlmEndpointRegistry)
    return VllmInferenceBackend(registry=registry, sync_transport=sync_transport)


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
    """End-to-end ``chat_completion_sync`` tests.

    Two boundary strategies, chosen by what each test proves:

    * **Inference CONTENT** (text + tool-call happy paths) replays REAL recorded
      model bytes through the canonical ``RecordedReplayInferenceTransport``
      (OMN-13499). The backend still constructs the OpenAI-compatible request
      LIVE; the transport returns the recorded bytes only because the live
      request matches the fixture's endpoint + ``request_hash`` + concrete model
      (a drifted request fails closed — proven in
      ``test_wrong_model_fails_replay``). No hand-written model output.
    * **Transport MECHANICS** (timeout / network / non-200 / request shaping) use
      a REAL ``httpx.Client`` driven by an ``httpx.MockTransport`` injected via
      the backend's ``sync_transport`` seam. Real request serialization runs; the
      transport programs the failure/status the mapping code must handle. These
      prove HTTP error handling, not inference content, so recorded replay (which
      can only return recorded 2xx bytes) does not fit them.
    """

    # --- Inference content: canonical recorded-from-real replay -------------

    def test_text_response(self) -> None:
        fixture = load_fixture(_TEXT_FIXTURE)
        transport = RecordedReplayInferenceTransport([fixture])
        backend = _make_backend()

        with patch("httpx.Client", return_value=transport):
            result = backend.chat_completion_sync(
                messages=[{"role": "user", "content": _TEXT_PROMPT}],
                endpoint_url=_ENDPOINT_URL,
                model=_RECORDED_MODEL,
                max_tokens=512,
                temperature=0.0,
            )

        assert result.error is None
        assert result.tool_calls == []
        # Real recorded completion bytes parsed through the sync path (no error,
        # non-empty content). The exact byte-for-byte parse of the recorded fields
        # is covered by TestParseChatCompletionResponse on the same shape.
        assert isinstance(result.content, str) and result.content.strip()
        # The live path resolved the CONCRETE recorded model, not a tier name.
        assert transport.calls[0]["model"] == _RECORDED_MODEL

    def test_tool_call_response(self) -> None:
        fixture = load_fixture(_TOOL_FIXTURE)
        transport = RecordedReplayInferenceTransport([fixture])
        backend = _make_backend()

        with patch("httpx.Client", return_value=transport):
            result = backend.chat_completion_sync(
                messages=[{"role": "user", "content": _TOOL_PROMPT}],
                endpoint_url=_ENDPOINT_URL,
                model=_RECORDED_MODEL,
                tools=[_READ_FILE_TOOL],
                tool_choice="auto",
                max_tokens=512,
                temperature=0.0,
            )

        assert result.error is None
        assert result.tool_calls, "recorded response carried a real tool call"
        names = [tc["function"]["name"] for tc in result.tool_calls]
        assert "read_file" in names
        # Arguments were parsed into a JSON string, not dropped.
        first = next(
            tc for tc in result.tool_calls if tc["function"]["name"] == "read_file"
        )
        assert json.loads(first["function"]["arguments"])  # valid JSON object

    def test_wrong_model_fails_replay(self) -> None:
        """Replay is EVIDENCE, not AUTHORITY: a drifted request fails closed.

        A boundary fake that hand-set canned bytes would return them regardless of
        the request. The canonical transport recomputes the request hash from the
        LIVE payload; a different model changes the hash and the replay raises
        REQUEST_HASH_MISMATCH instead of "passing anyway".
        """
        fixture = load_fixture(_TEXT_FIXTURE)
        transport = RecordedReplayInferenceTransport([fixture])
        backend = _make_backend()

        with (
            pytest.raises(GoldenChainReplayError) as exc,
            patch("httpx.Client", return_value=transport),
        ):
            backend.chat_completion_sync(
                messages=[{"role": "user", "content": _TEXT_PROMPT}],
                endpoint_url=_ENDPOINT_URL,
                model="some-other-model",
                max_tokens=512,
                temperature=0.0,
            )
        assert (
            exc.value.failure_class is EnumGoldenChainFailureClass.REQUEST_HASH_MISMATCH
        )

    # --- Transport mechanics: real httpx.Client + MockTransport -------------

    def test_timeout_returns_error(self) -> None:
        def _handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("timed out", request=request)

        backend = _make_backend(sync_transport=httpx.MockTransport(_handler))
        result = backend.chat_completion_sync(
            messages=[{"role": "user", "content": "hi"}],
            endpoint_url=_ENDPOINT_URL,
        )

        assert result.error == "TIMEOUT"

    def test_network_error_returns_backend_unavailable(self) -> None:
        def _handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("refused", request=request)

        backend = _make_backend(sync_transport=httpx.MockTransport(_handler))
        result = backend.chat_completion_sync(
            messages=[{"role": "user", "content": "hi"}],
            endpoint_url=_ENDPOINT_URL,
        )

        assert result.error == "BACKEND_UNAVAILABLE"

    def test_non_200_returns_http_error(self) -> None:
        def _handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(503, json={"error": "overloaded"})

        backend = _make_backend(sync_transport=httpx.MockTransport(_handler))
        result = backend.chat_completion_sync(
            messages=[{"role": "user", "content": "hi"}],
            endpoint_url=_ENDPOINT_URL,
        )

        assert result.error is not None
        assert "503" in result.error

    def test_tools_and_tool_choice_passed_in_payload(self) -> None:
        captured: dict[str, Any] = {}

        def _handler(request: httpx.Request) -> httpx.Response:
            captured["payload"] = json.loads(request.content.decode("utf-8"))
            captured["url"] = str(request.url)
            return httpx.Response(200, json=_chat_response(content="done"))

        backend = _make_backend(sync_transport=httpx.MockTransport(_handler))
        tools = [{"type": "function", "function": {"name": "test_tool"}}]
        backend.chat_completion_sync(
            messages=[{"role": "user", "content": "hi"}],
            endpoint_url=_ENDPOINT_URL,
            tools=tools,
            tool_choice="auto",
            max_tokens=100,
            temperature=0.5,
        )

        # Real httpx.Client serialized the request the backend constructed.
        assert captured["url"] == "http://localhost:8000/v1/chat/completions"
        sent_payload = captured["payload"]
        assert sent_payload["tools"] == tools
        assert sent_payload["tool_choice"] == "auto"
        assert sent_payload["max_tokens"] == 100
        assert sent_payload["temperature"] == 0.5
