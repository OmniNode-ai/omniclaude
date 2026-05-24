# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Tests for local LLM endpoint configuration registry.

Tests cover:
- LlmEndpointPurpose enum completeness
- LlmEndpointConfig construction and validation
- LocalLlmEndpointRegistry loading from environment variables
- Endpoint lookup by purpose with priority ordering
- Graceful handling of missing/invalid environment variables
- Latency budget validation
"""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any

import pytest
from pydantic import ValidationError

from omniclaude.config.model_local_llm_config import (
    LlmEndpointConfig,
    LlmEndpointPurpose,
    LocalLlmEndpointRegistry,
)


class TestLlmEndpointPurpose:
    """Tests for the LlmEndpointPurpose enum."""

    @pytest.mark.unit
    def test_all_purposes_defined(self) -> None:
        """All required purpose categories exist."""
        expected = {
            "ROUTING",
            "CODE_ANALYSIS",
            "EMBEDDING",
            "GENERAL",
            "VISION",
            "FUNCTION_CALLING",
            "REASONING",
            "GEMINI",
            "GLM",
            "OPENROUTER",
        }
        actual = {member.name for member in LlmEndpointPurpose}
        assert actual == expected

    @pytest.mark.unit
    def test_purpose_values_are_lowercase(self) -> None:
        """Purpose values are lowercase strings for serialization consistency."""
        for purpose in LlmEndpointPurpose:
            assert purpose.value == purpose.value.lower()

    @pytest.mark.unit
    def test_purpose_is_str_enum(self) -> None:
        """Purpose enum members are also strings (StrEnum)."""
        assert isinstance(LlmEndpointPurpose.ROUTING, str)
        assert LlmEndpointPurpose.ROUTING == "routing"


class TestLlmEndpointConfig:
    """Tests for the LlmEndpointConfig frozen model."""

    @pytest.mark.unit
    def test_valid_construction(self) -> None:
        """Config can be constructed with valid parameters."""
        config = LlmEndpointConfig(
            url="http://llm-coder-host:8000",
            model_name="Qwen2.5-Coder-14B",
            purpose=LlmEndpointPurpose.CODE_ANALYSIS,
            max_latency_ms=2000,
            priority=9,
        )
        assert str(config.url) == "http://llm-coder-host:8000/"
        assert config.model_name == "Qwen2.5-Coder-14B"
        assert config.purpose == LlmEndpointPurpose.CODE_ANALYSIS
        assert config.max_latency_ms == 2000
        assert config.priority == 9

    @pytest.mark.unit
    def test_defaults(self) -> None:
        """Default values are applied for max_latency_ms and priority."""
        config = LlmEndpointConfig(
            url="http://localhost:8000",
            model_name="test-model",
            purpose=LlmEndpointPurpose.GENERAL,
        )
        assert config.max_latency_ms == 5000
        assert config.priority == 5

    @pytest.mark.unit
    def test_frozen(self) -> None:
        """Config is immutable (frozen=True)."""
        config = LlmEndpointConfig(
            url="http://localhost:8000",
            model_name="test-model",
            purpose=LlmEndpointPurpose.GENERAL,
        )
        with pytest.raises(ValidationError):
            config.model_name = "other-model"  # type: ignore[misc]

    @pytest.mark.unit
    def test_invalid_url_rejected(self) -> None:
        """Invalid URLs are rejected at construction."""
        with pytest.raises(ValidationError, match="url"):
            LlmEndpointConfig(
                url="not-a-url",
                model_name="test",
                purpose=LlmEndpointPurpose.GENERAL,
            )

    @pytest.mark.unit
    def test_latency_below_minimum_rejected(self) -> None:
        """Latency below 100ms is rejected."""
        with pytest.raises(ValidationError, match="max_latency_ms"):
            LlmEndpointConfig(
                url="http://localhost:8000",
                model_name="test",
                purpose=LlmEndpointPurpose.GENERAL,
                max_latency_ms=50,
            )

    @pytest.mark.unit
    def test_latency_above_maximum_rejected(self) -> None:
        """Latency above 60000ms is rejected."""
        with pytest.raises(ValidationError, match="max_latency_ms"):
            LlmEndpointConfig(
                url="http://localhost:8000",
                model_name="test",
                purpose=LlmEndpointPurpose.GENERAL,
                max_latency_ms=70000,
            )

    @pytest.mark.unit
    def test_priority_below_minimum_rejected(self) -> None:
        """Priority below 1 is rejected."""
        with pytest.raises(ValidationError, match="priority"):
            LlmEndpointConfig(
                url="http://localhost:8000",
                model_name="test",
                purpose=LlmEndpointPurpose.GENERAL,
                priority=0,
            )

    @pytest.mark.unit
    def test_priority_above_maximum_rejected(self) -> None:
        """Priority above 10 is rejected."""
        with pytest.raises(ValidationError, match="priority"):
            LlmEndpointConfig(
                url="http://localhost:8000",
                model_name="test",
                purpose=LlmEndpointPurpose.GENERAL,
                priority=11,
            )

    @pytest.mark.unit
    def test_latency_boundary_values(self) -> None:
        """Boundary values for latency (100 and 60000) are accepted."""
        low = LlmEndpointConfig(
            url="http://localhost:8000",
            model_name="test",
            purpose=LlmEndpointPurpose.GENERAL,
            max_latency_ms=100,
        )
        high = LlmEndpointConfig(
            url="http://localhost:8000",
            model_name="test",
            purpose=LlmEndpointPurpose.GENERAL,
            max_latency_ms=60000,
        )
        assert low.max_latency_ms == 100
        assert high.max_latency_ms == 60000

    @pytest.mark.unit
    def test_empty_model_name_rejected(self) -> None:
        """Empty string model_name is rejected (min_length=1)."""
        with pytest.raises(ValidationError, match="model_name"):
            LlmEndpointConfig(
                url="http://localhost:8000",
                model_name="",
                purpose=LlmEndpointPurpose.GENERAL,
            )

    @pytest.mark.unit
    def test_priority_boundary_values(self) -> None:
        """Boundary values for priority (1 and 10) are accepted."""
        low = LlmEndpointConfig(
            url="http://localhost:8000",
            model_name="test",
            purpose=LlmEndpointPurpose.GENERAL,
            priority=1,
        )
        high = LlmEndpointConfig(
            url="http://localhost:8000",
            model_name="test",
            purpose=LlmEndpointPurpose.GENERAL,
            priority=10,
        )
        assert low.priority == 1
        assert high.priority == 10


class TestLocalLlmEndpointRegistry:
    """Tests for the LocalLlmEndpointRegistry settings loader."""

    @pytest.fixture
    def _clean_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Remove all LLM_* env vars to ensure clean test state."""
        for key in list(os.environ):
            if key.startswith("LLM_"):
                monkeypatch.delenv(key, raising=False)
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    @pytest.fixture
    def full_env(self, monkeypatch: pytest.MonkeyPatch, _clean_env: None) -> None:
        """Set all LLM endpoint env vars to known values."""
        monkeypatch.setenv("LLM_CODER_URL", "http://llm-coder-host:8000")
        monkeypatch.setenv("LLM_CODER_FAST_URL", "http://llm-fast-router-host:8004")
        monkeypatch.setenv("LLM_EMBEDDING_URL", "http://llm-embedding-host:8002")
        monkeypatch.setenv("LLM_FUNCTION_URL", "http://llm-fast-host:8001")
        monkeypatch.setenv("LLM_DEEPSEEK_LITE_URL", "http://llm-lite-host:8003")
        monkeypatch.setenv("LLM_QWEN_72B_URL", "http://llm-embedding-host:8100")
        monkeypatch.setenv("LLM_VISION_URL", "http://llm-vision-host:8102")
        monkeypatch.setenv("LLM_DEEPSEEK_R1_URL", "http://llm-reasoning-host:8101")
        monkeypatch.setenv("LLM_QWEN_14B_URL", "http://llm-mid-host:8200")
        monkeypatch.setenv("LLM_CODER_MODEL_NAME", "configured-coder")
        monkeypatch.setenv("LLM_CODER_FAST_MODEL_NAME", "configured-fast")
        monkeypatch.setenv("LLM_EMBEDDING_MODEL_NAME", "configured-embedding")
        monkeypatch.setenv("LLM_FUNCTION_MODEL_NAME", "configured-function")
        monkeypatch.setenv("LLM_DEEPSEEK_LITE_MODEL_NAME", "configured-lite")
        monkeypatch.setenv("LLM_QWEN_72B_MODEL_NAME", "configured-reasoning")
        monkeypatch.setenv("LLM_VISION_MODEL_NAME", "configured-vision")
        monkeypatch.setenv("LLM_DEEPSEEK_R1_MODEL_NAME", "configured-deepseek-r1")
        monkeypatch.setenv("LLM_QWEN_14B_MODEL_NAME", "configured-general")

    @pytest.fixture
    def partial_env(self, monkeypatch: pytest.MonkeyPatch, _clean_env: None) -> None:
        """Set only always-running endpoints (no hot-swap)."""
        monkeypatch.setenv("LLM_CODER_URL", "http://llm-coder-host:8000")
        monkeypatch.setenv("LLM_EMBEDDING_URL", "http://llm-embedding-host:8002")
        monkeypatch.setenv("LLM_QWEN_72B_URL", "http://llm-embedding-host:8100")
        monkeypatch.setenv("LLM_VISION_URL", "http://llm-vision-host:8102")
        monkeypatch.setenv("LLM_QWEN_14B_URL", "http://llm-mid-host:8200")
        monkeypatch.setenv("LLM_CODER_MODEL_NAME", "configured-coder")
        monkeypatch.setenv("LLM_EMBEDDING_MODEL_NAME", "configured-embedding")
        monkeypatch.setenv("LLM_QWEN_72B_MODEL_NAME", "configured-reasoning")
        monkeypatch.setenv("LLM_VISION_MODEL_NAME", "configured-vision")
        monkeypatch.setenv("LLM_QWEN_14B_MODEL_NAME", "configured-general")

    @pytest.fixture
    def make_registry(self) -> Callable[..., LocalLlmEndpointRegistry]:
        """Factory fixture for creating test registries without .env file loading."""

        def _make(**kwargs: Any) -> LocalLlmEndpointRegistry:
            kwargs.setdefault("_env_file", None)
            return LocalLlmEndpointRegistry(**kwargs)  # type: ignore[call-arg]

        return _make

    @pytest.mark.unit
    def test_empty_env_returns_empty_registry(
        self, _clean_env: None, make_registry: Callable[..., LocalLlmEndpointRegistry]
    ) -> None:
        """Missing env vars produce an empty registry, not an error."""
        registry = make_registry()
        assert registry.get_all_endpoints() == []

    @pytest.mark.unit
    def test_full_env_loads_all_endpoints(
        self, full_env: None, make_registry: Callable[..., LocalLlmEndpointRegistry]
    ) -> None:
        """All 9 endpoints are loaded when all env vars are set."""
        registry = make_registry()
        endpoints = registry.get_all_endpoints()
        assert len(endpoints) == 9

    @pytest.mark.unit
    def test_partial_env_loads_available_endpoints(
        self, partial_env: None, make_registry: Callable[..., LocalLlmEndpointRegistry]
    ) -> None:
        """Only endpoints with set env vars are loaded."""
        registry = make_registry()
        endpoints = registry.get_all_endpoints()
        assert len(endpoints) == 5
        model_names = {ep.model_name for ep in endpoints}
        assert "configured-coder" in model_names
        assert "configured-embedding" in model_names
        assert "configured-reasoning" in model_names
        assert "configured-vision" in model_names
        assert "configured-general" in model_names
        # Hot-swap models should not be present
        assert "configured-function" not in model_names
        assert "configured-lite" not in model_names
        assert "configured-deepseek-r1" not in model_names

    @pytest.mark.unit
    def test_get_all_endpoints_returns_defensive_copy(
        self, full_env: None, make_registry: Callable[..., LocalLlmEndpointRegistry]
    ) -> None:
        """get_all_endpoints returns a new list each call (defensive copy)."""
        registry = make_registry()
        first = registry.get_all_endpoints()
        second = registry.get_all_endpoints()
        assert first == second
        assert first is not second

    @pytest.mark.unit
    def test_get_endpoint_returns_best_for_purpose(
        self, full_env: None, make_registry: Callable[..., LocalLlmEndpointRegistry]
    ) -> None:
        """get_endpoint returns the highest-priority endpoint for a purpose."""
        registry = make_registry()
        endpoint = registry.get_endpoint(LlmEndpointPurpose.CODE_ANALYSIS)
        assert endpoint is not None
        assert endpoint.model_name == "configured-coder"
        assert endpoint.priority == 9

    @pytest.mark.unit
    def test_get_endpoint_returns_none_for_missing_purpose(
        self, _clean_env: None, make_registry: Callable[..., LocalLlmEndpointRegistry]
    ) -> None:
        """get_endpoint returns None when no endpoint serves the purpose."""
        registry = make_registry()
        assert registry.get_endpoint(LlmEndpointPurpose.VISION) is None

    @pytest.mark.unit
    def test_get_endpoint_routing_not_configured(
        self, full_env: None, make_registry: Callable[..., LocalLlmEndpointRegistry]
    ) -> None:
        """ROUTING purpose uses explicitly configured endpoint/model pairs."""
        registry = make_registry()
        endpoint = registry.get_endpoint(LlmEndpointPurpose.ROUTING)
        assert endpoint is not None
        assert endpoint.model_name == "configured-fast"

    @pytest.mark.unit
    def test_get_endpoints_by_purpose_sorted_by_priority(
        self, full_env: None, make_registry: Callable[..., LocalLlmEndpointRegistry]
    ) -> None:
        """Multiple endpoints for same purpose are sorted by priority descending."""
        registry = make_registry()
        reasoning_endpoints = registry.get_endpoints_by_purpose(
            LlmEndpointPurpose.REASONING
        )
        assert len(reasoning_endpoints) == 2
        assert reasoning_endpoints[0].priority >= reasoning_endpoints[1].priority
        assert reasoning_endpoints[0].model_name == "configured-reasoning"
        assert reasoning_endpoints[1].model_name == "configured-deepseek-r1"

    @pytest.mark.unit
    def test_get_endpoints_by_purpose_general(
        self, full_env: None, make_registry: Callable[..., LocalLlmEndpointRegistry]
    ) -> None:
        """GENERAL purpose returns explicitly configured general endpoints."""
        registry = make_registry()
        general_endpoints = registry.get_endpoints_by_purpose(
            LlmEndpointPurpose.GENERAL
        )
        assert len(general_endpoints) == 2
        assert general_endpoints[0].model_name == "configured-general"
        assert general_endpoints[1].model_name == "configured-lite"

    @pytest.mark.unit
    def test_get_endpoints_by_purpose_empty(
        self, _clean_env: None, make_registry: Callable[..., LocalLlmEndpointRegistry]
    ) -> None:
        """Empty purpose list when no endpoints configured."""
        registry = make_registry()
        assert registry.get_endpoints_by_purpose(LlmEndpointPurpose.VISION) == []

    @pytest.mark.unit
    def test_invalid_url_env_var_rejected(
        self,
        monkeypatch: pytest.MonkeyPatch,
        _clean_env: None,
        make_registry: Callable[..., LocalLlmEndpointRegistry],
    ) -> None:
        """Invalid URL in env var causes validation error."""
        monkeypatch.setenv("LLM_CODER_URL", "not-a-valid-url")
        monkeypatch.setenv("LLM_CODER_MODEL_NAME", "configured-coder")
        with pytest.raises(ValidationError):
            make_registry()

    @pytest.mark.unit
    def test_custom_latency_budget_from_env(
        self,
        monkeypatch: pytest.MonkeyPatch,
        _clean_env: None,
        make_registry: Callable[..., LocalLlmEndpointRegistry],
    ) -> None:
        """Latency budgets can be overridden via environment variables."""
        monkeypatch.setenv("LLM_CODER_URL", "http://llm-coder-host:8000")
        monkeypatch.setenv("LLM_CODER_MODEL_NAME", "configured-coder")
        monkeypatch.setenv("LLM_CODER_MAX_LATENCY_MS", "500")
        registry = make_registry()
        endpoint = registry.get_endpoint(LlmEndpointPurpose.CODE_ANALYSIS)
        assert endpoint is not None
        assert endpoint.max_latency_ms == 500

    @pytest.mark.unit
    def test_endpoint_urls_preserved(
        self, full_env: None, make_registry: Callable[..., LocalLlmEndpointRegistry]
    ) -> None:
        """Endpoint URLs match the environment variable values."""
        registry = make_registry()
        endpoint = registry.get_endpoint(LlmEndpointPurpose.EMBEDDING)
        assert endpoint is not None
        assert "llm-embedding-host" in str(endpoint.url)
        assert "8002" in str(endpoint.url)

    @pytest.mark.unit
    def test_vision_endpoint(
        self, full_env: None, make_registry: Callable[..., LocalLlmEndpointRegistry]
    ) -> None:
        """Vision endpoint is correctly mapped."""
        registry = make_registry()
        endpoint = registry.get_endpoint(LlmEndpointPurpose.VISION)
        assert endpoint is not None
        assert endpoint.model_name == "configured-vision"
        assert "8102" in str(endpoint.url)

    @pytest.mark.unit
    def test_function_calling_endpoint(
        self, full_env: None, make_registry: Callable[..., LocalLlmEndpointRegistry]
    ) -> None:
        """Function calling endpoint is correctly mapped."""
        registry = make_registry()
        endpoint = registry.get_endpoint(LlmEndpointPurpose.FUNCTION_CALLING)
        assert endpoint is not None
        assert endpoint.model_name == "configured-function"

    @pytest.mark.unit
    def test_extra_env_vars_ignored(
        self,
        monkeypatch: pytest.MonkeyPatch,
        _clean_env: None,
        make_registry: Callable[..., LocalLlmEndpointRegistry],
    ) -> None:
        """Unknown env vars are ignored (extra='ignore')."""
        monkeypatch.setenv("LLM_CODER_URL", "http://localhost:8000")
        monkeypatch.setenv("LLM_CODER_MODEL_NAME", "configured-coder")
        monkeypatch.setenv("LLM_UNKNOWN_THING", "http://localhost:9999")
        # Should not raise
        registry = make_registry()
        assert len(registry.get_all_endpoints()) == 1

    @pytest.mark.unit
    @pytest.mark.parametrize(
        "field_env_var",
        [
            "LLM_CODER_MODEL_NAME",
            "LLM_CODER_FAST_MODEL_NAME",
            "LLM_EMBEDDING_MODEL_NAME",
            "LLM_FUNCTION_MODEL_NAME",
            "LLM_DEEPSEEK_LITE_MODEL_NAME",
            "LLM_QWEN_72B_MODEL_NAME",
            "LLM_VISION_MODEL_NAME",
            "LLM_DEEPSEEK_R1_MODEL_NAME",
            "LLM_QWEN_14B_MODEL_NAME",
            "LLM_OPENROUTER_MODEL_NAME",
        ],
    )
    def test_whitespace_only_model_name_rejected(
        self,
        monkeypatch: pytest.MonkeyPatch,
        _clean_env: None,
        make_registry: Callable[..., LocalLlmEndpointRegistry],
        field_env_var: str,
    ) -> None:
        """Whitespace-only model names are rejected at validation time."""
        monkeypatch.setenv(field_env_var, "   ")
        with pytest.raises(ValidationError, match="whitespace"):
            make_registry()

    @pytest.mark.unit
    @pytest.mark.parametrize(
        "field_env_var",
        [
            "LLM_CODER_MODEL_NAME",
            "LLM_CODER_FAST_MODEL_NAME",
            "LLM_EMBEDDING_MODEL_NAME",
        ],
    )
    def test_tabs_only_model_name_rejected(
        self,
        monkeypatch: pytest.MonkeyPatch,
        _clean_env: None,
        make_registry: Callable[..., LocalLlmEndpointRegistry],
        field_env_var: str,
    ) -> None:
        """Tab-only model names are also rejected (tabs are whitespace)."""
        monkeypatch.setenv(field_env_var, "\t\t")
        with pytest.raises(ValidationError, match="whitespace"):
            make_registry()

    @pytest.mark.unit
    def test_valid_model_name_with_spaces_accepted(
        self,
        monkeypatch: pytest.MonkeyPatch,
        _clean_env: None,
        make_registry: Callable[..., LocalLlmEndpointRegistry],
    ) -> None:
        """A model name with interior spaces (but non-empty when stripped) is accepted."""
        monkeypatch.setenv("LLM_CODER_MODEL_NAME", "my model v2")
        registry = make_registry()
        assert registry.llm_coder_model_name == "my model v2"

    @pytest.mark.unit
    def test_openrouter_endpoint_requires_api_key(
        self,
        _clean_env: None,
        make_registry: Callable[..., LocalLlmEndpointRegistry],
    ) -> None:
        """OpenRouter is unavailable until keyed and explicitly routed."""
        registry = make_registry()
        assert registry.get_endpoint(LlmEndpointPurpose.OPENROUTER) is None

    @pytest.mark.unit
    def test_openrouter_endpoint_requires_explicit_route_config(
        self,
        monkeypatch: pytest.MonkeyPatch,
        _clean_env: None,
        make_registry: Callable[..., LocalLlmEndpointRegistry],
    ) -> None:
        """OPENROUTER_API_KEY alone must not create a hidden route default."""
        monkeypatch.setenv("OPENROUTER_API_KEY", "test-openrouter-key")
        registry = make_registry()

        with pytest.raises(RuntimeError, match="LLM_OPENROUTER_URL"):
            registry.get_endpoint(LlmEndpointPurpose.OPENROUTER)

    @pytest.mark.unit
    def test_openrouter_endpoint_uses_explicit_route_config(
        self,
        monkeypatch: pytest.MonkeyPatch,
        _clean_env: None,
        make_registry: Callable[..., LocalLlmEndpointRegistry],
    ) -> None:
        """OPENROUTER_API_KEY uses explicitly supplied URL and model."""
        monkeypatch.setenv("OPENROUTER_API_KEY", "test-openrouter-key")
        monkeypatch.setenv("LLM_OPENROUTER_URL", "https://openrouter.example.com/api")
        monkeypatch.setenv("LLM_OPENROUTER_MODEL_NAME", "configured-openrouter")
        registry = make_registry()

        endpoint = registry.get_endpoint(LlmEndpointPurpose.OPENROUTER)

        assert endpoint is not None
        assert str(endpoint.url) == "https://openrouter.example.com/api"
        assert endpoint.model_name == "configured-openrouter"
        assert endpoint.api_key == "test-openrouter-key"
        assert endpoint.chat_completions_path == "/chat/completions"
        assert endpoint.priority == 10
