# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Unit tests for VllmInferenceBackend (OMN-2799).

Coverage:
- Success path: choices[0].message.content returned
- Timeout -> ModelSkillResult(error_code="TIMEOUT")
- NetworkError -> BACKEND_UNAVAILABLE
- Non-200 response -> error with status code in detail
- Missing `choices` in response -> BACKEND_UNAVAILABLE
- Semaphore blocks beyond MAX_CONCURRENT (test with 5 concurrent calls, cap=4)
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import httpx
import pytest

from omniclaude.config.model_local_llm_config import (
    LlmEndpointConfig,
    LlmEndpointPurpose,
    LocalLlmEndpointRegistry,
)
from omniclaude.nodes.node_local_llm_inference_effect.backends.backend_vllm import (
    VllmInferenceBackend,
)
from omniclaude.nodes.node_local_llm_inference_effect.models import (
    ModelLocalLlmInferenceRequest,
)
from omniclaude.nodes.shared.models.model_skill_result import SkillResultStatus

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_FAKE_ENDPOINT = LlmEndpointConfig(
    url="http://localhost:8000/",
    model_name="test-model",
    purpose=LlmEndpointPurpose.CODE_ANALYSIS,
    max_latency_ms=5000,
    priority=9,
)


def _make_registry(endpoint: LlmEndpointConfig | None = _FAKE_ENDPOINT) -> MagicMock:
    """Create a mock LocalLlmEndpointRegistry."""
    registry = MagicMock(spec=LocalLlmEndpointRegistry)
    registry.get_endpoint.return_value = endpoint
    return registry


def _make_request(
    prompt: str = "Hello",
    correlation_id: UUID | None = None,
) -> ModelLocalLlmInferenceRequest:
    """Create a minimal inference request."""
    return ModelLocalLlmInferenceRequest(
        prompt=prompt,
        correlation_id=correlation_id or uuid4(),
    )


def _success_response(content: str = "world") -> httpx.Response:
    """Create a mock httpx.Response with a valid chat completion body."""
    response = httpx.Response(
        status_code=200,
        json={
            "choices": [
                {
                    "message": {"content": content},
                    "index": 0,
                    "finish_reason": "stop",
                }
            ]
        },
    )
    return response


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_success_path() -> None:
    """Successful inference returns SUCCESS with output text."""
    registry = _make_registry()
    backend = VllmInferenceBackend(registry=registry)

    mock_response = _success_response("Hello from LLM")
    backend._client = AsyncMock(spec=httpx.AsyncClient)
    backend._client.post = AsyncMock(return_value=mock_response)

    request = _make_request(prompt="test prompt")
    result = await backend.infer(request)

    assert result.status == SkillResultStatus.SUCCESS
    assert result.output == "Hello from LLM"
    assert result.error is None
    assert result.correlation_id == request.correlation_id

    # Verify the correct URL was called
    backend._client.post.assert_called_once()
    call_args = backend._client.post.call_args
    assert "v1/chat/completions" in call_args[0][0]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_timeout_returns_timeout_error() -> None:
    """httpx.TimeoutException results in FAILED with TIMEOUT error."""
    registry = _make_registry()
    backend = VllmInferenceBackend(registry=registry)

    backend._client = AsyncMock(spec=httpx.AsyncClient)
    backend._client.post = AsyncMock(
        side_effect=httpx.TimeoutException("read timed out")
    )

    request = _make_request()
    result = await backend.infer(request)

    assert result.status == SkillResultStatus.FAILED
    assert result.error == "TIMEOUT"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_network_error_returns_backend_unavailable() -> None:
    """httpx.NetworkError results in FAILED with BACKEND_UNAVAILABLE error."""
    registry = _make_registry()
    backend = VllmInferenceBackend(registry=registry)

    backend._client = AsyncMock(spec=httpx.AsyncClient)
    backend._client.post = AsyncMock(
        side_effect=httpx.NetworkError("Connection refused")
    )

    request = _make_request()
    result = await backend.infer(request)

    assert result.status == SkillResultStatus.FAILED
    assert result.error == "BACKEND_UNAVAILABLE"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_non_200_response_returns_http_error() -> None:
    """Non-200 HTTP status returns FAILED with status code in error."""
    registry = _make_registry()
    backend = VllmInferenceBackend(registry=registry)

    error_response = httpx.Response(status_code=503, json={"error": "overloaded"})
    backend._client = AsyncMock(spec=httpx.AsyncClient)
    backend._client.post = AsyncMock(return_value=error_response)

    request = _make_request()
    result = await backend.infer(request)

    assert result.status == SkillResultStatus.FAILED
    assert "503" in (result.error or "")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_missing_choices_returns_backend_unavailable() -> None:
    """Response without choices field returns FAILED with BACKEND_UNAVAILABLE."""
    registry = _make_registry()
    backend = VllmInferenceBackend(registry=registry)

    # Response body missing 'choices' key
    bad_response = httpx.Response(status_code=200, json={"id": "abc"})
    backend._client = AsyncMock(spec=httpx.AsyncClient)
    backend._client.post = AsyncMock(return_value=bad_response)

    request = _make_request()
    result = await backend.infer(request)

    assert result.status == SkillResultStatus.FAILED
    assert "BACKEND_UNAVAILABLE" in (result.error or "")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_semaphore_blocks_beyond_max_concurrent() -> None:
    """Semaphore limits concurrency to MAX_CONCURRENT (4 default)."""
    registry = _make_registry()
    backend = VllmInferenceBackend(registry=registry)
    backend._semaphore = asyncio.Semaphore(4)

    call_count = 0
    max_concurrent = 0
    lock = asyncio.Lock()

    original_post = AsyncMock()

    async def slow_post(*args: Any, **kwargs: Any) -> httpx.Response:
        nonlocal call_count, max_concurrent
        async with lock:
            call_count += 1
            current = call_count
        if current > max_concurrent:
            max_concurrent = current
        # Simulate work
        await asyncio.sleep(0.05)
        async with lock:
            call_count -= 1
        return _success_response("ok")

    backend._client = AsyncMock(spec=httpx.AsyncClient)
    backend._client.post = slow_post

    # Launch 5 concurrent calls with cap=4
    requests = [_make_request(prompt=f"prompt-{i}") for i in range(5)]
    results = await asyncio.gather(*[backend.infer(r) for r in requests])

    # All should succeed
    for r in results:
        assert r.status == SkillResultStatus.SUCCESS

    # At most 4 should have been in flight simultaneously
    assert max_concurrent <= 4


@pytest.mark.unit
@pytest.mark.asyncio
async def test_no_endpoint_returns_backend_unavailable() -> None:
    """When registry has no endpoint for the purpose, return BACKEND_UNAVAILABLE."""
    registry = _make_registry(endpoint=None)
    backend = VllmInferenceBackend(registry=registry)

    request = _make_request()
    result = await backend.infer(request)

    assert result.status == SkillResultStatus.FAILED
    assert "BACKEND_UNAVAILABLE" in (result.error or "")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_aclose_closes_client() -> None:
    """aclose() delegates to the httpx client."""
    registry = _make_registry()
    backend = VllmInferenceBackend(registry=registry)

    backend._client = AsyncMock(spec=httpx.AsyncClient)
    backend._client.aclose = AsyncMock()

    await backend.aclose()
    backend._client.aclose.assert_called_once()
