"""Local LLM endpoint configuration registry.

Provides a centralized configuration source for all local LLM endpoints used
by the OmniNode platform. Each endpoint is described by its URL, model name,
purpose, latency budget, and priority. The registry loads endpoint URLs from
environment variables and provides lookup methods by purpose.

Environment variables:
    LLM_CODER_URL: Qwen2.5-Coder-14B endpoint for code generation.
    LLM_EMBEDDING_URL: GTE-Qwen2 embedding endpoint.
    LLM_FUNCTION_URL: Qwen2.5-7B function-calling endpoint (optional, hot-swap).
    LLM_DEEPSEEK_LITE_URL: DeepSeek-V2-Lite endpoint (optional, hot-swap).
    LLM_QWEN_72B_URL: Qwen2.5-72B large model endpoint.
    LLM_VISION_URL: Qwen2-VL vision endpoint.
    LLM_DEEPSEEK_R1_URL: DeepSeek-R1-Distill reasoning endpoint (optional, hot-swap).
    LLM_QWEN_14B_URL: Qwen2.5-14B general purpose endpoint.

Example:
    >>> from omniclaude.config.model_local_llm_config import (
    ...     LlmEndpointPurpose,
    ...     LocalLlmEndpointRegistry,
    ... )
    >>>
    >>> registry = LocalLlmEndpointRegistry()
    >>> endpoint = registry.get_endpoint(LlmEndpointPurpose.CODE_ANALYSIS)
    >>> if endpoint:
    ...     print(endpoint.url)
"""

from __future__ import annotations

import functools
import logging
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, HttpUrl
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


class LlmEndpointPurpose(StrEnum):
    """Purpose categories for LLM endpoints.

    Each purpose maps to a class of tasks that an LLM endpoint is optimized for.
    Used by Epic 1 (routing), Epic 2 (enrichment), Epic 3 (enforcement), and
    Epic 4 (delegation) to resolve which model serves which task.

    Attributes:
        ROUTING: Agent routing decisions and prompt classification.
        CODE_ANALYSIS: Code generation, completion, and analysis.
        EMBEDDING: Text embedding for RAG and semantic search.
        GENERAL: General-purpose tasks and balanced workloads.
        VISION: Vision and multimodal capabilities.
        FUNCTION_CALLING: Structured function/tool calling.
        REASONING: Advanced reasoning with chain-of-thought.
    """

    ROUTING = "routing"
    CODE_ANALYSIS = "code_analysis"
    EMBEDDING = "embedding"
    GENERAL = "general"
    VISION = "vision"
    FUNCTION_CALLING = "function_calling"
    REASONING = "reasoning"


class LlmEndpointConfig(BaseModel):
    """Configuration for a single LLM endpoint.

    Immutable description of an LLM endpoint including its URL, model name,
    purpose, latency budget, and priority. Higher priority values indicate
    preferred endpoints when multiple serve the same purpose.

    Attributes:
        url: HTTP URL of the LLM endpoint.
        model_name: Human-readable model identifier (e.g., "Qwen2.5-Coder-14B").
        purpose: Primary purpose this endpoint is optimized for.
        max_latency_ms: Maximum acceptable latency in milliseconds (from E0 SLOs).
        priority: Selection priority (1-10, higher is preferred).
    """

    model_config = ConfigDict(frozen=True)

    url: HttpUrl = Field(
        description="HTTP URL of the LLM endpoint",
    )
    model_name: str = Field(
        description="Human-readable model identifier",
    )
    purpose: LlmEndpointPurpose = Field(
        description="Primary purpose this endpoint is optimized for",
    )
    max_latency_ms: int = Field(
        default=5000,
        ge=100,
        le=60000,
        description="Maximum acceptable latency in milliseconds",
    )
    priority: int = Field(
        default=5,
        ge=1,
        le=10,
        description="Selection priority (1-10, higher is preferred)",
    )


class LocalLlmEndpointRegistry(BaseSettings):
    """Registry of local LLM endpoints loaded from environment variables.

    Loads LLM endpoint URLs from environment variables and exposes them as
    a structured registry. Provides lookup methods to find the best endpoint
    for a given purpose.

    Missing environment variables result in None fields (not errors), since
    some endpoints are hot-swap and may not always be available.

    Attributes:
        llm_coder_url: Code generation endpoint (Qwen2.5-Coder-14B).
        llm_embedding_url: Embedding endpoint (GTE-Qwen2).
        llm_function_url: Function-calling endpoint (Qwen2.5-7B, hot-swap).
        llm_deepseek_lite_url: Lightweight reasoning endpoint (DeepSeek-V2-Lite, hot-swap).
        llm_qwen_72b_url: Large model endpoint (Qwen2.5-72B).
        llm_vision_url: Vision endpoint (Qwen2-VL).
        llm_deepseek_r1_url: Advanced reasoning endpoint (DeepSeek-R1-Distill, hot-swap).
        llm_qwen_14b_url: General purpose endpoint (Qwen2.5-14B).

    Example:
        >>> import os
        >>> os.environ["LLM_CODER_URL"] = "http://192.168.86.201:8000"
        >>> registry = LocalLlmEndpointRegistry()
        >>> endpoint = registry.get_endpoint(LlmEndpointPurpose.CODE_ANALYSIS)
        >>> endpoint is not None
        True
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # =========================================================================
    # LLM ENDPOINT URLS
    # =========================================================================
    llm_coder_url: HttpUrl | None = Field(
        default=None,
        description="Qwen2.5-Coder-14B endpoint for code generation (RTX 5090)",
    )
    llm_embedding_url: HttpUrl | None = Field(
        default=None,
        description="GTE-Qwen2 endpoint for embeddings (RTX 4090)",
    )
    llm_function_url: HttpUrl | None = Field(
        default=None,
        description="Qwen2.5-7B endpoint for function calling (RTX 4090, hot-swap)",
    )
    llm_deepseek_lite_url: HttpUrl | None = Field(
        default=None,
        description="DeepSeek-V2-Lite endpoint for lightweight reasoning (RTX 4090, hot-swap)",
    )
    llm_qwen_72b_url: HttpUrl | None = Field(
        default=None,
        description="Qwen2.5-72B endpoint for documentation and analysis (M2 Ultra)",
    )
    llm_vision_url: HttpUrl | None = Field(
        default=None,
        description="Qwen2-VL endpoint for vision and multimodal (M2 Ultra)",
    )
    llm_deepseek_r1_url: HttpUrl | None = Field(
        default=None,
        description="DeepSeek-R1-Distill endpoint for advanced reasoning (M2 Ultra, hot-swap)",
    )
    llm_qwen_14b_url: HttpUrl | None = Field(
        default=None,
        description="Qwen2.5-14B endpoint for general purpose tasks (M2 Pro)",
    )

    # =========================================================================
    # LATENCY BUDGETS (per endpoint, in milliseconds)
    # =========================================================================
    llm_coder_max_latency_ms: int = Field(
        default=2000,
        ge=100,
        le=60000,
        description="Max latency for code generation endpoint",
    )
    llm_embedding_max_latency_ms: int = Field(
        default=1000,
        ge=100,
        le=60000,
        description="Max latency for embedding endpoint",
    )
    llm_function_max_latency_ms: int = Field(
        default=3000,
        ge=100,
        le=60000,
        description="Max latency for function calling endpoint",
    )
    llm_deepseek_lite_max_latency_ms: int = Field(
        default=3000,
        ge=100,
        le=60000,
        description="Max latency for lightweight reasoning endpoint",
    )
    llm_qwen_72b_max_latency_ms: int = Field(
        default=10000,
        ge=100,
        le=60000,
        description="Max latency for large model endpoint",
    )
    llm_vision_max_latency_ms: int = Field(
        default=5000,
        ge=100,
        le=60000,
        description="Max latency for vision endpoint",
    )
    llm_deepseek_r1_max_latency_ms: int = Field(
        default=10000,
        ge=100,
        le=60000,
        description="Max latency for advanced reasoning endpoint",
    )
    llm_qwen_14b_max_latency_ms: int = Field(
        default=5000,
        ge=100,
        le=60000,
        description="Max latency for general purpose endpoint",
    )

    # Intentionally a cached_property, not a Pydantic field. This is a private
    # computed cache that will not appear in model_dump() or serialization.
    # Note: model_copy() will share this cache; no callers use model_copy today.
    @functools.cached_property
    def _endpoint_configs(self) -> list[LlmEndpointConfig]:
        """Build the list of available endpoint configs from loaded settings.

        Cached after first access since BaseSettings fields are effectively
        immutable after construction.

        Maps each non-None URL field to an LlmEndpointConfig with the
        appropriate model name, purpose, latency budget, and priority.

        Returns:
            List of LlmEndpointConfig for all configured (non-None) endpoints.
        """
        # NOTE: LlmEndpointPurpose.ROUTING is intentionally unassigned here.
        # It is reserved for future use when a dedicated routing model is
        # deployed. Until then, routing decisions are handled outside this
        # registry (e.g., by the event-based routing service).
        endpoint_specs: list[
            tuple[HttpUrl | None, str, LlmEndpointPurpose, int, int]
        ] = [
            (
                self.llm_coder_url,
                "Qwen2.5-Coder-14B",
                LlmEndpointPurpose.CODE_ANALYSIS,
                self.llm_coder_max_latency_ms,
                9,  # High priority: dedicated GPU (RTX 5090)
            ),
            (
                self.llm_embedding_url,
                "GTE-Qwen2-1.5B",
                LlmEndpointPurpose.EMBEDDING,
                self.llm_embedding_max_latency_ms,
                9,  # High priority: currently running
            ),
            (
                self.llm_function_url,
                "Qwen2.5-7B",
                LlmEndpointPurpose.FUNCTION_CALLING,
                self.llm_function_max_latency_ms,
                5,  # Medium priority: hot-swap, may not be running
            ),
            (
                self.llm_deepseek_lite_url,
                "DeepSeek-V2-Lite",
                LlmEndpointPurpose.GENERAL,
                self.llm_deepseek_lite_max_latency_ms,
                3,  # Lower priority: hot-swap, lightweight fallback
            ),
            (
                self.llm_qwen_72b_url,
                "Qwen2.5-72B",
                LlmEndpointPurpose.REASONING,
                self.llm_qwen_72b_max_latency_ms,
                8,  # High priority: best for complex reasoning
            ),
            (
                self.llm_vision_url,
                "Qwen2-VL",
                LlmEndpointPurpose.VISION,
                self.llm_vision_max_latency_ms,
                9,  # High priority: only vision model
            ),
            (
                self.llm_deepseek_r1_url,
                "DeepSeek-R1-Distill",
                LlmEndpointPurpose.REASONING,
                self.llm_deepseek_r1_max_latency_ms,
                7,  # Medium-high: hot-swap with 72B
            ),
            (
                self.llm_qwen_14b_url,
                "Qwen2.5-14B",
                LlmEndpointPurpose.GENERAL,
                self.llm_qwen_14b_max_latency_ms,
                6,  # Medium: always available, balanced
            ),
        ]

        configs: list[LlmEndpointConfig] = []
        for url, model_name, purpose, max_latency, priority in endpoint_specs:
            if url is not None:
                configs.append(
                    LlmEndpointConfig(
                        url=url,
                        model_name=model_name,
                        purpose=purpose,
                        max_latency_ms=max_latency,
                        priority=priority,
                    )
                )
        return configs

    def get_all_endpoints(self) -> list[LlmEndpointConfig]:
        """Return all configured (available) endpoints.

        Returns:
            List of LlmEndpointConfig for every endpoint with a non-None URL.
        """
        return list(self._endpoint_configs)

    def get_endpoints_by_purpose(
        self, purpose: LlmEndpointPurpose
    ) -> list[LlmEndpointConfig]:
        """Return all endpoints matching the given purpose, sorted by priority descending.

        Args:
            purpose: The LlmEndpointPurpose to filter by.

        Returns:
            List of matching LlmEndpointConfig sorted by priority (highest first).
        """
        matching = [ep for ep in self._endpoint_configs if ep.purpose == purpose]
        return sorted(matching, key=lambda ep: ep.priority, reverse=True)

    def get_endpoint(self, purpose: LlmEndpointPurpose) -> LlmEndpointConfig | None:
        """Return the highest-priority endpoint for the given purpose.

        This is the primary lookup method used by Epic 1-4 to resolve which
        model serves a particular task type.

        Args:
            purpose: The LlmEndpointPurpose to look up.

        Returns:
            The highest-priority LlmEndpointConfig for the purpose, or None
            if no endpoint is configured for that purpose.
        """
        endpoints = self.get_endpoints_by_purpose(purpose)
        if not endpoints:
            logger.debug("No LLM endpoint configured for purpose=%s", purpose.value)
            return None
        return endpoints[0]
