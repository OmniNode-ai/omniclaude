# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""vLLM inference backend for NodeLocalLlmInferenceEffect.

Implements ProtocolLocalLlmInference by calling an OpenAI-compatible
``/v1/chat/completions`` endpoint (vLLM, TGI, or any compatible server).

Concurrency is bounded by an asyncio.Semaphore (env: OMNICLAUDE_VLLM_MAX_CONCURRENT).
A single httpx.AsyncClient is reused across calls for connection pooling.

Reference pattern: node_agent_routing_compute/handler_routing_llm.py:393-446.

Ticket: OMN-2799
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any
from uuid import uuid4

import httpx

from omniclaude.config.model_local_llm_config import (
    LlmEndpointPurpose,
    LocalLlmEndpointRegistry,
)
from omniclaude.nodes.node_local_llm_inference_effect.models import (
    ModelLocalLlmInferenceRequest,
)
from omniclaude.nodes.shared.models.model_skill_result import (
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


class VllmInferenceBackend:
    """vLLM/OpenAI-compatible inference backend.

    Sends POST requests to ``<endpoint>/v1/chat/completions`` and parses
    ``choices[0].message.content`` from the response.

    Satisfies ``ProtocolLocalLlmInference`` (runtime-checkable).

    Attributes:
        handler_key: Backend identifier for handler routing (``"vllm"``).
    """

    handler_key: str = "vllm"

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
        correlation_id = request.correlation_id or uuid4()

        # Resolve purpose string to LlmEndpointPurpose enum.
        purpose_key = request.model_purpose or "CODE_ANALYSIS"
        purpose = _MAP_PURPOSE.get(purpose_key)
        if purpose is None:
            return ModelSkillResult(
                skill_name=request.skill_name,
                status=SkillResultStatus.FAILED,
                error=f"Unknown model_purpose: {purpose_key!r}",
                correlation_id=correlation_id,
            )

        endpoint = self._registry.get_endpoint(purpose)
        if endpoint is None:
            logger.warning(
                "No endpoint configured for purpose=%s (correlation_id=%s)",
                purpose_key,
                correlation_id,
            )
            return ModelSkillResult(
                skill_name=request.skill_name,
                status=SkillResultStatus.FAILED,
                error=f"BACKEND_UNAVAILABLE: no endpoint for purpose={purpose_key}",
                correlation_id=correlation_id,
            )

        url = f"{endpoint.url}v1/chat/completions"
        payload: dict[str, Any] = {
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
                logger.warning(
                    "vLLM inference timed out (correlation_id=%s)", correlation_id
                )
                return ModelSkillResult(
                    skill_name=request.skill_name,
                    status=SkillResultStatus.FAILED,
                    error="TIMEOUT",
                    correlation_id=correlation_id,
                )
            except httpx.NetworkError as exc:
                logger.warning(
                    "vLLM network error: %s (correlation_id=%s)", exc, correlation_id
                )
                return ModelSkillResult(
                    skill_name=request.skill_name,
                    status=SkillResultStatus.FAILED,
                    error="BACKEND_UNAVAILABLE",
                    correlation_id=correlation_id,
                )

            if response.status_code != 200:
                logger.warning(
                    "vLLM returned HTTP %d (correlation_id=%s)",
                    response.status_code,
                    correlation_id,
                )
                return ModelSkillResult(
                    skill_name=request.skill_name,
                    status=SkillResultStatus.FAILED,
                    error=f"HTTP {response.status_code}",
                    correlation_id=correlation_id,
                )

            data = response.json()

            try:
                content: str = data["choices"][0]["message"]["content"]
            except (KeyError, IndexError, TypeError) as exc:
                logger.warning(
                    "vLLM response missing choices: %s (correlation_id=%s)",
                    exc,
                    correlation_id,
                )
                return ModelSkillResult(
                    skill_name=request.skill_name,
                    status=SkillResultStatus.FAILED,
                    error="BACKEND_UNAVAILABLE: malformed response (missing choices)",
                    correlation_id=correlation_id,
                )

        return ModelSkillResult(
            skill_name=request.skill_name,
            status=SkillResultStatus.SUCCESS,
            output=content,
            correlation_id=correlation_id,
        )

    async def aclose(self) -> None:
        """Close the underlying httpx client.

        Must be called during plugin shutdown to release connections.
        """
        await self._client.aclose()


__all__ = ["VllmInferenceBackend"]
