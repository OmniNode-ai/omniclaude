# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""vLLM inference backend for NodeLocalLlmInferenceEffect.

Implements ProtocolLocalLlmInference by calling an OpenAI-compatible
``/v1/chat/completions`` endpoint (vLLM, TGI, or any compatible server).

Concurrency is bounded by an asyncio.Semaphore (env: OMNICLAUDE_VLLM_MAX_CONCURRENT).
A single httpx.AsyncClient is reused across calls for connection pooling.

Reference pattern: node_agent_routing_compute/handler_routing_llm.py:393-446.

Ticket: OMN-2799, OMN-5722
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any

import httpx

from omniclaude.config.model_local_llm_config import (
    LlmEndpointPurpose,
    LocalLlmEndpointRegistry,
)
from omniclaude.nodes.node_local_llm_inference_effect.models import (
    ModelLocalLlmInferenceRequest,
)
from omniclaude.shared.models.model_skill_result import (
    ModelSkillResult,
    SkillResultStatus,
)

logger = logging.getLogger(__name__)

# Exhaustive mapping from model_purpose literals to LlmEndpointPurpose.
# The keys match ModelSkillNodeExecution.model_purpose literals plus the
# request-level defaults used by callers.
_MAP_PURPOSE: dict[str, LlmEndpointPurpose] = {
    "CODE_ANALYSIS": LlmEndpointPurpose.CODE_ANALYSIS,
    "REASONING": LlmEndpointPurpose.REASONING,
    "ROUTING": LlmEndpointPurpose.ROUTING,
    "GENERAL": LlmEndpointPurpose.GENERAL,
    "EMBEDDING": LlmEndpointPurpose.EMBEDDING,
    "VISION": LlmEndpointPurpose.VISION,
    "FUNCTION_CALLING": LlmEndpointPurpose.FUNCTION_CALLING,
}


@dataclass
class ChatCompletionResult:
    """Result of a chat completion call with optional tool calls.

    Mirrors the structure needed by the agentic loop (OMN-5722).
    """

    content: str | None = None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None


def _parse_tool_calls_from_message(
    message: dict[str, Any],
) -> list[dict[str, Any]]:
    """Extract and normalize tool_calls from an OpenAI chat completion message.

    Mirrors ``_parse_tool_calls`` from ``handler_llm_openai_compatible.py:861-907``.
    Handles both well-formed tool_calls arrays and malformed/partial responses.

    Args:
        message: The ``choices[0].message`` dict from the API response.

    Returns:
        List of normalized tool call dicts with ``id``, ``function.name``,
        and ``function.arguments`` (as a JSON string).
    """
    raw_calls = message.get("tool_calls")
    if not raw_calls or not isinstance(raw_calls, list):
        return []

    parsed: list[dict[str, Any]] = []
    for call in raw_calls:
        if not isinstance(call, dict):
            continue

        func = call.get("function", {})
        if not isinstance(func, dict):
            continue

        name = func.get("name")
        if not name:
            continue

        # Arguments may be a string (normal) or a dict (some backends).
        args_raw = func.get("arguments", "{}")
        if isinstance(args_raw, dict):
            args_str = json.dumps(args_raw)
        elif isinstance(args_raw, str):
            args_str = args_raw
        else:
            args_str = "{}"

        parsed.append(
            {
                "id": call.get("id", f"call_{len(parsed)}"),
                "type": "function",
                "function": {
                    "name": name,
                    "arguments": args_str,
                },
            }
        )

    return parsed


def _parse_chat_completion_response(
    data: dict[str, Any],
) -> ChatCompletionResult:
    """Parse a full chat completion response into a ChatCompletionResult.

    Args:
        data: The raw JSON response from ``/v1/chat/completions``.

    Returns:
        ChatCompletionResult with content and/or tool_calls populated.
    """
    try:
        message = data["choices"][0]["message"]
    except (KeyError, IndexError, TypeError) as exc:
        logger.warning("chat_completion response missing choices: %s", exc)
        return ChatCompletionResult(error="MALFORMED_RESPONSE")

    content = message.get("content")
    tool_calls = _parse_tool_calls_from_message(message)

    return ChatCompletionResult(content=content, tool_calls=tool_calls)


class VllmInferenceBackend:
    """vLLM/OpenAI-compatible inference backend.

    Sends POST requests to ``<endpoint>/v1/chat/completions`` and parses
    ``choices[0].message.content`` from the response.

    Satisfies ``ProtocolLocalLlmInference`` (runtime-checkable).

    Attributes:
        handler_key: Backend identifier for handler routing (``"vllm"``).
    """

    handler_key: str = "vllm"

    # --- Synchronous chat_completion for agentic loop (OMN-5722) ---

    def chat_completion_sync(
        self,
        messages: list[dict[str, Any]],
        endpoint_url: str,
        model: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> ChatCompletionResult:
        """Synchronous chat completion with tool-calling support.

        Sends a full messages array (with optional tools) to a ``/v1/chat/completions``
        endpoint and parses the response, including any ``tool_calls`` in the
        assistant message.

        This method is intentionally synchronous for use in the delegation daemon's
        background thread (the agentic loop runs in a threading context, not asyncio).

        Args:
            messages: OpenAI-format messages list.
            endpoint_url: Base URL of the LLM endpoint (e.g. ``http://host:8000/``).
            model: Model name override. Falls back to ``"default"`` if not provided.
            tools: Optional list of tool definitions (OpenAI function-calling format).
            tool_choice: Optional tool choice directive (``"auto"``, ``"none"``, etc.).
            max_tokens: Optional max tokens for the response.
            temperature: Optional temperature for the response.

        Returns:
            ChatCompletionResult with content and/or tool_calls.
        """
        url = f"{endpoint_url.rstrip('/')}/v1/chat/completions"
        payload: dict[str, Any] = {
            "model": model or "default",
            "messages": messages,
        }
        if tools:
            payload["tools"] = tools
        if tool_choice is not None:
            payload["tool_choice"] = tool_choice
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if temperature is not None:
            payload["temperature"] = temperature

        try:
            with httpx.Client(timeout=self._TIMEOUT) as client:
                response = client.post(url, json=payload)
        except httpx.TimeoutException:
            logger.warning("chat_completion timed out for %s", url)
            return ChatCompletionResult(error="TIMEOUT")
        except httpx.NetworkError as exc:
            logger.warning("chat_completion network error: %s", exc)
            return ChatCompletionResult(error="BACKEND_UNAVAILABLE")

        if response.status_code != 200:
            logger.warning("chat_completion HTTP %d from %s", response.status_code, url)
            return ChatCompletionResult(error=f"HTTP {response.status_code}")

        data = response.json()
        return _parse_chat_completion_response(data)

    _MAX_CONCURRENT: int = int(os.getenv("OMNICLAUDE_VLLM_MAX_CONCURRENT", "4"))
    _TIMEOUT: httpx.Timeout = httpx.Timeout(
        connect=5.0, read=120.0, write=10.0, pool=5.0
    )

    def __init__(self, registry: LocalLlmEndpointRegistry) -> None:
        """Initialize the vLLM inference backend.

        Args:
            registry: Endpoint registry used to resolve model URLs by purpose.
        """
        self._registry = registry
        self._client = httpx.AsyncClient(timeout=self._TIMEOUT)
        self._semaphore = asyncio.Semaphore(self._MAX_CONCURRENT)

    async def infer(self, request: ModelLocalLlmInferenceRequest) -> ModelSkillResult:
        """Submit a prompt to the vLLM endpoint and return a ModelSkillResult.

        Resolves the endpoint from the registry using the request's model_purpose
        (defaults to ``"CODE_ANALYSIS"`` when not specified). The prompt is sent
        as a single user message to ``/v1/chat/completions``.

        Args:
            request: Inference request with prompt and optional parameters.

        Returns:
            ModelSkillResult with status SUCCESS and the LLM output, or
            status FAILED with an appropriate error string.
        """
        # Resolve purpose string to LlmEndpointPurpose enum.
        purpose_key = request.model_purpose or "CODE_ANALYSIS"
        purpose = _MAP_PURPOSE.get(purpose_key)
        if purpose is None:
            return ModelSkillResult(
                skill_name=request.skill_name,
                status=SkillResultStatus.FAILED,
                extra={"error": f"Unknown model_purpose: {purpose_key!r}"},
            )

        endpoint = self._registry.get_endpoint(purpose)
        if endpoint is None:
            logger.warning(
                "No endpoint configured for purpose=%s",
                purpose_key,
            )
            return ModelSkillResult(
                skill_name=request.skill_name,
                status=SkillResultStatus.FAILED,
                extra={
                    "error": f"BACKEND_UNAVAILABLE: no endpoint for purpose={purpose_key}"
                },
            )

        url = f"{endpoint.url}v1/chat/completions"
        payload: dict[  # ONEX_EXCLUDE: dict_str_any - external/untyped API boundary
            str, Any
        ] = {  # ONEX_EXCLUDE: dict_str_any - external/untyped API boundary
            "model": request.model or endpoint.model_name,
            "messages": [{"role": "user", "content": request.prompt}],
        }
        if request.max_tokens is not None:
            payload["max_tokens"] = request.max_tokens
        if request.temperature is not None:
            payload["temperature"] = request.temperature

        async with self._semaphore:
            try:
                response = await self._client.post(url, json=payload)
            except httpx.TimeoutException:
                logger.warning("vLLM inference timed out")
                return ModelSkillResult(
                    skill_name=request.skill_name,
                    status=SkillResultStatus.FAILED,
                    extra={"error": "TIMEOUT"},
                )
            except httpx.NetworkError as exc:
                logger.warning("vLLM network error: %s", exc)
                return ModelSkillResult(
                    skill_name=request.skill_name,
                    status=SkillResultStatus.FAILED,
                    extra={"error": "BACKEND_UNAVAILABLE"},
                )

            if response.status_code != 200:
                logger.warning("vLLM returned HTTP %d", response.status_code)
                return ModelSkillResult(
                    skill_name=request.skill_name,
                    status=SkillResultStatus.FAILED,
                    extra={"error": f"HTTP {response.status_code}"},
                )

            data = response.json()

            try:
                content: str = data["choices"][0]["message"]["content"]
            except (KeyError, IndexError, TypeError) as exc:
                logger.warning("vLLM response missing choices: %s", exc)
                return ModelSkillResult(
                    skill_name=request.skill_name,
                    status=SkillResultStatus.FAILED,
                    extra={
                        "error": "BACKEND_UNAVAILABLE: malformed response (missing choices)"
                    },
                )

        return ModelSkillResult(
            skill_name=request.skill_name,
            status=SkillResultStatus.SUCCESS,
            extra={"output": content},
        )

    async def aclose(self) -> None:
        """Close the underlying httpx client.

        Must be called during plugin shutdown to release connections.
        """
        await self._client.aclose()


__all__ = ["ChatCompletionResult", "VllmInferenceBackend"]
