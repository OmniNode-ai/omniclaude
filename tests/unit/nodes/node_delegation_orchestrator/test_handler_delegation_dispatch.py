# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for delegation backend selection."""

from __future__ import annotations

import pytest

from omniclaude.config.model_local_llm_config import LocalLlmEndpointRegistry
from omniclaude.nodes.node_delegation_orchestrator.handlers.handler_delegation_dispatch import (
    select_backend,
)


@pytest.fixture
def clean_backend_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep backend selection tests isolated from developer shell config."""
    for key in (
        "OPENROUTER_API_KEY",
        "LLM_OPENROUTER_URL",
        "LLM_OPENROUTER_MODEL_NAME",
        "LLM_OPENROUTER_MAX_LATENCY_MS",
        "LLM_CODER_URL",
        "LLM_CODER_MODEL_NAME",
        "LLM_CODER_FAST_URL",
        "LLM_CODER_FAST_MODEL_NAME",
        "LLM_EMBEDDING_URL",
        "LLM_EMBEDDING_MODEL_NAME",
        "LLM_FUNCTION_URL",
        "LLM_FUNCTION_MODEL_NAME",
        "LLM_DEEPSEEK_LITE_URL",
        "LLM_DEEPSEEK_LITE_MODEL_NAME",
        "LLM_QWEN_72B_URL",
        "LLM_QWEN_72B_MODEL_NAME",
        "LLM_VISION_URL",
        "LLM_VISION_MODEL_NAME",
        "LLM_DEEPSEEK_R1_URL",
        "LLM_DEEPSEEK_R1_MODEL_NAME",
        "LLM_QWEN_14B_URL",
        "LLM_QWEN_14B_MODEL_NAME",
        "LLM_GEMINI_URL",
        "LLM_GEMINI_API_KEY",
        "LLM_GEMINI_MODEL_NAME",
        "LLM_GLM_URL",
        "LLM_GLM_API_KEY",
        "LLM_GLM_MODEL_NAME",
        "DELEGATION_DISABLE_FRONTIER_ROUTING",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("PATH", "")


def _registry() -> LocalLlmEndpointRegistry:
    return LocalLlmEndpointRegistry(_env_file=None)  # type: ignore[call-arg]


@pytest.mark.unit
def test_openrouter_is_primary_when_keyed(
    monkeypatch: pytest.MonkeyPatch,
    clean_backend_env: None,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-openrouter-key")
    monkeypatch.setenv("LLM_OPENROUTER_URL", "https://openrouter.ai/api/v1")
    monkeypatch.setenv("LLM_OPENROUTER_MODEL_NAME", "z-ai/glm-4.7-flash")
    monkeypatch.setenv("LLM_CODER_URL", "http://llm-coder-host:8000")
    monkeypatch.setenv("LLM_CODER_MODEL_NAME", "Qwen3-Coder-30B-A3B-Instruct")

    route = select_backend(_registry())

    assert route is not None
    assert route.backend == "openrouter"
    assert route.base_url == "https://openrouter.ai/api/v1"
    assert route.model == "z-ai/glm-4.7-flash"
    assert route.api_key == "test-openrouter-key"
    assert route.timeout == 60


@pytest.mark.unit
def test_openrouter_without_key_falls_back_to_local_qwen(
    monkeypatch: pytest.MonkeyPatch,
    clean_backend_env: None,
) -> None:
    monkeypatch.setenv("LLM_CODER_URL", "http://llm-coder-host:8000")
    monkeypatch.setenv("LLM_CODER_MODEL_NAME", "Qwen3-Coder-30B-A3B-Instruct")

    route = select_backend(_registry())

    assert route is not None
    assert route.backend == "local_vllm"
    assert route.base_url == "http://llm-coder-host:8000"
    assert route.model == "Qwen3-Coder-30B-A3B-Instruct"
    assert route.api_key is None


@pytest.mark.unit
def test_local_qwen_coder_precedes_fast_routing_model(
    monkeypatch: pytest.MonkeyPatch,
    clean_backend_env: None,
) -> None:
    monkeypatch.setenv("LLM_CODER_URL", "http://llm-coder-host:8000")
    monkeypatch.setenv("LLM_CODER_MODEL_NAME", "Qwen3-Coder-30B-A3B-Instruct")
    monkeypatch.setenv("LLM_CODER_FAST_URL", "http://llm-fast-host:8001")
    monkeypatch.setenv("LLM_CODER_FAST_MODEL_NAME", "Qwen3-14B-Instruct-AWQ")

    route = select_backend(_registry())

    assert route is not None
    assert route.backend == "local_vllm"
    assert route.base_url == "http://llm-coder-host:8000"
    assert route.model == "Qwen3-Coder-30B-A3B-Instruct"


@pytest.mark.unit
def test_direct_glm_uses_typed_registry_after_cli_fallbacks(
    monkeypatch: pytest.MonkeyPatch,
    clean_backend_env: None,
) -> None:
    monkeypatch.setenv("LLM_GLM_URL", "https://open.bigmodel.cn/api/paas/v4")
    monkeypatch.setenv("LLM_GLM_API_KEY", "test-glm-key")
    monkeypatch.setenv("LLM_GLM_MODEL_NAME", "glm-4-plus")

    route = select_backend(_registry())

    assert route is not None
    assert route.backend == "glm"
    assert route.base_url == "https://open.bigmodel.cn/api/paas/v4"
    assert route.model == "glm-4-plus"
    assert route.api_key == "test-glm-key"
